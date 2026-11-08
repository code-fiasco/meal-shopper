"""Meal records, recipe lines, and archive checks."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Ingredient, Meal, PlannerEntry, RecipeIngredient, Unit
from app.models.types import utcnow
from app.models.unit import UnitFamily
from app.services.costing import MealCost, cost_lines
from app.services.ingredients import normalise_ingredient_name
from app.services.parsing import FieldValidationError
from app.services.units import convert

_METRIC = frozenset({UnitFamily.WEIGHT, UnitFamily.VOLUME})


@dataclass
class LineForm:
    """One recipe row as the editor displays it."""

    index: int
    ingredient_id: str
    ingredient_name: str
    canonical_symbol: str
    canonical_name: str
    entered_quantity: str
    entered_unit_id: str
    notes: str
    units: list[Unit]
    errors: dict[str, str]


@dataclass(frozen=True)
class RawLine:
    ingredient_id: str
    entered_quantity: str
    entered_unit_id: str
    notes: str


@dataclass(frozen=True)
class PreparedLine:
    ingredient: Ingredient
    entered_quantity: Decimal
    entered_unit: Unit
    canonical_quantity: Decimal
    notes: str | None
    sort_order: int


@dataclass(frozen=True)
class MealSummary:
    id: int
    name: str
    is_active: bool
    cost: MealCost


def historical_planner_entries(session: Session, meal_id: int) -> list[int]:
    """Planner entry ids that already use this meal."""
    return list(
        session.scalars(
            select(PlannerEntry.id)
            .where(PlannerEntry.meal_id == meal_id)
            .order_by(PlannerEntry.id)
        )
    )


def list_meals(
    session: Session, *, query: str = "", status: str = "active"
) -> list[MealSummary]:
    """List meals with a two-person cost. Missing prices stay out of the total."""
    statement = _meal_query().order_by(Meal.name)
    if status == "active":
        statement = statement.where(Meal.is_active.is_(True))
    elif status == "archived":
        statement = statement.where(Meal.is_active.is_(False))
    rows = list(session.scalars(statement))
    needle = normalise_ingredient_name(query)
    if needle:
        rows = [row for row in rows if _matches(row, needle)]
    return [
        MealSummary(row.id, row.name, row.is_active, cost_meal(row)) for row in rows
    ]


def get_meal(session: Session, meal_id: int) -> Meal | None:
    """Load a meal with the relationships costing and the editor need."""
    return session.scalar(_meal_query().where(Meal.id == meal_id))


def cost_meal(meal: Meal) -> MealCost:
    """Estimated ingredient cost for the two portions this recipe already describes."""
    rows = [
        (
            line.ingredient,
            line.entered_quantity,
            line.entered_unit.symbol,
            line.quantity,
            line.ingredient.canonical_unit.symbol,
        )
        for line in meal.lines
    ]
    return cost_lines(rows)


def meal_field_errors(
    *, name: str, description: str | None, instructions: str | None
) -> dict[str, str]:
    """Collect meal-level messages before anything is written."""
    errors: dict[str, str] = {}
    for cleaner in (
        lambda: _clean_name(name),
        lambda: _clean_text(description, "description", 2000),
        lambda: _clean_text(instructions, "instructions", 8000),
    ):
        try:
            cleaner()
        except FieldValidationError as exc:
            errors[exc.field] = str(exc)
    return errors


def save_meal(
    session: Session,
    meal: Meal | None,
    *,
    name: str,
    description: str | None,
    instructions: str | None,
    lines: list[PreparedLine],
) -> Meal:
    """Create or replace a recipe. Lines are stored in canonical units."""
    current = meal if meal is not None else Meal(is_active=True)
    current.name = _clean_name(name)
    current.description = _clean_text(description, "description", 2000)
    current.instructions = _clean_text(instructions, "instructions", 8000)
    current.updated_at = utcnow()
    if meal is None:
        session.add(current)
        session.flush()
    current.lines.clear()
    session.flush()
    for prepared in lines:
        current.lines.append(
            RecipeIngredient(
                ingredient=prepared.ingredient,
                quantity=prepared.canonical_quantity,
                entered_quantity=prepared.entered_quantity,
                entered_unit=prepared.entered_unit,
                notes=prepared.notes,
                sort_order=prepared.sort_order,
            )
        )
    session.flush()
    return current


def duplicate_meal(session: Session, meal: Meal) -> Meal:
    """Copy a recipe, including its lines, as a new active meal."""
    copy = Meal(
        name=_copy_name(meal.name),
        description=meal.description,
        instructions=meal.instructions,
        is_active=True,
    )
    session.add(copy)
    session.flush()
    for line in meal.lines:
        copy.lines.append(
            RecipeIngredient(
                ingredient=line.ingredient,
                quantity=line.quantity,
                entered_quantity=line.entered_quantity,
                entered_unit=line.entered_unit,
                notes=line.notes,
                sort_order=line.sort_order,
            )
        )
    session.flush()
    return copy


class MealInUseError(ValueError):
    """Raised when a meal cannot be removed because history still points at it."""


def set_meal_active(session: Session, meal: Meal, *, active: bool) -> Meal:
    """Archive or restore a meal. Planner entries keep their snapshotted name."""
    meal.is_active = active
    meal.updated_at = utcnow()
    session.flush()
    return meal


def delete_meal(session: Session, meal: Meal) -> None:
    """Refuse hard deletion. A meal on a plan must be archived."""
    if historical_planner_entries(session, meal.id):
        raise MealInUseError(
            "This meal is on a saved plan. Archive it instead of deleting it."
        )
    raise MealInUseError("Archive this meal instead of deleting it.")


def prepare_lines(
    session: Session, raw_lines: list[RawLine]
) -> tuple[list[PreparedLine], dict[int, dict[str, str]]]:
    """Convert entered units to canonical units, collecting every field error."""
    prepared: list[PreparedLine] = []
    errors: dict[int, dict[str, str]] = {}
    for index, raw in enumerate(raw_lines):
        if _blank(raw):
            continue
        line, line_errors = _prepare_one(session, raw, len(prepared))
        if line_errors:
            errors[index] = line_errors
        elif line is not None:
            prepared.append(line)
    return prepared, errors


def compatible_units(ingredient: Ingredient, catalog: list[Unit]) -> list[Unit]:
    """Units the recipe editor may offer for this ingredient."""
    explicit = {conversion.from_unit_id for conversion in ingredient.conversions}
    canonical = ingredient.canonical_unit
    chosen = [
        unit
        for unit in catalog
        if unit.id == canonical.id
        or unit.id in explicit
        or _same_metric_family(unit, canonical)
    ]
    chosen.sort(key=lambda unit: (unit.id != canonical.id, unit.name.lower()))
    return chosen


def blank_line(index: int) -> LineForm:
    """An empty recipe row."""
    return LineForm(
        index=index,
        ingredient_id="",
        ingredient_name="",
        canonical_symbol="",
        canonical_name="",
        entered_quantity="",
        entered_unit_id="",
        notes="",
        units=[],
        errors={},
    )


def line_form_for_ingredient(
    ingredient: Ingredient, index: int, catalog: list[Unit]
) -> LineForm:
    """A row with the ingredient selected and its canonical unit chosen."""
    units = compatible_units(ingredient, catalog)
    return LineForm(
        index=index,
        ingredient_id=str(ingredient.id),
        ingredient_name=ingredient.name,
        canonical_symbol=ingredient.canonical_unit.symbol,
        canonical_name=ingredient.canonical_unit.name,
        entered_quantity="",
        entered_unit_id=str(ingredient.canonical_unit_id),
        notes="",
        units=units,
        errors={},
    )


def line_form_from_stored(
    line: RecipeIngredient, index: int, catalog: list[Unit]
) -> LineForm:
    """Editor row for a saved recipe line."""
    from app.formatting import format_quantity_input

    ingredient = line.ingredient
    return LineForm(
        index=index,
        ingredient_id=str(ingredient.id),
        ingredient_name=ingredient.name,
        canonical_symbol=ingredient.canonical_unit.symbol,
        canonical_name=ingredient.canonical_unit.name,
        entered_quantity=format_quantity_input(line.entered_quantity),
        entered_unit_id=str(line.entered_unit_id),
        notes=line.notes or "",
        units=compatible_units(ingredient, catalog),
        errors={},
    )


def line_form_from_raw(
    session: Session,
    raw: RawLine,
    index: int,
    catalog: list[Unit],
    errors: dict[str, str],
) -> LineForm:
    """Redisplay a posted row, including an incompatible unit the user chose."""
    ingredient = _ingredient(session, raw.ingredient_id)
    units = compatible_units(ingredient, catalog) if ingredient is not None else []
    posted_unit = _unit(session, raw.entered_unit_id)
    if posted_unit is not None and all(unit.id != posted_unit.id for unit in units):
        units = [*units, posted_unit]
    return LineForm(
        index=index,
        ingredient_id=raw.ingredient_id if ingredient is not None else "",
        ingredient_name="" if ingredient is None else ingredient.name,
        canonical_symbol="" if ingredient is None else ingredient.canonical_unit.symbol,
        canonical_name="" if ingredient is None else ingredient.canonical_unit.name,
        entered_quantity=raw.entered_quantity,
        entered_unit_id=raw.entered_unit_id,
        notes=raw.notes,
        units=units,
        errors=errors,
    )


def unit_catalog(session: Session) -> list[Unit]:
    """Every stored unit, for compatibility checks."""
    return list(session.scalars(select(Unit).order_by(Unit.name)))


def _meal_query() -> object:
    return select(Meal).options(
        selectinload(Meal.lines)
        .selectinload(RecipeIngredient.ingredient)
        .selectinload(Ingredient.canonical_unit),
        selectinload(Meal.lines)
        .selectinload(RecipeIngredient.ingredient)
        .selectinload(Ingredient.purchase_options),
        selectinload(Meal.lines)
        .selectinload(RecipeIngredient.ingredient)
        .selectinload(Ingredient.conversions),
        selectinload(Meal.lines).selectinload(RecipeIngredient.entered_unit),
    )


def _matches(meal: Meal, needle: str) -> bool:
    haystack = normalise_ingredient_name(meal.name)
    description = normalise_ingredient_name(meal.description or "")
    return needle in haystack or needle in description


def _prepare_one(
    session: Session, raw: RawLine, sort_order: int
) -> tuple[PreparedLine | None, dict[str, str]]:
    from app.services.parsing import parse_recipe_quantity
    from app.services.units import IncompatibleUnitError, InvalidQuantityError

    errors: dict[str, str] = {}
    ingredient = _ingredient(session, raw.ingredient_id)
    if ingredient is None:
        errors["ingredient_id"] = "Choose an ingredient, or create a new one."
    unit = _unit(session, raw.entered_unit_id)
    symbol = unit.symbol if unit is not None else "units"
    if ingredient is not None and unit is None:
        errors["entered_unit_id"] = (
            f"Choose a unit compatible with {ingredient.canonical_unit.name}."
        )
    quantity: Decimal | None = None
    try:
        quantity = parse_recipe_quantity(raw.entered_quantity, unit_symbol=symbol)
    except InvalidQuantityError as exc:
        errors["entered_quantity"] = str(exc)
    notes: str | None = None
    try:
        notes = _clean_line_notes(raw.notes)
    except FieldValidationError as exc:
        errors[exc.field] = str(exc)
    if errors or ingredient is None or unit is None or quantity is None:
        return None, errors
    if not _unit_allowed(ingredient, unit):
        errors["entered_unit_id"] = (
            f"{ingredient.name} is measured in {ingredient.canonical_unit.name}; "
            f"{unit.name} cannot be used."
        )
        return None, errors
    try:
        canonical_quantity = convert(
            quantity,
            unit,
            ingredient.canonical_unit,
            ingredient.conversions,
            ingredient_name=ingredient.name,
        )
    except IncompatibleUnitError as exc:
        errors["entered_unit_id"] = str(exc)
        return None, errors
    return (
        PreparedLine(
            ingredient=ingredient,
            entered_quantity=quantity,
            entered_unit=unit,
            canonical_quantity=canonical_quantity,
            notes=notes,
            sort_order=sort_order,
        ),
        {},
    )


def _unit_allowed(ingredient: Ingredient, unit: Unit) -> bool:
    allowed = compatible_units(ingredient, [unit])
    return any(candidate.id == unit.id for candidate in allowed)


def _same_metric_family(unit: Unit, canonical: Unit) -> bool:
    if unit.family != canonical.family or unit.family not in _METRIC:
        return False
    return unit.factor_to_base is not None and canonical.factor_to_base is not None


def _blank(raw: RawLine) -> bool:
    return not any(
        (
            raw.ingredient_id.strip(),
            raw.entered_quantity.strip(),
            raw.entered_unit_id.strip(),
            raw.notes.strip(),
        )
    )


def _ingredient(session: Session, raw_id: str) -> Ingredient | None:
    if not raw_id.strip():
        return None
    try:
        ingredient_id = int(raw_id)
    except ValueError:
        return None
    return session.scalar(
        select(Ingredient)
        .where(Ingredient.id == ingredient_id)
        .options(
            selectinload(Ingredient.canonical_unit),
            selectinload(Ingredient.conversions),
            selectinload(Ingredient.purchase_options),
        )
    )


def _unit(session: Session, raw_id: str) -> Unit | None:
    if not raw_id.strip():
        return None
    try:
        unit_id = int(raw_id)
    except ValueError:
        return None
    return session.get(Unit, unit_id)


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise FieldValidationError("name", "Enter a meal name.")
    if len(cleaned) > 200:
        raise FieldValidationError(
            "name", "Use a meal name of 200 characters or fewer."
        )
    return cleaned


def _clean_text(value: str | None, field: str, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise FieldValidationError(field, f"Use {limit} characters or fewer.")
    return cleaned


def _clean_line_notes(notes: str) -> str | None:
    cleaned = notes.strip()
    if not cleaned:
        return None
    if len(cleaned) > 500:
        raise FieldValidationError(
            "notes", "Line notes must be 500 characters or fewer."
        )
    return cleaned


def _copy_name(name: str) -> str:
    combined = f"Copy of {name}"
    if len(combined) <= 200:
        return combined
    return combined[:200].rstrip()
