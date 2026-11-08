"""Build and refresh one shopping list per planner week.

Stock is read and subtracted once from the week's aggregated requirement.
Generating a list does not change pantry quantities.
"""

from dataclasses import dataclass
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
from app.services.planner import IngredientNeed, ingredient_requirements
from app.services.stock import get_stock_map
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
    _recompute_packs(line)


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


def kept_without_requirement(line: ShoppingListLine) -> bool:
    """True when a checked buy was kept after the plan stopped needing it."""
    return (
        line.source == GENERATED
        and line.checked
        and not line.removed
        and line.required_quantity == 0
    )


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
