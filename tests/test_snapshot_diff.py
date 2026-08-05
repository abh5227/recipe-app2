"""Change-tracking stage 3: the pure snapshot diff (snapshot_diff.diff_snapshots). The diff QUALITY is
validated here — realistic before/after pairs whose diffs a human would agree read cleanly. Blobs are
built directly as dicts (the stage-1 serialize_recipe_content format), so these are pure + DB-free.

Load-bearing cases: the AMOUNT collapse (split qty/quantity/unit -> ONE amount change), insert-at-top =
ONE 'added' (content-matching beats position-based), unlinked similarity match, step LCS, and the
similarity-threshold boundary (reword=modified vs wholesale=removed+added)."""
import json

import snapshot_diff as sd
from snapshot_diff import diff_snapshots


def _blob(recipe=None, ingredients=None, steps=None):
    r = {k: None for k in sd.CONTENT_FIELDS}
    r["name"] = "Dish"
    if recipe:
        r.update(recipe)
    return {"recipe": r, "ingredients": ingredients or [], "steps": steps or []}


def _ing(qty=None, ingredient_id=None, label=None, note="", raw_text=None,
         is_heading=0, position=0, quantity=None, unit=None):
    return {"position": position, "is_heading": is_heading, "qty": qty, "ingredient_id": ingredient_id,
            "label": label, "note": note, "raw_text": raw_text, "grams": None,
            "secondary_measure": None, "quantity": quantity, "unit": unit}


def _step(text, position=0, is_heading=0):
    return {"position": position, "is_heading": is_heading, "text": text}


# ---- content fields -----------------------------------------------------------------------------

def test_field_change_servings_only():
    old = _blob(recipe={"servings": "4", "prep_time": "10 min"})
    new = _blob(recipe={"servings": "6", "prep_time": "10 min"})
    assert diff_snapshots(old, new) == [
        {"kind": "field", "type": "modified", "field": "servings", "from": "4", "to": "6"}]


def test_identical_snapshots_no_changes():
    b = _blob(ingredients=[_ing(ingredient_id="x", label="sugar", qty="1 cup", raw_text="1 cup sugar")],
              steps=[_step("Mix")])
    assert diff_snapshots(b, b) == []


# ---- the AMOUNT collapse (the key coherence case) -----------------------------------------------

def test_linked_amount_change_is_ONE_coherent_entry_not_three():
    # qty AND quantity AND unit all change, but only ONE amount change is emitted (read from `qty`).
    old = _blob(ingredients=[_ing(ingredient_id="sugar", label="sugar", qty="1 cup",
                                  quantity="1", unit="cup", raw_text="1 cup sugar")])
    new = _blob(ingredients=[_ing(ingredient_id="sugar", label="sugar", qty="¾ cup",
                                  quantity="¾", unit="cup", raw_text="¾ cup sugar")])
    ch = diff_snapshots(old, new)
    assert ch == [{"kind": "ingredient", "type": "modified", "field": "amount",
                   "label": "sugar", "from": "1 cup", "to": "¾ cup"}]
    assert len(ch) == 1                                    # NOT qty + quantity + unit field-noise


def test_amount_and_note_are_separate_coherent_changes():
    old = _blob(ingredients=[_ing(ingredient_id="b", label="butter", qty="2 tbsp", note="softened", raw_text="2 tbsp butter")])
    new = _blob(ingredients=[_ing(ingredient_id="b", label="butter", qty="3 tbsp", note="melted", raw_text="3 tbsp butter")])
    fields = [(c["field"], c["from"], c["to"]) for c in diff_snapshots(old, new)]
    assert ("amount", "2 tbsp", "3 tbsp") in fields
    assert ("note", "softened", "melted") in fields
    assert len(fields) == 2


# ---- add / remove is ONE change, not a position-cascade (proves content-matching) ---------------

def test_insert_at_top_is_one_added_linked():
    old = _blob(ingredients=[_ing(ingredient_id="flour", label="flour", qty="2 cups"),
                             _ing(ingredient_id="salt", label="salt", qty="1 tsp")])
    new = _blob(ingredients=[_ing(ingredient_id="eggs", label="eggs", qty="2"),
                             _ing(ingredient_id="flour", label="flour", qty="2 cups"),
                             _ing(ingredient_id="salt", label="salt", qty="1 tsp")])
    assert diff_snapshots(old, new) == [
        {"kind": "ingredient", "type": "added", "text": "2 eggs", "label": "eggs"}]


def test_insert_at_top_is_one_added_unlinked():
    old = _blob(ingredients=[_ing(qty="2 cups", raw_text="flour"), _ing(qty="1 tsp", raw_text="salt")])
    new = _blob(ingredients=[_ing(qty="2", raw_text="eggs"),
                             _ing(qty="2 cups", raw_text="flour"), _ing(qty="1 tsp", raw_text="salt")])
    assert diff_snapshots(old, new) == [
        {"kind": "ingredient", "type": "added", "text": "2 eggs", "label": "eggs"}]


