"""mined corpus, the denominator N per source (mirrors migrations/042)

⚠️ N has never been stored. pairing_run.py computes it, writes it to JSON as `recipes_read`, and
the loader drops it. One source hides the gap because N cancels out of every comparison. A second
source ends that, and code forced to guess N reaches for MAX(n_recipes) in mined_occurrences,
which is the salt row at 960,395. See migrations/042 for the full provenance and for why the
count column is named `n`.

The backfill is conditional in SQLite and conditional here too. A fresh Postgres database has no
corpus loaded, so it gets the table and no row.

Revision ID: a1b2c3d4e5f6
Revises: e3f4a5b6c7d8
Create Date: 2026-09-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mined_corpus",
        sa.Column("source_slug", sa.Text(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("mined_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("source_slug"),
    )
    op.execute(
        "INSERT INTO mined_corpus (source_slug, n, mined_at) "
        "SELECT 'recipenlg-2020', 2231142, NULL "
        "WHERE EXISTS (SELECT 1 FROM mined_pairings WHERE source_slug = 'recipenlg-2020') "
        "ON CONFLICT (source_slug) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("mined_corpus")
