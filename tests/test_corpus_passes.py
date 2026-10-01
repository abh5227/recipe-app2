"""The two corpus scripts, RUN, against a real schema.

⚠️ WHY THIS FILE EXISTS. The claim that the repair scripts and the importer share one rule set was
written in a comment and never executed. They had drifted: import_cleanup.plan_step_rows called
move_link_out_of_label when it lifted a label, and scripts/convert_step_headings._lift did not. The
first clean run of the whole chain from live put a heading reading "Wilt the [[spinach]]" on
bulgogi-bowls, which app.js escapes and never linkifies, so the brackets would have printed on the
page. Nothing in 2,081 tests was running either script, so nothing could have caught it.

The fixture carries the REAL step row ids the decision CSVs name, because the scripts read those
CSVs. bulgogi-bowls 5765 is a lead-in label approved for lifting, and its label is the corpus's one
case of a link inside a label.
"""
import importlib
import importlib.util
import inspect
import json
import pathlib
import re
import sqlite3
import subprocess
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

import migrate  # noqa: E402
import snapshot_serialize  # noqa: E402

BULGOGI_STEP = 5765
BULGOGI_TEXT = ("Wilt the [[spinach]]: heat 2 tsp oil in a large non-stick pan over high heat. "
                "Add half the spinach, toss with tongs until semi-wilted, then add the rest.")


def _blank_step(**kw):
    row = {k: None for k in snapshot_serialize.SNAPSHOT_STEP_FIELDS}
    row.update(kw)
    return row


def _kitchen(tmp_path, steps):
    """A database on the real schema holding one recipe, its steps and its original baseline."""
    db = tmp_path / "corpus.db"
    migrate.DB = db
    migrate.migrate(verbose=False)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO recipes (id, name, source) VALUES ('bulgogi-bowls', 'Bulgogi', 'app')")
    for i, (sid, is_heading, text) in enumerate(steps):
        c.execute("INSERT INTO recipe_steps (id, recipe_id, position, is_heading, heading_level, "
                  "text) VALUES (?,'bulgogi-bowls',?,?,1,?)", (sid, i, is_heading, text))
    body = {"steps": [_blank_step(id=sid, position=i, is_heading=h, text=t)
                      for i, (sid, h, t) in enumerate(steps)]}
    c.execute("INSERT INTO recipe_snapshots (recipe_id, user_id, reason, content, created_at) "
              "VALUES ('bulgogi-bowls', 1, 'original', ?, '2026-01-01T00:00:00Z')",
              (json.dumps(body),))
    c.commit()
    c.close()
    return db


def _steps(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute(
        "SELECT id, position, is_heading, heading_level, text FROM recipe_steps ORDER BY position")]
    c.close()
    return rows


def _baseline(db):
    c = sqlite3.connect(db)
    body = json.loads(c.execute("SELECT content FROM recipe_snapshots WHERE reason='original'")
                      .fetchone()[0])
    c.close()
    return body


def test_the_corpus_lift_moves_a_link_out_of_the_label_like_the_importer_does(tmp_path):
    """convert_step_headings._lift and import_cleanup both apply move_link_out_of_label."""
    import convert_step_headings

    db = _kitchen(tmp_path, [(BULGOGI_STEP, 0, BULGOGI_TEXT)])
    convert_step_headings.run(str(db), True)

    rows = _steps(db)
    assert len(rows) == 2, "the label is lifted into a heading above its step"
    heading, step = rows
    assert heading["is_heading"] == 1
    assert heading["text"] == "Wilt the spinach", "the heading takes the plain words"
    assert "[[" not in heading["text"], "a heading is escaped, so markup would print as brackets"
    assert "[[spinach|spinach]]" in step["text"], "the link moved to the next mention in the step"
    assert step["id"] == BULGOGI_STEP, "the step keeps its id, which wait links are bound to"


def test_the_lift_patches_the_baseline_in_lockstep_so_it_mints_no_mark(tmp_path):
    import convert_step_headings

    db = _kitchen(tmp_path, [(BULGOGI_STEP, 0, BULGOGI_TEXT)])
    convert_step_headings.run(str(db), True)

    live = {(r["id"], r["text"]) for r in _steps(db)}
    base = {(s["id"], s["text"]) for s in _baseline(db)["steps"]}
    assert live == base, "the baseline carries the same words, so the recipe reports no change"


def test_no_heading_in_the_corpus_carries_link_markup(tmp_path):
    """The invariant sweep repairs a heading an earlier pass already lifted with its markup."""
    import apply_label_rules

    db = _kitchen(tmp_path, [
        (9001, 1, "Wilt the [[spinach]]"),
        (9002, 0, "Heat 2 tsp oil in a pan. Add half the spinach, toss until wilted."),
    ])
    apply_label_rules.run(str(db), True)

    rows = _steps(db)
    assert rows[0]["text"] == "Wilt the spinach"
    assert "[[" not in rows[0]["text"]
    assert "[[spinach|spinach]]" in rows[1]["text"]
    base = {s["id"]: s["text"] for s in _baseline(db)["steps"]}
    assert base[9001] == rows[0]["text"] and base[9002] == rows[1]["text"], "lockstep"


