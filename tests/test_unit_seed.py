"""Built-in unit catalogue."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Unit, UnitFamily
from app.services.unit_catalog import UNIT_SEEDS, seed_units


def test_migration_seeds_units(session: Session) -> None:
    stored = session.scalars(select(Unit).order_by(Unit.symbol)).all()
    assert {unit.symbol for unit in stored} == {spec.symbol for spec in UNIT_SEEDS}
    gram = next(unit for unit in stored if unit.symbol == "g")
    kilogram = next(unit for unit in stored if unit.symbol == "kg")
    litre = next(unit for unit in stored if unit.symbol == "litre")
    egg = next(unit for unit in stored if unit.symbol == "egg")
    teaspoon = next(unit for unit in stored if unit.symbol == "tsp")
    assert gram.family is UnitFamily.WEIGHT
    assert gram.factor_to_base == Decimal("1")
    assert kilogram.factor_to_base == Decimal("1000")
    assert litre.family is UnitFamily.VOLUME
    assert litre.factor_to_base == Decimal("1000")
    assert egg.family is UnitFamily.COUNT
    assert egg.factor_to_base is None
    assert teaspoon.family is UnitFamily.KITCHEN
    assert teaspoon.factor_to_base is None


def test_seed_units_is_idempotent(session: Session) -> None:
    before = session.scalar(select(func.count()).select_from(Unit))
    assert seed_units(session) == 0
    assert seed_units(session) == 0
    after = session.scalar(select(func.count()).select_from(Unit))
    assert before == after == len(UNIT_SEEDS)
