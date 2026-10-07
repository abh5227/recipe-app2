"""A machine repair rewrites a baseline without deleting the parts it did not touch.

⚠️ THE DEFECT, MEASURED RATHER THAN IMAGINED. `content_blob(recipe, ingredients, steps,
waits=None, storage=None)` OMITS waits and storage when they are falsy, which is deliberate and
load-bearing: every baseline written before those keys existed would otherwise stop being
byte-equal to its recipe. The cost is that the THREE-ARGUMENT form is a delete. A pass that loads a
stored baseline, edits one ingredient row in place and re-serializes with three arguments strips
both keys from a baseline that had them, and every wait on that recipe then reports as "added"
under "your changes", permanently, from a repair no cook made. That is the precise thing LOCKSTEP
exists to prevent.

It was found once, in snapshot_headsync, whose docstring carries the post-mortem. Three other
callers had the identical line and were missed: scripts/reparse_lines.apply_catchup,
resplit.write_lockstep and scripts/restore_from_paprika. Found by an independent review of the
2026-10-07 round, reproduced below.

⚠️ AND LIVE IS INSIDE THE BLAST RADIUS, WHICH IS WHY THIS IS STATED OVER THE FOLDER. Measured
read-only on live: 85 of the 300 reason='original' baselines carry a waits key and 28 carry
storage. `panang-curry` is named in relink_pass.NAMED_REPAIRS and is one of the 85. Both passes
happen to find zero rows on live today, so nothing is damaged, and that is luck rather than a
property.
"""
import ast
import json
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


# --------------------------------------------------------------------------------------------- #
# Stated over the folder, so the NEXT pass written is covered before anyone remembers it
# --------------------------------------------------------------------------------------------- #

# A three-argument content_blob is only correct where the baseline is being CREATED and the recipe
# genuinely has no waits and no storage yet. Each entry names why, and an entry that matches no
# call is a failure: an allowance nobody is using is a licence left lying around.
CREATES_A_BASELINE = {
    ("import_write.py", "commit_plan"):
        "the first baseline of a freshly imported recipe. import_write writes no recipe_waits and "
        "no recipe_storage rows at all (grep: neither table is named in the file), so there is "
        "nothing for this call to carry.",
}


def _sources():
    """Every non-test source file that could hold a pass. Stated as a walk, not a list of names."""
    files = sorted(REPO.glob("*.py"))
    files += sorted((REPO / "scripts").glob("*.py"))
    files += sorted((REPO / "scripts" / "applied").glob("*.py"))
    return [f for f in files if f.name != "snapshot_serialize.py"]


def _enclosing(tree, node):
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        if any(x is node for x in ast.walk(fn)):
            return fn.name
    return "<module>"


def _short_calls():
    """Every content_blob call that neither passes waits/storage nor names them by keyword."""
    out = []
    for f in _sources():
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            # ⚠️ BOTH SPELLINGS. app.py and import_write.py call it as
            #    snapshot_serialize.content_blob(...), which is an ast.Attribute and not an
            #    ast.Name, and a matcher that read only the bare name found 3 of the 4 real calls
            #    and silently excused the fourth. A check that cannot see a call cannot refuse it.
            if not isinstance(n, ast.Call):
                continue
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if name != "content_blob":
                continue
            named = {k.arg for k in n.keywords}
            if len(n.args) >= 5 or {"waits", "storage"} & named:
                continue
            out.append((f.name, _enclosing(tree, n), n.lineno))
    return out


def test_no_pass_rewrites_a_baseline_with_the_three_argument_form():
    """⚠️ THE CHECK IS ON THE CALL, NOT ON A COMMENT CLAIMING THE CALL IS SAFE. Three files said
    they re-serialized "through THE format module, so an untouched field cannot drift", and all
    three were dropping two keys while they said it."""
    unexplained = [c for c in _short_calls() if (c[0], c[1]) not in CREATES_A_BASELINE]
    assert not unexplained, (
        "a three-argument content_blob DELETES waits and storage. Use "
        "snapshot_serialize.rewrite_baseline to rewrite a stored baseline, or declare the call in "
        f"CREATES_A_BASELINE with a reason:\n  " + "\n  ".join(
            f"{f}:{ln} in {fn}()" for f, fn, ln in unexplained))


def test_every_declared_exception_is_a_real_call():
    """An allowance nobody is using is a licence left lying around, which is the rule
    tests/test_lockstep_guard.py states about its own allowlist."""
    seen = {(f, fn) for f, fn, _ in _short_calls()}
    stale = set(CREATES_A_BASELINE) - seen
    assert not stale, f"CREATES_A_BASELINE names calls that no longer exist: {sorted(stale)}"


