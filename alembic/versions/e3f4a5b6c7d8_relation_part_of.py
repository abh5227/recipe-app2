"""add 'part_of' to the relation kinds (mirrors migrations/041)

⚠️ 865 CLAIMS HAVE NOWHERE TO GO WITHOUT IT. 815 Wikidata P527 and 50 P361 claims where both
ends are already catalog rows. Forcing them into kind_of would say a cinnamon stick is a KIND
of cinnamon, which is a different and wrong claim.

⚠️ POSTGRES ALTERS THE CONSTRAINT IN PLACE. No table rebuild is needed here, unlike the SQLite
side, which cannot alter a CHECK and copies the table instead. Same end state, different route,
which is why the two files do not look alike.

Revision ID: e3f4a5b6c7d8
Revises: c5d6e7f8a9b0
Create Date: 2026-09-15 16:21:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "kind IN ('kind_of','in_category','made_from')"
_NEW = "kind IN ('kind_of','in_category','made_from','part_of')"
_NAME = "ck_lr_kind"          # the name c5d6e7f8a9b0 gave it. Verified, not guessed.


def upgrade() -> None:
    op.drop_constraint(_NAME, "library_relations", type_="check")
    op.create_check_constraint(_NAME, "library_relations", _NEW)


def downgrade() -> None:
    op.execute("DELETE FROM library_relations WHERE kind = 'part_of'")
    op.drop_constraint(_NAME, "library_relations", type_="check")
    op.create_check_constraint(_NAME, "library_relations", _OLD)
