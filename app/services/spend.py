"""Record what was paid, and total it without treating a blank week as £0."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    PlannerEntry,
    PlannerWeek,
    ShoppingList,
    ShoppingListLine,
    ShoppingTransaction,
    ShoppingTransactionLine,
)
from app.services.parsing import (
    FieldValidationError,
    InvalidPriceError,
    parse_gbp_to_pence,
    parse_recipe_quantity,
)
from app.services.planner import format_week_range, shift_week, week_start_for
from app.services.shopping import SHOPPED, shopping_totals
from app.services.units import InvalidQuantityError

STATUS_ACTUAL = "actual"
STATUS_ESTIMATED = "estimated"
STATUS_INCOMPLETE = "incomplete"

_STATUS_LABEL = {
    STATUS_ACTUAL: "Actual",
    STATUS_ESTIMATED: "Estimated",
    STATUS_INCOMPLETE: "Incomplete",
}
_NOTE_LIMIT = 500
_MAX_WEEKS = 52


class SpendFormError(Exception):
    """The spend form failed validation. Nothing was saved."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__("Spend form is invalid.")


class LineAdjustment:
    """Optional actual quantity and price for one shopping-list row."""

    def __init__(
        self,
        list_line_id: int,
        quantity: Decimal | None,
        price_pence: int | None,
        notes: str | None,
    ) -> None:
        self.list_line_id = list_line_id
        self.quantity = quantity
        self.price_pence = price_pence
        self.notes = notes


class WeekSpend:
    """One week's grocery, estimate, and takeaway, kept as separate figures."""

    def __init__(
        self,
        week_start: date,
        label: str,
        grocery_pence: int | None,
        estimated_pence: int | None,
        estimate_complete: bool,
        takeaway_pence: int,
        status: str,
    ) -> None:
        self.week_start = week_start
        self.label = label
        self.grocery_pence = grocery_pence
        self.estimated_pence = estimated_pence
        self.estimate_complete = estimate_complete
        self.takeaway_pence = takeaway_pence
        self.status = status

    @property
    def status_label(self) -> str:
        return _STATUS_LABEL[self.status]

    @property
    def combined_pence(self) -> int | None:
        """A finished total only. Incomplete weeks stay blank."""
        if self.status == STATUS_ACTUAL and self.grocery_pence is not None:
            return self.grocery_pence + self.takeaway_pence
        if self.status == STATUS_ESTIMATED and self.estimated_pence is not None:
            return self.estimated_pence + self.takeaway_pence
        return None


class SpendReport:
    """Several weeks, with unrecorded grocery left out of the sums."""

    def __init__(self, weeks: tuple[WeekSpend, ...]) -> None:
        recorded = [
            week.grocery_pence for week in weeks if week.grocery_pence is not None
        ]
        grocery = sum(recorded)
        self.weeks = weeks
        self.grocery_recorded_pence = grocery
        self.recorded_week_count = len(recorded)
        self.grocery_average_pence = _average(grocery, len(recorded))
        self.takeaway_pence = sum(week.takeaway_pence for week in weeks)
        self.combined_recorded_pence = grocery + self.takeaway_pence
        self.unrecorded_week_count = sum(
            1 for week in weeks if week.grocery_pence is None
        )

    def chart_payload(self) -> dict[str, list[object]]:
        """Pence series for the chart. Unrecorded grocery stays null, not 0."""
        return {
            "labels": [week.label for week in self.weeks],
            "grocery": [week.grocery_pence for week in self.weeks],
            "takeaway": [week.takeaway_pence for week in self.weeks],
            "estimated": [week.estimated_pence for week in self.weeks],
        }


def record_spend_from_form(
    session: Session,
    shopping_list: ShoppingList,
    values: dict[str, str],
) -> ShoppingTransaction:
    """Save a shop from form text. A blank total is an error, not the estimate."""
    errors: dict[str, str] = {}
    total = _parse_total(values.get("total", ""), errors)
    spent_on = _parse_spent_on(values.get("spent_on", ""), errors)
    notes = _parse_notes(values.get("notes", ""), "notes", errors)
    adjustments = _parse_lines(shopping_list, values, errors)
    if errors or total is None or spent_on is None:
        raise SpendFormError(errors)
    return record_spend(
        session,
        shopping_list=shopping_list,
        spent_on=spent_on,
        actual_total_pence=total,
        notes=notes,
        lines=adjustments,
    )


