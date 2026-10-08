#!/usr/bin/env python3
"""planahead.py - the plan-ahead wait: read a typed duration, and total a recipe's waits.

⚠️ THE TOTAL IS THE NORMAL MINIMUMS AND NOTHING ELSE. An extension never enters it. A recipe that
says "marinate 10 minutes to an hour (or overnight if time allows)" needs 10 minutes of planning,
not 8 hours, and the invitation is the cook's to take.

⚠️ A MAXIMUM TOTAL EXISTS ONLY IF EVERY WAIT HAS ONE. pepperoni-rolls rises for about an hour and
then rests 30 minutes, so 1 hr 30 min is a real ceiling. gai-yang says "at least 2 hours", so the
recipe has no ceiling at all and the total reads "2 hr+". Summing a missing max as if it equalled
the minimum would turn an open invitation into a promise.

⚠️ OVERNIGHT IS 8 HOURS FOR THE NUMBERS AND THE WORD FOR THE PAGE. 20 of the 72 proposals say
overnight or 'the day before', and no cook wants to read "Plan ahead 8 hr" where the recipe says
overnight. The label is stored as written and the minutes sit behind it.

⚠️ NOTHING HERE IS DERIVED FROM STEP TEXT AT READ TIME. read_duration runs on what a person typed
into the editor, once, on save. Editing a step does not move a wait, exactly as it does not move
prep_time.

⚠️ NO CLIENT MIRROR, ON PURPOSE. The reading happens on the way IN (app.py, on save) and the total
is computed on the way OUT and sent with the recipe. static/timefmt.js already had to be mirrored
because it runs at display time on 218 stored strings; this does not, and a second cross-language
pair is a cost with nothing buying it.
"""
import re

from import_cleanup import (_TIME_JOIN_RE, _TIME_SEG_RE, _TIME_UNITS, TIME_UNIT_MINUTES,
                            normalize_time, time_number)   # THE shared segment reader

# minutes per unit the segment reader may return, plus the two it does not carry
_MIN = dict(TIME_UNIT_MINUTES, day=1440, week=10080)
_UNIT_WORDS = dict(_TIME_UNITS)
_UNIT_WORDS.update({"day": "day", "days": "day", "week": "week", "weeks": "week"})

# ⚠️ A WORD THAT NAMES A DURATION WITHOUT A NUMBER. Measured on the corpus: 40 sentences over 31
#    recipes say overnight and 3 say the day before, and neither reaches any numeric reader.
_WORD_DURATIONS = (
    (re.compile(r"\bover\s?night\b", re.I), 480, None),
    (re.compile(r"\b(?:the day before|a day (?:ahead|in advance)|night before)\b", re.I), 480, None),
)

KINDS = ("marinating", "chilling", "rising", "soaking", "resting", "freezing", "brining", "other")
# The kind as a VERB, which is how the breakdown bullet reads it: "Chill 4 hr – overnight" rather
# than "4 hr – overnight chilling". Mirrored in static/app.js.
VERBS = {"marinating": "Marinate", "chilling": "Chill", "rising": "Rise", "soaking": "Soak",
         "resting": "Rest", "freezing": "Freeze", "brining": "Brine", "other": "Wait"}
SNIPPET_LEN = 48
WHERES = ("fridge", "freezer", "room temp", "other")
# ⚠️ 'alongside' IS A FOURTH VALUE ON A COLUMN THAT MEANS "does this wait always happen", and it is
# strictly speaking a different question: a wait could be both optional AND alongside, and one column
# cannot say so. Nothing in the corpus needs both (morning-buns' butter chill is unconditional, it just
# shares a night with the dough), so the collision costs nothing today. If a wait ever needs both, this
# is the seam that has to split into two columns.
WHENS = ("always", "optional", "only_if", "alongside")


def counts(w):
    """Does this wait reach the total? Only an unconditional one does.

    ⚠️ AN OPTIONAL SOAK IS NOT TIME A COOK HAS TO SET ASIDE. coconut-curried-golden-lentils soaks
    the lentils if there is time, and no-knead-bread rests the dough 45 to 60 minutes only when it
    went to the refrigerator. Summing either would tell a cook to block out hours for something the
    recipe already said they could skip. Both still show in the breakdown with their qualifier,
    because a wait a cook MIGHT take is worth reading before starting.

    ⚠️ when_kind ALONE DECIDES, AND IT USED TO READ alongside_step_id TOO. The alongside arm returned
    True when the pointer was null, on the ground that a wait overlapping nothing is ordinary waiting
    time. The client's own filter never had that arm, so the two readers of one rule disagreed on
    exactly that row: the server put it in the figure and the client left it out of `counted`, which
    on a one-wait recipe printed the head figure AND a bullet repeating it.

    The ruling is that this is a function of when_kind and of nothing else. A count that depends on
    whether a pointer still resolves is a count that changes when a step is deleted or converted to a
    heading, and neither of those is a statement about how long the cook has to wait. It also makes
    the rule small enough that the client does not need a copy: the answer rides on each wait as
    `in_total` (app.py's get_recipe) and the client filters on that.

    The cost is named rather than hidden: between a step being deleted and the next save, a wait that
    says 'alongside' and points at nothing is left out of the figure. write_plan_ahead normalizes that
    row back to 'always' on the next save, so the window is one page view wide, and the alternative is
    two implementations that cannot be held together by anything but attention.
    """
    return (w.get("when_kind") or "always") == "always"


# ⚠️ AN OVERNIGHT THAT IS THE FLOOR READS AS A FIGURE. "Plan ahead overnight" tells a cook nothing
#    they can put in a calendar, and the minutes behind it (480) were already right on all 14 rows
#    this touches. Only the words changed, and only on the way OUT.
#
#    THE THREE CASES THE CORPUS HAS, and the separator is what tells them apart:
#      A  "overnight" / "at least overnight" / "8 hr or overnight" / "the day before"
#            -> the word IS the minimum            -> "8 hr+ (overnight)"
#      B  "4 hr – overnight" / "6 hr – overnight"  -> the word is the CEILING, and 4 hr is the floor
#            -> left exactly as written, because rewriting it would lose the floor
#      C  the word lives in ext_label, not label   -> an invitation, not a requirement, left alone
#    Measured over the 94 stored waits: 14 are A, 7 are B, 4 are C.
_OVERNIGHT_WORD = re.compile(r"\b(over\s?night|the day before|night before)\b", re.I)
# The word preceded by a RANGE separator is case B. Nothing else in the label matters.
_OVERNIGHT_AS_CEILING = re.compile(r"(?:to|[-\u2013\u2014])\s*(?:over\s?night|the day before)\b", re.I)


def display_label(w):
    """What the page PRINTS for one wait. The stored label is never rewritten.

    ⚠️ IT IS COMPUTED SERVER-SIDE AND SENT, rather than mirrored in JS, for the reason at the top of
    this module. The client prints `label_text` and owns no second copy of this rule."""
    label = w.get("label") or ""
    m = _OVERNIGHT_WORD.search(label)
    if not m or _OVERNIGHT_AS_CEILING.search(label):
        return label
    lo = w.get("min_minutes")
    if lo is None:
        return label
    hi = w.get("max_minutes")
    figure = fmt_minutes(lo) if hi == lo else (f"{fmt_minutes(lo)}+" if hi is None
                                               else f"{fmt_minutes(lo)} \u2013 {fmt_minutes(hi)}")
    # The author's own word is kept beside the figure, so "the day before" does not become
    # "overnight". They are not the same instruction to a cook reading it the night before.
    return f"{figure} ({m.group(0).lower()})"


def alongside_label(w):
    """" alongside step 3", or "" for a wait that overlaps nothing. The caller renders it beside the
    wait's own words, the same way when_suffix renders "(optional)"."""
    n = w.get("alongside_no")
    return f" alongside step {n}" if n else ""


