"""Pantry quantities, one row per ingredient, in canonical units."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import DecimalQuantity, utcnow

if TYPE_CHECKING:
    from app.models.ingredient import Ingredient


class PantryStock(Base):
    """On-hand quantity for one ingredient. The ingredient id is unique."""

    __tablename__ = "pantry_stock"

    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("ingredients.id", ondelete="RESTRICT"), primary_key=True
    )
    quantity_on_hand: Mapped[Decimal] = mapped_column(DecimalQuantity)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    ingredient: Mapped["Ingredient"] = relationship()
