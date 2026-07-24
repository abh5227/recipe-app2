"""ratings composite pk (rescoping R3)

Revision ID: e6da68d80473
Revises: 8a16b2f3ad3d
Create Date: 2026-07-24 11:54:18.203939

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6da68d80473'
down_revision: Union[str, Sequence[str], None] = '8a16b2f3ad3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Hand-fixed from autogenerate: it detected the NOT NULL but NOT the PK change (Alembic doesn't
    # auto-detect PK changes). In-place composite-PK swap — same as scripts/backfill_rescoping.py's PG
    # branch: drop the sole PK, tighten user_id, add the composite PK. No copy, so rated_on is untouched.
    op.drop_constraint('ratings_pkey', 'ratings', type_='primary')
    op.alter_column('ratings', 'user_id', existing_type=sa.INTEGER(), nullable=False)
    op.create_primary_key('ratings_pkey', 'ratings', ['recipe_id', 'user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ratings_pkey', 'ratings', type_='primary')
    op.alter_column('ratings', 'user_id', existing_type=sa.INTEGER(), nullable=True)
    op.create_primary_key('ratings_pkey', 'ratings', ['recipe_id'])
