"""the names a catalog row also answers to (mirrors migrations/040)

⚠️ ONE ROW, MANY NAMES. library_names ships exactly one canonical per row, so 4,060 English
names the sources give to catalog rows reach nothing. `turkey meat` (Q4200953) is in the catalog
and the word `turkey` does not reach it.

⚠️ NO UNIQUE ON alias, DELIBERATELY. Six names are already carried by two rows each and
linkage_matcher refuses them rather than picking. A UNIQUE would make the table unable to
describe a state the catalog already holds. The loader reports a newly ambiguous alias, the
matcher declines to pick, and both fail toward the miss.

Revision ID: d1e2f3a4b5c6
Revises: d0e1f2a3b4c5
Create Date: 2026-09-15 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c0d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "library_aliases",
        sa.Column("library_id", sa.Text(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("canonical_at_load", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("library_id", "alias"),
        sa.CheckConstraint("confidence IN ('authored','read','high','picked')",
                           name="ck_library_aliases_confidence"),
    )
    op.create_index("idx_la_alias", "library_aliases", ["alias"])


def downgrade() -> None:
    op.drop_index("idx_la_alias", table_name="library_aliases")
    op.drop_table("library_aliases")
