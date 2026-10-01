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
import json
import pathlib
import sqlite3
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
def test_a_corpus_pass_refuses_live_without_being_told(script, tmp_path, monkeypatch):
    """All four name their database, and none of them takes live as a typo.

    ⚠️ Three of these had no guard at all. apply_plan_ahead_proposals has carried one since round 3
    and the other three would have written to live recipes.db from a mistyped path with --apply and
    no further word. A live run is now a sentence a person had to type.
    """
    import importlib

    mod = importlib.import_module(script)
    live = str(BASE / "recipes.db")
    with pytest.raises(SystemExit) as e:
        if script == "apply_plan_ahead_proposals":
            monkeypatch.setattr("sys.argv", [script, live])
        else:
            monkeypatch.setattr("sys.argv", [script, live, "--apply"])
        mod.main()
    assert "--i-mean-live" in str(e.value)
