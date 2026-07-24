"""drop change layer (rescoping R6)

Revision ID: 28128ca4f902
Revises: e6da68d80473
Create Date: 2026-07-24 15:00:24.090409

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28128ca4f902'
down_revision: Union[str, Sequence[str], None] = 'e6da68d80473'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Hand-fixed ORDER (autogenerate dropped people before recipe_additions, which FKs to it → PG would
    # block that): drop BOTH change tables (children of people) FIRST, then people. Matches migration 020.
    op.drop_index(op.f('idx_line_changes_recipe'), table_name='recipe_line_changes')
    op.drop_table('recipe_line_changes')
    op.drop_index(op.f('idx_additions_recipe'), table_name='recipe_additions')
    op.drop_table('recipe_additions')
    op.drop_table('people')


def downgrade() -> None:
    """Downgrade schema — hand-fixed ORDER: create people (the parent) FIRST, then the two change
    tables that FK to it (autogenerate created recipe_additions before people → FK to a missing table)."""
    op.create_table('people',
    sa.Column('id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('name', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('color', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('position', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('people_pkey'))
    )
    op.create_table('recipe_additions',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('recipe_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('person_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('qty', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('ingredient_id', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('label', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('note', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('raw_text', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('section', sa.TEXT(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], name=op.f('recipe_additions_ingredient_id_fkey')),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('recipe_additions_person_id_fkey'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], name=op.f('recipe_additions_recipe_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('recipe_additions_pkey'))
    )
    op.create_index(op.f('idx_additions_recipe'), 'recipe_additions', ['recipe_id'], unique=False)
    op.create_table('recipe_line_changes',
    sa.Column('recipe_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('person_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('position', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('kind', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('new_qty', sa.TEXT(), autoincrement=False, nullable=True),
    sa.CheckConstraint("kind = ANY (ARRAY['edit'::text, 'remove'::text])", name=op.f('recipe_line_changes_kind_check')),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('recipe_line_changes_person_id_fkey'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], name=op.f('recipe_line_changes_recipe_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('recipe_id', 'person_id', 'position', name=op.f('recipe_line_changes_pkey'))
    )
    op.create_index(op.f('idx_line_changes_recipe'), 'recipe_line_changes', ['recipe_id'], unique=False)
