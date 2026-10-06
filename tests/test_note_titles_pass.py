"""scripts/apply_note_titles.py, RUN, against the real schema.

⚠️ THE TEST HAS TO RUN THE SCRIPT. CLAUDE.md states it and the notes round proved it: four defects
in the sibling pass were found by hand because nothing executed a line of it. One was found here the
same way, by running this pass TWICE: applying a title DESTROYS the evidence the rule reads, because
the title comes off the front of the text, so a second run asked note_title_plan about a body with
no label in it, was told "no title", and refused all 27 titles on a database it had just written
correctly.

The baseline is built with the REAL serializer, which is what makes the byte-equal and lockstep
gates in these tests mean anything.
"""
import json
import pathlib
import sqlite3
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

import migrate                                                             # noqa: E402

TITLE_NOTE = "Flour. This recipe works best with flour with around 11% protein."
LABEL_NOTE = "Freezing – Freezes 100% perfectly! Cool the fries, then freeze on a tray."
WRAP_NOTE = "**Enriched Chicken and Pork Broth**\nSubstitute 2 pounds pork necks."
BARE_WRAP = "**Sui mi ya cai**"
BODY_NOTE = "Sui mi ya cai is a preserved vegetable from Sichuan. Use it within two weeks."


def _kitchen(tmp_path):
    """One recipe with four note rows at known ids, a wrapped ingredient heading, and a baseline
    the real serializer produced, so the recipe starts byte-equal to its own origin."""
    import app
    import models

    db = tmp_path / "titles.db"
    migrate.DB = db
    migrate.migrate(verbose=False)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO users (id, email, password_hash, is_admin, created_at) "
              "VALUES (1, 'x@example.com', 'x', 1, '2026-01-01T00:00:00Z')")
    c.execute("INSERT INTO recipes (id, name, source) VALUES ('rolls', 'Rolls', 'app')")
    c.execute("INSERT INTO recipe_steps (recipe_id, position, is_heading, heading_level, text) "
              "VALUES ('rolls', 0, 0, 1, 'Mix the dough.')")
    c.execute("INSERT INTO recipe_ingredients (id, recipe_id, position, is_heading, raw_text) "
              "VALUES (9213, 'rolls', 0, 1, '_Cinnamon Filling_')")
    for nid, pos, text in ((27, 0, TITLE_NOTE), (70, 1, LABEL_NOTE),
                           (64, 2, BARE_WRAP), (65, 3, BODY_NOTE)):
        c.execute("INSERT INTO recipe_notes (id, recipe_id, position, kind, text) "
                  "VALUES (?, 'rolls', ?, 'notes', ?)", (nid, pos, text))
    c.commit()
    c.close()

    app.DB = models.DB = db
    with app.orm_session() as s:
        blob = app.serialize_recipe_content(s, "rolls")
    with sqlite3.connect(db) as c2:
        c2.execute("INSERT INTO recipe_snapshots (recipe_id, user_id, reason, content, created_at) "
                   "VALUES ('rolls', 1, 'original', ?, '2026-01-01T00:00:00Z')", (blob,))
    return db


def _files(monkeypatch, tmp_path, title_rows, mark_rows=(), mark_text=""):
    """Two decision files in the committed shape, pointed at by the pass.

    ⚠️ THROUGH monkeypatch, not by assignment. Setting the module globals directly leaked the temp
    paths into the next test, which then read an empty file and failed for a reason of this
    helper's making."""
    import apply_note_titles as pass_
    t = tmp_path / "titles.csv"
    m = tmp_path / "marks.csv"
    t.write_text("recipe,note_id,separator,candidate_title,rule_verdict,rule_reason,"
                 "text_after_the_label,suggested_kind,DECISION,REASON\n"
                 + "".join(f"rolls,{nid},,{cand},title,,,,{dec},because\n"
                           for nid, cand, dec in title_rows))
    m.write_text("recipe,where,id,field,marks,classification,text,proposed_fix,DECISION,REASON\n"
                 + "".join(f"rolls,{where},{rid},,,,{mark_text},,{dec},because\n"
                           for where, rid, dec in mark_rows))
    monkeypatch.setattr(pass_, "TITLES_CSV", t)
    monkeypatch.setattr(pass_, "MARKS_CSV", m)
    return pass_


