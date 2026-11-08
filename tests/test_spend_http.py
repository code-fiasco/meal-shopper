"""Record a shop from the list, then read it on the spending page."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ShoppingList, ShoppingTransaction, Unit
from app.services.ingredients import create_ingredient
from app.services.meals import RawLine, prepare_lines, save_meal
from app.services.planner import assign_meal
from app.services.purchase_options import create_purchase_option
from app.services.shops import create_shop

MONDAY = date(2026, 11, 2)


def _unit(session: Session, symbol: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    return unit


def _plan(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(
        session, name="Minced beef", canonical_unit=grams
    ).ingredient
    create_purchase_option(
        session,
        ingredient=beef,
        shop=create_shop(session, name="Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    prepared, errors = prepare_lines(
        session, [RawLine(str(beef.id), "200", str(grams.id), "")]
    )
    assert errors == {}
    meal = save_meal(
        session,
        None,
        name="Ragu",
        description=None,
        instructions=None,
        lines=prepared,
    )
    assign_meal(session, plan_date=MONDAY, slot="lunch", meal_id=meal.id)
    session.commit()


def test_recording_spend_keeps_the_estimate_out_of_the_total(
    client: TestClient, session: Session
) -> None:
    _plan(session)
    page = client.post(
        "/shopping/generate",
        data={"date": MONDAY.isoformat()},
        follow_redirects=True,
    )
    assert page.status_code == 200
    assert 'id="spend-total"' in page.text
    total_at = page.text.index('id="spend-total"')
    total_tag = page.text[total_at : page.text.index(">", total_at)]
    assert 'value=""' in total_tag
    assert "£3.50" in page.text
    session.rollback()
    shopping_list = session.scalar(select(ShoppingList))
    assert shopping_list is not None

    refused = client.post(
        f"/shopping/{shopping_list.id}/spend",
        data={"total": "", "spent_on": MONDAY.isoformat(), "notes": ""},
    )
    assert refused.status_code == 200
    assert "Error: Enter the amount you paid" in refused.text
    session.rollback()
    count = session.scalar(select(func.count()).select_from(ShoppingTransaction))
    assert count == 0

    first = client.post(
        f"/shopping/{shopping_list.id}/spend",
        data={"total": "8.00", "spent_on": MONDAY.isoformat(), "notes": "Weekly shop"},
        follow_redirects=True,
    )
    assert first.status_code == 200
    assert "Spend recorded." in first.text
    assert "£8.00" in first.text
    session.rollback()
    second = client.post(
        f"/shopping/{shopping_list.id}/spend",
        data={"total": "2.00", "spent_on": "2026-11-03", "notes": ""},
        follow_redirects=True,
    )
    assert second.status_code == 200
    assert "£2.00" in second.text
    session.rollback()

    report = client.get("/spending?weeks=4&date=2026-11-02")
    assert report.status_code == 200
    body = report.text
    assert "<h1>Spending</h1>" in body
    assert "£10.00" in body
    assert "Actual" in body
    assert "Unrecorded" in body
    assert "Estimated outlay" in body
    assert "Grocery (actual)" in body
    assert 'src="/static/chart.umd.min.js"' in body
    assert "https://" not in body
    assert "http://" not in body