def test_a_heading_whose_link_has_no_later_mention_is_flagged_and_still_cleaned(tmp_path):
    """The link cannot move, so it is flagged for re-linking. The brackets still go."""
    import apply_label_rules

    db = _kitchen(tmp_path, [
        (9003, 1, "Wilt the [[spinach]]"),
        (9004, 0, "Heat the oil and cook until everything has softened."),
    ])
    log = apply_label_rules.run(str(db), True)

    assert _steps(db)[0]["text"] == "Wilt the spinach"
    assert any("needs re-linking" in str(f) for f in log["flagged"])


@pytest.mark.parametrize("script", ["add_missed_waits", "apply_label_rules",
                                    "apply_plan_ahead_proposals", "convert_step_headings"])
def test_every_corpus_pass_wires_the_one_shared_live_guard(script):
    """All four name their database, and none of them takes live as a typo.

    ⚠️ THIS TEST USED TO AIM PYTEST AT THE LIVE DATABASE. It set sys.argv to the repo's own
    recipes.db and called main(), so the guard was the only thing between an ordinary
    `python3.13 -m pytest` run and a real migration of the 300-recipe live database. For
    apply_plan_ahead_proposals, which wrote by default, there was not even an --apply to withhold.
    Reproduced by a reviewer: with the guard's path comparison broken, which is what a regression
    looks like, main() wrote and committed.

    So this asserts the WIRING, and the guard itself is asserted below as the pure function it is.
    Nothing here calls main() and nothing here names a path a write could reach.
    """
    import importlib

    import corpus_guard

    mod = importlib.import_module(script)
    assert mod.refuse_live is corpus_guard.refuse_live, \
        f"{script} has its own copy of the guard instead of the shared one"
    src = (BASE / "scripts" / f"{script}.py").read_text()
    assert '--i-mean-live' in src, f"{script} offers no way to say it means live"
    assert "refuse_live(" in src.split("def main(")[-1], f"{script}'s main() never calls the guard"


def test_the_live_guard_refuses_live_and_passes_everything_else(tmp_path):
    """The guard itself, called directly. A pure function, so this can name live safely."""
    import corpus_guard

    live = BASE / "recipes.db"
    with pytest.raises(SystemExit) as e:
        corpus_guard.refuse_live(live, False)
    assert "--i-mean-live" in str(e.value)

    # said out loud, it passes
    corpus_guard.refuse_live(live, True)
    # and a copy under any other name or in any other directory is not live
    corpus_guard.refuse_live(tmp_path / "recipes.db", False)
    corpus_guard.refuse_live(BASE / "rehearsal.db", False)


def test_a_corpus_pass_dry_runs_unless_it_is_told_to_apply():
    """⚠️ ALL FOUR AGREE ON THIS NOW. apply_plan_ahead_proposals took --dry and WROTE by default
    while the other three took --apply and dry-ran by default, so the same command shape had
    opposite effects depending on which one you typed, and the one that wrote was the first in the
    chain and the widest at 90 recipes."""
    for script in ("add_missed_waits", "apply_label_rules",
                   "apply_plan_ahead_proposals", "convert_step_headings"):
        src = (BASE / "scripts" / f"{script}.py").read_text()
        assert '"--apply"' in src, f"{script} has no --apply"


# ---- every script that can write names its database and says live out loud (review fix 3) ---------
# ⚠️ STATED OVER THE FOLDER, NOT OVER A LIST OF FOUR. The guard test above pins the four Round A
# passes by name. This one walks scripts/ and fails on the NEXT script that can write and has no
# guard, which is the only version of this check that survives the next script being added.
#
# Measured before the fix: 20 of 24 scripts could write and 13 of them hardcoded live recipes.db with
# no --db at all, including migrate.py, which is step one of the chain the repo's own README says to
# rehearse on a copy. archive_import_flags.py took --db with live as the DEFAULT, so `--apply` with
# no path went straight to the real database.

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
_WRITES = re.compile(r"\b(INSERT|UPDATE\s+\w|DELETE\s+FROM|CREATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE)\b",
                     re.IGNORECASE)

# Read-only by inspection, each for a stated reason. A script joins this set only when it cannot
# write, never because its guard is inconvenient.
READ_ONLY = {
    "cold_start_check.py":          "asserts a cold-started app served; opens no database",
    "plan_ahead_short_rests.py":    "report only, opens live with mode=ro",
    "plan_ahead_proposals_v3.py":   "reads the v2 CSV and writes a CSV; opens no database",
    "serve_live.py":                "serves the live database through the app, which has its own gates",
    "corpus_guard.py":              "it IS the guard",
}


