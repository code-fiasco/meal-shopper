"""Build and refresh one shopping list per planner week.

Stock is read and subtracted once from the week's aggregated requirement.
Generating a list does not change pantry quantities.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Ingredient,
    Meal,
    PlannerEntry,
    PlannerWeek,
    PurchaseOption,
    RecipeIngredient,
    ShoppingList,
    ShoppingListLine,
)
from app.models.types import utcnow
from app.services.parsing import FieldValidationError
from app.services.planner import (
    IngredientNeed,
    format_week_range,
    get_week,
    ingredient_requirements,
    shift_week,
    week_start_for,
)
from app.services.stock import (
    SET,
    StockControl,
    adjust_stock,
    get_stock_map,
    stock_control,
)
from app.services.units import allocated_cost_pence, unit_price_per_canonical

GENERATED = "generated"
MANUAL = "manual"
DRAFT = "draft"
SHOPPED = "shopped"


@dataclass(frozen=True)
class ShoppingTotals:
    """Pack outlay and recipe consumption, kept as separate figures."""

    outlay_pence: int
    consumption_pence: int
    is_complete: bool
    missing_ingredients: tuple[str, ...]


def generate_shopping_list(session: Session, week_id: int) -> ShoppingList:
    """Get or create the week's list and refresh its generated lines.

    Manual lines are left as they are. A second call updates the same list.
    """
    week = session.get(PlannerWeek, week_id)
    if week is None:
        raise FieldValidationError("week_id", "Choose a week that has been planned.")
    shopping_list = _list_for_week(session, week)
    needs = {
        need.ingredient_id: need
        for need in ingredient_requirements(_meal_entries(session, week.id))
    }
    held = get_stock_map(session)
    options = _options_for(session, list(needs))
    existing = _generated_by_ingredient(shopping_list)
    for ingredient_id, need in needs.items():
        line = existing.get(ingredient_id)
        if line is None:
            shopping_list.lines.append(
                _new_line(need, held, options.get(ingredient_id, []))
            )
            continue
        _refresh_line(line, need, held, options.get(ingredient_id, []))
    _retire_missing(shopping_list, existing, set(needs))
    shopping_list.updated_at = utcnow()
    session.flush()
    return shopping_list


def add_manual_line(
    session: Session,
    shopping_list: ShoppingList,
    *,
    description: str,
    quantity: Decimal | None = None,
    unit: str | None = None,
    price_pence: int | None = None,
    shop_name: str | None = None,
) -> ShoppingListLine:
    """Add an item that is not on a recipe. Regeneration will not change it."""
    amount = Decimal(0) if quantity is None else _require_quantity(quantity)
    line = ShoppingListLine(
        source=MANUAL,
        ingredient_id=None,
        description=_clean_description(description),
        unit_snapshot=_clean_unit(unit),
        required_quantity=amount,
        stock_allocated=Decimal(0),
        net_quantity=amount,
        shop_name=_clean_optional(shop_name),
        pack_count=0,
        manual_price_pence=_require_pence(price_pence),
        checked=False,
        removed=False,
        option_overridden=False,
        quantity_overridden=False,
    )
    shopping_list.lines.append(line)
    shopping_list.updated_at = utcnow()
    session.flush()
    return line


def remove_generated_line(line: ShoppingListLine) -> None:
    """Hide a generated item. The row stays so a later regenerate can restore it."""
    if line.source != GENERATED:
        raise FieldValidationError(
            "line", "Only a generated ingredient can be removed from the list."
        )
    line.removed = True


def restore_removed_line(line: ShoppingListLine) -> None:
    """Put a removed generated item back on the list."""
    if line.source != GENERATED or not line.removed:
        raise FieldValidationError(
            "line", "Only a removed generated item can be restored."
        )
    line.removed = False


def choose_purchase_option(
    session: Session, line: ShoppingListLine, option_id: int
) -> ShoppingListLine:
    """Use one active pack for this list, even when a cheaper pack exists."""
    if line.source != GENERATED or line.ingredient_id is None:
        raise FieldValidationError(
            "option_id", "Choose a purchase option for a generated ingredient."
        )
    option = session.scalar(
        select(PurchaseOption)
        .where(PurchaseOption.id == option_id)
        .options(selectinload(PurchaseOption.shop))
    )
    if (
        option is None
        or not option.is_active
        or option.ingredient_id != line.ingredient_id
    ):
        raise FieldValidationError(
            "option_id", "Choose an active pack for this ingredient."
        )
    line.selected_purchase_option_id = option.id
    line.option_overridden = True
    _snapshot_option(line, option)
    _recompute_packs(line)
    session.flush()
    return line


def set_quantity_override(line: ShoppingListLine, quantity: Decimal) -> None:
    """Buy a chosen amount and keep that choice across regeneration."""
    if line.source != GENERATED:
        raise FieldValidationError(
            "quantity", "Only a generated ingredient can have a quantity override."
        )
    line.quantity_override = _require_quantity(quantity)
    line.quantity_overridden = True
    line.pack_count_override = None
    _recompute_packs(line)


def set_pack_count_override(line: ShoppingListLine, count: int) -> None:
    """Buy a chosen number of packs and keep that choice across regeneration."""
    if line.source != GENERATED:
        raise FieldValidationError(
            "pack_count", "Only a generated ingredient can have a pack count."
        )
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise FieldValidationError("pack_count", "Pack count cannot be negative.")
    line.pack_count_override = count
    _recompute_packs(line)


def set_line_price(line: ShoppingListLine, price_pence: int) -> None:
    """Set the price used by this list. The ingredient's pack price is unchanged."""
    price = _require_pence(price_pence)
    if price is None:
        raise FieldValidationError("price", "Enter a price in pounds, such as 1.79.")
    if line.source == MANUAL:
        line.manual_price_pence = price
        return
    if line.pack_quantity is None:
        raise FieldValidationError("price", "This ingredient has no pack to price.")
    line.pack_price_pence = price
    _recompute_packs(line)


