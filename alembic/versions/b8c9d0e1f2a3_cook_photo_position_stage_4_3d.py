"""cook_photos.position — stored album order (stage 4 build 3d-i)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors migrations/027_cook_photo_position.sql. Stage 4 build 3d-i: a STORED per-recipe album order
    # (Model B) — cook_photos.position. Plain ADD COLUMN (nullable) on both dialects — no table rebuild
    # (adding a column has none of the DROP-NOT-NULL limit that forced 026's SQLite rebuild). Existing rows
    # are seeded from today's cooked_on order by a standalone backfill (not here); new rows set position on
    # insert (append). A composite (recipe_id, position) index backs the album read.
    op.add_column('cook_photos', sa.Column('position', sa.Integer(), nullable=True))
    op.create_index('idx_cook_photos_recipe_position', 'cook_photos', ['recipe_id', 'position'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_cook_photos_recipe_position', table_name='cook_photos')
    op.drop_column('cook_photos', 'position')
