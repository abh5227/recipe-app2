"""Pins the heading-layout sync transform (snapshot_headsync) and its content-safety postcondition.
Pure — no DB, no app, no fixtures: blobs in, a blob out.

The risk this file exists to contain: the transform rewrites the ONE thing the system treats as
immutable, and there is no second copy of a recipe's birth state. A bug that pulled content from the
CURRENT rows instead of the baseline would be silent, permanent, and indistinguishable from the user
having made those edits. test_heading_move_with_a_simultaneous_content_edit and its rename twin are
the tests that catch exactly that, and they are written so they fail loudly rather than quietly
passing on a coincidence.
"""
import json

import pytest

from snapshot_headsync import (
    HeadingSyncViolation, assert_content_safe, content_safety_problems, sync_heading_layout,
)
from snapshot_serialize import SNAPSHOT_ING_FIELDS, content_blob

RECIPE = {k: None for k in (
    "name", "author", "source_url", "category", "servings", "prep_time",
    "cook_time", "total_time", "descr", "notes", "image")}
RECIPE["name"] = "Test"


def ing(pos, *, heading=None, label=None, qty=None, id=None):
    """One ingredient row-like with EVERY snapshot key present — a heading pins the others to null."""
    row = {k: None for k in SNAPSHOT_ING_FIELDS}
    row["position"], row["is_heading"], row["id"] = pos, 1 if heading else 0, id
    if heading:
        row["raw_text"] = heading
    else:
        row["label"], row["qty"] = label, qty
        row["raw_text"] = f"{qty or ''} {label or ''}".strip()
    return row


def step(pos, text, heading=False, id=None):
    return {"id": id, "position": pos, "is_heading": 1 if heading else 0, "text": text}


def blob(ings, steps):
    return content_blob(RECIPE, ings, steps)


def rows(b, key):
    return json.loads(b)[key]


def texts(b, key, textkey):
    return [(r["is_heading"], r[textkey]) for r in rows(b, key)]


# ---- the four operations ------------------------------------------------------------------------

BASE_ING = [ing(0, heading="SAUCE"), ing(1, label="oil", qty="1 tbsp"), ing(2, label="garlic", qty="2")]
BASE_STEPS = [step(0, "MAKE IT", heading=True), step(1, "Heat the oil."), step(2, "Add garlic.")]
BASE = blob(BASE_ING, BASE_STEPS)


def test_move_a_heading_to_the_end():
    cur = [ing(0, label="oil"), ing(1, label="garlic"), ing(2, heading="SAUCE")]
    out = sync_heading_layout(BASE, cur, BASE_STEPS)
    assert texts(out, "ingredients", "raw_text") == [
        (0, "1 tbsp oil"), (0, "2 garlic"), (1, "SAUCE")]
    assert content_safety_problems(BASE, out) == []


def test_add_a_heading():
    cur = [ing(0, heading="SAUCE"), ing(1, label="oil"), ing(2, heading="EXTRA"), ing(3, label="garlic")]
    out = sync_heading_layout(BASE, cur, BASE_STEPS)
    assert texts(out, "ingredients", "raw_text") == [
        (1, "SAUCE"), (0, "1 tbsp oil"), (1, "EXTRA"), (0, "2 garlic")]
    assert content_safety_problems(BASE, out) == []


def test_remove_a_heading():
    cur = [ing(0, label="oil"), ing(1, label="garlic")]
    out = sync_heading_layout(BASE, cur, BASE_STEPS)
    assert texts(out, "ingredients", "raw_text") == [(0, "1 tbsp oil"), (0, "2 garlic")]
    assert content_safety_problems(BASE, out) == []


def test_rename_a_heading():
    cur = [ing(0, heading="THE SAUCE"), ing(1, label="oil"), ing(2, label="garlic")]
    out = sync_heading_layout(BASE, cur, BASE_STEPS)
    assert texts(out, "ingredients", "raw_text") == [
        (1, "THE SAUCE"), (0, "1 tbsp oil"), (0, "2 garlic")]
    assert content_safety_problems(BASE, out) == []


def test_step_headings_sync_the_same_way():
    cur_steps = [step(0, "Heat the oil."), step(1, "FINISH", heading=True), step(2, "Add garlic.")]
    out = sync_heading_layout(BASE, BASE_ING, cur_steps)
    assert texts(out, "steps", "text") == [
        (0, "Heat the oil."), (1, "FINISH"), (0, "Add garlic.")]
    assert content_safety_problems(BASE, out) == []


