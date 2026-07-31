"""cook_photos (per-cook album, stage 4 build 1)

Revision ID: f5a6b7c8d9e0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Hand-authored (mirrors shared_posts/comments/recipe_queue). Matches migrations/025_cook_photos.sql:
    # the per-cook photo album — one row per photo, several per cook, accumulating into a per-recipe album
    # beside the untouched hero. cook_log_id -> cook_log(id) ON DELETE CASCADE (undo-cook / recipe-delete
    # leaves no orphan photo); recipe_id (TEXT = recipes.id) -> recipes(id) ON DELETE CASCADE is the
    # DENORMALIZED per-recipe album key with its own cascade; user_id -> users(id) is a plain reference FK
    # (no ondelete, the interim multi-user-shaped rule); caption nullable; added_at = now_utc() text.
    # Additive: the table is created empty here (no backfill — a new table starts empty). Indexes back the
    # per-recipe album (recipe_id) and per-cook lookup (cook_log_id) query patterns.
    op.create_table(
        'cook_photos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cook_log_id', sa.Integer(), nullable=False),
        sa.Column('recipe_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('added_at', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['cook_log_id'], ['cook_log.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    op.create_index('idx_cook_photos_recipe', 'cook_photos', ['recipe_id'], unique=False)
    op.create_index('idx_cook_photos_cook_log', 'cook_photos', ['cook_log_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_cook_photos_cook_log', table_name='cook_photos')
    op.drop_index('idx_cook_photos_recipe', table_name='cook_photos')
    op.drop_table('cook_photos')
