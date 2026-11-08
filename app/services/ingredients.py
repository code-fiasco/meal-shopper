"""Ingredient names, archive rules, and list summaries."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Ingredient, PurchaseOption, Unit
from app.models.base import Base
from app.services.parsing import FieldValidationError
from app.services.units import unit_price_per_canonical


@dataclass(frozen=True)
class IngredientWrite:
    ingredient: Ingredient
    duplicate_warning: str | None


class DuplicateIngredient(ValueError):
    """The normalised name matches an existing ingredient and was not confirmed."""

    def __init__(self, warning: str) -> None:
        super().__init__(warning)
        self.warning = warning


class IngredientInUseError(ValueError):
    """Hard deletion is blocked because another record points at the ingredient."""


@dataclass(frozen=True)
class IngredientSummary:
    id: int
    name: str
    is_active: bool
    unit_symbol: str
    unit_name: str
    cheapest_unit_price: Decimal | None


@dataclass(frozen=True)
class PurchaseOptionView:
    id: int
    shop_name: str
    shop_is_active: bool
    pack_label: str
    pack_quantity: Decimal
    price_pence: int
    is_active: bool
    unit_price: Decimal
    unit_symbol: str


def normalise_ingredient_name(name: str) -> str:
    """Case-fold a name and collapse whitespace for duplicate checks."""
    return " ".join(name.casefold().split())


def find_likely_duplicates(
    session: Session, name: str, *, exclude_id: int | None = None
) -> list[Ingredient]:
    """Return ingredients whose normalised name matches."""
    target = normalise_ingredient_name(name)
    if not target:
        return []
    matches: list[Ingredient] = []
    for ingredient in session.scalars(select(Ingredient)):
        if exclude_id is not None and ingredient.id == exclude_id:
            continue
        if normalise_ingredient_name(ingredient.name) == target:
            matches.append(ingredient)
    return matches


def create_ingredient(
    session: Session,
    *,
    name: str,
    canonical_unit: Unit,
    notes: str | None = None,
    allow_duplicate: bool = True,
) -> IngredientWrite:
    """Save an ingredient. Unconfirmed duplicate names raise DuplicateIngredient."""
    cleaned = _clean_name(name)
    duplicates = find_likely_duplicates(session, cleaned)
    if duplicates and not allow_duplicate:
        raise DuplicateIngredient(_duplicate_warning(cleaned, duplicates))
    ingredient = Ingredient(
        name=cleaned,
        canonical_unit=canonical_unit,
        notes=_clean_notes(notes),
        is_active=True,
    )
    session.add(ingredient)
    session.flush()
    warning = _duplicate_warning(cleaned, duplicates)
    return IngredientWrite(ingredient=ingredient, duplicate_warning=warning)


def update_ingredient(
    session: Session,
    ingredient: Ingredient,
    *,
    name: str,
    canonical_unit: Unit,
    notes: str | None = None,
    allow_duplicate: bool = True,
) -> IngredientWrite:
    """Edit name, notes, and unit. Unit changes stop once packs exist."""
    cleaned = _clean_name(name)
    if canonical_unit.id != ingredient.canonical_unit_id and _has_pack_or_conversion(
        session, ingredient.id
    ):
        raise FieldValidationError(
            "canonical_unit_id",
            "This unit is already used by a purchase option. Archive those options "
            "before changing it.",
        )
    duplicates = find_likely_duplicates(session, cleaned, exclude_id=ingredient.id)
    if duplicates and not allow_duplicate:
        raise DuplicateIngredient(_duplicate_warning(cleaned, duplicates))
    ingredient.name = cleaned
    ingredient.canonical_unit = canonical_unit
    ingredient.notes = _clean_notes(notes)
    session.flush()
    warning = _duplicate_warning(cleaned, duplicates)
    return IngredientWrite(ingredient=ingredient, duplicate_warning=warning)


def set_default_purchase_option(
    ingredient: Ingredient, option: PurchaseOption | None
) -> Ingredient:
    """Choose which active pack recipe costing should use."""
    if option is not None and option.ingredient_id != ingredient.id:
        raise FieldValidationError(
            "default",
            "Choose a purchase option that belongs to this ingredient.",
        )
    ingredient.default_purchase_option_id = None if option is None else option.id
    return ingredient


def set_ingredient_active(
    session: Session, ingredient: Ingredient, *, active: bool
) -> Ingredient:
    """Archive or restore an ingredient without removing its history."""
    ingredient.is_active = active
    session.flush()
    return ingredient


def delete_ingredient(session: Session, ingredient: Ingredient) -> None:
    """Refuse hard deletion. Referenced ingredients must be archived."""
    if ingredient_in_use(session, ingredient.id):
        raise IngredientInUseError(
            "Archive this ingredient instead of deleting it. "
            "Other records still refer to it."
        )
    raise IngredientInUseError("Archive this ingredient instead of deleting it.")


def ingredient_in_use(session: Session, ingredient_id: int) -> bool:
    """True when any other table stores this ingredient id."""
    for table in Base.metadata.tables.values():
        if table.name == "ingredients":
            continue
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                if foreign_key.column.table.name != "ingredients":
                    continue
                found = session.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(column == ingredient_id)
                )
                if found:
                    return True
    return False


def list_ingredients(
    session: Session, *, query: str = "", status: str = "active"
) -> list[IngredientSummary]:
    """List ingredients with their canonical unit and cheapest active unit price."""
    statement = (
        select(Ingredient)
        .options(
            selectinload(Ingredient.canonical_unit),
            selectinload(Ingredient.purchase_options),
        )
        .order_by(Ingredient.name)
    )
    if status == "active":
        statement = statement.where(Ingredient.is_active.is_(True))
    elif status == "archived":
        statement = statement.where(Ingredient.is_active.is_(False))
    rows = list(session.scalars(statement))
    needle = normalise_ingredient_name(query)
    if needle:
        rows = [row for row in rows if needle in normalise_ingredient_name(row.name)]
    return [_summary(row) for row in rows]


def get_ingredient(session: Session, ingredient_id: int) -> Ingredient | None:
    """Load an ingredient with its unit, packs, and shops."""
    return session.scalar(
        select(Ingredient)
        .where(Ingredient.id == ingredient_id)
        .options(
            selectinload(Ingredient.canonical_unit),
            selectinload(Ingredient.purchase_options).selectinload(PurchaseOption.shop),
        )
    )


def purchase_option_views(ingredient: Ingredient) -> list[PurchaseOptionView]:
    """Describe each pack for display. Nothing is marked as the chosen option."""
    views = [
        PurchaseOptionView(
            id=option.id,
            shop_name=option.shop.name,
            shop_is_active=option.shop.is_active,
            pack_label=option.pack_label,
            pack_quantity=option.pack_quantity,
            price_pence=option.price_pence,
            is_active=option.is_active,
            unit_price=unit_price_per_canonical(option),
            unit_symbol=ingredient.canonical_unit.symbol,
        )
        for option in ingredient.purchase_options
    ]
    return sorted(views, key=lambda view: (not view.is_active, view.shop_name.lower()))


def _summary(ingredient: Ingredient) -> IngredientSummary:
    return IngredientSummary(
        id=ingredient.id,
        name=ingredient.name,
        is_active=ingredient.is_active,
        unit_symbol=ingredient.canonical_unit.symbol,
        unit_name=ingredient.canonical_unit.name,
        cheapest_unit_price=_cheapest_active_unit_price(ingredient),
    )


def _cheapest_active_unit_price(ingredient: Ingredient) -> Decimal | None:
    prices = [
        unit_price_per_canonical(option)
        for option in ingredient.purchase_options
        if option.is_active
    ]
    if not prices:
        return None
    return min(prices)


def collect_ingredient_errors(
    *, name: str, notes: str | None, unit: Unit | None
) -> dict[str, str]:
    """Return every field message so the form can show them together."""
    errors: dict[str, str] = {}
    if unit is None:
        errors["canonical_unit_id"] = "Choose a unit, such as g or slice."
    try:
        _clean_name(name)
    except FieldValidationError as exc:
        errors[exc.field] = str(exc)
    try:
        _clean_notes(notes)
    except FieldValidationError as exc:
        errors[exc.field] = str(exc)
    return errors


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise FieldValidationError("name", "Enter an ingredient name.")
    if len(cleaned) > 200:
        raise FieldValidationError("name", "Use a name of 200 characters or fewer.")
    return cleaned


def _clean_notes(notes: str | None) -> str | None:
    if notes is None:
        return None
    cleaned = notes.strip()
    if not cleaned:
        return None
    if len(cleaned) > 2000:
        raise FieldValidationError("notes", "Notes must be 2000 characters or fewer.")
    return cleaned


def _has_pack_or_conversion(session: Session, ingredient_id: int) -> bool:
    pack = session.scalar(
        select(PurchaseOption.id).where(PurchaseOption.ingredient_id == ingredient_id)
    )
    if pack is not None:
        return True
    return ingredient_in_use(session, ingredient_id)


def _duplicate_warning(name: str, duplicates: list[Ingredient]) -> str | None:
    if not duplicates:
        return None
    existing = duplicates[0].name
    return f"'{name}' looks like a duplicate of '{existing}'."
