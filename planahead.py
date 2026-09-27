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

from import_cleanup import _TIME_SEG_RE, _TIME_UNITS   # THE shared segment reader

# minutes per unit the segment reader may return, plus the two it does not carry
_MIN = {"min": 1, "hr": 60, "day": 1440, "week": 10080}
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
WHENS = ("always", "optional", "only_if")


def counts(w):
    """Does this wait reach the total? Only an unconditional one does.

    ⚠️ AN OPTIONAL SOAK IS NOT TIME A COOK HAS TO SET ASIDE. coconut-curried-golden-lentils soaks
    the lentils if there is time, and no-knead-bread rests the dough 45 to 60 minutes only when it
    went to the refrigerator. Summing either would tell a cook to block out hours for something the
    recipe already said they could skip. Both still show in the breakdown with their qualifier,
    because a wait a cook MIGHT take is worth reading before starting.
    """
    return (w.get("when_kind") or "always") == "always"


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
    m = _TIME_SEG_RE.search(s)
    unit = _UNIT_WORDS.get(m.group("unit").lower()) if m else None
    if m and unit:
        lo = float(m.group("lo")) * _MIN[unit]
        hi = float(m.group("hi")) * _MIN[unit] if m.group("hi") else lo
        # ⚠️ A SECOND SEGMENT MEANS ONE OF TWO THINGS AND THE SEPARATOR SETTLES IT.
        #    "10 min to 1 hr" is a RANGE ACROSS UNITS, which _TIME_SEG_RE cannot see because its
        #    `hi` group only catches a bare number. Read as a continuation it gave (10, 10), which
        #    silently halves a real marinade. "1 hr 30 min" is ADDITIVE and has no separator.
        rest = s[m.end():]
        sep = _RANGE_SEP.match(rest)
        m2 = _TIME_SEG_RE.match(rest[sep.end():] if sep else rest.lstrip(" ,"))
        u2 = _UNIT_WORDS.get(m2.group("unit").lower()) if m2 else None
        # ⚠️ THE HIGH END CAN BE A WORD. "6 hr – overnight" is 3 of the proposals, and without this
        #    it read as a flat 6 hours, dropping the half of the range the cook plans around.
        if sep and not m2 and not m.group("hi"):
            for pat, wlo, _whi in _WORD_DURATIONS:
                if pat.match(rest[sep.end():]):
                    return int(lo), wlo
        if m2 and u2 and not m.group("hi"):
            other = float(m2.group("lo")) * _MIN[u2]
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
            hi = float(m3.group("lo")) * _MIN[u3] if (m3 and u3) else None
        # ⚠️ "up to X" IS A CEILING AND WAS BEING READ AS A FLOOR. "up to 1 week" returned
        #    (10080, 10080), which says a week is required where the recipe says a week is the most.
        #    Measured on the v2 proposals: 22 rows carry this shape. All 22 are storage today, which
        #    reaches no total, so nothing shipped wrong, and the first wait that says "chill up to
        #    2 hours" would have told a cook to set aside 2 hours for it. The floor is 0, not null,
        #    because a null min already means the reader could not parse the text at all.
        elif hi is not None and nf:
            lo = 0
        return int(lo), (None if hi is None else int(hi))
    for pat, lo, hi in _WORD_DURATIONS:
        if pat.search(s):
            return lo, hi
    return None, None


# ⚠️ "at least" AND A TRAILING "+" BOTH MEAN NO CEILING. 45 of the 72 proposals are open-ended and
#    most of them say it in words rather than by leaving the range off.
_RANGE_SEP = re.compile(r"\s*(?:to|[-\u2013\u2014])\s*", re.I)
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
        return counted[0].get("label") or ""
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

    `steps` is the recipe's rows in position order, each a mapping with position, is_heading, text.
    Adds two keys to every wait, in place:
      step_no  - the number the page prints ("Step 4"), heading-EXCLUDED to match the CSS counter,
                 or None when there is no usable link
      step_ok  - False ONLY when a pointer exists and the check failed, so the editor can say so

    ⚠️ THE NUMBER IS NOT THE POSITION. Headings sit in the same table and carry positions but are
    not numbered, so position 4 can print as Step 3.
    """
    def get(st, key):
        """Rows arrive as dicts, SQLAlchemy RowMappings or ORM objects depending on the caller."""
        try:
            return st[key]
        except (TypeError, KeyError, IndexError):
            return getattr(st, key, None)

    by_pos, number = {}, 0
    for st in steps:
        pos, heading, text = get(st, "position"), get(st, "is_heading"), get(st, "text")
        if not heading:
            number += 1
        by_pos[pos] = (None if heading else number, text)
    for w in waits:
        pos = w.get("step_position")
        w["step_no"], w["step_ok"] = None, True
        if pos is None or pos not in by_pos:
            if pos is not None:
                w["step_ok"] = False          # the step it pointed at is gone
            continue
        num, text = by_pos[pos]
        if num is None:                        # it now points at a heading
            w["step_ok"] = False
            continue
        if step_ok(text, w.get("step_check")):
            w["step_no"] = num
        else:
            w["step_ok"] = False
    return waits
