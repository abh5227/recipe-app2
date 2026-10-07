"""Is a note's leading label a TITLE? The rule, and the 36 decisions it has to reproduce.

note_title_verdict answers about a label's SHAPE. note_title_plan is the rule: it adds the
separator the author used, how much text follows, whether the kind table already names the label,
and whether the line is wrapped in emphasis marks.

⚠️ THE DECISIONS ARE THE TEST, AND THEY ARE IN THE REPO. Andy decided all 36 cases the corpus
offers, in docs/data-repairs/note-titles-2026-10-05.csv and emphasis-marks-2026-10-05.csv, and
test_the_rule_reproduces_every_one_of_andys_decisions reads those files rather than a copy of their
contents. A rule whose cases are retyped into its own test agrees with the test and with nothing
else.

⚠️ AND "not a title" IS PINNED HERE AND NOWHERE ELSE for the discourse markers. No note in the 300
opens with one, so that branch has no evidence in the corpus at all. A branch with no data behind it
is exactly the one that quietly stops working.
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
    "Blind Bake",
    "Tomato Bouillon",
    "DASHI",
    "Measurements",
    "Kneading by hand",       # brioche-bread's note 28, and the only 3-word one of these
])
def test_a_short_capitalized_name_is_a_title_under_any_separator(label):
    assert verdict(label) == "title"
    assert ic.note_title_verdict(label, marked=True)[0] == "title"


@pytest.mark.parametrize("label", [
    "Form a Pie Shell",        # all-butter-pie-crust, the case that started the question
    "To Freeze the pie shell",
    "For waffles that stay crisp",
])
def test_a_longer_name_needs_the_heading_mark_the_author_actually_wrote(label):
    """All three carry a COLON in the corpus, which is what admits them. Over the full-stop form
    they are 4 and 5 words with no clause word, the shape "Made with Vedant and Sophia" has too, so
    there they go to a person instead."""
    assert ic.note_title_verdict(label, marked=True)[0] == "title"


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
    ("One two three four five six", "longer than a heading"),
    ("a lowercase thing", "capital"),
])
def test_a_label_the_rule_cannot_defend_is_unclear_with_a_reason(label, why):
    kind, reason = ic.note_title_verdict(label)
    assert kind == "unclear"
    assert why in reason


# --- a clause is settled by the separator, not left for a person --------------------------------

@pytest.mark.parametrize("label", [
    "If using fresh Yeast",
    "You can use Canned Chickpeas",
    "Don't over-mix the batter",
    "When the dough is cold",
])
def test_a_clause_under_a_full_stop_is_a_sentence_and_not_a_title(label):
    """⚠️ THIS USED TO READ "unclear" AND THE SEPARATOR IS WHAT CHANGED IT. The full-stop form means
    the label is only the note's first sentence unless it reads as a name, so a clause in it settles
    the question rather than opening one. pasta-e-ceci's "You can use Canned Chickpeas." is Andy's
    `no`, and sending it to a review queue would ask a person something the rule can answer."""
    assert verdict(label) == "not a title"


@pytest.mark.parametrize("label", [
    "If using fresh Yeast",
    "For waffles that stay crisp",
    "When the dough is cold",
])
def test_the_same_clause_under_a_colon_or_a_dash_is_a_title(label):
    """marked=True is the author having drawn a heading. waffle's note 174 is "For waffles that stay
    crisp:" and it is Andy's `title`, clause word and all."""
    assert ic.note_title_verdict(label, marked=True)[0] == "title"


def test_marked_defaults_to_the_reading_that_refuses_more():
    # A caller that does not say which separator it saw gets the full-stop answer.
    assert verdict("You can use Canned Chickpeas") == "not a title"
    assert ic.note_title_verdict("You can use Canned Chickpeas", marked=False)[0] == "not a title"


def test_a_curly_apostrophe_reads_as_a_straight_one():
    # The corpus holds both, and a clause word spelled with the curly form is the same clause word.
    assert verdict("Don’t over-mix the batter") == "not a title"
    assert ic.note_label_clause_words("Don’t over-mix the batter") == ["don't"]


def test_an_empty_label_is_unclear_rather_than_a_crash():
    assert verdict("") == "unclear"
    assert verdict(None) == "unclear"
    assert verdict("   ") == "unclear"


