"""a wait's alternative points at the step that describes it

Revision ID: e27b4f91a3c5
Revises: d16fa3c07b58
Create Date: 2026-09-30 13:10:00.000000

Mirrors migrations/057_wait_ext_step.sql.

⚠️ NO CHECK HERE EITHER, and Postgres could have one cheaply. Keeping the two dialects saying the
same thing matters more than the one constraint Postgres could afford and SQLite could not.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e27b4f91a3c5"
down_revision: Union[str, Sequence[str], None] = "d16fa3c07b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recipe_waits", sa.Column("ext_step_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_recipe_waits_ext_step_id", "recipe_waits", "recipe_steps",
                          ["ext_step_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_recipe_waits_ext_step_id", "recipe_waits", type_="foreignkey")
    op.drop_column("recipe_waits", "ext_step_id")
