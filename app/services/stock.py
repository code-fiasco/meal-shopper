"""Pantry quantities. Stock changes only when a person edits it."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.formatting import format_quantity
from app.models import Ingredient, PantryStock, Unit
from app.services.ingredients import list_ingredients
from app.services.meals import compatible_units, unit_catalog
from app.services.parsing import FieldValidationError, parse_recipe_quantity
from app.services.units import IncompatibleUnitError, InvalidQuantityError, convert

SET = "set"
ADD = "add"
SUBTRACT = "subtract"
CLEAR = "clear"
_ADJUSTMENTS = frozenset({SET, ADD, SUBTRACT})


@dataclass
class StockControl:
    """One ingredient's quick-edit control, for the stock page or a later list."""

    ingredient_id: int
    ingredient_name: str
    ingredient_active: bool
    canonical_symbol: str
    canonical_name: str
    quantity: Decimal | None
    units: list[Unit]
    quantity_input: str
    unit_id: str
    errors: dict[str, str]
    placement: str
    dom_id: str


@dataclass(frozen=True)
class StockSearchHit:
    """An active ingredient the stock search can add."""

    id: int
    name: str
    unit_symbol: str
    quantity: Decimal | None


def get_stock_map(session: Session) -> dict[int, Decimal]:
    """On-hand canonical quantities, including explicit zeros.

    Ingredients with no pantry row are absent. Callers treat a missing id as
    no recorded stock. Plans and purchases do not update this map.
    """
    rows = session.scalars(select(PantryStock))
    return {row.ingredient_id: row.quantity_on_hand for row in rows}


def list_stock_controls(session: Session) -> list[StockControl]:
    """Controls for ingredients that currently have some stock."""
    catalog = unit_catalog(session)
    rows = session.scalars(
        select(PantryStock)
        .join(Ingredient, Ingredient.id == PantryStock.ingredient_id)
        .options(
            selectinload(PantryStock.ingredient).selectinload(
                Ingredient.canonical_unit
            ),
            selectinload(PantryStock.ingredient).selectinload(Ingredient.conversions),
        )
        .order_by(Ingredient.name)
    )
    return [
        _control(row.ingredient, row, catalog, placement="list")
        for row in rows
        if row.quantity_on_hand > 0
    ]


def stock_control(
    session: Session,
    ingredient_id: int,
    *,
    placement: str,
    quantity_input: str = "",
    unit_id: str | None = None,
    errors: dict[str, str] | None = None,
) -> StockControl | None:
    """Build the quick-edit control for one ingredient."""
    ingredient = _load_ingredient(session, ingredient_id)
    if ingredient is None:
        return None
    row = session.get(PantryStock, ingredient_id)
    return _control(
        ingredient,
        row,
        unit_catalog(session),
        placement=placement,
        quantity_input=quantity_input,
        unit_id=unit_id,
        errors=errors or {},
    )


def search_ingredients_for_stock(session: Session, query: str) -> list[StockSearchHit]:
    """Active ingredients matching a name, with any positive stock noted."""
    held = get_stock_map(session)
    return [
        StockSearchHit(
            id=item.id,
            name=item.name,
            unit_symbol=item.unit_symbol,
            quantity=held.get(item.id),
        )
        for item in list_ingredients(session, query=query, status="active")
    ]


def adjust_stock(
    session: Session,
    *,
    ingredient_id: int,
    action: str,
    quantity: str,
    unit_id: str,
) -> PantryStock:
    """Set, add, subtract, or clear a pantry quantity in the canonical unit.

    Compatible units are converted. An adjustment that would go below zero
    raises and leaves the stored quantity unchanged.
    """
    ingredient = _load_ingredient(session, ingredient_id)
    if ingredient is None:
        raise FieldValidationError("ingredient_id", "Choose an ingredient.")
    if action == CLEAR:
        return _store(session, ingredient.id, Decimal(0))
    if action not in _ADJUSTMENTS:
        raise FieldValidationError("action", "Choose set, add, subtract, or none left.")
    amount = _canonical_amount(session, ingredient, quantity, unit_id)
    current = _on_hand(session, ingredient.id)
    updated = _combine(action, current, amount)
    if updated < 0:
        held = format_quantity(current, ingredient.canonical_unit.symbol)
        raise FieldValidationError(
            "quantity",
            f"That would take {ingredient.name} below zero. {held} is in stock.",
        )
    return _store(session, ingredient.id, updated)