def test_the_two_word_ceilings_are_stated():
    """The boundaries are named, so moving one is a decision rather than an accident.

    ⚠️ THE FULL-STOP FORM IS TIGHTER, AND THAT WAS FOUND BY WRITING A TEST RATHER THAN BY READING
    THE CORPUS. "Made with Vedant and Sophia. It was great." has no clause word in it, and under one
    shared ceiling of five the rule promoted it to a heading. dry-rub-for-ribs' note 66 is that
    sentence with nothing after it, which _NOTE_LEAD does not match, so the corpus never showed it
    and the importer would have. Measured over the 9 period-form leads the 300 carry, the titles are
    1 and 3 words and the refusals are 4 and 5 with clause words in them."""
    assert ic.NOTE_TITLE_MAX_WORDS == 5
    assert ic.NOTE_TITLE_PERIOD_MAX_WORDS == 3
    # marked, which is a colon, a dash or an emphasis wrap: five is in and six is out
    assert ic.note_title_verdict("One Two Three Four Five", marked=True)[0] == "title"
    assert ic.note_title_verdict("One Two Three Four Five Six", marked=True)[0] == "unclear"
    # the full-stop form: three is in and four goes to a person
    assert verdict("One Two Three") == "title"
    assert verdict("One Two Three Four") == "unclear"


def test_a_short_sentence_under_a_full_stop_is_not_promoted_to_a_heading():
    """⚠️ THE HOLE THE PERIOD CEILING CLOSES, kept as its own case because it is the shape that got
    through. clean_notes' docstring already warned about this exact sentence from the other side:
    "Made with Vedant and Sophia." is a whole sentence that happens to be short."""
    plan = ic.note_title_plan("Made with Vedant and Sophia. It was great.")
    assert plan.verdict == "unclear"
    assert plan.title is None
    # and the real corpus row, which has no body at all, is not even a lead
    assert ic.note_lead("Made with Vedant and Sophia.") is None
    assert ic.note_title_plan("Made with Vedant and Sophia.").verdict == "no title"


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


# --- the emphasis wrap ----------------------------------------------------------------------------

@pytest.mark.parametrize("line,inner,run", [
    ("**Chinese black vinegar**", "Chinese black vinegar", "**"),
    ("_Buying_", "Buying", "_"),
    ("_Cinnamon Filling_", "Cinnamon Filling", "_"),
    ("__bold the other way__", "bold the other way", "__"),
    ("*italic*", "italic", "*"),
])
def test_a_wrapped_line_loses_its_marks(line, inner, run):
    assert ic.strip_wrapping_marks(line) == (inner, run)


def test_a_space_before_the_closing_mark_still_closes_it():
    """⚠️ LOOSER THAN MARKDOWN ON PURPOSE, AND THIS IS THE CASE THAT NEEDED IT. CommonMark will not
    close emphasis on a delimiter with whitespace in front of it, so the corpus survey's classifier
    filed key-lime-pie's note 89 under "unpaired marker, not emphasis". It is somebody wrapping a
    line all the same, and the space goes with the mark."""
    assert ic.strip_wrapping_marks("*Pie recipe for year 5 anniversary 3/14/25 : ) *") == (
        "Pie recipe for year 5 anniversary 3/14/25 : )", "*")


@pytest.mark.parametrize("line", [
    "*To improve digestibility you can soak lentils overnight. Drain before cooking.",
    "*Turn the heat lower if needed to avoid burning. Transfer the beans and set aside.",
    "¼ teaspoon salt*",
    "regular yogurt (any flavor*)",
    "*a* and *b*",
    "**a** and **b**",
    "***three***",
    "**",
    "*",
    "",
])
def test_a_footnote_marker_and_in_sentence_emphasis_are_left_alone(line):
    """19 of the corpus's 30 marks are footnote markers and there is not one in-sentence emphasis in
    the 300 recipes. A rule that stripped either would edit a sentence rather than lift a heading."""
    assert ic.strip_wrapping_marks(line) == (line, None)


def test_a_line_with_no_wrap_comes_back_byte_identical():
    # Not stripped, not trimmed. A save that changes nothing has to leave the bytes alone.
    for line in ("  Flour. This recipe works best...  ", "Freezing – Freezes 100%"):
        assert ic.strip_wrapping_marks(line) == (line, None)


# --- the separator, read off the one pattern ------------------------------------------------------

@pytest.mark.parametrize("text,sep", [
    ("Blind Bake: put the weights in.", ":"),
    ("Flour. This recipe works best with bread flour.", "."),
    ("Measurements - Both grams and US cup sizes are provided.", "-"),
    ("Cannellini – also known as White Italian Beans.", "–"),
    ("Mirin — substitute Chinese cooking wine.", "—"),
    ("No label here at all", None),
])
def test_the_separator_is_read_back_off_the_same_match(text, sep):
    assert ic.note_lead_separator(text) == sep