def read_duration(text):
    """Typed text -> (min_minutes, max_minutes). Either may be None.

    (None, None) means the words carried no duration, and the caller keeps the words. A None max
    with a real min is OPEN-ENDED.

        '1 hr rise'                  -> (60, 60)
        '8-12 hr cold proof'         -> (480, 720)
        'at least 2 hours'           -> (120, None)
        '2 hr+'                      -> (120, None)
        'overnight'                  -> (480, None)
        'until it smells right'      -> (None, None)
    """
    s = (text or "").strip()
    if not s:
        return None, None
    # ⚠️ THE FIRST SEGMENT IS NOT ALWAYS THE FIRST TIME, AND READING ONLY THE FIRST ONE LOST SIX
    #    REAL DURATIONS. A word number matches "twelve balls" and "one batch", whose unit is not a
    #    time word, so "or roll into twelve balls and chill 30 minutes" refused the 30 minutes it
    #    had read before. The extension sentences in docs/data-repairs/ are written exactly that
    #    way. Scan for the first segment whose UNIT is a time.
    if _TRAILING_FRACTION_ANYWHERE.search(s):
        return None, None
    m = unit = None
    for probe in _TIME_SEG_RE.finditer(s):
        word = _UNIT_WORDS.get(probe.group("unit").lower())
        if word and time_number(probe.group("lo")) is not None:
            m, unit = probe, word
            break
    if m and unit:
        # time_number, not float: the segment reader admits "2 1/2", "1½", "¾" and "half" now,
        # and float() read the first of those as a bare 2 and refused the other three.
        lo = time_number(m.group("lo")) * _MIN[unit]
        hi = lo
        if m.group("hi") is not None and time_number(m.group("hi")) is not None:
            hi = time_number(m.group("hi")) * _MIN[unit]
        # ⚠️ A SECOND SEGMENT MEANS ONE OF TWO THINGS AND THE SEPARATOR SETTLES IT.
        #    "10 min to 1 hr" is a RANGE ACROSS UNITS, which _TIME_SEG_RE cannot see because its
        #    `hi` group only catches a bare number. Read as a continuation it gave (10, 10), which
        #    silently halves a real marinade. "1 hr 30 min" is ADDITIVE and has no separator.
        rest = s[m.end():]
        sep = _RANGE_SEP.match(rest)
        m2 = _TIME_SEG_RE.match(rest[sep.end():] if sep else rest.lstrip(" ,"))
        u2 = _UNIT_WORDS.get(m2.group("unit").lower()) if m2 else None
        if m2 is not None and time_number(m2.group("lo")) is None:
            m2 = u2 = None
        # ⚠️ THE HIGH END CAN BE A WORD. "6 hr – overnight" is 3 of the proposals, and without this
        #    it read as a flat 6 hours, dropping the half of the range the cook plans around.
        if sep and not m2 and not m.group("hi"):
            for pat, wlo, _whi in _WORD_DURATIONS:
                if pat.match(rest[sep.end():]):
                    return int(lo), wlo
        if m2 and u2 and not m.group("hi"):
            other = time_number(m2.group("lo")) * _MIN[u2]
            if sep:
                hi = other                                  # the high end of a cross-unit range
            elif _MIN[u2] < _MIN[unit]:
                lo = hi = lo + other                        # "1 hr 30 min'
        nf = _NO_FLOOR.search(s)
        if _OPEN_ENDED.search(s):
            # Both markers together state a real range, so both ends hold: "at least 12 hours and
            # up to 48" is 12 to 48, not 12 with no ceiling. The ceiling is the figure AFTER the
            # "up to", which the leading segment reader never reaches.
            m3 = _TIME_SEG_RE.search(s[nf.end():]) if nf else None
            u3 = _UNIT_WORDS.get(m3.group("unit").lower()) if m3 else None
            n3 = time_number(m3.group("lo")) if m3 else None
            hi = n3 * _MIN[u3] if (m3 and u3 and n3 is not None) else None
        # ⚠️ "up to X" IS A CEILING AND WAS BEING READ AS A FLOOR. "up to 1 week" returned
        #    (10080, 10080), which says a week is required where the recipe says a week is the most.
        #    Measured on the v2 proposals: 22 rows carry this shape. All 22 are storage today, which
        #    reaches no total, so nothing shipped wrong, and the first wait that says "chill up to
        #    2 hours" would have told a cook to set aside 2 hours for it. The floor is 0, not null,
        #    because a null min already means the reader could not parse the text at all.
        elif hi is not None and nf:
            lo = 0
        # int(n + 0.5) for the reason clock_minutes gives: int() read half a minute as 0.
        return int(lo + 0.5), (None if hi is None else int(hi + 0.5))
    for pat, lo, hi in _WORD_DURATIONS:
        if pat.search(s):
            return lo, hi
    return None, None


# ⚠️ "at least" AND A TRAILING "+" BOTH MEAN NO CEILING. 45 of the 72 proposals are open-ended and
#    most of them say it in words rather than by leaving the range off.
_RANGE_SEP = re.compile(r"\s*(?:to|[-\u2013\u2014])\s*", re.I)
# ⚠️ A FIGURE CONTINUED BY "AND A HALF" IS NOT READABLE HERE EITHER. The segment reader sees the
# hour and not the half, so answering 60 for an hour and a half is worse than answering nothing.
# The mirror of import_cleanup's _TIME_TRAILING_FRACTION.
_TRAILING_FRACTION_ANYWHERE = re.compile(
    r"\band\s+(?:a\s+)?(?:half|quarter|third|three\s+quarters)\b", re.I)
_OPEN_ENDED = re.compile(r"\b(?:at least|minimum(?: of)?|or (?:more|longer|overnight))\b|\+\s*$", re.I)
# The mirror of the line above. "at least" removes the ceiling, "up to" removes the floor, and a
# text carrying both ("at least 12 hours and up to 48") states a real range and keeps both ends.
_NO_FLOOR = re.compile(r"\b(?:up to|no more than|at most|maximum(?: of)?)\b", re.I)


def total(waits):
    """[{min_minutes, max_minutes, when_kind}] -> (min_total, max_total). max_total is None when ANY
    counted wait is open-ended, and None minutes anywhere are skipped rather than counted as zero.

    ⚠️ CONDITIONAL WAITS ARE FILTERED OUT FIRST, so a recipe whose only wait is optional has no
    plan-ahead total at all, which is the truthful answer."""
    counted = [w for w in waits if counts(w)]
    mins = [w.get("min_minutes") for w in counted]
    maxs = [w.get("max_minutes") for w in counted]
    known = [m for m in mins if m is not None]
    if not known:
        return None, None
    lo = sum(known)
    hi = sum(maxs) if counted and all(m is not None for m in maxs) else None
    return lo, hi


