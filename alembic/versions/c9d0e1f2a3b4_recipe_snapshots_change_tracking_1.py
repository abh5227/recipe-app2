"""recipe_snapshots — change-tracking stage 1 (capture-on-cook)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-04 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors migrations/028_recipe_snapshots.sql. Change-tracking stage 1: recipe_snapshots — a versioned
    # JSON-blob snapshot of a recipe's editable content, captured on cook (reason='cook'; manual is stage 2).
    # Purely additive CREATE TABLE, no backfill (retroactive snapshots are impossible -> tracking starts
    # fresh). cook_log_id ON DELETE CASCADE (undo a cook -> its snapshot goes); recipe_id ON DELETE CASCADE.
    op.create_table(
        'recipe_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('recipe_id', sa.Text(), sa.ForeignKey('recipes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('cook_log_id', sa.Integer(), sa.ForeignKey('cook_log.id', ondelete='CASCADE'), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_index('idx_recipe_snapshots_recipe', 'recipe_snapshots', ['recipe_id', 'created_at'])
    op.create_index('idx_recipe_snapshots_cook_log', 'recipe_snapshots', ['cook_log_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_recipe_snapshots_cook_log', table_name='recipe_snapshots')
    op.drop_index('idx_recipe_snapshots_recipe', table_name='recipe_snapshots')
    op.drop_table('recipe_snapshots')
