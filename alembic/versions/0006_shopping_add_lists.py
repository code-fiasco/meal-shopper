"""add shopping lists

Revision ID: 0006_shopping
Revises: 0005_stock
Create Date: 2026-11-08 16:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_shopping"
down_revision: str | None = "0005_stock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shopping_lists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("planner_week_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'shopped')",
            name="ck_shopping_lists_status",
        ),
        sa.ForeignKeyConstraint(
            ["planner_week_id"],
            ["planner_weeks.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("planner_week_id"),
    )
    op.create_table(
        "shopping_list_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=16), nullable=False),
        sa.Column("required_quantity", sa.String(length=32), nullable=False),
        sa.Column("stock_allocated", sa.String(length=32), nullable=False),
        sa.Column("net_quantity", sa.String(length=32), nullable=False),
        sa.Column("selected_purchase_option_id", sa.Integer(), nullable=True),
        sa.Column("shop_name", sa.String(length=200), nullable=True),
        sa.Column("pack_label", sa.String(length=200), nullable=True),
        sa.Column("pack_quantity", sa.String(length=32), nullable=True),
        sa.Column("pack_price_pence", sa.Integer(), nullable=True),
        sa.Column("pack_count", sa.Integer(), nullable=False),
        sa.Column("estimated_price_pence", sa.Integer(), nullable=True),
        sa.Column("manual_price_pence", sa.Integer(), nullable=True),
        sa.Column("checked", sa.Boolean(), nullable=False),
        sa.Column("removed", sa.Boolean(), nullable=False),
        sa.Column("quantity_override", sa.String(length=32), nullable=True),
        sa.Column("pack_count_override", sa.Integer(), nullable=True),
        sa.Column("option_overridden", sa.Boolean(), nullable=False),
        sa.Column("quantity_overridden", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "source IN ('generated', 'manual')",
            name="ck_shopping_list_lines_source",
        ),
        sa.ForeignKeyConstraint(
            ["ingredient_id"],
            ["ingredients.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["shopping_lists.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["selected_purchase_option_id"],
            ["purchase_options.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shopping_list_lines_list_id",
        "shopping_list_lines",
        ["list_id"],
    )
    op.create_index(
        "ix_shopping_list_lines_ingredient_id",
        "shopping_list_lines",
        ["ingredient_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shopping_list_lines_ingredient_id", "shopping_list_lines")
    op.drop_index("ix_shopping_list_lines_list_id", "shopping_list_lines")
    op.drop_table("shopping_list_lines")
    op.drop_table("shopping_lists")
