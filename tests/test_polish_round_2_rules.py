"""The rules polish round 2 added, each stated over the shape rather than over the corpus row.

Every one of these answers a question a person asked once and a rule has to answer forever. The
corpus cases are named in the docstrings so the next reader can find the row that prompted the rule,
and the refusals are tested as hard as the admissions, because every one of these rules is one bad
match away from rewriting a sentence the author meant.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import import_cleanup as ic                                                   # noqa: E402


# ---- the author's lettering ---------------------------------------------------------------------

def test_a_run_of_letters_from_a_is_the_authors_list():
    """karak-chai's steps 9 to 11, under the author's own heading "Repeat this 3-5 times to make the
    texture velvety:". The app draws its own marker, so the author's is drawn twice."""
    out, runs = ic.strip_author_letters([
        "a. Bring the pot to a boil so the chai foams up",
        "b. Remove the pot from the stove so that the foam dies down",
        "c. Once the pot has stopped boiling completely, place this back on the stove",
    ])
    assert out == ["Bring the pot to a boil so the chai foams up",
                   "Remove the pot from the stove so that the foam dies down",
                   "Once the pot has stopped boiling completely, place this back on the stove"]
    assert runs == [(0, ["a", "b", "c"])]


@pytest.mark.parametrize("marker", ["a.", "a)", "(a)", "A."])
def test_every_marker_shape_the_author_might_use(marker):
    out, runs = ic.strip_author_letters([f"{marker} First thing", "b. Second thing"])
    assert out == ["First thing", "Second thing"]
    assert len(runs) == 1


def test_a_lone_letter_is_not_a_list():
    """⚠️ THE RUN IS THE EVIDENCE, exactly as it is for a number. One step opening "a." in a recipe
    that is not lettered is a sentence that happens to start that way."""
    assert ic.strip_author_letters(["a. Bring the pot to a boil", "Then strain it"]) == (
        ["a. Bring the pot to a boil", "Then strain it"], [])


def test_a_run_that_does_not_open_at_a_is_not_a_list():
    """Starting at "b" means the list's own first item is missing, which is evidence that these are
    not the list rather than evidence that one was dropped."""
    out, runs = ic.strip_author_letters(["b. Remove the pot", "c. Place it back"])
    assert out == ["b. Remove the pot", "c. Place it back"]
    assert runs == []


def test_a_gap_breaks_the_run():
    out, runs = ic.strip_author_letters(["a. First", "c. Third", "d. Fourth"])
    assert out == ["a. First", "c. Third", "d. Fourth"]
    assert runs == []


@pytest.mark.parametrize("text", [
    "a large onion, diced",            # no separator after the letter
    "a.m. start the dough",            # no space after the stop
    "I like it hot",                   # a word, not a marker
])
def test_the_shapes_that_look_like_a_marker_and_are_not(text):
    """⚠️ MEASURED OVER THE 2,223 ORDINARY STEPS: the pattern matches 3 of them, all three
    karak-chai's. These are the near misses it has to keep refusing."""
    assert ic.author_step_letter(text) is None
    assert ic.strip_author_letters([text, "b. Second thing"])[1] == []


def test_two_separate_runs_in_one_recipe_are_both_read():
    """Lettering is a sub-list under one step, so a recipe may carry several. The author's NUMBERING
    is all-or-nothing per recipe because it runs over every step, and this is the difference."""
    out, runs = ic.strip_author_letters([
        "a. First of the first", "b. Second of the first",
        "Now do the other thing",
        "a. First of the second", "b. Second of the second"])
    assert out == ["First of the first", "Second of the first", "Now do the other thing",
                   "First of the second", "Second of the second"]
    assert runs == [(0, ["a", "b"]), (3, ["a", "b"])]


# ---- the author's numbering, restarting under each heading --------------------------------------

def test_numbering_that_restarts_under_a_heading_is_still_a_sequence():
    """⚠️ READ OVER THE WHOLE RECIPE THIS IS 1, 2, 1, 2 AND IS REFUSED. Split at the headings and
    each section is its own list, which is what Andy's rule says."""
    rows = [(True, "Make the dough"), (False, "1. Mix the flour"), (False, "2. Knead it"),
            (True, "Cooking"), (False, "1. Boil the water"), (False, "2. Cook the pasta")]
    assert ic.strip_author_numbers_by_section(rows) == [
        "Make the dough", "Mix the flour", "Knead it",
        "Cooking", "Boil the water", "Cook the pasta"]


def test_a_single_number_directly_under_a_heading_is_the_author_opening_a_list():
    """homemade-pasta-dough's "Cooking" section holds one step, "1. bring a salted water to a boil".
    The whole-recipe rule needs two numbers because it has no other evidence; the heading IS the
    other evidence that a list starts here."""
    rows = [(False, "Weigh & combine flour (s) in a bowl"), (True, "Cooking"),
            (False, "1. bring a salted water to a boil & cook for about 3-4 mins.")]
    assert ic.strip_author_numbers_by_section(rows)[2] == (
        "bring a salted water to a boil & cook for about 3-4 mins.")


def test_a_run_of_one_whose_number_is_followed_by_a_figure_is_refused():
    """⚠️ A RUN OF ONE HAS NO NEIGHBOURS TO CORROBORATE IT, so the one shape that could make it a
    measurement is refused outright. "1. 5 cups water" keeps its number."""
    rows = [(True, "Ingredients"), (False, "1. 5 cups water")]
    assert ic.strip_author_numbers_by_section(rows) == ["Ingredients", "1. 5 cups water"]