def _rows(db, sql, args=()):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    out = [dict(r) for r in c.execute(sql, args)]
    c.close()
    return out


def _marks_on(db, rid="rolls"):
    import app
    import models
    app.DB = models.DB = db
    with app.orm_session() as s:
        return app._recipe_annotations(s, rid)


# ---- the DECISION column is the input, and it is read strictly -----------------------------------

@pytest.mark.parametrize("decision,why", [
    ("", "empty"),
    ("   ", "empty"),
    ("maybe", "vocabulary"),
    ("title; ", "empty part"),
    ("title:", "gives none"),
    ("strip; probably", "vocabulary"),
])
def test_a_decision_it_cannot_read_stops_the_run(decision, why):
    """⚠️ A ROW IT SKIPPED WOULD BE A SILENT SUBSET APPLIED AND REPORTED AS SUCCESS."""
    import apply_note_titles as pass_
    with pytest.raises(pass_.BadDecision) as e:
        pass_.parse_decision(decision)
    assert why in str(e.value)


@pytest.mark.parametrize("decision,want", [
    ("title", ({"title"}, None, None)),
    ("title: Dashi", ({"title"}, "Dashi", None)),
    ("title; kind=storage", ({"title"}, None, "storage")),
    ("label; kind=storage", ({"label"}, None, "storage")),
    ("strip; title: Buying", ({"strip", "title"}, "Buying", None)),
    ("strip; merge-title-into-next", ({"strip", "merge-title-into-next"}, None, None)),
    ("no", ({"no"}, None, None)),
    ("keep", ({"keep"}, None, None)),
    ("derived", ({"derived"}, None, None)),
])
def test_the_whole_vocabulary_parses(decision, want):
    import apply_note_titles as pass_
    verbs, title, kind, _flag = pass_.parse_decision(decision)
    assert (verbs, title, kind) == want


def test_the_committed_decision_files_parse_and_carry_every_row():
    """⚠️ A CHECK THAT READ NOTHING FAILS. These are the files the real run reads, and a blank
    DECISION in either would make every comparison below pass on an empty set."""
    import apply_note_titles as pass_
    rows = pass_.read_decisions()
    assert len(rows) == 57, f"{len(rows)} rows across the two files, expected 57"
    assert sum(1 for r in rows if r["file"].startswith("note-titles")) == 27
    assert sum(1 for r in rows if r["file"].startswith("emphasis-marks")) == 30
    assert all(r["verbs"] for r in rows)
    # the four shapes the round actually takes, counted so a file edited by hand is noticed
    kinds = {"title": 0, "label": 0, "no": 0, "strip": 0, "keep": 0, "derived": 0,
             "merge-title-into-next": 0}
    for r in rows:
        for v in r["verbs"]:
            kinds[v] += 1
    assert kinds["title"] == 27, kinds
    assert kinds["label"] == 2, kinds
    assert kinds["no"] == 3, kinds
    assert kinds["merge-title-into-next"] == 1, kinds
    assert kinds["derived"] == 7, kinds


# ---- the write half ------------------------------------------------------------------------------

def test_the_pass_writes_every_shape_and_mints_no_mark(monkeypatch, tmp_path):
    db = _kitchen(tmp_path)
    assert _marks_on(db) == [], "the fixture did not start byte-equal to its baseline"
    pass_ = _files(monkeypatch, tmp_path, [(27, "Flour", "title"), (70, "Freezing", "label; kind=storage")],
                   [("note", 64, "strip; merge-title-into-next"),
                    ("ingredient heading", 9213, "strip")])
    pass_.run(str(db), apply=True)

    notes = {r["id"]: r for r in _rows(
        db, "SELECT id, position, kind, title, text FROM recipe_notes ORDER BY position")}

    # a title comes off the front of the text, or it prints twice
    assert notes[27]["title"] == "Flour"
    assert notes[27]["text"] == "This recipe works best with flour with around 11% protein."

    # a known label sets the kind and keeps the author's words, label and all
    assert notes[70]["kind"] == "storage"
    assert notes[70]["title"] is None
    assert notes[70]["text"] == LABEL_NOTE, "not one character of a label note moves"

    # the merge: the title lands on the next row, this one goes, and the gap closes
    assert 64 not in notes
    assert notes[65]["title"] == "Sui mi ya cai"
    assert [r["position"] for r in sorted(notes.values(), key=lambda r: r["position"])] == [0, 1, 2]

    # and no mark was minted by any of it
    assert _marks_on(db) == [], "a machine repair minted a mark"