def _script_sources():
    return sorted(p for p in SCRIPTS.glob("*.py") if p.name != "__init__.py")


def test_every_script_that_can_write_takes_the_shared_guard():
    missing = []
    for p in _script_sources():
        if p.name in READ_ONLY:
            continue
        src = p.read_text()
        if not _WRITES.search(src):
            continue
        if "refuse_live" not in src or "--i-mean-live" not in src:
            missing.append(p.name)
    assert missing == [], (
        "these scripts can write and do not wire scripts/corpus_guard.py: " + ", ".join(missing))


def test_every_script_that_can_write_can_be_pointed_at_a_copy():
    """⚠️ THE OTHER HALF, AND THE ONE THAT WAS WORSE. A guard with no --db leaves 'rehearse on a copy'
    impossible to follow: the only database the script can reach is the one it must not touch."""
    missing = []
    for p in _script_sources():
        if p.name in READ_ONLY:
            continue
        src = p.read_text()
        if not _WRITES.search(src):
            continue
        if not re.search(r'add_argument\(\s*"(?:--db|db)"', src):
            missing.append(p.name)
    assert missing == [], "these scripts can write and cannot be pointed at a copy: " + ", ".join(missing)


def test_migrate_takes_a_db_and_refuses_live_without_the_sentence():
    """migrate.py is step one of the chain docs/data-repairs/README.md says to rehearse on a copy."""
    src = (SCRIPTS.parent / "migrate.py").read_text()
    assert 'ap.add_argument("--db"' in src
    assert "--i-mean-live" in src
    assert "refuse_live(" in src
    assert "from corpus_guard import refuse_live" in src, "a fifth copy of the guard, not the guard"
    import migrate
    assert "db" in inspect.signature(migrate.migrate).parameters, \
        "migrate() must accept a path, or live_chain.sh has to rebind a module global to rehearse"


def test_no_spent_backfill_is_left_runnable_in_scripts():
    """A spent one-off names live with no --db and its work is already done, so running it again is
    risk with no upside. They are archived in scripts/applied/, not deleted, and they refuse."""
    archived = sorted(p.name for p in (SCRIPTS / "applied").glob("*.py") if p.name != "_spent.py")
    assert len(archived) == 16, f"the archive changed size: {len(archived)}"
    for name in archived:
        src = (SCRIPTS / "applied" / name).read_text()
        assert "refuse_spent(" in src, f"{name} is archived and would still run"
    # and none of them is still sitting in scripts/
    live_names = {p.name for p in _script_sources()}
    assert live_names.isdisjoint(archived), live_names & set(archived)


def test_an_archived_script_still_imports_so_its_tests_still_run():
    """⚠️ THE REFUSAL IS AT RUN TIME. Eight of the archived scripts carry a test file that imports
    the module to pin the transform it applied. An exit on import would delete that record as surely
    as deleting the file."""
    spec = importlib.util.spec_from_file_location(
        "spent_probe", SCRIPTS / "applied" / "backfill_qty_unit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)            # must not raise
    assert hasattr(mod, "DB")


def test_running_an_archived_script_refuses_with_a_nonzero_exit():
    out = subprocess.run([sys.executable, str(SCRIPTS / "applied" / "fix_junk_times.py")],
                         capture_output=True, text=True)
    assert out.returncode == 2, out
    assert "spent one-time backfill" in out.stderr
    assert "nulled the two stored times" in out.stderr


def test_a_dry_run_does_not_truncate_a_committed_record():
    """⚠️ FOUND BY DOING IT. Five scripts write their report CSV into docs/data-repairs/, which holds
    the record of what was done to the data, and they wrote it whether or not there was anything to
    report. Their work is applied, so a re-run finds 0 rows — and three committed records were
    truncated to their header lines at once, from DRY RUNS, during this review.

    Stated over the source rather than by running them, because running them is what did the damage.
    Each write site has to be reachable only when there is something to write."""
    writers = {
        "archive_import_flags.py": "rows",
        "relink_pass.py": "rows",
        "reparse_lines.py": "plan",
        "restore_notes.py": "rows",
        "restore_from_paprika.py": "rows",
    }
    for name, rowsvar in writers.items():
        src = (SCRIPTS / name).read_text()
        assert f"if not {rowsvar}:" in src, f"{name} writes its report with no emptiness check"
        assert "is left exactly as it is" in src, f"{name} does not say it left the record alone"
        # and the check comes BEFORE the open, not after it
        guard = src.index(f"if not {rowsvar}:")
        opened = src.index('"w", newline="", encoding="utf-8"')
        assert guard < opened, f"{name} opens the file before deciding whether to write it"
