"""Online backup and restore of the SQLite file."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.db as database
from app.config import get_settings
from app.db import dispose_engine, init_engine
from app.services.backup import backup_sqlite, restore_database, sqlite_path
from app.services.shops import create_shop


def test_backup_and_restore_round_trip(database_url: str, tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    session = database.SessionLocal()
    shop = create_shop(session, name="Corner shop")
    session.commit()
    shop_id = shop.id
    session.close()

    source = sqlite_path(database_url)
    backup = tmp_path / "copy.db"
    backup_sqlite(source, backup)
    copied = sqlite3.connect(backup)
    try:
        name = copied.execute(
            "SELECT name FROM shops WHERE id = ?", (shop_id,)
        ).fetchone()
    finally:
        copied.close()
    assert name == ("Corner shop",)

    dispose_engine()
    raw = sqlite3.connect(source)
    raw.execute("DELETE FROM shops")
    raw.commit()
    raw.close()
    restore_database(backup, source)

    init_engine(database_url)
    restored = sqlite3.connect(source)
    try:
        again = restored.execute(
            "SELECT name FROM shops WHERE id = ?", (shop_id,)
        ).fetchone()
    finally:
        restored.close()
    assert again == ("Corner shop",)


def test_download_uses_a_sqlite_backup(
    client: TestClient, session: Session, tmp_path: Path
) -> None:
    create_shop(session, name="Market")
    session.commit()
    page = client.get("/settings")
    assert page.status_code == 200
    assert "<h1>Settings</h1>" in page.text
    assert "Download backup" in page.text
    assert 'href="/settings/backup"' in page.text
    downloaded = client.get("/settings/backup")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"SQLite format 3")
    assert "meal-shopper-" in downloaded.headers["content-disposition"]
    saved = tmp_path / "downloaded.db"
    saved.write_bytes(downloaded.content)
    check = sqlite3.connect(saved)
    try:
        row = check.execute("SELECT name FROM shops WHERE name = 'Market'").fetchone()
        integrity = check.execute("PRAGMA integrity_check").fetchone()
    finally:
        check.close()
    assert row == ("Market",)
    assert integrity == ("ok",)
    kept = sqlite_path(get_settings().database_url).parent / "backups"
    assert list(kept.glob("meal-shopper-*.db"))
