"""wikipedia sourced content, a second layer beside the handwritten description (mirrors migrations/044)

⚠️ THE HANDWRITTEN TEXT IS NEVER WRITTEN HERE AND NEVER READ FROM HERE. ingredients.descr is the
handwritten layer. Precedence at render time is handwritten, then sourced, then blank.

⚠️ image_license IS THE GATE, NOT A NOTE. NULL means the file's rights were not read or are not
usable, and such a row MUST NOT render its image. Commons licences vary file by file.

⚠️ match_basis records how the article was reached so a wrong attachment stays findable. Nothing is
reached by walking P279: subclass edges put the Vegetable article on onion and the Fruit article on
tomato, which looks like a success and is not one. See migrations/044.

Revision ID: f2b3c4d5e6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-09-18 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2b3c4d5e6a7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "library_sourced_content",
        sa.Column("library_id", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_title", sa.Text()),
        sa.Column("source_url", sa.Text()),
        sa.Column("source_revision", sa.Integer()),
        sa.Column("match_basis", sa.Text(), nullable=False),
        sa.Column("sourced_description", sa.Text()),
        sa.Column("scientific_name", sa.Text()),
        sa.Column("license", sa.Text()),
        sa.Column("attribution", sa.Text()),
        sa.Column("sourced_image", sa.Text()),
        sa.Column("image_url", sa.Text()),
        sa.Column("image_license", sa.Text()),
        sa.Column("image_attribution", sa.Text()),
        sa.Column("fetched_at", sa.Text(), nullable=False),
        sa.CheckConstraint("match_basis IN ('sitelink','title','redirect')",
                           name="ck_lsc_match_basis"),
    )
    op.create_index("idx_lsc_basis", "library_sourced_content", ["match_basis"])


def downgrade() -> None:
    op.drop_index("idx_lsc_basis", table_name="library_sourced_content")
    op.drop_table("library_sourced_content")
