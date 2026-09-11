"""mined pairings, co-occurrence and lift (mirrors migrations/036)

⚠️ The name must start with mined_, because both boundary tests scan sqlite_master for
'mined_%'. A library_pairings table is invisible to them. See migrations/036 for the full
provenance: cap k<=25, 158 non-food records excluded at the recipe level, lift stored because
the corpus is frozen, and the order-not-cut rule.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-09-11 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mined_pairings",
        sa.Column("a_id", sa.Text(), nullable=False),
        sa.Column("b_id", sa.Text(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("n_a", sa.Integer(), nullable=False),
        sa.Column("n_b", sa.Integer(), nullable=False),
        sa.Column("lift", sa.Float(), nullable=False),
        sa.Column("source_slug", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("a_id", "b_id", "source_slug"),
    )
    op.create_index("idx_mined_pairings_a", "mined_pairings", ["a_id", sa.text("lift DESC")])
    op.create_index("idx_mined_pairings_b", "mined_pairings", ["b_id", sa.text("lift DESC")])
    op.create_index("idx_mined_pairings_n", "mined_pairings", [sa.text("n DESC")])


def downgrade() -> None:
    for i in ("idx_mined_pairings_n", "idx_mined_pairings_b", "idx_mined_pairings_a"):
        op.drop_index(i, table_name="mined_pairings")
    op.drop_table("mined_pairings")