def clock_minutes(text):
    """A prep/cook/total column -> (lo, hi) minutes, or (None, None) if it is not a duration.

    ⚠️ IT IS NOT read_duration, AND MIXING THEM UP WOULD BE SILENT. read_duration reads what a person
    typed into a WAIT box, where "at least 2 hours" means no ceiling and "up to 1 week" means no
    floor. A time column is a flat clock figure: "1 hr 15 min" is 75 minutes and nothing about it is
    open-ended. Running the wait reader over a prep time would turn "up to 30 min" into a floor of 0.

    It mirrors import_cleanup.normalize_time's SEGMENT LOOP, which is the function that decides what
    counts as a duration in these three columns, so a string that normalizes reads here and a string
    that does not (2 of the 216 stored times are not times at all) returns (None, None) rather than a
    guess.

        "35 min"                     -> (35, 35)
        "1 hr 15 min"                -> (75, 75)
        "15-20 minutes"              -> (15, 20)
        "2 hr 45 min"                -> (165, 165)
        "35 min (plus 1 hr soaking)" -> (35, 35)   the NOTE is not part of the figure
        "1 cup"                      -> (None, None)
    """
    s = (text or "").strip()
    if not s:
        return None, None
    if _TRAILING_FRACTION_ANYWHERE.search(s):
        return None, None
    lo = hi = 0.0
    pos, seen = 0, 0
    while pos < len(s):
        probe = _TIME_JOIN_RE.match(s, pos).end() if seen else pos
        m = _TIME_SEG_RE.match(s, probe)
        if not m:
            break
        unit = _TIME_UNITS.get(m.group("unit").lower())
        if not unit:
            break
        a = time_number(m.group("lo"))
        if a is None:
            break                       # the regex matched a shape that is not a number (1/0)
        b = time_number(m.group("hi")) if m.group("hi") else a
        if b is None:
            b = a
        lo += a * _MIN[unit]
        hi += b * _MIN[unit]
        seen += 1
        pos = m.end()
    if not seen:
        return None, None
    # ⚠️ ROUNDED, NOT TRUNCATED. int() read "half a minute" as 0 minutes, and round() reads it as 0
    #    too, because Python rounds a half to the even number. Every whole-number case is
    #    unchanged, because int(n + 0.5) of an integer is that integer.
    return int(lo + 0.5), int(hi + 0.5)


# What the Total line says when the plan-ahead waits are inside the figure. A cook seeing
# "Total 8 hr 30 min" on a stir fry needs to know the eight hours are a marinade, not the cooking.
INCLUDES_WAITS_NOTE = "incl. plan ahead"


# The three answers to "does the author's stated total already include the waits that always
# apply?". Named rather than returned as bare strings, so a caller cannot invent a fourth.
STATED_EXCLUDES = "excludes"      # the total is SHORTER than those waits, so it cannot contain them
STATED_UNCLEAR = "unclear"        # long enough to hold them, short enough that it might not
STATED_INCLUDES = "includes"      # prep + cook + the waits fits inside it
STATED_NO_QUESTION = "no question"   # no stated total, or no waits that always apply


def stated_minutes(stated):
    """An author's stated total -> (low, high) minutes, with None for an end that is not stated.

    ⚠️ clock_minutes CANNOT SEE AN OPEN END, AND IT READS ONE AS A CEILING. normalize_time rewrites
    a trailing "+" into " (+)", a parenthetical note, and clock_minutes then answers "1 hr+" with
    (60, 60). So the one shape that says "at least" comes back claiming "exactly", which is the
    worst direction for a rule that overrules an author on the strength of an upper bound.

    ⚠️ AND THE "+" IS READ OFF THE RAW TEXT, BEFORE normalize_time TOUCHES IT. The previous attempt
    did `normalize_time(stated).rstrip("+")` and then tested the result for a trailing "+", which
    normalize_time has by then turned into "(+)". Measured: the test was False for every "+" form
    there is, so the branch behind it never ran once. A guard that cannot fire is worse than none,
    because the test written for it passes.

    One function, because `recipe_total` and `stated_total_verdict` both need this and the parse is
    precisely the thing that was wrong when it was written twice.
    """
    text = (stated or "").strip()
    if not text:
        return None, None
    lo, hi = clock_minutes(normalize_time(text))
    if lo is None:
        return None, None
    return (lo, None) if text.rstrip().endswith("+") else (lo, hi)


def stated_total_verdict(recipe, waits):
    """Does the author's stated total already include the waits that always apply?

    -> (verdict, stated_minutes, always_wait_minutes). The minutes are None where there is no
    question to answer.

    ⚠️ THE ONE THING THE PAGE CAN KNOW FOR CERTAIN IS ARITHMETIC. A total cannot contain waits that
    alone take longer than it. earl-grey-tea-cake states 1 hr and carries a 1 hr 30 min rest that
    always applies, so "Total 1 hr" with "Plan ahead 1 hr 30 min+" under it is two figures that
    cannot both describe the same recipe. That is the ONLY case where the page may add the waits
    on top of an author's own figure, and it is decided by a comparison rather than by a guess.

    ⚠️ AND THE MIDDLE CASE IS "CAN'T TELL", WHICH IS NOT "INCLUDES". A stated total long enough to
    hold the waits may or may not have counted them. miso-tofu states 25 min with 15 min of resting
    and 25 minutes of prep and cook, so either reading fits. Nothing on the page can settle it, so
    the author's figure stands and the recipe goes on a list for a person to decide. Guessing here
    would silently rewrite a figure the author got right.

    ⚠️ MISSING prep OR cook LANDS IN THE SAME "CAN'T TELL". all-butter-pie-crust states 1 hr 15 min
    with a 1 hr chill and no cook time, so the upper bound cannot be computed at all. Unanswerable
    is the unclear answer, never the settled one, which is the direction every other guard here
    fails in.

    ⚠️ AND SO DO THE TWO SHAPES THAT ARE NOT A BARE NUMBER, for the same reason stated twice.
      * An OPEN END ("1 hr+") has no ceiling to be below the waits. "At least an hour" holds a
        90 minute rest perfectly well, so the arithmetic proves nothing.
      * A total carrying its OWN NOTE ("35 min (plus 1 hr soaking)") has already answered this in
        words. The figure is not the whole of what the author wrote, and overruling it would print
        "Author's total: 35 min, before the waits" against an author who said the opposite.
    Both reached EXCLUDES before, both by reading the FLOOR of the stated total as though it were
    the whole of it. 0 of live's 14 stated totals are either shape, so no page moved.

    Measured over live's 300, read only, 2026-10-07: 1 excludes (earl-grey-tea-cake), 0 unclear,
    1 includes (no-knead-bread), 298 no question. Two of that 298 are the recipes a person
    ANSWERED, which is the state the two paragraphs above are written to produce: miso-tofu-recipe
    carries a 0 and all-butter-pie-crust a 1. Both would read "unclear" with their rulings removed,
    and both are named there because the question they were asked is the one this function asks.

    ⚠️ AN EARLIER VERSION OF THIS LINE COUNTED THEM AS UNCLEAR, which this function has never
    returned for either. The ruling is read before the arithmetic and ends the question, so a
    docstring reporting the pre-ruling verdict was describing a call nobody makes.
    """
    get = (lambda k: recipe.get(k)) if isinstance(recipe, dict) else (
        lambda k: getattr(recipe, k, None))
    stated = (get("total_time") or "").strip()
    always = [w for w in (waits or []) if counts(w)]
    alo, _ahi = total(always)
    if not stated or not always or alo is None:
        return STATED_NO_QUESTION, None, None
    # ⚠️ A RECORDED DECISION ENDS THE QUESTION, IN BOTH DIRECTIONS. total_includes_waits is a
    #    person's answer to exactly this, and the page has no business re-deriving it or asking for
    #    it again. miso-tofu-recipe carries a 0 ("the author did not count them"), which is why its
    #    Total has read "40 min+ (incl. plan ahead)" since migration 058, and it would otherwise
    #    land in the unclear bucket and be put on a list asking for a decision that exists.
    if get("total_includes_waits") is not None:
        return STATED_NO_QUESTION, None, None
    slo, shi = stated_minutes(stated)
    if slo is None:
        return STATED_NO_QUESTION, None, None
    # ⚠️ A TOTAL THAT CARRIES ITS OWN NOTE HAS ALREADY ANSWERED THIS, IN WORDS. "35 min (plus 1 hr
    #    soaking)" parses to 35 minutes, and the figure is not the whole of what the author said.
    #    Declaring it impossible would print "Author's total: 35 min, before the waits" against an
    #    author whose own text says the soaking is on top, which is not dropping information, it is
    #    contradicting them. The arithmetic cannot read the note, so this is the middle case and a
    #    person reads it. The "(" is tested on the RAW text: normalize_time turns a trailing "+"
    #    into "(+)", and that case is already the middle one for its own reason.
    #    Measured over live's 300: 0 of the 14 stated totals carry a parenthetical, so no page moves.
    if "(" in stated:
        return STATED_UNCLEAR, slo, alo
    # ⚠️ THE CEILING ANSWERS THIS, NOT THE FLOOR. The claim being made is that the author's total
    #    CANNOT contain these waits, and that is only proved when the longest the total could be is
    #    still shorter than the waits alone. This read the floor, so "1 to 2 hr" with 2 hr of waits
    #    was declared impossible when the author's own upper end holds it exactly, and "1 hr+" was
    #    declared impossible when "at least 1 hr" holds anything at all. Both overruled a figure the
    #    author may have got right, which is the one thing the middle case exists to refuse.
    #    An open end is shi None, which can never be below alo, so it falls through to "can't tell"
    #    and the recipe goes on the list for a person. Measured over live's 300: all 14 stated
    #    totals are a single closed figure, so this changes no page today.
    if shi is not None and shi < alo:
        return STATED_EXCLUDES, slo, alo
    plo, _phi = clock_minutes(get("prep_time"))
    clo, _chi = clock_minutes(get("cook_time"))
    if plo is None or clo is None or slo < plo + clo + alo:
        return STATED_UNCLEAR, slo, alo
    return STATED_INCLUDES, slo, alo


