"""notes.scan_step_mentions and notes.step_numbers, stated adversarially.

⚠️ WHY THIS FILE EXISTS. scan_step_mentions decides which words in a note become a link and which
stored reference each one belongs to, and it had no unit test at all. The pattern is deliberately
narrow (a step named by NUMBER, nothing else), and what it does with everything else had never been
written down: "step 0" matches and the zero is never validated, "steps 3 and 4" yields ONE reference
and the second number is unreachable, "step 03" reads as 3.

tests/fixtures/step-mention-cases.json is the shared half, asserted here and in
tests/js/step-mention-sync.test.js, so the Python pattern and the client's cannot drift apart.
"""
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import notes as notes_rules  # noqa: E402

FIX = json.loads((BASE / "tests" / "fixtures" / "step-mention-cases.json").read_text())


def test_the_fixture_is_what_the_python_side_actually_produces():
    """The client asserts this same file. A pattern change has to regenerate it, which is the point."""
    wrong = []
    for case in FIX["cases"]:
        got = notes_rules.scan_step_mentions(case["text"])
        if got != case["mentions"]:
            wrong.append((case["text"], got, case["mentions"]))
    assert not wrong, f"the fixture no longer matches scan_step_mentions: {wrong[:3]}"


def test_the_corpus_s_own_two_cases_are_in_the_fixture():
    texts = [c["text"] for c in FIX["cases"]]
    assert any("grated cheddar" in t for t in texts), "the aloo-potato-parathas case is gone"
    assert any("SAME DAY VERSION" in t for t in texts), "the bagel case is gone"


def _mentions(text):
    return [(m["ref_index"], m["match_text"], m["number"])
            for m in notes_rules.scan_step_mentions(text)]


def test_a_step_named_by_number_is_a_mention():
    assert _mentions("proceed with step 9.") == [(0, "step 9", 9)]
    assert _mentions("STEP 7") == [(0, "STEP 7", 7)]
    assert _mentions("step  9") == [(0, "step  9", 9)]
    assert _mentions("step\n9") == [(0, "step\n9", 9)]


def test_two_mentions_are_numbered_in_the_order_they_appear():
    assert _mentions("the step 10 and step 11") == [(0, "step 10", 10), (1, "step 11", 11)]


def test_a_word_that_merely_ends_in_step_is_not_a_mention():
    for text in ("misstep 3", "sidestep 4", "backstep 2", "stepping 3", "step_3"):
        assert _mentions(text) == [], text


def test_a_step_named_in_words_is_not_a_mention():
    """⚠️ DELIBERATELY NARROW. Measured over the 177 corpus paragraphs: 2 name a step by number and
    0 say "the step above", "see step" or "the first step". Every hit becomes a link, so a pattern
    that guessed at prose would put links on phrases nobody meant as a reference."""
    for text in ("step three", "steps", "step", "the step above", "see the previous step"):
        assert _mentions(text) == [], text


def test_the_second_number_in_steps_3_and_4_is_not_reached():
    """⚠️ ONE REFERENCE, NOT TWO, AND THIS IS THE KNOWN LIMIT. The pattern reads a number straight
    after the word, so "steps 3 and 4" links only the 3. The corpus has no case of it. Written down
    here because the behaviour was argued about in a comment and asserted nowhere, and because
    widening it is a decision about what a link means, not a bug fix."""
    assert _mentions("see steps 3 and 4") == [(0, "steps 3", 3)]


def test_a_leading_zero_and_a_zero_step_are_read_as_written():
    """Neither is validated against the recipe. The resolver is what decides whether a number names
    a step, and it answers None for one that does not, so a page cannot print a wrong link."""
    assert _mentions("step 03") == [(0, "step 03", 3)]
    assert _mentions("step 0") == [(0, "step 0", 0)]


def test_a_number_that_is_not_the_whole_word_is_not_a_mention():
    for text in ("step 12a", "step 2nd", "step-3", "step.3"):
        assert _mentions(text) == [], text


# ---- step_numbers: what the page prints beside each step ---------------------------------------

def _steps(*rows):
    return [{"id": i + 1, "is_heading": h, "text": t} for i, (h, t) in enumerate(rows)]


def test_a_heading_does_not_take_a_number_and_does_not_advance_the_count():
    """⚠️ THE HEADING HALF WAS COVERED AND THE COUNTER HALF WAS NOT. Every notes fixture happened to
    put the linked step before any heading, so a heading that silently consumed a number would have
    passed the suite and printed "step 3" beside the second step."""
    got = notes_rules.step_numbers(_steps((1, "FOR THE DOUGH"), (0, "Mix it."), (0, "Bake it.")))
    assert got == {1: None, 2: 1, 3: 2}


def test_a_heading_in_the_middle_leaves_the_sequence_unbroken():
    got = notes_rules.step_numbers(_steps(
        (0, "Mix it."), (1, "FOR THE FILLING"), (0, "Chop it."), (0, "Fold it.")))
    assert got == {1: 1, 2: None, 3: 2, 4: 3}


def test_a_reference_to_a_step_that_became_a_heading_resolves_to_no_number():
    steps = _steps((0, "Mix it."), (1, "FOR THE FILLING"))
    rows = [{"id": 7, "text": "see step 2", "step_id": 2, "refs":
             [{"ref_index": 0, "match_text": "step 2", "step_id": 2}]}]
    notes_rules.resolve(rows, steps)
    assert rows[0]["step_no"] is None
    assert rows[0]["refs"][0]["step_no"] is None