def test_the_lead_pattern_is_built_from_the_named_separator_set():
    """⚠️ ONE PATTERN, NOT TWO. The title rule needs to know WHICH separator it saw, and a second
    regex to recover that character is how two rules that must agree stop agreeing. The hyphen stays
    last in the set, where a character class reads it as a literal rather than as a range."""
    assert ic._NOTE_SEP_CHARS == ":.–—-"
    assert ic._NOTE_SEP_CHARS.endswith("-")
    assert f"[{ic._NOTE_SEP_CHARS}]" in ic._NOTE_LEAD.pattern
    # a label whose own characters include the hyphen still reads, which is what a range would break
    assert ic.note_lead("Slow-cook: lid on.") == ("Slow-cook", "lid on.")


# --- the tiny body --------------------------------------------------------------------------------

def test_a_body_of_one_or_two_words_takes_no_title():
    """⚠️ MEASURED, NOT CHOSEN. french-baguette's note 69 is "If using fresh Yeast: 8g", a body of
    ONE word, and a heading over an amount is worse than no heading. The smallest body under a title
    Andy kept is SEVEN words, then 9, then 13, so the threshold sits in a gap from 1 to 7."""
    assert ic.NOTE_TITLE_TINY_BODY_WORDS == 2
    assert ic.note_title_plan("If using fresh Yeast: 8g").verdict == "no title"
    assert ic.note_title_plan("Flour: bread flour").verdict == "no title"       # two words
    assert ic.note_title_plan("Flour: use bread flour").verdict == "title"      # three is a body
    # and seven words is a title, which is the other side of the gap
    assert ic.note_title_plan(
        "Borlotti – also known as Cranberry bean, Roman bean").verdict == "title"


# --- ALL CAPS goes through the existing heading rule ----------------------------------------------

def test_all_caps_is_cased_and_everything_else_is_left_as_written():
    assert ic.note_title_plan("DASHI: Vegetarian Japanese stock is great to have.").title == "Dashi"
    assert ic.note_title_plan(
        "CHICKPEA FLOUR - Also known as garbanzo bean flour or gram flour.").title == "Chickpea flour"
    # is_caps says no, so the author's own capitals stand
    assert ic.note_title_plan("Blind Bake: Place a piece of parchment in the shell.").title == (
        "Blind Bake")
    assert ic.note_title_plan(
        "Tomato Bouillon: granules or cubes, found in the Mexican aisle.").title == "Tomato Bouillon"


# --- a known type label is a KIND, never a title --------------------------------------------------

def test_a_known_label_sets_the_kind_and_keeps_the_text_verbatim():
    """migration 060's rule: the words are stored as the author wrote them, label and all, and the
    kind sits beside them. Promoting "Freezing" would print a heading over a note already filed
    under Storage."""
    text = "Freezing – Freezes 100% perfectly! After Fry #1, fully cool the fries."
    plan = ic.note_title_plan(text)
    assert (plan.verdict, plan.kind, plan.title) == ("label", "storage", None)
    assert plan.text == text, "not one character of it moves"


def test_freezing_is_a_storage_label():
    """Added for french-fries' note 70, which is the corpus's only one. The fixture the JS sync test
    reads was regenerated with it, or that test fails by design."""
    assert ic.note_label_is_known("Freezing") is True
    assert ic.note_kind("Freezing: cool them first, then freeze on a tray.") == "storage"


def test_a_title_opening_with_a_known_label_carries_that_kind_and_keeps_its_own_heading():
    """all-butter-pie-crust's note 13. "To Freeze the pie shell" is not a label the table knows, and
    it opens with one that is, so the note belongs under Storage with its own heading."""
    plan = ic.note_title_plan("To Freeze the pie shell: Place the pie shell into the refrigerator.")
    assert (plan.verdict, plan.title, plan.kind) == (
        "title", "To Freeze the pie shell", "storage")
    assert ic.note_title_kind("Blind Bake") is None


# --- the four verdicts ----------------------------------------------------------------------------

def test_a_title_comes_off_the_front_of_the_text():
    plan = ic.note_title_plan("Flour. This recipe works best with flour with around 11% protein.")
    assert plan.verdict == "title"
    assert plan.title == "Flour"
    assert plan.text == "This recipe works best with flour with around 11% protein."


def test_a_wrapped_title_line_over_a_body_is_a_title():
    plan = ic.note_title_plan("**Enriched Chicken and Pork Broth**\nSubstitute 2 pounds pork necks.")
    assert (plan.verdict, plan.title, plan.marks) == (
        "title", "Enriched Chicken and Pork Broth", "**")
    assert plan.text == "Substitute 2 pounds pork necks."


