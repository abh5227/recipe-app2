"""A migration and a corpus pass may not move "your changes" or the byte-equal set.

⚠️ THE LESSON THIS FILE IS WRITTEN FROM. The page's "your changes" is
diff(reason='original' snapshot, current rows), so anything that rewrites a row without rewriting
that baseline in the same breath is indistinguishable from the cook having hand-edited it. Every
corpus pass patches both halves in lockstep for that reason, and nothing was checking that a
MIGRATION does the same. Migration 046 deleted the 36 hand-authored ingredient rows and their 65
seasons, 102 region links and 44 regions, and the only thing that kept the annotation layer still
through that round was a person thinking about it.

So this is the standing version of the question. It is asked of:
  * every migration that can touch content, run against a fixture that already HAS a hand edit and
    byte-equal recipes, and
  * every corpus pass that can write, run with --apply against the same fixture.

⚠️ AND IT CANNOT PASS VACUOUSLY, WHICH IS THE ONLY WAY A CHECK LIKE THIS GOES WRONG. Two empty
readings are equal. `_assert_live_fixture` demands a non-empty short-circuit set AND a non-empty
annotation set in the BEFORE reading, so a fixture that failed to seed, or a schema too old to hold
a snapshot, is a failure or a declared skip rather than a pass.
`test_the_guard_catches_a_migration_that_edits_a_recipe_without_its_baseline` plants exactly the
defect the file exists for and asserts the comparison catches it.
"""
import json
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS = REPO / "migrations"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import migrate as migrate_mod                                                  # noqa: E402
import snapshot_serialize as ss                                                # noqa: E402
from gates import state as gate_state                                          # noqa: E402

ALL = sorted(p.name for p in MIGRATIONS.glob("*.sql"))

# recipe_snapshots is created by 028, so nothing before it can hold a baseline to compare. Those
# migrations are listed rather than skipped silently, and the count is asserted below, so a
# migration cannot slip into this group by accident.
FIRST_WITH_SNAPSHOTS = "028_recipe_snapshots.sql"
NO_SNAPSHOT_YET = [n for n in ALL if n <= FIRST_WITH_SNAPSHOTS]
CHECKABLE = [n for n in ALL if n > FIRST_WITH_SNAPSHOTS]

# ⚠️ AN ENTRY HERE IS A DECISION, NOT A CONVENIENCE. A migration that legitimately moves the
# annotation layer names itself and says why, and the test still asserts that it moved it in the
# declared direction rather than letting it move freely. Empty today.
LOCKSTEP_ALLOWED = {}

# The passes that can write. Taken from the folder rather than from a list, so the next one written
# is covered. The archive (scripts/applied/) refuses to run and is excluded by living there.
NOT_A_PASS = {"corpus_guard.py", "serve_live.py", "serve_rehearsal.py", "create_admin.py",
              "cold_start_check.py", "gen_note_lead_cases.py", "plan_ahead_short_rests.py",
              "plan_ahead_proposals_v3.py", "gen_note_corpus.py", "scan_notes_for_waits.py",
              "time-block-lift.py"}
PASSES = sorted(p.name for p in (REPO / "scripts").glob("*.py")
                if p.name not in NOT_A_PASS and "--apply" in p.read_text())


# ---------------------------------------------------------------------------- the fixture --------

ORIGINAL_STEP = "Toast the spices until they smell of pepper, about 2 minutes."
EDITED_STEP = "Toast the spices in a dry pan until they smell of pepper, about 90 seconds."


def _columns(con, table):
    return {r[1]: r for r in con.execute(f"PRAGMA table_info({table})")}


def _insert(con, table, values):
    """Insert what this schema can hold. Columns the table does not have yet are dropped, and a
    NOT NULL column with no default that the caller did not name is filled, so one seeder works
    against every schema in the folder's history."""
    cols = _columns(con, table)
    if not cols:
        return
    use = {k: v for k, v in values.items() if k in cols}
    for name, r in cols.items():
        _, _, decl, notnull, dflt, pk = r
        if name in use or pk or dflt is not None or not notnull:
            continue
        use[name] = "" if "CHAR" in (decl or "").upper() or "TEXT" in (decl or "").upper() else 0
    names = ",".join('"' + k + '"' for k in use)
    marks = ",".join("?" * len(use))
    con.execute(f'INSERT INTO "{table}" ({names}) VALUES ({marks})', list(use.values()))


