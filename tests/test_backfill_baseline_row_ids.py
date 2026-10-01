"""scripts/applied/backfill_baseline_row_ids.py — the one-off that gave all 300 reason='original' baselines
their row ids (option C, commit 3).

The rehearsal on a copy of live is the real proof and it is recorded in docs/data-repairs/. These
tests pin the DECISIONS the script makes, so the tiers stay auditable and the abort stays armed:
which rows it may bind, which it must leave null, and that it refuses to write at all if stripping
the ids back out does not reproduce the stored baseline byte for byte.
"""
import json
import sqlite3

import pytest

from scripts.applied import backfill_baseline_row_ids as bf
from snapshot_serialize import SNAPSHOT_ING_FIELDS, content_blob

RECIPE = {k: None for k in (
    "name", "author", "source_url", "category", "servings", "prep_time",
    "cook_time", "total_time", "descr", "notes", "image")}
RECIPE["name"] = "Test"

ING_COLS = ("qty", "quantity", "unit", "ingredient_id", "label", "note", "raw_text",
            "grams", "secondary_measure")


def ing(pos, **kw):
    row = {k: None for k in SNAPSHOT_ING_FIELDS}
    row["position"], row["is_heading"] = pos, 1 if kw.get("heading") else 0
    if kw.get("heading"):
        row["raw_text"] = kw["heading"]
    else:
        row["label"], row["qty"] = kw.get("label"), kw.get("qty")
        row["raw_text"] = kw.get("raw_text", f"{kw.get('qty') or ''} {kw.get('label') or ''}".strip())
        row["note"], row["ingredient_id"] = kw.get("note"), kw.get("ingredient_id")
    return row


def step(pos, text, heading=False):
    return {"id": None, "position": pos, "is_heading": 1 if heading else 0, "text": text}


@pytest.fixture
def db(tmp_path):
    """A two-table stand-in: the columns the script reads, and a baseline written the pre-commit-3
    way (no id keys at all), which is exactly the shape live's 300 were in."""
    path = tmp_path / "t.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE recipe_snapshots (id INTEGER PRIMARY KEY, recipe_id TEXT, "
              "reason TEXT, content TEXT)")
    c.execute(f"CREATE TABLE recipe_ingredients (id INTEGER PRIMARY KEY, recipe_id TEXT, "
              f"position INT, is_heading INT, {', '.join(ING_COLS)})")
    c.execute("CREATE TABLE recipe_steps (id INTEGER PRIMARY KEY, recipe_id TEXT, position INT, "
              "is_heading INT, text TEXT)")
    c.commit()
    return path


def _write(db, rid, baseline_ing, baseline_steps, live_ing, live_steps, reason="original"):
    blob = json.loads(content_blob(RECIPE, baseline_ing, baseline_steps))
    for row in blob["ingredients"] + blob["steps"]:
        del row["id"]                                  # the stored shape: no id key at all
    c = sqlite3.connect(db)
    c.execute("INSERT INTO recipe_snapshots (recipe_id, reason, content) VALUES (?,?,?)",
              (rid, reason, json.dumps(blob, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":"))))
    for i, r in enumerate(live_ing):
        c.execute(f"INSERT INTO recipe_ingredients (id, recipe_id, position, is_heading,"
                  f"{','.join(ING_COLS)}) VALUES (?,?,?,?,{','.join('?' * len(ING_COLS))})",
                  [r.get("_id", 100 + i), rid, r["position"], r["is_heading"]]
                  + [r.get(k) for k in ING_COLS])
    for i, r in enumerate(live_steps):
        c.execute("INSERT INTO recipe_steps (id, recipe_id, position, is_heading, text) "
                  "VALUES (?,?,?,?,?)",
                  (r.get("_id", 200 + i), rid, r["position"], r["is_heading"], r["text"]))
    c.commit()
    return blob


def _baseline(db, rid):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return json.loads(c.execute("SELECT content FROM recipe_snapshots WHERE recipe_id=?",
                                (rid,)).fetchone()["content"])


def test_an_unchanged_recipe_gets_every_id_on_the_exact_tier(db, tmp_path):
    rows = [ing(0, heading="SAUCE"), ing(1, qty="2 tbsp", label="oil"), ing(2, qty="1 cup", label="water")]
    tally = bf.run(str(db), apply=True, csv_out=tmp_path / "a.csv") if _write(
        db, "dish", rows, [step(0, "Mix.")], rows, [step(0, "Mix.")]) else None
    assert tally["ingredient"]["exact"] == 3 and tally["step"]["exact"] == 1
    assert [r["id"] for r in _baseline(db, "dish")["ingredients"]] == [100, 101, 102]
    assert [r["id"] for r in _baseline(db, "dish")["steps"]] == [200]


def test_two_identical_rows_pair_in_order(db, tmp_path):
    """⚠️ CONSUME-ONCE IS WHAT MAKES A DUPLICATE SAFE. brioche-bread lists every ingredient twice, so
    'unique exact' is not available for 52 of live's rows. They pair in list order and neither row is
    bound twice, which is the only answer available without inventing a distinction."""
    rows = [ing(0, qty="1 tsp", label="salt"), ing(1, qty="1 tsp", label="salt")]
    tally = bf.run(str(db), apply=True, csv_out=tmp_path / "a.csv") if _write(
        db, "dish", rows, [], rows, []) else None
    assert tally["ingredient"]["exact-dup"] == 2 and tally["ingredient"]["exact"] == 0
    assert [r["id"] for r in _baseline(db, "dish")["ingredients"]] == [100, 101]