def test_a_title_line_with_nothing_under_it_goes_to_a_person():
    """⚠️ dan-dan-noodles' note 64 IS THE CASE, and it is why this is not "no title". The row holds
    "**Sui mi ya cai**" and nothing else, because its body was split into the next note. A heading
    with nothing under it is a person's call: Andy's decision moves the title onto that next row and
    deletes this one, and no rule reading one row can see that."""
    plan = ic.note_title_plan("**Sui mi ya cai**")
    assert (plan.verdict, plan.marks) == ("unclear", "**")
    assert plan.text == "Sui mi ya cai"
    assert "nothing under it" in plan.reason


def test_a_wrapped_sentence_with_no_body_loses_its_marks_and_takes_no_title():
    """key-lime-pie's note 89. Nine words is not a heading, so the marks come off and that is all."""
    plan = ic.note_title_plan("*Pie recipe for year 5 anniversary 3/14/25 : ) *")
    assert (plan.verdict, plan.title, plan.marks) == ("no title", None, "*")
    assert plan.text == "Pie recipe for year 5 anniversary 3/14/25 : )"


def test_a_wrapped_whole_note_whose_label_the_table_knows_is_a_label():
    """baked-zucchini's note 19. Unwrap first, then ask: "Note for next time:" is a label the table
    already names, so it sets the kind and there is no title."""
    plan = ic.note_title_plan(
        "**Note for next time: Oven couldn't hold the temperature, so turned out soggy!**")
    assert (plan.verdict, plan.kind, plan.title, plan.marks) == ("label", "notes", None, "**")
    assert plan.text == "Note for next time: Oven couldn't hold the temperature, so turned out soggy!"


def test_a_note_with_no_label_and_no_wrap_takes_no_title():
    plan = ic.note_title_plan("I roasted these alongside the chicken and they were better for it.")
    assert (plan.verdict, plan.title, plan.marks) == ("no title", None, None)
    assert plan.text == "I roasted these alongside the chicken and they were better for it."
    assert "no leading label" in plan.reason


def test_a_discourse_marker_takes_no_title():
    """The branch with no evidence in the corpus, stated here because of that."""
    plan = ic.note_title_plan("Important: do not skip the chilling step, it will not set.")
    assert plan.verdict == "no title"
    assert "names nothing" in plan.reason


def test_an_empty_note_is_no_title_rather_than_a_crash():
    for text in (None, "", "   "):
        plan = ic.note_title_plan(text)
        assert plan.verdict == "no title"
        assert plan.title is None


def test_a_long_label_under_a_colon_is_the_one_shape_that_stays_unclear():
    # Length is not settled by the separator, so this is still a person's call.
    plan = ic.note_title_plan("One two three four five six: and then the body of the note follows.")
    assert plan.verdict == "unclear"
    assert "longer than a heading" in plan.reason


# --- Andy's 36 decisions, read from the files rather than retyped ---------------------------------

def _decisions():
    """(where, row id, recipe, DECISION, candidate_title) for every row Andy decided a rule
    question on.

    `keep` and `derived` rows are not rule questions: `keep` is in-sentence emphasis or a footnote
    marker the rule must leave alone, and `derived` names the retired recipes.notes copy, which this
    round does not touch."""
    import csv
    d = pathlib.Path(BASE) / "docs" / "data-repairs"
    out = []
    with (d / "note-titles-2026-10-05.csv").open() as fh:
        for r in csv.DictReader(fh):
            out.append(("note", int(r["note_id"]), r["recipe"], r["DECISION"].strip(),
                        (r.get("candidate_title") or "").strip()))
    with (d / "emphasis-marks-2026-10-05.csv").open() as fh:
        for r in csv.DictReader(fh):
            dec = r["DECISION"].strip()
            if dec == "derived" or dec.startswith("keep"):
                continue
            out.append(("note" if r["where"] == "note" else "ing",
                        int(r["id"]), r["recipe"], dec, ""))
    return out


