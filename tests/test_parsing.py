"""Pound amounts and pack quantities parsed without floats."""

from decimal import Decimal

import pytest

from app.formatting import format_gbp_exact
from app.services.parsing import parse_gbp_to_pence, parse_pack_quantity
from app.services.units import InvalidQuantityError


def test_pound_amounts_become_integer_pence() -> None:
    assert parse_gbp_to_pence("1.79") == 179
    assert parse_gbp_to_pence("£1.79") == 179
    assert parse_gbp_to_pence("1.9") == 190
    assert parse_gbp_to_pence("0") == 0


def test_price_rejects_extra_places_negatives_and_commas() -> None:
    with pytest.raises(ValueError, match="two decimal places"):
        parse_gbp_to_pence("1.795")
    with pytest.raises(ValueError, match="cannot be negative"):
        parse_gbp_to_pence("-0.10")
    with pytest.raises(ValueError, match="decimal point"):
        parse_gbp_to_pence("1,79")


def test_unit_price_display_stays_short() -> None:
    assert format_gbp_exact(Decimal(179)) == "£1.79"
    assert format_gbp_exact(Decimal("17.9")) == "£0.179"
    assert format_gbp_exact(Decimal(179) / Decimal(6)) == "£0.298333"


def test_pack_quantity_names_the_unit_and_rejects_zero() -> None:
    assert parse_pack_quantity("1.5", unit_symbol="kg") == Decimal("1.5")
    with pytest.raises(InvalidQuantityError, match="kg"):
        parse_pack_quantity("nope", unit_symbol="kg")
    with pytest.raises(InvalidQuantityError, match="Zero is not a pack"):
        parse_pack_quantity("0", unit_symbol="g")
    with pytest.raises(InvalidQuantityError, match="cannot be negative"):
        parse_pack_quantity("-2", unit_symbol="g")
