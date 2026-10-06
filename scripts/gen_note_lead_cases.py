#!/usr/bin/env python3.13
"""Regenerate tests/fixtures/note-lead-cases.json, the shared LEAD fixture.

⚠️ THE TABLE WAS SHARED AND THE PATTERN THAT READS THE LABEL WAS NOT, TWICE. note-kinds.json is
read by both sides and a test already asserts that. The pattern in front of it, which decides what
counts as a label at all, is hand-written in `import_cleanup._NOTE_LEAD` and again in
`static/note-blocks.js` LEAD, and the pair has now drifted twice: first on the separator set (a
"Tip - ..." note printed under the wrong header), then on the letter class, where both sides read
ASCII only and "Café: use a dark roast" could not be a label in either language.

tests/js/note-kinds-sync.test.js cannot catch this class on its own. It compares the KIND each side
answers, and an unlisted label answers "no kind" on both sides whether the pattern matched or not.
So the label and the body are recorded here, per case, and both suites assert them.

⚠️ THIS SCRIPT OPENS NO DATABASE. The cases are written out below rather than mined from the corpus
on purpose: the corpus carries no accented, Greek or Cyrillic label today, so a fixture generated
from it would prove nothing about the very characters this exists for.

    python3.13 scripts/gen_note_lead_cases.py
"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import import_cleanup as ic                                                   # noqa: E402

OUT = REPO / "tests" / "fixtures" / "note-lead-cases.json"

TEXTS = [
    # the five separators, the shapes the corpus really carries
    "Tip: a wetter dough gives a chewier crumb and a more open texture.",
    "Flour. This recipe works best with a high protein bread flour.",
    "Leftovers – best to pan fry them fresh so they stay crisp.",
    "Variation — for pita pockets, roll them a little thinner.",
    "Freezing - wrap each one twice before it goes in the freezer.",
    # apostrophes, slashes and hyphens inside a label
    "Baker's percentage: the flour is always 100 and the rest is read against it.",
    "Baker’s percentage: the flour is always 100 and the rest is read against it.",
    "Make-ahead: the dough keeps for two days in the fridge.",
    "Oven/stovetop: either works, the oven is just steadier.",
    # accented Latin, which the ASCII class could never read
    "Café: use a dark roast, it stands up to the milk.",
    "Crème fraîche: stir it in off the heat so it does not split.",
    "Jalapeño – take the seeds out if you want it milder.",
    "Æbleskiver: turn them with a knitting needle, not a fork.",
    # a label the look-alike repair leaves alone, in Greek and in Cyrillic
    "Ρίγανη: the Greek kind is dried on the stalk.",
    "Борщ: serve it with a spoon of sour cream and dill.",
    # DECOMPOSED, the case \p{L} and [^\W\d_] would have disagreed on
    "Café: use a dark roast, it stands up to the milk.",
    # the Nl and No numerals [^\W\d_] admits and \p{L} does not
    "Ⅷ: the eighth batch was the one that worked.",
    "²: squared, which is how the tin is measured here.",
    # shapes that must NOT read as a label
    "500g: that is the flour, not the total.",
    "_private: an underscore is not a letter.",
    "Serve with rice - or with bread.",
    "Tip:no space after the colon.",
    "A label this long is not a heading any more because it runs past the limit: and then a body.",
    "No separator at all so this is simply a sentence about flour",
]

WHAT = ("The shared LEAD pattern, case by case. import_cleanup._NOTE_LEAD and "
        "static/note-blocks.js LEAD read a label off the front of a note's paragraph, and the two "
        "are hand-written mirrors. Each case records the label and the body the pattern must "
        "produce, or null when it must not match at all. Regenerate with "
        "scripts/gen_note_lead_cases.py.")


def build():
    cases = []
    for t in TEXTS:
        m = ic._NOTE_LEAD.match(t)
        cases.append({"text": t,
                      "label": m.group(1) if m else None,
                      "body": m.group(2) if m else None})
    return {"what": WHAT, "cases": cases}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(REPO)} with {len(TEXTS)} cases")
