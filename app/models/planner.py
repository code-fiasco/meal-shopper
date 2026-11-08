"""Monday-based weeks and the lunch and dinner slots on them."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.meal import Meal
from app.models.types import utcnow


class PlannerWeek(Base):
    """One planning week. Created the first time a slot in that week is saved."""

    __tablename__ = "planner_weeks"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start_date: Mapped[date] = mapped_column(Date, unique=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    notes: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    entries: Mapped[list["PlannerEntry"]] = relationship(
        back_populates="week",
        cascade="all, delete-orphan",
        order_by="PlannerEntry.plan_date",
    )


class PlannerEntry(Base):
    """One lunch or dinner. The meal name is snapshotted when the slot is saved."""

    __tablename__ = "planner_entries"
    __table_args__ = (
        UniqueConstraint("date", "slot", name="uq_planner_entries_date_slot"),
        CheckConstraint(
            "slot IN ('lunch', 'dinner')",
            name="ck_planner_entries_slot",
        ),
        CheckConstraint(
            "entry_type IN ('meal', 'takeaway', 'blank')",
            name="ck_planner_entries_entry_type",
        ),
        CheckConstraint(
            "takeaway_price_pence IS NULL OR takeaway_price_pence >= 0",
            name="ck_planner_entries_takeaway_price",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    week_id: Mapped[int] = mapped_column(
        ForeignKey("planner_weeks.id", ondelete="CASCADE"),
        index=True,
    )
    plan_date: Mapped[date] = mapped_column("date", Date)
    slot: Mapped[str] = mapped_column(String(16))
    entry_type: Mapped[str] = mapped_column(String(16))
    meal_id: Mapped[int | None] = mapped_column(
        ForeignKey("meals.id", ondelete="RESTRICT"),
        index=True,
    )
    snapshot_meal_name: Mapped[str | None] = mapped_column(String(200))
    takeaway_description: Mapped[str | None] = mapped_column(String(200))
    takeaway_price_pence: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    week: Mapped[PlannerWeek] = relationship(back_populates="entries")
    meal: Mapped[Meal | None] = relationship()
