"""the dish x ingredient profile (mirrors migrations/039)

⚠️ EVERY COLUMN IS A HASH, A CATALOG ID OR AN INTEGER. No corpus text, no vocabulary, no
exception. The boundary check passes it without a new allowed column.

⚠️ THE FLOOR IS THE BOUNDARY, AND IT LIVES IN THE LOADER. A dish x ingredient cell is a thin cell
by construction, which is the case docs/mining-decision.md section 2 singles out. Only rows
supported by at least 10 recipes are loaded. Measured: without a floor the table grows linearly,
beta 0.985, projecting 9.1 million cells against mined_pairings' 362,319 at beta 0.39.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-09-14 18:06:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c0d1e2f3a4b5'
down_revision: Union[str, Sequence[str], None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mined_dish_ingredient",
        sa.Column("dish_id", sa.Text(), nullable=False),
        sa.Column("library_id", sa.Text(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("n_dish", sa.Integer(), nullable=False),   # the frozen denominator
        sa.Column("source_slug", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("dish_id", "library_id", "source_slug"),
    )
    op.create_index("idx_mdi_dish", "mined_dish_ingredient", ["dish_id", sa.text("n DESC")])
    op.create_index("idx_mdi_ing", "mined_dish_ingredient", ["library_id", sa.text("n DESC")])


def downgrade() -> None:
    op.drop_index("idx_mdi_ing", table_name="mined_dish_ingredient")
    op.drop_index("idx_mdi_dish", table_name="mined_dish_ingredient")
    op.drop_table("mined_dish_ingredient")
