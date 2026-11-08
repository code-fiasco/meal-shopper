"""add planner weeks and entries

Revision ID: 0004_planner
Revises: 0003_meals
Create Date: 2026-11-08 14:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_planner"
down_revision: str | None = "0003_meals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "planner_weeks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("week_start_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("week_start_date"),
    )
    op.create_table(
        "planner_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("week_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(length=16), nullable=False),
        sa.Column("entry_type", sa.String(length=16), nullable=False),
        sa.Column("meal_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_meal_name", sa.String(length=200), nullable=True),
        sa.Column("takeaway_description", sa.String(length=200), nullable=True),
        sa.Column("takeaway_price_pence", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "slot IN ('lunch', 'dinner')",
            name="ck_planner_entries_slot",
        ),
        sa.CheckConstraint(
            "entry_type IN ('meal', 'takeaway', 'blank')",
            name="ck_planner_entries_entry_type",
        ),
        sa.ForeignKeyConstraint(
            ["meal_id"],
            ["meals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["week_id"],
            ["planner_weeks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "slot", name="uq_planner_entries_date_slot"),
    )
    op.create_index(
        "ix_planner_entries_week_id",
        "planner_entries",
        ["week_id"],
    )
    op.create_index(
        "ix_planner_entries_meal_id",
        "planner_entries",
        ["meal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_planner_entries_meal_id", table_name="planner_entries")
    op.drop_index("ix_planner_entries_week_id", table_name="planner_entries")
    op.drop_table("planner_entries")
    op.drop_table("planner_weeks")