def test_an_ingredient_heading_strips_in_lockstep_with_its_baseline(monkeypatch, tmp_path):
    """⚠️ THE ONE PART OF THIS ROUND THAT IS BASELINE CONTENT. recipe_ingredients.raw_text is in
    recipe_snapshots.content, so the row and the entry move in one transaction or the cook is told
    they edited an ingredient heading they never touched."""
    db = _kitchen(tmp_path)
    pass_ = _files(monkeypatch, tmp_path, [], [("ingredient heading", 9213, "strip")])
    pass_.run(str(db), apply=True)

    assert _rows(db, "SELECT raw_text FROM recipe_ingredients WHERE id=9213")[0]["raw_text"] == (
        "Cinnamon Filling")
    doc = json.loads(_rows(db, "SELECT content FROM recipe_snapshots WHERE reason='original'")[0]
                     ["content"])
    entry = next(e for e in doc["ingredients"] if e["id"] == 9213)
    assert entry["raw_text"] == "Cinnamon Filling"
    assert _marks_on(db) == [], "the strip minted a mark, so the baseline did not move with it"


def test_a_dry_run_writes_nothing(monkeypatch, tmp_path):
    db = _kitchen(tmp_path)
    pass_ = _files(monkeypatch, tmp_path, [(27, "Flour", "title")], [("ingredient heading", 9213, "strip")])
    before = _rows(db, "SELECT id, title, text FROM recipe_notes ORDER BY id")
    pass_.run(str(db), apply=False)
    assert _rows(db, "SELECT id, title, text FROM recipe_notes ORDER BY id") == before
    assert _rows(db, "SELECT raw_text FROM recipe_ingredients WHERE id=9213")[0]["raw_text"] == (
        "_Cinnamon Filling_")


def test_a_second_run_is_a_no_op(monkeypatch, tmp_path):
    """⚠️ THE DEFECT THIS FILE FOUND. Applying a title removes the label the rule reads, so the
    second run's planning phase has to recognise its own work rather than re-deriving it. Before
    the fix this refused every title and exited non-zero on a database it had written correctly."""
    db = _kitchen(tmp_path)
    pass_ = _files(monkeypatch, tmp_path, [(27, "Flour", "title"), (70, "Freezing", "label; kind=storage")],
                   [("note", 64, "strip; merge-title-into-next"),
                    ("ingredient heading", 9213, "strip")])
    pass_.run(str(db), apply=True)
    after = _rows(db, "SELECT id, position, kind, title, text FROM recipe_notes ORDER BY id")

    todo = pass_.run(str(db), apply=True)
    assert todo == [], "the second run found work to do"
    assert _rows(db, "SELECT id, position, kind, title, text FROM recipe_notes ORDER BY id") == after


# ---- what it refuses -----------------------------------------------------------------------------