def test_a_cleared_library_link_does_not_block_the_match(db, tmp_path):
    """Migration 046 deleted all 36 library ingredients, so live holds 0 rows with an ingredient_id
    while 46 baseline rows still name one. The pointer is always to a row that no longer exists, and
    the diff never compares the column, so it is not evidence of a different row."""
    base = [ing(0, qty="2 tbsp", label="oil", ingredient_id="olive_oil")]
    live = [ing(0, qty="2 tbsp", label="oil")]
    tally = bf.run(str(db), apply=True, csv_out=tmp_path / "a.csv") if _write(
        db, "dish", base, [], live, []) else None
    assert tally["ingredient"]["quirk"] == 1
    assert [r["id"] for r in _baseline(db, "dish")["ingredients"]] == [100]


def test_an_empty_string_against_null_does_not_block_the_match(db, tmp_path):
    """A save writes '' where it found null on a column it did not touch (a pre-existing defect in
    ROADMAP). snapshot_diff already reads '' and null as the same absence, so this follows it."""
    base = [ing(0, qty="2 tbsp", label="oil", note=None)]
    live = [ing(0, qty="2 tbsp", label="oil", note="")]
    tally = bf.run(str(db), apply=True, csv_out=tmp_path / "a.csv") if _write(
        db, "dish", base, [], live, []) else None
    assert tally["ingredient"]["quirk"] == 1


def test_a_real_edit_leaves_the_row_unassigned(db, tmp_path):
    """⚠️ NO SIMILARITY TIER, AND A WRONG ID IS WORSE THAN NONE. The amount genuinely changed, so the
    baseline row keeps a null id and the text-based diff keeps reporting it, as it does today."""
    base = [ing(0, qty="½ teaspoon", label="garlic powder")]
    live = [ing(0, qty="1 tsp", label="garlic powder")]
    tally = bf.run(str(db), apply=True, csv_out=tmp_path / "a.csv") if _write(
        db, "dish", base, [], live, []) else None
    assert tally["ingredient"]["unassigned"] == 1
    assert [r["id"] for r in _baseline(db, "dish")["ingredients"]] == [None]


def test_a_removed_row_leaves_the_row_unassigned(db, tmp_path):
    base = [ing(0, qty="2 tbsp", label="oil"), ing(1, qty="1 cup", label="water")]
    live = [ing(0, qty="2 tbsp", label="oil")]
    tally = bf.run(str(db), apply=True, csv_out=tmp_path / "a.csv") if _write(
        db, "dish", base, [], live, []) else None
    assert tally["ingredient"]["unassigned"] == 1
    assert [r["id"] for r in _baseline(db, "dish")["ingredients"]] == [100, None]


def test_it_refuses_to_write_if_the_rewrite_changes_more_than_the_ids(db, tmp_path, monkeypatch):
    """⚠️ THE ABORT IS THE WHOLE SAFETY ARGUMENT. Every baseline is re-serialized with the ids
    stripped back out and must equal the stored bytes. Here the serializer is made to drop a key, and
    nothing may be written to any of the 300."""
    rows = [ing(0, qty="2 tbsp", label="oil")]
    _write(db, "dish", rows, [], rows, [])
    stored = json.dumps(_baseline(db, "dish"), sort_keys=True, ensure_ascii=False,
                        separators=(",", ":"))
    monkeypatch.setattr(bf, "content_blob", lambda *a, **k: json.dumps(
        {"recipe": RECIPE, "ingredients": [], "steps": []},
        sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    with pytest.raises(SystemExit) as e:
        bf.run(str(db), apply=True, csv_out=tmp_path / "a.csv")
    assert "ABORT on dish" in str(e.value)
    assert json.dumps(_baseline(db, "dish"), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")) == stored, "nothing may be written after an abort"


def test_a_second_run_leaves_an_already_backfilled_baseline_alone(db, tmp_path):
    rows = [ing(0, qty="2 tbsp", label="oil")]
    _write(db, "dish", rows, [], rows, [])
    bf.run(str(db), apply=True, csv_out=tmp_path / "a.csv")
    first = _baseline(db, "dish")
    tally = bf.run(str(db), apply=True, csv_out=tmp_path / "b.csv")
    assert _baseline(db, "dish") == first
    assert sum(tally["ingredient"].values()) == 0, "an already-backfilled baseline is skipped"


def test_a_cook_snapshot_is_never_touched(db, tmp_path):
    """Only reason='original' is a baseline the diff reads. The 6 reason='cook' snapshots on live
    keep the format they were written in."""
    rows = [ing(0, qty="2 tbsp", label="oil")]
    _write(db, "dish", rows, [], rows, [])
    _write(db, "dish", rows, [], [], [], reason="cook")
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    cook_before = c.execute("SELECT content FROM recipe_snapshots WHERE reason='cook'"
                            ).fetchone()["content"]
    bf.run(str(db), apply=True, csv_out=tmp_path / "a.csv")
    c2 = sqlite3.connect(db)
    c2.row_factory = sqlite3.Row
    assert c2.execute("SELECT content FROM recipe_snapshots WHERE reason='cook'"
                      ).fetchone()["content"] == cook_before


def test_a_rehearsal_writes_nothing(db, tmp_path):
    rows = [ing(0, qty="2 tbsp", label="oil")]
    _write(db, "dish", rows, [], rows, [])
    before = _baseline(db, "dish")
    bf.run(str(db), apply=False, csv_out=tmp_path / "a.csv")
    assert _baseline(db, "dish") == before
    assert (tmp_path / "a.csv").exists(), "a rehearsal still writes the audit"
