"""Planner pages: persistence, takeaway validation, and the print view."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.test_planner import _rice_meal

from app.config import get_settings
from app.models import PlannerEntry, PlannerWeek
from app.services.planner import (
    format_week_range,
    local_today,
    shift_week,
    week_start_for,
)


def test_planner_shows_the_current_week_without_creating_one(
    client: TestClient, session: Session
) -> None:
    today = local_today(get_settings().app_timezone)
    start = week_start_for(today)
    response = client.get("/planner")
    assert response.status_code == 200
    assert "<h1>Planner</h1>" in response.text
    assert format_week_range(start) in response.text
    assert "Previous week" in response.text
    assert "Next week" in response.text
    assert "Print view" in response.text
    assert "Monday" in response.text
    assert "Sunday" in response.text
    previous = shift_week(start, -1).isoformat()
    assert f'href="/planner?date={previous}"' in response.text
    assert "https://" not in response.text
    assert "http://" not in response.text
    session.rollback()
    assert session.scalar(select(func.count()).select_from(PlannerWeek)) == 0


def test_past_and_future_weeks_keep_their_meals(
    client: TestClient, session: Session
) -> None:
    meal = _rice_meal(session)
    session.commit()
    past = "2026-10-05"
    future = "2026-12-08"
    for day, slot in ((past, "lunch"), (future, "dinner")):
        saved = client.post(
            "/planner/slots",
            data={
                "date": day,
                "slot": slot,
                "intent": "save-meal",
                "meal_id": str(meal.id),
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303
    past_page = client.get(f"/planner?date={past}")
    future_page = client.get("/planner?date=2026-12-07")
    current_page = client.get("/planner?date=2026-11-02")
    assert past_page.status_code == 200
    assert "Fried rice" in past_page.text
    assert "Monday 5 Oct" in past_page.text
    assert "Fried rice" in future_page.text
    assert "Tuesday 8 Dec" in future_page.text
    assert "Fried rice" not in current_page.text
    session.rollback()
    dates = set(session.scalars(select(PlannerEntry.plan_date)))
    assert dates == {date(2026, 10, 5), date(2026, 12, 8)}


def test_takeaway_price_error_stays_beside_the_field(
    client: TestClient, session: Session
) -> None:
    rejected = client.post(
        "/planner/slots",
        data={
            "date": "2026-11-03",
            "slot": "dinner",
            "intent": "save-takeaway",
            "takeaway_price": "",
            "takeaway_description": "Pizza",
        },
    )
    assert rejected.status_code == 200
    assert 'id="slot-2026-11-03-dinner-price-error"' in rejected.text
    assert "Enter a price" in rejected.text
    assert "Pizza" in rejected.text
    session.rollback()
    assert session.scalar(select(func.count()).select_from(PlannerEntry)) == 0


def test_htmx_save_returns_the_slot_without_a_full_page(
    client: TestClient, session: Session
) -> None:
    meal = _rice_meal(session)
    session.commit()
    saved = client.post(
        "/planner/slots",
        data={
            "date": "2026-11-02",
            "slot": "lunch",
            "intent": "save-meal",
            "meal_id": str(meal.id),
        },
        headers={"HX-Request": "true"},
    )
    assert saved.status_code == 200
    body = saved.text
    assert "<html" not in body.lower()
    assert 'id="slot-2026-11-02-lunch"' in body
    assert 'hx-swap-oob="outerHTML"' in body
    assert 'id="week-costs"' in body
    assert "Fried rice" in body
    assert "incomplete: missing price for Rice" in body
    again = client.get("/planner?date=2026-11-02")
    assert "Fried rice" in again.text


def test_repeated_meal_and_takeaway_stay_on_the_page(
    client: TestClient, session: Session
) -> None:
    meal = _rice_meal(session)
    session.commit()
    for slot in ("lunch", "dinner"):
        client.post(
            "/planner/slots",
            data={
                "date": "2026-11-04",
                "slot": slot,
                "intent": "save-meal",
                "meal_id": str(meal.id),
            },
        )
    client.post(
        "/planner/slots",
        data={
            "date": "2026-11-05",
            "slot": "lunch",
            "intent": "save-takeaway",
            "takeaway_price": "8.00",
            "takeaway_description": "Pizza",
        },
    )
    page = client.get("/planner?date=2026-11-02")
    assert page.text.count("Fried rice") >= 2
    assert "Takeaway: Pizza" in page.text
    assert "Takeaway: £8.00" in page.text
    assert "Estimated meal cost: £8.00" not in page.text
    assert "incomplete: missing price for Rice" in page.text
    detail = client.get(f"/meals/{meal.id}")
    assert "This meal is on a saved plan" in detail.text


def test_print_view_lists_the_week_without_navigation(
    client: TestClient, session: Session
) -> None:
    meal = _rice_meal(session)
    session.commit()
    client.post(
        "/planner/slots",
        data={
            "date": "2026-11-02",
            "slot": "lunch",
            "intent": "save-meal",
            "meal_id": str(meal.id),
        },
    )
    page = client.get("/planner/print?date=2026-11-02")
    assert page.status_code == 200
    body = page.text
    assert 'class="print-plan"' in body
    assert "<nav" not in body
    assert "<button" not in body
    assert "Monday 2 Nov" in body
    assert "Sunday 8 Nov" in body
    assert "Fried rice" in body
    assert "Estimated meal cost" not in body
    assert "incomplete:" not in body
    shown = client.get("/planner/print?date=2026-11-02&costs=1")
    assert "incomplete: missing price for Rice" in shown.text
    stylesheet = client.get("/static/app.css")
    assert "A4 landscape" in stylesheet.text
