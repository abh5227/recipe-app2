"""a heading row keeps its own title

Revision ID: f3d5c8e2a640
Revises: e2b4a7d1c530
Create Date: 2026-09-28 09:40:00.000000

Mirrors migrations/052_ingredient_heading_text.sql.

⚠️ THREE STRINGS, AND THERE WERE ONLY TWO COLUMNS. A heading row has a TITLE. A line has a NAME
(label) and a SOURCE LINE (raw_text). Converting a line to a heading wrote the title over raw_text
and NULLed the rest, so the save destroyed the amount, the weight, the note and the four linkage
columns. Measured on live, 2,912 of 3,349 lines (87%) carry a raw_text richer than their label, so
the title cannot share raw_text and leave the round trip lossless.

⚠️ NULLABLE, AND NULL ON ALL 223 EXISTING HEADING ROWS. Every reader resolves the title as
`heading` when set, else raw_text, which is the fallback the client's headingText() already used,
so those rows and the 300 reason='original' baselines are untouched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f3d5c8e2a640"
down_revision: Union[str, Sequence[str], None] = "e2b4a7d1c530"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recipe_ingredients", sa.Column("heading", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("recipe_ingredients", "heading")