def _rows(con, sql, *args):
    return [dict(r) for r in con.execute(sql, args)]


def seed(db):
    """Three recipes: two byte-equal to their baselines, one with a hand edit.

    The baselines are written with the app's OWN serializer (snapshot_serialize.content_blob), which
    is what the gate reads them back with, so "byte-equal" means the same thing here as on the page.
    """
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = OFF")
    _insert(con, "users", {"id": 1, "email": "lockstep@test.local", "password_hash": "x",
                           "created_at": "2026-01-01T00:00:00Z", "is_admin": 0})
    for rid, name in (("kept-one", "Kept One"), ("kept-two", "Kept Two"), ("edited", "Edited")):
        _insert(con, "recipes", {"id": rid, "name": name, "source": "app", "category": "Mains",
                                 "servings": "4", "prep_time": "10 min", "cook_time": "20 min",
                                 "descr": "a fixture recipe", "created_at": "2026-01-01T00:00:00Z",
                                 "notes": "An original note paragraph."})
        _insert(con, "recipe_ingredients", {"recipe_id": rid, "position": 0, "is_heading": 0,
                                            "qty": "2 tsp", "raw_text": "2 tsp cumin seed",
                                            "label": "cumin seed"})
        _insert(con, "recipe_ingredients", {"recipe_id": rid, "position": 1, "is_heading": 0,
                                            "qty": "1", "raw_text": "1 onion", "label": "onion"})
        _insert(con, "recipe_steps", {"recipe_id": rid, "position": 0, "is_heading": 0,
                                      "text": ORIGINAL_STEP})
        _insert(con, "recipe_steps", {"recipe_id": rid, "position": 1, "is_heading": 0,
                                      "text": "Add the onion and cook until soft."})
    con.commit()

    # the baselines, from the rows as they stand now
    for rid in ("kept-one", "kept-two", "edited"):
        recipe = dict(con.execute("SELECT * FROM recipes WHERE id = ?", (rid,)).fetchone())
        blob = ss.content_blob(
            recipe,
            _rows(con, "SELECT * FROM recipe_ingredients WHERE recipe_id = ? ORDER BY position, id", rid),
            _rows(con, "SELECT * FROM recipe_steps WHERE recipe_id = ? ORDER BY position, id", rid),
            _rows(con, "SELECT * FROM recipe_waits WHERE recipe_id = ? ORDER BY position, id", rid)
            if _columns(con, "recipe_waits") else [],
            _rows(con, "SELECT * FROM recipe_storage WHERE recipe_id = ? ORDER BY position, id", rid)
            if _columns(con, "recipe_storage") else [])
        _insert(con, "recipe_snapshots", {"recipe_id": rid, "user_id": 1, "reason": "original",
                                          "content": blob, "created_at": "2026-01-01T00:00:00Z"})
    # ⚠️ THE HAND EDIT GOES IN AFTER THE BASELINE, which is what makes it a hand edit. One recipe
    #    therefore differs from its baseline by one step's wording, and the page would show that
    #    entry under "your changes".
    con.execute("UPDATE recipe_steps SET text = ? WHERE recipe_id = 'edited' AND position = 0",
                (EDITED_STEP,))
    con.commit()
    con.close()
    return db


def build_up_to(tmp_path, upto_exclusive, folder=None):
    """A fresh build holding every migration BEFORE `upto_exclusive`, then seeded."""
    part = tmp_path / f"part-{upto_exclusive}"
    part.mkdir(exist_ok=True)
    for p in sorted((folder or MIGRATIONS).glob("*.sql")):
        if p.name < upto_exclusive:
            shutil.copy(p, part / p.name)
    db = tmp_path / f"db-{upto_exclusive}"
    migrate_mod.MIGRATIONS_DIR = part
    migrate_mod.migrate(verbose=False, db=db)
    return seed(db), part


def apply_one(db, part, name, folder=None):
    """Apply exactly one more migration, through migrate.py itself."""
    shutil.copy((folder or MIGRATIONS) / name, part / name)
    migrate_mod.MIGRATIONS_DIR = part
    migrate_mod.migrate(verbose=False, db=db)


