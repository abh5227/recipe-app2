"""shared_posts (social sub-stage 2a)

Revision ID: b2c3d4e5f6a7
Revises: a1f2c3d4e5b6
Create Date: 2026-07-24 22:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1f2c3d4e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Hand-authored (autogenerate won't emit the XOR CHECK — same reason friendships/ratings were hand-
    # fixed). Mirrors migrations/022_shared_posts.sql: separate nullable FK columns with ON DELETE CASCADE
    # (so a deleted cook/recipe cascades the post — no orphans), the exactly-one XOR CHECK, surrogate PK.
    op.create_table(
        'shared_posts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('cook_log_id', sa.Integer(), nullable=True),
        sa.Column('recipe_id', sa.Text(), nullable=True),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['cook_log_id'], ['cook_log.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('(cook_log_id IS NOT NULL) <> (recipe_id IS NOT NULL)'),
        sqlite_autoincrement=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('shared_posts')
