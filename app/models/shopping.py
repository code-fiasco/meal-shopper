"""A week's shopping list, with generated lines and manual additions."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import DecimalQuantity, utcnow

if TYPE_CHECKING:
    from app.models.ingredient import Ingredient
    from app.models.planner import PlannerWeek
    from app.models.purchase import PurchaseOption


class ShoppingList(Base):
    """The primary shopping list for one planner week."""

    __tablename__ = "shopping_lists"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'shopped')",
            name="ck_shopping_lists_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    planner_week_id: Mapped[int] = mapped_column(
        ForeignKey("planner_weeks.id", ondelete="RESTRICT"),
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    week: Mapped["PlannerWeek"] = relationship()
    lines: Mapped[list["ShoppingListLine"]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
        order_by="ShoppingListLine.id",
    )


class ShoppingListLine(Base):
    """One generated or manual row. Names, packs, and prices are snapshotted."""

    __tablename__ = "shopping_list_lines"
    __table_args__ = (
        CheckConstraint(
            "source IN ('generated', 'manual')",
            name="ck_shopping_list_lines_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(
        ForeignKey("shopping_lists.id", ondelete="CASCADE"),
        index=True,
    )
    source: Mapped[str] = mapped_column(String(16))
    ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredients.id", ondelete="RESTRICT"),
        index=True,
    )
    description: Mapped[str] = mapped_column(String(200))
    unit_snapshot: Mapped[str] = mapped_column(String(16), default="")
    required_quantity: Mapped[Decimal] = mapped_column(DecimalQuantity)
    stock_allocated: Mapped[Decimal] = mapped_column(DecimalQuantity)
    net_quantity: Mapped[Decimal] = mapped_column(DecimalQuantity)
    selected_purchase_option_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_options.id", ondelete="RESTRICT")
    )
    shop_name: Mapped[str | None] = mapped_column(String(200))
    pack_label: Mapped[str | None] = mapped_column(String(200))
    pack_quantity: Mapped[Decimal | None] = mapped_column(DecimalQuantity)
    pack_price_pence: Mapped[int | None] = mapped_column()
    pack_count: Mapped[int] = mapped_column(default=0)
    estimated_price_pence: Mapped[int | None] = mapped_column()
    manual_price_pence: Mapped[int | None] = mapped_column()
    checked: Mapped[bool] = mapped_column(default=False)
    removed: Mapped[bool] = mapped_column(default=False)
    quantity_override: Mapped[Decimal | None] = mapped_column(DecimalQuantity)
    pack_count_override: Mapped[int | None] = mapped_column()
    option_overridden: Mapped[bool] = mapped_column(default=False)
    quantity_overridden: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(String(500))

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="lines")
    ingredient: Mapped["Ingredient | None"] = relationship()
    purchase_option: Mapped["PurchaseOption | None"] = relationship()