# ---- ⚠️ the adversarial pair: a heading change PLUS a content edit in the same save --------------

def test_heading_move_with_a_simultaneous_content_edit():
    """THE CATASTROPHIC CASE. Current has BOTH a moved heading AND edited content. The baseline's
    content is the recipe's birth state and must survive verbatim; only the heading layout moves.
    Written so it fails loudly if the transform ever sources content from `current`: the current rows
    carry values that appear NOWHERE in the expected output, so a wrong-side implementation cannot
    coincidentally pass."""
    cur = [
        ing(0, label="EDITED oil", qty="99 tbsp"),      # content edited since birth
        ing(1, label="EDITED garlic", qty="42"),
        ing(2, heading="SAUCE"),                        # and the heading moved to the end
    ]
    out = sync_heading_layout(BASE, cur, BASE_STEPS)

    assert texts(out, "ingredients", "raw_text") == [
        (0, "1 tbsp oil"), (0, "2 garlic"), (1, "SAUCE")], "baseline content must survive verbatim"
    body = json.dumps(json.loads(out))
    assert "EDITED" not in body and "99" not in body and "42" not in body, \
        "current's CONTENT leaked into the baseline — the birth state has been overwritten"
    assert content_safety_problems(BASE, out) == []


def test_heading_rename_with_a_simultaneous_content_edit():
    """The same trap in a second shape: a rename (not a move) alongside a content edit."""
    cur = [ing(0, heading="RENAMED"), ing(1, label="EDITED oil"), ing(2, label="EDITED garlic")]
    out = sync_heading_layout(BASE, cur, BASE_STEPS)
    assert texts(out, "ingredients", "raw_text") == [
        (1, "RENAMED"), (0, "1 tbsp oil"), (0, "2 garlic")]
    assert "EDITED" not in out
    assert content_safety_problems(BASE, out) == []


def test_content_added_since_birth_does_not_enter_the_baseline():
    """Current has MORE content rows than the baseline. The extra row is not part of the birth state
    and must not appear; the content-row count must be unchanged."""
    cur = [ing(0, heading="SAUCE"), ing(1, label="oil"), ing(2, label="garlic"), ing(3, label="BRAND NEW")]
    out = sync_heading_layout(BASE, cur, BASE_STEPS)
    assert "BRAND NEW" not in out
    assert len([r for r in rows(out, "ingredients") if not r["is_heading"]]) == 2
    assert content_safety_problems(BASE, out) == []


# ---- degenerate shapes --------------------------------------------------------------------------

def test_no_headings_at_all_is_identity_on_content_and_still_satisfies_p2():
    base = blob([ing(0, label="oil"), ing(1, label="garlic")], [step(0, "Do it.")])
    out = sync_heading_layout(base, [ing(0, label="oil"), ing(1, label="garlic")], [step(0, "Do it.")])
    assert out == base                                   # byte-identical: a true no-op
    assert content_safety_problems(base, out) == []


def test_all_headings_no_content_rows_does_not_crash_and_p1_is_vacuous():
    base = blob([ing(0, heading="A"), ing(1, heading="B")], [step(0, "X", heading=True)])
    cur = [ing(0, heading="B"), ing(1, heading="A")]     # reordered headings, no content anywhere
    out = sync_heading_layout(base, cur, [step(0, "X", heading=True)])
    assert texts(out, "ingredients", "raw_text") == [(1, "B"), (1, "A")]
    assert content_safety_problems(base, out) == []      # vacuously true — zero content rows


def test_empty_lists_survive():
    base = blob([], [])
    out = sync_heading_layout(base, [], [])
    assert out == base
    assert content_safety_problems(base, out) == []


# ---- positions ----------------------------------------------------------------------------------

@pytest.mark.parametrize("cur_ing, expect_len", [
    ([ing(0, heading="A"), ing(1, label="oil"), ing(2, heading="B"), ing(3, label="garlic")], 4),
    ([ing(0, label="oil"), ing(1, label="garlic")], 2),
    ([ing(0, heading="A"), ing(1, heading="B"), ing(2, label="oil"), ing(3, label="garlic")], 4),
])
def test_positions_renumber_to_a_contiguous_range(cur_ing, expect_len):
    out = sync_heading_layout(BASE, cur_ing, BASE_STEPS)
    got = [r["position"] for r in rows(out, "ingredients")]
    assert got == list(range(expect_len))
    assert content_safety_problems(BASE, out) == []


