"""Built-in units. Seeding inserts any symbol that is not already stored."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.unit import Unit, UnitFamily


@dataclass(frozen=True)
class UnitSeed:
    name: str
    symbol: str
    family: UnitFamily
    factor_to_base: Decimal | None


UNIT_SEEDS: tuple[UnitSeed, ...] = (
    UnitSeed("milligram", "mg", UnitFamily.WEIGHT, Decimal("0.001")),
    UnitSeed("gram", "g", UnitFamily.WEIGHT, Decimal("1")),
    UnitSeed("kilogram", "kg", UnitFamily.WEIGHT, Decimal("1000")),
    UnitSeed("millilitre", "ml", UnitFamily.VOLUME, Decimal("1")),
    UnitSeed("litre", "litre", UnitFamily.VOLUME, Decimal("1000")),
    UnitSeed("egg", "egg", UnitFamily.COUNT, None),
    UnitSeed("slice", "slice", UnitFamily.COUNT, None),
    UnitSeed("clove", "clove", UnitFamily.COUNT, None),
    UnitSeed("item", "item", UnitFamily.COUNT, None),
    UnitSeed("pack", "pack", UnitFamily.COUNT, None),
    UnitSeed("teaspoon", "tsp", UnitFamily.KITCHEN, None),
    UnitSeed("tablespoon", "tbsp", UnitFamily.KITCHEN, None),
    UnitSeed("cup", "cup", UnitFamily.KITCHEN, None),
    UnitSeed("handful", "handful", UnitFamily.KITCHEN, None),
    UnitSeed("pinch", "pinch", UnitFamily.KITCHEN, None),
)


def seed_units(session: Session) -> int:
    """Insert missing built-in units. A second call inserts nothing."""
    stored = set(session.scalars(select(Unit.symbol)))
    inserted = 0
    for spec in UNIT_SEEDS:
        if spec.symbol in stored:
            continue
        session.add(
            Unit(
                name=spec.name,
                symbol=spec.symbol,
                family=spec.family,
                factor_to_base=spec.factor_to_base,
            )
        )
        inserted += 1
    session.flush()
    return inserted
