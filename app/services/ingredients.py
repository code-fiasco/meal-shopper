"""Ingredient names and likely-duplicate warnings."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, Unit


@dataclass(frozen=True)
class IngredientWrite:
    ingredient: Ingredient
    duplicate_warning: str | None


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
    session: Session, *, name: str, canonical_unit: Unit, notes: str | None = None
) -> IngredientWrite:
    """Save an ingredient and warn when the normalised name already exists."""
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise ValueError("Ingredient name is required.")
    duplicates = find_likely_duplicates(session, cleaned)
    ingredient = Ingredient(
        name=cleaned,
        canonical_unit=canonical_unit,
        notes=notes,
        is_active=True,
    )
    session.add(ingredient)
    session.flush()
    warning = _duplicate_warning(cleaned, duplicates)
    return IngredientWrite(ingredient=ingredient, duplicate_warning=warning)


def _duplicate_warning(name: str, duplicates: list[Ingredient]) -> str | None:
    if not duplicates:
        return None
    existing = duplicates[0].name
    return f"'{name}' looks like a duplicate of '{existing}'."
