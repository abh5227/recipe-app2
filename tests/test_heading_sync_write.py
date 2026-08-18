"""The heading-sync WRITE path (stage 2): a PUT keeps the reason='original' baseline's heading layout
in step with the rows it just saved. The pure transform and its postcondition are pinned in
tests/test_heading_sync.py; this file pins the SEAM — that it runs on a real transaction, that it is
skipped when there is nothing to do, and above all that it never absorbs the user's edits into the
baseline.

The load-bearing test here is test_move_a_heading_and_edit_an_ingredient_in_one_save: the baseline is
the recipe's birth state, there is no second copy of it, and a sync that pulled content from the rows
being saved would be silent, permanent, and indistinguishable from the user having made those edits.
"""
import json

import app
import snapshot_headsync


def _recipe(client, name="Sync Dish"):
    """A recipe with TWO ingredient sections and a step heading, so every heading operation is
    expressible without changing any content row."""
    return client.post("/api/recipes", json={
        "name": name,
        "ingredients": [
            {"heading": "FOR THE BASE"},
            {"qty": "2", "text": "eggs"},
            {"qty": "1 cup", "text": "flour"},
            {"heading": "FOR THE TOP"},
            {"qty": "3 tbsp", "text": "sugar"},
        ],
        "steps": [{"heading": "PREP"}, "Beat the eggs.", "Fold in the flour."],
    }).get_json()["id"]


def _original(kitchen, rid):
    with kitchen.conn() as c:
        row = c.execute(
            "SELECT content FROM recipe_snapshots WHERE recipe_id=? AND reason='original'", (rid,)
        ).fetchone()
    return row["content"] if row else None


def _layout(blob, key, textkey):
    return [(i, r[textkey]) for i, r in enumerate(json.loads(blob)[key]) if r["is_heading"]]


def _content(blob, key):
    """Content rows with `position` projected out — the P1 view (a heading move legitimately
    renumbers content rows; see snapshot_headsync.content_safety_problems)."""
    return [{k: v for k, v in r.items() if k != "position"}
            for r in json.loads(blob)[key] if not r["is_heading"]]


def _put(client, rid, ingredients, steps, name="Sync Dish"):
    return client.put(f"/api/recipes/{rid}",
                      json={"name": name, "ingredients": ingredients, "steps": steps})


BASE_ING = [
    {"heading": "FOR THE BASE"}, {"qty": "2", "text": "eggs"}, {"qty": "1 cup", "text": "flour"},
    {"heading": "FOR THE TOP"}, {"qty": "3 tbsp", "text": "sugar"},
]
BASE_STEPS = [{"heading": "PREP"}, "Beat the eggs.", "Fold in the flour."]


# ---- the headline case ---------------------------------------------------------------------------

def test_moving_a_heading_syncs_the_baseline_and_clears_the_annotations(kitchen):
    rid = _recipe(kitchen.client)
    before = _original(kitchen, rid)
    assert _layout(before, "ingredients", "raw_text") == [(0, "FOR THE BASE"), (3, "FOR THE TOP")]

    moved = [                                      # FOR THE TOP moves to the front; content order kept
        {"heading": "FOR THE TOP"}, {"heading": "FOR THE BASE"},
        {"qty": "2", "text": "eggs"}, {"qty": "1 cup", "text": "flour"}, {"qty": "3 tbsp", "text": "sugar"},
    ]
    assert _put(kitchen.client, rid, moved, BASE_STEPS).status_code == 200

    after = _original(kitchen, rid)
    assert after != before, "the baseline should have been rewritten"
    assert _layout(after, "ingredients", "raw_text") == [(0, "FOR THE TOP"), (1, "FOR THE BASE")]
    # P1 held through a real transaction: the birth content survived verbatim
    assert _content(after, "ingredients") == _content(before, "ingredients")
    assert _content(after, "steps") == _content(before, "steps")

    # and the byte-equal short-circuit is reachable again -> zero annotations
    with app.orm_session() as s:
        assert app.serialize_recipe_content(s, rid) == after
        assert app._recipe_annotations(s, rid) == []


# ---- ⚠️ the case that matters most -----------------------------------------------------------------