def _wanted(decision, candidate=""):
    """Andy's DECISION -> (verdict the rule must reach, title or None, kind or None, strip).

    ⚠️ A BARE `title` NAMES ITS TEXT THROUGH candidate_title, AND THAT COLUMN WAS NOT READ. 21 of
    the 27 title decisions are bare, so `want_title` was None for them and the comparison below
    skipped the title entirely. Proved by mutation: corrupting every lifted title to "Flour XX"
    left this test GREEN while three literal tests went red. The review list's own reading of the
    label is what a bare `title` means, and the pass already uses it the same way."""
    verbs, title, kind = set(), None, None
    for part in [p.strip() for p in decision.split(";")]:
        if part.startswith("title:"):
            verbs.add("title")
            title = part[len("title:"):].strip()
        elif part.startswith("kind="):
            kind = part[len("kind="):].strip()
        elif part:
            verbs.add(part)
    if "title" in verbs and title is None and candidate:
        title = ic._title_case(candidate)
    verdict = ("label" if "label" in verbs else
               "title" if "title" in verbs else
               # the rule cannot see the next row, so it declines and the decision answers
               "unclear" if "merge-title-into-next" in verbs else
               "no title")
    return verdict, title, kind, "strip" in verbs


def test_every_decision_in_both_files_is_filled_in_and_parses():
    """⚠️ A CHECK THAT READ NOTHING FAILS. An empty DECISION column would make the comparison below
    pass on an empty set of cases."""
    rows = _decisions()
    assert len(rows) == 36, f"{len(rows)} decided rows, expected 36"
    blank = [(w, i) for w, i, _r, d, _c in rows if not d]
    assert blank == [], f"undecided rows: {blank}"
    for w, i, _r, d, c in rows:
        verdict, _t, _k, _s = _wanted(d, c)
        assert verdict in ("title", "label", "no title", "unclear"), (i, d)


def _corpus_notes():
    """{note id: text} for all 177 corpus notes, from the COMMITTED fixture.

    ⚠️ IT WAS live_catalog AND SKIPPED IN CI, which is where the whole point of this test was lost.
    That marker exists for the real 10,020-entry library, where a fixture database has the tables
    and no rows; 177 short strings are small enough to commit, and scripts/gen_note_corpus.py is
    what regenerates them. The two decision CSVs are read from the repo the same way, so the
    comparison is against Andy's recorded decisions rather than against a copy of them."""
    import json
    got = json.loads((BASE / "tests" / "fixtures" / "note-corpus.json").read_text())["notes"]
    assert len(got) == 177, f"the fixture holds {len(got)} notes, the measurements were over 177"
    return {n["id"]: n["text"] for n in got}, {n["id"]: n["kind"] for n in got}


def test_the_rule_reproduces_every_one_of_andys_decisions():
    """⚠️ READ FROM THE CORPUS AND FROM THE DECISION FILES, NOT FROM A COPY OF EITHER. A rule whose
    cases are retyped into its own test agrees with the test and with nothing else. Every case it
    covers is also stated above against literal text, so the rule stays pinned either way."""
    notes, _kinds = _corpus_notes()
    ings = {9213: "_Cinnamon Filling_", 9217: "_Vanilla Cream Cheese Icing_"}

    differ = []
    for where, rid, recipe, decision, candidate in _decisions():
        want_verdict, want_title, want_kind, want_strip = _wanted(decision, candidate)
        if where == "ing":
            _text, marks = ic.strip_wrapping_marks(ings[rid])
            if bool(marks) != want_strip:
                differ.append(f"ingredient {rid} ({recipe}): marks={marks!r}, wanted {want_strip}")
            continue
        plan = ic.note_title_plan(notes[rid])
        for got, want, what in ((plan.verdict, want_verdict, "verdict"),
                                (bool(plan.marks), want_strip, "strip"),
                                (plan.title, want_title, "title"),
                                (plan.kind, want_kind, "kind")):
            if what == "kind" and want is None:
                continue                      # the decision is silent about the kind
            if what == "title" and want is None and want_verdict == "title":
                raise AssertionError(f"note {rid}: a title decision with no expected text, so the "
                                     f"comparison would check nothing")
            if what == "title" and want is None:
                continue                      # a `no`, `label` or `strip` decision names no title
            if got != want:
                differ.append(f"note {rid} ({recipe}) {decision!r}: {what} {got!r}, wanted {want!r}")
    assert differ == [], "\n".join(differ)


def test_the_rule_invents_nothing_on_a_row_nobody_reviewed():
    """⚠️ THE OTHER HALF, AND THE ONE THAT MATTERS FOR THE IMPORTER. The pass only applies recorded
    decisions, so a rule that over-reaches is invisible there. The importer runs the rule freely.
    Measured over all 177 corpus notes: it writes a title or asks a question on exactly the 34 rows
    Andy reviewed and on none of the other 143."""
    notes, kinds = _corpus_notes()
    reviewed = {rid for _w, rid, _r, _d, _c in _decisions()}

    reached = []
    for nid, text in sorted(notes.items()):
        plan = ic.note_title_plan(text)
        touched = (plan.verdict in ("title", "unclear") or plan.marks
                   or (plan.kind is not None and plan.kind != kinds[nid]))
        if touched and nid not in reviewed:
            reached.append(f"note {nid}: {plan.verdict}, title={plan.title!r}, "
                           f"kind={plan.kind!r}, marks={plan.marks!r}")
    assert reached == [], "\n".join(reached)


