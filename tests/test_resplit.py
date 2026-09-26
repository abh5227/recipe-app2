"""resplit.py — the ONE path every re-split goes through, and the lockstep rule it exists to hold.

The bug it prevents: ed6aaf5 lifted the counting noun into the unit on 73 live rows on 2026-09-23,
touched no `reason='original'` baseline, and minted 73 phantom amount-edits. The page has shown
them as "your changes" ever since, against 8 edits that are real.
"""
import json

import pytest

import import_cleanup as ic
import resplit


# --------------------------------------------------------------------------------------------- #
# The split itself
# --------------------------------------------------------------------------------------------- #
def test_a_re_split_never_returns_raw_text():
    """A re-split re-READS a line. Rewriting the source line is what lost the amounts in the first
    place, so raw_text is not among the columns this can write."""
    got = resplit.split_columns("5 garlic cloves, peeled")
    assert "raw_text" not in got
    assert set(got) <= set(resplit.SPLIT_COLUMNS)


def test_a_section_line_is_never_written():
    """Turning an ingredient into a heading loses it from the list, the worse error."""
    assert resplit.split_columns("FOR THE SAUCE:") is None
    assert resplit.split_columns("") is None


def test_a_row_that_already_has_an_amount_is_not_read_as_a_heading():
    """⚠️ THE 7 LIVE MISREADS. 'maple syrup' and 'oyster sauce' end in a common section word, so the
    narrow guess in block 3b promoted them. The row carries '2 tbsp' in its qty column, so it is an
    ingredient whatever the text looks like."""
    for text in ("maple syrup", "oyster sauce", "light soy sauce", "dark soy sauce",
                 "Worcestershire sauce"):
        assert ic.classify_line(text)["kind"] == "section", f"premise: {text!r} used to promote"
        assert ic.classify_line(text, None, has_stored_amount=True)["kind"] != "section"
        assert resplit.split_columns(text, stored_qty="2 tbsp") is not None


def test_a_real_heading_is_still_a_heading_whatever_the_row_holds():
    """Block 3 is untouched: a colon or ALL-CAPS still settles it."""
    for text in ("FOR THE SAUCE:", "Glaze:", "FOR THE REST OF THE DISH:"):
        assert ic.classify_line(text, None, has_stored_amount=True)["kind"] == "section"
        assert resplit.split_columns(text, stored_qty="2 tbsp") is None


def test_a_stored_amount_survives_a_line_that_no_longer_carries_one():
    """⚠️ NEVER LOSE INFORMATION. The old save rewrote raw_text with the displayed name, so the
    amount survives only in the qty column. Re-reading that text finds none, and writing the result
    back would throw the stored one away. The re-split updates the NAME only."""
    row = {"raw_text": "maple syrup", "qty": "2 tbsp", "quantity": "2", "unit": "tbsp", "label": None}
    got = resplit.plan_row(row)
    assert got == {"label": "maple syrup"}
    assert "qty" not in got and "unit" not in got


def test_the_space_before_a_comma_leaves_the_parsed_name():
    """77 live lines over 24 recipes read "onion , roughly sliced". The source line keeps its
    spacing; only the name the page shows is tidied."""
    got = resplit.split_columns("5 garlic cloves , peeled")
    assert got["label"] == "garlic, peeled"
    assert ic.clean_source_text("beef stock / broth , low sodium")[0] == "beef stock / broth, low sodium"
    assert ic.clean_source_text("a, b")[1] == []          # nothing to do, no flag


# --------------------------------------------------------------------------------------------- #
# Lockstep
# --------------------------------------------------------------------------------------------- #
def _seed(kitchen, rows, baseline_rows=None):
    """A recipe whose live rows and 'original' baseline are set independently, so a test can make
    them differ the way a real edit does."""
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Lockstep", "ingredients": [], "steps": ["placeholder"]}).get_json()["id"]
    with kitchen.conn() as c:
        c.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (rid,))
        for i, r in enumerate(rows):
            c.execute("INSERT INTO recipe_ingredients "
                      "(recipe_id, position, is_heading, qty, quantity, unit, label, raw_text) "
                      "VALUES (?,?,0,?,?,?,?,?)",
                      (rid, i, r.get("qty"), r.get("quantity"), r.get("unit"),
                       r.get("label"), r["raw_text"]))
        doc = {"recipe": {}, "steps": [],
               "ingredients": [dict({"position": i, "is_heading": 0, "qty": None, "quantity": None,
                                     "unit": None, "label": None, "note": None, "grams": None,
                                     "secondary_measure": None, "ingredient_id": None}, **r)
                               for i, r in enumerate(baseline_rows or rows)]}
        c.execute("INSERT INTO recipe_snapshots (recipe_id, reason, user_id, content, created_at) "
                  "VALUES (?, 'original', 1, ?, '2026-01-01')", (rid, json.dumps(doc)))
        c.commit()
    return rid


