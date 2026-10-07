"""The baseline catch-up may only cancel debt, never run ahead of the live row.

⚠️ THE DEFECT, MEASURED. reparse_lines.plan_catchup decides a baseline row "was left behind by a
live re-split" by re-splitting the baseline's own text and checking it lands where the live row
already is. It compared `qty` and `label`, and resplit.plan_row writes `qty`, `quantity`, `unit` and
`label`. A live row carrying a NULL quantity and unit therefore agreed on both compared columns, the
catch-up wrote a quantity and a unit into the BASELINE, and the recipe stopped being byte-equal to
it. The page then shows an edit the cook never made, which is the exact shape lockstep exists to
prevent. Found by tests/test_lockstep_guard.py running the pass over a fixture.

A NULL quantity and unit is not a corner: that is what every row looked like before the 2026-09-25
reparse, and migration 015 left both columns nullable on purpose.
"""
import pathlib
import sqlite3
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import migrate as migrate_mod                                                   # noqa: E402
import reparse_lines                                                            # noqa: E402
import snapshot_serialize as ss                                                 # noqa: E402


def _db(tmp_path, live_cols, baseline_cols):
    """One recipe, one ingredient line, with the live row and the baseline row set separately."""
    db = tmp_path / "catchup.db"
    migrate_mod.migrate(verbose=False, db=db)
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("INSERT INTO recipes (id, name, source) VALUES ('r', 'R', 'app')")
    cols = dict(recipe_id="r", position=0, is_heading=0, **live_cols)
    con.execute(f"INSERT INTO recipe_ingredients ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})", list(cols.values()))
    con.row_factory = sqlite3.Row
    row = dict(con.execute("SELECT * FROM recipe_ingredients").fetchone())
    base_row = dict(row, **baseline_cols)
    blob = ss.content_blob({"name": "R"}, [base_row], [])
    con.execute("INSERT INTO recipe_snapshots (recipe_id, user_id, reason, content, created_at) "
                "VALUES ('r', 1, 'original', ?, '2026-01-01T00:00:00Z')", (blob,))
    con.commit()
    return db, con


def _baseline(con):
    import json
    doc = json.loads(con.execute("SELECT content FROM recipe_snapshots WHERE reason='original'")
                     .fetchone()[0])
    return doc["ingredients"][0]


def test_a_baseline_is_not_caught_up_past_a_live_row_that_was_never_resplit(tmp_path):
    """The live row has no quantity and no unit, so there is no debt to cancel and the catch-up
    must leave the baseline alone."""
    db, con = _db(tmp_path,
                  live_cols=dict(qty="2 tsp", raw_text="2 tsp cumin seed", label="cumin seed",
                                 quantity=None, unit=None),
                  baseline_cols=dict(quantity=None, unit=None))
    before = _baseline(con)
    plan = reparse_lines.plan_catchup(con)
    reparse_lines.apply_catchup(con, plan)
    con.commit()
    assert _baseline(con) == before, (
        "the catch-up moved a baseline whose live row had not been re-split, which mints an "
        f"annotation nobody made: {plan}")


def test_a_baseline_left_behind_by_a_real_resplit_is_still_caught_up(tmp_path):
    """And the other half. The live row HAS been re-split, the baseline has not, so the debt is
    real and the catch-up cancels it. A fix that simply stopped writing would pass the test above
    and break this one."""
    db, con = _db(tmp_path,
                  live_cols=dict(qty="2 tsp", raw_text="2 tsp cumin seed", label="cumin seed",
                                 quantity="2", unit="tsp"),
                  baseline_cols=dict(quantity=None, unit=None))
    plan = reparse_lines.plan_catchup(con)
    assert plan, "the catch-up found no debt where the live row is ahead of its baseline"
    reparse_lines.apply_catchup(con, plan)
    con.commit()
    after = _baseline(con)
    assert (after["quantity"], after["unit"]) == ("2", "tsp"), after