ORDER_SHOP = "shop"
ORDER_NAME = "name"


@dataclass(frozen=True)
class ChecklistTotals:
    """Estimated outlay, and the share of it that is still unticked."""

    estimated_pence: int
    remaining_pence: int
    is_complete: bool
    missing_ingredients: tuple[str, ...]


@dataclass(frozen=True)
class ChecklistItem:
    """One visible checklist row and the price it contributes."""

    line: ShoppingListLine
    price_pence: int | None
    off_plan: bool


@dataclass
class ChecklistPage:
    """Phone checklist or print view for one saved list."""

    list_id: int
    label: str
    start: date
    items: list[ChecklistItem]
    totals: ChecklistTotals
    order: str
    show_boxes: bool


def set_line_checked(line: ShoppingListLine, checked: bool) -> None:
    """Mark a row collected. The choice stays on this list."""
    if not isinstance(checked, bool):
        raise FieldValidationError("checked", "Choose collected or still to buy.")
    if line.removed:
        raise FieldValidationError("checked", "A removed item is not on the checklist.")
    line.checked = checked


def checklist_for(
    shopping_list: ShoppingList, *, order: str = ORDER_SHOP, show_boxes: bool = True
) -> ChecklistPage:
    """Rows to buy, in shop order or A-Z, with estimated and remaining totals."""
    chosen = _checklist_order(order)
    visible = checklist_lines(list(shopping_list.lines), order=chosen)
    return ChecklistPage(
        list_id=shopping_list.id,
        label=format_week_range(shopping_list.week.week_start_date),
        start=shopping_list.week.week_start_date,
        items=visible,
        totals=checklist_totals(list(shopping_list.lines)),
        order=chosen,
        show_boxes=show_boxes,
    )


def checklist_lines(
    lines: list[ShoppingListLine], *, order: str
) -> list[ChecklistItem]:
    """Visible rows. Shop order uses the shop only when one is set."""
    chosen = _checklist_order(order)
    visible = [line for line in lines if not line.removed]
    if chosen == ORDER_NAME:
        ordered = sorted(visible, key=_name_key)
    else:
        with_shop = [line for line in visible if line.shop_name]
        without_shop = [line for line in visible if not line.shop_name]
        with_shop.sort(key=_shop_key)
        without_shop.sort(key=_name_key)
        ordered = [*with_shop, *without_shop]
    return [_checklist_item(line) for line in ordered]


def checklist_totals(lines: list[ShoppingListLine]) -> ChecklistTotals:
    """Sum priced rows. Remaining leaves out anything already ticked."""
    estimated = 0
    remaining = 0
    missing: list[str] = []
    for line in lines:
        if line.removed:
            continue
        price = _outlay_pence(line)
        if price is not None:
            estimated += price
            if not line.checked:
                remaining += price
        if _missing_price(line):
            missing.append(line.description)
    missing.sort(key=str.casefold)
    return ChecklistTotals(
        estimated_pence=estimated,
        remaining_pence=remaining,
        is_complete=not missing,
        missing_ingredients=tuple(missing),
    )


