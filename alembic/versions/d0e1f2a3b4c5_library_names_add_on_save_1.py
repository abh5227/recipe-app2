"""library_names, add-on-save ingredient linking stage 1

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-27 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors migrations/029_library_names.sql. Add-on-save stage 1: library_names maps a library row's
    # id to its canonical name, so a later save path can create an `ingredients` row without opening
    # join.db (894 MB) or sources.db (5.18 GB). Two columns on purpose, the slug column and its index
    # went with the dropped step-link promotion. Purely additive CREATE TABLE with no backfill.
    # ⚠️ ON POSTGRES THIS TABLE STAYS EMPTY, AND THAT IS INTENDED. The loader (stage 3) is part of
    #    build_db.py, which is raw-SQLite by design and is never run against PG (docs/migration-plan.md).
    #    An empty table means the later save gate's create branch never matches, so PG keeps today's
    #    behavior instead of half-enabling the feature. A dialect-neutral loader is a separate decision.
    op.create_table(
        'library_names',
        sa.Column('library_id', sa.Text(), primary_key=True),
        sa.Column('canonical', sa.Text(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('library_names')