def record_spend(
    session: Session,
    *,
    shopping_list: ShoppingList,
    spent_on: date,
    actual_total_pence: int,
    notes: str | None,
    lines: list[LineAdjustment],
) -> ShoppingTransaction:
    """Store one shop against the list's week. Another shop can follow it."""
    total = _require_pence(actual_total_pence)
    transaction = ShoppingTransaction(
        planner_week_id=shopping_list.planner_week_id,
        shopping_list_id=shopping_list.id,
        spent_on=spent_on,
        actual_total_pence=total,
        notes=notes,
    )
    session.add(transaction)
    for adjustment in lines:
        source = _active_line(shopping_list, adjustment.list_line_id)
        transaction.lines.append(
            ShoppingTransactionLine(
                list_line_id=source.id,
                description=source.description,
                actual_quantity=_optional_quantity(adjustment.quantity),
                unit_snapshot=source.unit_snapshot,
                actual_price_pence=_optional_pence(adjustment.price_pence),
                notes=adjustment.notes,
            )
        )
    shopping_list.status = SHOPPED
    session.flush()
    return transaction


def transactions_for_list(
    session: Session, shopping_list_id: int
) -> list[ShoppingTransaction]:
    """Shops recorded against one list, oldest first."""
    return list(
        session.scalars(
            select(ShoppingTransaction)
            .where(ShoppingTransaction.shopping_list_id == shopping_list_id)
            .options(selectinload(ShoppingTransaction.lines))
            .order_by(ShoppingTransaction.spent_on, ShoppingTransaction.id)
        )
    )


def spend_report(session: Session, *, end: date, week_count: int) -> SpendReport:
    """Weekly grocery, estimate, and takeaway for the weeks up to `end`."""
    if week_count < 1 or week_count > _MAX_WEEKS:
        raise FieldValidationError("weeks", "Choose between 1 and 52 weeks.")
    mondays = _mondays(end, week_count)
    weeks_by_start = _weeks_by_start(session, mondays)
    week_ids = [week.id for week in weeks_by_start.values()]
    transactions = _transactions_by_week(session, week_ids)
    lists = _lists_by_week(session, week_ids)
    takeaway = _takeaway_by_week(session, mondays[0], mondays[-1])
    built = tuple(
        _week_spend(
            monday,
            transactions.get(weeks_by_start[monday].id, [])
            if monday in weeks_by_start
            else [],
            lists.get(weeks_by_start[monday].id) if monday in weeks_by_start else None,
            takeaway.get(monday, 0),
        )
        for monday in mondays
    )
    return SpendReport(built)


def _mondays(end: date, week_count: int) -> list[date]:
    last = week_start_for(end)
    first = shift_week(last, 1 - week_count)
    return [shift_week(first, index) for index in range(week_count)]


def _weeks_by_start(session: Session, mondays: list[date]) -> dict[date, PlannerWeek]:
    rows = session.scalars(
        select(PlannerWeek).where(PlannerWeek.week_start_date.in_(mondays))
    ).all()
    return {row.week_start_date: row for row in rows}


def _transactions_by_week(
    session: Session, week_ids: list[int]
) -> dict[int, list[ShoppingTransaction]]:
    grouped: dict[int, list[ShoppingTransaction]] = defaultdict(list)
    if not week_ids:
        return grouped
    rows = session.scalars(
        select(ShoppingTransaction).where(
            ShoppingTransaction.planner_week_id.in_(week_ids)
        )
    ).all()
    for row in rows:
        grouped[row.planner_week_id].append(row)
    return grouped


def _lists_by_week(session: Session, week_ids: list[int]) -> dict[int, ShoppingList]:
    if not week_ids:
        return {}
    rows = session.scalars(
        select(ShoppingList)
        .where(ShoppingList.planner_week_id.in_(week_ids))
        .options(selectinload(ShoppingList.lines))
    ).all()
    return {row.planner_week_id: row for row in rows}


def _takeaway_by_week(
    session: Session, first_monday: date, last_monday: date
) -> dict[date, int]:
    last_sunday = last_monday + timedelta(days=6)
    entries = session.scalars(
        select(PlannerEntry).where(
            PlannerEntry.plan_date >= first_monday,
            PlannerEntry.plan_date <= last_sunday,
            PlannerEntry.entry_type == "takeaway",
        )
    ).all()
    totals: dict[date, int] = defaultdict(int)
    for entry in entries:
        if entry.takeaway_price_pence is None:
            continue
        totals[week_start_for(entry.plan_date)] += entry.takeaway_price_pence
    return totals