def _assert_live_fixture(st, what):
    """⚠️ THE ANTI-VACUITY GUARD. Equal readings prove nothing if both are empty."""
    assert st["short_circuit"], f"{what}: nothing is byte-equal to its baseline, so the check is empty"
    assert st["annotations"], f"{what}: no hand edit is visible, so the check is empty"
    assert len(st["short_circuit"]) >= 2, f"{what}: {st['short_circuit']}"


# ---------------------------------------------------------------------------- the migrations -----

def test_the_fixture_shows_two_untouched_recipes_and_one_hand_edit(tmp_path):
    """The fixture itself, on the current schema, before anything is asked of it."""
    db, _ = build_up_to(tmp_path, "zzz")          # every migration
    st = gate_state.read_state(db)
    _assert_live_fixture(st, "the fixture")
    assert st["short_circuit"] == ["kept-one", "kept-two"]
    assert list(st["annotations"]) == ["edited"]
    entry = st["annotations"]["edited"][0]
    assert entry[0] == "step" and entry[1] == "modified", entry


@pytest.mark.parametrize("name", CHECKABLE)
def test_a_migration_moves_neither_the_annotations_nor_the_byte_equal_set(tmp_path, name):
    db, part = build_up_to(tmp_path, name)
    before = gate_state.read_state(db)
    _assert_live_fixture(before, f"before {name}")

    apply_one(db, part, name)
    after = gate_state.read_state(db)

    moved_short = before["short_circuit"] != after["short_circuit"]
    moved_anns = before["annotations"] != after["annotations"]
    if name in LOCKSTEP_ALLOWED:
        assert moved_short or moved_anns, (
            f"{name} is on the allowlist ({LOCKSTEP_ALLOWED[name]}) and moved nothing. "
            "An allowlist entry that is not needed is a licence nobody is using.")
        return
    assert not moved_short, (
        f"{name} moved the byte-equal set.\n"
        f"  left:   {sorted(set(before['short_circuit']) - set(after['short_circuit']))}\n"
        f"  joined: {sorted(set(after['short_circuit']) - set(before['short_circuit']))}\n"
        "A migration that rewrites a row has to rewrite the reason='original' baseline in the same "
        "transaction, or declare itself in LOCKSTEP_ALLOWED with a reason.")
    assert not moved_anns, (
        f"{name} moved 'your changes'.\n  before: {before['annotations']}\n  after:  {after['annotations']}")


def test_every_migration_is_either_checked_or_predates_the_snapshot_table():
    """No third category. A migration is checked above, or it ran before recipe_snapshots existed."""
    assert set(CHECKABLE) | set(NO_SNAPSHOT_YET) == set(ALL)
    assert not (set(CHECKABLE) & set(NO_SNAPSHOT_YET))
    assert len(NO_SNAPSHOT_YET) == 28, NO_SNAPSHOT_YET
    assert len(CHECKABLE) >= 34, len(CHECKABLE)


# ---------------------------------------------------------------------------- the planted defect -

PLANTED = """-- a migration that edits a recipe's text and leaves its baseline alone.
BEGIN;
UPDATE recipe_steps SET text = 'A machine rewrote this and told nobody.'
 WHERE recipe_id = 'kept-one' AND position = 0;
COMMIT;
"""


def test_the_guard_catches_a_migration_that_edits_a_recipe_without_its_baseline(tmp_path):
    """⚠️ THE PROOF THAT THE CHECK ABOVE IS DOING SOMETHING. The planted migration is exactly the
    shape of the defect: a real row rewritten, the reason='original' baseline untouched. The recipe
    leaves the byte-equal set and arrives in 'your changes' as an edit the cook never made."""
    folder = tmp_path / "planted"
    folder.mkdir()
    for p in sorted(MIGRATIONS.glob("*.sql")):
        shutil.copy(p, folder / p.name)
    (folder / "999_planted_edit.sql").write_text(PLANTED)

    db, part = build_up_to(tmp_path, "999_planted_edit.sql", folder=folder)
    before = gate_state.read_state(db)
    _assert_live_fixture(before, "before the planted migration")

    apply_one(db, part, "999_planted_edit.sql", folder=folder)
    after = gate_state.read_state(db)

    assert "kept-one" in before["short_circuit"] and "kept-one" not in after["short_circuit"], (
        "the planted edit did not cost kept-one its place in the byte-equal set, so the comparison "
        "the other test relies on would not have caught it")
    assert "kept-one" not in before["annotations"] and "kept-one" in after["annotations"], (
        "the planted edit minted no annotation entry, so 'your changes' would not have shown it")
    assert after["annotations"]["kept-one"][0][1] == "modified"


