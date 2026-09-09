"""linkage stage 1: recipe line -> built-catalog row (mirrors migrations/033)

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-08 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors migrations/033_recipe_line_catalog_link.sql. Read that file for the reasoning.
    # ⚠️ ingredient_id is NOT repurposed: it is an FK to ingredients(id), carries 50 live links, and
    #    shares an id space with the 30 [[key]]s in recipe prose. catalog_id is a separate, softer
    #    link to a catalog row that is documented to dangle.
    # ⚠️ catalog_id is NOT a foreign key, for migration 030's reason. A dangling catalog_id degrades
    #    a lookup and breaks no page; an FK would block a catalog rebuild or cascade recipe lines away.
    op.add_column('recipe_ingredients', sa.Column('catalog_id', sa.Text(), nullable=True))
    op.add_column('recipe_ingredients', sa.Column('link_confidence', sa.Text(), nullable=True))
    op.add_column('recipe_ingredients', sa.Column('link_rule', sa.Text(), nullable=True))
    op.add_column('recipe_ingredients', sa.Column('link_matched', sa.Text(), nullable=True))
    op.create_index('idx_ri_catalog', 'recipe_ingredients', ['catalog_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_ri_catalog', table_name='recipe_ingredients')
    op.drop_column('recipe_ingredients', 'link_matched')
    op.drop_column('recipe_ingredients', 'link_rule')
    op.drop_column('recipe_ingredients', 'link_confidence')
    op.drop_column('recipe_ingredients', 'catalog_id')