def test_a_row_whose_text_has_moved_is_refused_and_nothing_is_written(monkeypatch, tmp_path):
    """The decision was made about a sentence, not about a row id."""
    db = _kitchen(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE recipe_notes SET text='Something else entirely now.' WHERE id=27")
    pass_ = _files(monkeypatch, tmp_path, [(27, "Flour", "title"), (70, "Freezing", "label; kind=storage")])
    with pytest.raises(SystemExit) as e:
        pass_.run(str(db), apply=True)
    assert "no longer matches" in str(e.value)
    # and the row the pass COULD have written is untouched, because the abort is before any write
    assert _rows(db, "SELECT kind FROM recipe_notes WHERE id=70")[0]["kind"] == "notes"


def test_a_row_on_another_recipe_is_refused(monkeypatch, tmp_path):
    db = _kitchen(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO recipes (id, name, source) VALUES ('other', 'Other', 'app')")
        c.execute("UPDATE recipe_notes SET recipe_id='other' WHERE id=27")
    pass_ = _files(monkeypatch, tmp_path, [(27, "Flour", "title")])
    with pytest.raises(SystemExit):
        pass_.run(str(db), apply=True)


def test_a_merge_onto_a_row_that_already_has_a_title_is_refused(monkeypatch, tmp_path):
    db = _kitchen(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE recipe_notes SET title='Already named' WHERE id=65")
    pass_ = _files(monkeypatch, tmp_path, [], [("note", 64, "strip; merge-title-into-next")])
    with pytest.raises(SystemExit):
        pass_.run(str(db), apply=True)
    assert _rows(db, "SELECT COUNT(*) c FROM recipe_notes WHERE id=64")[0]["c"] == 1, \
        "the row was deleted despite the refusal"


def test_a_missing_row_is_refused_rather_than_skipped(monkeypatch, tmp_path):
    db = _kitchen(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute("DELETE FROM recipe_notes WHERE id=27")
    pass_ = _files(monkeypatch, tmp_path, [(27, "Flour", "title")])
    with pytest.raises(SystemExit):
        pass_.run(str(db), apply=True)


# ---- what it leaves alone, which the brief states explicitly -------------------------------------

def test_the_authors_words_and_the_retired_column_are_not_touched(monkeypatch, tmp_path):
    """recipe_notes_original is the only record of the author's own words, and recipes.notes is a
    derived copy whose 7 marks Andy decided as `derived`. A playground is only safe if there is a
    way back."""
    db = _kitchen(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE recipes SET notes=? WHERE id='rolls'", (TITLE_NOTE,))
        for nid, pos, text in ((27, 0, TITLE_NOTE), (70, 1, LABEL_NOTE)):
            c.execute("INSERT INTO recipe_notes_original (recipe_id, position, kind, text, "
                      "recorded_at) VALUES ('rolls', ?, 'notes', ?, '2026-01-01T00:00:00Z')",
                      (pos, text))
    before_orig = _rows(db, "SELECT * FROM recipe_notes_original ORDER BY position")
    before_col = _rows(db, "SELECT notes FROM recipes WHERE id='rolls'")

    pass_ = _files(monkeypatch, tmp_path, [(27, "Flour", "title"), (70, "Freezing", "label; kind=storage")])
    pass_.run(str(db), apply=True)

    assert _rows(db, "SELECT * FROM recipe_notes_original ORDER BY position") == before_orig
    assert _rows(db, "SELECT notes FROM recipes WHERE id='rolls'") == before_col


def test_a_keep_or_derived_row_is_named_and_not_written(monkeypatch, tmp_path):
    db = _kitchen(tmp_path)
    pass_ = _files(monkeypatch, tmp_path, [], [("note", 62, "keep"), ("recipe notes", 1, "derived")])
    todo = pass_.run(str(db), apply=True)
    assert todo == []


# ---- the round file declares exactly what the pass does ------------------------------------------

def test_the_round_file_names_the_rows_the_decision_files_do():
    """⚠️ NOTHING ELSE TIES THE DECLARATION TO THE PASS. A round file is checked by the gate against
    a before and an after reading, so a declaration that names the wrong tables fails late, on live.
    The recipe_notes count moves by exactly the one row the merge deletes."""
    spec = json.loads((BASE / "golive" / "rounds" / "2026-10-06-note-titles.json").read_text())
    import apply_note_titles as pass_
    rows = pass_.read_decisions()
    merges = [r for r in rows if "merge-title-into-next" in r["verbs"]]
    before, after = spec["counts"]["recipe_notes"]
    assert before - after == len(merges) == 1
    assert spec["short_circuit"] == "unchanged"
    assert spec["annotations"] == "unchanged"
    assert set(spec["tables"]["except"]) == {
        "schema_migrations", "recipe_notes", "recipe_ingredients", "recipe_snapshots"}
    assert spec["counts"]["migrations"] == [61, 62]


# ---- what a fresh review found -------------------------------------------------------------------

def test_a_place_the_pass_does_not_know_is_refused(monkeypatch, tmp_path):
    """⚠️ IT READ `where` AS NOTE-OR-NOT, so the marks CSV's three `step` rows were read as
    recipe_ingredients ids and were safe only because all three are `keep`. Step ids and ingredient
    ids overlap in live's ranges, so one added or mistyped `strip` on a step row edited an unrelated
    ingredient line. Demonstrated in review: a `step,3650,strip` row rewrote ingredient 3650."""
    db = _kitchen(tmp_path)
    pass_ = _files(monkeypatch, tmp_path, [], [("step", 9213, "strip")])
    with pytest.raises(SystemExit):
        pass_.run(str(db), apply=True)
    assert _rows(db, "SELECT raw_text FROM recipe_ingredients WHERE id=9213")[0]["raw_text"] == (
        "_Cinnamon Filling_"), "a step row's decision reached an ingredient"

    bad = _files(monkeypatch, tmp_path, [], [("somewhere else", 9213, "strip")])
    with pytest.raises(SystemExit):
        bad.run(str(db), apply=True)


def test_an_ingredient_row_whose_text_has_moved_is_refused(monkeypatch, tmp_path):
    """⚠️ THE ONLY BASELINE CONTENT THE ROUND WRITES, AND IT HAD NO STALE CHECK. The note branch
    refuses a row whose words have moved and this one did not: the guard it had was an `if` with two
    identical arms. The marks CSV already carries a `text` column holding what the decision was made
    about, and nothing read it."""
    db = _kitchen(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE recipe_ingredients SET raw_text='_Something Else Entirely_' WHERE id=9213")
    pass_ = _files(monkeypatch, tmp_path, [], [("ingredient heading", 9213, "strip")],
                   mark_text="_Cinnamon Filling_")
    with pytest.raises(SystemExit) as e:
        pass_.run(str(db), apply=True)
    assert "no longer matches" in str(e.value)
    assert _rows(db, "SELECT raw_text FROM recipe_ingredients WHERE id=9213")[0]["raw_text"] == (
        "_Something Else Entirely_"), "it wrote anyway"


def test_a_merge_onto_a_row_another_merge_deletes_is_refused(monkeypatch, tmp_path):
    """⚠️ "Alpha" DISAPPEARED AND NOTHING COMPLAINED. Three notes with merges on the first two:
    "Alpha" went onto note 2, and note 2 was then deleted by its own merge, so the title went with
    it. nxt is read off the PRE-RUN snapshot, which cannot see what a sibling decision will do, and
    the gate cannot see it either because notes are outside the baseline."""
    db = _kitchen(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute("DELETE FROM recipe_notes")
        for nid, pos, text in ((1, 0, "**Alpha**"), (2, 1, "**Beta**"), (3, 2, BODY_NOTE)):
            c.execute("INSERT INTO recipe_notes (id, recipe_id, position, kind, text) "
                      "VALUES (?, 'rolls', ?, 'notes', ?)", (nid, pos, text))
    pass_ = _files(monkeypatch, tmp_path, [],
                   [("note", 1, "strip; merge-title-into-next"),
                    ("note", 2, "strip; merge-title-into-next")])
    with pytest.raises(SystemExit) as e:
        pass_.run(str(db), apply=True)
    assert "no longer matches" in str(e.value), "the abort is the shared refusal message"
    assert _rows(db, "SELECT COUNT(*) c FROM recipe_notes")[0]["c"] == 3, "it deleted a row anyway"
    assert _rows(db, "SELECT title FROM recipe_notes WHERE id=2")[0]["title"] is None


def test_a_flag_in_a_decision_is_reported_rather_than_parsed_and_dropped(monkeypatch, tmp_path,
                                                                         capsys):
    """⚠️ `flag <name>` WAS PARSED AND READ BY NOTHING, so the one row carrying it recorded nothing
    anywhere. A decision that says "come back to this" only means something if the run says so."""
    db = _kitchen(tmp_path)
    pass_ = _files(monkeypatch, tmp_path, [], [("step", 3651, "keep; flag split-footnote")])
    pass_.run(str(db), apply=False)
    out = capsys.readouterr().out
    assert "flagged for a later round : 1" in out, out
    assert "split-footnote" in out, out
