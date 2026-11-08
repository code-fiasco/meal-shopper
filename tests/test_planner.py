"""Week boundaries, planner slots, and costs kept apart from takeaway."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PlannerEntry, PlannerWeek, Shop, Unit
from app.services.ingredients import create_ingredient
from app.services.meals import (
    MealInUseError,
    RawLine,
    delete_meal,
    historical_planner_entries,
    prepare_lines,
    save_meal,
    set_meal_active,
)
from app.services.parsing import FieldValidationError
from app.services.planner import (
    assign_blank,
    assign_meal,
    assign_takeaway,
    build_week,
    entries_for_week,
    format_week_range,
    get_week,
    ingredient_requirements,
    local_today,
    week_cost,
    week_start_for,
)
from app.services.purchase_options import create_purchase_option


def test_week_starts_on_monday() -> None:
    sunday = date(2026, 11, 8)
    monday = date(2026, 11, 2)
    assert week_start_for(sunday) == monday
    assert week_start_for(monday) == monday
    assert week_start_for(date(2026, 11, 3)) == monday
    assert format_week_range(sunday) == "2–8 Nov 2026"
    assert format_week_range(date(2026, 11, 30)) == "30 Nov – 6 Dec 2026"
    assert format_week_range(date(2026, 12, 28)) == "28 Dec 2026 – 3 Jan 2027"


def test_local_today_follows_the_configured_timezone() -> None:
    after_midnight_in_london = datetime(2026, 11, 9, 0, 30, tzinfo=UTC)
    assert local_today("Europe/London", after_midnight_in_london) == date(2026, 11, 9)
    london_week = week_start_for(local_today("Europe/London", after_midnight_in_london))
    assert london_week == date(2026, 11, 9)
    new_york_day = local_today("America/New_York", after_midnight_in_london)
    assert new_york_day == date(2026, 11, 8)
    new_york_week = week_start_for(
        local_today("America/New_York", after_midnight_in_london)
    )
    assert new_york_week == date(2026, 11, 2)

    still_sunday_in_london = datetime(2026, 11, 8, 23, 30, tzinfo=UTC)
    auckland_day = local_today("Pacific/Auckland", still_sunday_in_london)
    assert auckland_day == date(2026, 11, 9)
    assert week_start_for(auckland_day) == date(2026, 11, 9)
    assert week_start_for(local_today("Europe/London", still_sunday_in_london)) == date(
        2026, 11, 2
    )


def test_week_is_created_when_a_slot_is_saved(session: Session) -> None:
    monday = date(2026, 11, 2)
    build_week(session, monday, today=monday)
    assert session.scalar(select(func.count()).select_from(PlannerWeek)) == 0
    assign_blank(session, plan_date=date(2026, 11, 4), slot="dinner")
    week = get_week(session, date(2026, 11, 4))
    assert week is not None
    assert week.week_start_date == monday
    assert week.status == "open"
    stored = entries_for_week(session, monday)
    assert len(stored) == 1
    assert stored[0].plan_date == date(2026, 11, 4)
    assert stored[0].entry_type == "blank"


def test_entries_persist_on_past_and_future_weeks(session: Session) -> None:
    meal = _rice_meal(session)
    past = date(2026, 10, 5)
    future = date(2026, 12, 7)
    assign_meal(session, plan_date=past, slot="lunch", meal_id=meal.id)
    tuesday = future + timedelta(days=1)
    assign_meal(session, plan_date=tuesday, slot="dinner", meal_id=meal.id)
    past_entries = entries_for_week(session, past)
    future_entries = entries_for_week(session, future)
    current_entries = entries_for_week(session, date(2026, 11, 2))
    assert [entry.plan_date for entry in past_entries] == [past]
    assert [entry.plan_date for entry in future_entries] == [tuesday]
    assert current_entries == []
    assert past_entries[0].snapshot_meal_name == "Fried rice"
    assert future_entries[0].meal_id == meal.id


def test_takeaway_requires_a_non_negative_price_and_adds_no_ingredients(
    session: Session,
) -> None:
    meal = _rice_meal(session, quantity="200")
    day = date(2026, 11, 2)
    with pytest.raises(FieldValidationError, match="Enter a price"):
        assign_takeaway(
            session, plan_date=day, slot="dinner", price="", description="Pizza"
        )
    with pytest.raises(FieldValidationError, match="negative"):
        assign_takeaway(
            session, plan_date=day, slot="dinner", price="-1", description=None
        )
    assert get_week(session, day) is None
    meal_slot = assign_meal(session, plan_date=day, slot="lunch", meal_id=meal.id)
    takeaway = assign_takeaway(
        session,
        plan_date=day,
        slot="dinner",
        price="0",
        description="  ",
    )
    assert takeaway.takeaway_price_pence == 0
    assert takeaway.takeaway_description is None
    needs = ingredient_requirements([meal_slot, takeaway])
    assert len(needs) == 1
    assert needs[0].ingredient_name == "Rice"
    assert needs[0].quantity == Decimal("200")
    assert needs[0].unit_symbol == "g"
    priced = assign_takeaway(
        session,
        plan_date=day + timedelta(days=1),
        slot="lunch",
        price="12.50",
        description="Pizza",
    )
    assert priced.takeaway_price_pence == 1250
    assert ingredient_requirements([priced]) == []


def test_same_meal_can_be_used_twice_and_keeps_its_snapshot(session: Session) -> None:
    meal = _rice_meal(session, quantity="200")
    monday = date(2026, 11, 2)
    lunch = assign_meal(session, plan_date=monday, slot="lunch", meal_id=meal.id)
    dinner = assign_meal(session, plan_date=monday, slot="dinner", meal_id=meal.id)
    assert lunch.id != dinner.id
    assert lunch.meal_id == dinner.meal_id == meal.id
    needs = ingredient_requirements([lunch, dinner])
    assert needs[0].quantity == Decimal("400")
    meal.name = "Renamed rice"
    session.flush()
    assert lunch.snapshot_meal_name == "Fried rice"
    assert dinner.snapshot_meal_name == "Fried rice"
    reloaded = session.get(PlannerEntry, lunch.id)
    assert reloaded is not None
    assert reloaded.snapshot_meal_name == "Fried rice"
    assert reloaded.meal is not None
    assert reloaded.meal.name == "Renamed rice"


def test_archiving_or_deleting_warns_when_a_plan_uses_the_meal(
    session: Session,
) -> None:
    meal = _rice_meal(session)
    entry = assign_meal(
        session,
        plan_date=date(2026, 11, 3),
        slot="lunch",
        meal_id=meal.id,
    )
    assert historical_planner_entries(session, meal.id) == [entry.id]
    set_meal_active(session, meal, active=False)
    assert session.get(PlannerEntry, entry.id) is not None
    assert entry.snapshot_meal_name == "Fried rice"
    with pytest.raises(MealInUseError, match="saved plan"):
        delete_meal(session, meal)
    with pytest.raises(FieldValidationError, match="active meal"):
        assign_meal(
            session,
            plan_date=date(2026, 11, 4),
            slot="dinner",
            meal_id=meal.id,
        )
    unused = save_meal(
        session,
        None,
        name="Unused",
        description=None,
        instructions=None,
        lines=[],
    )
    with pytest.raises(MealInUseError, match="Archive"):
        delete_meal(session, unused)


def test_week_cost_keeps_takeaway_separate_from_meal_cost(session: Session) -> None:
    meal = _priced_rice(session)
    day = date(2026, 11, 2)
    lunch = assign_meal(session, plan_date=day, slot="lunch", meal_id=meal.id)
    dinner = assign_takeaway(
        session,
        plan_date=day,
        slot="dinner",
        price="12.50",
        description="Pizza",
    )
    cost = week_cost([lunch, dinner])
    assert cost.meal_is_complete is True
    assert cost.meal_total_pence == 50
    assert cost.takeaway_total_pence == 1250
    assert cost.takeaway_count == 1
    assert cost.meal_total_pence != cost.takeaway_total_pence


def test_missing_price_is_incomplete_rather_than_free(session: Session) -> None:
    meal = _rice_meal(session)
    entry = assign_meal(
        session,
        plan_date=date(2026, 11, 2),
        slot="lunch",
        meal_id=meal.id,
    )
    takeaway = assign_takeaway(
        session,
        plan_date=date(2026, 11, 2),
        slot="dinner",
        price="5.00",
        description=None,
    )
    cost = week_cost([entry, takeaway])
    assert cost.meal_is_complete is False
    assert cost.meal_total_pence == 0
    assert cost.missing_ingredients == ("Rice",)
    assert cost.incomplete_label() == "incomplete: missing price for Rice"
    assert cost.takeaway_total_pence == 500


def test_replacing_a_slot_keeps_a_single_row(session: Session) -> None:
    meal = _rice_meal(session)
    day = date(2026, 11, 2)
    assign_meal(session, plan_date=day, slot="lunch", meal_id=meal.id)
    replaced = assign_takeaway(
        session,
        plan_date=day,
        slot="lunch",
        price="8",
        description="Indian",
    )
    rows = list(session.scalars(select(PlannerEntry)))
    assert rows == [replaced]
    assert replaced.entry_type == "takeaway"
    assert replaced.meal_id is None
    assert replaced.snapshot_meal_name is None
    assert replaced.takeaway_price_pence == 800


def _rice_meal(session: Session, *, quantity: str = "200", name: str = "Fried rice"):
    grams = _unit(session, "g")
    rice = create_ingredient(session, name="Rice", canonical_unit=grams).ingredient
    prepared, errors = prepare_lines(
        session,
        [RawLine(str(rice.id), quantity, str(grams.id), "")],
    )
    assert errors == {}
    return save_meal(
        session,
        None,
        name=name,
        description=None,
        instructions=None,
        lines=prepared,
    )


def _priced_rice(session: Session):
    meal = _rice_meal(session)
    shop = Shop(name="Market", is_active=True)
    session.add(shop)
    session.flush()
    create_purchase_option(
        session,
        ingredient=meal.lines[0].ingredient,
        shop=shop,
        pack_quantity=Decimal("1000"),
        pack_label="1kg bag",
        price_pence=250,
    )
    return meal


def _unit(session: Session, symbol: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    return unit
