"""Shop-specific packs and their append-only price history."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import DecimalQuantity, utcnow

if TYPE_CHECKING:
    from app.models.ingredient import Ingredient
    from app.models.shop import Shop


class PriceHistoryImmutableError(RuntimeError):
    """Raised when code tries to edit or delete a price-history row."""


class PurchaseOption(Base):
    """A pack of an ingredient sold by one shop, priced in integer pence."""

    __tablename__ = "purchase_options"
    __table_args__ = (
        CheckConstraint("price_pence >= 0", name="ck_purchase_options_price"),
        CheckConstraint(
            "CAST(pack_quantity AS NUMERIC) > 0",
            name="ck_purchase_options_pack",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    pack_quantity: Mapped[Decimal] = mapped_column(DecimalQuantity)
    pack_label: Mapped[str] = mapped_column(String(200))
    price_pence: Mapped[int]
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    ingredient: Mapped["Ingredient"] = relationship(
        back_populates="purchase_options",
        foreign_keys=[ingredient_id],
    )
    shop: Mapped["Shop"] = relationship()
    price_history: Mapped[list["PurchasePriceHistory"]] = relationship(
        back_populates="purchase_option",
        order_by="PurchasePriceHistory.recorded_at",
    )


class PurchasePriceHistory(Base):
    """Snapshot of a pack price. Rows are inserted and then left unchanged."""

    __tablename__ = "purchase_price_history"
    __table_args__ = (
        CheckConstraint("price_pence >= 0", name="ck_purchase_price_history_price"),
        CheckConstraint(
            "CAST(pack_quantity AS NUMERIC) > 0",
            name="ck_purchase_price_history_pack",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_option_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_options.id"), index=True
    )
    price_pence: Mapped[int]
    pack_quantity: Mapped[Decimal] = mapped_column(DecimalQuantity)
    recorded_at: Mapped[datetime] = mapped_column(default=utcnow)

    purchase_option: Mapped[PurchaseOption] = relationship(
        back_populates="price_history"
    )


def _reject_history_mutation(
    _mapper: object, _connection: object, _target: object
) -> None:
    raise PriceHistoryImmutableError("Price history rows cannot be edited or deleted.")


event.listen(PurchasePriceHistory, "before_update", _reject_history_mutation)
event.listen(PurchasePriceHistory, "before_delete", _reject_history_mutation)
