"""ingredient identity, the Panel stage 1 (Option D row-key / concept-key split)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-28 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors migrations/031_ingredient_identity.sql. The Panel stage 1: ingredients.id was doing two
    # jobs, saying which row this is and which concept it is, and the model needs those to differ. id
    # stays the row key, so the 50 stored links and the 30 [[key]]s in recipe prose keep resolving.
    # ⚠️ concept's server_default of '' is a SQLite necessity carried here for schema parity, not a
    #    design choice. The UPDATE below overwrites it and a test asserts no row ever holds ''.
    # ⚠️ TWO INDEXES, AND ONE ALONE IS NOT ENOUGH. Both dialects treat NULLs as distinct in a unique
    #    index, so UNIQUE(owner, concept) by itself permits two shared rows for one concept. The
    #    partial index is what makes one-shared-per-concept true.
    op.add_column('ingredients',
                  sa.Column('concept', sa.Text(), server_default=sa.text("''"), nullable=False))
    op.add_column('ingredients',
                  sa.Column('owner', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.execute("UPDATE ingredients SET concept = id WHERE concept = ''")
    op.create_index('idx_ingredients_owner_concept', 'ingredients', ['owner', 'concept'], unique=True)
    op.create_index('idx_ingredients_shared_concept', 'ingredients', ['concept'], unique=True,
                    postgresql_where=sa.text('owner IS NULL'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_ingredients_shared_concept', table_name='ingredients')
    op.drop_index('idx_ingredients_owner_concept', table_name='ingredients')
    op.drop_column('ingredients', 'owner')
    op.drop_column('ingredients', 'concept')
