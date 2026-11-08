"""Pytest fixtures. Each test that needs a database gets its own SQLite file."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

import app.db as database
from app.config import get_settings
from app.db import dispose_engine, init_engine


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Point the app at a temporary SQLite file and rebuild the engine."""
    url = "sqlite:///" + (tmp_path / "test.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    init_engine(url)
    yield url
    dispose_engine()


@pytest.fixture
def session(database_url: str) -> Iterator[Session]:
    """Migrated database session. Rows added by a test are rolled back."""
    command.upgrade(Config("alembic.ini"), "head")
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
