"""Empty baseline schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-08

"""

from collections.abc import Sequence

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Baseline revision. Domain tables arrive in later migrations."""


def downgrade() -> None:
    """Baseline revision has nothing to remove."""
