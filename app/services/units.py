"""Pure unit conversion and per-unit price calculations."""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from app.models.unit import UnitFamily

_METRIC_FAMILIES = frozenset({UnitFamily.WEIGHT, UnitFamily.VOLUME})
_PENCE = Decimal("1")


class UnitView(Protocol):
    """Fields the converter needs from a unit."""

    id: int
    name: str
    family: UnitFamily
    factor_to_base: Decimal | None


class ConversionView(Protocol):
    """An explicit factor from one unit into the canonical unit."""

    from_unit_id: int
    factor_to_canonical: Decimal


class IncompatibleUnitError(ValueError):
    """Raised when a quantity cannot be expressed in the canonical unit."""


class InvalidQuantityError(ValueError):
    """Raised when a quantity is negative, non-finite, or not a Decimal."""


def convert(
    quantity: Decimal,
    from_unit: UnitView,
    to_unit: UnitView,
    ingredient_conversions: Sequence[ConversionView] | None = None,
    *,
    ingredient_name: str | None = None,
) -> Decimal:
    """Convert quantity into to_unit.

    Weight converts only to weight, and volume only to volume, using exact
    factors. Anything else needs an explicit conversion into to_unit.
    """
    amount = _require_quantity(quantity)
    if _same_unit(from_unit, to_unit):
        return amount
    if _metric_pair(from_unit, to_unit):
        return _convert_metric(amount, from_unit, to_unit)
    factor = _explicit_factor(from_unit, to_unit, ingredient_conversions)
    if factor is not None:
        return amount * factor
    raise _incompatible(from_unit, to_unit, ingredient_name)


def unit_price_per_canonical(option: object) -> Decimal:
    """Pence per canonical unit, unrounded."""
    price_pence = getattr(option, "price_pence")
    pack_quantity = getattr(option, "pack_quantity")
    if isinstance(price_pence, bool) or not isinstance(price_pence, int):
        raise TypeError("Price must be integer pence.")
    if price_pence < 0:
        raise InvalidQuantityError("Price cannot be negative.")
    pack = _require_quantity(pack_quantity)
    if pack == 0:
        raise InvalidQuantityError("Pack quantity must be greater than zero.")
    return Decimal(price_pence) / pack


def round_to_pence(amount: Decimal) -> int:
    """Round a pence amount to a whole penny, half up."""
    if isinstance(amount, float) or not isinstance(amount, Decimal):
        raise TypeError("Money calculations must use Decimal.")
    return int(amount.quantize(_PENCE, rounding=ROUND_HALF_UP))


def allocated_cost_pence(quantity: Decimal, unit_price: Decimal) -> int:
    """Cost of a quantity, rounded to whole pence only after multiplying."""
    amount = _require_quantity(quantity)
    if isinstance(unit_price, float) or not isinstance(unit_price, Decimal):
        raise TypeError("Unit price must be Decimal pence.")
    return round_to_pence(amount * unit_price)


def _require_quantity(quantity: Decimal) -> Decimal:
    if isinstance(quantity, float) or not isinstance(quantity, Decimal):
        raise InvalidQuantityError("Quantity must be Decimal, not float.")
    if not quantity.is_finite():
        raise InvalidQuantityError("Quantity must be a finite number.")
    if quantity < 0:
        raise InvalidQuantityError("Quantity cannot be negative.")
    return quantity


def _same_unit(from_unit: UnitView, to_unit: UnitView) -> bool:
    if from_unit.id is not None and to_unit.id is not None:
        return from_unit.id == to_unit.id
    return from_unit.name == to_unit.name and _family(from_unit) == _family(to_unit)


def _family(unit: UnitView) -> UnitFamily:
    family = unit.family
    if isinstance(family, UnitFamily):
        return family
    return UnitFamily(str(family))


def _metric_pair(from_unit: UnitView, to_unit: UnitView) -> bool:
    family = _family(from_unit)
    return family in _METRIC_FAMILIES and family == _family(to_unit)


def _convert_metric(
    quantity: Decimal, from_unit: UnitView, to_unit: UnitView
) -> Decimal:
    from_factor = from_unit.factor_to_base
    to_factor = to_unit.factor_to_base
    if from_factor is None or to_factor is None or to_factor == 0:
        raise _incompatible(from_unit, to_unit, None)
    return quantity * from_factor / to_factor


def _explicit_factor(
    from_unit: UnitView,
    to_unit: UnitView,
    conversions: Sequence[ConversionView] | None,
) -> Decimal | None:
    if not conversions:
        return None
    for conversion in conversions:
        if conversion.from_unit_id != from_unit.id:
            continue
        target_id = getattr(conversion, "canonical_unit_id", None)
        if target_id is not None and target_id != to_unit.id:
            continue
        factor = conversion.factor_to_canonical
        if isinstance(factor, float) or not isinstance(factor, Decimal):
            raise InvalidQuantityError("Conversion factor must be Decimal.")
        if not factor.is_finite() or factor <= 0:
            raise InvalidQuantityError("Conversion factor must be positive.")
        return factor
    return None


def _incompatible(
    from_unit: UnitView, to_unit: UnitView, ingredient_name: str | None
) -> IncompatibleUnitError:
    subject = ingredient_name or "This ingredient"
    message = (
        f"{subject} is measured in {to_unit.name}; {from_unit.name} cannot be used."
    )
    return IncompatibleUnitError(message)
