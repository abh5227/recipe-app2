"""archived_at matches the format every other text timestamp uses

Revision ID: d7a1c3e95b20
Revises: a4d2f8c16b57
Create Date: 2026-10-01 14:30:00.000000

⚠️ A REAL SQLITE/POSTGRES DIVERGENCE, FOUND BY tests/test_schema_parity.py ON ITS FIRST RUN.

`import_flags_archive.archived_at` is TEXT NOT NULL with a server default, and the two sides
disagreed about what that default produces:

    SQLite  (migrations/055)              datetime('now')      ->  "2026-10-01 18:05:12"
    Postgres (c58b1d9e4f73, the mirror)   CURRENT_TIMESTAMP    ->  "2026-10-01 18:05:12.123456+00"

The column is text, so Postgres stores whatever CURRENT_TIMESTAMP renders to, which carries
microseconds and a timezone offset that no other timestamp in this schema has. The baseline
revision (72e165e6482e) states the convention in its own docstring and every other text timestamp
follows it, so the mirror was simply written wrong. Nothing explicitly supplies archived_at, which
means the default is the ONLY thing that fills it and every archived row would have carried the
wrong shape.

The SQLite side is the correct one and is unchanged. This brings Postgres to the convention.

⚠️ A NEW REVISION RATHER THAN AN EDIT to c58b1d9e4f73, per the repository's rule that a migration is
apply-once and is corrected by a later one. Editing the applied revision would leave any database
that already ran it untouched while claiming to be fixed.

No data is rewritten. The archive is empty today (the move script has archived 0 rows), and a
default only applies to rows inserted after it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d7a1c3e95b20"
down_revision: Union[str, Sequence[str], None] = "a4d2f8c16b57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONVENTION = "to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')"


def upgrade() -> None:
    op.alter_column("import_flags_archive", "archived_at",
                    existing_type=sa.Text(), existing_nullable=False,
                    server_default=sa.text(CONVENTION))


def downgrade() -> None:
    op.alter_column("import_flags_archive", "archived_at",
                    existing_type=sa.Text(), existing_nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"))