def test_a_section_whose_numbers_do_not_run_from_one_is_left_alone():
    rows = [(True, "Cooking"), (False, "2. Boil the water"), (False, "3. Cook the pasta")]
    assert ic.strip_author_numbers_by_section(rows) == [
        "Cooking", "2. Boil the water", "3. Cook the pasta"]


def test_the_whole_recipe_reading_still_wins_where_it_fires():
    """A recipe numbered straight through, with a heading in the middle that does not restart it.
    The per-section pass must not re-read what the whole-recipe pass already took."""
    rows = [(False, "1. Mix the flour"), (False, "2. Knead it"), (True, "Cooking"),
            (False, "3. Boil the water"), (False, "4. Cook the pasta")]
    assert ic.strip_author_numbers_by_section(rows) == [
        "Mix the flour", "Knead it", "Cooking", "Boil the water", "Cook the pasta"]


def test_a_recipe_with_no_numbering_at_all_is_untouched():
    rows = [(True, "Cooking"), (False, "2 cups flour, sifted"), (False, "Boil the water")]
    assert ic.strip_author_numbers_by_section(rows) == [
        "Cooking", "2 cups flour, sifted", "Boil the water"]


# ---- a step after a heading is not a continuation ------------------------------------------------

def test_a_heading_above_a_step_does_not_make_it_a_continuation():
    """⚠️ THE TEST IS "THE ROW ABOVE DOES NOT END IN TERMINAL PUNCTUATION", AND A HEADING NEVER DOES,
    so every first step of every section read as the tail of a sentence and stayed lowercase."""
    assert ic.continues_the_line_above("Cooking", True) is False


def test_an_unfinished_step_above_still_makes_it_a_continuation():
    """homemade-pasta-dough's step 1 was split by the import, so "consistency forms." is its own row
    and really is the tail of the line above it."""
    assert ic.continues_the_line_above(
        "gradually incorporate the flour until a thick, batter-like", False) is True


@pytest.mark.parametrize("prev", ["Mix it well.", "Is it smooth?", "Stop!", "Do this:", "And this;"])
def test_a_finished_step_above_leaves_the_next_one_to_be_capitalized(prev):
    assert ic.continues_the_line_above(prev, False) is False


def test_nothing_above_is_not_a_continuation():
    assert ic.continues_the_line_above(None, False) is False


# ---- a note's label that names its own kind ------------------------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("Note: the dough is sticky.", "notes"),
    ("Notes: the dough is sticky.", "notes"),
    ("Tip: chill the bowl first.", "tips"),
    ("Storage: keep it covered.", "storage"),
    ("Storing: keep it covered.", "storage"),
    ("Variation: swap the herbs.", "variations"),
    ("VARIATION: swap the herbs.", "variations"),
])
def test_a_label_that_only_restates_the_kind_comes_off(text, kind):
    """The page prints the kind's header over the group, so the label says it twice.

    ⚠️ "Storing" IS ON THIS LIST BY ANDY'S CALL, 2026-10-08, AND WAS A TITLE BEFORE IT. The first
    version of the rule compared the label against the kind's name with a plural rule, which titled
    "Storing" on the grounds that it is not spelled "Storage". Which gerunds are really the kind's
    name is a judgement about words, so it is written down in static/note-kinds.json now rather than
    derived here."""
    plan = ic.note_label_plan(text)
    assert plan.verdict == "restates the kind"
    assert plan.kind == kind
    assert plan.title is None
    assert not plan.text.lower().startswith(("note", "tip", "storage", "variation"))


@pytest.mark.parametrize("text,title,kind", [
    ("To Store: keep it cold.", "To Store", "storage"),
    ("To Freeze: wrap it twice.", "To Freeze", "storage"),
    ("Freezer: up to three months.", "Freezer", "storage"),
    ("Freezing: lay them flat.", "Freezing", "storage"),
    ("Leftovers: they keep two days.", "Leftovers", "storage"),
    ("Note for next time: more salt.", "Note for next time", "notes"),
    ("NOTE FOR NEXT TIME: more salt.", "Note for next time", "notes"),
    ("COOK'S NOTE: taste as you go.", "Cook's note", "notes"),
    ("SAME DAY VERSION: increase water to ~354 grams.", "Same day version", "variations"),
    ("Reminder: the dough needs an hour.", "Reminder", "notes"),
])
def test_a_label_that_says_more_than_the_kind_becomes_the_title(text, title, kind):
    """⚠️ all-butter-pie-crust CARRIES BOTH "To Store" AND "To Freeze", two notes of one kind, which
    is exactly the pair a title exists to tell apart. The heading case rule brings ALL CAPS down and
    leaves anything the author already cased alone."""
    plan = ic.note_label_plan(text)
    assert plan.verdict == "says more than the kind"
    assert (plan.title, plan.kind) == (title, kind)
    assert not plan.text.startswith(plan.label)


@pytest.mark.parametrize("text", [
    "Blind Bake: line the tin with foil.",
    "Tomato Bouillon: a cube dissolved in water.",
    "Borlotti: they cook faster than kidney beans.",
    "The dough will be sticky at first.",
])
def test_an_unlisted_label_is_not_read_at_all(text):
    """⚠️ 27 OF THE 177 CORPUS PARAGRAPHS LEAD WITH A LABEL THE KIND TABLE DOES NOT KNOW. Stripping
    one would delete the only thing naming what the note is about."""
    assert ic.note_label_plan(text) is None


