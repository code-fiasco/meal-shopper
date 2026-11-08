"""Weekly lunch and dinner plans. Takeaway spend stays out of meal cost."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Ingredient, Meal, RecipeIngredient
from app.models.planner import PlannerEntry, PlannerWeek
from app.models.types import utcnow
from app.services.costing import MealCost
from app.services.meals import MealSummary, cost_meal, get_meal, list_meals
from app.services.parsing import (
    FieldValidationError,
    InvalidPriceError,
    parse_gbp_to_pence,
)

LUNCH = "lunch"
DINNER = "dinner"
SLOTS = (LUNCH, DINNER)
MEAL = "meal"
TAKEAWAY = "takeaway"
BLANK = "blank"
WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_SLOT_ORDER = {LUNCH: 0, DINNER: 1}


@dataclass(frozen=True)
class IngredientNeed:
    """Recipe quantity a planned meal still asks for. Takeaway slots add none."""

    ingredient_id: int
    ingredient_name: str
    quantity: Decimal
    unit_symbol: str


@dataclass(frozen=True)
class WeekCost:
    """Ingredient estimate and takeaway spend for one week, kept apart."""

    meal_total_pence: int
    meal_is_complete: bool
    missing_ingredients: tuple[str, ...]
    meal_count: int
    takeaway_total_pence: int
    takeaway_count: int

    def incomplete_label(self) -> str | None:
        """Missing prices stay named. They are never folded in as £0."""
        if self.meal_is_complete:
            return None
        names = ", ".join(self.missing_ingredients)
        return f"incomplete: missing price for {names}"


@dataclass
class SlotView:
    """One slot as the week page renders it."""

    plan_date: date
    slot: str
    entry: PlannerEntry | None
    cost: MealCost | None
    mode: str = "saved"
    errors: dict[str, str] = field(default_factory=dict)
    draft_price: str = ""
    draft_description: str = ""
    meals: list[MealSummary] = field(default_factory=list)
    search_query: str = ""

    @property
    def dom_id(self) -> str:
        return f"slot-{self.plan_date.isoformat()}-{self.slot}"

    @property
    def slot_label(self) -> str:
        return "Lunch" if self.slot == LUNCH else "Dinner"


@dataclass
class DayView:
    plan_date: date
    weekday: str
    date_label: str
    lunch: SlotView
    dinner: SlotView


@dataclass
class WeekView:
    start: date
    end: date
    label: str
    previous: date
    following: date
    days: list[DayView]
    costs: WeekCost
    is_current: bool


def local_today(timezone_name: str, now: datetime | None = None) -> date:
    """Calendar date in the configured timezone."""
    moment = now if now is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(ZoneInfo(timezone_name)).date()


def week_start_for(day: date) -> date:
    """Monday of the week that contains this date."""
    if isinstance(day, datetime):
        day = day.date()
    return day - timedelta(days=day.weekday())


def shift_week(start: date, weeks: int) -> date:
    """Move a Monday by a number of weeks."""
    return week_start_for(start) + timedelta(days=7 * weeks)


def format_week_range(start: date) -> str:
    """Human week range, for example 2–8 Nov 2026."""
    monday = week_start_for(start)
    end = monday + timedelta(days=6)
    if monday.year != end.year:
        return f"{_day_month(monday)} {monday.year} – {_day_month(end)} {end.year}"
    if monday.month != end.month:
        return f"{_day_month(monday)} – {_day_month(end)} {end.year}"
    return f"{monday.day}–{end.day} {_month(end)} {end.year}"


def format_day(day: date) -> str:
    """Weekday and date, for example Monday 2 Nov."""
    return f"{WEEKDAYS[day.weekday()]} {_day_month(day)}"


def get_week(session: Session, day: date) -> PlannerWeek | None:
    """Return the stored week, or nothing when nobody has edited it yet."""
    monday = week_start_for(day)
    return session.scalar(
        select(PlannerWeek).where(PlannerWeek.week_start_date == monday)
    )


def ensure_week(session: Session, day: date) -> PlannerWeek:
    """Create the Monday week the first time one of its slots is saved."""
    existing = get_week(session, day)
    if existing is not None:
        return existing
    week = PlannerWeek(week_start_date=week_start_for(day), status="open")
    session.add(week)
    session.flush()
    return week


def entries_for_week(session: Session, day: date) -> list[PlannerEntry]:
    """Slots saved in the Monday–Sunday week that contains this date."""
    start = week_start_for(day)
    end = start + timedelta(days=6)
    statement = (
        select(PlannerEntry)
        .where(PlannerEntry.plan_date >= start, PlannerEntry.plan_date <= end)
        .options(*_meal_options())
        .order_by(PlannerEntry.plan_date, PlannerEntry.slot)
    )
    return list(session.scalars(statement))


def build_week(session: Session, day: date, *, today: date) -> WeekView:
    """Assemble seven days without creating a week row."""
    start = week_start_for(day)
    stored = {(_key(entry)): entry for entry in entries_for_week(session, start)}
    days = [_day_view(start + timedelta(days=offset), stored) for offset in range(7)]
    costs = week_cost(list(stored.values()))
    return WeekView(
        start=start,
        end=start + timedelta(days=6),
        label=format_week_range(start),
        previous=shift_week(start, -1),
        following=shift_week(start, 1),
        days=days,
        costs=costs,
        is_current=start == week_start_for(today),
    )


def assign_blank(session: Session, *, plan_date: date, slot: str) -> PlannerEntry:
    """Clear a slot. The week row appears on this first edit."""
    checked = _require_slot(slot)
    return _store(
        session,
        plan_date=plan_date,
        slot=checked,
        entry_type=BLANK,
        meal=None,
        description=None,
        price_pence=None,
    )


def assign_meal(
    session: Session, *, plan_date: date, slot: str, meal_id: int
) -> PlannerEntry:
    """Assign an active meal and snapshot its name. Repeats are allowed."""
    checked = _require_slot(slot)
    meal = get_meal(session, meal_id)
    if meal is None:
        raise FieldValidationError("meal_id", "Choose a meal.")
    if not meal.is_active:
        raise FieldValidationError(
            "meal_id",
            "Choose an active meal. Archived meals stay on the days already planned.",
        )
    return _store(
        session,
        plan_date=plan_date,
        slot=checked,
        entry_type=MEAL,
        meal=meal,
        description=None,
        price_pence=None,
    )


def assign_takeaway(
    session: Session,
    *,
    plan_date: date,
    slot: str,
    price: str,
    description: str | None,
) -> PlannerEntry:
    """Record a takeaway price. This creates no ingredient requirement."""
    checked = _require_slot(slot)
    pence = _require_price(price)
    notes = _clean_description(description)
    return _store(
        session,
        plan_date=plan_date,
        slot=checked,
        entry_type=TAKEAWAY,
        meal=None,
        description=notes,
        price_pence=pence,
    )


def ingredient_requirements(entries: list[PlannerEntry]) -> list[IngredientNeed]:
    """Sum recipe quantities. Blank and takeaway slots contribute nothing."""
    totals: dict[int, IngredientNeed] = {}
    for entry in entries:
        if entry.entry_type != MEAL or entry.meal is None:
            continue
        for line in entry.meal.lines:
            ingredient = line.ingredient
            current = totals.get(ingredient.id)
            added = line.quantity
            quantity = added if current is None else current.quantity + added
            totals[ingredient.id] = IngredientNeed(
                ingredient_id=ingredient.id,
                ingredient_name=ingredient.name,
                quantity=quantity,
                unit_symbol=ingredient.canonical_unit.symbol,
            )
    needs = list(totals.values())
    needs.sort(key=lambda need: need.ingredient_name.casefold())
    return needs


def week_cost(entries: list[PlannerEntry]) -> WeekCost:
    """Sum known meal costs. Takeaway pence are counted on their own."""
    ordered = sorted(entries, key=_entry_sort)
    meal_total = 0
    missing: list[str] = []
    seen: set[str] = set()
    meal_count = 0
    takeaway_total = 0
    takeaway_count = 0
    for entry in ordered:
        if entry.entry_type == TAKEAWAY:
            if entry.takeaway_price_pence is not None:
                takeaway_total += entry.takeaway_price_pence
                takeaway_count += 1
            continue
        if entry.entry_type != MEAL or entry.meal is None:
            continue
        meal_count += 1
        cost = cost_meal(entry.meal)
        meal_total += cost.total_pence
        for name in cost.missing_ingredients:
            if name in seen:
                continue
            seen.add(name)
            missing.append(name)
    return WeekCost(
        meal_total_pence=meal_total,
        meal_is_complete=not missing,
        missing_ingredients=tuple(missing),
        meal_count=meal_count,
        takeaway_total_pence=takeaway_total,
        takeaway_count=takeaway_count,
    )


def search_meals(session: Session, query: str, *, limit: int = 12) -> list[MealSummary]:
    """Active meals for the slot picker."""
    return list_meals(session, query=query, status="active")[:limit]


def slot_cost(entry: PlannerEntry | None) -> MealCost | None:
    """Ingredient estimate for a meal slot. Takeaway and blank have none."""
    if entry is None or entry.entry_type != MEAL or entry.meal is None:
        return None
    return cost_meal(entry.meal)


def open_editor(
    week: WeekView,
    *,
    plan_date: date,
    slot: str,
    mode: str,
    errors: dict[str, str] | None = None,
    draft_price: str = "",
    draft_description: str = "",
    meals: list[MealSummary] | None = None,
    search_query: str = "",
) -> SlotView | None:
    """Point one slot at the meal picker or the takeaway form."""
    found = find_slot(week, plan_date, slot)
    if found is None:
        return None
    found.mode = mode
    found.errors = dict(errors or {})
    found.draft_price = draft_price
    found.draft_description = draft_description
    found.meals = list(meals or [])
    found.search_query = search_query
    return found


def find_slot(week: WeekView, plan_date: date, slot: str) -> SlotView | None:
    """The lunch or dinner view for one date in this week."""
    for day in week.days:
        for candidate in (day.lunch, day.dinner):
            if candidate.plan_date == plan_date and candidate.slot == slot:
                return candidate
    return None


def _store(
    session: Session,
    *,
    plan_date: date,
    slot: str,
    entry_type: str,
    meal: Meal | None,
    description: str | None,
    price_pence: int | None,
) -> PlannerEntry:
    week = ensure_week(session, plan_date)
    entry = session.scalar(
        select(PlannerEntry).where(
            PlannerEntry.plan_date == plan_date,
            PlannerEntry.slot == slot,
        )
    )
    if entry is None:
        entry = PlannerEntry(
            week=week,
            plan_date=plan_date,
            slot=slot,
            entry_type=BLANK,
        )
        session.add(entry)
    entry.week = week
    entry.entry_type = entry_type
    entry.meal = meal
    entry.meal_id = None if meal is None else meal.id
    entry.snapshot_meal_name = None if meal is None else meal.name
    entry.takeaway_description = description
    entry.takeaway_price_pence = price_pence
    entry.updated_at = utcnow()
    session.flush()
    return entry


def _day_view(day: date, stored: dict[tuple[date, str], PlannerEntry]) -> DayView:
    lunch = stored.get((day, LUNCH))
    dinner = stored.get((day, DINNER))
    return DayView(
        plan_date=day,
        weekday=WEEKDAYS[day.weekday()],
        date_label=format_day(day),
        lunch=_slot_view(day, LUNCH, lunch),
        dinner=_slot_view(day, DINNER, dinner),
    )


def _slot_view(day: date, slot: str, entry: PlannerEntry | None) -> SlotView:
    return SlotView(plan_date=day, slot=slot, entry=entry, cost=slot_cost(entry))


def _require_slot(slot: str) -> str:
    if slot not in SLOTS:
        raise FieldValidationError("slot", "Choose lunch or dinner.")
    return slot


def _require_price(raw: str) -> int:
    try:
        return parse_gbp_to_pence(raw)
    except InvalidPriceError as exc:
        raise FieldValidationError("takeaway_price", str(exc)) from exc


def _clean_description(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > 200:
        raise FieldValidationError(
            "takeaway_description",
            "Use a description of 200 characters or fewer.",
        )
    return cleaned


def _month(day: date) -> str:
    return MONTHS[day.month - 1]


def _day_month(day: date) -> str:
    return f"{day.day} {_month(day)}"


def _entry_sort(entry: PlannerEntry) -> tuple[date, int]:
    return (entry.plan_date, _SLOT_ORDER.get(entry.slot, 2))


def _key(entry: PlannerEntry) -> tuple[date, str]:
    return (entry.plan_date, entry.slot)


def _meal_options() -> tuple[Any, ...]:
    meal_lines = selectinload(PlannerEntry.meal).selectinload(Meal.lines)
    ingredient = meal_lines.selectinload(RecipeIngredient.ingredient)
    return (
        ingredient.selectinload(Ingredient.canonical_unit),
        ingredient.selectinload(Ingredient.purchase_options),
        meal_lines.selectinload(RecipeIngredient.entered_unit),
    )
