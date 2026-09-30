"""a wait that happens at the same time as another

Revision ID: d16fa3c07b58
Revises: c58b1d9e4f73
Create Date: 2026-09-30 09:40:00.000000

Mirrors migrations/056_wait_alongside.sql.

⚠️ POSTGRES NEEDS NO REBUILD. A named CHECK can be dropped and re-added in place, where SQLite has to
recreate the table to change one. Same end state, two routes.

⚠️ IT POINTS AT A STEP, NEVER AT A WAIT. Waits are deleted and reinserted on every save, so a wait id
is not a thing that survives being referenced. The step it overlaps does.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d16fa3c07b58"
down_revision: Union[str, Sequence[str], None] = "c58b1d9e4f73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recipe_waits", sa.Column("alongside_step_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_recipe_waits_alongside_step_id", "recipe_waits", "recipe_steps",
                          ["alongside_step_id"], ["id"], ondelete="SET NULL")
    op.drop_constraint("ck_recipe_waits_when_kind", "recipe_waits", type_="check")
    op.create_check_constraint(
        "ck_recipe_waits_when_kind", "recipe_waits",
        "when_kind IN ('always','optional','only_if','alongside')")
    # ⚠️ NO "an alongside wait must name a step" CHECK. It contradicts ON DELETE SET NULL above and
    # would turn a step deletion into a CHECK violation. See migrations/056 for the whole argument.
    op.create_check_constraint(
        "ck_recipe_waits_alongside_not_self", "recipe_waits",
        "alongside_step_id IS NULL OR alongside_step_id <> step_id")


def downgrade() -> None:
    op.drop_constraint("ck_recipe_waits_alongside_not_self", "recipe_waits", type_="check")
    op.drop_constraint("ck_recipe_waits_when_kind", "recipe_waits", type_="check")
    op.create_check_constraint(
        "ck_recipe_waits_when_kind", "recipe_waits",
        "when_kind IN ('always','optional','only_if')")
    op.drop_constraint("fk_recipe_waits_alongside_step_id", "recipe_waits", type_="foreignkey")
    op.drop_column("recipe_waits", "alongside_step_id")