@pytest.mark.live_catalog
def test_the_committed_note_corpus_still_matches_live():
    """⚠️ A FIXTURE IS A MEASUREMENT WITH A DATE ON IT. The two tests above read the committed copy
    so they run in CI, and this is the one that notices the copy going stale. It needs the real
    database, so it keeps the live_catalog marker and skips in CI, which is the right split: the
    rule's behaviour is checked everywhere and the fixture's freshness only where live exists.
    ⚠️ AND IT COMPARES THE ROWS AS THEY WERE BEFORE THE TITLES PASS. Once that pass has run on live
    the texts move, so this is expected to fail then and the answer is to regenerate."""
    import sqlite3
    sys.path.insert(0, str(BASE / "scripts"))
    import corpus_guard
    live = corpus_guard.live_db()
    if not live.exists():
        pytest.skip("no live database here")
    con = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    have = {r[0]: r[1] for r in con.execute("SELECT id, text FROM recipe_notes")}
    # ⚠️ r[1] IS THE COLUMN NAME. PRAGMA table_info returns (cid, name, type, notnull, dflt, pk),
    #    so `r[0] == "title"` compared an integer against a string and could never be true. The skip
    #    below was written for exactly the state live has been in since the titles round ran on
    #    2026-10-06, and it never fired: the test failed instead, telling the reader to regenerate a
    #    fixture that is deliberately a record of what came BEFORE that round.
    if any(r[1] == "title" for r in con.execute("PRAGMA table_info(recipe_notes)")) and \
            con.execute("SELECT COUNT(*) FROM recipe_notes "
                        "WHERE title IS NOT NULL").fetchone()[0]:
        pytest.skip("the titles pass has run on live, so the fixture is a record of what came "
                    "before it; regenerate with scripts/gen_note_corpus.py")
    notes, _kinds = _corpus_notes()
    assert notes == have, ("tests/fixtures/note-corpus.json is stale; regenerate it with "
                           "scripts/gen_note_corpus.py")


# --- who may call the rule ------------------------------------------------------------------------

def test_the_rule_has_one_copy_and_the_client_does_not_read_it():
    """⚠️ THIS REPLACES test_nothing_in_the_repo_calls_the_rule_yet, WHICH WAS TRUE UNTIL THIS ROUND
    AND IS THE TEST THAT WAS MEANT TO FAIL. What it was protecting was that the rule exists ONCE. So
    that is what is asserted now: the definition is in import_cleanup and every caller reaches it
    from there, and no second copy has grown in the browser. Vite inlines static/note-kinds.json for
    the client, and the TITLE rule is a server rule."""
    import subprocess
    names = ["-e", "note_title_plan", "-e", "note_title_verdict", "-e", "strip_wrapping_marks"]
    out = set(subprocess.run(["git", "grep", "-l"] + names + ["--", "*.py"],
                             cwd=BASE, capture_output=True, text=True).stdout.split())
    # ⚠️ THE FILE THAT DEFINES IT MUST BE IN THE ANSWER, or this passes on an empty grep. Rename the
    #    function, delete it, or mistype the pattern and the result is the empty set, which is a
    #    subset of anything.
    assert "import_cleanup.py" in out, f"the rule itself was not found: {sorted(out)}"
    assert "def note_title_plan" in (BASE / "import_cleanup.py").read_text()
    js = subprocess.run(["git", "grep", "-l"] + names + ["--", "*.js"],
                        cwd=BASE, capture_output=True, text=True).stdout.split()
    assert not js, f"a second copy of the title rule reached the client: {js}"


# --- what a fresh review broke, and the rule now refuses ------------------------------------------

