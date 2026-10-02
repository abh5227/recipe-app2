"""The three notes passes, RUN, against the real schema.

⚠️ WHY THIS FILE EXISTS. notes_to_rows moved 177 note rows over 95 recipes and apply_note_decisions
writes the recorded links, and nothing in the suite executed a line of either. CLAUDE.md states the
rule the other way round for a reason: "The test that catches this class has to RUN the scripts."
Four defects were found by hand in one review sitting, every one of them invisible to a test that
reads the source:

  - apply_note_decisions REBUILT the baseline from current content, so a recipe carrying a real cook
    edit came out of the pass with that edit absorbed and its mark gone. 20 recipes carry 49 entries.
  - both passes committed each recipe and THEN checked the gate, so an abort was a verdict on data
    already on disk.
  - a second --apply died on an IntegrityError part way through, with earlier recipes committed and a
    dry run that had shown nothing wrong.
  - scan_notes_for_waits read one COUNT over the whole table and applied the answer to every recipe.

The baseline here is built with the REAL serializer rather than by hand, which is what makes the
byte-equal and lockstep gates mean anything in these tests.
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

NOTES = "Soak the beans overnight, at least 8 hours.\n\nTip: see step 2 before you start."


def _kitchen(tmp_path, notes=NOTES, name="beans"):
    """A database on the real schema, one recipe with notes in the COLUMN, and a baseline the real
    serializer produced, so the recipe starts byte-equal to its own origin."""
    import app
    import models

    db = tmp_path / "notes.db"
    migrate.DB = db
    migrate.migrate(verbose=False)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO users (id, email, password_hash, is_admin, created_at) "
              "VALUES (1, 'x@example.com', 'x', 1, '2026-01-01T00:00:00Z')")
    c.execute("INSERT INTO recipes (id, name, source, notes) VALUES (?,?, 'app', ?)",
              (name, name.title(), notes))
    for i, text in enumerate(("Rinse the beans.", "Simmer until tender.")):
        c.execute("INSERT INTO recipe_steps (recipe_id, position, is_heading, heading_level, text) "
                  "VALUES (?,?,0,1,?)", (name, i, text))
    c.commit()
    c.close()

    # ⚠️ THE BASELINE COMES FROM THE REAL SERIALIZER. Hand-building it would leave the recipe not
    #    byte-equal to its own origin, and the byte-equal and lockstep gates these tests exist to
    #    exercise would then pass whatever the passes did.
    app.DB = models.DB = db
    with app.orm_session() as s:
        blob = app.serialize_recipe_content(s, name)
    with sqlite3.connect(db) as c2:
        c2.execute("INSERT INTO recipe_snapshots (recipe_id, user_id, reason, content, created_at) "
                   "VALUES (?, 1, 'original', ?, '2026-01-01T00:00:00Z')", (name, blob))
    return db


def _rows(db, sql, args=()):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    out = [dict(r) for r in c.execute(sql, args)]
    c.close()
    return out


def _marks(db, rid="beans"):
    import app
    import models
    app.DB = models.DB = db
    with app.orm_session() as s:
        return app._recipe_annotations(s, rid)


# ---- notes_to_rows ------------------------------------------------------------------------------

def test_the_notes_move_into_rows_in_lockstep_and_mint_no_mark(tmp_path):
    import notes_to_rows

    db = _kitchen(tmp_path)
    assert _marks(db) == [], "the fixture did not start byte-equal to its baseline"

    notes_to_rows.run(str(db), apply=True)

    rows = _rows(db, "SELECT position, kind, text FROM recipe_notes ORDER BY position")
    assert [r["kind"] for r in rows] == ["notes", "tips"]
    assert rows[0]["text"].startswith("Soak the beans")
    # the derived column and the baseline moved with them, so the page shows nothing new
    assert _marks(db) == [], "a machine repair minted a mark"
    doc = json.loads(_rows(db, "SELECT content FROM recipe_snapshots WHERE reason='original'")[0]
                     ["content"])
    assert [n["text"] for n in doc["notes"]] == [r["text"] for r in rows]


def test_a_second_run_moves_nothing(tmp_path):
    import notes_to_rows

    db = _kitchen(tmp_path)
    notes_to_rows.run(str(db), apply=True)
    before = _rows(db, "SELECT id, text FROM recipe_notes ORDER BY id")
    notes_to_rows.run(str(db), apply=True)
    assert _rows(db, "SELECT id, text FROM recipe_notes ORDER BY id") == before


def test_a_run_that_would_move_a_mark_writes_nothing_at_all(tmp_path):
    """⚠️ THE GATE RUNS BEFORE THE COMMIT. It ran after every recipe had committed, so an abort was
    a verdict on data already on disk: the rows were written, the baseline was half moved, and the
    message read as though nothing had happened. On a 95-recipe pass that is a restore from backup.

    The recipe here carries a note in its BASELINE that its rows do not have, which is a real
    annotation the cook can see. Moving the notes into rows would make that mark disappear, so the
    pass must refuse the recipe and leave it exactly as it found it."""
    import notes_to_rows

    db = _kitchen(tmp_path)
    doc = json.loads(_rows(db, "SELECT content FROM recipe_snapshots WHERE reason='original'")[0]
                     ["content"])
    doc["notes"] = [{"id": 999, "position": 0, "kind": "notes", "text": "a note the cook deleted",
                     "step_id": None, "ingredient_row_id": None}]
    with sqlite3.connect(db) as c:
        c.execute("UPDATE recipe_snapshots SET content=? WHERE reason='original'",
                  (json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")),))
    before = _marks(db)
    assert len(before) == 1, f"the fixture does not carry the mark this test is about: {before}"

    with pytest.raises(SystemExit) as e:
        notes_to_rows.run(str(db), apply=True)
    assert "annotation set" in str(e.value) or "byte-equal" in str(e.value)
    assert _rows(db, "SELECT * FROM recipe_notes") == [], "the abort left rows behind"
    assert _rows(db, "SELECT notes FROM recipes")[0]["notes"] == NOTES, "the column was rewritten"
    assert _marks(db) == before, "the cook's mark moved"


# ---- apply_note_decisions ----------------------------------------------------------------------

def _decisions(tmp_path, monkeypatch, **kw):
    """Point the pass at a decision file describing THIS fixture instead of the committed one."""
    import apply_note_decisions

    plan = {"step_links": [], "step_references": [], "waits": [], "flagged_references": []}
    plan.update(kw)
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps(plan))
    monkeypatch.setattr(apply_note_decisions, "DECISIONS", path)
    return apply_note_decisions


def test_a_recorded_link_is_applied_in_lockstep(tmp_path, monkeypatch):
    import notes_to_rows

    db = _kitchen(tmp_path)
    notes_to_rows.run(str(db), apply=True)
    step = _rows(db, "SELECT id FROM recipe_steps ORDER BY position")[1]["id"]
    mod = _decisions(tmp_path, monkeypatch, step_links=[
        {"recipe_id": "beans", "note_position": 0, "text_fragment": "Soak the beans",
         "step_id": step}])

    mod.run(str(db), apply=True)

    assert _rows(db, "SELECT step_id FROM recipe_notes ORDER BY position")[0]["step_id"] == step
    assert _marks(db) == [], "a recorded decision minted a mark"


def test_a_second_apply_is_a_no_op_and_not_an_integrity_error(tmp_path, monkeypatch):
    """⚠️ BOTH WRITES WERE BARE INSERTS. Re-running the pass on an applied database died on
    UNIQUE (note_id, ref_index) with earlier recipes already committed, and the dry run before it
    reported every decision as pending."""
    import notes_to_rows

    db = _kitchen(tmp_path)
    notes_to_rows.run(str(db), apply=True)
    step = _rows(db, "SELECT id FROM recipe_steps ORDER BY position")[0]["id"]
    mod = _decisions(tmp_path, monkeypatch,
                     step_references=[{"recipe_id": "beans", "note_position": 1,
                                       "text_fragment": "see step 2", "ref_index": 0,
                                       "step_id": step}],
                     waits=[{"recipe_id": "beans", "position": 0, "kind": "soaking",
                             "label": "soak 8 hr", "min_minutes": 480, "max_minutes": 480,
                             "ext_label": None, "ext_min_minutes": None, "ext_max_minutes": None,
                             "when_kind": "always", "when_label": None, "step_id": step}])

    mod.run(str(db), apply=True)
    first = (_rows(db, "SELECT note_id, ref_index, step_id FROM recipe_note_step_refs"),
             _rows(db, "SELECT label, position FROM recipe_waits"))
    assert first[0] and first[1]

    todo = mod.run(str(db), apply=True)      # must not raise, and must write nothing new
    assert todo == []
    assert (_rows(db, "SELECT note_id, ref_index, step_id FROM recipe_note_step_refs"),
            _rows(db, "SELECT label, position FROM recipe_waits")) == first


def test_a_cooks_own_edit_survives_the_pass(tmp_path, monkeypatch):
    """⚠️ THE BASELINE IS PATCHED SURGICALLY, NEVER REBUILT. The pass rewrote the whole baseline
    from current content, which declares the recipe born in its edited state: a recipe with one real
    cook edit came out of it with 0 marks and the cook's words sitting in the baseline as though
    they had always been there."""
    import notes_to_rows

    db = _kitchen(tmp_path)
    notes_to_rows.run(str(db), apply=True)
    # a cook rewords a step, which is a real annotation and nothing to do with this pass
    with sqlite3.connect(db) as c:
        c.execute("UPDATE recipe_steps SET text='Rinse the beans well.' WHERE position=0 "
                  "AND recipe_id='beans'")
    before = _marks(db)
    assert len(before) == 1, before

    step = _rows(db, "SELECT id FROM recipe_steps ORDER BY position")[1]["id"]
    mod = _decisions(tmp_path, monkeypatch, step_links=[
        {"recipe_id": "beans", "note_position": 0, "text_fragment": "Soak the beans",
         "step_id": step}])
    mod.run(str(db), apply=True)

    assert _marks(db) == before, "the pass changed what the page says the cook edited"
    doc = json.loads(_rows(db, "SELECT content FROM recipe_snapshots WHERE reason='original'")[0]
                     ["content"])
    assert "Rinse the beans well." not in json.dumps(doc), \
        "the cook's words were absorbed into the baseline"


def test_a_decision_that_no_longer_matches_stops_the_pass(tmp_path, monkeypatch):
    import notes_to_rows

    db = _kitchen(tmp_path)
    notes_to_rows.run(str(db), apply=True)
    mod = _decisions(tmp_path, monkeypatch, step_links=[
        {"recipe_id": "beans", "note_position": 0, "text_fragment": "a sentence nobody wrote",
         "step_id": 1}])
    with pytest.raises(SystemExit) as e:
        mod.run(str(db), apply=True)
    assert "no longer matches" in str(e.value)


# ---- scan_notes_for_waits ----------------------------------------------------------------------

def test_the_survey_reads_the_column_for_a_recipe_that_has_no_rows_yet(tmp_path):
    """⚠️ DECIDED PER RECIPE, NOT ONCE FOR THE CORPUS. It read one COUNT over recipe_notes and
    applied the answer to all 300, so the moment any recipe had rows a recipe whose notes are still
    only in the column was scanned as empty. That is the state every imported recipe is in."""
    import notes_to_rows
    import scan_notes_for_waits

    db = _kitchen(tmp_path)
    notes_to_rows.run(str(db), apply=True)          # 'beans' now has rows
    with sqlite3.connect(db) as c:                   # a second recipe with notes in the column only
        c.execute("INSERT INTO recipes (id, name, source, notes) VALUES "
                  "('late', 'Late', 'app', 'Soak the chickpeas overnight, at least 10 hours.')")

    rows = scan_notes_for_waits.run(str(db))
    assert any(r["recipe_id"] == "late" for r in rows), \
        f"the column-only recipe was skipped: {[r['recipe_id'] for r in rows]}"


def test_the_survey_writes_nothing_to_the_recipe_data(tmp_path):
    import scan_notes_for_waits

    db = _kitchen(tmp_path)
    before = _rows(db, "SELECT * FROM recipes") + _rows(db, "SELECT * FROM recipe_waits")
    scan_notes_for_waits.run(str(db))
    assert _rows(db, "SELECT * FROM recipes") + _rows(db, "SELECT * FROM recipe_waits") == before
