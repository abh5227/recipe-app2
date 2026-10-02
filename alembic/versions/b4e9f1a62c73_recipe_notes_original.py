"""recipe_notes_original — the author's original notes, kept as a record and compared by nothing

The Postgres mirror of migrations/061_recipe_notes_original.sql. Hand-written from the same
intention, and tests/test_schema_parity.py is what keeps the two agreeing.

⚠️ NOTES TAKE NO PART IN "YOUR CHANGES" FROM HERE ON. Andy's ruling: a note is a playground, so it
mints no annotation entry and editing one cannot cost a recipe its place in the byte-equal set. The
notes therefore leave recipe_snapshots.content, and this table is where the author's words are kept
instead, so a future restore is still possible.

Revision ID: b4e9f1a62c73
Revises: f3c8d21a97e4
"""
import sqlalchemy as sa
from alembic import op

revision = "b4e9f1a62c73"
down_revision = "f3c8d21a97e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recipe_notes_original",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("recipe_id", sa.Text, sa.ForeignKey("recipes.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("kind", sa.Text, sa.ForeignKey("note_kinds.kind"), nullable=False,
                  server_default="notes"),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("recorded_at", sa.Text, nullable=False),
        sa.CheckConstraint("length(trim(text)) > 0", name="recipe_notes_original_text_check"),
        sa.UniqueConstraint("recipe_id", "position", name="recipe_notes_original_recipe_position"),
    )
    op.create_index("idx_recipe_notes_original_recipe", "recipe_notes_original", ["recipe_id"])


def downgrade():
    op.drop_index("idx_recipe_notes_original_recipe", table_name="recipe_notes_original")
    op.drop_table("recipe_notes_original")
