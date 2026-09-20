"""an alias may be scoped to one source (mirrors migrations/047)

⚠️ WHY. 'corn flour' means cornstarch to an Indian recipe writer and cornmeal to an American one.
Both rows exist and the name reaches neither today. An unscoped alias would have to pick one and
be wrong for the other source, which is the resolved-but-wrong failure the matcher exists to avoid.

⚠️ NULL MEANS EVERY SOURCE. All 183 existing rows are unscoped and most rows should stay that way.
A scope is written only when two sources genuinely disagree about what a name means.

⚠️ THE PRIMARY KEY IS UNCHANGED. load_aliases.py holds the constraint that no alias resolves to
two rows within one source's effective set, for the reason migration 030 gave for leaving
UNIQUE(alias) off the table.

Revision ID: a1c7e4b92f30
Revises: bbbd3536038a
Create Date: 2026-09-20 17:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c7e4b92f30'
down_revision: Union[str, Sequence[str], None] = 'bbbd3536038a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("library_aliases", sa.Column("source_slug", sa.Text(), nullable=True))
    op.create_index("idx_library_aliases_slug", "library_aliases", ["source_slug"])


def downgrade() -> None:
    # ⚠️ A scoped alias becomes an unscoped one, which is a WIDENING. Dropping the column cannot
    #    preserve the scope, so the rows that carry one are deleted rather than silently applied
    #    to every source.
    op.execute("DELETE FROM library_aliases WHERE source_slug IS NOT NULL")
    op.drop_index("idx_library_aliases_slug", table_name="library_aliases")
    op.drop_column("library_aliases", "source_slug")