def test_the_folder_walk_is_not_empty():
    """⚠️ ANTI-VACUITY. A glob that stops matching turns both tests above into a pass."""
    files = _sources()
    assert len(files) > 40, len(files)
    names = {f.name for f in files}
    for required in ("import_write.py", "resplit.py", "reparse_lines.py", "restore_from_paprika.py"):
        assert required in names, f"{required} fell out of the walk this test is stated over"


# --------------------------------------------------------------------------------------------- #
# What rewrite_baseline does, and what the pass that calls it does
# --------------------------------------------------------------------------------------------- #

WAIT = {"id": 7, "kind": "rising", "label": "overnight", "minutes": 480, "in_total": 1,
        "when_kind": "always", "when_label": None, "position": 0, "ext_label": None,
        "alongside_no": None, "step_id": None}
STORE = {"id": 3, "where_kept": "fridge", "label": "up to 3 days", "applies_to": None,
         "position": 0}


def _doc(**over):
    base = {"recipe": {"name": "R"}, "ingredients": [{"position": 0, "label": "cumin"}],
            "steps": [], "waits": [WAIT], "storage": [STORE]}
    base.update(over)
    return base


def test_a_rewrite_carries_the_keys_it_was_not_asked_to_change():
    out = json.loads(ss.rewrite_baseline(_doc(), ingredients=[{"position": 0, "label": "cumin seed"}]))
    assert out["ingredients"][0]["label"] == "cumin seed"
    assert [w["id"] for w in out["waits"]] == [7], out
    assert [x["id"] for x in out["storage"]] == [3], out


def test_a_rewrite_of_a_baseline_that_never_had_them_does_not_invent_them():
    """⚠️ THE OMISSION IS THE POINT AND MUST SURVIVE THE FIX. Emitting "waits":[] on the baselines
    written before the key existed would take every one of them out of the byte-equal set."""
    out = json.loads(ss.rewrite_baseline(_doc(waits=None, storage=None)))
    assert "waits" not in out and "storage" not in out, out


def _db_with_a_wait_in_the_baseline(tmp_path):
    """One recipe, one line the live re-split moved on from, and a wait in the stored baseline."""
    db = tmp_path / "carry.db"
    migrate_mod.migrate(verbose=False, db=db)
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("INSERT INTO recipes (id, name, source) VALUES ('r', 'R', 'app')")
    cols = dict(recipe_id="r", position=0, is_heading=0, qty="2 tsp", quantity="2", unit="tsp",
                raw_text="2 tsp cumin seed", label="cumin seed")
    con.execute(f"INSERT INTO recipe_ingredients ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})", list(cols.values()))
    con.row_factory = sqlite3.Row
    row = dict(con.execute("SELECT * FROM recipe_ingredients").fetchone())
    # the baseline is one re-split behind on quantity and unit, which is the debt the catch-up cancels
    behind = dict(row, quantity=None, unit=None)
    blob = ss.content_blob({"name": "R"}, [behind], [], [WAIT], [STORE])
    con.execute("INSERT INTO recipe_snapshots (recipe_id, user_id, reason, content, created_at) "
                "VALUES ('r', 1, 'original', ?, '2026-01-01T00:00:00Z')", (blob,))
    con.commit()
    return db, con


def _stored(con):
    return json.loads(con.execute(
        "SELECT content FROM recipe_snapshots WHERE reason='original'").fetchone()[0])


def test_the_catch_up_pass_leaves_the_waits_and_the_storage_where_it_found_them(tmp_path):
    """⚠️ THE REVIEW'S OWN REPRODUCTION, RUN THROUGH THE REAL PASS. Before the fix this left the
    baseline with no waits key at all, and the recipe's wait then read as "added" for good."""
    db, con = _db_with_a_wait_in_the_baseline(tmp_path)
    assert "waits" in _stored(con), "the fixture must START with a wait, or this proves nothing"
    plan = reparse_lines.plan_catchup(con)
    assert plan, "the fixture must give the catch-up something to do, or this proves nothing"
    reparse_lines.apply_catchup(con, plan)
    con.commit()
    after = _stored(con)
    assert [w["id"] for w in after.get("waits", [])] == [7], \
        f"the catch-up deleted the baseline's waits: {sorted(after)}"
    assert [x["id"] for x in after.get("storage", [])] == [3], \
        f"the catch-up deleted the baseline's storage: {sorted(after)}"
    assert after["ingredients"][0]["unit"] == "tsp", "the catch-up did not do its own job"
