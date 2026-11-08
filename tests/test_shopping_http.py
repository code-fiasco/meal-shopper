"""Shopping page: generate a week, then adjust the list from the browser."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Meal, ShoppingList, ShoppingListLine, Unit
from app.services.ingredients import create_ingredient
from app.services.meals import RawLine, prepare_lines, save_meal
from app.services.planner import assign_meal
from app.services.purchase_options import create_purchase_option
from app.services.shops import create_shop
from app.services.stock import SET, adjust_stock

MONDAY = date(2026, 11, 2)


def _unit(session: Session, symbol: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    return unit


def _beef_week(session: Session, quantity: str = "700") -> tuple[int, int]:
    grams = _unit(session, "g")
    beef = create_ingredient(
        session, name="Minced beef", canonical_unit=grams
    ).ingredient
    cheap = create_purchase_option(
        session,
        ingredient=beef,
        shop=create_shop(session, name="Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    dear = create_purchase_option(
        session,
        ingredient=beef,
        shop=create_shop(session, name="Market"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=500,
    )
    prepared, errors = prepare_lines(
        session, [RawLine(str(beef.id), quantity, str(grams.id), "")]
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
    adjust_stock(
        session,
        ingredient_id=beef.id,
        action=SET,
        quantity="100",
        unit_id=str(grams.id),
    )
    session.commit()
    return cheap.id, dear.id


def _generate(client: TestClient) -> str:
    response = client.post(
        "/shopping/generate",
        data={"date": MONDAY.isoformat()},
        follow_redirects=True,
    )
    assert response.status_code == 200
    return response.text


def _line(session: Session) -> ShoppingListLine:
    session.rollback()
    line = session.scalar(
        select(ShoppingListLine).where(ShoppingListLine.source == "generated")
    )
    assert line is not None
    return line


def test_generate_shows_requirement_stock_and_both_totals(
    client: TestClient, session: Session
) -> None:
    _beef_week(session)
    page = _generate(client)
    assert "<h1>Shopping</h1>" in page
    assert "Recipe needs 700g" in page
    assert "Stock used 100g" in page
    assert "Buy 600g" in page
    assert "Butcher" in page
    assert "Packs 2" in page
    assert "1 new" in page
    assert "Estimated shopping outlay" in page
    assert "£7.00" in page
    assert "Recipe consumption cost" in page
    assert "£4.90" in page
    assert "unused stock" in page
    assert "None removed." in page


def test_changing_the_pack_uses_that_shop(client: TestClient, session: Session) -> None:
    _cheap, dear = _beef_week(session)
    _generate(client)
    line = _line(session)
    changed = client.post(
        f"/shopping/lines/{line.id}",
        data={"action": "option", "option_id": str(dear)},
        headers={"HX-Request": "true"},
    )
    assert changed.status_code == 200
    assert "<html" not in changed.text.lower()
    assert "Market" in changed.text
    assert "£10.00" in changed.text
    assert "Butcher, 500g pack" not in changed.text.split("Shop and pack")[0]


def test_remove_and_restore_move_the_line(client: TestClient, session: Session) -> None:
    _beef_week(session)
    _generate(client)
    line = _line(session)
    removed = client.post(
        f"/shopping/lines/{line.id}",
        data={"action": "remove"},
        follow_redirects=True,
    )
    assert "Removed items" in removed.text
    assert "Nothing to buy yet." in removed.text
    assert "£0.00" in removed.text
    restored = client.post(
        f"/shopping/lines/{line.id}",
        data={"action": "restore"},
        follow_redirects=True,
    )
    assert "Buy 600g" in restored.text
    assert "None removed." in restored.text
    assert "£7.00" in restored.text


def test_manual_item_is_added_to_the_outlay(
    client: TestClient, session: Session
) -> None:
    _beef_week(session)
    _generate(client)
    session.rollback()
    shop = create_shop(session, name="Chemist")
    session.commit()
    added = client.post(
        "/shopping/manual",
        data={
            "date": MONDAY.isoformat(),
            "description": "Toilet roll",
            "quantity": "4",
            "unit": "roll",
            "price": "1.50",
            "shop_id": str(shop.id),
        },
        follow_redirects=True,
    )
    assert "Toilet roll" in added.text
    assert "4 roll" in added.text
    assert "Chemist" in added.text
    assert "£1.50" in added.text
    assert "£8.50" in added.text


def test_refresh_after_a_plan_change_counts_the_update(
    client: TestClient, session: Session
) -> None:
    _beef_week(session, quantity="200")
    _generate(client)
    line = _line(session)
    client.post(f"/shopping/lines/{line.id}", data={"action": "remove"})
    session.rollback()
    shop = create_shop(session, name="Chemist")
    session.commit()
    client.post(
        "/shopping/manual",
        data={
            "date": MONDAY.isoformat(),
            "description": "Toilet roll",
            "quantity": "",
            "unit": "",
            "price": "1.50",
            "shop_id": str(shop.id),
        },
    )
    session.rollback()
    meal_line = session.scalar(
        select(ShoppingListLine).where(ShoppingListLine.source == "generated")
    )
    assert meal_line is not None
    grams = _unit(session, "g")
    beef_id = meal_line.ingredient_id
    meal = session.scalar(select(Meal))
    assert meal is not None and beef_id is not None
    revised, errors = prepare_lines(
        session, [RawLine(str(beef_id), "500", str(grams.id), "")]
    )
    assert errors == {}
    save_meal(
        session, meal, name="Ragu", description=None, instructions=None, lines=revised
    )
    session.commit()
    refreshed = _generate(client)
    assert "1 updated" in refreshed
    assert "Recipe needs 500g" in refreshed
    assert "Toilet roll" in refreshed
    assert "Removed items" in refreshed
    assert "£1.50" in refreshed


def test_invalid_price_stays_on_the_page(client: TestClient, session: Session) -> None:
    _beef_week(session)
    _generate(client)
    line = _line(session)
    rejected = client.post(
        f"/shopping/lines/{line.id}",
        data={"action": "price", "price": "1.799"},
    )
    assert rejected.status_code == 200
    assert "Error:" in rejected.text
    assert "two decimal places" in rejected.text
    assert "£7.00" in rejected.text
    assert "Buy 600g" in rejected.text


def test_checklist_tick_persists_and_print_is_plain(
    client: TestClient, session: Session
) -> None:
    _beef_week(session)
    page = _generate(client)
    list_id = page.split("/shopping/")[1].split("/checklist")[0]
    checklist = client.get(f"/shopping/{list_id}/checklist")
    assert checklist.status_code == 200
    assert "Minced beef" in checklist.text
    assert "To buy" in checklist.text
    assert "600g" in checklist.text
    assert "2 packs" in checklist.text
    assert "Butcher" in checklist.text
    assert "Estimated total" in checklist.text
    assert "Remaining" in checklist.text
    assert "£7.00" in checklist.text
    line = _line(session)
    saved = client.post(
        f"/shopping/lines/{line.id}/check",
        data={"checked": "1"},
        headers={"HX-Request": "true"},
    )
    assert saved.status_code == 200
    assert "<html" not in saved.text.lower()
    assert "Remaining" in saved.text
    assert "£0.00" in saved.text
    again = client.get(f"/shopping/{list_id}/checklist")
    assert "checked" in again.text
    assert "✓ Collected" in again.text
    session.rollback()
    stored = session.get(ShoppingListLine, line.id)
    assert stored is not None
    assert stored.checked is True
    cleared = client.post(
        f"/shopping/lines/{line.id}/check",
        data={"checked": "0"},
        follow_redirects=True,
    )
    assert "To buy" in cleared.text
    session.rollback()
    stored = session.get(ShoppingListLine, line.id)
    assert stored is not None
    assert stored.checked is False
    printed = client.get(f"/shopping/{list_id}/print")
    assert printed.status_code == 200
    assert "Minced beef" in printed.text
    assert "2 packs" in printed.text
    assert "£7.00" in printed.text
    assert "print-box" in printed.text
    assert "<nav" not in printed.text
    assert "Skip to content" not in printed.text
    hidden = client.get(f"/shopping/{list_id}/print?boxes=0")
    assert "print-box" not in hidden.text


def test_generate_needs_a_planned_week(client: TestClient, session: Session) -> None:
    rejected = client.post(
        "/shopping/generate",
        data={"date": MONDAY.isoformat()},
    )
    assert rejected.status_code == 200
    assert "Choose a week that has been planned." in rejected.text
    session.rollback()
    assert session.scalar(select(func.count()).select_from(ShoppingList)) == 0