def test_the_body_is_the_whole_paragraph_minus_the_label():
    """⚠️ READING FROM THE END OF THE MATCH RETURNS AN EMPTY STRING, because the pattern consumes the
    whole paragraph. A rule that silently empties a note is not a rule anyone would notice."""
    plan = ic.note_label_plan("Note: the dough is sticky. Flour your hands.")
    assert plan.text == "the dough is sticky. Flour your hands."


# ---- the footnote that became a step -------------------------------------------------------------

def test_a_footnote_step_moves_to_a_note_and_the_marker_comes_off():
    """stir-fried-green-beans-with-pork steps 3650 and 3651. The marker points at a step rather than
    at the aside, and the app has no footnotes: a note LINKED to the step is what it has instead."""
    got = ic.footnote_step_plan(
        "It takes about 5-8 minutes to cook the green beans this way*. Transfer them.",
        "*Turn the heat lower if needed to avoid burning.")
    assert got == ("Turn the heat lower if needed to avoid burning.",
                   "It takes about 5-8 minutes to cook the green beans this way. Transfer them.")


def test_a_step_that_merely_contains_an_asterisk_is_not_a_footnote():
    assert ic.footnote_step_plan("cook this way*. Transfer.", "Then add the meat*.") is None


def test_a_footnote_needs_a_marker_above_it_too():
    """Both halves of the evidence, or an aside the author wrote with a bullet becomes a note."""
    assert ic.footnote_step_plan("Cook for five minutes.", "*Turn the heat lower.") is None


@pytest.mark.parametrize("text,marks", [
    ("cook this way*. Transfer", [13]),
    ("*Turn the heat lower", [0]),
    ("*Sui mi ya cai* is a pickle", []),
    ("no marker here", []),
    ("*one* and a half*", [16]),
])
def test_paired_asterisks_are_emphasis_and_only_an_unpaired_one_is_a_marker(text, marks):
    """⚠️ "*Sui mi ya cai*" WRAPS A PHRASE, which is what strip_wrapping_marks reads. Measured over
    the corpus: 3 steps in the 300 contain an asterisk at all."""
    assert ic.unpaired_footnote_marks(text) == marks


def test_stripping_a_marker_tidies_the_spacing_it_leaves():
    assert ic.strip_footnote_markers("for 70-90 seconds* (until set)") == (
        "for 70-90 seconds (until set)")
    assert ic.strip_footnote_markers("*Sui mi ya cai* stays") == "*Sui mi ya cai* stays"


# ---- "Optional:" on an ingredient line ----------------------------------------------------------

def _rows(*texts):
    return [{"id": i + 1, "is_heading": 0, "text": t} for i, t in enumerate(texts)]


def test_consecutive_optional_lines_become_one_group():
    """quick-easy-hainanese-chicken-rice-khao-mun-gai rows 5163 and 5164. The word is doing a
    heading's job on every line instead of once above them."""
    rows = _rows("2 Tbsp chopped ginger",
                 "Optional: Extra chicken stock for serving on the side",
                 "Optional: Fresh cucumber slices for serving")
    groups = ic.optional_ingredient_groups(rows)
    assert len(groups) == 1
    assert groups[0]["at"] == 1
    assert groups[0]["heading_id"] is None
    assert groups[0]["lines"] == [(2, "extra chicken stock for serving on the side"),
                                  (3, "fresh cucumber slices for serving")]


def test_a_heading_already_there_is_used_rather_than_a_second_one_inserted():
    rows = [{"id": 1, "is_heading": 1, "text": "Optional"},
            {"id": 2, "is_heading": 0, "text": "Optional: Extra stock"}]
    groups = ic.optional_ingredient_groups(rows)
    assert groups[0]["heading_id"] == 1


def test_two_runs_separated_by_a_heading_are_two_groups():
    """⚠️ CONSECUTIVE LINES SHARE ONE HEADING, which is why a heading between them ends the run."""
    rows = [{"id": 1, "is_heading": 0, "text": "Optional: a"},
            {"id": 2, "is_heading": 1, "text": "For the sauce"},
            {"id": 3, "is_heading": 0, "text": "Optional: b"}]
    groups = ic.optional_ingredient_groups(rows)
    assert [g["at"] for g in groups] == [0, 2]


def test_a_line_that_merely_mentions_optional_is_not_in_a_group():
    """"1 Thai chili, optional, to taste" is the corpus near miss. The prefix has to be at the FRONT
    and carry its colon."""
    assert ic.optional_ingredient_groups(_rows("1 Thai chili, optional, to taste")) == []
    assert ic.optional_ingredient_groups(_rows("5-6 slices ginger, optional")) == []


def test_the_first_word_is_lowercased_unless_it_is_a_name():
    """The same exception lists ingredient_name_case applies. A line that has just lost a prefix is a
    name this round is already rewriting, so the blanket lowercase is safe here."""
    assert ic.lower_lead_word("Extra chicken stock") == "extra chicken stock"
    assert ic.lower_lead_word("Thai chilies, sliced") == "Thai chilies, sliced"
    assert ic.lower_lead_word("MSG, a pinch") == "MSG, a pinch"
    assert ic.lower_lead_word("already lowercase") == "already lowercase"


def test_a_heading_row_is_never_read_as_an_optional_line():
    rows = [{"id": 1, "is_heading": 1, "text": "Optional: extras"}]
    assert ic.optional_ingredient_groups(rows) == []