def author_total_note(recipe, waits):
    """The lighter line under a Total the page has added the waits to -> text, or None.

    ⚠️ THE AUTHOR'S OWN FIGURE IS NEVER DELETED, ONLY MOVED DOWN A LINE. The Total above it is the
    page's arithmetic and says so with "(incl. plan ahead)". This says what the author wrote, so a
    cook comparing the page against the source card finds their number rather than wondering where
    it went. Same rule as the second Total: one figure the recipe costs, one line saying which path
    it describes.
    """
    verdict, _slo, _alo = stated_total_verdict(recipe, waits)
    if verdict != STATED_EXCLUDES:
        return None
    get = (lambda k: recipe.get(k)) if isinstance(recipe, dict) else (
        lambda k: getattr(recipe, k, None))
    figure, _note = _stated_parts((get("total_time") or "").strip())
    return f"Author's total: {figure}, before the waits"


def recipe_total(recipe, waits):
    """The Total the recipe page prints -> (label, note) or (None, None).

    ⚠️ COMPUTED AT DISPLAY AND NEVER STORED. A stored total goes stale the first time a step or a
    wait is edited, and there is nothing to tell the cook it has.

    THE RULES, in order:
      * A stated total is the author's answer and is shown unchanged. Adding waits on top of it would
        contradict them. no-knead-bread says 2 hr 45 min and that figure already includes the rise.
      * Otherwise, prep AND cook both present -> prep + cook + every COUNTED wait. Missing either one
        means there is no total to give, because a part of it is unknown.
      * A range stays a range and an open-ended wait leaves the total open-ended, exactly as
        planahead.total already decides for the plan-ahead figure itself.
      * total_includes_waits overrides the first two. It is NULL on 299 of 300 recipes.

    ⚠️ ONE IMPLEMENTATION, SERVER SIDE. The client prints the label it is handed. See the header.
    """
    get = (lambda k: recipe.get(k)) if isinstance(recipe, dict) else (lambda k: getattr(recipe, k, None))
    stated = (get("total_time") or "").strip()
    ruling = get("total_includes_waits")
    counted = [w for w in (waits or []) if counts(w)]
    wlo, whi = total(counted)
    has_waits = wlo is not None

    if stated and ruling != 0:
        # ⚠️ UNTOUCHED UNLESS IT IS ARITHMETICALLY IMPOSSIBLE. The author's figure is the answer,
        #    and the one thing that can overrule it is a total shorter than the waits it would have
        #    to contain. stated_total_verdict is the whole of that rule and there is no second copy
        #    of it. ruling == 1 says "the author counted the waits" explicitly, and it is read
        #    BEFORE this, so an explicit ruling still wins.
        if stated_total_verdict(recipe, waits)[0] == STATED_EXCLUDES:
            # ⚠️ shi CANNOT BE None HERE. A verdict of EXCLUDES needs a stated ceiling below the
            #    waits, so an open-ended total never reaches this line. The branch that used to
            #    blank shi for a "+" has gone with it: it never ran, and it was guarding a case
            #    that is now answered one level up by not being EXCLUDES at all.
            slo, shi = stated_minutes(stated)
            return _range_label(slo + wlo, None if whi is None else shi + whi), \
                INCLUDES_WAITS_NOTE
        # The author's own figure, untouched. ruling == 1 says the same thing explicitly.
        return _stated_parts(stated)
    plo, phi = clock_minutes(get("prep_time"))
    clo, chi = clock_minutes(get("cook_time"))
    if plo is None or clo is None:
        # ⚠️ A STATED TOTAL STILL WINS EVEN WHEN THE RULING SAYS "ADD THE WAITS", because there is
        #    nothing to add it to. Showing the author's figure beats showing none.
        return _stated_parts(stated) if stated else (None, None)
    base_lo, base_hi = plo + clo, phi + chi
    if not has_waits or ruling == 1:
        return _range_label(base_lo, base_hi), None
    lo = base_lo + wlo
    hi = None if whi is None else base_hi + whi
    return _range_label(lo, hi), INCLUDES_WAITS_NOTE


def conditional_totals(recipe, waits):
    """The second Total, one line per conditional wait -> [{"label", "when"}].

    ⚠️ ANDY'S RULE: THE MAIN TOTAL IS UNCHANGED AND THIS SITS UNDER IT. The Total answers "how long
    does this take", and an optional soak is not time a cook has to set aside (see counts). But a
    cook who IS going to soak the beans still has to know what that costs, and working it out from a
    total and a bullet is arithmetic the page can do for them.

    ⚠️ ONE LINE PER CONDITIONAL WAIT, NOT ONE LINE PER COMBINATION. Measured over the 300: 5 recipes
    carry a conditional wait and exactly ONE carries two (no-knead-bread, an optional cold rise of
    up to 3 days and a 45 to 60 minute rest only if chilled). Two lines there read as two choices a
    cook makes one at a time, which is what they are, where a combined line would read as a third
    figure for a path nobody described. Each line names its own condition, so a chain says so.

    ⚠️ AND `alongside` IS NOT ONE OF THESE. A wait that runs alongside the cooking is not a longer
    path through the recipe, it is the same path with something happening next to it.

    Returns [] when there is no base to add to, which is the same silence recipe_total keeps."""
    get = (lambda k: recipe.get(k)) if isinstance(recipe, dict) else (
        lambda k: getattr(recipe, k, None))
    conditional = [w for w in (waits or [])
                   if _when(w) in ("optional", "only_if")]
    if not conditional:
        return []
    # ⚠️ THE BASE IS THE FIGURE THE PAGE ACTUALLY PRINTS, NOT A SECOND OPINION ABOUT IT. The second
    #    Total is read as "the Total, plus this", so a reader subtracts one from the other. If the
    #    author STATED a total, that is what sits above this line, and computing from prep + cook
    #    instead would put two figures on the page whose difference is not the wait. no-knead-bread
    #    is the case: it states 2 hr 45 min and its stated figure already includes the rise.
    shown, _note = recipe_total(recipe, waits)
    # ⚠️ A TRAILING "+" IS THE OPEN END, AND clock_minutes CANNOT SEE IT. _range_label prints the
    #    floor plus a "+" whenever the real answer is longer, so reading the label back gives one
    #    number and loses that. Dropping it would turn "11 hr 10 min+" into "11 hr 10 min" and state
    #    a ceiling the recipe never had.
    open_ended = bool(shown) and shown.rstrip().endswith("+")
    base_lo, base_hi = clock_minutes(shown.rstrip("+")) if shown else (None, None)
    if open_ended:
        base_hi = None
    if base_lo is None:
        plo, phi = clock_minutes(get("prep_time"))
        clo, chi = clock_minutes(get("cook_time"))
        if plo is None or clo is None:
            return []
        counted = [w for w in (waits or []) if counts(w)]
        wlo, whi = total(counted)
        base_lo = plo + clo + (wlo or 0)
        base_hi = None if (whi is None and counted) else phi + chi + (whi or 0)

    out = []
    for w in conditional:
        lo, hi = _minutes(w)
        if lo is None:
            continue
        top = None if base_hi is None or hi is None else base_hi + hi
        # ⚠️ A FLOOR OF ZERO HAS NO SECOND TOTAL, AND SAYING NOTHING BEATS SAYING EITHER ANSWER.
        #    The main Total's convention is the shortest time plus a "+". A wait stored 0 to 4320
        #    ("up to 3 days", no-knead-bread, the one case in the 300) has a floor that adds
        #    nothing, so the floor form printed the SAME figure as the Total above it and answered
        #    the question with the question. Reading it from the ceiling instead gives "73 hr
        #    10 min", which is arithmetic rather than an answer, and fmt_minutes has no day form to
        #    make it readable. The wait is still in the plan-ahead breakdown with its own words,
        #    which is where "up to 3 days" reads properly.
        if lo == 0:
            continue
        label = _range_label(base_lo + lo, top)
        if label is None:
            continue
        out.append({"label": label, "when": _conditional_phrase(w)})
    return out


