"""cook_photos.cook_log_id nullable (standalone album photos, stage 4 build 2a)

Revision ID: a7b8c9d0e1f2
Revises: f5a6b7c8d9e0
Create Date: 2026-07-31 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors migrations/026_cook_photos_cook_log_nullable.sql. A cook photo may stand alone in the album
    # (no cook), so cook_log_id becomes nullable. Postgres does this in place — a trivial DROP NOT NULL —
    # so there's no table rebuild (that's the SQLite-only path in the .sql half). The FK + ON DELETE
    # CASCADE on cook_log_id is unaffected by the nullability change.
    op.alter_column('cook_photos', 'cook_log_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('cook_photos', 'cook_log_id', existing_type=sa.Integer(), nullable=False)
