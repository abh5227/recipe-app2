"""a fourth match_basis, 'resolved', for an article a person chose (mirrors migrations/045)

⚠️ WHY A FOURTH VALUE RATHER THAN REUSING 'title'. 168 rows landed on a Wikipedia disambiguation
page and were refused rather than guessed. Settling one means reading the page's options and
picking the food sense, which is a judgement and not a match. Recording it as 'title' would file a
human decision as an automatic name hit, and the first question asked of a wrong attachment is how
it was reached.

⚠️ AND IT IS THE BASIS A WRONG ATTACHMENT IS MOST LIKELY TO CARRY. 'mint' reached Mint (candy) and
'squash' reached Squash (drink), both by sitelink, the basis described as authoritative. A sitelink
is authoritative about which item links to which article and says nothing about whether the item is
the sense a cook means. See migrations/045.

⚠️ POSTGRES TAKES A NAMED CHECK AND SQLITE REBUILDS THE TABLE. The batch operation below does the
right thing on both, which is why it is written as batch_alter_table rather than a raw ALTER.

Revision ID: f3c4d5e6a7b8
Revises: f2b3c4d5e6a7
Create Date: 2026-09-18 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3c4d5e6a7b8'
down_revision: Union[str, Sequence[str], None] = 'f2b3c4d5e6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "match_basis IN ('sitelink','title','redirect')"
NEW = "match_basis IN ('sitelink','title','redirect','resolved')"


def upgrade() -> None:
    with op.batch_alter_table("library_sourced_content") as b:
        b.drop_constraint("ck_lsc_match_basis", type_="check")
        b.create_check_constraint("ck_lsc_match_basis", sa.text(NEW))


def downgrade() -> None:
    # ⚠️ A row already recorded as 'resolved' would violate the narrower CHECK, so it moves back
    #    to 'title', the nearest of the three. The attachment survives and only the record of how
    #    it was reached is coarsened.
    op.execute("UPDATE library_sourced_content SET match_basis='title' "
               "WHERE match_basis='resolved'")
    with op.batch_alter_table("library_sourced_content") as b:
        b.drop_constraint("ck_lsc_match_basis", type_="check")
        b.create_check_constraint("ck_lsc_match_basis", sa.text(OLD))
