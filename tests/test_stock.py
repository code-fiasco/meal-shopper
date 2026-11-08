"""Pantry quantities stay in canonical units and never go below zero."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PantryStock, Unit
from app.services.ingredients import create_ingredient
from app.services.meals import RawLine, prepare_lines, save_meal
from app.services.parsing import FieldValidationError
from app.services.planner import assign_meal
from app.services.stock import (
    ADD,
    CLEAR,
    SET,
    SUBTRACT,
    adjust_stock,
    get_stock_map,
    list_stock_controls,
)


def _unit(session: Session, symbol: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    return unit


def test_set_converts_kilograms_to_canonical_grams(session: Session) -> None:
    grams = _unit(session, "g")
    kilograms = _unit(session, "kg")
    sugar = create_ingredient(session, name="Sugar", canonical_unit=grams).ingredient
    row = adjust_stock(
        session,
        ingredient_id=sugar.id,
        action=SET,
        quantity="1",
        unit_id=str(kilograms.id),
    )
    assert row.quantity_on_hand == Decimal("1000")
    assert isinstance(row.quantity_on_hand, Decimal)
    assert get_stock_map(session) == {sugar.id: Decimal("1000")}
    listed = list_stock_controls(session)
    assert [item.ingredient_name for item in listed] == ["Sugar"]
    assert listed[0].quantity == Decimal("1000")


def test_add_converts_before_it_changes_the_canonical_quantity(
    session: Session,
) -> None:
    grams = _unit(session, "g")
    kilograms = _unit(session, "kg")
    sugar = create_ingredient(session, name="Sugar", canonical_unit=grams).ingredient
    adjust_stock(
        session,
        ingredient_id=sugar.id,
        action=SET,
        quantity="200",
        unit_id=str(grams.id),
    )
    row = adjust_stock(
        session,
        ingredient_id=sugar.id,
        action=ADD,
        quantity="1",
        unit_id=str(kilograms.id),
    )
    assert row.quantity_on_hand == Decimal("1200")


def test_incompatible_unit_is_rejected_and_stock_is_unchanged(
    session: Session,
) -> None:
    grams = _unit(session, "g")
    slices = _unit(session, "slice")
    ham = create_ingredient(session, name="Ham", canonical_unit=slices).ingredient
    adjust_stock(
        session,
        ingredient_id=ham.id,
        action=SET,
        quantity="4",
        unit_id=str(slices.id),
    )
    with pytest.raises(FieldValidationError, match="gram cannot be used") as caught:
        adjust_stock(
            session,
            ingredient_id=ham.id,
            action=SUBTRACT,
            quantity="100",
            unit_id=str(grams.id),
        )
    assert caught.value.field == "unit_id"
    assert "Ham is measured in slice" in str(caught.value)
    assert get_stock_map(session)[ham.id] == Decimal("4")


def test_rejected_unit_does_not_create_a_stock_row(session: Session) -> None:
    grams = _unit(session, "g")
    slices = _unit(session, "slice")
    ham = create_ingredient(session, name="Ham", canonical_unit=slices).ingredient
    with pytest.raises(FieldValidationError, match="gram cannot be used"):
        adjust_stock(
            session,
            ingredient_id=ham.id,
            action=SET,
            quantity="100",
            unit_id=str(grams.id),
        )
    assert session.get(PantryStock, ham.id) is None
    assert get_stock_map(session) == {}


def test_subtract_never_goes_below_zero(session: Session) -> None:
    grams = _unit(session, "g")
    sugar = create_ingredient(session, name="Sugar", canonical_unit=grams).ingredient
    adjust_stock(
        session,
        ingredient_id=sugar.id,
        action=SET,
        quantity="200",
        unit_id=str(grams.id),
    )
    with pytest.raises(FieldValidationError, match="below zero") as caught:
        adjust_stock(
            session,
            ingredient_id=sugar.id,
            action=SUBTRACT,
            quantity="250",
            unit_id=str(grams.id),
        )
    assert caught.value.field == "quantity"
    assert "200g is in stock" in str(caught.value)
    assert get_stock_map(session)[sugar.id] == Decimal("200")
    row = adjust_stock(
        session,
        ingredient_id=sugar.id,
        action=SUBTRACT,
        quantity="200",
        unit_id=str(grams.id),
    )
    assert row.quantity_on_hand == Decimal("0")
    assert list_stock_controls(session) == []
    assert get_stock_map(session) == {sugar.id: Decimal("0")}


def test_none_left_records_zero(session: Session) -> None:
    eggs = _unit(session, "egg")
    egg = create_ingredient(session, name="Eggs", canonical_unit=eggs).ingredient
    adjust_stock(
        session,
        ingredient_id=egg.id,
        action=SET,
        quantity="6",
        unit_id=str(eggs.id),
    )
    row = adjust_stock(
        session,
        ingredient_id=egg.id,
        action=CLEAR,
        quantity="",
        unit_id="",
    )
    assert row.quantity_on_hand == Decimal("0")
    assert list_stock_controls(session) == []
    assert get_stock_map(session)[egg.id] == Decimal("0")


def test_planning_a_meal_does_not_change_stock(session: Session) -> None:
    grams = _unit(session, "g")
    rice = create_ingredient(session, name="Rice", canonical_unit=grams).ingredient
    adjust_stock(
        session,
        ingredient_id=rice.id,
        action=SET,
        quantity="500",
        unit_id=str(grams.id),
    )
    prepared, errors = prepare_lines(
        session, [RawLine(str(rice.id), "200", str(grams.id), "")]
    )
    assert errors == {}
    meal = save_meal(
        session,
        None,
        name="Fried rice",
        description=None,
        instructions=None,
        lines=prepared,
    )
    assign_meal(session, plan_date=date(2026, 11, 2), slot="lunch", meal_id=meal.id)
    assert get_stock_map(session)[rice.id] == Decimal("500")