def _conditional_phrase(w):
    """How a conditional line names its own condition.

    ⚠️ THE AUTHOR'S WORDS WHERE THERE ARE ANY. only_if carries a when_label written for this exact
    recipe ("the dough was refrigerated ahead"), and nothing a rule invents will beat it. An
    optional wait has no condition to state, so it is named by what it IS.

    ⚠️ "if you soak", NOT "with the optional soak". Andy's wording, chosen off the preview. The
    second total is read as a path the cook may take, and the condition for taking it is something
    they DO, so the line says so in the second person the rest of the app's microcopy uses. It is
    built here rather than in the client for the reason everything else about the Total is: one
    implementation, and the page prints what it is handed.

    ⚠️ AND IT READS THE VERB, NOT THE KIND NOUN. _kind_noun answers "marinade" where VERBS answers
    "Marinate", and "if you marinade" is not a sentence. The verb table is the same one the
    breakdown line leads with, so the two halves of the block name the wait the same way."""
    when = _when(w)
    label = (w.get("when_label") or "").strip()
    if when == "only_if":
        return f"if {label}" if label else "on that path"
    if label:
        return f"with {label}"
    verb = VERBS.get((w.get("kind") or "").strip().lower())
    return f"if you {verb.lower()}" if verb else "if you take it"


def _kind_noun(w):
    """The wait's kind as a noun a sentence can carry: "soak", "rise", "chill"."""
    kind = (w.get("kind") or "").strip().lower()
    return {"soaking": "soak", "rising": "rise", "chilling": "chill", "marinating": "marinade",
            "resting": "rest", "freezing": "freeze", "brining": "brine"}.get(kind, "")


def _when(w):
    return (w.get("when_kind") or "always").strip() or "always"


def _minutes(w):
    return w.get("min_minutes"), w.get("max_minutes")


def _stated_parts(stated):
    """An author's own total -> (figure, note), normalized the way every other stored time is.

    ⚠️ THE SPLIT HAPPENS HERE BECAUSE THE CLIENT MUST NOT SPLIT A COMPUTED ONE. The reading view used
    to run timeParts over whatever sat in the Total slot, which is right for a stored string ("2 hr,
    30 min" -> "2 hr 30 min", "35 min (plus 1 hr soaking)" -> a figure and a note) and WRONG for a
    computed range: timeParts stops at the en dash, so "40 min - 45 min" came back as "40 min" and
    the upper end was silently dropped. Measured on miso-tofu, butter-chicken and brioche-bread.
    Normalizing both cases here means the label the client prints is final either way."""
    text = normalize_time(stated)
    if text.endswith(")") and " (" in text:
        figure, note = text.rsplit(" (", 1)
        return figure, note[:-1]
    return text, None


def _range_label(lo, hi):
    """(lo, hi) minutes -> the COMPUTED Total's figure. The shortest time, and a '+' whenever the
    real answer is longer than it.

    ⚠️ THE SHORTEST TIME PLUS A '+', NOT BOTH ENDS, AND ONLY HERE. A computed Total is a SUM of
    ranges, so its two ends drift apart much further than any one part of it: butter-chicken's
    marinade is "1 to 22 hr" and the total that carries it printed "3 hr 35 min - 24 hr 35 min",
    which is 27 characters of arithmetic answering a question a cook asked in one word. The floor is
    the number they need, and the '+' says the ceiling exists.

    ⚠️ THE PLAN AHEAD LINE KEEPS BOTH ENDS, and total_label holds its own copy of the range spelling
    for exactly that reason. There the range IS the content: a cook deciding whether to start the
    marinade tonight needs to know it tolerates 22 hours, and that line names one wait rather than
    summing four things. A publisher's stated total is untouched too, because _stated_parts
    normalizes what the author wrote and never recomputes it.

    An open-ended hi already read this way, so the '+' is one spelling for both cases rather than a
    new one: a range and an unbounded wait both mean "at least this"."""
    if lo is None:
        return None
    if hi is None or hi != lo:
        return f"{fmt_minutes(lo)}+"
    return fmt_minutes(lo)


def fmt_minutes(m):
    """Minutes -> the app's own duration spelling. Mirrors what normalize_time writes."""
    if m is None:
        return ""
    if m >= 1440 and m % 1440 == 0:
        d = m // 1440
        return f"{d} day" + ("s" if d > 1 else "")
    if m >= 60:
        h, rem = divmod(m, 60)
        return f"{h} hr {rem} min" if rem else f"{h} hr"
    return f"{m} min"


def total_label(waits):
    """What the page prints beside 'Plan ahead'. A single counted wait shows its own words, so
    'overnight' stays 'overnight'. Several show the summed figure, because no one wrote that
    sentence. A recipe whose waits are all conditional has no figure and prints nothing here."""
    counted = [w for w in waits if counts(w)]
    if len(counted) == 1:
        return display_label(counted[0])
    lo, hi = total(waits)
    if lo is None:
        return ""
    if hi is None:
        return f"{fmt_minutes(lo)}+"
    return fmt_minutes(lo) if hi == lo else f"{fmt_minutes(lo)} – {fmt_minutes(hi)}"


# ---------------------------------------------------------------------------------------------
# The step pointer. See migration 051.
# ---------------------------------------------------------------------------------------------

_TAGS = re.compile(r"<[^>]+>")


def step_key(text):
    """A step's text reduced to what the check compares: tags stripped, whitespace collapsed,
    lowercased. Formatting changes do not break a link. Re-wording does, which is the point."""
    return " ".join(_TAGS.sub(" ", text or "").split()).lower()


# ⚠️ BOTH OF THE NEXT TWO ARE RETIRED FROM THE LIVE PATH BY MIGRATION 053. resolve_steps reads
# step_id and needs no snippet, and app.write_plan_ahead no longer computes one. They stay because
# scripts/apply_plan_ahead_proposals.py, a one-off that has already run, still imports step_snippet,
# and because deleting a pure function that a committed script references buys nothing.
def step_snippet(text, length=SNIPPET_LEN):
    """The stored check: the first `length` characters of the normalized step text.

    ⚠️ THE FRONT OF THE STEP, NOT THE MATCHED SENTENCE. A wait is usually read from a sentence in
    the middle of a step, and storing that sentence would keep matching after the rest of the step
    was rewritten around it. The opening is what identifies WHICH step this is."""
    return step_key(text)[:length] or None


