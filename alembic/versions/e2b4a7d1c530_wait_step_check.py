"""a step pointer that refuses to point at the wrong step

Revision ID: e2b4a7d1c530
Revises: d1a3f6c9b420
Create Date: 2026-09-27 17:05:00.000000

Mirrors migrations/051_wait_step_check.sql.

⚠️ step_position ALONE IS A STALE POINTER WAITING TO HAPPEN. Insert a step above a linked one and
every position below it shifts. The snippet stored here is checked against the step at that
position at read time, and a wait whose check fails shows with NO step number rather than linking
to the wrong step.

⚠️ NULLABLE ON PURPOSE. A wait read from no particular step, or typed by hand with no step chosen,
carries neither a position nor a check and simply has no link.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b4a7d1c530'
down_revision: Union[str, Sequence[str], None] = 'd1a3f6c9b420'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('recipe_waits', sa.Column('step_check', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('recipe_waits', 'step_check')