def _control(
    ingredient: Ingredient,
    row: PantryStock | None,
    catalog: list[Unit],
    *,
    placement: str,
    quantity_input: str = "",
    unit_id: str | None = None,
    errors: dict[str, str] | None = None,
) -> StockControl:
    selected = str(ingredient.canonical_unit_id) if unit_id is None else unit_id
    dom_id = (
        f"stock-editor-{ingredient.id}"
        if placement == "editor"
        else f"stock-item-{ingredient.id}"
    )
    return StockControl(
        ingredient_id=ingredient.id,
        ingredient_name=ingredient.name,
        ingredient_active=ingredient.is_active,
        canonical_symbol=ingredient.canonical_unit.symbol,
        canonical_name=ingredient.canonical_unit.name,
        quantity=None if row is None else row.quantity_on_hand,
        units=_units(ingredient, catalog, selected),
        quantity_input=quantity_input,
        unit_id=selected,
        errors=errors or {},
        placement=placement,
        dom_id=dom_id,
    )


def _units(ingredient: Ingredient, catalog: list[Unit], posted: str) -> list[Unit]:
    units = compatible_units(ingredient, catalog)
    extra = next((unit for unit in catalog if str(unit.id) == posted), None)
    if extra is None or any(unit.id == extra.id for unit in units):
        return units
    return [*units, extra]


def _canonical_amount(
    session: Session, ingredient: Ingredient, quantity: str, unit_id: str
) -> Decimal:
    unit = _unit(session, unit_id)
    if unit is None:
        raise FieldValidationError(
            "unit_id",
            f"Choose a unit compatible with {ingredient.canonical_unit.name}.",
        )
    try:
        amount = parse_recipe_quantity(quantity, unit_symbol=unit.symbol)
    except InvalidQuantityError as exc:
        raise FieldValidationError("quantity", str(exc)) from exc
    if not _unit_allowed(ingredient, unit):
        raise FieldValidationError(
            "unit_id",
            f"{ingredient.name} is measured in {ingredient.canonical_unit.name}; "
            f"{unit.name} cannot be used.",
        )
    try:
        return convert(
            amount,
            unit,
            ingredient.canonical_unit,
            ingredient.conversions,
            ingredient_name=ingredient.name,
        )
    except IncompatibleUnitError as exc:
        raise FieldValidationError("unit_id", str(exc)) from exc


def _unit_allowed(ingredient: Ingredient, unit: Unit) -> bool:
    return any(
        candidate.id == unit.id for candidate in compatible_units(ingredient, [unit])
    )


def _combine(action: str, current: Decimal, amount: Decimal) -> Decimal:
    if action == ADD:
        return current + amount
    if action == SUBTRACT:
        return current - amount
    return amount


def _on_hand(session: Session, ingredient_id: int) -> Decimal:
    row = session.get(PantryStock, ingredient_id)
    if row is None:
        return Decimal(0)
    return row.quantity_on_hand


def _store(session: Session, ingredient_id: int, quantity: Decimal) -> PantryStock:
    row = session.get(PantryStock, ingredient_id)
    if row is None:
        row = PantryStock(ingredient_id=ingredient_id, quantity_on_hand=quantity)
        session.add(row)
    else:
        row.quantity_on_hand = quantity
    session.flush()
    return row


def _load_ingredient(session: Session, ingredient_id: int) -> Ingredient | None:
    return session.scalar(
        select(Ingredient)
        .where(Ingredient.id == ingredient_id)
        .options(
            selectinload(Ingredient.canonical_unit),
            selectinload(Ingredient.conversions),
        )
    )


def _unit(session: Session, raw: str) -> Unit | None:
    try:
        unit_id = int(raw)
    except ValueError:
        return None
    return session.get(Unit, unit_id)
