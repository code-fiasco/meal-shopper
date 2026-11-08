"""Optional sample data. Nothing here runs unless someone asks for it."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Meal, Unit
from app.services.ingredients import create_ingredient
from app.services.meals import RawLine, prepare_lines, save_meal
from app.services.planner import (
    assign_blank,
    assign_meal,
    assign_takeaway,
    local_today,
    week_start_for,
)
from app.services.purchase_options import create_purchase_option
from app.services.shops import create_shop
from app.services.stock import SET, adjust_stock

_MARKER = "Tomato pasta"


@dataclass(frozen=True)
class SeedResult:
    """Whether this call added the sample week."""

    created: bool


def seed_demo(session: Session) -> SeedResult:
    """Create sample ingredients, meals, and the current week's plan.

    A second run leaves the database unchanged once Tomato pasta exists.
    """
    existing = session.scalar(select(Unit.id).limit(1))
    if existing is None:
        raise RuntimeError("Seed the unit catalogue before adding demo data.")
    if _meal_exists(session):
        return SeedResult(created=False)

    grams = _unit(session, "g")
    eggs = _unit(session, "egg")
    market = create_shop(session, name="Market")
    corner = create_shop(session, name="Corner shop")
    pasta = create_ingredient(session, name="Pasta", canonical_unit=grams).ingredient
    tomatoes = create_ingredient(
        session, name="Tinned tomatoes", canonical_unit=grams
    ).ingredient
    egg = create_ingredient(session, name="Eggs", canonical_unit=eggs).ingredient
    create_purchase_option(
        session,
        ingredient=pasta,
        shop=market,
        pack_quantity=Decimal("500"),
        pack_label="500g bag",
        price_pence=120,
    )
    create_purchase_option(
        session,
        ingredient=tomatoes,
        shop=market,
        pack_quantity=Decimal("400"),
        pack_label="400g tin",
        price_pence=85,
    )
    create_purchase_option(
        session,
        ingredient=egg,
        shop=corner,
        pack_quantity=Decimal("6"),
        pack_label="box of 6",
        price_pence=180,
    )
    tomato_pasta = _meal(
        session,
        _MARKER,
        [
            RawLine(str(pasta.id), "200", str(grams.id), ""),
            RawLine(str(tomatoes.id), "300", str(grams.id), ""),
        ],
    )
    fried_eggs = _meal(
        session,
        "Fried eggs",
        [RawLine(str(egg.id), "4", str(eggs.id), "")],
    )
    monday = week_start_for(local_today(get_settings().app_timezone))
    assign_meal(session, plan_date=monday, slot="lunch", meal_id=tomato_pasta)
    assign_meal(session, plan_date=monday, slot="dinner", meal_id=fried_eggs)
    assign_meal(
        session,
        plan_date=monday + timedelta(days=1),
        slot="lunch",
        meal_id=tomato_pasta,
    )
    assign_blank(session, plan_date=monday + timedelta(days=2), slot="lunch")
    assign_takeaway(
        session,
        plan_date=monday + timedelta(days=4),
        slot="dinner",
        price="12.50",
        description="Curry",
    )
    adjust_stock(
        session,
        ingredient_id=pasta.id,
        action=SET,
        quantity="50",
        unit_id=str(grams.id),
    )
    return SeedResult(created=True)


def _meal_exists(session: Session) -> bool:
    found = session.scalar(select(Meal.id).where(Meal.name == _MARKER))
    return found is not None


def _unit(session: Session, symbol: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    if unit is None:
        raise RuntimeError(f"Unit {symbol} is not in the catalogue.")
    return unit


def _meal(session: Session, name: str, lines: list[RawLine]) -> int:
    prepared, errors = prepare_lines(session, lines)
    if errors:
        raise RuntimeError(f"Could not prepare {name}: {errors}")
    meal = save_meal(
        session,
        None,
        name=name,
        description=None,
        instructions=None,
        lines=prepared,
    )
    return meal.id
