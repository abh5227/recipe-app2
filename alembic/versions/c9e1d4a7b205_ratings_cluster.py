"""a rating is a cooking's verdict (mirrors migrations/048)

⚠️ THE MODEL. Each logged cook carries its own rating. The recipe's headline number is the AVERAGE of
its rated cooks. INPUT is per-cook; DISPLAY is the average, read-only, everywhere. The old ratings
table was keyed (recipe_id, user_id), so rating a fourth cook overwrote the verdict on the first three.

⚠️ THE ratings TABLE IS LEFT FROZEN, NOT DROPPED. Nothing reads or writes it after this revision, so
it cannot drift, and it is the rollback for the data backfill. A later revision drops it.

⚠️ THE HALF-STEP CHECK IS AN EXPLICIT IN-LIST. The arithmetic form (rating * 2 = CAST(rating * 2 AS
INT)) relies on rounding behavior that differs between SQLite and Postgres. Numeric(2, 1) holds every
half value exactly, so equality against a literal list is safe and says what it means.

⚠️ rated_at IS SEPARATE FROM cooked_on. The verdict's timestamp is not the cook's date.

Revision ID: c9e1d4a7b205
Revises: a1c7e4b92f30
Create Date: 2026-09-24 09:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9e1d4a7b205'
down_revision: Union[str, Sequence[str], None] = 'a1c7e4b92f30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HALF_STEPS = "(0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5)"


def upgrade() -> None:
    # Numeric(2, 1) rather than a float type: the half steps are exact and the stored value never
    # needs more than one decimal place. The average is computed in the query, never stored.
    op.add_column("cook_log", sa.Column("rating", sa.Numeric(2, 1), nullable=True))
    op.add_column("cook_log", sa.Column("rated_at", sa.Text(), nullable=True))
    op.add_column("cook_log", sa.Column("caption", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_cook_log_rating_half_steps", "cook_log",
        f"rating IS NULL OR rating IN {_HALF_STEPS}",
    )
    op.create_check_constraint(
        "ck_cook_log_caption_len", "cook_log",
        "caption IS NULL OR LENGTH(caption) <= 60",
    )
    # Partial index: both headline-average call sites filter rating IS NOT NULL, so this backs exactly
    # the rows they read. idx_cook_log_recipe already covers the unfiltered scans.
    op.create_index("idx_cook_log_rating", "cook_log", ["recipe_id", "user_id"],
                    postgresql_where=sa.text("rating IS NOT NULL"))

    # A dated observation of what ONE WEB PAGE displayed. ⚠️ NOT Andy's rating and never averaged with
    # it. A table rather than columns on recipes, so a re-import records a SECOND observation instead
    # of destroying the first. scale_assumed records that the 5-point scale was a guess (bestRating is
    # absent from all 7 fixtures that carry a rating). int-boolean, the is_heading/is_admin idiom.
    op.create_table(
        "recipe_source_ratings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recipe_id", sa.Text(), sa.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", sa.Numeric(4, 2), nullable=False),
        sa.Column("rating_count", sa.Integer(), nullable=True),
        sa.Column("scale", sa.Numeric(4, 2), nullable=False, server_default=sa.text("5")),
        sa.Column("scale_assumed", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_recipe_source_ratings_recipe", "recipe_source_ratings", ["recipe_id"])


def downgrade() -> None:
    # ⚠️ THE PER-COOK RATINGS ARE LOST HERE, and that is why the frozen ratings table matters. Dropping
    #    the column cannot fold several cooks' verdicts back into one row per recipe, so no attempt is
    #    made to. The pre-migration ratings rows are still sitting in `ratings` untouched.
    op.drop_index("idx_recipe_source_ratings_recipe", table_name="recipe_source_ratings")
    op.drop_table("recipe_source_ratings")
    op.drop_index("idx_cook_log_rating", table_name="cook_log")
    op.drop_constraint("ck_cook_log_caption_len", "cook_log", type_="check")
    op.drop_constraint("ck_cook_log_rating_half_steps", "cook_log", type_="check")
    op.drop_column("cook_log", "caption")
    op.drop_column("cook_log", "rated_at")
    op.drop_column("cook_log", "rating")