# ---- the importer runs every one of these, which is clause (2) of FIX BY RULE -------------------

import import_write                                                           # noqa: E402


def test_the_importer_strips_lettering_and_makes_its_parent_a_heading():
    """⚠️ THE PARENT CLAUSE FIRES ZERO TIMES ON THIS CORPUS and is here for the importer.
    karak-chai's parent ends in a colon, which rule 2 already reads as a heading. A parent with no
    colon has only the letter run below it as evidence."""
    rows, _notes, conv = ic.plan_step_rows([
        "Repeat this a few times", "a. Bring the pot to a boil", "b. Remove the pot"])
    assert [(r["is_heading"], r["text"]) for r in rows] == [
        (1, "Repeat this a few times"), (0, "Bring the pot to a boil"), (0, "Remove the pot")]
    assert [c["flag"] for c in conv].count("step_letters_stripped") == 2


def test_the_importer_reads_numbering_that_restarts_under_each_heading():
    """It could not do this where the numbers come off, at the top, because no row was a heading yet.
    Over the whole list these read 1, 2, 1 and are correctly refused there."""
    rows, _n, conv = ic.plan_step_rows([
        "MAKE THE DOUGH:", "1. Mix the flour", "2. Knead it", "COOKING:", "1. Boil the water"])
    assert [r["text"] for r in rows] == [
        "Make the dough:", "Mix the flour", "Knead it", "Cooking:", "Boil the water"]
    assert [c["flag"] for c in conv].count("step_numbers_restarted") == 3


def test_the_importer_moves_a_footnote_step_into_the_notes_and_takes_the_marker_off():
    rows, notes, conv = ic.plan_step_rows([
        "It takes about 5-8 minutes this way*. Transfer them.",
        "*Turn the heat lower if needed to avoid burning."])
    assert [r["text"] for r in rows] == ["It takes about 5-8 minutes this way. Transfer them."]
    assert notes == "Turn the heat lower if needed to avoid burning."
    moved = [c for c in conv if c["flag"] == "step_footnote_moved"]
    assert len(moved) == 1
    assert "footnote of:" in moved[0]["detail"], moved[0]["detail"]


def test_the_importer_takes_off_a_marker_with_no_footnote_under_it():
    rows, _n, conv = ic.plan_step_rows(["Cook in microwave for 70-90 seconds* (until set)."])
    assert rows[0]["text"] == "Cook in microwave for 70-90 seconds (until set)."
    assert [c["flag"] for c in conv] == ["step_footnote_marker_dangling"]


def test_the_importer_leaves_paired_emphasis_alone():
    """A whole step wrapped in emphasis is rule 1's business and becomes a heading. What matters here
    is that the dangling-marker rule does not reach inside a *wrapped phrase*."""
    rows, _n, conv = ic.plan_step_rows(["Stir in the *sui mi ya cai* at the end."])
    assert rows[0]["text"] == "Stir in the *sui mi ya cai* at the end."
    assert "step_footnote_marker_dangling" not in [c["flag"] for c in conv]


def test_the_importer_gives_an_optional_run_its_heading():
    rows, flags, _moved = import_write._group_optional_lines([
        {"position": 0, "is_heading": 0, "label": "chopped ginger", "raw_text": "2 Tbsp chopped ginger",
         "qty": "2 Tbsp", "quantity": "2", "unit": "Tbsp", "note": None, "ingredient_id": None,
         "grams": None, "secondary_measure": None},
        {"position": 1, "is_heading": 0, "label": "Optional: Extra chicken stock",
         "raw_text": "Optional: Extra chicken stock", "qty": None, "quantity": None, "unit": None,
         "note": None, "ingredient_id": None, "grams": None, "secondary_measure": None},
    ])
    assert [(r["is_heading"], r["raw_text"], r["position"]) for r in rows] == [
        (0, "2 Tbsp chopped ginger", 0), (1, "Optional", 1), (0, "Optional: Extra chicken stock", 2)]
    assert rows[2]["label"] == "extra chicken stock", "the prefix comes off the DISPLAYED name"
    assert [f["flag"] for f in flags] == ["ingredient_optional_grouped"]


def test_the_importer_lowercases_a_new_name_and_flags_a_title_cased_one():
    """⚠️ THE BLANKET RULE IS FOR AN IMPORT ONLY. ingredient_name_case needs evidence before it
    lowercases, and a line arriving for the first time has none, so it correctly answers "uncertain"
    and changes nothing. For a new import that is the wrong default, so the evidence is assumed and
    the one shape it cannot help with is flagged."""
    rows, flags = import_write._lowercase_ingredient_names([
        {"position": 0, "is_heading": 0, "label": "Salt to taste", "raw_text": "Salt to taste"},
        {"position": 1, "is_heading": 0, "label": "Fresh Parsley, chopped",
         "raw_text": "1 bunch Fresh Parsley, chopped"},
        {"position": 2, "is_heading": 0, "label": "Thai chilies", "raw_text": "3 Thai chilies"},
    ])
    assert rows[0]["label"] == "salt to taste"
    assert rows[1]["label"] == "Fresh Parsley, chopped", "a title-cased name is flagged, not rewritten"
    assert rows[2]["label"] == "Thai chilies", "a proper noun keeps its capital"
    assert sorted(f["flag"] for f in flags) == [
        "ingredient_name_lowercased", "ingredient_name_title_cased"]


