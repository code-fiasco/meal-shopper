"""Ingredient duplicate warnings, archive, and list prices."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Ingredient, Shop, Unit
from app.services.ingredients import (
    DuplicateIngredient,
    IngredientInUseError,
    create_ingredient,
    delete_ingredient,
    find_likely_duplicates,
    list_ingredients,
    normalise_ingredient_name,
    set_ingredient_active,
)
from app.services.purchase_options import change_purchase_option, create_purchase_option


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


def test_unconfirmed_duplicate_is_not_saved(session: Session) -> None:
    grams = _unit(session, "g")
    create_ingredient(session, name="Plain flour", canonical_unit=grams)
    with pytest.raises(DuplicateIngredient, match="duplicate"):
        create_ingredient(
            session,
            name="plain flour",
            canonical_unit=grams,
            allow_duplicate=False,
        )
    stored = session.scalar(select(func.count()).select_from(Ingredient))
    assert stored == 1


def test_archive_hides_ingredient_until_restored(session: Session) -> None:
    grams = _unit(session, "g")
    created = create_ingredient(session, name="Rice", canonical_unit=grams)
    set_ingredient_active(session, created.ingredient, active=False)
    assert list_ingredients(session, status="active") == []
    archived = list_ingredients(session, status="archived")
    assert archived[0].name == "Rice"
    assert archived[0].is_active is False
    set_ingredient_active(session, created.ingredient, active=True)
    assert list_ingredients(session, status="active")[0].name == "Rice"


def test_search_matches_normalised_name(session: Session) -> None:
    slices = _unit(session, "slice")
    create_ingredient(session, name="Honey roast ham", canonical_unit=slices)
    found = list_ingredients(session, query="  honey ")
    assert [item.name for item in found] == ["Honey roast ham"]


def test_cheapest_unit_price_ignores_archived_options(session: Session) -> None:
    grams = _unit(session, "g")
    created = create_ingredient(session, name="Flour", canonical_unit=grams)
    cheap_shop = Shop(name="Budget", is_active=True)
    other_shop = Shop(name="Corner", is_active=True)
    session.add_all([cheap_shop, other_shop])
    session.flush()
    cheaper = create_purchase_option(
        session,
        ingredient=created.ingredient,
        shop=cheap_shop,
        pack_quantity=Decimal("1000"),
        pack_label="1kg bag",
        price_pence=100,
    )
    create_purchase_option(
        session,
        ingredient=created.ingredient,
        shop=other_shop,
        pack_quantity=Decimal("500"),
        pack_label="500g bag",
        price_pence=80,
    )
    listed = list_ingredients(session)[0]
    assert listed.cheapest_unit_price == Decimal("0.1")
    assert listed.unit_symbol == "g"
    change_purchase_option(session, cheaper, is_active=False)
    session.expire(created.ingredient, ["purchase_options"])
    after = list_ingredients(session)[0]
    assert after.cheapest_unit_price == Decimal("0.16")


def test_ingredient_without_a_price_reports_none(session: Session) -> None:
    grams = _unit(session, "g")
    create_ingredient(session, name="Salt", canonical_unit=grams)
    listed = list_ingredients(session)[0]
    assert listed.cheapest_unit_price is None


def test_referenced_ingredient_cannot_be_deleted(session: Session) -> None:
    grams = _unit(session, "g")
    created = create_ingredient(session, name="Butter", canonical_unit=grams)
    shop = Shop(name="Market", is_active=True)
    session.add(shop)
    session.flush()
    create_purchase_option(
        session,
        ingredient=created.ingredient,
        shop=shop,
        pack_quantity=Decimal("250"),
        pack_label="block",
        price_pence=200,
    )
    with pytest.raises(IngredientInUseError, match="Archive"):
        delete_ingredient(session, created.ingredient)
    still_there = session.get(Ingredient, created.ingredient.id)
    assert still_there is not None