@pytest.mark.parametrize("text,label", [
    ("Mrs. Smith gave me this recipe years ago in Kerala.", "Mrs"),
    ("Dr. Chen's version uses less sugar than this one.", "Dr"),
    ("St. Louis style ribs work here too, if you can get them.", "St"),
    ("Prof. Alvarez wrote the book this comes from, years ago.", "Prof"),
])
def test_an_abbreviation_is_not_a_title_however_short_it_is(text, label):
    """⚠️ SIX OF THESE GOT THROUGH, FOUND BY AN ADVERSARIAL REVIEW RATHER THAN BY THE CORPUS. The
    period form needed only three words and an initial capital, which an abbreviation has, and the
    label is then REMOVED from the front of the text: "Mrs. Smith gave me this recipe" became a
    heading "Mrs" over "Smith gave me this recipe". The measurement behind the ceiling was the 9
    period-form leads the 300 recipes carry, and abbreviations are absent from that sample, which
    is docs/measuring-the-premise.md's own failure mode."""
    plan = ic.note_title_plan(text)
    assert plan.verdict == "no title", plan
    assert plan.title is None
    assert plan.text == text, "and not one word came off the front"
    assert label.lower() in plan.reason.lower() or "abbreviation" in plan.reason


@pytest.mark.parametrize("text", [
    "No. 5 flour works best here, or anything close to it.",
    "Approx. 40 minutes before serving, take it out of the fridge.",
    "Vs. the original, this uses half the butter and no cream.",
])
def test_a_body_that_does_not_open_a_new_sentence_refuses_the_period_form(text):
    """The second piece of evidence, and the one that needs no list: a lowercase word or a digit
    after the stop is proof the stop did not end a sentence."""
    plan = ic.note_title_plan(text)
    assert plan.verdict == "no title", plan
    assert plan.text == text


def test_the_abbreviation_list_is_maintained_and_the_corpus_is_not_its_authority():
    """⚠️ THE RULE THE INGREDIENT CAPITALIZATION PASS STATES, APPLIED HERE. The 300 recipes carry
    none of these, so "the corpus does not do it" is no evidence at all. The list is the record of
    a decision, so it is read back rather than taken on trust."""
    for word in ("mrs", "dr", "st", "no", "vs", "approx", "etc", "tbsp"):
        assert word in ic.NOTE_TITLE_ABBREVIATIONS, word
    assert all(w == w.lower() and "." not in w for w in ic.NOTE_TITLE_ABBREVIATIONS)
    # and a real title is not on it, which is what would make the list a bug rather than a fix
    for word in ("flour", "storing", "measurements", "dashi", "mirin", "pekmez"):
        assert word not in ic.NOTE_TITLE_ABBREVIATIONS, word


@pytest.mark.parametrize("text,dash", [
    ("Salt — and this is important — goes in at the very end.", "—"),
    ("Chicken — or pork, if you prefer — works just as well here.", "—"),
    ("Salt - and this is important - goes in at the end.", "-"),
    ("Flour – the good kind – makes the difference here.", "–"),
])
def test_a_paired_dash_encloses_rather_than_labels(text, dash):
    """⚠️ THE SAME REVIEW'S SECOND FINDING. The marked form skips the clause test, which is required
    so that waffle's "For waffles that stay crisp:" is admitted, and that let an em dash used as a
    parenthetical be read as a label: "Salt" over a body starting "and this is important".
    Measured over the corpus: 8 notes carry a dash-form title and none is paired, and the two notes
    that do have a second spaced dash are known labels whose second dash falls after a full stop."""
    plan = ic.note_title_plan(text)
    assert plan.verdict == "no title", plan
    assert plan.title is None
    assert plan.text == text
    assert "pair" in plan.reason


def test_a_dash_label_whose_body_uses_a_dash_LATER_is_still_a_title():
    """The other side of the pair test. The closing dash of a parenthetical sits inside the same
    sentence; a dash in a later sentence is just punctuation."""
    plan = ic.note_title_plan("Pekmez - Available at Middle Eastern stores. Brush it on - it "
                              "glazes well.")
    assert (plan.verdict, plan.title) == ("title", "Pekmez")
    # and the corpus's two real cases, which are known labels and never reach the dash rule
    assert ic.note_title_plan(
        "Leftovers – Best to pan fry fresh. Excellent for prepare ahead – keep the beef "
        "separate.").verdict == "label"


@pytest.mark.parametrize("line", ["**Season** well, then **rest**", "*Really* good *tip*",
                                  "***Important***", "_a_b_", "*   *", "_ _", "**  **"])
def test_strip_emphasis_is_strip_wrapping_marks_and_no_longer_mangles_text(line):
    """⚠️ TWO FUNCTIONS ANSWERED ONE QUESTION AND THE OLDER ONE MANGLED TEXT. strip_emphasis used a
    backreference regex with no inner guard, so a real step "**Season** well, then **rest**" became
    a SECTION HEADING reading "Season** well, then **rest". Measured over all 6,235 of live's step,
    ingredient and note strings the two agreed on every one, so unifying changed nothing that
    exists. This is the shape CLAUDE.md shouts about: one rule set means one function."""
    assert ic.strip_emphasis(line) == line
    assert ic.strip_wrapping_marks(line) == (line, None)


