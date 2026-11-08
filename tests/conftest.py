"""Pytest fixtures. Each test that needs a database gets its own SQLite file."""

from collections.abc import Iterator
from pathlib import Path

import pytest

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
