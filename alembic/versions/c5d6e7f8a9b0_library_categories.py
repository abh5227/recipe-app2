"""category vocabulary + relation edges (mirrors migrations/034)

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-09-09 13:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors migrations/034_library_categories.sql. Read that file for the reasoning.
    # ⚠️ library_categories holds ONLY the filter vocabulary, terms that are not catalog rows. A
    #    kind_of parent IS a catalog row and needs no entry here, so there is no is_filter column.
    # ⚠️ parent_id is NOT a foreign key, per migration 030. It holds either a library_id or a
    #    category_id, and library ids are not durable across a rebuild.
    op.create_table(
        'library_categories',
        sa.Column('category_id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('parent_slug', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
    )
    op.create_table(
        'library_relations',
        sa.Column('child_id', sa.Text(), nullable=False),
        sa.Column('parent_id', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('child_canonical', sa.Text(), nullable=True),
        sa.Column('parent_canonical', sa.Text(), nullable=True),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('child_id', 'parent_id', 'kind'),
        sa.CheckConstraint("kind IN ('kind_of','in_category','made_from')", name='ck_lr_kind'),
    )
    op.create_index('idx_lr_parent', 'library_relations', ['parent_id', 'kind'])
    op.create_index('idx_lr_child', 'library_relations', ['child_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_lr_child', table_name='library_relations')
    op.drop_index('idx_lr_parent', table_name='library_relations')
    op.drop_table('library_relations')
    op.drop_table('library_categories')
