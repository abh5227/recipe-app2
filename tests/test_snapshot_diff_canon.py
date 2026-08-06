"""O-c-1 fix: diff_snapshots compares AMOUNTS by canonical unit form, so a representation-only unit
difference (the client re-canonicalizes units on every save — "1 teaspoon" is stored back as "1 tsp")
does NOT read as an amount change. A GENUINE amount change (different number) still emits, with the RAW
from/to. Pins the phantom-kill without masking real edits."""
import snapshot_diff as sd
from snapshot_diff import diff_snapshots
from test_snapshot_diff import _blob, _ing   # reuse the pure blob/ingredient builders


def _amounts(ch):
    return [c for c in ch if c.get("kind") == "ingredient" and c.get("type") == "modified"
            and c.get("field") == "amount"]


def test_representation_only_unit_change_is_not_an_amount_change():
    # baseline stored the full word; save canonicalized the unit -> current is "1 tsp". Same amount.
    old = _blob(ingredients=[_ing(ingredient_id="pep", label="peppercorns", qty="1 teaspoon",
                                  quantity="1", unit="teaspoon", raw_text="1 teaspoon peppercorns")])
    new = _blob(ingredients=[_ing(ingredient_id="pep", label="peppercorns", qty="1 tsp",
                                  quantity="1", unit="tsp", raw_text="1 tsp peppercorns")])
    assert diff_snapshots(old, new) == []            # canonical forms equal -> no phantom at all


def test_genuine_amount_change_still_emits_with_raw_values():
    old = _blob(ingredients=[_ing(ingredient_id="salt", label="salt", qty="1 tsp", quantity="1", unit="tsp")])
    new = _blob(ingredients=[_ing(ingredient_id="salt", label="salt", qty="2 tsp", quantity="2", unit="tsp")])
    amt = _amounts(diff_snapshots(old, new))
    assert len(amt) == 1
    assert amt[0]["from"] == "1 tsp" and amt[0]["to"] == "2 tsp"   # detection canonical, values RAW


def test_mixed_unit_abbrev_and_number_change_emits_raw():
    # unit abbreviates AND the number changes -> a real change; emit with the raw strings verbatim.
    old = _blob(ingredients=[_ing(ingredient_id="cumin", label="cumin", qty="1 teaspoon",
                                  quantity="1", unit="teaspoon")])
    new = _blob(ingredients=[_ing(ingredient_id="cumin", label="cumin", qty="2 tsp",
                                  quantity="2", unit="tsp")])
    amt = _amounts(diff_snapshots(old, new))
    assert len(amt) == 1
    assert amt[0]["from"] == "1 teaspoon" and amt[0]["to"] == "2 tsp"


def _names(ch):
    return [c for c in ch if c.get("kind") == "ingredient" and c.get("type") == "modified"
            and c.get("field") == "name"]


def test_rename_with_unit_drift_stays_ONE_name_change_not_split():
    # THE regression (Fix A): a real save canonicalizes the unit (teaspoon->tsp) AND the user renames.
    # Raw full-line similarity ("1 teaspoon kosher salt" vs "1 tsp sea salt") is 0.556 < 0.6 -> the pair
    # used to split into remove+add (a silent replacement). Canonicalizing the qty in the MATCH key lifts
    # it back above threshold -> ONE name/modified, with the RAW from/to.
    old = _blob(ingredients=[_ing(qty="1 teaspoon", quantity="1", unit="teaspoon", raw_text="kosher salt")])
    new = _blob(ingredients=[_ing(qty="1 tsp", quantity="1", unit="tsp", raw_text="sea salt")])
    ch = diff_snapshots(old, new)
    assert not [c for c in ch if c.get("type") in ("removed", "added")]   # NOT split
    names = _names(ch)
    assert len(names) == 1
    assert names[0]["from"] == "kosher salt" and names[0]["to"] == "sea salt"


def test_word_removal_rename_with_unit_drift_stays_name_change():
    # The already-working case must NOT regress: dropping one word, with unit drift, stays one name/modified.
    old = _blob(ingredients=[_ing(qty="1 teaspoon", quantity="1", unit="teaspoon", raw_text="whole black peppercorns")])
    new = _blob(ingredients=[_ing(qty="1 tsp", quantity="1", unit="tsp", raw_text="black peppercorns")])
    names = _names(diff_snapshots(old, new))
    assert len(names) == 1
    assert names[0]["from"] == "whole black peppercorns" and names[0]["to"] == "black peppercorns"


def test_unrelated_rows_still_split_remove_add_after_canon():
    # Guard the threshold still discriminates: a genuinely different pair (shares almost nothing) stays
    # remove+add even with the qty canonicalized — canonicalizing the qty must not over-match real renames.
    old = _blob(ingredients=[_ing(qty="1 teaspoon", quantity="1", unit="teaspoon", raw_text="kosher salt")])
    new = _blob(ingredients=[_ing(qty="3 large", quantity="3", unit="large", raw_text="eggs")])
    ch = diff_snapshots(old, new)
    types = sorted(c["type"] for c in ch if c["kind"] == "ingredient")
    assert types == ["added", "removed"]                          # still split, not a modify
    assert not _names(ch)


def test_unlinked_full_word_baseline_save_yields_zero_amount_changes():
    # Regression for the reported phantom: a whole (unlinked) recipe with full-word spoon units, "saved"
    # (units canonicalized) with ONE real edit -> only that edit diffs, no phantom on the untouched rows.
    def rows(pep, tur, salt, bay):
        return [
            _ing(qty="½ cup", quantity="½", unit="cup", raw_text="split mung beans", position=0),
            _ing(qty=bay, quantity=bay.split()[0], unit="", raw_text="bay leaf", position=1),
            _ing(qty=pep, quantity="1", unit=pep.split(" ", 1)[1], raw_text="peppercorns", position=2),
            _ing(qty=tur, quantity="1", unit=tur.split(" ", 1)[1], raw_text="turmeric", position=3),
            _ing(qty=salt, quantity="1", unit=salt.split(" ", 1)[1], raw_text="kosher salt", position=4),
            _ing(qty="pinch", quantity="", unit="pinch", raw_text="asafetida", position=5),
        ]
    old = _blob(ingredients=rows("1 teaspoon", "1 teaspoon", "1 teaspoon", "1"))
    new = _blob(ingredients=rows("1 tsp", "1 tsp", "1 tsp", "2"))   # units canonicalized + bay leaf 1->2
    amt = _amounts(diff_snapshots(old, new))
    assert len(amt) == 1                              # ONLY the real bay-leaf edit
    assert amt[0]["from"] == "1" and amt[0]["to"] == "2" and amt[0]["label"] == "bay leaf"
