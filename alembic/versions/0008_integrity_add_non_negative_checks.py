"""add non-negative checks for prices and quantities

Revision ID: 0008_integrity
Revises: 0007_spend
Create Date: 2026-11-08 18:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_integrity"
down_revision: str | None = "0007_spend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("units", "ck_units_factor", "factor_to_base IS NULL OR CAST(factor_to_base AS NUMERIC) > 0"),
    ("purchase_options", "ck_purchase_options_price", "price_pence >= 0"),
    (
        "purchase_options",
        "ck_purchase_options_pack",
        "CAST(pack_quantity AS NUMERIC) > 0",
    ),
    (
        "purchase_price_history",
        "ck_purchase_price_history_price",
        "price_pence >= 0",
    ),
    (
        "purchase_price_history",
        "ck_purchase_price_history_pack",
        "CAST(pack_quantity AS NUMERIC) > 0",
    ),
    (
        "ingredient_conversions",
        "ck_ingredient_conversions_factor",
        "CAST(factor_to_canonical AS NUMERIC) > 0",
    ),
    (
        "recipe_ingredients",
        "ck_recipe_ingredients_quantity",
        "CAST(quantity AS NUMERIC) >= 0",
    ),
    (
        "recipe_ingredients",
        "ck_recipe_ingredients_entered_quantity",
        "CAST(entered_quantity AS NUMERIC) >= 0",
    ),
    (
        "planner_entries",
        "ck_planner_entries_takeaway_price",
        "takeaway_price_pence IS NULL OR takeaway_price_pence >= 0",
    ),
    (
        "pantry_stock",
        "ck_pantry_stock_quantity",
        "CAST(quantity_on_hand AS NUMERIC) >= 0",
    ),
    (
        "shopping_list_lines",
        "ck_shopping_list_lines_required",
        "CAST(required_quantity AS NUMERIC) >= 0",
    ),
    (
        "shopping_list_lines",
        "ck_shopping_list_lines_stock",
        "CAST(stock_allocated AS NUMERIC) >= 0",
    ),
    (
        "shopping_list_lines",
        "ck_shopping_list_lines_net",
        "CAST(net_quantity AS NUMERIC) >= 0",
    ),
    (
        "shopping_list_lines",
        "ck_shopping_list_lines_pack_quantity",
        "pack_quantity IS NULL OR CAST(pack_quantity AS NUMERIC) > 0",
    ),
    (
        "shopping_list_lines",
        "ck_shopping_list_lines_override",
        "quantity_override IS NULL OR CAST(quantity_override AS NUMERIC) >= 0",
    ),
    ("shopping_list_lines", "ck_shopping_list_lines_pack_count", "pack_count >= 0"),
    (
        "shopping_list_lines",
        "ck_shopping_list_lines_pack_count_override",
        "pack_count_override IS NULL OR pack_count_override >= 0",
    ),
    (
        "shopping_list_lines",
        "ck_shopping_list_lines_pack_price",
        "pack_price_pence IS NULL OR pack_price_pence >= 0",
    ),
    (
        "shopping_list_lines",
        "ck_shopping_list_lines_estimated_price",
        "estimated_price_pence IS NULL OR estimated_price_pence >= 0",
    ),
    (
        "shopping_list_lines",
        "ck_shopping_list_lines_manual_price",
        "manual_price_pence IS NULL OR manual_price_pence >= 0",
    ),
    (
        "shopping_transaction_lines",
        "ck_shopping_transaction_lines_quantity",
        "actual_quantity IS NULL OR CAST(actual_quantity AS NUMERIC) >= 0",
    ),
)


def _grouped() -> dict[str, list[tuple[str, str]]]:
    grouped: dict[str, list[tuple[str, str]]] = {}
    for table, name, expression in _CHECKS:
        grouped.setdefault(table, []).append((name, expression))
    return grouped


def upgrade() -> None:
    for table, checks in _grouped().items():
        with op.batch_alter_table(table) as batch:
            for name, expression in checks:
                batch.create_check_constraint(name, expression)


def downgrade() -> None:
    for table, checks in reversed(_grouped().items()):
        with op.batch_alter_table(table) as batch:
            for name, _expression in reversed(checks):
                batch.drop_constraint(name, type_="check")
