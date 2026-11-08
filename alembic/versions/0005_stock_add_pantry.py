"""add pantry stock

Revision ID: 0005_stock
Revises: 0004_planner
Create Date: 2026-11-08 15:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_stock"
down_revision: str | None = "0004_planner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pantry_stock",
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity_on_hand", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingredient_id"],
            ["ingredients.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("ingredient_id"),
    )


def downgrade() -> None:
    op.drop_table("pantry_stock")
