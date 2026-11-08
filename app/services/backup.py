"""SQLite online backup and restore. Copies go through Connection.backup."""

import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine.url import make_url

from app.config import get_settings


def sqlite_path(database_url: str) -> Path:
    """File path for a SQLite URL. Memory databases cannot be backed up here."""
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        raise RuntimeError("Backups require a SQLite database file.")
    if url.database == ":memory:":
        raise RuntimeError("An in-memory database has no file to back up.")
    return Path(url.database)


def backup_sqlite(source: Path, destination: Path) -> None:
    """Copy source into destination with SQLite's online backup API."""
    if not source.is_file():
        raise FileNotFoundError(f"Database file not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source)
    dest_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()
    _require_integrity(destination)


def write_timestamped_backup(database_url: str, now: datetime | None = None) -> Path:
    """Write a timestamped copy next to the live database, under backups/."""
    source = sqlite_path(database_url)
    destination = _unique_backup_path(source, now)
    backup_sqlite(source, destination)
    return destination


def restore_database(backup: Path, destination: Path) -> None:
    """Replace destination with the contents of backup.

    Stop the application first. A restore removes any leftover WAL files so
    SQLite cannot replay the previous database over the restored pages.
    """
    if not backup.is_file():
        raise FileNotFoundError(f"Backup file not found: {backup}")
    if backup.resolve() == destination.resolve():
        raise ValueError("Refusing to restore a database onto itself.")
    temporary = destination.with_name(f"{destination.name}.restoring")
    try:
        backup_sqlite(backup, temporary)
        for suffix in ("-wal", "-shm"):
            Path(f"{destination}{suffix}").unlink(missing_ok=True)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _unique_backup_path(source: Path, now: datetime | None) -> Path:
    moment = now or datetime.now(get_settings().zoneinfo)
    folder = source.parent / "backups"
    stamp = moment.strftime("%Y%m%d-%H%M%S")
    candidate = folder / f"meal-shopper-{stamp}.db"
    if not candidate.exists():
        return candidate
    for number in range(2, 100):
        numbered = folder / f"meal-shopper-{stamp}-{number}.db"
        if not numbered.exists():
            return numbered
    raise RuntimeError("Could not choose a backup filename.")


def _require_integrity(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if row is None or row[0] != "ok":
        path.unlink(missing_ok=True)
        raise RuntimeError("The backup failed its integrity check.")
