"""Estimated ingredient cost of a two-person recipe."""

from dataclasses import dataclass
from decimal import Decimal

from app.models import Ingredient, PurchaseOption
from app.services.units import allocated_cost_pence, unit_price_per_canonical

PORTIONS = 2


@dataclass(frozen=True)
class LineCost:
    ingredient_id: int
    ingredient_name: str
    entered_quantity: Decimal
    entered_unit_symbol: str
    canonical_quantity: Decimal
    canonical_symbol: str
    cost_pence: int | None
    option_label: str | None


@dataclass(frozen=True)
class MealCost:
    """Allocated cost of the lines that have a price. Missing prices are omitted."""

    total_pence: int
    per_person_pence: Decimal | None
    is_complete: bool
    missing_ingredients: tuple[str, ...]
    lines: tuple[LineCost, ...]

    def incomplete_label(self) -> str | None:
        """Exact list text. Missing prices are never described as £0."""
        if self.is_complete:
            return None
        names = ", ".join(self.missing_ingredients)
        return f"incomplete: missing price for {names}"


def cost_lines(
    rows: list[tuple[Ingredient, Decimal, str, Decimal, str]],
) -> MealCost:
    """Cost rows of ingredient, entered amount, and canonical amount."""
    lines: list[LineCost] = []
    missing: list[str] = []
    total = 0
    for row in rows:
        (
            ingredient,
            entered_quantity,
            entered_symbol,
            canonical_quantity,
            canonical_symbol,
        ) = row
        option = costing_option(ingredient)
        if option is None:
            missing.append(ingredient.name)
            cost_pence = None
            label = None
        else:
            cost_pence = allocated_cost_pence(
                canonical_quantity, unit_price_per_canonical(option)
            )
            total += cost_pence
            label = option.pack_label
        lines.append(
            LineCost(
                ingredient_id=ingredient.id,
                ingredient_name=ingredient.name,
                entered_quantity=entered_quantity,
                entered_unit_symbol=entered_symbol,
                canonical_quantity=canonical_quantity,
                canonical_symbol=canonical_symbol,
                cost_pence=cost_pence,
                option_label=label,
            )
        )
    complete = not missing
    return MealCost(
        total_pence=total,
        per_person_pence=Decimal(total) / Decimal(PORTIONS) if complete else None,
        is_complete=complete,
        missing_ingredients=tuple(missing),
        lines=tuple(lines),
    )


def costing_option(ingredient: Ingredient) -> PurchaseOption | None:
    """Designated active pack, otherwise the cheapest active unit price."""
    active = [option for option in ingredient.purchase_options if option.is_active]
    designated = _designated(ingredient, active)
    if designated is not None:
        return designated
    if not active:
        return None
    return min(active, key=_price_key)


def _designated(
    ingredient: Ingredient, active: list[PurchaseOption]
) -> PurchaseOption | None:
    chosen_id = ingredient.default_purchase_option_id
    if chosen_id is None:
        return None
    for option in active:
        if option.id == chosen_id:
            return option
    return None


def _price_key(option: PurchaseOption) -> tuple[Decimal, int]:
    return (unit_price_per_canonical(option), option.id)
