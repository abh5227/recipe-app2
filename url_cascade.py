"""URL import, stage 2 (U2): run the readers in order until one produces a usable recipe.

CASCADE, NOT MERGE. A layer either produces a usable result or it fails and the next one runs from
scratch. Gaps are never filled from a second source — that yields a recipe assembled from three
places with no coherent provenance, where nobody can say which part came from where. One layer
answers, or it doesn't.

PURE — no network, no DB. The HTML arrives already fetched (url_fetch), and every layer is a pure
function of (url, html).

THERE IS CURRENTLY ONE LAYER, and that is expected. This module exists for the SHAPE — the interface
U3 (microdata) and U6 (heuristics) slot into without rework, the ordering, and the composition of
refusals. Layer 3 of the original sketch (recipe-scrapers) is deliberately absent: measured against
this corpus it read exactly the same 10 pages as the stdlib layers for 39MB and 20 dependencies, and
it flattens HowToSections that our own reader marks.

PROVENANCE RIDES ALONGSIDE THE 17-KEY DICT, NEVER INSIDE IT. The normalized dict is the
reader->cleanup contract, and provenance answers HOW WE KNOW rather than WHAT WE KNOW; an 18th key
would touch every fixture that builds one and force clean_recipe to carry a field it has no use for.
It is persisted instead as a recipe-level import_flags row — see provenance_flag_row.
"""
from typing import NamedTuple

import url_jsonld


class Read(NamedTuple):
    """A layer produced a usable recipe."""
    normalized: dict            # the 17-key dict, untouched
    provenance: dict            # {"layer": <stable id>} — how it was read


class Refusal(NamedTuple):
    """One layer declined, and why. Composed into a message when every layer declines."""
    layer: str
    code: str                   # NO_STRUCTURED_DATA | NOT_A_RECIPE | INCOMPLETE
    detail: str                 # a short phrase, already worded to follow "<layer>: "


class Failed(NamedTuple):
    """No layer produced a recipe. Carries every refusal in order, plus the composed message."""
    refusals: tuple
    message: str


# --------------------------------------------------------------------------- #
# Message composition
# --------------------------------------------------------------------------- #
def and_list(items, limit=2):
    """'Article and ImageObject'. Capped because a page's @graph routinely carries five types and
    naming all of them buries the one that matters; the full tuple stays on the reader's refusal."""
    items = list(items)[:limit]
    if len(items) < 2:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _jsonld_phrase(refused):
    """url_jsonld's refusal -> a phrase that reads correctly after 'json-ld: '.

    The taxonomy is kept rather than flattened. A page carrying two ld+json blocks that describe an
    Article has NOT got 'no structured data' — saying so would be false, and 'found Article and
    ImageObject, not Recipe' tells the user something they can act on (this is a blog post, or the
    recipe is in the body text) instead of something they can't.
    """
    if refused.code == "NOT_A_RECIPE" and refused.context:
        return f"found {and_list(refused.context)}, not Recipe"
    if refused.code == "NO_STRUCTURED_DATA":
        return "no JSON-LD on the page"
    if refused.code == "INCOMPLETE" and refused.context:
        return f"a Recipe with no {and_list(refused.context, limit=3)}"
    return refused.detail


# --------------------------------------------------------------------------- #
# The layers
# --------------------------------------------------------------------------- #
def jsonld_layer(url, html):
    """Adapt url_jsonld to the layer interface: (url, html) -> Read | Refusal.

    url_jsonld needed NO change for this. The adapter exists because provenance is attached HERE by
    design — a reader returns the normalized dict and nothing else, and the cascade is what knows
    which reader ran. U3 and U6 will be wrapped the same way.
    """
    got = url_jsonld.read(html, url)
    if isinstance(got, url_jsonld.Refused):
        return Refusal("json-ld", got.code, _jsonld_phrase(got))
    return Read(got, {"layer": "json-ld"})


LAYERS = (jsonld_layer,)        # ORDER IS THE POLICY: cheapest and most authoritative first.


# --------------------------------------------------------------------------- #
# The cascade
# --------------------------------------------------------------------------- #
def read(url, html, layers=LAYERS):
    """Run layers in order; return the FIRST Read, or Failed carrying every refusal.

    Short-circuits: once a layer produces a recipe the rest are never called, so a later, weaker
    layer can never overwrite or 'improve' a better one's answer.
    """
    refusals = []
    for layer in layers:
        got = layer(url, html)
        if isinstance(got, Read):
            return got
        refusals.append(got)
    return Failed(tuple(refusals), compose(refusals))


def compose(refusals):
    """Every refusal, in the order the layers ran, one per line:

        json-ld: found Article and ImageObject, not Recipe

    The user learns WHICH layers were tried and what each one saw — not a flat 'nothing worked',
    which tells them nothing about whether to retry, paste a different URL, or type it in.
    """
    if not refusals:
        return "no reader was tried"
    return "\n".join(f"{r.layer}: {r.detail}" for r in refusals)


# --------------------------------------------------------------------------- #
# Provenance persistence
# --------------------------------------------------------------------------- #
def provenance_flag_row(provenance):
    """A Read's provenance -> the recipe-level import_flags row that records how it was read.

    position=None is the existing recipe-level convention (import_write._line_flag_rows carries a
    line's position; recipe-level flags carry None, and backfill_headings joins on the pair). The row
    shape matches what commit_plan already inserts, so U5's write path can append it to
    plan['review_flags'] with no schema change and no new insert.

    ⚠️ This is the first recipe-level flag to USE the reason column — the existing ones
    (no_directions, no_ingredients, photo_only) leave it NULL, and a W1 characterisation test pins
    that for the Paprika path. That test stays true: Paprika plans never carry this row. But the
    invariant is now 'recipe-level REVIEW flags carry no reason', not 'recipe-level flags carry no
    reason', which is worth knowing before U5 wires this in.
    """
    return {"position": None, "flag": "imported_via", "reason": provenance["layer"]}
