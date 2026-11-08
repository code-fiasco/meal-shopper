"""Stock page, unit errors, and the embeddable quick-edit partial."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PantryStock, Unit
from app.services.ingredients import create_ingredient
from app.services.stock import SET, adjust_stock, get_stock_map


def _unit_id(session: Session, symbol: str) -> int:
    session.commit()
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    session.commit()
    return unit.id


def _create_ingredient(client: TestClient, name: str, unit_id: int) -> str:
    created = client.post(
        "/ingredients",
        data={"name": name, "canonical_unit_id": str(unit_id), "notes": ""},
        follow_redirects=False,
    )
    assert created.status_code == 303
    return created.headers["location"].rsplit("/", 1)[-1]


def test_stock_page_shows_a_converted_quantity_with_its_unit(
    client: TestClient, session: Session
) -> None:
    gram_id = _unit_id(session, "g")
    kilogram_id = _unit_id(session, "kg")
    sugar_id = _create_ingredient(client, "Sugar", gram_id)
    saved = client.post(
        "/stock/items",
        data={
            "ingredient_id": sugar_id,
            "quantity": "1",
            "unit_id": str(kilogram_id),
            "action": "set",
            "placement": "editor",
        },
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "<h1>Stock</h1>" in saved.text
    assert "In stock: 1000g" in saved.text
    assert "Stored in gram (g)." in saved.text
    session.rollback()
    assert get_stock_map(session) == {int(sugar_id): Decimal("1000")}


def test_search_opens_the_quick_edit_control(
    client: TestClient, session: Session
) -> None:
    gram_id = _unit_id(session, "g")
    sugar_id = _create_ingredient(client, "Sugar", gram_id)
    found = client.get(
        "/stock/search",
        params={"q": "sug"},
        headers={"HX-Request": "true"},
    )
    assert found.status_code == 200
    assert "<html" not in found.text.lower()
    assert f'href="/stock/ingredients/{sugar_id}"' in found.text
    opened = client.get(
        f"/stock/ingredients/{sugar_id}",
        headers={"HX-Request": "true"},
    )
    assert "<html" not in opened.text.lower()
    assert f'id="stock-editor-{sugar_id}"' in opened.text
    assert 'value="set"' in opened.text
    assert 'value="add"' in opened.text
    assert 'value="subtract"' in opened.text
    assert 'value="clear"' in opened.text
    assert "None left" in opened.text
    session.rollback()


def test_incompatible_unit_is_shown_beside_the_field(
    client: TestClient, session: Session
) -> None:
    slice_id = _unit_id(session, "slice")
    gram_id = _unit_id(session, "g")
    ham_id = _create_ingredient(client, "Ham", slice_id)
    rejected = client.post(
        "/stock/items",
        data={
            "ingredient_id": ham_id,
            "quantity": "100",
            "unit_id": str(gram_id),
            "action": "set",
            "placement": "editor",
        },
        headers={"HX-Request": "true"},
    )
    assert rejected.status_code == 200
    assert "<html" not in rejected.text.lower()
    assert f'id="stock-editor-{ham_id}-unit-error"' in rejected.text
    assert "Ham is measured in slice" in rejected.text
    assert "gram cannot be used" in rejected.text
    session.rollback()
    assert session.get(PantryStock, int(ham_id)) is None


def test_htmx_adjust_returns_the_embeddable_control(
    client: TestClient, session: Session
) -> None:
    grams = _unit_id(session, "g")
    session.commit()
    unit = session.get(Unit, grams)
    assert unit is not None
    sugar = create_ingredient(session, name="Sugar", canonical_unit=unit).ingredient
    adjust_stock(
        session,
        ingredient_id=sugar.id,
        action=SET,
        quantity="1000",
        unit_id=str(grams),
    )
    session.commit()
    updated = client.post(
        "/stock/items",
        data={
            "ingredient_id": str(sugar.id),
            "quantity": "500",
            "unit_id": str(grams),
            "action": "add",
            "placement": "list",
        },
        headers={"HX-Request": "true"},
    )
    assert updated.status_code == 200
    assert "<html" not in updated.text.lower()
    assert f'id="stock-item-{sugar.id}"' in updated.text
    assert f'id="stock-editor-{sugar.id}"' in updated.text
    assert 'hx-swap-oob="outerHTML"' in updated.text
    assert "In stock: 1500g" in updated.text
    assert 'hx-post="/stock/items"' in updated.text
    session.rollback()
    assert get_stock_map(session)[sugar.id] == Decimal("1500")


def test_subtract_below_zero_keeps_the_displayed_quantity(
    client: TestClient, session: Session
) -> None:
    grams = _unit_id(session, "g")
    session.commit()
    unit = session.get(Unit, grams)
    assert unit is not None
    sugar = create_ingredient(session, name="Sugar", canonical_unit=unit).ingredient
    adjust_stock(
        session,
        ingredient_id=sugar.id,
        action=SET,
        quantity="200",
        unit_id=str(grams),
    )
    session.commit()
    kilogram_id = _unit_id(session, "kg")
    rejected = client.post(
        "/stock/items",
        data={
            "ingredient_id": str(sugar.id),
            "quantity": "1",
            "unit_id": str(kilogram_id),
            "action": "subtract",
            "placement": "list",
        },
        headers={"HX-Request": "true"},
    )
    assert rejected.status_code == 200
    assert 'id="stock-item-' in rejected.text
    assert "below zero" in rejected.text
    assert "200g is in stock" in rejected.text
    assert "In stock: 200g" in rejected.text
    session.rollback()
    assert get_stock_map(session)[sugar.id] == Decimal("200")
