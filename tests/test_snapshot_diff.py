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
    assert ch == [{"kind": "ingredient", "type": "modified", "field": "amount", "label": "sugar",
                   "from": "1 cup", "to": "¾ cup", "new_pos": 0, "old_pos": 0}]
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
        {"kind": "ingredient", "type": "added", "text": "2 eggs", "label": "eggs", "new_pos": 0, "old_pos": None}]


def test_insert_at_top_is_one_added_unlinked():
    old = _blob(ingredients=[_ing(qty="2 cups", raw_text="flour"), _ing(qty="1 tsp", raw_text="salt")])
    new = _blob(ingredients=[_ing(qty="2", raw_text="eggs"),
                             _ing(qty="2 cups", raw_text="flour"), _ing(qty="1 tsp", raw_text="salt")])
    assert diff_snapshots(old, new) == [
        {"kind": "ingredient", "type": "added", "text": "2 eggs", "label": "eggs", "new_pos": 0, "old_pos": None}]


def test_remove_ingredient_is_one_removed():
    old = _blob(ingredients=[_ing(qty="2 cups", raw_text="flour"), _ing(qty="1 tsp", raw_text="salt")])
    new = _blob(ingredients=[_ing(qty="2 cups", raw_text="flour")])
    assert diff_snapshots(old, new) == [                    # old_pos 1 = salt is the 2nd real ingredient
        {"kind": "ingredient", "type": "removed", "text": "1 tsp salt", "label": "salt",
         "new_pos": None, "old_pos": 1, "section": None}]


# ---- linked vs unlinked matching ----------------------------------------------------------------

def test_unlinked_amount_change_matched_by_similarity_is_modified():
    old = _blob(ingredients=[_ing(qty="1 cup", raw_text="sugar")])
    new = _blob(ingredients=[_ing(qty="¾ cup", raw_text="sugar")])
    assert diff_snapshots(old, new) == [                    # matched, not removed+added
        {"kind": "ingredient", "type": "modified", "field": "amount", "label": "sugar",
         "from": "1 cup", "to": "¾ cup", "new_pos": 0, "old_pos": 0}]


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
        {"kind": "step", "type": "modified", "from": "Beat the eggs", "to": "Beat the eggs well",
         "new_pos": 0, "old_pos": 0}]


def test_step_insert_is_one_added_not_cascade():
    old = _blob(steps=[_step("Preheat the oven"), _step("Bake for 20 minutes")])
    new = _blob(steps=[_step("Preheat the oven"), _step("Grease the pan"), _step("Bake for 20 minutes")])
    assert diff_snapshots(old, new) == [                    # new_pos 1 = inserted at the 2nd real-step slot
        {"kind": "step", "type": "added", "text": "Grease the pan", "new_pos": 1, "old_pos": None}]


def test_step_remove_is_one_removed():
    old = _blob(steps=[_step("Preheat the oven"), _step("Bake for 20 minutes")])
    new = _blob(steps=[_step("Preheat the oven")])
    assert diff_snapshots(old, new) == [                    # old_pos 1 = the 2nd real step
        {"kind": "step", "type": "removed", "text": "Bake for 20 minutes",
         "new_pos": None, "old_pos": 1, "section": None}]


# ---- headings don't pollute line matching -------------------------------------------------------

def test_heading_change_is_heading_kind_and_line_untouched():
    old = _blob(ingredients=[_ing(is_heading=1, raw_text="For the base"),
                             _ing(qty="1 cup", raw_text="sugar", position=1)])
    new = _blob(ingredients=[_ing(is_heading=1, raw_text="For the batter"),
                             _ing(qty="1 cup", raw_text="sugar", position=1)])
    assert diff_snapshots(old, new) == [                    # new_pos/old_pos = index in the headings sequence
        {"kind": "heading", "type": "modified", "from": "For the base", "to": "For the batter",
         "new_pos": 0, "old_pos": 0}]


# ---- the similarity-threshold boundary (pins + documents the knob) ------------------------------

