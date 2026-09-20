"""retire the 36 hand-authored demo ingredients, their seasons and their regions (mirrors migrations/046)

The 36 were written early as a demonstration of what an ingredient library would look like. The
library that actually shipped is 10,013 catalog rows drawn from Wikidata, Open Food Facts, AGROVOC
and Wiktionary, and the 36 carry model-written prose that was never rewritten. They are a demo of
the idea, not an early version of the data, so they are deleted rather than migrated onto the
catalog.

⚠️ ingredient_weights IS NOT TOUCHED AND MUST NOT BE. Its 129 rows are the King Arthur
volume-to-weight chart, real reference data behind the grams converter. 0 of its lookup_keys is one
of the 36. Only seed_content's ingredient half is being retired.

⚠️ SCOPED TO source='seed' RATHER THAN TO EVERY ROW, so an app-owned or promoted ingredient added
later survives this on a database built from scratch. Today the two sets are identical, and they
will not stay identical. See migrations/046.

⚠️ DML, NOT DDL, WHICH IS UNUSUAL HERE AND DELIBERATE. The schema does not change. What changes is
which rows the seed tier owns, and Postgres has to reach the same state SQLite does or the two
dialects drift on the one table the app reads on every recipe page.

⚠️ THE library_names INSERT IS GUARDED AND IS A NO-OP ON POSTGRES TODAY. build_db.py is raw-SQLite
by design and never runs against PG, so PG's library_names is created by an earlier revision and
left empty (see build_db.seed_library_names). The EXISTS guard means an empty lookup stays empty
rather than gaining one lone row.

Revision ID: bbbd3536038a
Revises: f3c4d5e6a7b8
Create Date: 2026-09-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'bbbd3536038a'
down_revision: Union[str, Sequence[str], None] = 'f3c4d5e6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEED = "SELECT id FROM ingredients WHERE source = 'seed'"


def upgrade() -> None:
    # 1. the catalog gains the one row the repoint needs. Guarded, so an empty lookup stays empty.
    op.execute("""
        INSERT INTO library_names (library_id, canonical)
        SELECT 'lemongrass', 'lemongrass'
         WHERE EXISTS (SELECT 1 FROM library_names)
           AND NOT EXISTS (SELECT 1 FROM library_names WHERE library_id = 'lemongrass')
    """)

    # 2. the two lines that carry no catalog_id. The values are exactly what build_links.py writes,
    #    so a later link rebuild is a no-op rather than a diff.
    op.execute("""
        UPDATE recipe_ingredients
           SET catalog_id = 'lemongrass', link_confidence = 'exact',
               link_rule = 'exact', link_matched = 'lemongrass'
         WHERE recipe_id = 'gai-yang' AND position = 4 AND catalog_id IS NULL
    """)
    op.execute("""
        UPDATE recipe_ingredients
           SET catalog_id = 'Q45422', link_confidence = 'repoint',
               link_rule = 'repoint:instant-yeast-to-yeast', link_matched = 'yeast'
         WHERE recipe_id = 'no-knead-bread' AND position = 1 AND catalog_id IS NULL
    """)

    # 3. release every line, not only the two above. ingredient_id carries no ON DELETE clause, so
    #    step 5 is refused while any line still points at one of these rows.
    op.execute(f"UPDATE recipe_ingredients SET ingredient_id = NULL WHERE ingredient_id IN ({SEED})")

    # 4. children first. Both cascade, and both are written out so the file does not depend on it.
    op.execute(f"DELETE FROM ingredient_seasons WHERE ingredient_id IN ({SEED})")
    op.execute(f"DELETE FROM ingredient_regions WHERE ingredient_id IN ({SEED})")

    # 5. the rows themselves.
    op.execute("DELETE FROM ingredients WHERE source = 'seed'")

    # 6. the regions left behind, orphans only.
    op.execute("DELETE FROM regions WHERE id NOT IN (SELECT region_id FROM ingredient_regions)")


def downgrade() -> None:
    # ⚠️ NOT REVERSIBLE, AND SAYING SO IS THE HONEST ANSWER. The 36 rows, their prose, their 65
    #    seasons and their 44 regions are content, not schema. Recreating them means restoring the
    #    INGREDIENTS dict this migration was written to retire, which is a git revert of seed.py
    #    plus a build_db run, not anything this function can do. A downgrade that silently
    #    recreated nothing would report success on an empty result.
    raise NotImplementedError(
        "046 deletes seed content. Restore seed.py's INGREDIENTS and run build_db.py instead."
    )
