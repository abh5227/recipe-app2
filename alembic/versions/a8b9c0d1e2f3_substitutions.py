"""substitution candidates and confirmed facts (mirrors migrations/037)

⚠️ TWO TABLES THAT ARE NOT THE SAME KIND OF THING. mined_substitution_candidates is a review
queue the next mining run rebuilds whole. library_substitutions is replayed from
hand_substitutions.csv, which is in git, so it is a projection of that file rather than a place
anything is typed into. See migrations/037 for the full provenance.

⚠️ BOTH ARE GUARDED by name in tests/test_mining_boundaries.py, not by the mined_ prefix alone.
A corpus-derived table called library_something used to be invisible to that scan.

⚠️ COALESCE HERE, IFNULL IN THE SQLITE FILE, and the difference is the only one between them.
to_id is nullable because 143 matches read as one ingredient replaced by two, and a NULL is a
flagged gap rather than a missing value. Both dialects count every NULL in a unique key as
distinct, so a plain PRIMARY KEY (from_id, to_id, source_slug) would let the same one-to-many row
in twice. Folding the NULL to '' is what makes the key hold, and Postgres spells that COALESCE.

Revision ID: a8b9c0d1e2f3
Revises: e7f8a9b0c1d2
Create Date: 2026-09-11 20:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, Sequence[str], None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mined_substitution_candidates",
        sa.Column("from_id", sa.Text(), nullable=False),
        sa.Column("to_id", sa.Text(), nullable=True),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("n_reverse", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("one_to_many", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("source_slug", sa.Text(), nullable=False),
    )
    op.create_index("idx_msc_key", "mined_substitution_candidates",
                    ["from_id", sa.text("COALESCE(to_id, '')"), "source_slug"], unique=True)
    op.create_index("idx_msc_n", "mined_substitution_candidates", [sa.text("n DESC")])
    op.create_index("idx_msc_from", "mined_substitution_candidates",
                    ["from_id", sa.text("n DESC")])

    op.create_table(
        "library_substitutions",
        sa.Column("from_id", sa.Text(), nullable=False),
        sa.Column("to_id", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("ratio", sa.Float(), nullable=True),
        sa.Column("n", sa.Integer(), nullable=True),
        sa.Column("source_slug", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("from_id", "to_id"),
    )
    op.create_index("idx_lsub_from", "library_substitutions", ["from_id"])
    op.create_index("idx_lsub_to", "library_substitutions", ["to_id"])


def downgrade() -> None:
    for i in ("idx_lsub_to", "idx_lsub_from"):
        op.drop_index(i, table_name="library_substitutions")
    op.drop_table("library_substitutions")
    for i in ("idx_msc_from", "idx_msc_n", "idx_msc_key"):
        op.drop_index(i, table_name="mined_substitution_candidates")
    op.drop_table("mined_substitution_candidates")
