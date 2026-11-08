"""Persistence models. Domain tables are added in later migrations."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Typed declarative base shared with Alembic."""
