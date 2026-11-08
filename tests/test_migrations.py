"""Alembic uses the application metadata and DATABASE_URL."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_upgrade_head_creates_version_table(database_url: str) -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")

    check = create_engine(database_url)
    with check.connect() as connection:
        version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    check.dispose()
    assert version == "0002_catalog"


def test_entrypoint_uses_lf_line_endings() -> None:
    script = Path("docker/entrypoint.sh").read_bytes()
    assert b"\r" not in script
    assert script.startswith(b"#!/bin/sh\n")