def step_ok(step_text, check):
    """Does the step at the stored position still look like the step the wait was read from?

    A missing check is not a failure: rows written before 051 have no snippet, and a wait with a
    position and no check keeps its link. A check that is present and absent from the step DOES
    fail, and the caller drops the link rather than pointing at the wrong step."""
    if not check:
        return True
    return check in step_key(step_text)


def resolve_steps(waits, steps):
    """Decide each wait's step link against the steps as they stand NOW.

    `steps` is the recipe's rows in position order, each a mapping with id, is_heading, text. Adds two
    keys to every wait, in place:
      step_no  - the number the page prints ("Step 4"), heading-EXCLUDED to match the CSS counter,
                 or None when there is no usable link
      step_ok  - False only when the link names a row that is not a numbered step (see below)

    ⚠️ IT READS step_id NOW, AND THAT DELETED MOST OF THIS FUNCTION'S JOB. It used to take
    step_position and re-derive whether that slot still held the step the wait came from, by comparing
    a stored snippet of the text (step_check). Every branch of that was about detecting drift a save
    had caused, because write_recipe_rows renumbered every step on every save. An id does not drift.
    Migration 053 retired both columns.

    ⚠️ THE NUMBER IS NOT THE ID, AND IT IS NOT THE POSITION EITHER. Headings sit in the same table as
    steps and carry positions but are not numbered, so the third row can print as Step 2. The number is
    counted here, heading-excluded, to match what the CSS counter prints.

    ⚠️ step_ok IS NOW UNREACHABLE THROUGH THE SAVE PATH, and it is kept for the callers that are not
    the save path. write_plan_ahead validates an incoming step_id against this recipe's is_heading=0
    rows, so it stores a heading's id and an unknown id as NULL alike, and ON DELETE SET NULL removes
    the last way a stored pointer could go stale. What is left is a defensive answer for a row this
    function is handed directly (the plan-ahead scripts do that): a link naming a heading, or naming
    nothing here, reports no number instead of guessing one. A test pins both halves.

    ⚠️ AND ONE STATE IT USED TO REPORT WAS SIMPLY WRONG. The snippet compared the FRONT of the step, so
    rewording a step's opening broke a link nobody meant to touch and the wait went quiet."""
    def get(st, key):
        """Rows arrive as dicts, SQLAlchemy RowMappings or ORM objects depending on the caller."""
        try:
            return st[key]
        except (TypeError, KeyError, IndexError):
            return getattr(st, key, None)

    by_id, number = {}, 0
    for st in steps:
        heading = get(st, "is_heading")
        if not heading:
            number += 1
        by_id[get(st, "id")] = None if heading else number
    for w in waits:
        sid = w.get("step_id")
        w["step_no"], w["step_ok"] = None, True
        # ⚠️ THE OVERLAP POINTER IS RESOLVED THE SAME WAY AND REPORTED SEPARATELY. alongside_no is the
        # PRINTED number of the step this wait runs alongside, so "alongside step 3" means the number
        # the page shows, not a position and not an id. A pointer at a heading or at nothing resolves
        # to None and the wait simply reads without the phrase, rather than reading a wrong number.
        w["alongside_no"] = by_id.get(w.get("alongside_step_id")) if w.get("alongside_step_id") else None
        # ⚠️ AND THE ALTERNATIVE'S STEP, resolved the same way and reported separately. ext_no is the
        # PRINTED number of the step that describes the alternative, which exists only when the
        # alternative lives somewhere other than the wait's own step.
        w["ext_no"] = by_id.get(w.get("ext_step_id")) if w.get("ext_step_id") else None
        if sid is None:
            continue
        num = by_id.get(sid)
        if num is None:                        # unknown to this recipe, or it is a heading
            w["step_ok"] = False
            continue
        w["step_no"] = num
    return waits


# ---------------------------------------------------------------------------------------------
# The cook-time estimate. Round B, decision 10.
# ---------------------------------------------------------------------------------------------
# ⚠️ ONE IMPLEMENTATION, AND THE PAGE AND THE REVIEW FILE BOTH CALL IT. app.py computes the line
#    when the recipe page is drawn and scripts/round_b_cook_estimates.py writes the review CSV from
#    the same call, so a figure Andy reads in the CSV is the figure the page prints.
#
# ⚠️ IT IS COMPUTED, NEVER STORED. There is no column for it and there is no migration. A stored
#    estimate is a number nobody wrote that outlives the steps it was read from, and the first
#    time somebody edits a step the two disagree with nothing to say so.
#
# ⚠️ AND IT NEVER REACHES THE TOTAL. recipe_total reads recipe["cook_time"], which this never
#    writes, so the Total cannot pick it up by accident. The estimate is a reading of the steps and
#    the Total is a claim about the dish.

# Which recipes get no estimate at all, and why. ⚠️ A DECLARED LIST, NOT A COLUMN: these are seven
# decisions Andy made once, recorded in docs/data-repairs/round-b-decisions-2026-10-08.csv, and a
# column would make them user data that a rebuild cannot explain and that no one can read the
# reason for. tests/test_round_b_rules.py holds this list to that file, so the two cannot drift.
NO_COOK_ESTIMATE = {
    "beans": "the sibling sections are alternative methods (stovetop, pressure cooker, slow cooker)",
    "shrimp-scampi": "the whole dish happens inside one 12-minute pasta boil",
    "sunday-sauce": "step 7 restates step 4's 4 to 5 hours",
    "rigatoni-amatriciana": "\"pull the pasta 1 to 2 minutes early\" is a subtraction",
    "kachumber-tilapia": "a batch aside, and whether the figures are sequential needs a person",
    "khichdi": "the sentence runs past what the rule reads",
    "chocolate-peanut-butter-banana-smoothie":
        "the cook edited the cook time by hand, and an estimate never overrides that",
}

# ⚠️ A SENTENCE ENDS AFTER A CLOSING BRACKET TOO, AND A CLAUSE IS WHAT A DURATION IS JUDGED BY.
#    Both halves were found by reading the 14 recipes where every duration was excluded.
#    matcha-amaretti writes "(Alternatively, use a hand mixer and large bowl.) Mix on medium speed
#    until slightly frothy, 2 to 3 minutes", and with no split after the bracket the whole thing
#    read as one sentence offering an alternative method, so the mixing time went with it.
#    buttermilk-biscuits writes "Place the tray in the freezer for 15 minutes, then transfer
#    straight to the oven and bake for 15 to 17 minutes": one sentence holding a rest AND a bake,
#    and judging the sentence as a whole threw the bake away with the rest.
_SENTENCE_SPLIT = re.compile(r"(?:(?<=[.!?;])|(?<=[.!?;]\)))\s+|,?\s+then\s+|,\s+and\s+then\s+")
_SECONDS = {"sec", "secs", "second", "seconds", "s"}
# A step that runs alongside another one costs no extra time.
# ⚠️ "BAKE BOTH SHEETS AT THE SAME TIME" IS NOT TWO TASKS, IT IS TWO TRAYS IN ONE OVEN. The bare
#    phrase is gone for that reason: it took the whole estimate off four cookie recipes, including
#    the only bake time any of them stated. "Meanwhile" and "while the X cooks" are the shapes that
#    really mean a second task running inside the first one.
_PARALLEL = re.compile(r"\b(meanwhile|in the meantime|while (?:the|it|they|you|that)"
                       r"|as the\b.{0,30}\b(?:cook|bake|simmer|roast|rest|chill))\b", re.I)
