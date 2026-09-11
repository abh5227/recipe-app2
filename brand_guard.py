#!/usr/bin/env python3
"""brand_guard.py - boundary (g) of docs/mining-decision.md.

A brand name is never stored as a generic ingredient or a generic dish type.

⚠️ THE LIST IS THE AUTHORITY AND THE HEURISTIC NEVER EXCLUDES. what-the-library-is-for.md says
the default is keep, and a name that merely LOOKS like a brand is a real food until somebody
says otherwise. So there are three answers and only the first one blocks:

    BRAND    the name is on brands.csv. Excluded from mined facts.
    SUSPECT  it looks like a mark and is not on the list. FLAGGED for review, NOT excluded.
    CLEAR    it passes as an ordinary name.

⚠️ A BRAND IS NEVER MAPPED TO ITS GENERIC EITHER. brands.csv carries a generic_equivalent column
and it is reference for a human reading the file. Nothing reads it into a fact. Cool Whip and
whipped cream are not the same claim about what a cook used, and boundary (g) says so.

⚠️ TWO NAMES THE PROBE CALLED BRANDS ARE NOT ON THIS LIST, ON PURPOSE. `oleo` is short for
oleomargarine, which is a generic term for margarine and not anybody's mark. `graham cracker` is
a generic food named after Sylvester Graham, and the mark in that aisle is Honey Maid. Between
them they were 9,016 of the 30,114 occurrences the probe's heuristic flagged, 29.9% of it. Both
belong on the alias and catalog-gap lists instead. Blocking them would have cut two real foods,
which is the exact failure the default-is-keep rule exists to prevent.
"""
import csv, re
from pathlib import Path

BASE = Path(__file__).resolve().parent
BRANDS_CSV = BASE / "brands.csv"


def _norm(s):
    s = (s or "").lower().strip()
    s = s.replace("'", " ").replace("-", " ").replace(".", " ")
    return re.sub(r"\s+", " ", s)


def load_brands(path=BRANDS_CSV):
    """surface form -> mark. Normalized on both sides."""
    out = {}
    if not Path(path).exists():
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sf = _norm(r["surface_form"])
            if sf:
                out[sf] = r["mark"]
    return out


BRANDS = load_brands()

# ── the flagging heuristic. It NEVER excludes, and it is deliberately NARROW. ───────────────
# ⚠️ A WIDE HEURISTIC WAS TRIED AND MEASURED AND IS NOT HERE. "no word in this name is one the
#    catalog uses" sounds like a brand detector and is really a catalog-gap detector. Over the
#    top 600 unmatched names it flagged 81, and the top of that queue was pecans, hamburger,
#    pimento, cherries, mayo, pretzels and crabmeat. Every one a real food the catalog lacks.
#    A review queue that is mostly wrong gets ignored, and then the one real mark in it is missed
#    too. That signal is worth having under its own name, which is what the CATALOG GAP list in
#    the probe output already is. It is not this.
POSSESSIVE = re.compile(r"\b[a-z]{3,}\s+s\b")        # NER strips apostrophes: "campbell s"
TRADE_WORDS = {"brand"}                               # "style" flagged `cream style corn`


def classify(name, brands=None, known_word=None):
    """Return (verdict, detail). verdict is 'brand', 'suspect' or 'clear'.

    known_word is accepted and unused. It is kept in the signature because the obvious wide
    heuristic wants it, and the comment above records why that heuristic is not here.
    """
    b = BRANDS if brands is None else brands
    n = _norm(name)
    if not n:
        return "clear", ""
    if n in b:
        return "brand", b[n]
    # a mark inside a longer name: "velveeta cheese" when the list holds "velveeta"
    words = n.split()
    for size in range(len(words), 0, -1):
        for i in range(len(words) - size + 1):
            span = " ".join(words[i:i + size])
            if span in b:
                return "brand", b[span]
    if POSSESSIVE.search(n):
        return "suspect", "possessive shape, a mark is usually somebody's name"
    if any(w in TRADE_WORDS for w in words):
        return "suspect", "carries a trade word"
    return "clear", ""


def is_brand(name, brands=None):
    """The one question the enforcement test asks. Only a listed mark answers yes."""
    return classify(name, brands)[0] == "brand"
