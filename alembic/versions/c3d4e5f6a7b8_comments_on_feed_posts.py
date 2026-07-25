"""comments on feed posts

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-25 14:52:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors migrations/023_comments.sql. post_id -> shared_posts ON DELETE CASCADE is the integrity
    # chain (recipe/cook -> shared_post -> comments); author_id -> users is a plain reference FK. Plain
    # table (no CHECK / composite PK), so this is what autogenerate would emit — kept hand-authored +
    # verified (alembic check clean) so the cascade + index are guaranteed present, like the other revisions.
    op.create_table(
        'comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('post_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['shared_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    op.create_index('idx_comments_post', 'comments', ['post_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_comments_post', table_name='comments')
    op.drop_table('comments')