def _checklist_item(line: ShoppingListLine) -> ChecklistItem:
    return ChecklistItem(
        line=line,
        price_pence=_outlay_pence(line),
        off_plan=kept_without_requirement(line),
    )


def _checklist_order(order: str) -> str:
    if order in {ORDER_SHOP, ORDER_NAME}:
        return order
    raise FieldValidationError("order", "Sort by shop or A-Z.")


def _name_key(line: ShoppingListLine) -> tuple[str, int]:
    return (line.description.casefold(), line.id)


def _shop_key(line: ShoppingListLine) -> tuple[str, str, int]:
    shop = line.shop_name or ""
    return (shop.casefold(), line.description.casefold(), line.id)


def shopping_totals(shopping_list: ShoppingList) -> ShoppingTotals:
    """Sum pack outlay and recipe consumption without mixing the two."""
    outlay = 0
    consumption = 0
    missing: list[str] = []
    for line in shopping_list.lines:
        if line.removed:
            continue
        price = _outlay_pence(line)
        if price is not None:
            outlay += price
        used = _consumption_pence(line)
        if used is not None:
            consumption += used
        if _missing_price(line):
            missing.append(line.description)
    missing.sort(key=str.casefold)
    return ShoppingTotals(
        outlay_pence=outlay,
        consumption_pence=consumption,
        is_complete=not missing,
        missing_ingredients=tuple(missing),
    )


@dataclass(frozen=True)
class RefreshSummary:
    """How many generated lines a refresh created, changed, or dropped."""

    created: int
    updated: int
    removed: int

    def label(self) -> str:
        """Short status, for example '2 updated, 1 new'."""
        parts: list[str] = []
        if self.updated:
            parts.append(f"{self.updated} updated")
        if self.created:
            parts.append(f"{self.created} new")
        if self.removed:
            parts.append(f"{self.removed} removed")
        if not parts:
            return "No changes"
        return ", ".join(parts)


def refresh_shopping_list(
    session: Session, week_id: int
) -> tuple[ShoppingList, RefreshSummary]:
    """Regenerate the week's list and report what changed."""
    before = _generated_snapshot(_existing_list(session, week_id))
    shopping_list = generate_shopping_list(session, week_id)
    return shopping_list, _summarise(before, shopping_list)


def cover_requirement_with_stock(
    session: Session, line: ShoppingListLine
) -> RefreshSummary:
    """Record enough pantry stock to cover this line, then refresh the list."""
    if line.source != GENERATED or line.ingredient_id is None:
        raise FieldValidationError(
            "line", "Pantry stock can cover a generated ingredient."
        )
    if line.required_quantity <= 0:
        raise FieldValidationError(
            "line", "This ingredient has no recipe requirement to cover."
        )
    ingredient = session.scalar(
        select(Ingredient)
        .where(Ingredient.id == line.ingredient_id)
        .options(selectinload(Ingredient.canonical_unit))
    )
    if ingredient is None:
        raise FieldValidationError("line", "Choose an ingredient.")
    held = get_stock_map(session).get(ingredient.id, Decimal(0))
    if held < line.required_quantity:
        adjust_stock(
            session,
            ingredient_id=ingredient.id,
            action=SET,
            quantity=format(line.required_quantity, "f"),
            unit_id=str(ingredient.canonical_unit_id),
        )
    _, summary = refresh_shopping_list(session, _week_id(session, line))
    return summary


def kept_without_requirement(line: ShoppingListLine) -> bool:
    """True when a checked buy was kept after the plan stopped needing it."""
    return (
        line.source == GENERATED
        and line.checked
        and not line.removed
        and line.required_quantity == 0
    )


@dataclass(frozen=True)
class PackChoice:
    """One active pack the shopper can choose for this list."""

    id: int
    shop_name: str
    pack_label: str
    pack_quantity: Decimal
    price_pence: int
    unit_price: Decimal
    unit_symbol: str


@dataclass
class ShoppingLineView:
    """A list row plus the packs and stock control the page can show."""

    line: ShoppingListLine
    packs: list[PackChoice]
    stock: StockControl | None
    missing_price: bool
    manually_adjusted: bool
    off_plan: bool
    errors: dict[str, str]