def test_content_positions_renumber_when_a_heading_moves():
    """The measured behaviour that forces P1 to project position out: moving a heading shifts every
    content row's position, so the content rows are NOT byte-identical including position."""
    cur = [ing(0, label="oil"), ing(1, label="garlic"), ing(2, heading="SAUCE")]
    out = sync_heading_layout(BASE, cur, BASE_STEPS)
    before = [r["position"] for r in rows(BASE, "ingredients") if not r["is_heading"]]
    after = [r["position"] for r in rows(out, "ingredients") if not r["is_heading"]]
    assert before == [1, 2] and after == [0, 1]          # they genuinely differ …
    assert content_safety_problems(BASE, out) == []      # … and P1 still passes


# ---- idempotence --------------------------------------------------------------------------------

def test_syncing_twice_is_byte_equal_to_syncing_once():
    cur = [ing(0, label="oil"), ing(1, heading="SAUCE"), ing(2, label="garlic")]
    once = sync_heading_layout(BASE, cur, BASE_STEPS)
    twice = sync_heading_layout(once, cur, BASE_STEPS)
    assert once == twice


def test_a_recipe_already_in_sync_is_a_byte_level_no_op():
    out = sync_heading_layout(BASE, BASE_ING, BASE_STEPS)
    assert out == BASE


# ---- the abort path -----------------------------------------------------------------------------

def _corrupt_transform(old_blob, current_ingredients, current_steps):
    """A deliberately WRONG transform: it takes content from `current` instead of the baseline —
    precisely the catastrophic bug. Used only to prove the checker catches it."""
    old = json.loads(old_blob)
    merged = [dict(r) for r in current_ingredients]
    for i, r in enumerate(merged):
        r["position"] = i
    return content_blob(old["recipe"], merged, json.loads(old_blob)["steps"])


def test_the_checker_names_the_problem_rather_than_returning_a_bare_false():
    cur = [ing(0, heading="SAUCE"), ing(1, label="EDITED oil"), ing(2, label="garlic")]
    bad = _corrupt_transform(BASE, cur, BASE_STEPS)
    problems = content_safety_problems(BASE, bad)
    assert problems, "the corrupted transform must be rejected"
    assert any("P1 ingredients[0]" in p for p in problems)
    assert any("label" in p for p in problems), f"the message must name the field: {problems}"


def test_assert_content_safe_raises_on_a_violating_transform():
    cur = [ing(0, heading="SAUCE"), ing(1, label="EDITED oil"), ing(2, label="garlic")]
    bad = _corrupt_transform(BASE, cur, BASE_STEPS)
    with pytest.raises(HeadingSyncViolation) as e:
        assert_content_safe(BASE, bad)
    assert "heading sync would alter content" in str(e.value)


def test_assert_content_safe_is_silent_on_a_correct_transform():
    cur = [ing(0, label="oil"), ing(1, heading="SAUCE"), ing(2, label="garlic")]
    assert_content_safe(BASE, sync_heading_layout(BASE, cur, BASE_STEPS))


def test_a_dropped_content_row_is_caught_by_count():
    dropped = content_blob(RECIPE, [ing(0, heading="SAUCE"), ing(1, label="oil")], BASE_STEPS)
    problems = content_safety_problems(BASE, dropped)
    assert any("content-row COUNT changed 2 -> 1" in p for p in problems)


def test_broken_positions_are_caught_by_p2():
    rowset = [ing(0, heading="SAUCE"), ing(5, label="oil", qty="1 tbsp"), ing(9, label="garlic", qty="2")]
    problems = content_safety_problems(BASE, content_blob(RECIPE, rowset, BASE_STEPS))
    assert any(p.startswith("P2 ingredients") for p in problems)


# ---- P3: the sync carries every key it does not interleave -------------------------------------
#
# ⚠️ THE BUG THESE PIN. sync_heading_layout rebuilt the blob by calling content_blob with THREE
# arguments. waits and storage default to None there, which OMITS the keys, so every save on a
# recipe that had them silently stripped both from its baseline. Measured on the round-3 preview
# copy: one save on morning-buns left its baseline with no waits key, and all six of that recipe's
# waits then reported as "added" in "your changes" for good. P1 and P2 read ingredients and steps
# only, so content_safety_problems reported no problem and the save went through.

WAITS = [{"id": None, "position": 0, "kind": "rising", "label": "1 hr", "min_minutes": 60, "max_minutes": 60,
          "ext_label": None, "ext_min_minutes": None, "ext_max_minutes": None,
          "when_kind": "always", "when_label": None}]
