"""ingredient provenance, add-on-save ingredient linking stage 2

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-27 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors migrations/030_ingredient_provenance.sql. Add-on-save stage 2: tell a promoted ingredient
    # row apart from a hand-authored seed one, which stage 6's delete path needs (source) and a
    # re-audit needs (library_id). source mirrors recipes.source exactly, same vocabulary and the same
    # Text NOT NULL server_default 'seed' the baseline revision gives recipes.
    # ⚠️ THE 'seed' DEFAULT IS LOAD-BEARING. Postgres backfills existing rows with it on ADD COLUMN, so
    #    the hand-authored rows read as seed-tier and stage 6 refuses to delete them. Defaulting to
    #    'app' would mark the whole curated library as promoted, and therefore deletable.
    # ⚠️ NO FOREIGN KEY ON library_id, ON PURPOSE. Library ids are not durable across a rebuild (7 died
    #    in commit 460cae5), and an FK would either block the rebuild or cascade the promoted row away.
    #    The column is audit provenance and is expected to dangle. Nothing on a page reads it.
    op.add_column('ingredients',
                  sa.Column('source', sa.Text(), server_default=sa.text("'seed'"), nullable=False))
    op.add_column('ingredients', sa.Column('library_id', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ingredients', 'library_id')
    op.drop_column('ingredients', 'source')
