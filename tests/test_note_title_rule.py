"""Is a note's leading label a TITLE? The rule, held before anything reads it.

⚠️ NOTHING CALLS import_cleanup.note_title_verdict YET, AND THIS FILE IS WHY IT IS SAFE TO LEAVE IT
THAT WAY. The rule produced reports/note-titles-candidates.csv, the review list Andy decides from.
The titles round will read those decisions and then this rule will have a caller. Until then the
tests are the only thing holding its answers still, so they are stated now rather than written
alongside the pass that will depend on them.

⚠️ AND "not a title" IS PINNED HERE AND NOWHERE ELSE. No note in the 300 opens with a discourse
marker, so that branch has no evidence in the corpus at all. A branch with no data behind it is
exactly the one that quietly stops working.
"""
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import import_cleanup as ic                                           # noqa: E402

verdict = lambda s: ic.note_title_verdict(s)[0]                       # noqa: E731


# --- a name is a title -----------------------------------------------------------------------

@pytest.mark.parametrize("label", [
    "Form a Pie Shell",        # all-butter-pie-crust, the case that started the question
    "Blind Bake",
    "Tomato Bouillon",
    "DASHI",
    "To Freeze the pie shell",
    "Measurements",
    "Kneading by hand",
])
def test_a_short_capitalized_name_is_a_title(label):
    assert verdict(label) == "title"


def test_the_reason_is_carried_so_a_review_list_can_say_why(label="Blind Bake"):
    kind, why = ic.note_title_verdict(label)
    assert kind == "title"
    assert "2-word" in why


# --- a discourse marker is not one ----------------------------------------------------------------

@pytest.mark.parametrize("label", ["Important", "Warning", "PS", "NB", "Caution", "Remember"])
def test_a_discourse_marker_names_nothing_and_is_not_a_title(label):
    # It adds emphasis. There is no heading in it, so there is nothing to promote.
    assert verdict(label) == "not a title"


def test_the_marker_test_ignores_case_and_trailing_punctuation():
    assert verdict("IMPORTANT") == "not a title"
    assert verdict("important.") == "not a title"


# --- anything it cannot defend goes to a person ---------------------------------------------------

@pytest.mark.parametrize("label,why", [
    ("If using fresh Yeast", "clause"),
    ("You can use Canned Chickpeas", "clause"),
    ("Don't over-mix the batter", "clause"),
    ("When the dough is cold", "clause"),
    ("One two three four five six", "longer than a heading"),
    ("a lowercase thing", "capital"),
])
def test_a_label_the_rule_cannot_defend_is_unclear_with_a_reason(label, why):
    kind, reason = ic.note_title_verdict(label)
    assert kind == "unclear"
    assert why in reason


def test_a_curly_apostrophe_reads_as_a_straight_one():
    # The corpus holds both, and a clause word spelled with the curly form is the same clause word.
    assert verdict("Don’t over-mix the batter") == "unclear"


def test_an_empty_label_is_unclear_rather_than_a_crash():
    assert verdict("") == "unclear"
    assert verdict(None) == "unclear"
    assert verdict("   ") == "unclear"


def test_five_words_is_in_and_six_is_out():
    # The boundary is stated, so moving it is a decision rather than an accident.
    assert ic.NOTE_TITLE_MAX_WORDS == 5
    assert verdict("One Two Three Four Five") == "title"
    assert verdict("One Two Three Four Five Six") == "unclear"


# --- it reads the same "leading label" the rest of the app does -----------------------------------

def test_the_lead_is_the_one_note_kind_already_reads():
    assert ic.note_lead("Blind Bake: put the weights in.") == ("Blind Bake", "put the weights in.")
    assert ic.note_lead("Flour. This recipe works best with bread flour.") == (
        "Flour", "This recipe works best with bread flour.")
    assert ic.note_lead("No label here at all") is None


def test_a_label_the_kind_table_knows_is_a_KIND_and_not_a_title():
    """⚠️ THE TWO QUESTIONS ARE DIFFERENT AND BOTH HAVE TO BE ASKED. "Tip" passes the title rule on
    its shape, and it is the name of a kind: promoting it to a heading would print "TIPS" over a
    note whose own first word is "Tip". The caller asks note_label_is_known first."""
    assert verdict("Tip") == "title", "on shape alone it looks like one"
    assert ic.note_label_is_known("Tip") is True
    assert ic.note_label_is_known("Storing") is True, "a kind's other spellings count too"
    assert ic.note_label_is_known("Blind Bake") is False


def test_nothing_in_the_repo_calls_the_rule_yet():
    """⚠️ THE POINT OF MOVING IT HERE WAS TO KEEP IT, NOT TO RUN IT. A caller appearing by accident
    would turn a review list Andy has not decided yet into data. When the titles round lands, this
    test is the one that should fail and be deleted on purpose."""
    import subprocess
    out = set(subprocess.run(
        ["git", "grep", "-l", "-e", "note_title_verdict", "-e", "note_label_is_known",
         "--", "*.py"],
        cwd=BASE, capture_output=True, text=True).stdout.split())
    # A SUBSET check, not an equality one: git grep reads TRACKED files, so a file still being
    # written is simply absent and must not fail the run for the wrong reason.
    allowed = {"import_cleanup.py", "tests/test_note_title_rule.py"}
    assert out <= allowed, f"something new reads the title rule: {sorted(out - allowed)}"
