"""The author's own step numbers come off, and a step that merely starts with a number never does.

⚠️ THE APP PRINTS ITS OWN NUMBER IN A CIRCLE, so a step whose text still begins "1." shows the number
twice. Worse, a lead-in label hiding behind one is invisible to the label rule: seven of
aloo-potato-parathas' steps kept an ALL-CAPS title inside the step text because "1. MAKE THE DOUGH:"
does not match a pattern that expects a capital letter first.

⚠️ THE EVIDENCE THAT A LEADING NUMBER IS THE AUTHOR'S IS THAT THE REST OF THE RECIPE IS NUMBERED TOO.
That is why the rule is all-or-nothing over the whole recipe rather than per line, and it is what
keeps "30 minutes before you start cooking throw your butter into the freezer" intact.
"""
import import_cleanup as ic
import harness  # noqa: F401


# ---- the number rule --------------------------------------------------------------------------

def test_a_consecutive_run_is_the_authors_numbering():
    assert ic.strip_author_numbers(["1. Do this.", "2. Then this.", "3. Last."]) == \
        ["Do this.", "Then this.", "Last."]


def test_every_separator_the_brief_names():
    for sep in (".", ")", ":", " -", " –"):
        got = ic.strip_author_numbers([f"1{sep} First.", f"2{sep} Second."])
        assert got == ["First.", "Second."], sep
    assert ic.strip_author_numbers(["Step 1: First.", "Step 2: Second."]) == ["First.", "Second."]


def test_a_step_that_merely_starts_with_a_number_is_never_touched():
    """⚠️ THE CASE THE WHOLE RULE IS SHAPED AROUND. Three real corpus steps open this way."""
    rows = ["30 minutes before you start cooking throw your butter into the freezer.", "Mix it."]
    assert ic.strip_author_numbers(rows) == rows


def test_an_unnumbered_recipe_is_left_alone_even_where_one_line_looks_numbered():
    rows = ["Mix the dough.", "2. Rest it.", "Bake."]
    assert ic.strip_author_numbers(rows) == rows, "the run does not start at 1, so nothing is the author's"


def test_a_number_that_disagrees_with_its_ordinal_is_not_this_steps_number():
    rows = ["1. First.", "7. Seventh?"]
    assert ic.strip_author_numbers(rows) == rows


def test_a_single_numbered_line_is_not_a_sequence():
    rows = ["1. The only numbered line.", "Then this.", "And this."]
    assert ic.strip_author_numbers(rows) == rows


def test_a_gap_in_the_run_is_still_one_sequence():
    """white-bean-stuffed-poblanos: the author missed the separator on one line, not the number."""
    rows = ["1. Preheat.", "2 In a large skillet, warm the oil.", "3. Mash the beans."]
    assert ic.strip_author_numbers(rows) == ["Preheat.", "In a large skillet, warm the oil.",
                                             "Mash the beans."]


def test_a_bare_number_needs_a_capital_after_it():
    """⚠️ THE RISKY FORM, ADMITTED ONLY ON TWO PIECES OF EVIDENCE AT ONCE. Measured over the 300:
    the pair (number equals the ordinal, a capital follows) admits 7 steps, all of them the author's
    numbering, and refuses the 3 real ones."""
    assert ic.strip_author_numbers(["1 Preheat the oven.", "2 In a skillet, warm oil."]) == \
        ["Preheat the oven.", "In a skillet, warm oil."]
    rows = ["1 Preheat the oven.", "2 cups flour, sifted, go in next."]
    assert ic.strip_author_numbers(rows)[1] == rows[1], "a lowercase word after the number is content"


def test_author_step_number_reports_the_number_it_found():
    assert ic.author_step_number("3. Divide the dough.", 3) == (3, "Divide the dough.")
    assert ic.author_step_number("3. Divide the dough.", 2) is None


# ---- the ALL-CAPS lead-in ---------------------------------------------------------------------

def test_an_all_caps_lead_in_with_a_colon_is_a_label_despite_a_comma():
    """⚠️ MEASURED BEFORE IT WAS WRITTEN: exactly 2 labels in the corpus take this door, and the 8
    other currently-refused lead-ins are all mixed case and stay refused."""
    got = ic.split_lead_label(
        "WHILE THE DOUGH IS RESTING, MAKE THE FILLING: In another bowl, mash the potatoes.")
    assert isinstance(got, tuple), got
    assert got[0] == "WHILE THE DOUGH IS RESTING, MAKE THE FILLING"


def test_an_all_caps_lead_in_with_a_colon_is_a_label_despite_a_connective():
    got = ic.split_lead_label(
        "MEANWHILE, MAKE THE KACHUMBER TOPPING: In a medium bowl, combine the cucumber.")
    assert isinstance(got, tuple), got


def test_a_mixed_case_lead_in_with_a_comma_is_still_refused():
    """The exemption is about CASE plus a COLON, not about commas becoming acceptable."""
    got = ic.split_lead_label(
        "Turn stove up to high, add wine and simmer rapidly: reduce by half.")
    assert isinstance(got, str) and "comma" in got


def test_an_all_caps_lead_in_with_a_DASH_is_not_exempt():
    """⚠️ THE COLON IS HALF THE EVIDENCE. A dash-separated lead-in is the ordinary shape and keeps
    the ordinary refusals."""
    got = ic.split_lead_label(
        "WHILE THE DOUGH IS RESTING, MAKE THE FILLING - In another bowl, mash the potatoes.")
    assert isinstance(got, str), got


def test_an_open_bracket_still_refuses_even_in_capitals():
    """A half-open bracket means the label is half a sentence whatever its case."""
    got = ic.split_lead_label("POUR THE BATTER INTO THE PAN (IT'LL BE THICK: that's ok.")
    assert isinstance(got, str), got


# ---- the two together, which is how they ship --------------------------------------------------

def test_the_importer_strips_the_number_then_lifts_the_label(kitchen):
    rows, _notes, _conv = ic.plan_step_rows([
        "1. MAKE THE DOUGH: In a medium bowl, mix all the dough ingredients.",
        "2. WHILE THE DOUGH IS RESTING, MAKE THE FILLING: In another bowl, mash the potatoes.",
        "3. Divide the dough into 4 equal portions.",
    ])
    assert [(r["is_heading"], r["text"]) for r in rows] == [
        (1, "Make the dough"),
        (0, "In a medium bowl, mix all the dough ingredients."),
        (1, "While the dough is resting, make the filling"),
        (0, "In another bowl, mash the potatoes."),
        (0, "Divide the dough into 4 equal portions."),
    ]


def test_the_importer_leaves_an_unnumbered_recipe_alone(kitchen):
    rows, _notes, _conv = ic.plan_step_rows([
        "30 minutes before you start, freeze the butter.",
        "Mix the dough.",
    ])
    assert rows[0]["text"] == "30 minutes before you start, freeze the butter."
