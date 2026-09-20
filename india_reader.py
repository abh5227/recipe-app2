#!/usr/bin/env python3
"""india_reader.py - read the Indian recipe dataset. One source, one format, no judgements.

⚠️ THE SLUG IS 'india' AND IT IS NOT FREE TO CHANGE. library_aliases already carries two rows
scoped to it, 'corn flour' and 'cornflour' -> cornstarch, written by migration 047. A different
slug here would leave those aliases inert and 'corn flour' would reach nothing, which is a silent
miss rather than an error.

⚠️ THE DATASET SHIPS TWO INGREDIENT COLUMNS AND NEITHER IS SUFFICIENT ALONE. Measured over all
70,227 lines against the built catalog:

    Cleaned-Ingredients, as-is                     78.8%
    TranslatedIngredients, as-is                   63.1%   ⚠️ 15.7 points WORSE
    TranslatedIngredients, prep-note tail stripped 80.4%
    cleaned first, raw entry as a fallback         80.7%   ✅ what this module does

The last row is variant A. It reads the cleaned name, and only when that name fails to resolve does
it fall back to the raw entry the cleaned name came from. The wholesale switch to the raw column
was measured and rejected, not assumed.

⚠️ THE CLEANED COLUMN IS LOSSY IN A SPECIFIC, MEASURED WAY. Its author removed a stopword list as
bare SUBSTRINGS rather than as whole words, so 'boneless' became 'bless', 'stone' became 'st',
'mascarpone' became 'mascarp' and 'honey' became 'hy' before being dropped entirely. Honey is named
in 321 recipes and survives in 1. The raw column has none of that damage, which is why the fallback
is worth its cost.

⚠️ THE FALLBACK IS FALLBACK-ONLY AND THAT IS THE WHOLE DESIGN. Reading the raw column first loses
15.7 points, because the raw entries carry quantities, prep notes and alternatives the cleaned
column has already removed. Each column repairs the other's failure and neither wins outright.
"""
import csv, re, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import mining_probe as MP

csv.field_size_limit(10_000_000)

SLUG = "india"

# ⚠️ THE HYPHEN IS OVERLOADED IN THIS SOURCE and the split keeps the head. Measured over all
#    31,382 raw entries that contain one: 30,695 have a tail that names no ingredient at all
#    ('Tamarind - lemon sized', 'Water - to knead the dough'), 510 have prep text that resolves
#    anyway and would be WRONG ('Ginger - paste' -> food paste), 32 are an alternative, and 62
#    carry a genuine second ingredient. Keeping the head is right 97.8% of the time and the 62
#    were read one at a time before this line was written.
HYPHEN = re.compile(r"\s+[-–]\s+")
WORD = re.compile(r"[a-z0-9]+")

# ⚠️ 'RECIPE' IS PART OF THIS DATASET'S TITLE STYLE, NOT PART OF ANY DISH NAME, AND THE DISH ID
#    IS DERIVED FROM THE NAME. dish_facets.dish_id is sha256 of the reduced string, so
#
#        dish_id('khichdi')        = 7eccf12992f5ff5e   the id RecipeNLG and Wikibooks already use
#        dish_id('khichdi recipe') = e64707ada1d03887   a different dish entirely
#
#    Mined unstripped, India's dishes land in their own id space and combine with nothing. Every
#    elevation reads zero and no error is raised anywhere, which is why this is stripped here and
#    not left to be noticed later.
#
#    ⚠️ IT LIVES IN THE READER BECAUSE IT IS A FACT ABOUT THIS FILE. Putting it in dish_facets
#    would apply an India-specific rule to every source, and RecipeNLG has titles where the word
#    is load-bearing.
#
#    Measured over all 5,938 titles before this was written: 6,369 occurrences across 5,904
#    titles, 3,517 trailing, 2,585 mid-title, 260 inside parentheses, 7 leading. ⚠️ ZERO titles
#    are left empty by the strip, which is the check that mattered.
RECIPE_WORD = re.compile(r"\brecipes?\b", re.I)
_TIDY = re.compile(r"\s+")


def strip_recipe(title):
    """The title with the dataset's 'Recipe' label removed. Never returns an empty string when
    the input had any other word in it."""
    out = _TIDY.sub(" ", RECIPE_WORD.sub(" ", title or "")).strip()
    out = out.strip(" -–()").strip()
    return out or (title or "").strip()

# The share of a cleaned name's words that must appear in a raw entry before that entry is
# accepted as the one it came from. Below this the match is a guess.
OVERLAP_FLOOR = 0.6


