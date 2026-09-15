"""the eight dish facets (mirrors migrations/038)

⚠️ THIS REVISION WAS MISSING AND NOTHING CAUGHT IT. 035, 036 and 037 each shipped an Alembic
counterpart. 038 did not, so the eight tables existed in SQLite and would simply have been absent
from Postgres. There is no parity test between migrations/ and alembic/versions/, so CI stayed
green the whole time. test_every_sqlite_migration_has_an_alembic_revision now closes that.

⚠️ SEVEN TABLES ARE SAFE BY CONSTRUCTION AND ONE IS AN EXCEPTION. form, method, diet, structural
and appliance hold a word from an authored vocabulary. base and accompaniment hold a library_id.
mined_dish holds the cleaned specific-dish string, which is the one deliberate free-text exception
in the whole mined schema, recorded in tests/test_mining_boundaries.py::FREE_TEXT_EXCEPTIONS.

⚠️ EVERY OTHER FACET REFERENCES THE DISH BY SURROGATE ID, never by its text. That is what keeps
the exception needed once rather than eight times. See migrations/038 for the full reasoning.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-09-14 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, Sequence[str], None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, value column, index name). The dish table is created separately, it carries the string.
FACETS = [("mined_dish_form", "dish_type", "idx_mdf_v"),
          ("mined_dish_method", "method", "idx_mdm_v"),
          ("mined_dish_diet", "diet", "idx_mdd_v"),
          ("mined_dish_structural", "structural", "idx_mds_v"),
          ("mined_dish_appliance", "appliance", "idx_mda_v"),
          ("mined_dish_base", "library_id", "idx_mdb_v"),
          ("mined_dish_accompaniment", "library_id", "idx_mdac_v")]


def upgrade() -> None:
    op.create_table(
        "mined_dish",
        sa.Column("dish_id", sa.Text(), nullable=False),
        sa.Column("dish", sa.Text(), nullable=False),      # the one free-text exception, cleaned
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("source_slug", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("dish_id", "source_slug"),
    )
    op.create_index("idx_mdish_n", "mined_dish", [sa.text("n DESC")])
    for table, col, idx in FACETS:
        op.create_table(
            table,
            sa.Column("dish_id", sa.Text(), nullable=False),
            sa.Column(col, sa.Text(), nullable=False),
            sa.Column("n", sa.Integer(), nullable=False),
            sa.Column("source_slug", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("dish_id", col, "source_slug"),
        )
        op.create_index(idx, table, [col, sa.text("n DESC")])


def downgrade() -> None:
    for table, _col, idx in reversed(FACETS):
        op.drop_index(idx, table_name=table)
        op.drop_table(table)
    op.drop_index("idx_mdish_n", table_name="mined_dish")
    op.drop_table("mined_dish")
