"""the old wait step pointer goes

Revision ID: b4e07a51cd92
Revises: a7c1e93b240f
Create Date: 2026-09-30 00:30:00.000000

Mirrors migrations/054_drop_wait_step_pointer.sql.

⚠️ DESTRUCTIVE, AT THE CHEAPEST POSSIBLE MOMENT. Live holds 0 recipe_waits rows, so both columns are
empty everywhere. 053 added step_id and deliberately left these in place to stay additive.

⚠️ THE DOWNGRADE CANNOT RESTORE WHAT WAS IN THEM, and there was nothing in them. It re-creates the two
columns as nullable so the schema round-trips, which is the most an irreversible drop can offer.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b4e07a51cd92"
down_revision: Union[str, Sequence[str], None] = "a7c1e93b240f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("recipe_waits", "step_position")
    op.drop_column("recipe_waits", "step_check")


def downgrade() -> None:
    op.add_column("recipe_waits", sa.Column("step_check", sa.Text(), nullable=True))
    op.add_column("recipe_waits", sa.Column("step_position", sa.Integer(), nullable=True))