# ⚠️ THE VERB IS NOT ALWAYS NEXT TO ITS OBJECT. "Let broth settle for 5 minutes", "Set the batter
#    aside for 5 minutes" and "Cover again and set for 24 hours" are all rests, and a pattern that
#    wanted "let the X settle" read all three as time on the heat.
_RESTING = re.compile(r"\b(rest|rests|resting|cool|cools|cooling|chill|chills|chilled|chilling|"
                      r"refrigerat\w*|fridge|freez\w*|frozen|marinat\w*|soak\w*|rise|rises|rising|"
                      r"proof\w*|prove|proving|ferment\w*|"
                      r"\b(?:let|leave|allow)\b[^.;]{0,30}?\b(?:set|sit|stand|rest|settle|sink|cool)\b|"
                      r"\bset\b[^.;]{0,24}?\baside\b|\bset for\b|\bsettle for\b|"
                      r"\bleave\b[^.;]{0,24}?\b(?:for|out|to|in the)\b|doubled in size|"
                      r"\brisen\b|\bdouble[sd]? in (?:size|volume)\b|"
                      r"standing|overnight|thaw\w*|defrost\w*|"
                      r"brine|brining|infuse|infusing|steep\w*|macerat\w*|sink to the bottom|"
                      r"come to room temperature)\b", re.I)
_SHELF_LIFE = re.compile(r"\b(keeps?|keeping|lasts?|stores?|storage|storing|shelf|stays? (?:fresh|good)|"
                         r"good for|best within|up to \d+ (?:day|week|month))\b", re.I)
# ⚠️ AN ALTERNATIVE METHOD IS NOT A STEP OF THIS RECIPE. "Alternatively, in an Instant Pot … 6
#    minutes" and "If kneading by hand … 7-10 minutes" are a second way to do a step already timed.
_ALT_METHOD = re.compile(r"\b(alternatively|or you (?:can|could)|if (?:you (?:are |'re )?)?"
                         r"(?:knead|mix|work|do|prefer|would rather|use|using|cook)\w*\b[^.;]{0,40}"
                         r"\b(?:by hand|instead|manually)|instant pot|multi-?cooker|pressure cooker|"
                         r"slow cooker|air fryer|microwave instead)\b", re.I)
# ⚠️ A LATER DURATION IN ONE SENTENCE IS USUALLY PART OF THE FIRST, NOT A SECOND COST.
#    "a total of around 4 minutes, 2 minutes on each side"      the 2 is inside the 4
#    "18 to 22 minutes, rotating the sheets after 12 minutes"   the 12 is inside the 22
_SUBPART = re.compile(r"\b(on each side|per side|each side|after|halfway|half way|rotating|"
                      r"turning|flipping|at a time|in between|of (?:that|which))\b", re.I)
_ADDITIVE_BEFORE = re.compile(r"\b(another|more|further|additional|then|and)\s*$", re.I)
_OR_BEFORE = re.compile(r"\bor\s*(?:until\s+)?$", re.I)
# ⚠️ "AFTER 30 MINUTES, REMOVE THE LID" IS A CLOCK READING, NOT A SECOND HALF HOUR. Measured:
#    french-baguette counted its 45-minute rise three times and pasta-with-lentils counted its 30
#    minutes twice, purely on sentences looking back at a duration the recipe already gave. It is a
#    backreference only when the SAME figure was already counted, because "After 8-9 minutes of
#    cooking, add the pasta" is the only statement of that time in pasta-alla-norcina.
_AFTER_BEFORE = re.compile(r"\bafter\s+(?:the\s+|about\s+|around\s+)?$", re.I)
# ⚠️ "EVERY 2 MINUTES" IS A CADENCE. It says how often to stir, not how long anything cooks.
_EVERY_BEFORE = re.compile(r"\b(every|each)\s*$", re.I)
# ⚠️ "EITHER … FOR 5 MINUTES OR … FOR 10" IS ONE STEP DONE TWO WAYS.
_EITHER = re.compile(r"\beither\b", re.I)
# Decision 10's three rules about what a duration MEANS.
_PER_SIDE = re.compile(r"\b(?:on each side|per side|each side)\b", re.I)
_AT_LEAST = re.compile(r"\bat least\s*$", re.I)
_SCHEDULING = re.compile(r"\bbefore you(?:'re| are)? ready to\b", re.I)
# ⚠️ A COOKING VERB GOVERNING THE DURATION BEATS THE REST TEST. "microwave for 5 minutes, until all
#    the beans are thawed" mentions thawing and is five minutes of real heat, and "bake for 15 to
#    17 minutes" in a clause that also froze the tray is a bake. The verb has to come BEFORE the
#    figure, which is what keeps "allow it to cool for 15 minutes before baking another batch"
#    excluded.
# ⚠️ A COOKING WORD IS NOT ALWAYS A COOKING VERB, AND THREE NOUNS PROVED IT. "Let the COOKIES cool
#    for at least 1 hour" matched cook\w*, "allow it to cool for 15 minutes" sat behind "the BAKING
#    sheets", and brown\w* reaches "brownies". Each one turned a cooling into time on the heat: the
#    mocha cookies read 1 hr 31 min, of which 1 hr 15 min was the cookies cooling down. The verb
#    endings are spelled out and the baking-sheet family is refused by name.
_COOKING_VERB = re.compile(
    r"\b(?:bak(?:e|es|ed|ing)\b(?!\s+(?:sheet|sheets|tray|trays|dish|dishes|pan|pans|paper|"
    r"parchment|powder|soda|rack|racks|time|times|stone|stones))|"
    r"roast(?:s|ed|ing)?|fry|frying|fried|deep-fry(?:ing)?|sear(?:s|ed|ing)?|"
    r"saut[eé](?:s|ed|ing)?|griddle(?:s|d)?|griddling|grill(?:s|ed|ing)?|broil(?:s|ed|ing)?|"
    r"boil(?:s|ed|ing)?|simmer(?:s|ed|ing)?|poach(?:es|ed|ing)?|steam(?:s|ed|ing)?|"
    r"braise(?:s|d)?|braising|stew(?:s|ed|ing)?|toast(?:s|ed|ing)?|microwave(?:s|d)?|microwaving|"
    r"caramelis(?:e|es|ed|ing)|caramefiz|carameliz(?:e|es|ed|ing)|"
    r"brown(?:s|ed|ing)?|reduce(?:s|d)?|reducing|stir-fry(?:ing)?|"
    r"cook(?:s|ed|ing)?|heat(?:s|ed|ing)?|warm(?:s|ed|ing)?|blanch(?:es|ed|ing)?|"
    r"pressure-cook(?:s|ed|ing)?)\b", re.I)


def _estimate_durations(text):
    """Every duration in a step, in minutes, with where it sits. Seconds are not a cook time."""
    out = []
    for m in _TIME_SEG_RE.finditer(text or ""):
        word = m.group("unit").lower().rstrip(".")
        if word in _SECONDS:
            continue
        unit = _UNIT_WORDS.get(word)
        if unit not in ("min", "hr"):
            continue
        lo = time_number(m.group("lo"))
        if lo is None:
            continue
        hi = time_number(m.group("hi")) if m.group("hi") else lo
        out.append({"span": (m.start(), m.end()), "lo": lo * _MIN[unit], "hi": hi * _MIN[unit],
                    "raw": m.group(0)})
    return out


def _sentences(text):
    pos, out = 0, []
    for part in _SENTENCE_SPLIT.split(text or ""):
        start = (text or "").find(part, pos)
        out.append((start, start + len(part), part))
        pos = start + len(part)
    return out


