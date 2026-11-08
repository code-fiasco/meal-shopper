"""SQLite connection setup."""

from sqlalchemy import text

import app.db


def test_sqlite_enables_foreign_keys_and_wal(database_url: str) -> None:
    with app.db.engine.connect() as first:
        assert first.execute(text("PRAGMA foreign_keys")).scalar() == 1
        journal = str(first.execute(text("PRAGMA journal_mode")).scalar()).lower()
        assert journal == "wal"
        timeout = first.execute(text("PRAGMA busy_timeout")).scalar()
        assert timeout == 5000

    with app.db.engine.connect() as second:
        assert second.execute(text("PRAGMA foreign_keys")).scalar() == 1
