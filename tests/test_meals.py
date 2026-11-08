"""Recipe lines, two-person costing, and meal copies."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Ingredient, Meal, Shop, Unit
from app.services.costing import cost_lines, costing_option
from app.services.ingredients import create_ingredient, delete_ingredient
from app.services.meals import (
    RawLine,
    compatible_units,
    cost_meal,
    duplicate_meal,
    historical_planner_entries,
    prepare_lines,
    save_meal,
    unit_catalog,
)
from app.services.purchase_options import create_purchase_option
from app.services.units import allocated_cost_pence


def _unit(session: Session, symbol: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    return unit


def test_complete_recipe_cost_uses_canonical_quantity(session: Session) -> None:
    grams = _unit(session, "g")
    kilograms = _unit(session, "kg")
    slices = _unit(session, "slice")
    sugar = create_ingredient(session, name="Sugar", canonical_unit=grams).ingredient
    ham = create_ingredient(session, name="Ham", canonical_unit=slices).ingredient
    shop = Shop(name="Market", is_active=True)
    session.add(shop)
    session.flush()
    create_purchase_option(
        session,
        ingredient=sugar,
        shop=shop,
        pack_quantity=Decimal("1000"),
        pack_label="1kg bag",
        price_pence=250,
    )
    create_purchase_option(
        session,
        ingredient=ham,
        shop=shop,
        pack_quantity=Decimal("10"),
        pack_label="10 pack",
        price_pence=179,
    )
    meal = save_meal(
        session,
        None,
        name="Toast",
        description=None,
        instructions=None,
        lines=_lines(
            session,
            [
                RawLine(str(sugar.id), "1", str(kilograms.id), ""),
                RawLine(str(ham.id), "6", str(slices.id), ""),
            ],
        ),
    )
    cost = cost_meal(meal)
    ham_price = Decimal(179) / Decimal(10)
    assert cost.is_complete is True
    assert cost.missing_ingredients == ()
    assert cost.lines[0].canonical_quantity == Decimal("1000")
    assert cost.lines[0].cost_pence == 250
    assert cost.lines[1].cost_pence == allocated_cost_pence(Decimal("6"), ham_price)
    assert cost.lines[1].cost_pence == 107
    assert cost.total_pence == 357
    assert cost.per_person_pence == Decimal(357) / Decimal(2)


def test_missing_price_is_not_counted_as_zero(session: Session) -> None:
    grams = _unit(session, "g")
    sugar = create_ingredient(session, name="Sugar", canonical_unit=grams).ingredient
    salt = create_ingredient(session, name="Salt", canonical_unit=grams).ingredient
    shop = Shop(name="Market", is_active=True)
    session.add(shop)
    session.flush()
    create_purchase_option(
        session,
        ingredient=sugar,
        shop=shop,
        pack_quantity=Decimal("1000"),
        pack_label="bag",
        price_pence=250,
    )
    meal = save_meal(
        session,
        None,
        name="Porridge",
        description=None,
        instructions=None,
        lines=_lines(
            session,
            [
                RawLine(str(sugar.id), "100", str(grams.id), ""),
                RawLine(str(salt.id), "5", str(grams.id), ""),
            ],
        ),
    )
    cost = cost_meal(meal)
    assert cost.is_complete is False
    assert cost.missing_ingredients == ("Salt",)
    assert cost.lines[1].cost_pence is None
    assert cost.total_pence == 25
    assert cost.per_person_pence is None
    assert cost.incomplete_label() == "incomplete: missing price for Salt"


def test_designated_option_beats_the_cheapest(session: Session) -> None:
    grams = _unit(session, "g")
    flour = create_ingredient(session, name="Flour", canonical_unit=grams).ingredient
    cheap = Shop(name="Budget", is_active=True)
    dear = Shop(name="Corner", is_active=True)
    session.add_all([cheap, dear])
    session.flush()
    create_purchase_option(
        session,
        ingredient=flour,
        shop=cheap,
        pack_quantity=Decimal("1000"),
        pack_label="bag",
        price_pence=100,
    )
    preferred = create_purchase_option(
        session,
        ingredient=flour,
        shop=dear,
        pack_quantity=Decimal("1000"),
        pack_label="local bag",
        price_pence=300,
    )
    flour.default_purchase_option_id = preferred.id
    session.flush()
    chosen = costing_option(flour)
    assert chosen is not None
    assert chosen.id == preferred.id
    cost = cost_lines([(flour, Decimal("1000"), "g", Decimal("1000"), "g")])
    assert cost.total_pence == 300


def test_incompatible_unit_is_rejected_with_the_canonical_name(
    session: Session,
) -> None:
    slices = _unit(session, "slice")
    grams = _unit(session, "g")
    ham = create_ingredient(session, name="Ham", canonical_unit=slices).ingredient
    _prepared, errors = prepare_lines(
        session, [RawLine(str(ham.id), "100", str(grams.id), "")]
    )
    message = errors[0]["entered_unit_id"]
    assert "Ham is measured in slice" in message
    assert "gram cannot be used" in message
    stored = session.scalar(select(func.count()).select_from(Meal))
    assert stored == 0


def test_weight_units_are_compatible_and_count_units_are_not(session: Session) -> None:
    grams = _unit(session, "g")
    sugar = create_ingredient(session, name="Sugar", canonical_unit=grams).ingredient
    symbols = {unit.symbol for unit in compatible_units(sugar, unit_catalog(session))}
    assert {"mg", "g", "kg"} <= symbols
    assert "slice" not in symbols


def test_duplicate_meal_copies_lines(session: Session) -> None:
    slices = _unit(session, "slice")
    ham = create_ingredient(session, name="Ham", canonical_unit=slices).ingredient
    original = save_meal(
        session,
        None,
        name="Ham sandwich",
        description="quick",
        instructions="Toast the bread.",
        lines=_lines(session, [RawLine(str(ham.id), "2", str(slices.id), "thick")]),
    )
    copy = duplicate_meal(session, original)
    assert copy.id != original.id
    assert copy.name == "Copy of Ham sandwich"
    assert copy.description == "quick"
    assert copy.instructions == "Toast the bread."
    assert len(copy.lines) == 1
    assert copy.lines[0].id != original.lines[0].id
    assert copy.lines[0].quantity == Decimal("2")
    assert copy.lines[0].notes == "thick"
    assert len(original.lines) == 1


def test_planner_check_is_empty_until_planner_entries_exist(session: Session) -> None:
    assert historical_planner_entries(session, 1) == []


def test_recipe_use_blocks_ingredient_deletion(session: Session) -> None:
    slices = _unit(session, "slice")
    ham = create_ingredient(session, name="Ham", canonical_unit=slices).ingredient
    save_meal(
        session,
        None,
        name="Ham sandwich",
        description=None,
        instructions=None,
        lines=_lines(session, [RawLine(str(ham.id), "2", str(slices.id), "")]),
    )
    with pytest.raises(ValueError, match="Archive"):
        delete_ingredient(session, ham)
    assert session.get(Ingredient, ham.id) is not None


def _lines(session: Session, raw_lines: list[RawLine]) -> list:
    prepared, errors = prepare_lines(session, raw_lines)
    assert errors == {}
    return prepared