def test_move_a_heading_and_edit_an_ingredient_in_one_save(kitchen):
    """A heading move and a CONTENT edit in the same PUT. The baseline must take the new heading
    layout and NOT the new content, so the edit still registers as an annotation. If the sync ever
    absorbed the edit, `annotations` would come back empty and the pre-edit value would be gone from
    the baseline — this asserts both directions."""
    rid = _recipe(kitchen.client)
    before = _original(kitchen, rid)

    both = [
        {"heading": "FOR THE TOP"}, {"heading": "FOR THE BASE"},
        {"qty": "2", "text": "eggs"},
        {"qty": "1 cup", "text": "flour"},
        {"qty": "9 tbsp", "text": "sugar"},        # <-- the user's edit: 3 tbsp -> 9 tbsp
    ]
    assert _put(kitchen.client, rid, both, BASE_STEPS).status_code == 200

    after = _original(kitchen, rid)
    assert _layout(after, "ingredients", "raw_text") == [(0, "FOR THE TOP"), (1, "FOR THE BASE")]
    # the baseline still holds the PRE-EDIT content, byte-for-byte
    assert _content(after, "ingredients") == _content(before, "ingredients")
    assert "9 tbsp" not in after, "the user's edit leaked into the baseline — birth state overwritten"
    assert "3 tbsp" in after, "the baseline lost the pre-edit value"

    # and the edit is still visible as an annotation
    with app.orm_session() as s:
        ann = app._recipe_annotations(s, rid)
    amounts = [a for a in ann if a["kind"] == "ingredient" and a.get("field") == "amount"]
    assert len(amounts) == 1, f"expected exactly the amount change, got {ann}"
    assert amounts[0]["from"] == "3 tbsp"
    assert amounts[0]["to"] == "9 tbsp"


# ---- the other three operations --------------------------------------------------------------------

def test_adding_a_heading_syncs(kitchen):
    rid = _recipe(kitchen.client)
    before = _original(kitchen, rid)
    added = BASE_ING + [{"heading": "TO SERVE"}]
    assert _put(kitchen.client, rid, added, BASE_STEPS).status_code == 200
    after = _original(kitchen, rid)
    assert [t for _, t in _layout(after, "ingredients", "raw_text")] == [
        "FOR THE BASE", "FOR THE TOP", "TO SERVE"]
    assert _content(after, "ingredients") == _content(before, "ingredients")


def test_removing_a_heading_syncs(kitchen):
    rid = _recipe(kitchen.client)
    before = _original(kitchen, rid)
    removed = [r for r in BASE_ING if r != {"heading": "FOR THE TOP"}]
    assert _put(kitchen.client, rid, removed, BASE_STEPS).status_code == 200
    after = _original(kitchen, rid)
    assert [t for _, t in _layout(after, "ingredients", "raw_text")] == ["FOR THE BASE"]
    assert _content(after, "ingredients") == _content(before, "ingredients")


def test_renaming_a_heading_syncs(kitchen):
    rid = _recipe(kitchen.client)
    before = _original(kitchen, rid)
    renamed = [{"heading": "FOR THE SPONGE"} if r == {"heading": "FOR THE BASE"} else r for r in BASE_ING]
    assert _put(kitchen.client, rid, renamed, BASE_STEPS).status_code == 200
    after = _original(kitchen, rid)
    assert [t for _, t in _layout(after, "ingredients", "raw_text")] == ["FOR THE SPONGE", "FOR THE TOP"]
    assert _content(after, "ingredients") == _content(before, "ingredients")


def test_step_headings_sync_too(kitchen):
    rid = _recipe(kitchen.client)
    before = _original(kitchen, rid)
    moved_steps = ["Beat the eggs.", {"heading": "PREP"}, "Fold in the flour."]
    assert _put(kitchen.client, rid, BASE_ING, moved_steps).status_code == 200
    after = _original(kitchen, rid)
    assert _layout(after, "steps", "text") == [(1, "PREP")]
    assert _content(after, "steps") == _content(before, "steps")


# ---- the no-op paths -------------------------------------------------------------------------------