@dataclass
class ShoppingPage:
    """One week of the shopping screen."""

    start: date
    label: str
    previous: date
    following: date
    is_current: bool
    shopping_list: ShoppingList | None
    generated: list[ShoppingLineView]
    manual: list[ShoppingLineView]
    removed: list[ShoppingLineView]
    totals: ShoppingTotals | None
    notice: str | None
    error: str | None
    form_errors: dict[str, str]
    form_values: dict[str, str]


def shopping_page_for(
    session: Session,
    day: date,
    *,
    today: date,
    notice: str | None = None,
    error: str | None = None,
    line_errors: dict[int, dict[str, str]] | None = None,
    form_errors: dict[str, str] | None = None,
    form_values: dict[str, str] | None = None,
) -> ShoppingPage:
    """Assemble the shopping screen without creating a list or a week."""
    start = week_start_for(day)
    week = get_week(session, start)
    shopping_list = _existing_list(session, week.id) if week is not None else None
    errors = line_errors or {}
    generated: list[ShoppingLineView] = []
    manual: list[ShoppingLineView] = []
    removed: list[ShoppingLineView] = []
    if shopping_list is not None:
        grouped = _views(session, shopping_list, errors)
        generated, manual, removed = grouped
    totals = None if shopping_list is None else shopping_totals(shopping_list)
    return ShoppingPage(
        start=start,
        label=format_week_range(start),
        previous=shift_week(start, -1),
        following=shift_week(start, 1),
        is_current=start == week_start_for(today),
        shopping_list=shopping_list,
        generated=generated,
        manual=manual,
        removed=removed,
        totals=totals,
        notice=notice,
        error=error,
        form_errors=form_errors or {},
        form_values=form_values or {},
    )


def _views(
    session: Session,
    shopping_list: ShoppingList,
    errors: dict[int, dict[str, str]],
) -> tuple[list[ShoppingLineView], list[ShoppingLineView], list[ShoppingLineView]]:
    ingredient_ids = [
        line.ingredient_id
        for line in shopping_list.lines
        if line.ingredient_id is not None
    ]
    options = _options_for(session, ingredient_ids)
    generated: list[ShoppingLineView] = []
    manual: list[ShoppingLineView] = []
    removed: list[ShoppingLineView] = []
    for line in shopping_list.lines:
        view = _line_view(session, line, options, errors.get(line.id, {}))
        if line.source == MANUAL:
            manual.append(view)
        elif line.removed:
            removed.append(view)
        else:
            generated.append(view)
    return generated, manual, removed


def _line_view(
    session: Session,
    line: ShoppingListLine,
    options: dict[int, list[PurchaseOption]],
    errors: dict[str, str],
) -> ShoppingLineView:
    packs: list[PackChoice] = []
    stock = None
    if line.ingredient_id is not None:
        active = [
            option for option in options.get(line.ingredient_id, []) if option.is_active
        ]
        active.sort(key=_price_key)
        packs = [_pack_choice(option, line.unit_snapshot) for option in active]
        if line.source == GENERATED and not line.removed:
            stock = stock_control(session, line.ingredient_id, placement="list")
    return ShoppingLineView(
        line=line,
        packs=packs,
        stock=stock,
        missing_price=_missing_price(line),
        manually_adjusted=(
            line.quantity_overridden or line.pack_count_override is not None
        ),
        off_plan=kept_without_requirement(line),
        errors=errors,
    )


def _pack_choice(option: PurchaseOption, unit_symbol: str) -> PackChoice:
    return PackChoice(
        id=option.id,
        shop_name=option.shop.name,
        pack_label=option.pack_label,
        pack_quantity=option.pack_quantity,
        price_pence=option.price_pence,
        unit_price=unit_price_per_canonical(option),
        unit_symbol=unit_symbol,
    )


@dataclass(frozen=True)
class _Snap:
    required: Decimal
    stock: Decimal
    net: Decimal
    pack_count: int
    price: int | None
    option_id: int | None
    removed: bool


def _existing_list(session: Session, week_id: int) -> ShoppingList | None:
    return session.scalar(
        select(ShoppingList)
        .where(ShoppingList.planner_week_id == week_id)
        .options(selectinload(ShoppingList.lines))
    )


def _week_id(session: Session, line: ShoppingListLine) -> int:
    shopping_list = line.shopping_list or session.get(ShoppingList, line.list_id)
    if shopping_list is None:
        raise FieldValidationError("line", "Choose a shopping list.")
    return shopping_list.planner_week_id


