"""Demo data is optional and does not duplicate itself."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Ingredient, Meal, PlannerEntry
from app.services.seed import seed_demo


def test_seed_creates_a_week_once(session: Session) -> None:
    first = seed_demo(session)
    assert first.created is True
    assert session.scalar(select(func.count()).select_from(Ingredient)) == 3
    assert session.scalar(select(func.count()).select_from(Meal)) == 2
    assert session.scalar(select(func.count()).select_from(PlannerEntry)) == 5
    assert session.scalar(select(Meal).where(Meal.name == "Tomato pasta")) is not None
    second = seed_demo(session)
    assert second.created is False
    assert session.scalar(select(func.count()).select_from(Meal)) == 2
