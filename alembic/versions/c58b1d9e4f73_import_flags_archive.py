"""somewhere a confirmed import flag can go

Revision ID: c58b1d9e4f73
Revises: b4e07a51cd92
Create Date: 2026-09-30 01:10:00.000000

Mirrors migrations/055_import_flags_archive.sql.

⚠️ ADDITIVE, AND IT MOVES NOTHING. scripts/archive_import_flags.py does the move.

⚠️ NO FOREIGN KEY ON recipe_id, deliberately. import_flags cascades from recipes, so deleting a recipe
takes its flags with it, and an archive that did the same would lose the history it exists to hold.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c58b1d9e4f73"
down_revision: Union[str, Sequence[str], None] = "b4e07a51cd92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_flags_archive",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("recipe_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("flag", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.Text(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_import_flags_archive_recipe", "import_flags_archive", ["recipe_id"])


def downgrade() -> None:
    op.drop_index("idx_import_flags_archive_recipe", table_name="import_flags_archive")
    op.drop_table("import_flags_archive")