@pytest.mark.parametrize("line,inner", [
    ("**Other Ingredients:**", "Other Ingredients:"),
    ("**Day 1**", "Day 1"),
    ("_Vanilla Cream Cheese Icing_", "Vanilla Cream Cheese Icing"),
    ("__Bold Underscore:__", "Bold Underscore:"),
])
def test_and_it_still_strips_every_wrap_it_always_did(line, inner):
    assert ic.strip_emphasis(line) == inner


def test_a_note_of_nothing_but_marks_keeps_them_rather_than_emptying(tmp_path=None):
    """⚠️ IT ABORTED A WHOLE IMPORT. "*   *" returned "" from the strip, note_title_plan handed back
    an empty text, and commit_plan died on recipe_notes' own CHECK (length(trim(text)) > 0). An
    empty inner is not a wrap."""
    plan = ic.note_title_plan("*   *")
    assert plan.text == "*   *"
    assert plan.marks is None
    assert plan.verdict == "no title"


# ---- a title may be written in any language (Andy's call, 2026-10-06) ---------------------------
# ⚠️ THE CORPUS HAS NO CASE, WHICH IS WHY THE GAP SURVIVED A WHOLE ROUND OF MEASUREMENT. Every
# threshold in this rule was measured over the 177 notes, and the 177 are entirely ASCII, so
# "measured against the corpus" said nothing at all about the letter class. The rule was ASCII-only
# and reproduced all 36 decisions while doing it.

@pytest.mark.parametrize("text,title,body", [
    ("Café: use a dark roast, it stands up to the milk.",
     "Café", "use a dark roast, it stands up to the milk."),
    ("Crème fraîche: stir it in off the heat so it does not split.",
     "Crème fraîche", "stir it in off the heat so it does not split."),
    ("Jalapeño – take the seeds out if you want it milder in the sauce.",
     "Jalapeño", "take the seeds out if you want it milder in the sauce."),
    ("Æbleskiver: turn them with a knitting needle rather than a fork.",
     "Æbleskiver", "turn them with a knitting needle rather than a fork."),
    # Greek and Cyrillic, which is where the look-alike repair had to be checked as well
    ("Ρίγανη: the Greek kind is dried on the stalk and keeps for a year.",
     "Ρίγανη",
     "the Greek kind is dried on the stalk and keeps for a year."),
    ("Борщ: serve it with a spoon of sour cream and plenty of dill.",
     "Борщ", "serve it with a spoon of sour cream and plenty of dill."),
])
def test_an_accented_or_non_latin_label_can_be_a_title(text, title, body):
    plan = ic.note_title_plan(text)
    assert plan.verdict == "title", plan.reason
    assert plan.title == title
    assert plan.text == body


def test_the_look_alike_repair_leaves_a_real_greek_or_cyrillic_title_alone():
    """⚠️ TWO RULES PULLING OPPOSITE WAYS, AND BOTH ARE RIGHT. normalize_lookalikes runs ahead of
    every label rule and rewrites "МАКЕ THE CHICKEN" because each non-Latin
    letter in it has a Latin twin. It declines Борщ and
    Ρίγανη because щ, γ and η have none, so widening the
    label class is what lets a real title in another script be read as a title rather than mangled
    into one in Latin."""
    for text in ["Борщ: serve it with a spoon of sour cream and plenty of dill.",
                 "Ρίγανη: the Greek kind is dried on the stalk."]:
        assert ic.normalize_lookalikes(text) == text
        assert ic.note_title_plan(ic.normalize_lookalikes(text)).verdict == "title"


def test_widening_the_letter_class_refuses_what_it_always_refused():
    """The two pieces of evidence the period form needs, and the clause test, read words rather than
    characters, so neither should move. Stated rather than assumed."""
    # an abbreviation is still not a title
    assert ic.note_title_plan(
        "Mrs. Smith gave me this recipe when we moved in next door.").verdict == "no title"
    # a clause word is still a statement
    assert ic.note_title_plan(
        "You can use Canned Chickpeas. Drain them well first.").verdict == "no title"
    # a paired dash still encloses
    assert ic.note_title_plan(
        "Salt - and this is important - goes in at the very end.").verdict == "no title"
    # a digit still opens no label
    assert ic.note_title_plan("500g: that is the flour, not the total weight.").verdict == "no title"