def _matches_a_wait(duration, waits, step_id):
    """Is this duration the wait the step carries, rather than a different figure in the same step?"""
    for w in waits:
        if w.get("step_id") != step_id:
            continue
        for minutes in (w.get("min_minutes"), w.get("max_minutes")):
            if minutes is None:
                continue
            if abs(duration["lo"] - minutes) < 1 or abs(duration["hi"] - minutes) < 1:
                return True
    return False


def cook_estimate(recipe, steps, waits=(), storage=(), baseline_cook_time=None):
    """What the steps say this dish costs on the heat, and why each figure was counted or not.

    Returns {"label", "lo", "hi", "open_ended", "verdict", "rows"}. `label` is "" wherever the
    page must print nothing, which is the only field the reading view uses.

    ⚠️ THE AUTHOR'S OWN COOK TIME ALWAYS WINS, and so does a cook's edit to it. A hand edit is
       detected by comparing the stored cook_time against the recipe's ORIGINAL baseline, which is
       the same evidence the "your changes" layer reads. Measured over the 300: exactly one recipe
       differs, the smoothie, whose baseline said "0 mins" and whose cook cleared it. Without that
       comparison the estimate would reappear over a deliberate deletion.
    """
    rid = recipe.get("id")
    stated = (recipe.get("cook_time") or "").strip()
    if stated:
        return {"label": "", "lo": 0, "hi": 0, "open_ended": False,
                "verdict": "the author gave a cook time", "rows": []}
    if baseline_cook_time is not None and (baseline_cook_time or "").strip() != stated:
        return {"label": "", "lo": 0, "hi": 0, "open_ended": False,
                "verdict": "the cook edited the cook time by hand", "rows": []}
    if rid in NO_COOK_ESTIMATE:
        return {"label": "", "lo": 0, "hi": 0, "open_ended": False,
                "verdict": NO_COOK_ESTIMATE[rid], "rows": []}

    wait_steps = {w.get("step_id") for w in waits if w.get("step_id")}
    wait_text = " | ".join((w.get("label") or "") + " " + (w.get("ext_label") or "")
                           for w in waits)
    store_text = " | ".join(s.get("label") or "" for s in storage)
    found, counted_figures, number = [], set(), 0
    open_ended = False
    for step in steps:
        if step.get("is_heading"):
            continue
        number += 1
        text = step.get("text") or ""
        every = _estimate_durations(text)
        for s0, s1, sentence in _sentences(text):
            here = [d for d in every if s0 <= d["span"][0] < s1]
            says_total = bool(re.search(r"\btotal of\b", sentence, re.I))
            for k, d in enumerate(here):
                before = text[max(0, d["span"][0] - 28):d["span"][0]]
                clause_before = sentence[:max(0, d["span"][0] - s0)]
                cooking = bool(_COOKING_VERB.search(clause_before))
                why = None
                # ⚠️ THE WAIT'S OWN FIGURE IS EXCLUDED, NOT EVERY FIGURE IN ITS STEP. blueberry
                #    -muffin-sugar-cookies browns butter for 3 to 4 minutes and then cools it for
                #    30, both in step 1, and the step carrying the cooling wait took the browning
                #    with it. The comparison is against the wait's own minutes, because a wait's
                #    label is often a rewording of the step's words.
                if (step.get("id") in wait_steps and not cooking
                        and _matches_a_wait(d, waits, step.get("id"))):
                    # ⚠️ AND NOT WHERE A COOKING VERB GOVERNS IT. The wait is matched by its
                    #    MINUTES, so "Simmer for 30 minutes, then chill for 30 minutes" against a
                    #    30-minute chill lost the simmer as well as the chill.
                    why = "the duration is the plan-ahead wait this step carries"
                elif d["raw"].strip() and d["raw"].strip() in wait_text:
                    why = "the duration is already stored as a wait"
                elif d["raw"].strip() and d["raw"].strip() in store_text:
                    why = "the duration is already stored as a Keeps entry"
                elif _SCHEDULING.search(sentence):
                    why = "the sentence is scheduling, not time on the heat"
                elif _SHELF_LIFE.search(sentence) and not cooking:
                    # ⚠️ "KEEP ON A LOW SIMMER" IS NOT A SHELF LIFE, and the cooking-verb override
                    #    was wired to the rest test alone. _SHELF_LIFE opens on "keeps?|keeping",
                    #    so "Cover and keep on a low simmer for 20 minutes" lost 20 minutes of heat.
                    why = "the sentence states a shelf life"
                elif _ALT_METHOD.search(sentence):
                    why = "the sentence gives an alternative method for a step already timed"
                elif _PARALLEL.search(sentence):
                    why = "the step runs alongside another one"
                elif _RESTING.search(sentence) and not cooking:
                    why = "the sentence is a rest, not time on the heat"
                elif _EVERY_BEFORE.search(before):
                    why = "the figure is how often to stir, not how long anything cooks"
                elif _AFTER_BEFORE.search(before) and (d["lo"], d["hi"]) in counted_figures:
                    why = "the sentence looks back at a duration this recipe already counted"
                elif k and _EITHER.search(sentence):
                    why = "one of two ways to do the step, and the first is already counted"
                elif k and _OR_BEFORE.search(before):
                    why = "an alternative to the duration already counted in this sentence"
                elif k and says_total:
                    why = "the sentence gives a total, and this is part of it"
                elif k and _SUBPART.search(sentence) and not _ADDITIVE_BEFORE.search(before):
                    why = "a part of the duration already counted in this sentence"
                lo, hi = d["lo"], d["hi"]
                note = ""
                if why is None:
                    # Decision 10. "N per side" is paid twice, and "at least N" has no ceiling.
                    # ⚠️ AND ONLY WHERE THE CLAUSE STATES ONE DURATION. "a total of around 4
                    #    minutes, 2 minutes on each side" states the total and then breaks it
                    #    down, so the 2 is correctly excluded as part of the 4 and the 4 was then
                    #    DOUBLED, printing 8 minutes for a 4-minute sear. The same shape as
                    #    _SUBPART's own comment, read from the other end.
                    if _PER_SIDE.search(sentence) and len(here) == 1:
                        lo, hi, note = lo * 2, hi * 2, "counted twice, the sentence says per side"
                    if _AT_LEAST.search(before):
                        open_ended, note = True, "open-ended, the sentence says at least"
                    counted_figures.add((d["lo"], d["hi"]))
                found.append({"step": number, "step_id": step.get("id"), "raw": d["raw"],
                              "lo": lo, "hi": hi, "used": why is None,
                              "why": why or (note or "counted"),
                              "sentence": sentence.strip()[:170]})
    used = [f for f in found if f["used"]]
    if not found:
        return {"label": "", "lo": 0, "hi": 0, "open_ended": False,
                "verdict": "no stated time in any step", "rows": found}
    if not used:
        return {"label": "", "lo": 0, "hi": 0, "open_ended": False,
                "verdict": "every duration excluded", "rows": found}
    if any(f["why"] == "the step runs alongside another one" for f in found):
        return {"label": "", "lo": 0, "hi": 0, "open_ended": False,
                "verdict": "no estimate, the steps overlap", "rows": found}
    lo = int(sum(f["lo"] for f in used))
    hi = int(sum(f["hi"] for f in used))
    # ⚠️ "~" AND NOTHING ELSE. Andy's call: the line reads "Cook ~30 min – 35 min", with the app's
    #    own duration spelling after the tilde. No "about", no "from the steps".
    if open_ended:
        label = f"~{fmt_minutes(lo)}+"
    elif hi == lo:
        label = f"~{fmt_minutes(lo)}"
    else:
        label = f"~{fmt_minutes(lo)} – {fmt_minutes(hi)}"
    return {"label": label, "lo": lo, "hi": hi, "open_ended": open_ended,
            "verdict": "estimate", "rows": found}
