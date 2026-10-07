"""drop the retired recipes.notes column

The Postgres mirror of migrations/063_drop_recipes_notes.sql. Hand-written from the same intention,
and tests/test_schema_parity.py is what keeps the two agreeing.

⚠️ DESTRUCTIVE, SO THE CODE GOES OUT FIRST. The deploy that stops naming the column serves both
schemas; the one before it names `notes` on its Recipe model and fails every recipe page once this
has run.

⚠️ THE DOWNGRADE PUTS THE COLUMN BACK EMPTY, AND THAT IS THE HONEST SHAPE OF IT. The text it held
was a derived copy of recipe_notes, and the rows no longer carry the label prefixes that copy held,
so re-deriving it would invent something that was never stored. The rollback for real data is a
restore from the backup, not a downgrade.

Revision ID: a7c4e81b9d35
Revises: c5f1a73b2d80
"""
import sqlalchemy as sa
from alembic import op

revision = "a7c4e81b9d35"
down_revision = "c5f1a73b2d80"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("recipes", "notes")


def downgrade():
    op.add_column("recipes", sa.Column("notes", sa.Text, nullable=True))
