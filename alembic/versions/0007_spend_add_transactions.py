"""add shopping transactions

Revision ID: 0007_spend
Revises: 0006_shopping
Create Date: 2026-11-08 17:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_spend"
down_revision: str | None = "0006_shopping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shopping_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("planner_week_id", sa.Integer(), nullable=False),
        sa.Column("shopping_list_id", sa.Integer(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("actual_total_pence", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "actual_total_pence >= 0",
            name="ck_shopping_transactions_total",
        ),
        sa.ForeignKeyConstraint(
            ["planner_week_id"],
            ["planner_weeks.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shopping_list_id"],
            ["shopping_lists.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shopping_transactions_planner_week_id",
        "shopping_transactions",
        ["planner_week_id"],
    )
    op.create_index(
        "ix_shopping_transactions_shopping_list_id",
        "shopping_transactions",
        ["shopping_list_id"],
    )
    op.create_table(
        "shopping_transaction_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("list_line_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("actual_quantity", sa.String(length=32), nullable=True),
        sa.Column("unit_snapshot", sa.String(length=16), nullable=False),
        sa.Column("actual_price_pence", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "actual_price_pence IS NULL OR actual_price_pence >= 0",
            name="ck_shopping_transaction_lines_price",
        ),
        sa.ForeignKeyConstraint(
            ["list_line_id"],
            ["shopping_list_lines.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["shopping_transactions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shopping_transaction_lines_transaction_id",
        "shopping_transaction_lines",
        ["transaction_id"],
    )
    op.create_index(
        "ix_shopping_transaction_lines_list_line_id",
        "shopping_transaction_lines",
        ["list_line_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shopping_transaction_lines_list_line_id",
        table_name="shopping_transaction_lines",
    )
    op.drop_index(
        "ix_shopping_transaction_lines_transaction_id",
        table_name="shopping_transaction_lines",
    )
    op.drop_table("shopping_transaction_lines")
    op.drop_index(
        "ix_shopping_transactions_shopping_list_id",
        table_name="shopping_transactions",
    )
    op.drop_index(
        "ix_shopping_transactions_planner_week_id",
        table_name="shopping_transactions",
    )
    op.drop_table("shopping_transactions")
