"""does a recipe's total already cover its plan-ahead waits

Revision ID: f38c5a2be914
Revises: e27b4f91a3c5
Create Date: 2026-09-30 13:55:00.000000

Mirrors migrations/058_recipe_total_includes_waits.sql. Three states on one nullable column: NULL is
"use the rule", 1 is "the total already covers the waits", 0 is "add them and say so".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f38c5a2be914"
down_revision: Union[str, Sequence[str], None] = "e27b4f91a3c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("total_includes_waits", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("recipes", "total_includes_waits")
