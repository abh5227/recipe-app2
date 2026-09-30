"""a step heading is a section or a subheading

Revision ID: a4d2f8c16b57
Revises: f38c5a2be914
Create Date: 2026-09-30 15:05:00.000000

Mirrors migrations/059_step_heading_level.sql. Level 1 is a section heading (larger, ruled, opens a
group) and level 2 a subheading (smaller, tight to its step). NOT NULL DEFAULT 1 so every existing
row is already correct, matching is_heading on the same table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a4d2f8c16b57"
down_revision: Union[str, Sequence[str], None] = "f38c5a2be914"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recipe_steps", sa.Column("heading_level", sa.Integer(), nullable=False,
                                            server_default=sa.text("1")))


def downgrade() -> None:
    op.drop_column("recipe_steps", "heading_level")
