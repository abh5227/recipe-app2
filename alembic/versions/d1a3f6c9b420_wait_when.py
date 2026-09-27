"""a wait can be conditional, and only an unconditional one counts

Revision ID: d1a3f6c9b420
Revises: c9f2e5b8a310
Create Date: 2026-09-27 15:45:00.000000

Mirrors migrations/050_wait_when.sql. Hand-authored, like c9f2e5b8a310, because autogenerate emits
no CHECK constraints.

⚠️ ADDITIVE. c9f2e5b8a310 is already applied to the live SQLite file, so this adds columns rather
than restating the table.

⚠️ `when` IS RESERVED IN BOTH DIALECTS, exactly like `where` in the previous revision. The columns
are when_kind and when_label.

⚠️ server_default='always' is what makes this safe on a table that already holds rows. Every wait
written before this revision was read from a recipe that states it flatly, so 'always' is not a
placeholder, it is the correct value for all of them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1a3f6c9b420'
down_revision: Union[str, Sequence[str], None] = 'c9f2e5b8a310'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WHENS = ('always', 'optional', 'only_if')


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('recipe_waits',
                  sa.Column('when_kind', sa.Text(), nullable=False, server_default='always'))
    op.add_column('recipe_waits', sa.Column('when_label', sa.Text(), nullable=True))
    op.create_check_constraint(
        'ck_recipe_waits_when_kind', 'recipe_waits',
        "when_kind IN (" + ", ".join(f"'{w}'" for w in WHENS) + ")")
    # only_if is the one kind that needs words after it. The other two read on their own.
    op.create_check_constraint(
        'ck_recipe_waits_when_label', 'recipe_waits',
        "when_kind <> 'only_if' OR when_label IS NOT NULL")
    op.create_index('idx_recipe_waits_when', 'recipe_waits', ['when_kind'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_recipe_waits_when', table_name='recipe_waits')
    op.drop_constraint('ck_recipe_waits_when_label', 'recipe_waits', type_='check')
    op.drop_constraint('ck_recipe_waits_when_kind', 'recipe_waits', type_='check')
    op.drop_column('recipe_waits', 'when_label')
    op.drop_column('recipe_waits', 'when_kind')