def test_a_heading_row_is_never_recased_by_the_importer():
    rows, flags = import_write._lowercase_ingredient_names(
        [{"position": 0, "is_heading": 1, "label": None, "raw_text": "For the Chicken:"}])
    assert rows[0]["raw_text"] == "For the Chicken:"
    assert flags == []


def test_the_importer_capitalizes_a_step_after_a_heading():
    """⚠️ THE CONTINUATION TEST IS ONE FUNCTION NOW, shared with apply_capitalization.py. Both copies
    had the same hole: a heading never ends in terminal punctuation."""
    rows, _n, _c = import_write._step_rows({"directions": ["COOKING:", "bring a salted water to a boil."],
                                            "notes": ""})
    assert [r["text"] for r in rows] == ["Cooking:", "Bring a salted water to a boil."]


def test_the_importer_still_leaves_a_real_continuation_lowercase():
    rows, _n, _c = import_write._step_rows({"directions": [
        "Mix until a thick, batter-like", "consistency forms."], "notes": ""})
    assert [r["text"] for r in rows] == ["Mix until a thick, batter-like", "consistency forms."]


# ---- the pass's provenance test, which the whole heading rule rests on --------------------------

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import apply_polish_round_2 as r2                                             # noqa: E402


def _steps(*rows):
    """rows are (id, is_heading, text), in position order, all on one recipe."""
    return {"probe": [{"id": i, "recipe_id": "probe", "position": n, "is_heading": h, "text": t,
                       "heading_level": 1 if h else None}
                      for n, (i, h, t) in enumerate(rows)]}


def test_an_inserted_heading_is_the_one_with_an_id_above_every_ordinary_step():
    """A lift INSERTS a row, a conversion changes one in place, and an author's heading arrived as
    one. On live: ordinary steps run to 5972 and the 127 inserted headings are 5973 to 6099."""
    by = _steps((100, 0, "Mix it"), (101, 1, "Fry #1"), (102, 0, "Fry it"),
                (900, 1, "50 sec fry"), (103, 0, "Wait"))
    assert r2.lifted_heading_ids(by) == {900}


def test_a_step_row_added_after_the_lifts_refuses_rather_than_silently_misreading():
    """⚠️ THE FRAGILITY THE CROSS-CHECK EXISTS FOR. "Every inserted heading has an id above every
    ordinary step" is true of this corpus and is not a law. One step row added after the lifts raises
    the threshold, the lifted headings below it drop out, and that does not fail loudly: it stops
    promoting them AND makes them parents that demote the headings under them.

    ⚠️ THE FIRST VERSION OF THIS GUARD COMPARED IDS AGAINST EACH OTHER AND WAS VACUOUS ON THIS EXACT
    CASE, which is why the fixture below uses a REAL reviewed lift. french-fries' step 2439 had the
    label "Cut" lifted out of it into heading row 6005, recorded in
    docs/data-repairs/step-leadin-labels-2026-09-30.csv. Put one ordinary step above 6005 in id order
    and the id test can no longer see 6005 as a lift. Evidence of a different kind is what catches
    it."""
    by = {"french-fries": [
        {"id": 6005, "recipe_id": "french-fries", "position": 0, "is_heading": 1, "text": "Cut"},
        {"id": 2439, "recipe_id": "french-fries", "position": 1, "is_heading": 0, "text": "Peel them"},
        {"id": 9999, "recipe_id": "french-fries", "position": 2, "is_heading": 0,
         "text": "A step row added after the lifts ran"},
    ]}
    with pytest.raises(r2.BadDecision) as e:
        r2.lifted_heading_ids(by)
    assert "6005" in str(e.value) and "no longer separable by id" in str(e.value)


def test_the_cross_check_finds_the_heading_the_lift_created_not_the_step_it_came_from():
    """⚠️ THE CSV NAMES THE STEP, NOT THE HEADING. Matching on `step_row_id` alone found 0 of 263
    lifted headings and would have reported "nothing changes" for the whole round."""
    by = {"french-fries": [
        {"id": 6005, "recipe_id": "french-fries", "position": 0, "is_heading": 1, "text": "Cut"},
        {"id": 2439, "recipe_id": "french-fries", "position": 1, "is_heading": 0, "text": "Peel them"},
    ]}
    assert r2.reviewed_lift_ids(by) == {6005}, "the heading above the step, not the step"


def test_the_cross_check_refuses_a_heading_whose_words_no_longer_match_the_label():
    """It matches by WORDING, so a heading someone has since retitled is not claimed as that lift."""
    by = {"french-fries": [
        {"id": 6005, "recipe_id": "french-fries", "position": 0, "is_heading": 1,
         "text": "Cut the potatoes"},
        {"id": 2439, "recipe_id": "french-fries", "position": 1, "is_heading": 0, "text": "Peel them"},
    ]}
    assert r2.reviewed_lift_ids(by) == set()


def test_a_recipe_with_no_inserted_heading_at_all_is_fine():
    by = _steps((100, 0, "Mix it"), (101, 1, "Fry #1"), (102, 0, "Fry it"))
    assert r2.lifted_heading_ids(by) == set()


