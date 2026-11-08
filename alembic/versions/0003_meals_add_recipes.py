"""add meals and recipe lines

Revision ID: 0003_meals
Revises: 0002_catalog
Create Date: 2026-11-08 14:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.models.types  # noqa: F401

revision: str = "0003_meals"
down_revision: str | None = "0002_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("instructions", sa.String(length=8000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "recipe_ingredients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meal_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.String(length=32), nullable=False),
        sa.Column("entered_quantity", sa.String(length=32), nullable=False),
        sa.Column("entered_unit_id", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["entered_unit_id"], ["units.id"]),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["meal_id"], ["meals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recipe_ingredients_meal_id",
        "recipe_ingredients",
        ["meal_id"],
    )
    op.create_index(
        "ix_recipe_ingredients_ingredient_id",
        "recipe_ingredients",
        ["ingredient_id"],
    )
    with op.batch_alter_table("ingredients") as batch:
        batch.add_column(
            sa.Column("default_purchase_option_id", sa.Integer(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_ingredients_default_purchase_option",
            "purchase_options",
            ["default_purchase_option_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("ingredients") as batch:
        batch.drop_constraint(
            "fk_ingredients_default_purchase_option", type_="foreignkey"
        )
        batch.drop_column("default_purchase_option_id")
    op.drop_index(
        "ix_recipe_ingredients_ingredient_id", table_name="recipe_ingredients"
    )
    op.drop_index("ix_recipe_ingredients_meal_id", table_name="recipe_ingredients")
    op.drop_table("recipe_ingredients")
    op.drop_table("meals")
