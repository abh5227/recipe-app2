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


def ing(pos, *, heading=None, label=None, qty=None):
    """One ingredient row-like with ALL 11 keys present — a heading pins the other nine to null."""
    row = {k: None for k in SNAPSHOT_ING_FIELDS}
    row["position"], row["is_heading"] = pos, 1 if heading else 0
    if heading:
        row["raw_text"] = heading
    else:
        row["label"], row["qty"] = label, qty
        row["raw_text"] = f"{qty or ''} {label or ''}".strip()
    return row


def step(pos, text, heading=False):
    return {"position": pos, "is_heading": 1 if heading else 0, "text": text}


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