def test_the_authors_own_inserted_section_is_read_from_its_decision_file_not_guessed():
    """brioche-bread's "Baking" is a NEW row and is the author's own section, recovered from the
    source ld+json by the 2026-10-01 round. Nothing about the row says so, so the round file does."""
    recorded = r2.author_section_inserts()
    assert ("brioche-bread", "Baking") in recorded, recorded
    by = {"brioche-bread": [
        {"id": 100, "recipe_id": "brioche-bread", "position": 0, "is_heading": 0, "text": "Mix"},
        {"id": 900, "recipe_id": "brioche-bread", "position": 1, "is_heading": 1, "text": "Baking"},
        {"id": 901, "recipe_id": "brioche-bread", "position": 2, "is_heading": 1, "text": "Option 1:"},
    ]}
    assert r2.lifted_heading_ids(by) == {901}, "Baking is the author's, Option 1 is not recorded"


def test_an_author_written_heading_is_the_parent_and_a_lifted_one_is_not():
    """The parents are GIVEN, not derived, which is what makes the sweep idempotent. An earlier
    version read the level it had just written, and one pass changed 86 levels with 69 demotions."""
    by = _steps((100, 1, "Fry #1"), (101, 0, "Fry it"), (900, 1, "Assembly"), (102, 0, "Build it"))
    want = r2.levels_the_rule_wants(ic, by)
    assert want == {900: ic.SUBHEADING}, "under the author's own heading, so a subheading"
    by2 = _steps((900, 1, "Marinade"), (100, 0, "Mix it"), (901, 1, "Assembly"), (101, 0, "Build it"))
    want2 = r2.levels_the_rule_wants(ic, by2)
    assert want2 == {900: ic.SECTION, 901: ic.SECTION}, \
        "both lifted, so neither is a parent and both open a section"


# ---- one rule set, one function, checked rather than claimed -------------------------------------

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_the_continuation_test_is_stated_in_exactly_one_place():
    """⚠️ IT WAS STATED TWICE AND BOTH COPIES HAD THE SAME HOLE, which is the failure mode CLAUDE.md
    names: "ONE RULE SET MEANS ONE FUNCTION, AND A COMMENT SAYING SO IS NOT THE SAME THING". A review
    of this very round found `import_write._step_rows` claiming the test was shared with
    `scripts/apply_capitalization.py` while that file still carried its own copy. Stated over the
    repo, so the next caller cannot quietly write a third."""
    needle = 'endswith((".", "!", "?", ":", ";"))'
    carriers = []
    for path in list(REPO.glob("*.py")) + list((REPO / "scripts").glob("*.py")) \
            + list((REPO / "scripts" / "applied").glob("*.py")):
        if needle in path.read_text():
            carriers.append(path.name)
    assert carriers == ["import_cleanup.py"], (
        f"the continuation test is spelled out in {carriers}. It belongs in "
        f"import_cleanup.continues_the_line_above and nowhere else.")


def test_both_callers_of_the_continuation_test_reach_the_shared_function():
    """The other direction: the one function is not enough if a caller stopped using it."""
    for name in ("import_write.py", "scripts/apply_capitalization.py"):
        src = (REPO / name).read_text()
        assert "continues_the_line_above" in src, f"{name} no longer asks the shared rule"


def test_a_heading_predecessor_is_the_half_both_copies_were_missing():
    """The hole, stated as a behaviour rather than as a grep. A heading never ends in terminal
    punctuation, so the old test called every first step of every section a continuation."""
    assert ic.continues_the_line_above("Cooking", True) is False
    assert ic.continues_the_line_above("Cooking", False) is True, (
        "the same words as an ordinary step DO read as an unfinished line, which is why the flag "
        "has to be passed in rather than guessed from the text")


def test_which_labels_restate_their_kind_is_a_list_in_the_table_not_a_rule_here():
    """⚠️ ANDY ASKED FOR A LIST RATHER THAN A GRAMMAR RULE, and this is what holds the rule to it.
    static/note-kinds.json is the file the client reads too, so the display and the data rule cannot
    disagree about what "Storing." means. A kind with no `restates_the_kind` key would make the rule
    raise rather than default to "nothing restates it", which is the behaviour worth keeping: a kind
    added without a decision is a question, not an empty answer."""
    table = json.loads((REPO / "static" / "note-kinds.json").read_text())["kinds"]
    assert table, "the table is empty, so this test is checking nothing"
    for k in table:
        assert "restates_the_kind" in k, f"{k['kind']} carries no restates_the_kind list"
        declared = {l.lower() for l in k["restates_the_kind"]}
        assert declared <= {l.lower() for l in k["labels"]}, (
            f"{k['kind']} restates labels it does not carry: "
            f"{sorted(declared - {l.lower() for l in k['labels']})}")
        assert ic.KIND_RESTATING_LABELS[k["kind"]] == frozenset(declared), (
            f"the rule and the table disagree for {k['kind']}")


def test_andys_two_calls_are_the_table_and_not_a_coincidence():
    """The two the 2026-10-08 click-through decided, asserted as the decisions rather than as the
    behaviour, so editing the table to taste fails here."""
    assert "storing" in ic.KIND_RESTATING_LABELS["storage"], "Storing restates Storage"
    assert "reminder" not in ic.KIND_RESTATING_LABELS["notes"], "Reminder does not restate Notes"


def test_a_kind_whose_list_is_missing_is_a_question_rather_than_an_empty_answer():
    """Stated over a copy of the table, because the real one has every key."""
    table = json.loads((REPO / "static" / "note-kinds.json").read_text())["kinds"]
    broken = [dict(k) for k in table]
    broken[0].pop("restates_the_kind")
    with pytest.raises(KeyError):
        {k["kind"]: frozenset(k["restates_the_kind"]) for k in broken}


# ---- the stage rule's refusals, every one found by review on 2026-10-08 -------------------------

