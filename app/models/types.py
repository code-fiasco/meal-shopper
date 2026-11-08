"""Column types that keep quantities as fixed-precision decimals."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Dialect, String
from sqlalchemy.types import TypeDecorator

QUANTITY_SCALE = 6
_QUANTUM = Decimal("0.000001")


class DecimalQuantity(TypeDecorator[Decimal]):
    """Store a Decimal as text so SQLite never converts it to float."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) or not isinstance(value, Decimal):
            raise TypeError("Quantities must be Decimal, not float.")
        if not value.is_finite():
            raise ValueError("Quantity must be a finite Decimal.")
        return format(value.quantize(_QUANTUM), "f")

    def process_result_value(
        self, value: str | None, dialect: Dialect
    ) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)


def utcnow() -> datetime:
    """Timezone-aware timestamp for created and updated columns."""
    return datetime.now(UTC)
