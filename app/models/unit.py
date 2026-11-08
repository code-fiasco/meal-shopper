"""Canonical measurement units."""

from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import DecimalQuantity


class UnitFamily(StrEnum):
    WEIGHT = "weight"
    VOLUME = "volume"
    COUNT = "count"
    KITCHEN = "kitchen"


class Unit(Base):
    """One measurement unit. Metric units carry an exact factor to the family base."""

    __tablename__ = "units"
    __table_args__ = (
        CheckConstraint(
            "factor_to_base IS NULL OR CAST(factor_to_base AS NUMERIC) > 0",
            name="ck_units_factor",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True)
    family: Mapped[UnitFamily] = mapped_column(
        Enum(
            UnitFamily,
            native_enum=False,
            length=16,
            values_callable=lambda choices: [item.value for item in choices],
        )
    )
    factor_to_base: Mapped[Decimal | None] = mapped_column(DecimalQuantity)
