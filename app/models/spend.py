"""What was actually paid, kept apart from shopping estimates."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.planner import PlannerWeek
from app.models.shopping import ShoppingList, ShoppingListLine
from app.models.types import DecimalQuantity, utcnow


class ShoppingTransaction(Base):
    """One shop for a planner week. The total is entered, never copied."""

    __tablename__ = "shopping_transactions"
    __table_args__ = (
        CheckConstraint(
            "actual_total_pence >= 0",
            name="ck_shopping_transactions_total",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    planner_week_id: Mapped[int] = mapped_column(
        ForeignKey("planner_weeks.id", ondelete="RESTRICT"),
        index=True,
    )
    shopping_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("shopping_lists.id", ondelete="SET NULL"),
        index=True,
    )
    spent_on: Mapped[date] = mapped_column("date", Date)
    actual_total_pence: Mapped[int] = mapped_column()
    notes: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    week: Mapped[PlannerWeek] = relationship()
    shopping_list: Mapped[ShoppingList | None] = relationship()
    lines: Mapped[list["ShoppingTransactionLine"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="ShoppingTransactionLine.id",
    )


class ShoppingTransactionLine(Base):
    """Optional detail for one list row. Description and unit are snapshotted."""

    __tablename__ = "shopping_transaction_lines"
    __table_args__ = (
        CheckConstraint(
            "actual_price_pence IS NULL OR actual_price_pence >= 0",
            name="ck_shopping_transaction_lines_price",
        ),
        CheckConstraint(
            "actual_quantity IS NULL OR CAST(actual_quantity AS NUMERIC) >= 0",
            name="ck_shopping_transaction_lines_quantity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("shopping_transactions.id", ondelete="CASCADE"),
        index=True,
    )
    list_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("shopping_list_lines.id", ondelete="SET NULL"),
        index=True,
    )
    description: Mapped[str] = mapped_column(String(200))
    actual_quantity: Mapped[Decimal | None] = mapped_column(DecimalQuantity)
    unit_snapshot: Mapped[str] = mapped_column(String(16), default="")
    actual_price_pence: Mapped[int | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(String(500))

    transaction: Mapped[ShoppingTransaction] = relationship(back_populates="lines")
    list_line: Mapped[ShoppingListLine | None] = relationship()
