"""Database engine and session dependency."""

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

engine: Engine
SessionLocal: sessionmaker[Session]


def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def build_engine(database_url: str) -> Engine:
    """Create an engine. SQLite connections enable foreign keys and WAL mode."""
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 5
    new_engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        event.listen(new_engine, "connect", _set_sqlite_pragmas)
    return new_engine


def init_engine(database_url: str | None = None) -> Engine:
    """Bind the process engine and session factory, replacing any previous engine."""
    global engine, SessionLocal
    previous = globals().get("engine")
    if isinstance(previous, Engine):
        previous.dispose()
    url = get_settings().database_url if database_url is None else database_url
    engine = build_engine(url)
    SessionLocal = sessionmaker(bind=engine)
    return engine


def dispose_engine() -> None:
    """Close pooled connections for the process engine."""
    current = globals().get("engine")
    if isinstance(current, Engine):
        current.dispose()


def get_db() -> Generator[Session, None, None]:
    """Yield a session and close it when the request finishes."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


init_engine()
