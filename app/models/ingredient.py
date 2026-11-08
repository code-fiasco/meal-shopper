"""Central ingredient records."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import utcnow

if TYPE_CHECKING:
    from app.models.conversion import IngredientConversion
    from app.models.purchase import PurchaseOption
    from app.models.unit import Unit


class Ingredient(Base):
    """A household ingredient with one canonical unit."""

    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    canonical_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    notes: Mapped[str | None] = mapped_column(String(2000))
    default_purchase_option_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_options.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    canonical_unit: Mapped["Unit"] = relationship()
    purchase_options: Mapped[list["PurchaseOption"]] = relationship(
        back_populates="ingredient",
        foreign_keys="PurchaseOption.ingredient_id",
    )
    conversions: Mapped[list["IngredientConversion"]] = relationship(
        back_populates="ingredient"
    )
