"""Declarative base shared by the models and Alembic."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Typed declarative base."""