def test_the_planted_defect_is_invisible_when_the_baseline_moves_in_lockstep(tmp_path):
    """And the other half: the same edit, with the baseline patched in the same transaction, moves
    nothing. This is what every corpus pass does and what a migration would have to do."""
    folder = tmp_path / "lockstep"
    folder.mkdir()
    for p in sorted(MIGRATIONS.glob("*.sql")):
        shutil.copy(p, folder / p.name)
    db, part = build_up_to(tmp_path, "zzz", folder=folder)
    before = gate_state.read_state(db)

    con = sqlite3.connect(db)
    row = con.execute("SELECT content FROM recipe_snapshots WHERE recipe_id='kept-one' "
                      "AND reason='original'").fetchone()[0]
    body = json.loads(row)
    new_text = "A machine rewrote this and patched the baseline with it."
    for st in body["steps"]:
        if st["position"] == 0:
            st["text"] = new_text
    con.execute("UPDATE recipe_steps SET text = ? WHERE recipe_id='kept-one' AND position=0",
                (new_text,))
    con.execute("UPDATE recipe_snapshots SET content = ? WHERE recipe_id='kept-one' "
                "AND reason='original'",
                (json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")),))
    con.commit()
    con.close()

    after = gate_state.read_state(db)
    assert before["short_circuit"] == after["short_circuit"], "the lockstep patch cost a recipe its place"
    assert before["annotations"] == after["annotations"], "the lockstep patch minted a mark"


# ---------------------------------------------------------------------------- the data passes ----

def _argv_for(script, db):
    """The command line this pass actually takes. Read from the script rather than assumed."""
    src = (REPO / "scripts" / script).read_text()
    if '"--db"' in src:
        return ["--db", str(db), "--apply"]
    return [str(db), "--apply"]


@pytest.mark.parametrize("script", PASSES)
def test_a_corpus_pass_moves_neither_the_annotations_nor_the_byte_equal_set(tmp_path, script):
    """Every pass that can write, run with --apply against the fixture.

    ⚠️ A PASS THAT FINDS NOTHING STILL HAS TO LEAVE THE TWO SETS ALONE, and the reading before it
    is asserted non-empty, so this is a real comparison even where the pass has no work to do. What
    it cannot claim is that the pass is lockstep-correct on data it DID change, which is what each
    pass's own test is for (tests/test_corpus_passes.py and the per-pass files)."""
    db, _ = build_up_to(tmp_path, "zzz")
    before = gate_state.read_state(db)
    _assert_live_fixture(before, f"before {script}")

    r = subprocess.run([sys.executable, str(REPO / "scripts" / script)] + _argv_for(script, db),
                       capture_output=True, text=True, cwd=str(REPO), timeout=300)
    # ⚠️ AN ARGPARSE ERROR IS A VACUOUS PASS, AND THIS IS HOW THE CHECK NEARLY WENT QUIET. Six of
    #    the passes take --db where the other twelve take the path as a positional, so invoking all
    #    eighteen the same way meant six of them exited 2 without opening anything, and the
    #    comparison below compared a database nothing had touched. Exit 2 is argparse's own code for
    #    "I could not read that command line".
    assert r.returncode != 2, (
        f"{script} refused the command line, so this test ran nothing:\n{r.stderr[-800:]}")
    after = gate_state.read_state(db)

    assert before["short_circuit"] == after["short_circuit"], (
        f"{script} moved the byte-equal set (exit {r.returncode}).\n"
        f"  left:   {sorted(set(before['short_circuit']) - set(after['short_circuit']))}\n"
        f"  joined: {sorted(set(after['short_circuit']) - set(before['short_circuit']))}\n"
        f"{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    assert before["annotations"] == after["annotations"], (
        f"{script} moved 'your changes' (exit {r.returncode}).\n"
        f"  before: {before['annotations']}\n  after:  {after['annotations']}\n"
        f"{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