def test_remove_ingredient_is_one_removed():
    old = _blob(ingredients=[_ing(qty="2 cups", raw_text="flour"), _ing(qty="1 tsp", raw_text="salt")])
    new = _blob(ingredients=[_ing(qty="2 cups", raw_text="flour")])
    assert diff_snapshots(old, new) == [
        {"kind": "ingredient", "type": "removed", "text": "1 tsp salt", "label": "salt"}]


# ---- linked vs unlinked matching ----------------------------------------------------------------

def test_unlinked_amount_change_matched_by_similarity_is_modified():
    old = _blob(ingredients=[_ing(qty="1 cup", raw_text="sugar")])
    new = _blob(ingredients=[_ing(qty="¾ cup", raw_text="sugar")])
    assert diff_snapshots(old, new) == [
        {"kind": "ingredient", "type": "modified", "field": "amount",
         "label": "sugar", "from": "1 cup", "to": "¾ cup"}]   # matched, not removed+added


def test_linked_matched_despite_large_text_change():
    old = _blob(ingredients=[_ing(ingredient_id="x", label="sugar", qty="1 cup", raw_text="1 cup sugar")])
    new = _blob(ingredients=[_ing(ingredient_id="x", label="brown sugar", qty="2 tbsp", raw_text="2 tbsp brown sugar")])
    ch = diff_snapshots(old, new)
    assert {c["field"] for c in ch} == {"amount", "name"}   # id-matched -> field changes, NOT removed+added
    assert all(c["type"] == "modified" for c in ch)


def test_unlinked_wholesale_replacement_is_removed_and_added():
    old = _blob(ingredients=[_ing(qty="1 cup", raw_text="sugar")])
    new = _blob(ingredients=[_ing(qty="3", raw_text="eggs")])
    assert {c["type"] for c in diff_snapshots(old, new)} == {"removed", "added"}   # below threshold


# ---- steps (LCS + similarity) -------------------------------------------------------------------

def test_step_reword_is_modified():
    old = _blob(steps=[_step("Beat the eggs")])
    new = _blob(steps=[_step("Beat the eggs well")])
    assert diff_snapshots(old, new) == [
        {"kind": "step", "type": "modified", "from": "Beat the eggs", "to": "Beat the eggs well"}]


def test_step_insert_is_one_added_not_cascade():
    old = _blob(steps=[_step("Preheat the oven"), _step("Bake for 20 minutes")])
    new = _blob(steps=[_step("Preheat the oven"), _step("Grease the pan"), _step("Bake for 20 minutes")])
    assert diff_snapshots(old, new) == [{"kind": "step", "type": "added", "text": "Grease the pan"}]


def test_step_remove_is_one_removed():
    old = _blob(steps=[_step("Preheat the oven"), _step("Bake for 20 minutes")])
    new = _blob(steps=[_step("Preheat the oven")])
    assert diff_snapshots(old, new) == [{"kind": "step", "type": "removed", "text": "Bake for 20 minutes"}]


# ---- headings don't pollute line matching -------------------------------------------------------

def test_heading_change_is_heading_kind_and_line_untouched():
    old = _blob(ingredients=[_ing(is_heading=1, raw_text="For the base"),
                             _ing(qty="1 cup", raw_text="sugar", position=1)])
    new = _blob(ingredients=[_ing(is_heading=1, raw_text="For the batter"),
                             _ing(qty="1 cup", raw_text="sugar", position=1)])
    assert diff_snapshots(old, new) == [
        {"kind": "heading", "type": "modified", "from": "For the base", "to": "For the batter"}]


# ---- the similarity-threshold boundary (pins + documents the knob) ------------------------------

def test_threshold_boundary_reword_vs_replacement():
    reword = diff_snapshots(_blob(steps=[_step("Fold in the cream gently")]),
                            _blob(steps=[_step("Fold in the cream")]))
    assert reword == [{"kind": "step", "type": "modified",
                       "from": "Fold in the cream gently", "to": "Fold in the cream"}]   # >= threshold
    swap = diff_snapshots(_blob(steps=[_step("Fold in the cream")]),
                          _blob(steps=[_step("Roast the whole chicken")]))
    assert {c["type"] for c in swap} == {"removed", "added"}                             # < threshold


# ---- purity / determinism / the string contract -------------------------------------------------

def test_stable_ordering_and_determinism():
    old = _blob(recipe={"servings": "4"},
                ingredients=[_ing(ingredient_id="x", label="sugar", qty="1 cup")], steps=[_step("Mix the batter")])
    new = _blob(recipe={"servings": "6"},
                ingredients=[_ing(ingredient_id="x", label="sugar", qty="¾ cup")], steps=[_step("Mix the batter slowly")])
    a = diff_snapshots(old, new)
    b = diff_snapshots(old, new)
    assert a == b                                          # deterministic
    assert [c["kind"] for c in a] == ["field", "ingredient", "step"]   # fields -> ingredients -> steps


def test_accepts_json_string_blobs():
    old = json.dumps(_blob(recipe={"servings": "4"}))
    new = json.dumps(_blob(recipe={"servings": "6"}))
    assert diff_snapshots(old, new) == [
        {"kind": "field", "type": "modified", "field": "servings", "from": "4", "to": "6"}]
