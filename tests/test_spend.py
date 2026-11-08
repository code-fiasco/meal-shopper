"""Weekly spend: unrecorded weeks, estimates, several shops, and takeaway."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    PurchaseOption,
    Shop,
    ShoppingList,
    ShoppingListLine,
    ShoppingTransaction,
    ShoppingTransactionLine,
    Unit,
)
from app.services.ingredients import create_ingredient
from app.services.meals import RawLine, prepare_lines, save_meal
from app.services.parsing import FieldValidationError
from app.services.planner import assign_meal, assign_takeaway, get_week
from app.services.purchase_options import change_purchase_option, create_purchase_option
from app.services.shopping import generate_shopping_list
from app.services.spend import (
    LineAdjustment,
    SpendFormError,
    record_spend,
    record_spend_from_form,
    spend_report,
)

MONDAY = date(2026, 11, 2)


def _unit(session: Session, symbol: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    return unit


def _meal(session: Session, name: str, lines: list[RawLine]):
    prepared, errors = prepare_lines(session, lines)
    assert errors == {}
    return save_meal(
        session,
        None,
        name=name,
        description=None,
        instructions=None,
        lines=prepared,
    )


def _priced_list(session: Session) -> tuple[ShoppingList, PurchaseOption]:
    grams = _unit(session, "g")
    beef = create_ingredient(
        session, name="Minced beef", canonical_unit=grams
    ).ingredient
    shop = Shop(name="Butcher", is_active=True)
    session.add(shop)
    session.flush()
    option = create_purchase_option(
        session,
        ingredient=beef,
        shop=shop,
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(
        session,
        "Ragu",
        [RawLine(str(beef.id), "200", str(grams.id), "")],
    )
    assign_meal(session, plan_date=MONDAY, slot="lunch", meal_id=meal.id)
    week = get_week(session, MONDAY)
    assert week is not None
    return generate_shopping_list(session, week.id), option


def _beef_line(shopping_list: ShoppingList) -> ShoppingListLine:
    found = [line for line in shopping_list.lines if line.description == "Minced beef"]
    assert len(found) == 1
    return found[0]


def test_unrecorded_week_is_not_zero_and_takeaway_stays_separate(
    session: Session,
) -> None:
    assign_takeaway(
        session,
        plan_date=MONDAY,
        slot="dinner",
        price="12.50",
        description="Curry",
    )
    report = spend_report(session, end=MONDAY, week_count=2)
    previous, current = report.weeks

    assert previous.grocery_pence is None
    assert previous.takeaway_pence == 0
    assert previous.status == "incomplete"
    assert current.grocery_pence is None
    assert current.takeaway_pence == 1250
    assert current.status == "incomplete"
    assert current.combined_pence is None
    assert report.grocery_recorded_pence == 0
    assert report.grocery_average_pence is None
    assert report.unrecorded_week_count == 2
    assert report.takeaway_pence == 1250
    assert report.combined_recorded_pence == 1250
    assert report.chart_payload()["grocery"] == [None, None]
    assert report.chart_payload()["takeaway"] == [0, 1250]


def test_actual_spend_sums_shops_and_keeps_the_estimate_separate(
    session: Session,
) -> None:
    shopping_list, option = _priced_list(session)
    assign_takeaway(
        session,
        plan_date=MONDAY + timedelta(days=1),
        slot="dinner",
        price="12.50",
        description="Curry",
    )
    before = spend_report(session, end=MONDAY, week_count=2)
    estimated = before.weeks[1]
    assert estimated.status == "estimated"
    assert estimated.grocery_pence is None
    assert estimated.estimated_pence == 350
    assert estimated.takeaway_pence == 1250
    assert estimated.combined_pence == 1600

    change_purchase_option(session, option, price_pence=999)
    line = _beef_line(shopping_list)
    assert line.pack_price_pence == 350
    record_spend(
        session,
        shopping_list=shopping_list,
        spent_on=MONDAY,
        actual_total_pence=800,
        notes=None,
        lines=[LineAdjustment(line.id, Decimal("200"), 100, None)],
    )
    record_spend(
        session,
        shopping_list=shopping_list,
        spent_on=MONDAY + timedelta(days=1),
        actual_total_pence=200,
        notes="Top up",
        lines=[],
    )
    change_purchase_option(session, option, price_pence=100)

    report = spend_report(session, end=MONDAY, week_count=2)
    previous, current = report.weeks
    assert previous.grocery_pence is None
    assert previous.status == "incomplete"
    assert current.grocery_pence == 1000
    assert current.estimated_pence == 350
    assert current.takeaway_pence == 1250
    assert current.status == "actual"
    assert current.status_label == "Actual"
    assert current.combined_pence == 2250
    assert report.grocery_recorded_pence == 1000
    assert report.recorded_week_count == 1
    assert report.grocery_average_pence == 1000
    assert report.unrecorded_week_count == 1
    assert report.combined_recorded_pence == 2250
    payload = report.chart_payload()
    assert payload["grocery"] == [None, 1000]
    assert payload["estimated"] == [None, 350]
    assert payload["takeaway"] == [0, 1250]
    saved = session.scalars(select(ShoppingTransactionLine)).one()
    assert saved.description == "Minced beef"
    assert saved.actual_quantity == Decimal("200")
    assert saved.unit_snapshot == "g"
    assert saved.actual_price_pence == 100
    line.description = "Renamed later"
    session.flush()
    assert saved.description == "Minced beef"
    assert line.pack_price_pence == 350
    assert option.price_pence == 100
    assert shopping_list.status == "shopped"


def test_blank_total_is_not_copied_from_the_estimate(session: Session) -> None:
    shopping_list, _option = _priced_list(session)
    with pytest.raises(SpendFormError) as caught:
        record_spend_from_form(
            session,
            shopping_list,
            {"total": "", "spent_on": MONDAY.isoformat(), "notes": ""},
        )
    assert caught.value.errors["total"].startswith("Enter the amount you paid")
    assert session.scalars(select(ShoppingTransaction)).first() is None

    record_spend_from_form(
        session,
        shopping_list,
        {"total": "0", "spent_on": MONDAY.isoformat(), "notes": ""},
    )
    current = spend_report(session, end=MONDAY, week_count=1).weeks[0]
    assert current.grocery_pence == 0
    assert current.status == "actual"
    assert current.estimated_pence == 350


def test_negative_line_quantity_is_rejected(session: Session) -> None:
    shopping_list, _option = _priced_list(session)
    line = _beef_line(shopping_list)
    with pytest.raises(SpendFormError) as caught:
        record_spend_from_form(
            session,
            shopping_list,
            {
                "total": "8.00",
                "spent_on": MONDAY.isoformat(),
                "notes": "",
                f"qty-{line.id}": "-1",
            },
        )
    assert f"qty-{line.id}" in caught.value.errors
    assert session.scalars(select(ShoppingTransaction)).first() is None


def test_missing_price_is_incomplete(session: Session) -> None:
    grams = _unit(session, "g")
    oats = create_ingredient(session, name="Oats", canonical_unit=grams).ingredient
    meal = _meal(
        session,
        "Porridge",
        [RawLine(str(oats.id), "80", str(grams.id), "")],
    )
    assign_meal(session, plan_date=MONDAY, slot="lunch", meal_id=meal.id)
    week = get_week(session, MONDAY)
    assert week is not None
    generate_shopping_list(session, week.id)
    current = spend_report(session, end=MONDAY, week_count=1).weeks[0]
    assert current.grocery_pence is None
    assert current.status == "incomplete"
    assert current.status_label == "Incomplete"
    assert current.combined_pence is None


def test_week_count_must_be_in_range(session: Session) -> None:
    with pytest.raises(FieldValidationError):
        spend_report(session, end=MONDAY, week_count=0)
