"""Unit conversion and pence-per-unit calculations."""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.models import Unit, UnitFamily
from app.services.units import (
    IncompatibleUnitError,
    InvalidQuantityError,
    allocated_cost_pence,
    convert,
    round_to_pence,
    unit_price_per_canonical,
)


@dataclass
class _Conversion:
    from_unit_id: int
    factor_to_canonical: Decimal
    canonical_unit_id: int | None = None


def _unit(
    unit_id: int,
    name: str,
    symbol: str,
    family: UnitFamily,
    factor: str | None,
) -> Unit:
    return Unit(
        id=unit_id,
        name=name,
        symbol=symbol,
        family=family,
        factor_to_base=None if factor is None else Decimal(factor),
    )


def test_kilogram_converts_to_grams() -> None:
    grams = _unit(1, "gram", "g", UnitFamily.WEIGHT, "1")
    kilograms = _unit(2, "kilogram", "kg", UnitFamily.WEIGHT, "1000")
    assert convert(Decimal("1"), kilograms, grams) == Decimal("1000")


def test_grams_convert_to_kilograms() -> None:
    grams = _unit(1, "gram", "g", UnitFamily.WEIGHT, "1")
    kilograms = _unit(2, "kilogram", "kg", UnitFamily.WEIGHT, "1000")
    assert convert(Decimal("2500"), grams, kilograms) == Decimal("2.5")


def test_litre_converts_to_millilitres() -> None:
    millilitres = _unit(1, "millilitre", "ml", UnitFamily.VOLUME, "1")
    litres = _unit(2, "litre", "litre", UnitFamily.VOLUME, "1000")
    assert convert(Decimal("1"), litres, millilitres) == Decimal("1000")


def test_same_unit_returns_the_quantity() -> None:
    slices = _unit(1, "slice", "slice", UnitFamily.COUNT, None)
    assert convert(Decimal("6"), slices, slices) == Decimal("6")


def test_grams_rejected_for_sliced_ham() -> None:
    slices = _unit(1, "slices", "slice", UnitFamily.COUNT, None)
    grams = _unit(2, "grams", "g", UnitFamily.WEIGHT, "1")
    with pytest.raises(IncompatibleUnitError) as caught:
        convert(Decimal("100"), grams, slices, ingredient_name="Ham")
    assert str(caught.value) == "Ham is measured in slices; grams cannot be used."


def test_millilitres_and_grams_are_rejected() -> None:
    grams = _unit(1, "grams", "g", UnitFamily.WEIGHT, "1")
    millilitres = _unit(2, "millilitres", "ml", UnitFamily.VOLUME, "1")
    with pytest.raises(IncompatibleUnitError) as to_weight:
        convert(Decimal("250"), millilitres, grams, ingredient_name="Milk")
    assert "grams" in str(to_weight.value)
    with pytest.raises(IncompatibleUnitError) as to_volume:
        convert(Decimal("250"), grams, millilitres, ingredient_name="Milk")
    assert "millilitres" in str(to_volume.value)


def test_egg_and_item_are_rejected() -> None:
    egg = _unit(1, "egg", "egg", UnitFamily.COUNT, None)
    item = _unit(2, "item", "item", UnitFamily.COUNT, None)
    with pytest.raises(IncompatibleUnitError) as caught:
        convert(Decimal("2"), egg, item, ingredient_name="Eggs")
    assert str(caught.value) == "Eggs is measured in item; egg cannot be used."


def test_kitchen_units_do_not_convert_implicitly() -> None:
    teaspoon = _unit(1, "teaspoon", "tsp", UnitFamily.KITCHEN, None)
    tablespoon = _unit(2, "tablespoon", "tbsp", UnitFamily.KITCHEN, None)
    with pytest.raises(IncompatibleUnitError):
        convert(Decimal("3"), teaspoon, tablespoon, ingredient_name="Sugar")


def test_negative_quantity_is_rejected() -> None:
    grams = _unit(1, "gram", "g", UnitFamily.WEIGHT, "1")
    kilograms = _unit(2, "kilogram", "kg", UnitFamily.WEIGHT, "1000")
    with pytest.raises(InvalidQuantityError):
        convert(Decimal("-1"), kilograms, grams)


def test_float_quantity_is_rejected() -> None:
    grams = _unit(1, "gram", "g", UnitFamily.WEIGHT, "1")
    with pytest.raises(InvalidQuantityError):
        convert(1.5, grams, grams)  # type: ignore[arg-type]


def test_explicit_conversion_is_honoured() -> None:
    bulb = _unit(1, "bulb", "bulb", UnitFamily.COUNT, None)
    clove = _unit(2, "clove", "clove", UnitFamily.COUNT, None)
    conversions = [
        _Conversion(
            from_unit_id=bulb.id,
            factor_to_canonical=Decimal("10"),
            canonical_unit_id=clove.id,
        )
    ]
    assert convert(Decimal("2"), bulb, clove, conversions) == Decimal("20")


def test_explicit_conversion_does_not_apply_to_another_unit() -> None:
    bulb = _unit(1, "bulb", "bulb", UnitFamily.COUNT, None)
    clove = _unit(2, "clove", "clove", UnitFamily.COUNT, None)
    grams = _unit(3, "grams", "g", UnitFamily.WEIGHT, "1")
    conversions = [
        _Conversion(
            from_unit_id=bulb.id,
            factor_to_canonical=Decimal("10"),
            canonical_unit_id=clove.id,
        )
    ]
    with pytest.raises(IncompatibleUnitError):
        convert(Decimal("1"), bulb, grams, conversions, ingredient_name="Garlic")


def test_zero_quantity_is_allowed() -> None:
    grams = _unit(1, "gram", "g", UnitFamily.WEIGHT, "1")
    kilograms = _unit(2, "kilogram", "kg", UnitFamily.WEIGHT, "1000")
    assert convert(Decimal("0"), kilograms, grams) == Decimal("0")


def test_unit_price_stays_exact_until_the_final_rounding() -> None:
    class _Pack:
        price_pence = 179
        pack_quantity = Decimal("10")

    price = unit_price_per_canonical(_Pack())
    assert price == Decimal("17.9")
    assert allocated_cost_pence(Decimal("6"), price) == 107
    assert round_to_pence(price) == 18
