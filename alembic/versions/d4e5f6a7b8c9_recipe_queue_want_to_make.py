"""recipe_queue (want-to-make queue)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Hand-authored (mirrors friendships/shared_posts). Matches migrations/024_recipe_queue.sql: a per-user
    # join promoting the latent global "To Make" tag into per-user planning state. user_id -> users(id) no
    # ondelete; recipe_id (TEXT = recipes.id) -> recipes(id) ON DELETE CASCADE so a deleted recipe leaves no
    # orphan queue row; UNIQUE(user_id, recipe_id) so a recipe is queued once or not at all; surrogate PK.
    # Additive: the table is created empty here; the standalone backfill moves the 133 tags into it.
    op.create_table(
        'recipe_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('recipe_id', sa.Text(), nullable=False),
        sa.Column('added_at', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'recipe_id'),
        sqlite_autoincrement=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('recipe_queue')