def _generated_snapshot(
    shopping_list: ShoppingList | None,
) -> dict[int, _Snap]:
    if shopping_list is None:
        return {}
    snaps: dict[int, _Snap] = {}
    for line in shopping_list.lines:
        if line.source != GENERATED or line.ingredient_id is None:
            continue
        snaps[line.ingredient_id] = _Snap(
            required=line.required_quantity,
            stock=line.stock_allocated,
            net=line.net_quantity,
            pack_count=line.pack_count,
            price=line.estimated_price_pence,
            option_id=line.selected_purchase_option_id,
            removed=line.removed,
        )
    return snaps


def _summarise(before: dict[int, _Snap], shopping_list: ShoppingList) -> RefreshSummary:
    after = _generated_snapshot(shopping_list)
    created = 0
    updated = 0
    for ingredient_id, snap in after.items():
        previous = before.get(ingredient_id)
        if previous is None:
            created += 1
        elif previous != snap:
            updated += 1
    removed = sum(1 for ingredient_id in before if ingredient_id not in after)
    return RefreshSummary(created=created, updated=updated, removed=removed)


def _list_for_week(session: Session, week: PlannerWeek) -> ShoppingList:
    existing = session.scalar(
        select(ShoppingList)
        .where(ShoppingList.planner_week_id == week.id)
        .options(selectinload(ShoppingList.lines))
    )
    if existing is not None:
        return existing
    created = ShoppingList(planner_week_id=week.id, status=DRAFT)
    session.add(created)
    session.flush()
    return created


def _meal_entries(session: Session, week_id: int) -> list[PlannerEntry]:
    ingredient = (
        selectinload(PlannerEntry.meal)
        .selectinload(Meal.lines)
        .selectinload(RecipeIngredient.ingredient)
    )
    statement = (
        select(PlannerEntry)
        .where(PlannerEntry.week_id == week_id)
        .options(ingredient.selectinload(Ingredient.canonical_unit))
    )
    return list(session.scalars(statement))


def _options_for(
    session: Session, ingredient_ids: list[int]
) -> dict[int, list[PurchaseOption]]:
    if not ingredient_ids:
        return {}
    rows = session.scalars(
        select(PurchaseOption)
        .where(PurchaseOption.ingredient_id.in_(ingredient_ids))
        .options(selectinload(PurchaseOption.shop))
    )
    grouped: dict[int, list[PurchaseOption]] = {}
    for option in rows:
        grouped.setdefault(option.ingredient_id, []).append(option)
    return grouped


def _generated_by_ingredient(
    shopping_list: ShoppingList,
) -> dict[int, ShoppingListLine]:
    found: dict[int, ShoppingListLine] = {}
    for line in list(shopping_list.lines):
        if line.source != GENERATED or line.ingredient_id is None:
            continue
        if line.ingredient_id in found:
            shopping_list.lines.remove(line)
            continue
        found[line.ingredient_id] = line
    return found


def _new_line(
    need: IngredientNeed,
    held: dict[int, Decimal],
    options: list[PurchaseOption],
) -> ShoppingListLine:
    line = ShoppingListLine(
        source=GENERATED,
        ingredient_id=need.ingredient_id,
        description=need.ingredient_name,
        unit_snapshot=need.unit_symbol,
        required_quantity=Decimal(0),
        stock_allocated=Decimal(0),
        net_quantity=Decimal(0),
        pack_count=0,
        checked=False,
        removed=False,
        option_overridden=False,
        quantity_overridden=False,
    )
    _refresh_line(line, need, held, options)
    return line


def _refresh_line(
    line: ShoppingListLine,
    need: IngredientNeed,
    held: dict[int, Decimal],
    options: list[PurchaseOption],
) -> None:
    required = need.quantity
    available = held.get(need.ingredient_id, Decimal(0))
    line.description = need.ingredient_name
    line.unit_snapshot = need.unit_symbol
    line.required_quantity = required
    line.stock_allocated = min(required, available)
    line.net_quantity = max(Decimal(0), required - available)
    _apply_choice(line, options)


def _retire_missing(
    shopping_list: ShoppingList,
    existing: dict[int, ShoppingListLine],
    still_needed: set[int],
) -> None:
    for ingredient_id, line in existing.items():
        if ingredient_id in still_needed:
            continue
        if line.checked and not line.removed:
            _park(line)
            continue
        shopping_list.lines.remove(line)


def _park(line: ShoppingListLine) -> None:
    """Keep a checked line after its ingredient leaves the plan."""
    line.required_quantity = Decimal(0)
    line.stock_allocated = Decimal(0)
    line.net_quantity = Decimal(0)
    _recompute_packs(line)


