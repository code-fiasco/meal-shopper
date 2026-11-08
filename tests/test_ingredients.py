"""Ingredient duplicate warnings."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Unit
from app.services.ingredients import (
    create_ingredient,
    find_likely_duplicates,
    normalise_ingredient_name,
)


def _unit(session: Session, symbol: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    return unit


def test_normalise_folds_case_and_whitespace() -> None:
    assert normalise_ingredient_name("  Honey   Roast HAM ") == "honey roast ham"


def test_likely_duplicate_warning_uses_normalised_names(session: Session) -> None:
    slices = _unit(session, "slice")
    first = create_ingredient(session, name="Honey roast ham", canonical_unit=slices)
    assert first.duplicate_warning is None

    second = create_ingredient(
        session, name="  HONEY   roast ham ", canonical_unit=slices
    )
    assert second.duplicate_warning == (
        "'HONEY roast ham' looks like a duplicate of 'Honey roast ham'."
    )
    matches = find_likely_duplicates(session, "honey roast ham")
    assert matches[0].id == first.ingredient.id
    assert (
        find_likely_duplicates(
            session, "honey roast ham", exclude_id=first.ingredient.id
        )[0].id
        == second.ingredient.id
    )


def test_different_names_do_not_warn(session: Session) -> None:
    grams = _unit(session, "g")
    create_ingredient(session, name="Caster sugar", canonical_unit=grams)
    other = create_ingredient(session, name="Icing sugar", canonical_unit=grams)
    assert other.duplicate_warning is None


def test_blank_ingredient_name_is_rejected(session: Session) -> None:
    grams = _unit(session, "g")
    try:
        create_ingredient(session, name="   ", canonical_unit=grams)
    except ValueError as exc:
        assert "name" in str(exc).lower()
    else:
        raise AssertionError("blank name was accepted")
