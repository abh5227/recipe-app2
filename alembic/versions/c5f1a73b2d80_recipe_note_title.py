"""recipe_notes.title — an optional title on a note

The Postgres mirror of migrations/062_recipe_note_title.sql. Hand-written from the same intention,
and tests/test_schema_parity.py is what keeps the two agreeing.

⚠️ NULLABLE, AND NULL IS NOT ''. NULL means the note has no title, which is 148 of the 176 notes
the corpus carries once this round has run. An empty string would be a title the editor had
cleared, so the CHECK refuses it and the two states cannot both mean "none". A cleared Title box
writes NULL.

⚠️ NO BASELINE CHANGE FROM THIS COLUMN. A note is a playground (Andy's ruling): the rows and the
derived column are both outside recipe_snapshots.content and snapshot_diff does not compare notes,
so a title set on 28 notes over 18 recipes mints no annotation entry and costs none of them its
place in the byte-equal set. The round's two ingredient-heading strips are a different matter, and
migrations/062_recipe_note_title.sql says why.

Revision ID: c5f1a73b2d80
Revises: b4e9f1a62c73
"""
import sqlalchemy as sa
from alembic import op

revision = "c5f1a73b2d80"
down_revision = "b4e9f1a62c73"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("recipe_notes", sa.Column("title", sa.Text, nullable=True))
    # Named, because Postgres names an unnamed CHECK itself and SQLite's is anonymous. The parity
    # test compares CHECKs by their normalized expression rather than by name, so the name is for
    # the person reading \d recipe_notes, not for the comparison.
    op.create_check_constraint(
        "ck_recipe_notes_title_not_blank", "recipe_notes",
        "title IS NULL OR length(trim(title)) > 0")


def downgrade():
    op.drop_constraint("ck_recipe_notes_title_not_blank", "recipe_notes", type_="check")
    op.drop_column("recipe_notes", "title")