@pytest.mark.parametrize("label", [
    "Keeps 3 days", "Will keep 2 days", "Best within 2 days", "Store 3 days",
    "Shelf life 2 weeks", "Stays crisp 2 hours", "Good for 3 days", "Lasts 5 days",
])
def test_a_shelf_life_carries_a_duration_and_is_not_a_stage(label):
    """⚠️ IT SAYS HOW LONG THE FOOD LASTS, NOT HOW LONG THE COOK WAITS, and both shapes are a figure
    plus a time unit. Without this a storage note lifted out of a step was promoted to a section of
    the method."""
    assert ic.names_a_stage(label) is None


@pytest.mark.parametrize("label", ["Use 2 day-old bread", "3 day old rice", "1 week-old sourdough"])
def test_an_ingredients_age_is_not_a_duration(label):
    """The hyphen is a word boundary, so "2 day-old" matched the duration pattern."""
    assert ic.names_a_stage(label) is None


@pytest.mark.parametrize("label", ["Freeze 2 hours", "Chill in the fridge 1 hour",
                                   "Rest 10 minutes", "Cool 30 min"])
def test_the_shelf_life_list_leaves_the_real_waits_alone(label):
    """⚠️ fridge, freezer AND freeze ARE DELIBERATELY NOT ON THAT LIST. "Freeze 2 hours" is a stage
    the cook waits out, and refusing it would be the same mistake in the other direction."""
    assert ic.names_a_stage(label) is not None


@pytest.mark.parametrize("label", [
    "Serves 4", "Makes 24", "Yield 12", "Bake 350", "Oven 200", "Pan 2", "Tip 2", "Notes 2",
])
def test_a_yield_or_a_temperature_is_not_a_numbered_stage(label):
    """⚠️ THE COUNTER HALF WAS `[A-Za-z]{3,}\\s+\\d+$`, ANY WORD THEN ANY NUMBER, and a review found
    it reading every one of these as a stage. A yield is not an ordinal and 350 is not a batch."""
    assert ic.names_a_stage(label) is None


@pytest.mark.parametrize("label", ["Batch 2", "Day 2", "Fry 3", "Rise 2", "Proof 2", "Bake 2",
                                   "Step 4", "Round 2", "Soak 2", "Pass 3"])
def test_a_listed_stage_word_with_a_small_ordinal_is_a_stage(label):
    assert ic.names_a_stage(label) == "names a numbered stage, so it opens a section"


@pytest.mark.parametrize("label", ["Batch 12", "Bake 350", "Day 30"])
def test_a_figure_too_large_to_be_an_ordinal_is_refused_even_on_a_stage_word(label):
    """A recipe with a tenth batch does not number it in a heading. Above the bound the figure is a
    temperature, a yield or a quantity."""
    assert ic.names_a_stage(label) is None


@pytest.mark.parametrize("label", ["Fry #2", "Batch #12", "Thing #3"])
def test_the_hash_form_needs_neither_a_listed_word_nor_a_small_number(label):
    """The author marked it themselves, which is evidence no list can improve on."""
    assert ic.names_a_stage(label) == "names a numbered stage, so it opens a section"


@pytest.mark.parametrize("label", ["Variant 2", "Alternative 2", "Approach 2", "Choice 2",
                                   "Option 1", "Method 2", "Version 1", "Way 2", "Variation 2"])
def test_every_alternative_shape_is_refused_by_the_one_list_both_rules_read(label):
    """⚠️ FIVE OF THESE SLIPPED PAST _ALTERNATIVE UNTIL 2026-10-08, and it cost two rules at once:
    group_alternatives never demoted them under their section, and names_a_stage read the trailing
    number as a stage counter and promoted them. Opposite answers from one gap."""
    assert ic.names_a_stage(label) is None
    assert ic._ALTERNATIVE.match(label), f"{label} is not read as an alternative"
    assert ic.label_level(label, section_above=True) == ic.SUBHEADING


# ---- the step-text chain ------------------------------------------------------------------------

def test_two_step_text_writes_that_chain_are_collapsed_into_one():
    writes = [{"what": "step_text", "id": 7, "was": "1. bring it", "now": "bring it",
               "why": "the number came off"},
              {"what": "step_text", "id": 7, "was": "bring it", "now": "Bring it",
               "why": "it follows a heading"}]
    out, broken = r2._collapse_step_text(writes)
    assert broken == []
    assert [(w["id"], w["was"], w["now"]) for w in out] == [(7, "1. bring it", "Bring it")]
    assert out[0]["why"] == "the number came off, then it follows a heading"


def test_two_step_text_writes_computed_from_the_same_text_are_refused_not_merged():
    """⚠️ THE DEFECT A REVIEW FOUND. The collapse kept the first `was` and the LAST `now`, so two
    writes computed from the same starting text silently dropped one change while the pass reported
    both. Rather than guess an order, the break is named and the caller aborts."""
    writes = [{"what": "step_text", "id": 7, "was": "cook this way*. Go.", "now": "cook this way. Go.",
               "why": "the marker came off"},
              {"what": "step_text", "id": 7, "was": "cook this way*. Go.", "now": "Cook this way*. Go.",
               "why": "it follows a heading"}]
    out, broken = r2._collapse_step_text(writes)
    assert len(broken) == 1 and broken[0]["id"] == 7
    assert broken[0]["was"] == "cook this way*. Go."
    assert broken[0]["leaves"] == "cook this way. Go."
    assert [w["id"] for w in out] == [7], "the first write survives for the abort message to name"


