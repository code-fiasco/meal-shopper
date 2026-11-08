"""Backup, restore, and optional demo data.

Run inside the container, for example:

    python -m app.cli backup
    python -m app.cli restore /data/backups/meal-shopper-20261108-180000.db
    python -m app.cli seed
"""

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal
from app.services.backup import restore_database, sqlite_path, write_timestamped_backup
from app.services.seed import seed_demo


def main(argv: list[str] | None = None) -> int:
    """Run one maintenance command. Returns a process status code."""
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="Write a timestamped copy into the data volume")
    restore = commands.add_parser("restore", help="Replace the live database")
    restore.add_argument("backup", help="Path to a backup created by this app")
    commands.add_parser("seed", help="Add sample ingredients, meals, and a week plan")
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            path = write_timestamped_backup(get_settings().database_url)
            print(path)
        elif args.command == "restore":
            destination = sqlite_path(get_settings().database_url)
            restore_database(Path(args.backup), destination)
            print(f"Restored {args.backup} onto {destination}")
        else:
            _seed()
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def _seed() -> None:
    session = SessionLocal()
    try:
        result = seed_demo(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    if result.created:
        print("Created demo ingredients, meals, and a week plan.")
    else:
        print("Demo data is already present.")


if __name__ == "__main__":
    raise SystemExit(main())
