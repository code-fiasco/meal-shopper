"""Optional per-ingredient unit conversions."""

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import DecimalQuantity

if TYPE_CHECKING:
    from app.models.ingredient import Ingredient
    from app.models.unit import Unit


class IngredientConversion(Base):
    """Explicit factor from one unit into the ingredient's canonical unit."""

    __tablename__ = "ingredient_conversions"
    __table_args__ = (
        CheckConstraint(
            "CAST(factor_to_canonical AS NUMERIC) > 0",
            name="ck_ingredient_conversions_factor",
        ),
    )

    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("ingredients.id"), primary_key=True
    )
    from_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), primary_key=True)
    factor_to_canonical: Mapped[Decimal] = mapped_column(DecimalQuantity)

    ingredient: Mapped["Ingredient"] = relationship(back_populates="conversions")
    from_unit: Mapped["Unit"] = relationship()
