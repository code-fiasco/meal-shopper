"""Recipes for two portions, with ingredient lines stored in canonical units."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import DecimalQuantity, utcnow

if TYPE_CHECKING:
    from app.models.ingredient import Ingredient
    from app.models.unit import Unit


class Meal(Base):
    """A household recipe. Every meal is for two portions."""

    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000))
    instructions: Mapped[str | None] = mapped_column(String(8000))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    lines: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="meal",
        order_by="RecipeIngredient.sort_order",
        cascade="all, delete-orphan",
    )


class RecipeIngredient(Base):
    """One ingredient line. Quantity is stored in the canonical unit."""

    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(DecimalQuantity)
    entered_quantity: Mapped[Decimal] = mapped_column(DecimalQuantity)
    entered_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"))
    notes: Mapped[str | None] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(default=0)

    meal: Mapped[Meal] = relationship(back_populates="lines")
    ingredient: Mapped["Ingredient"] = relationship()
    entered_unit: Mapped["Unit"] = relationship()
