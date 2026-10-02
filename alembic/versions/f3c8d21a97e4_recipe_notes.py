"""a note is a row, and it can point at a step or an ingredient line

Revision ID: f3c8d21a97e4
Revises: d7a1c3e95b20
Create Date: 2026-10-01 21:10:00.000000

The Postgres mirror of migrations/060_recipe_notes.sql. Additive only: recipes.notes is untouched
and keeps being written as a derived copy until a later revision drops it.

⚠️ THE KIND IS A LOOKUP TABLE WITH A FOREIGN KEY, NOT AN ENUM AND NOT A CHECK. The SQLite side needs
it because adding a CHECK there is a table rebuild; this side matches it so the two schemas agree,
which is what tests/test_schema_parity.py compares. A Postgres ENUM would have been the idiomatic
choice here and would have diverged from SQLite on every reflection.

⚠️ THE SEED ROWS ARE PART OF THE SCHEMA, not data. Five rows mirroring static/note-kinds.json, which
the client and import_cleanup already share. A fresh Postgres database with no note_kinds rows
cannot store a note at all, so they belong in the migration rather than in a seeding step.
"""
import sqlalchemy as sa
from alembic import op

revision = "f3c8d21a97e4"
down_revision = "d7a1c3e95b20"
branch_labels = None
depends_on = None

KINDS = [
    ("notes", "Notes", 0),
    ("tips", "Tips", 1),
    ("storage", "Storage", 2),
    ("variations", "Variations", 3),
    ("serving", "Serving", 4),
]


def upgrade():
    op.create_table(
        "note_kinds",
        sa.Column("kind", sa.Text(), primary_key=True),
        sa.Column("header", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.bulk_insert(
        sa.table("note_kinds",
                 sa.column("kind", sa.Text), sa.column("header", sa.Text),
                 sa.column("position", sa.Integer)),
        [{"kind": k, "header": h, "position": p} for k, h, p in KINDS],
    )
    op.create_table(
        "recipe_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recipe_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'notes'")),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=True),
        sa.Column("ingredient_row_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kind"], ["note_kinds.kind"]),
        sa.ForeignKeyConstraint(["step_id"], ["recipe_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ingredient_row_id"], ["recipe_ingredients.id"],
                                ondelete="SET NULL"),
        sa.CheckConstraint("length(trim(text)) > 0"),
        sa.UniqueConstraint("recipe_id", "position"),
    )
    op.create_index("idx_recipe_notes_recipe", "recipe_notes", ["recipe_id", "position"])
    op.create_index("idx_recipe_notes_step", "recipe_notes", ["step_id"])
    op.create_index("idx_recipe_notes_ing", "recipe_notes", ["ingredient_row_id"])

    op.create_table(
        "recipe_note_step_refs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("ref_index", sa.Integer(), nullable=False),
        sa.Column("match_text", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["note_id"], ["recipe_notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["recipe_steps.id"], ondelete="SET NULL"),
        sa.CheckConstraint("ref_index >= 0"),
        sa.UniqueConstraint("note_id", "ref_index"),
    )
    op.create_index("idx_note_step_refs_note", "recipe_note_step_refs", ["note_id"])
    op.create_index("idx_note_step_refs_step", "recipe_note_step_refs", ["step_id"])


def downgrade():
    op.drop_table("recipe_note_step_refs")
    op.drop_table("recipe_notes")
    op.drop_table("note_kinds")