def test_threshold_boundary_reword_vs_replacement():
    reword = diff_snapshots(_blob(steps=[_step("Fold in the cream gently")]),
                            _blob(steps=[_step("Fold in the cream")]))
    assert reword == [{"kind": "step", "type": "modified", "new_pos": 0, "old_pos": 0,
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


# ---- O-c-0: POSITION + section identity on each change ------------------------------------------
# new_pos/old_pos index the HEADING-EXCLUDED real sequence (the O-c-1 anchor); section (removed items)
# uses the HEADING-INCLUSIVE full position (ordering among headings). Two numbers, two purposes.

def test_modified_ingredient_carries_positions():
    old = _blob(ingredients=[_ing(ingredient_id="s", label="sugar", qty="1 cup", position=0)])
    new = _blob(ingredients=[_ing(ingredient_id="s", label="sugar", qty="¾ cup", position=0)])
    (c,) = diff_snapshots(old, new)
    assert c["new_pos"] == 0 and c["old_pos"] == 0


def test_added_at_position_is_real_index_not_append():
    old = _blob(ingredients=[_ing(ingredient_id="flour", label="flour", qty="2 cups", position=0)])
    new = _blob(ingredients=[_ing(ingredient_id="eggs", label="eggs", qty="2", position=0),
                             _ing(ingredient_id="flour", label="flour", qty="2 cups", position=1)])
    (c,) = diff_snapshots(old, new)
    assert c["type"] == "added" and c["new_pos"] == 0 and c["old_pos"] is None   # inserted at TOP, not appended


def test_removed_carries_old_pos():
    old = _blob(ingredients=[_ing(qty="2 cups", raw_text="flour", position=0),
                             _ing(qty="1 tsp", raw_text="salt", position=1)])
    new = _blob(ingredients=[_ing(qty="2 cups", raw_text="flour", position=0)])
    (c,) = diff_snapshots(old, new)
    assert c["type"] == "removed" and c["old_pos"] == 1 and c["new_pos"] is None


def test_duplicate_label_modified_carries_the_RIGHT_position():
    # THE 18.5% fix: two same-label rows, the SECOND edited -> the change anchors to the second's index, not
    # the first. Content alone ("oil") can't disambiguate; the heading-excluded position does.
    old = _blob(ingredients=[_ing(qty="1 tbsp", raw_text="oil", position=0),
                             _ing(qty="2 tbsp", raw_text="oil", position=1)])
    new = _blob(ingredients=[_ing(qty="1 tbsp", raw_text="oil", position=0),
                             _ing(qty="3 tbsp", raw_text="oil", position=1)])
    mods = [c for c in diff_snapshots(old, new) if c["type"] == "modified"]
    assert len(mods) == 1
    assert mods[0]["from"] == "2 tbsp" and mods[0]["to"] == "3 tbsp"
    assert mods[0]["new_pos"] == 1 and mods[0]["old_pos"] == 1   # the SECOND oil, unambiguously


def test_insert_shift_positions_track():
    # Insert at top + edit a shifted row: inserted new_pos=0; the shifted salt (now index 2) carries 2.
    old = _blob(ingredients=[_ing(ingredient_id="flour", label="flour", qty="2 cups", position=0),
                             _ing(ingredient_id="salt", label="salt", qty="1 tsp", position=1)])
    new = _blob(ingredients=[_ing(ingredient_id="eggs", label="eggs", qty="2", position=0),
                             _ing(ingredient_id="flour", label="flour", qty="2 cups", position=1),
                             _ing(ingredient_id="salt", label="salt", qty="2 tsp", position=2)])
    ch = diff_snapshots(old, new)
    added = [c for c in ch if c["type"] == "added"][0]
    mod = [c for c in ch if c["type"] == "modified"][0]
    assert added["new_pos"] == 0                            # inserted at top
    assert mod["old_pos"] == 1 and mod["new_pos"] == 2      # salt shifted index 1 -> 2, amount edited


def test_removed_item_carries_section_identity():
    # heading "For the base": [flour, eggs]; heading "For the sauce": [cream]. Removing an item names its
    # ORIGINAL section (its old_pos is the heading-excluded index; section uses the full position).
    def build(with_eggs=True, with_cream=True):
        rows = [_ing(is_heading=1, raw_text="For the base", position=0),
                _ing(qty="1 cup", raw_text="flour", position=1)]
        if with_eggs:
            rows.append(_ing(qty="2", raw_text="eggs", position=2))
        rows.append(_ing(is_heading=1, raw_text="For the sauce", position=3))
        if with_cream:
            rows.append(_ing(qty="1 cup", raw_text="cream", position=4))
        return _blob(ingredients=rows)
    (c,) = [c for c in diff_snapshots(build(), build(with_eggs=False)) if c["type"] == "removed"]
    assert c["label"] == "eggs" and c["section"] == "For the base" and c["old_pos"] == 1
    (c,) = [c for c in diff_snapshots(build(), build(with_cream=False)) if c["type"] == "removed"]
    assert c["label"] == "cream" and c["section"] == "For the sauce" and c["old_pos"] == 2


def test_removed_before_any_heading_has_no_section():
    old = _blob(ingredients=[_ing(qty="1 cup", raw_text="flour", position=0),
                             _ing(is_heading=1, raw_text="For the sauce", position=1),
                             _ing(qty="1 cup", raw_text="cream", position=2)])
    new = _blob(ingredients=[_ing(is_heading=1, raw_text="For the sauce", position=1),
                             _ing(qty="1 cup", raw_text="cream", position=2)])
    (c,) = [c for c in diff_snapshots(old, new) if c["type"] == "removed"]
    assert c["label"] == "flour" and c["section"] is None   # sat before any heading -> list bottom


def test_removed_section_emitted_even_if_current_lacks_it():
    # The heading is RENAMED in current; O-c-0 still emits the ORIGINAL section (O-c-1 resolves the fallback).
    old = _blob(ingredients=[_ing(is_heading=1, raw_text="For the glaze", position=0),
                             _ing(qty="2 tbsp", raw_text="honey", position=1)])
    new = _blob(ingredients=[_ing(is_heading=1, raw_text="For the topping", position=0)])
    (c,) = [c for c in diff_snapshots(old, new) if c["kind"] == "ingredient" and c["type"] == "removed"]
    assert c["section"] == "For the glaze"                  # the ORIGINAL section, not current's "topping"


def test_step_positions_and_section():
    old = _blob(steps=[_step("Prep", position=0, is_heading=1),
                       _step("Chop onions", position=1), _step("Dice garlic", position=2)])
    new = _blob(steps=[_step("Prep", position=0, is_heading=1), _step("Chop onions", position=1)])
    (c,) = [c for c in diff_snapshots(old, new) if c["type"] == "removed"]
    assert c["kind"] == "step" and c["old_pos"] == 1 and c["section"] == "Prep"   # 2nd real step, under "Prep"


def test_step_modified_and_added_positions():
    old = _blob(steps=[_step("Preheat the oven", position=0)])
    new = _blob(steps=[_step("Preheat the oven to 400", position=0), _step("Grease the pan", position=1)])
    ch = diff_snapshots(old, new)
    mod = [c for c in ch if c["type"] == "modified"][0]
    add = [c for c in ch if c["type"] == "added"][0]
    assert mod["new_pos"] == 0 and mod["old_pos"] == 0
    assert add["new_pos"] == 1 and add["old_pos"] is None


def test_field_change_has_no_position():
    (c,) = diff_snapshots(_blob(recipe={"servings": "4"}), _blob(recipe={"servings": "6"}))
    assert "new_pos" not in c and "old_pos" not in c and "section" not in c   # named, not positional


# ---- moves emit NOTHING (_suppress_moves) --------------------------------------------------------
# A reordered row reads as delete-plus-insert by construction (LCS matching), so a pure reorder used to
# emit a removed+added pair for ~99% of rows — and BOTH halves render, showing the old row struck and
# the new one in ink for content that never changed. A final pass pairs them back up and drops both.

def test_reordering_two_ingredients_emits_nothing():
    a = _ing(qty="1 tsp", raw_text="salt", position=0)
    b = _ing(qty="2 cups", raw_text="flour", position=1)
    old = _blob(ingredients=[a, b])
    new = _blob(ingredients=[dict(b, position=0), dict(a, position=1)])
    assert diff_snapshots(old, new) == []


def test_reordering_two_steps_emits_nothing():
    a = _step("Preheat the oven to 400F", position=0)
    b = _step("Grease a 9-inch tin", position=1)
    old = _blob(steps=[a, b])
    new = _blob(steps=[dict(b, position=0), dict(a, position=1)])
    assert diff_snapshots(old, new) == []


def test_reorder_through_a_save_is_suppressed_despite_unit_recanonicalization():
    """THE PRODUCTION CASE — the one a raw-text comparison would fail.

    A real reorder happens through a SAVE, and the client re-canonicalizes units on every row. So the
    REMOVED entry carries the ORIGINAL snapshot's raw text ('1 litre …') while the ADDED entry carries
    the current rows ('1 liter …'). Comparing raw text passes every other reorder test in this file and
    then suppresses nothing at all in real use; the key must be canonical."""
    a = _ing(qty="1 litre", raw_text="filtered water", position=0)
    b = _ing(qty="5 tablespoons", raw_text="mirin", position=1)
    old = _blob(ingredients=[a, b])
    # the same two rows, swapped AND written back in canonical unit form (litre->liter, tablespoons->tbsp)
    new = _blob(ingredients=[_ing(qty="5 tbsp", raw_text="mirin", position=0),
                             _ing(qty="1 liter", raw_text="filtered water", position=1)])
    assert [c for c in diff_snapshots(old, new) if c["type"] in ("added", "removed")] == []
    assert diff_snapshots(old, new) == []


def test_move_across_a_section_heading_is_also_suppressed():
    """Per the ruling, ALL moves are suppressed — the removed entry's `section` is present and ignored.
    The acknowledged cost: an item changing which section it belongs to leaves no trace."""
    head_a = _ing(raw_text="FOR THE MARINADE:", is_heading=1, position=0)
    salt = _ing(qty="1 tsp", raw_text="salt", position=1)
    head_b = _ing(raw_text="FOR THE SAUCE:", is_heading=1, position=2)
    sugar = _ing(qty="1 tbsp", raw_text="sugar", position=3)
    old = _blob(ingredients=[head_a, salt, head_b, sugar])
    new = _blob(ingredients=[dict(head_a, position=0), dict(head_b, position=1),
                             dict(sugar, position=2), dict(salt, position=3)])
    assert diff_snapshots(old, new) == []
    # and the section WAS being carried before suppression — pin that the pass isn't hiding a bug
    entry = sd._removed("ingredient", "1 tsp salt", 0, "FOR THE MARINADE:")
    assert entry["section"] == "FOR THE MARINADE:"
    assert sd._suppress_moves([entry, sd._added("ingredient", "1 tsp salt", 1)]) == []


def test_moved_and_edited_is_NOT_suppressed():
    """A move that also changes the row must stay visible — the canonical key normalizes unit WORDS
    only, never numbers or names, so each of these still differs across the pair."""
    keep = _step("Rest the dough", position=0)
    for old_qty, new_qty in [("10 grams", "20 grams")]:              # amount changed
        old = _blob(ingredients=[_ing(qty=old_qty, raw_text="kombu", position=0),
                                 _ing(qty="1 tsp", raw_text="salt", position=1)], steps=[keep])
        new = _blob(ingredients=[_ing(qty="1 tsp", raw_text="salt", position=0),
                                 _ing(qty=new_qty, raw_text="kombu", position=1)], steps=[keep])
        types = sorted(c["type"] for c in diff_snapshots(old, new))
        assert types == ["added", "removed"], f"{old_qty}->{new_qty} should survive"

    for old_name, new_name in [("kombu (dried kelp)", "kombu (dried kelp), torn"),   # lightly reworded
                               ("kombu (dried kelp)", "wakame seaweed, fresh")]:      # heavily renamed
        old = _blob(ingredients=[_ing(qty="10 g", raw_text=old_name, position=0),
                                 _ing(qty="1 tsp", raw_text="salt", position=1)])
        new = _blob(ingredients=[_ing(qty="1 tsp", raw_text="salt", position=0),
                                 _ing(qty="10 g", raw_text=new_name, position=1)])
        ch = diff_snapshots(old, new)
        assert ch, f"{old_name!r}->{new_name!r} must not vanish"
        # raw values survive untouched — the pass drops entries, it never rewrites one
        for c in ch:
            assert old_name in json.dumps(c) or new_name in json.dumps(c)


def test_deleting_one_of_two_identical_rows_still_emits_its_removed():
    """The case that most LOOKS like a move: duplicate content, one copy deleted. The surviving twin
    still matches under LCS, so there is no `added` to pair with and the removal stays visible."""
    dup = _step("Lightly flour a work surface.", position=0)
    old = _blob(steps=[dup, _step("Roll it out", position=1), dict(dup, position=2)])
    new = _blob(steps=[_step("Roll it out", position=0), dict(dup, position=1)])
    (c,) = diff_snapshots(old, new)
    assert c["kind"] == "step" and c["type"] == "removed"
    assert c["text"] == "Lightly flour a work surface."


def test_suppression_is_greedy_one_to_one():
    """Two removed and one added sharing a key -> exactly ONE pair suppressed. Many-to-many would hide a
    genuine deletion whenever a different row with identical canonical text merely moved."""
    rem = [sd._removed("step", "Stir well", 0, None), sd._removed("step", "Stir well", 1, None)]
    add = [sd._added("step", "Stir well", 3)]
    out = sd._suppress_moves(rem + add)
    assert len(out) == 1 and out[0]["type"] == "removed"


def test_lone_removed_and_lone_added_both_survive():
    kept = sd._removed("step", "Chill overnight", 0, None)
    out = sd._suppress_moves([kept, sd._added("step", "Serve warm", 1)])
    assert [c["type"] for c in out] == ["removed", "added"]
    # different KINDS never pair, even with identical text
    out = sd._suppress_moves([sd._removed("ingredient", "salt", 0, None), sd._added("step", "salt", 0)])
    assert len(out) == 2