def _week_spend(
    monday: date,
    transactions: list[ShoppingTransaction],
    shopping_list: ShoppingList | None,
    takeaway_pence: int,
) -> WeekSpend:
    grocery = (
        sum(row.actual_total_pence for row in transactions) if transactions else None
    )
    estimated: int | None = None
    complete = False
    if shopping_list is not None:
        totals = shopping_totals(shopping_list)
        estimated = totals.outlay_pence
        complete = totals.is_complete
    return WeekSpend(
        week_start=monday,
        label=format_week_range(monday),
        grocery_pence=grocery,
        estimated_pence=estimated,
        estimate_complete=complete,
        takeaway_pence=takeaway_pence,
        status=_status(transactions, shopping_list, complete),
    )


def _status(
    transactions: list[ShoppingTransaction],
    shopping_list: ShoppingList | None,
    estimate_complete: bool,
) -> str:
    if transactions:
        return STATUS_ACTUAL
    if shopping_list is not None and estimate_complete:
        return STATUS_ESTIMATED
    return STATUS_INCOMPLETE


def _parse_total(raw: str, errors: dict[str, str]) -> int | None:
    if not raw.strip():
        errors["total"] = "Enter the amount you paid, such as 12.50."
        return None
    try:
        return parse_gbp_to_pence(raw)
    except InvalidPriceError as exc:
        errors["total"] = str(exc)
        return None


def _parse_spent_on(raw: str, errors: dict[str, str]) -> date | None:
    text = raw.strip()
    if not text:
        errors["spent_on"] = "Choose the date you shopped."
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        errors["spent_on"] = "Choose a valid date."
        return None


def _parse_notes(raw: str, field: str, errors: dict[str, str]) -> str | None:
    text = " ".join(raw.split())
    if not text:
        return None
    if len(text) > _NOTE_LIMIT:
        errors[field] = "Notes must be 500 characters or fewer."
        return None
    return text


def _parse_lines(
    shopping_list: ShoppingList,
    values: dict[str, str],
    errors: dict[str, str],
) -> list[LineAdjustment]:
    adjustments: list[LineAdjustment] = []
    for line in shopping_list.lines:
        if line.removed:
            continue
        quantity_text = values.get(f"qty-{line.id}", "")
        price_text = values.get(f"price-{line.id}", "")
        notes_text = values.get(f"line-notes-{line.id}", "")
        blank = (
            not quantity_text.strip()
            and not price_text.strip()
            and not notes_text.strip()
        )
        if blank:
            continue
        quantity = _parse_line_quantity(line, quantity_text, errors)
        price = _parse_line_price(line.id, price_text, errors)
        notes = _parse_notes(notes_text, f"line-notes-{line.id}", errors)
        if f"qty-{line.id}" in errors or f"price-{line.id}" in errors:
            continue
        if f"line-notes-{line.id}" in errors:
            continue
        adjustments.append(
            LineAdjustment(
                list_line_id=line.id,
                quantity=quantity,
                price_pence=price,
                notes=notes,
            )
        )
    return adjustments


def _parse_line_quantity(
    line: ShoppingListLine, raw: str, errors: dict[str, str]
) -> Decimal | None:
    if not raw.strip():
        return None
    symbol = line.unit_snapshot or "units"
    try:
        return parse_recipe_quantity(raw, unit_symbol=symbol)
    except InvalidQuantityError as exc:
        errors[f"qty-{line.id}"] = str(exc)
        return None


def _parse_line_price(line_id: int, raw: str, errors: dict[str, str]) -> int | None:
    if not raw.strip():
        return None
    try:
        return parse_gbp_to_pence(raw)
    except InvalidPriceError as exc:
        errors[f"price-{line_id}"] = str(exc)
        return None


def _active_line(shopping_list: ShoppingList, line_id: int) -> ShoppingListLine:
    for line in shopping_list.lines:
        if line.id == line_id and not line.removed:
            return line
    raise FieldValidationError("line", "That item is not on this list.")


def _require_pence(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Money must be integer pence.")
    if value < 0:
        raise FieldValidationError(
            "total",
            "Price cannot be negative. Enter 0 or a positive amount such as 1.79.",
        )
    return value


def _optional_pence(value: int | None) -> int | None:
    if value is None:
        return None
    return _require_pence(value)


def _optional_quantity(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, float) or not isinstance(value, Decimal):
        raise TypeError("Quantities must be Decimal, not float.")
    if value < 0:
        raise FieldValidationError("quantity", "Quantity cannot be negative.")
    return value


def _average(total: int, count: int) -> int | None:
    if count <= 0:
        return None
    rounded = (Decimal(total) / Decimal(count)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(rounded)
