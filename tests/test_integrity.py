"""Foreign keys, integer pence, and non-negative database checks."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Float, Integer, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base
from app.models.types import DecimalQuantity
from app.services.ingredients import create_ingredient
from app.services.purchase_options import create_purchase_option
from app.services.shops import create_shop


def test_money_is_integer_pence_and_quantities_are_not_float() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            assert not isinstance(column.type, Float)
            if column.name.endswith("pence"):
                assert isinstance(column.type, Integer)
            if isinstance(column.type, DecimalQuantity):
                assert not isinstance(column.type.impl, Float)


def test_database_rejects_a_negative_price(session: Session) -> None:
    from app.models import Unit

    grams = session.scalar(text("SELECT id FROM units WHERE symbol = 'g'"))
    assert grams is not None
    unit = session.get(Unit, grams)
    assert unit is not None
    ingredient = create_ingredient(session, name="Rice", canonical_unit=unit).ingredient
    option = create_purchase_option(
        session,
        ingredient=ingredient,
        shop=create_shop(session, name="Market"),
        pack_quantity=Decimal("500"),
        pack_label="500g",
        price_pence=100,
    )
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(
            text("UPDATE purchase_options SET price_pence = -1 WHERE id = :id"),
            {"id": option.id},
        )
        session.commit()
    session.rollback()


def test_database_rejects_deleting_a_referenced_ingredient(session: Session) -> None:
    from app.models import Unit

    gram_id = session.scalar(text("SELECT id FROM units WHERE symbol = 'g'"))
    grams = session.get(Unit, gram_id)
    assert grams is not None
    ingredient = create_ingredient(
        session, name="Oats", canonical_unit=grams
    ).ingredient
    create_purchase_option(
        session,
        ingredient=ingredient,
        shop=create_shop(session, name="Grocer"),
        pack_quantity=Decimal("1000"),
        pack_label="1kg",
        price_pence=150,
    )
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(
            text("DELETE FROM ingredients WHERE id = :id"),
            {"id": ingredient.id},
        )
        session.commit()
    session.rollback()


def test_compose_publishes_localhost_and_keeps_the_database() -> None:
    text_file = Path("docker-compose.yml").read_text()
    assert "127.0.0.1:${APP_PORT:-5373}:${APP_PORT:-5373}" in text_file
    assert "./data:/data" in text_file