def _apply_choice(line: ShoppingListLine, options: list[PurchaseOption]) -> None:
    chosen = _kept_or_cheapest(line, options)
    if chosen is None:
        _clear_pack(line)
        return
    if line.selected_purchase_option_id != chosen.id:
        line.option_overridden = False
    line.selected_purchase_option_id = chosen.id
    _snapshot_option(line, chosen)
    _recompute_packs(line)


def _kept_or_cheapest(
    line: ShoppingListLine, options: list[PurchaseOption]
) -> PurchaseOption | None:
    active = [option for option in options if option.is_active]
    for option in active:
        if option.id == line.selected_purchase_option_id:
            return option
    if not active:
        return None
    return min(active, key=_price_key)


def _price_key(option: PurchaseOption) -> tuple[Decimal, int]:
    return (unit_price_per_canonical(option), option.id)


def _snapshot_option(line: ShoppingListLine, option: PurchaseOption) -> None:
    line.shop_name = option.shop.name
    line.pack_label = option.pack_label
    line.pack_quantity = option.pack_quantity
    line.pack_price_pence = option.price_pence


def _clear_pack(line: ShoppingListLine) -> None:
    line.selected_purchase_option_id = None
    line.option_overridden = False
    line.shop_name = None
    line.pack_label = None
    line.pack_quantity = None
    line.pack_price_pence = None
    line.pack_count = 0
    line.estimated_price_pence = None


def _recompute_packs(line: ShoppingListLine) -> None:
    if line.pack_price_pence is None or line.pack_quantity is None:
        line.pack_count = 0
        line.estimated_price_pence = None
        return
    if line.pack_count_override is not None:
        count = line.pack_count_override
    else:
        count = packs_to_buy(_buy_quantity(line), line.pack_quantity)
    line.pack_count = count
    line.estimated_price_pence = count * line.pack_price_pence


def _buy_quantity(line: ShoppingListLine) -> Decimal:
    if line.quantity_overridden and line.quantity_override is not None:
        return line.quantity_override
    return line.net_quantity


def packs_to_buy(quantity: Decimal, pack_quantity: Decimal) -> int:
    """Whole packs needed. Zero when nothing remains to buy."""
    if quantity <= 0:
        return 0
    if pack_quantity <= 0:
        raise FieldValidationError("pack_quantity", "Pack quantity must be above zero.")
    count = (quantity / pack_quantity).to_integral_value(rounding=ROUND_CEILING)
    return int(count)


def _outlay_pence(line: ShoppingListLine) -> int | None:
    if line.source == MANUAL:
        return line.manual_price_pence
    if line.pack_price_pence is None or line.pack_count <= 0:
        return None
    return line.estimated_price_pence


def _consumption_pence(line: ShoppingListLine) -> int | None:
    if line.source != GENERATED or line.required_quantity <= 0:
        return None
    if line.pack_price_pence is None or line.pack_quantity is None:
        return None
    unit_price = Decimal(line.pack_price_pence) / line.pack_quantity
    return allocated_cost_pence(line.required_quantity, unit_price)


def _missing_price(line: ShoppingListLine) -> bool:
    return (
        line.source == GENERATED
        and line.required_quantity > 0
        and line.pack_price_pence is None
    )


def _require_quantity(quantity: Decimal) -> Decimal:
    if isinstance(quantity, float) or not isinstance(quantity, Decimal):
        raise FieldValidationError("quantity", "Quantity must be Decimal, not float.")
    if not quantity.is_finite() or quantity < 0:
        raise FieldValidationError("quantity", "Quantity cannot be negative.")
    return quantity


def _require_pence(price: int | None) -> int | None:
    if price is None:
        return None
    if isinstance(price, bool) or not isinstance(price, int):
        raise FieldValidationError("price", "Enter a price in pence.")
    if price < 0:
        raise FieldValidationError("price", "Price cannot be negative.")
    return price


def _clean_description(raw: str) -> str:
    cleaned = " ".join(raw.strip().split())
    if not cleaned:
        raise FieldValidationError("description", "Enter an item name.")
    if len(cleaned) > 200:
        raise FieldValidationError(
            "description", "Use an item name of 200 characters or fewer."
        )
    return cleaned


def _clean_unit(raw: str | None) -> str:
    if raw is None:
        return ""
    return " ".join(raw.strip().split())[:16]


def _clean_optional(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = " ".join(raw.strip().split())
    return cleaned or None
