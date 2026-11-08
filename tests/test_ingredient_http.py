"""Ingredient pages for FR-01, FR-03, and FR-04."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Ingredient, PurchaseOption, Shop, Unit


def _unit_id(session: Session, symbol: str) -> int:
    session.commit()
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    session.commit()
    return unit.id


def test_create_ingredient_with_canonical_unit(
    client: TestClient, session: Session
) -> None:
    slice_id = _unit_id(session, "slice")
    response = client.post(
        "/ingredients",
        data={"name": "Ham", "canonical_unit_id": str(slice_id), "notes": "smoked"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Ham" in response.text
    assert "slice" in response.text
    form = client.get("/ingredients/form")
    assert form.status_code == 200
    assert "<select" in form.text
    assert "slice" in form.text
    assert "<html" not in form.text.lower()


def test_duplicate_name_warns_until_confirmed(
    client: TestClient, session: Session
) -> None:
    slice_id = _unit_id(session, "slice")
    payload = {"name": "Ham", "canonical_unit_id": str(slice_id), "notes": ""}
    client.post("/ingredients", data=payload)
    warned = client.post("/ingredients", data=payload)
    assert warned.status_code == 200
    assert "looks like a duplicate" in warned.text
    assert "Save anyway" in warned.text
    session.rollback()
    assert session.scalar(select(func.count()).select_from(Ingredient)) == 1
    saved = client.post("/ingredients", data={**payload, "confirm_duplicate": "yes"})
    assert saved.status_code == 200
    session.rollback()
    assert session.scalar(select(func.count()).select_from(Ingredient)) == 2


def test_two_purchase_options_stay_unselected(
    client: TestClient, session: Session
) -> None:
    gram_id = _unit_id(session, "g")
    created = client.post(
        "/ingredients",
        data={"name": "Bread", "canonical_unit_id": str(gram_id), "notes": ""},
        follow_redirects=False,
    )
    detail = created.headers["location"]
    client.post("/shops", data={"name": "Tesco", "notes": ""})
    client.post("/shops", data={"name": "Aldi", "notes": ""})
    session.rollback()
    shops = {shop.name: shop.id for shop in session.scalars(select(Shop))}
    for shop_name, quantity, label, price in (
        ("Tesco", "400", "medium loaf", "1.00"),
        ("Aldi", "800", "large loaf", "1.50"),
    ):
        saved = client.post(
            f"{detail}/options",
            data={
                "shop_id": str(shops[shop_name]),
                "pack_quantity": quantity,
                "pack_label": label,
                "price": price,
            },
            follow_redirects=True,
        )
        assert saved.status_code == 200
    page = client.get(detail)
    body = page.text
    assert "Tesco" in body
    assert "Aldi" in body
    assert "medium loaf" in body
    assert "large loaf" in body
    assert "400g" in body
    assert "800g" in body
    assert "£1.00" in body
    assert "£1.50" in body
    assert "per g" in body
    assert 'type="radio"' not in body


def test_price_change_keeps_history_newest_first(
    client: TestClient, session: Session
) -> None:
    gram_id = _unit_id(session, "g")
    created = client.post(
        "/ingredients",
        data={"name": "Rice", "canonical_unit_id": str(gram_id), "notes": ""},
        follow_redirects=False,
    )
    detail = created.headers["location"]
    client.post("/shops", data={"name": "Tesco", "notes": ""})
    session.rollback()
    shop = session.scalar(select(Shop).where(Shop.name == "Tesco"))
    assert shop is not None
    client.post(
        f"{detail}/options",
        data={
            "shop_id": str(shop.id),
            "pack_quantity": "1000",
            "pack_label": "1kg bag",
            "price": "1.00",
        },
    )
    session.rollback()
    option = session.scalar(select(PurchaseOption))
    assert option is not None
    client.post(
        f"{detail}/options/{option.id}",
        data={
            "shop_id": str(shop.id),
            "pack_quantity": "1000",
            "pack_label": "1kg bag",
            "price": "2.00",
        },
    )
    history = client.get(f"{detail}/options/{option.id}/history")
    assert history.status_code == 200
    body = history.text
    assert body.index("£2.00") < body.index("£1.00")
    assert "1000g" in body


def test_invalid_price_is_shown_beside_the_field(
    client: TestClient, session: Session
) -> None:
    gram_id = _unit_id(session, "g")
    created = client.post(
        "/ingredients",
        data={"name": "Oats", "canonical_unit_id": str(gram_id), "notes": ""},
        follow_redirects=False,
    )
    detail = created.headers["location"]
    client.post("/shops", data={"name": "Tesco", "notes": ""})
    session.rollback()
    shop = session.scalar(select(Shop).where(Shop.name == "Tesco"))
    assert shop is not None
    rejected = client.post(
        f"{detail}/options",
        data={
            "shop_id": str(shop.id),
            "pack_quantity": "500",
            "pack_label": "bag",
            "price": "1.795",
        },
    )
    assert rejected.status_code == 200
    assert 'id="price-error"' in rejected.text
    assert "two decimal places" in rejected.text
    session.rollback()
    assert session.scalar(select(func.count()).select_from(PurchaseOption)) == 0
