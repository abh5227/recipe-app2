"""plan-ahead waits and storage

Revision ID: c9f2e5b8a310
Revises: c9e1d4a7b205
Create Date: 2026-09-27 13:10:00.000000

Mirrors migrations/049_plan_ahead_waits.sql. Hand-authored: autogenerate emits no CHECK constraints
and there is no model to generate from yet.

⚠️ `where` IS RESERVED IN BOTH DIALECTS, so the storage column is `where_kept`.

⚠️ THE MINUTES ARE INTEGER AND NOTHING SHOULD EVER AVG THEM IN SQL. Postgres returns Decimal from
AVG over an integer column and SQLite returns float, which is the shape that bit the ratings work.
The total is a SUM computed in Python over the rows the page already has, so neither dialect's
numeric type reaches the client. SUM in SQL would be safe (bigint -> int); AVG would not.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9f2e5b8a310'
down_revision: Union[str, Sequence[str], None] = 'c9e1d4a7b205'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KINDS = ('marinating', 'chilling', 'rising', 'soaking', 'resting', 'freezing', 'brining', 'other')
WHERES = ('fridge', 'freezer', 'room temp', 'other')


def _in_list(col, values):
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'recipe_waits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipe_id', sa.Text(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('min_minutes', sa.Integer(), nullable=True),
        sa.Column('max_minutes', sa.Integer(), nullable=True),
        sa.Column('step_position', sa.Integer(), nullable=True),
        sa.Column('ext_label', sa.Text(), nullable=True),
        sa.Column('ext_min_minutes', sa.Integer(), nullable=True),
        sa.Column('ext_max_minutes', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('recipe_id', 'position', name='uq_recipe_waits_position'),
        sa.CheckConstraint(_in_list('kind', KINDS), name='ck_recipe_waits_kind'),
        sa.CheckConstraint('min_minutes IS NULL OR min_minutes >= 0', name='ck_recipe_waits_min'),
        sa.CheckConstraint('max_minutes IS NULL OR min_minutes IS NULL OR max_minutes >= min_minutes',
                           name='ck_recipe_waits_range'),
        sa.CheckConstraint('ext_max_minutes IS NULL OR ext_min_minutes IS NULL '
                           'OR ext_max_minutes >= ext_min_minutes', name='ck_recipe_waits_ext_range'),
        sa.CheckConstraint('ext_label IS NOT NULL OR (ext_min_minutes IS NULL '
                           'AND ext_max_minutes IS NULL)', name='ck_recipe_waits_ext_label'),
    )
    op.create_index('idx_recipe_waits_recipe', 'recipe_waits', ['recipe_id'])
    op.create_index('idx_recipe_waits_min', 'recipe_waits', ['min_minutes'])

    op.create_table(
        'recipe_storage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipe_id', sa.Text(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('where_kept', sa.Text(), nullable=False),
        sa.Column('applies_to', sa.Text(), nullable=True),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('min_minutes', sa.Integer(), nullable=True),
        sa.Column('max_minutes', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('recipe_id', 'position', name='uq_recipe_storage_position'),
        sa.CheckConstraint(_in_list('where_kept', WHERES), name='ck_recipe_storage_where'),
        sa.CheckConstraint('min_minutes IS NULL OR min_minutes >= 0', name='ck_recipe_storage_min'),
        sa.CheckConstraint('max_minutes IS NULL OR min_minutes IS NULL OR max_minutes >= min_minutes',
                           name='ck_recipe_storage_range'),
    )
    op.create_index('idx_recipe_storage_recipe', 'recipe_storage', ['recipe_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_recipe_storage_recipe', table_name='recipe_storage')
    op.drop_table('recipe_storage')
    op.drop_index('idx_recipe_waits_min', table_name='recipe_waits')
    op.drop_index('idx_recipe_waits_recipe', table_name='recipe_waits')
    op.drop_table('recipe_waits')
