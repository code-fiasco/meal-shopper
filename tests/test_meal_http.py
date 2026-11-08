"""Meal pages for costing, unit rejection, and inline ingredient creation."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Ingredient, Meal, Unit


def _unit_id(session: Session, symbol: str) -> int:
    session.commit()
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    session.commit()
    return unit.id


def test_inline_ingredient_updates_the_line_without_the_meal_form(
    client: TestClient, session: Session
) -> None:
    gram_id = _unit_id(session, "g")
    page = client.get("/meals/new")
    assert page.status_code == 200
    assert 'id="meal-name"' in page.text
    assert 'id="meal-description"' in page.text
    assert 'hx-target="#ingredient-panel"' in page.text
    created = client.post(
        "/ingredients",
        data={
            "name": "Rice",
            "canonical_unit_id": str(gram_id),
            "notes": "",
            "embed": "1",
            "line": "0",
        },
    )
    assert created.status_code == 200
    body = created.text
    assert 'id="line-0-picker"' in body
    assert 'hx-swap-oob="outerHTML"' in body
    assert 'name="ingredient_id"' in body
    assert "Rice" in body
    assert 'id="meal-name"' not in body
    assert "<html" not in body.lower()
    session.rollback()
    stored = session.scalar(select(Ingredient).where(Ingredient.name == "Rice"))
    assert stored is not None


def test_incompatible_unit_is_shown_beside_the_field(
    client: TestClient, session: Session
) -> None:
    slice_id = _unit_id(session, "slice")
    gram_id = _unit_id(session, "g")
    created = client.post(
        "/ingredients",
        data={"name": "Ham", "canonical_unit_id": str(slice_id), "notes": ""},
        follow_redirects=False,
    )
    ingredient_id = created.headers["location"].rsplit("/", 1)[-1]
    rejected = client.post(
        "/meals",
        data={
            "name": "Sandwiches",
            "description": "still here",
            "instructions": "toast",
            "ingredient_id": [ingredient_id],
            "entered_quantity": ["100"],
            "entered_unit_id": [str(gram_id)],
            "line_notes": [""],
        },
    )
    assert rejected.status_code == 200
    assert 'id="line-0-unit-error"' in rejected.text
    assert "cannot be used" in rejected.text
    assert "slice" in rejected.text
    assert "still here" in rejected.text
    session.rollback()
    assert session.scalar(select(func.count()).select_from(Meal)) == 0


def test_duplicate_meal_from_the_detail_page(
    client: TestClient, session: Session
) -> None:
    saved = client.post(
        "/meals",
        data={
            "name": "Omelette",
            "description": "",
            "instructions": "Beat the eggs.",
            "ingredient_id": [],
            "entered_quantity": [],
            "entered_unit_id": [],
            "line_notes": [],
        },
        follow_redirects=False,
    )
    detail = saved.headers["location"]
    copied = client.post(f"{detail}/duplicate", follow_redirects=True)
    assert copied.status_code == 200
    assert "Copy of Omelette" in copied.text
    assert "Beat the eggs." in copied.text
    session.rollback()
    names = set(session.scalars(select(Meal.name)))
    assert names == {"Omelette", "Copy of Omelette"}


def test_meal_page_shows_a_complete_two_person_cost(
    client: TestClient, session: Session
) -> None:
    gram_id = _unit_id(session, "g")
    ingredient = client.post(
        "/ingredients",
        data={"name": "Rice", "canonical_unit_id": str(gram_id), "notes": ""},
        follow_redirects=False,
    )
    ingredient_id = ingredient.headers["location"].rsplit("/", 1)[-1]
    client.post("/shops", data={"name": "Tesco", "notes": ""})
    session.rollback()
    from app.models import Shop

    shop = session.scalar(select(Shop).where(Shop.name == "Tesco"))
    assert shop is not None
    client.post(
        f"/ingredients/{ingredient_id}/options",
        data={
            "shop_id": str(shop.id),
            "pack_quantity": "1000",
            "pack_label": "1kg bag",
            "price": "2.50",
        },
    )
    saved = client.post(
        "/meals",
        data={
            "name": "Rice bowl",
            "description": "",
            "instructions": "",
            "ingredient_id": [ingredient_id],
            "entered_quantity": ["500"],
            "entered_unit_id": [str(gram_id)],
            "line_notes": [""],
        },
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "£1.25" in saved.text
    assert "for two" in saved.text
    assert "Per person" in saved.text
    assert "incomplete:" not in saved.text
    assert "500g" in saved.text