class Recipe:
    """One row, read. Nothing here is a judgement about food."""

    __slots__ = ("title", "cleaned", "raw", "cuisine")

    def __init__(self, title, cleaned, raw, cuisine):
        self.title = title
        self.cleaned = cleaned          # the dataset's own cleaned ingredient names
        self.raw = raw                  # the source entries, prep-note tails already cut
        self.cuisine = cuisine

    @property
    def usable(self):
        """⚠️ THE ONLY DEFINITION OF `A RECIPE` THIS MODULE OFFERS, and it is deliberately thin:
        a row that names at least one ingredient. Row count is not recipe count and neither is
        the count that survives dish reduction."""
        return bool(self.cleaned)

    def origin(self, cleaned_name):
        """The raw entry a cleaned name most likely came from, or None when nothing overlaps
        it enough to be sure. Word overlap, not position: the cleaned column reorders."""
        ct = set(WORD.findall(cleaned_name.lower()))
        if not ct:
            return None
        best, score = None, 0.0
        for entry in self.raw:
            et = set(WORD.findall(entry.lower()))
            if not et:
                continue
            s = len(ct & et) / len(ct)
            if s > score:
                score, best = s, entry
        return best if score >= OVERLAP_FLOOR else None

    def ingredient_lines(self, resolves=None):
        """Variant A. The cleaned name, or the raw entry it came from when the cleaned name
        resolves to nothing.

        ⚠️ `resolves` IS THE CALLER'S MATCHER AND THIS MODULE HAS NO OPINION ABOUT FOOD. Without
        it the reader yields the cleaned column unchanged, which is the 78.8% baseline. The
        fallback cannot be decided here because whether a name resolves is a fact about the
        catalog, and the catalog belongs to the caller."""
        for name in self.cleaned:
            if resolves is None or resolves(name):
                yield name
                continue
            origin = self.origin(name)
            yield origin if origin else name


def read(path, limit=10**9):
    """Yield a Recipe per row. The instructions column is never read.

    ⚠️ TranslatedInstructions IS DELIBERATELY NOT YIELDED. India is registered derive_only, which
    means its counts may be kept and its text may not. The column is the one place this dataset
    escaped its own cleaner, so it is tempting and it stays shut."""
    with open(path, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            if i >= limit:
                return
            cleaned = [c.strip() for c in (row.get("Cleaned-Ingredients") or "").split(",") if c.strip()]
            raw = [HYPHEN.split(t.strip())[0].strip()
                   for t in (row.get("TranslatedIngredients") or "").split(",") if t.strip()]
            yield Recipe(title=strip_recipe(row.get("TranslatedRecipeName") or ""),
                         cleaned=cleaned,
                         raw=[r for r in raw if r],
                         cuisine=(row.get("Cuisine") or "").strip())


def lines(path, limit=10**9, resolves=None):
    """Ingredient lines with MP.SENTINEL between recipes, the shape the mining runs consume."""
    for rec in read(path, limit):
        for name in rec.ingredient_lines(resolves):
            yield name
        yield MP.SENTINEL


def records(path, limit=10**9, resolves=None):
    """(title, [ingredient names]) pairs, the shape dish_facet_run consumes."""
    for rec in read(path, limit):
        yield rec.title, list(rec.ingredient_lines(resolves))


def titles(path, limit=10**9):
    for rec in read(path, limit):
        yield rec.title


# ⚠️ THE CUISINE COLUMN CARRIES THE SAME TITLE STYLE AND A BOM. Measured over all 5,938 rows:
#    82 distinct values, of which 'north indian recipes' 763, 'south indian recipes' 558 and
#    'kerala recipes' 133 all end in the label, and 'gujarati recipes﻿' carries a zero-width
#    no-break space that makes it a different string from 'gujarati recipes'. Left alone the
#    facet would hold three spellings of one cuisine and none of them would match Wikibooks'.
_ZERO_WIDTH = re.compile(r"[\ufeff\u200b\u200c\u200d]")


def clean_cuisine(value):
    """A cuisine value with the dataset's label and invisible characters removed, lowercased."""
    v = _ZERO_WIDTH.sub("", value or "")
    v = _TIDY.sub(" ", RECIPE_WORD.sub(" ", v)).strip().strip(" -–()").lower()
    return v


def cuisines(path, limit=10**9):
    """(title, cuisine) for the facet pass. Empty cuisines are skipped rather than emitted."""
    for rec in read(path, limit):
        v = clean_cuisine(rec.cuisine)
        if v:
            yield rec.title, v


def assertions(path, limit=10**9):
    """(title, facet, value) for what this source STATES about a recipe.

    ⚠️ ONE FACET, AND IT IS THE REASON THIS SOURCE WAS TAKEN. Every other facet in the mined
    schema is inferred from a title, so `baked` is in the title and n counts the evidence. The
    Cuisine column is an editor's claim, present on all 5,938 rows, and a stated `Chettinad` or
    `Awadhi` is a fact no title inference can reach. 34 of the 82 values are sub-national.
    """
    for title, v in cuisines(path, limit):
        yield title, "cuisine", v


MP.register_reader("india", lines=lines, records=records, titles=titles, slug=SLUG,
                   needs_resolver=True, assertions=assertions)
