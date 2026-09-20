"""dish cuisine and course facets (mirrors migrations/043)

⚠️ Two facets RecipeNLG structurally cannot answer. A title says what a dish is, not where it is
from or when you eat it. Wikibooks states both as editor categories. See migrations/043 for the
granularity ruling (156 cuisines kept across five levels), the four duplicate merges, and why
`baking` is a course value while `baked` is a method value.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-17 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FACETS = [("mined_dish_cuisine", "cuisine"), ("mined_dish_course", "course")]


def upgrade() -> None:
    for table, col in FACETS:
        op.create_table(
            table,
            sa.Column("dish_id", sa.Text(), nullable=False),
            sa.Column(col, sa.Text(), nullable=False),
            sa.Column("n", sa.Integer(), nullable=False),
            sa.Column("source_slug", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("dish_id", col, "source_slug"),
        )
        op.create_index(f"idx_{table}_v", table, [col, sa.text("n DESC")])


def downgrade() -> None:
    for table, col in reversed(FACETS):
        op.drop_index(f"idx_{table}_v", table_name=table)
        op.drop_table(table)
