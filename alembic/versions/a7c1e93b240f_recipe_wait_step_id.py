"""a wait points at a step row

Revision ID: a7c1e93b240f
Revises: f3d5c8e2a640
Create Date: 2026-09-29 23:50:00.000000

Mirrors migrations/053_recipe_wait_step_id.sql.

⚠️ step_position AND step_check ARE RETIRED, NOT DROPPED. 051's pointer was a position plus a snippet
of the step's text, because a save renumbered every step, so the snippet existed only to detect that
drift and drop the link rather than point at the wrong step. Option C gave every step row an id that
survives a save, so the row itself is the pointer and both halves go away. The columns stay so this
revision cannot lose anything.

⚠️ ON DELETE SET NULL, tested on both dialects before this was written: a deleted step nulls exactly
the waits that pointed at it. It is a backstop, because write_plan_ahead already refuses a step_id that
names no step of the recipe. Live holds 0 recipe_waits rows, so nothing is converted.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7c1e93b240f"
down_revision: Union[str, Sequence[str], None] = "f3d5c8e2a640"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recipe_waits", sa.Column("step_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_recipe_waits_step_id", "recipe_waits", "recipe_steps",
                          ["step_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_recipe_waits_step_id", "recipe_waits", type_="foreignkey")
    op.drop_column("recipe_waits", "step_id")
