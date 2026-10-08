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


def classify(name, brands=None, known_word=None, is_catalog_name=None):
    """Return (verdict, detail). verdict is 'brand', 'suspect' or 'clear'.

    known_word is accepted and unused. It is kept in the signature because the obvious wide
    heuristic wants it, and the comment above records why that heuristic is not here.

    is_catalog_name(name) -> bool says whether the library already holds this exact canonical.
    Pass it and the library wins, which is what the rule below is about.
    """
    b = BRANDS if brands is None else brands
    n = _norm(name)
    if not n:
        return "clear", ""
    if n in b:
        return "brand", b[n]
    # ⚠️ THE LIBRARY DECIDES WHAT IS FOOD. An interior word span used to be enough to call a name
    #    a brand, and that cut three real catalog rows. "Tabasco pepper" is Capsicum frutescens,
    #    the variety, where the mark covers the sauce. "Castagna del Monte Amiata PGI" and
    #    "Pecorino del Monte Poro" are a chestnut and a cheese, and "del Monte" is Italian for
    #    "of the mountain", not the canner. A row the library already carries as a canonical is
    #    food, unless its EXACT form is on the list. Measured: this clears exactly those three,
    #    no listed surface form is itself a catalog canonical, so nothing real is let through.
    if is_catalog_name is not None and is_catalog_name(name):
        return "clear", "the library carries this as a canonical"
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


# ⚠️ THE ONE NAME THAT IS BOTH A LISTED MARK AND A CATALOG CANONICAL, DECLARED RATHER THAN
#    DISCOVERED. The library-wins rule above clears a canonical whose name merely CONTAINS a mark.
#    It cannot clear one whose name IS a mark, because the exact-form check runs first and has to:
#    "velveeta" is a listed mark and a canonical would not make it a cheese variety.
#
#    Andy's call, 2026-10-07: Miracle Whip STAYS its own ingredient. It is a dressing, not mayonnaise,
#    and the two are not interchangeable in a recipe. Both halves of that ruling are what the code
#    already does, which is why nothing here changed to honour it:
#      * it stays a library_names canonical. Nothing in this module deletes a row. The verdict is
#        read by substitution_run.py, and by nothing that owns the library.
#      * it is never offered as a substitute. is_brand -> True drops any substitution pair naming
#        either side, so "Miracle Whip <-> mayonnaise" can never be mined. That is the ruling.
#
#    Measured over live, read only, 2026-10-07: 104 surface forms against 10,020 canonicals, and
#    this is the ONLY intersection. The enforcement test asserted the intersection was EMPTY, which
#    is stricter than the rule its own name states ("unless its exact form is listed") and was true
#    only until the catalog grew a row for a mark. It compares against this set now, so a NEW
#    collision still fails and this one does not.
DELIBERATE_BRAND_CANONICALS = {
    "miracle whip": "a dressing in its own right, not interchangeable with mayonnaise. Andy's call, "
                    "2026-10-07. It keeps its library row and is never offered as a substitute.",
}


def is_brand(name, brands=None, is_catalog_name=None):
    """The one question the enforcement test asks. Only a listed mark answers yes."""
    return classify(name, brands, is_catalog_name=is_catalog_name)[0] == "brand"


def is_declared_brand_canonical(name):
    """Is this name a mark the library deliberately carries as a canonical? -> bool.

    Normalized on both sides, the way every other lookup in this module is, so "Miracle Whip",
    "miracle whip" and "Miracle-Whip" are one answer.
    """
    return _norm(name) in DELIBERATE_BRAND_CANONICALS


def catalog_name_check(conn):
    """Build is_catalog_name from a live connection. One query, then a set lookup."""
    names = {_norm(r[0]) for r in conn.execute("SELECT canonical FROM library_names")}
    return lambda s: _norm(s) in names