STORAGE = [{"id": None, "position": 0, "where_kept": "fridge", "applies_to": None, "label": "up to 1 week",
            "min_minutes": 0, "max_minutes": 10080}]


def test_the_heading_sync_carries_waits_and_storage_through():
    b = content_blob(RECIPE, BASE_ING, BASE_STEPS, WAITS, STORAGE)
    synced = sync_heading_layout(b, BASE_ING, BASE_STEPS)
    assert json.loads(synced)["waits"] == json.loads(b)["waits"]
    assert json.loads(synced)["storage"] == json.loads(b)["storage"]


def test_a_no_op_sync_is_byte_identical_when_a_recipe_has_waits():
    """The byte-equal short-circuit in _recipe_annotations protects all 300 baselines, and it only
    works if a sync that changes nothing changes nothing."""
    b = content_blob(RECIPE, BASE_ING, BASE_STEPS, WAITS, STORAGE)
    assert sync_heading_layout(b, BASE_ING, BASE_STEPS) == b


def test_the_guard_refuses_a_sync_that_drops_a_top_level_key():
    """P3, stated over the KEY SET rather than a list of known keys, so the next key added to the
    snapshot is covered before anyone remembers it."""
    b = content_blob(RECIPE, BASE_ING, BASE_STEPS, WAITS, STORAGE)
    stripped = content_blob(RECIPE, BASE_ING, BASE_STEPS)        # the old three-argument call
    problems = content_safety_problems(b, stripped)
    assert problems and any("P3" in p for p in problems)
    assert "waits" in problems[-1] and "storage" in problems[-1]
    with pytest.raises(HeadingSyncViolation):
        assert_content_safe(b, stripped)


def test_a_heading_move_still_syncs_with_waits_present():
    """The transform's actual job, with the new keys along for the ride: the heading layout follows
    current, the content rows survive verbatim, and waits and storage are untouched."""
    moved = [ing(0, label="oil", qty="1 tbsp"), ing(1, heading="SAUCE"), ing(2, label="garlic", qty="2")]
    b = content_blob(RECIPE, BASE_ING, BASE_STEPS, WAITS, STORAGE)
    synced = sync_heading_layout(b, moved, BASE_STEPS)
    assert content_safety_problems(b, synced) == []
    assert texts(synced, "ingredients", "raw_text") == [
        (0, "1 tbsp oil"), (1, "SAUCE"), (0, "2 garlic")]
    assert json.loads(synced)["waits"] == WAITS
    assert json.loads(synced)["storage"] == STORAGE


# --------------------------------------------------------------------------------------------- #
# Migration 052: a heading's TITLE, and the row it was converted from
# --------------------------------------------------------------------------------------------- #
def _conv_head(pos, *, title, label, source):
    """A heading converted from a line: its title in `heading`, the line's name still in `label`
    and the line's SOURCE TEXT still in raw_text. The shape migration 052 made possible."""
    row = {k: None for k in SNAPSHOT_ING_FIELDS}
    row.update(position=pos, is_heading=1, label=label, raw_text=source)
    row["heading"] = title
    return row


def test_a_copied_heading_carries_its_title_not_its_source_line():
    """⚠️ ONE PROJECTION, ONE PLACE. _reinterleave used a plain field copy and so wrote raw_text —
    the dormant SOURCE LINE — into the baseline as a section title. It now uses the snapshot's own
    row builder, the same one content_blob uses, so there is no second copy to drift."""
    base = content_blob(RECIPE, [ing(0, label="oil"), ing(1, label="garlic")], BASE_STEPS)
    # a heading whose name is NOT among the baseline's content rows, so the sync really does copy it
    cur = [ing(0, label="oil"),
           _conv_head(1, title="FOR THE BRINE", label="kosher salt",
                      source="1 teaspoon kosher salt"),
           ing(2, label="garlic")]
    out = json.loads(sync_heading_layout(base, cur, BASE_STEPS))
    heads = [r["raw_text"] for r in out["ingredients"] if r["is_heading"]]
    assert heads == ["FOR THE BRINE"]
    assert "1 teaspoon kosher salt" not in heads
    assert "heading" not in out["ingredients"][0], "the extra key must not enter the blob"
    assert_content_safe(base, json.dumps(out))