def _live(kitchen, rid):
    with kitchen.conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT position, qty, quantity, unit, label, raw_text FROM recipe_ingredients "
            "WHERE recipe_id=? ORDER BY position", (rid,))]


def _baseline(kitchen, rid):
    with kitchen.conn() as c:
        doc = json.loads(c.execute("SELECT content FROM recipe_snapshots WHERE recipe_id=? "
                                   "AND reason='original'", (rid,)).fetchone()[0])
    return {x["position"]: x for x in doc["ingredients"]}


def test_a_re_split_moves_the_live_row_and_its_baseline_together(kitchen):
    """THE RULE. Both sides hold "4 garlic cloves" and neither is split. One re-split must leave
    both split the same way, so the page shows no edit."""
    rid = _seed(kitchen, [{"raw_text": "4 garlic cloves", "qty": "4", "quantity": "4", "unit": ""}])
    with kitchen.conn() as c:
        plan = {0: resplit.plan_row(dict(_live(kitchen, rid)[0]))}
        assert plan[0], "premise: the re-split must want to change something"
        n_live, n_base = resplit.write_lockstep(c, rid, plan)
        c.commit()
    assert (n_live, n_base) == (1, 1)
    live, base = _live(kitchen, rid)[0], _baseline(kitchen, rid)[0]
    assert live["unit"] == "cloves" and live["label"] == "garlic"
    assert base["unit"] == "cloves" and base["label"] == "garlic"
    assert (live["label"], live["qty"]) == (base["label"], base["qty"])   # no annotation


def test_the_baseline_is_re_split_from_its_OWN_text_not_the_live_row_s(kitchen):
    """⚠️ THE HALF THAT IS EASY TO GET WRONG. The cook changed the ingredient since the baseline was
    minted. Copying the live row's split into the baseline would erase that edit from the
    crossed-out view. Each side is re-read from its own line."""
    rid = _seed(kitchen,
                rows=[{"raw_text": "4 garlic cloves", "qty": "4", "quantity": "4", "unit": ""}],
                baseline_rows=[{"raw_text": "4 shallot cloves", "qty": "4", "quantity": "4", "unit": ""}])
    with kitchen.conn() as c:
        resplit.write_lockstep(c, rid, {0: resplit.plan_row(dict(_live(kitchen, rid)[0]))})
        c.commit()
    live, base = _live(kitchen, rid)[0], _baseline(kitchen, rid)[0]
    assert live["label"] == "garlic"
    assert base["label"] == "shallot", "the baseline took the live row's name"
    assert base["raw_text"] == "4 shallot cloves", "a re-split rewrote the source line"
    assert live["unit"] == base["unit"] == "cloves"      # the RULE applied to both, the TEXT did not


def test_a_genuine_edit_still_shows_after_a_re_split(kitchen):
    """The whole point. After lockstep the parser change is invisible and the cook's edit is not."""
    rid = _seed(kitchen,
                rows=[{"raw_text": "4 garlic cloves", "qty": "4", "quantity": "4", "unit": ""}],
                baseline_rows=[{"raw_text": "2 garlic cloves", "qty": "2", "quantity": "2", "unit": ""}])
    with kitchen.conn() as c:
        resplit.write_lockstep(c, rid, {0: resplit.plan_row(dict(_live(kitchen, rid)[0]))})
        c.commit()
    live, base = _live(kitchen, rid)[0], _baseline(kitchen, rid)[0]
    assert live["label"] == base["label"] == "garlic"    # the parser change cancels out
    assert live["qty"] == "4 cloves" and base["qty"] == "2 cloves"   # the real edit survives


def test_a_re_split_never_rewrites_raw_text_on_either_side(kitchen):
    rid = _seed(kitchen, [{"raw_text": "5 garlic cloves , peeled", "qty": "5",
                           "quantity": "5", "unit": ""}])
    before = _live(kitchen, rid)[0]["raw_text"]
    with kitchen.conn() as c:
        resplit.write_lockstep(c, rid, {0: resplit.plan_row(dict(_live(kitchen, rid)[0]))})
        c.commit()
    assert _live(kitchen, rid)[0]["raw_text"] == before == "5 garlic cloves , peeled"
    assert _baseline(kitchen, rid)[0]["raw_text"] == "5 garlic cloves , peeled"
    assert _live(kitchen, rid)[0]["label"] == "garlic, peeled"       # only the NAME was tidied


def test_lockstep_is_idempotent(kitchen):
    rid = _seed(kitchen, [{"raw_text": "4 garlic cloves", "qty": "4", "quantity": "4", "unit": ""}])
    with kitchen.conn() as c:
        resplit.write_lockstep(c, rid, {0: resplit.plan_row(dict(_live(kitchen, rid)[0]))})
        c.commit()
    after_first = (_live(kitchen, rid), _baseline(kitchen, rid))
    assert resplit.plan_row(dict(_live(kitchen, rid)[0])) == {}, "a second pass still wants a change"
    assert (_live(kitchen, rid), _baseline(kitchen, rid)) == after_first