def test_a_write_that_is_not_step_text_is_carried_through_untouched():
    writes = [{"what": "heading_level", "id": 9, "was": 2, "now": 1},
              {"what": "step_text", "id": 7, "was": "a", "now": "b", "why": "x"}]
    out, broken = r2._collapse_step_text(writes)
    assert broken == []
    assert {w["what"] for w in out} == {"heading_level", "step_text"}


def test_the_abort_message_says_what_is_already_committed():
    """⚠️ IT USED TO SAY "so nothing was written", WHICH IS FALSE FOR EVERY RECIPE BEFORE THE ONE
    THAT TRIPPED. Each recipe is its own transaction on purpose, so an abort leaves the corpus part
    way through and the message has to say so."""
    msg = r2._half_applied("brioche-bread", ["beans", "biscuits"], "the annotation set moved")
    assert "nothing was written" not in msg
    assert "2 recipe(s) BEFORE it are already COMMITTED" in msg
    assert "beans, biscuits" in msg
    assert r2._half_applied("beans", [], "x").endswith("(none)")


# ---- the four more a review found on 2026-10-08 -------------------------------------------------

@pytest.mark.parametrize("name", ["McIntosh apples", "DeLallo olive oil", "McCormick chili powder",
                                   "LaCroix lime", "MacGregor oats"])
def test_a_capital_inside_the_first_word_is_uncertain_rather_than_half_lowered(name):
    """⚠️ _is_title_cased READS THE TEXT AFTER THE LEAD WORD, so an internally capitalized lead word
    passed every check and came out half-cased: "McIntosh apples" -> "mcIntosh apples". That is
    exactly the string the title-cased refusal exists to prevent, one word earlier. It matters most
    on the import-only blanket rule, where there is no corpus evidence to catch it either."""
    fixed, verdict, why = ic.ingredient_name_case(name, lowercase_elsewhere=True)
    assert fixed == name, "it must be left exactly as written"
    assert verdict == ic.CASE_UNCERTAIN
    assert "half-cased" in why


@pytest.mark.parametrize("name,want", [("Salt to taste", "salt to taste"),
                                        ("Flour, sifted", "flour, sifted"),
                                        ("Buns", "buns")])
def test_an_ordinary_first_word_still_lowercases_on_an_import(name, want):
    fixed, verdict, _why = ic.ingredient_name_case(name, lowercase_elsewhere=True)
    assert (fixed, verdict) == (want, ic.CASE_CERTAIN)


@pytest.mark.parametrize("text,title", [
    ("leftovers: best pan-fried fresh", "Leftovers"),
    ("to freeze: wrap it twice", "To freeze"),
    ("LEFTOVERS - best fresh", "Leftovers"),
    ("To Store: keep it cold", "To Store"),
])
def test_a_note_title_starts_with_a_capital_whatever_the_author_typed(text, title):
    """⚠️ _title_case ALONE FIXES ONLY ALL CAPS, so "leftovers:" came out titled "leftovers" while
    "LEFTOVERS -" came out "Leftovers". One author's casing decided whether the page printed a
    heading in lower case."""
    assert ic.note_label_plan(text).title == title


def test_a_kind_with_no_restating_list_says_what_to_do_rather_than_raising_a_bare_keyerror():
    """⚠️ A BARE KeyError HERE TAKES DOWN EVERY IMPORTER OF THE MODULE, app.py INCLUDED, on a
    one-line edit to a JSON file. Stopping is right; stopping silently is not."""
    import unittest.mock as mock
    broken = [dict(k) for k in ic.NOTE_KINDS]
    broken[0] = {k: v for k, v in broken[0].items() if k != "restates_the_kind"}
    with mock.patch.object(ic, "NOTE_KINDS", broken):
        with pytest.raises(KeyError) as e:
            ic._restating_labels()
    assert "note-kinds.json" in str(e.value) and "restates_the_kind" in str(e.value)


def test_an_inserted_optional_heading_brings_the_earlier_flags_positions_with_it():
    """⚠️ import_flags HAS ONE NULLABLE `position` COLUMN AND A LINE FLAG'S VALUE IS THE INGREDIENT
    LINE'S INDEX. The grouping renumbers the rows, so every flag after an inserted heading pointed at
    its neighbour, and the first one pointed at the heading itself, which the review-queue printer
    renders as a section. Found by review 2026-10-08."""
    rows = [{"position": i, "is_heading": 0, "label": lab, "raw_text": raw, "qty": None,
             "quantity": None, "unit": None, "note": None, "ingredient_id": None,
             "grams": None, "secondary_measure": None}
            for i, (lab, raw) in enumerate([("flour", "1 cup flour"),
                                            ("Optional: Walnuts", "Optional: 1/2 cup walnuts"),
                                            ("salt", "Salt")])]
    out, _flags, moved = import_write._group_optional_lines(rows)
    assert [(r["position"], bool(r["is_heading"])) for r in out] == [
        (0, False), (1, True), (2, False), (3, False)]
    assert moved == {1: 2, 2: 3}, "the two lines after the insert each moved down one"
    assert 0 not in moved, "a row the insert did not pass must not be remapped"


def test_a_recipe_with_no_optional_run_remaps_nothing():
    rows = [{"position": 0, "is_heading": 0, "label": "flour", "raw_text": "1 cup flour"}]
    out, flags, moved = import_write._group_optional_lines(rows)
    assert (out, flags, moved) == (rows, [], {})