def test_a_converted_row_is_not_duplicated_into_the_baseline():
    """⚠️ THE BASELINE ALREADY HOLDS IT, AS A LINE. Copying current's heading in regardless left the
    same row in the baseline twice, as a content line and as a section title — a state the recipe
    was never in — and every further conversion save added another."""
    base = content_blob(RECIPE, [ing(0, label="oil"), ing(1, label="garlic")], BASE_STEPS)
    cur = [_conv_head(0, title="oil", label="oil", source="2 tbsp oil"), ing(1, label="garlic")]
    out = json.loads(sync_heading_layout(base, cur, BASE_STEPS))
    assert [r["raw_text"] for r in out["ingredients"] if r["is_heading"]] == []
    assert [r["label"] for r in out["ingredients"] if not r["is_heading"]] == ["oil", "garlic"]
    assert_content_safe(base, json.dumps(out))


def test_a_real_section_heading_is_still_copied_in():
    """The skip is narrow: only a heading that names one of the baseline's own content rows."""
    base = content_blob(RECIPE, [ing(0, label="oil"), ing(1, label="garlic")], BASE_STEPS)
    cur = [ing(0, heading="FOR THE SAUCE"), ing(1, label="oil"), ing(2, label="garlic")]
    out = json.loads(sync_heading_layout(base, cur, BASE_STEPS))
    assert [r["raw_text"] for r in out["ingredients"] if r["is_heading"]] == ["FOR THE SAUCE"]
    assert_content_safe(base, json.dumps(out))


# ---- option C commit 3: the baseline carries row ids ---------------------------------------------

def test_the_sync_carries_a_baseline_content_rows_id_through():
    """⚠️ THE IDS ARE THE POINT OF THE BASELINE NOW, and a sync rewrites the whole blob. A content
    row is copied from the baseline, so it keeps the id the backfill gave it — the sync has no
    business re-pointing a row it is not allowed to touch."""
    base = content_blob(RECIPE, [ing(0, label="oil", id=11), ing(1, label="garlic", id=12)],
                        BASE_STEPS)
    cur = [ing(0, heading="FOR THE SAUCE", id=99), ing(1, label="oil", id=11),
           ing(2, label="garlic", id=12)]
    out = json.loads(sync_heading_layout(base, cur, BASE_STEPS))
    assert [(r["label"], r["id"]) for r in out["ingredients"] if not r["is_heading"]] \
        == [("oil", 11), ("garlic", 12)]


def test_an_interleaved_heading_carries_the_live_rows_id():
    """A heading in the new blob IS the live row: the layout is replaced wholesale from current, so
    the id that comes with it is current's. `null` there would be a row the diff cannot place."""
    base = content_blob(RECIPE, [ing(0, label="oil", id=11)], BASE_STEPS)
    cur = [ing(0, heading="FOR THE SAUCE", id=99), ing(1, label="oil", id=11)]
    out = json.loads(sync_heading_layout(base, cur, BASE_STEPS))
    assert [(r["raw_text"], r["id"]) for r in out["ingredients"] if r["is_heading"]] \
        == [("FOR THE SAUCE", 99)]


def test_p4_refuses_a_transform_that_repoints_a_content_row():
    """⚠️ P1 PROJECTS `id` OUT, so without P4 a transform could hand back the right content under the
    wrong row identity — which after the id-matched diff lands would re-point every annotation on the
    recipe. The content here is byte-identical and only the id moves."""
    base = content_blob(RECIPE, [ing(0, label="oil", id=11), ing(1, label="garlic", id=12)],
                        BASE_STEPS)
    swapped = content_blob(RECIPE, [ing(0, label="oil", id=12), ing(1, label="garlic", id=11)],
                           BASE_STEPS)
    problems = content_safety_problems(base, swapped)
    assert [p for p in problems if p.startswith("P4")], problems
    with pytest.raises(HeadingSyncViolation):
        assert_content_safe(base, swapped)


def test_p1_tolerates_a_baseline_written_before_the_ids_existed():
    """⚠️ THE TOLERANT DIRECTION IS DELIBERATE. All 300 stored baselines were written without an `id`
    key, and the builder emits "id": null for such a row. A strict dict compare would fail P1 and
    abort the save with a 500 on a recipe whose content is perfectly intact, so an id the old row
    does not have may be filled in. An id it DOES have may not change (see P4)."""
    old = json.loads(content_blob(RECIPE, [ing(0, label="oil"), ing(1, label="garlic")], BASE_STEPS))
    for row in old["ingredients"] + old["steps"]:
        del row["id"]                                  # the pre-backfill shape, exactly
    old_blob = json.dumps(old, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    out = sync_heading_layout(old_blob, [ing(0, label="oil", id=11), ing(1, label="garlic", id=12)],
                              BASE_STEPS)
    assert content_safety_problems(old_blob, out) == []
    assert_content_safe(old_blob, out)
