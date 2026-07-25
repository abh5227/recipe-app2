"""friendships (social sub-stage 1)

Revision ID: a1f2c3d4e5b6
Revises: 28128ca4f902
Create Date: 2026-07-24 21:48:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f2c3d4e5b6'
down_revision: Union[str, Sequence[str], None] = '28128ca4f902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Hand-authored (autogenerate emits neither the composite PK nor CHECK constraints reliably — same
    # reason e6da68d80473 was hand-fixed). Mirrors migrations/021_friendships.sql: one row per friendship
    # (requester -> addressee), composite PK, text-IN status CHECK, self-friend CHECK, reference FKs ->
    # users(id) with no ondelete. Purely additive; nothing reads it yet.
    op.create_table(
        'friendships',
        sa.Column('requester_id', sa.Integer(), nullable=False),
        sa.Column('addressee_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('accepted_at', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['requester_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['addressee_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('requester_id', 'addressee_id'),
        sa.CheckConstraint("status IN ('pending','accepted')"),
        sa.CheckConstraint('requester_id <> addressee_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('friendships')
