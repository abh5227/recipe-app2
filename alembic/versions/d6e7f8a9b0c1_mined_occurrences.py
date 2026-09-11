"""mined occurrences, the first mined table (mirrors migrations/035)

⚠️ EMPTY IS THE NORMAL STATE. These rows are derived from RecipeNLG, which is gitignored and
carries a license that forbids redistribution, so nothing replays them from the repo. A clone
regenerates them only by obtaining the corpus and re-running occurrence_run.py. The durable
record is the reducer plus source_slug. See docs/mining-decision.md and migrations/035.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-11 01:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mined_occurrences",
        sa.Column("library_id", sa.Text(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("n_recipes", sa.Integer(), nullable=False),
        sa.Column("source_slug", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("library_id", "source_slug"),
    )
    op.create_index("idx_mined_occurrences_n", "mined_occurrences", [sa.text("n DESC")])


def downgrade() -> None:
    op.drop_index("idx_mined_occurrences_n", table_name="mined_occurrences")
    op.drop_table("mined_occurrences")