def test_a_save_that_changes_nothing_structural_leaves_the_baseline_byte_identical(kitchen):
    rid = _recipe(kitchen.client)
    before = _original(kitchen, rid)
    assert _put(kitchen.client, rid, BASE_ING, BASE_STEPS).status_code == 200
    assert _original(kitchen, rid) == before          # byte-identical -> the UPDATE was skipped


def test_a_content_only_edit_leaves_the_baseline_byte_identical(kitchen):
    """Editing content without touching a heading must not rewrite the baseline at all — otherwise
    every save would churn the one row we are trying to protect."""
    rid = _recipe(kitchen.client)
    before = _original(kitchen, rid)
    edited = [dict(r) for r in BASE_ING]
    edited[4] = {"qty": "9 tbsp", "text": "sugar"}
    assert _put(kitchen.client, rid, edited, BASE_STEPS).status_code == 200
    assert _original(kitchen, rid) == before


def test_a_recipe_with_no_original_snapshot_saves_normally(kitchen):
    rid = _recipe(kitchen.client)
    with kitchen.conn() as c:
        c.execute("DELETE FROM recipe_snapshots WHERE recipe_id=? AND reason='original'", (rid,))
        c.commit()
    assert _original(kitchen, rid) is None

    moved = [{"heading": "FOR THE TOP"}, {"heading": "FOR THE BASE"},
             {"qty": "2", "text": "eggs"}, {"qty": "1 cup", "text": "flour"}, {"qty": "3 tbsp", "text": "sugar"}]
    assert _put(kitchen.client, rid, moved, BASE_STEPS).status_code == 200   # no error
    assert _original(kitchen, rid) is None, "the sync must NEVER mint a baseline — that is birth capture's job"
    with kitchen.conn() as c:                                                # the edit itself landed
        heads = [r["raw_text"] for r in c.execute(
            "SELECT raw_text FROM recipe_ingredients WHERE recipe_id=? AND is_heading=1 ORDER BY position", (rid,))]
    assert heads == ["FOR THE TOP", "FOR THE BASE"]


# ---- the abort path --------------------------------------------------------------------------------

def test_a_content_safety_failure_aborts_the_whole_save(kitchen, monkeypatch):
    """If the postcondition ever fails, the correct behaviour is to fail the save LOUDLY — not to
    swallow it and write anyway. Because the sync runs inside the one transaction before the single
    commit, the rows must roll back too: proving it half-applies nothing."""
    rid = _recipe(kitchen.client)
    before_baseline = _original(kitchen, rid)
    with kitchen.conn() as c:
        before_rows = [dict(r) for r in c.execute(
            "SELECT position,is_heading,qty,raw_text FROM recipe_ingredients WHERE recipe_id=? ORDER BY position",
            (rid,))]

    def boom(old_blob, new_blob):
        raise snapshot_headsync.HeadingSyncViolation("forced failure for the abort test")

    monkeypatch.setattr(app.snapshot_headsync, "assert_content_safe", boom)

    moved = [{"heading": "FOR THE TOP"}, {"heading": "FOR THE BASE"},
             {"qty": "2", "text": "eggs"}, {"qty": "1 cup", "text": "flour"}, {"qty": "3 tbsp", "text": "sugar"}]
    # The violation surfaces to the CLIENT as a failed request (Flask turns the unhandled exception
    # into a 500) — deliberately not swallowed into a 200. What matters is that the save did not
    # half-apply, asserted below.
    assert _put(kitchen.client, rid, moved, BASE_STEPS).status_code == 500

    # nothing half-applied: the baseline AND the rows are exactly as they were
    assert _original(kitchen, rid) == before_baseline
    with kitchen.conn() as c:
        after_rows = [dict(r) for r in c.execute(
            "SELECT position,is_heading,qty,raw_text FROM recipe_ingredients WHERE recipe_id=? ORDER BY position",
            (rid,))]
    assert after_rows == before_rows, "the ingredient rows were not rolled back"


def test_the_real_postcondition_is_wired_in_not_a_copy(kitchen):
    """Guards against the seam drifting from the committed transform: the call site must use
    snapshot_headsync's own checker, so tightening it there tightens it here."""
    rid = _recipe(kitchen.client)
    with app.orm_session() as s:
        assert app.sync_original_heading_layout(s, rid) is False      # already in sync -> no write
    assert app.snapshot_headsync is snapshot_headsync
