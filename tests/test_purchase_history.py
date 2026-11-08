"""Price history is appended and never rewritten."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceHistoryImmutableError, PurchasePriceHistory, Shop, Unit
from app.services.ingredients import create_ingredient
from app.services.purchase_options import (
    change_purchase_option,
    create_purchase_option,
)
from app.services.units import InvalidQuantityError


def _unit(session: Session, symbol: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    return unit


def _history(session: Session, option_id: int) -> list[PurchasePriceHistory]:
    return list(
        session.scalars(
            select(PurchasePriceHistory)
            .where(PurchasePriceHistory.purchase_option_id == option_id)
            .order_by(PurchasePriceHistory.id)
        )
    )


def test_history_records_price_and_pack_changes(session: Session) -> None:
    gram = _unit(session, "g")
    shop = Shop(name="Shop B", is_active=True)
    session.add(shop)
    session.flush()
    sugar = create_ingredient(session, name="Sugar", canonical_unit=gram).ingredient
    option = create_purchase_option(
        session,
        ingredient=sugar,
        shop=shop,
        pack_quantity=Decimal("1000"),
        pack_label="1kg bag",
        price_pence=89,
    )

    opening = _history(session, option.id)
    assert len(opening) == 1
    assert opening[0].price_pence == 89
    assert opening[0].pack_quantity == Decimal("1000")
    opening_id = opening[0].id

    change_purchase_option(session, option, price_pence=99)
    after_price = _history(session, option.id)
    assert len(after_price) == 2
    assert after_price[0].id == opening_id
    assert after_price[0].price_pence == 89
    assert after_price[0].pack_quantity == Decimal("1000")
    assert after_price[1].price_pence == 99
    assert after_price[1].pack_quantity == Decimal("1000")

    change_purchase_option(session, option, pack_quantity=Decimal("2000"))
    after_pack = _history(session, option.id)
    assert len(after_pack) == 3
    assert after_pack[0].price_pence == 89
    assert after_pack[1].price_pence == 99
    assert after_pack[1].pack_quantity == Decimal("1000")
    assert after_pack[2].price_pence == 99
    assert after_pack[2].pack_quantity == Decimal("2000")


def test_label_change_does_not_write_history(session: Session) -> None:
    gram = _unit(session, "g")
    shop = Shop(name="Shop A", is_active=True)
    session.add(shop)
    session.flush()
    sugar = create_ingredient(session, name="Flour", canonical_unit=gram).ingredient
    option = create_purchase_option(
        session,
        ingredient=sugar,
        shop=shop,
        pack_quantity=Decimal("500"),
        pack_label="500g bag",
        price_pence=70,
    )
    change_purchase_option(session, option, pack_label="500g plain flour")
    assert option.pack_label == "500g plain flour"
    assert len(_history(session, option.id)) == 1


def test_negative_price_and_pack_are_rejected(session: Session) -> None:
    shop = Shop(name="Shop C", is_active=True)
    session.add(shop)
    session.flush()
    eggs = create_ingredient(session, name="Eggs", canonical_unit=_unit(session, "egg"))
    with pytest.raises(InvalidQuantityError):
        create_purchase_option(
            session,
            ingredient=eggs.ingredient,
            shop=shop,
            pack_quantity=Decimal("6"),
            pack_label="6 pack",
            price_pence=-120,
        )
    with pytest.raises(InvalidQuantityError):
        create_purchase_option(
            session,
            ingredient=eggs.ingredient,
            shop=shop,
            pack_quantity=Decimal("-6"),
            pack_label="6 pack",
            price_pence=120,
        )


def test_history_rows_cannot_be_changed_or_deleted(session: Session) -> None:
    gram = _unit(session, "g")
    shop = Shop(name="Shop D", is_active=True)
    session.add(shop)
    session.flush()
    sugar = create_ingredient(session, name="Salt", canonical_unit=gram).ingredient
    option = create_purchase_option(
        session,
        ingredient=sugar,
        shop=shop,
        pack_quantity=Decimal("750"),
        pack_label="750g",
        price_pence=55,
    )
    row = _history(session, option.id)[0]
    row.price_pence = 1
    with pytest.raises(PriceHistoryImmutableError):
        session.flush()
    session.rollback()


def test_history_rows_cannot_be_deleted(session: Session) -> None:
    gram = _unit(session, "g")
    shop = Shop(name="Shop E", is_active=True)
    session.add(shop)
    session.flush()
    sugar = create_ingredient(session, name="Pepper", canonical_unit=gram).ingredient
    option = create_purchase_option(
        session,
        ingredient=sugar,
        shop=shop,
        pack_quantity=Decimal("50"),
        pack_label="50g",
        price_pence=80,
    )
    row = _history(session, option.id)[0]
    session.delete(row)
    with pytest.raises(PriceHistoryImmutableError):
        session.flush()


def test_explicit_conversion_round_trip(session: Session) -> None:
    from app.models import IngredientConversion

    clove = _unit(session, "clove")
    bulb = Unit(
        name="bulb",
        symbol="bulb",
        family=clove.family,
        factor_to_base=None,
    )
    session.add(bulb)
    session.flush()
    garlic = create_ingredient(session, name="Garlic", canonical_unit=clove).ingredient
    session.add(
        IngredientConversion(
            ingredient=garlic,
            from_unit=bulb,
            factor_to_canonical=Decimal("10"),
        )
    )
    session.flush()
    stored = session.scalar(
        select(IngredientConversion).where(
            IngredientConversion.ingredient_id == garlic.id
        )
    )
    assert stored is not None
    assert stored.factor_to_canonical == Decimal("10")
    assert stored.from_unit_id == bulb.id
