"""snapshot_serialize.py — the SINGLE SOURCE of the recipe-content snapshot FORMAT (change-tracking).
Pure + dependency-light (json only): given a recipe's content (recipe fields + ingredient rows + step
rows) it returns the STABLE JSON blob that recipe_snapshots.content stores.

ONE format, reused by BOTH the ORM/serve path (app.serialize_recipe_content) AND the raw-SQL import
writer (import_write.commit_plan) — so an import-origin ORIGINAL snapshot and an app-origin CURRENT
serialization are BYTE-IDENTICAL for the same content. The stage-3 diff (snapshot_diff) compares an
original against a later current, so a drifted format would silently break the annotations diff for
import-origin recipes; single-sourcing the format here is the correctness guarantee (mirrors
snapshot_diff.py's pure-module shape).

Inputs are "row-like": either mappings (dicts — e.g. the import plan) OR attribute objects (ORM rows);
_get() reads both. STEPS must carry a "text" key/attr — the ORM's RecipeStep maps the DB "text" column to
the attribute .body, so the ORM caller passes step dicts with "text" already resolved. Keys sorted,
ensure_ascii=False, compact separators — byte-stable so future diffs compare like-for-like.
"""
import json
from collections.abc import Mapping

# The recipe's editable CONTENT a snapshot captures: the 11 editable recipe fields, EXCLUDING non-content
# (id/created_at/source/uid/hash/owner — those live on the recipe, not the version), plus the ingredient
# columns below. Order is irrelevant (sort_keys), but kept explicit as the content contract. Mirrors
# snapshot_diff.CONTENT_FIELDS (the diff's copy of the same 11).
SNAPSHOT_RECIPE_FIELDS = (
    "name", "author", "source_url", "category", "servings", "prep_time",
    "cook_time", "total_time", "descr", "notes", "image",
)
SNAPSHOT_ING_FIELDS = (
    "position", "is_heading", "qty", "ingredient_id", "label", "note",
    "raw_text", "grams", "secondary_measure", "quantity", "unit",
)


def _get(row, key):
    """Read `key` from a mapping (dict — the import plan) or an attribute object (ORM row)."""
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _ing_row(row):
    """One ingredient row, projected for the snapshot.

    ⚠️ A HEADING'S TITLE IS PROJECTED INTO raw_text, AND `heading` IS NOT EMITTED. Migration 052
    gave a heading row its own title column so converting a line to a heading stops destroying the
    line, which means a converted heading now holds its title in `heading` and the line's source
    text in raw_text. The diff reads an ingredient heading's text from raw_text alone
    (snapshot_diff.ing_h), and all 300 reason='original' baselines were written that way.
    Resolving the title HERE keeps both true at once: the diff still reads one key, and every
    pre-052 heading row (heading NULL, title in raw_text) serializes to exactly the bytes it always
    did, so _recipe_annotations' byte-equal short-circuit survives for all 300 recipes untouched.

    Adding `heading` to SNAPSHOT_ING_FIELDS instead would have made every one of those 300
    baselines differ from its recipe's current serialization on the day it shipped, which is the
    cost the waits keys avoided by being omitted when empty. A title is never empty, so the same
    trick was not available."""
    out = {k: _get(row, k) for k in SNAPSHOT_ING_FIELDS}
    if out.get("is_heading"):
        title = _get(row, "heading")
        if title is not None:
            out["raw_text"] = title
    return out


SNAPSHOT_WAIT_FIELDS = (
    "position", "kind", "label", "min_minutes", "max_minutes",
    "ext_label", "ext_min_minutes", "ext_max_minutes",
    "when_kind", "when_label",
)
SNAPSHOT_STORAGE_FIELDS = (
    "position", "where_kept", "applies_to", "label", "min_minutes", "max_minutes",
)


def content_blob(recipe, ingredients, steps, waits=None, storage=None):
    """The stable JSON snapshot of a recipe's content. `recipe` is one row-like; the rest are lists of
    row-likes (steps carry 'text'). Projects the content fields, sorts keys, compact + ascii-safe
    -> a byte-stable string. THE format recipe_snapshots.content stores and snapshot_diff consumes.

    ⚠️ WAITS AND STORAGE ARE OMITTED WHEN EMPTY, AND THAT IS NOT TIDINESS. _recipe_annotations
    short-circuits on a byte-equal comparison against the stored baseline, and all 306 existing
    baselines were written before these keys existed. Emitting "waits":[] on every recipe would make
    every one of them differ from its baseline, forcing the diff to run 300 times to return the same
    answer. A recipe that GAINS a wait stops being byte-equal, which is correct: it changed.

    ⚠️ step_position IS NOT IN THE SNAPSHOT. It records which step a wait was read from, which is
    provenance rather than content, and moving a step would otherwise read as an edit to the wait.
    """
    body = {
        "recipe": {k: _get(recipe, k) for k in SNAPSHOT_RECIPE_FIELDS},
        "ingredients": [_ing_row(row) for row in ingredients],
        "steps": [
            {"position": _get(st, "position"), "is_heading": _get(st, "is_heading"), "text": _get(st, "text")}
            for st in steps
        ],
    }
    if waits:
        body["waits"] = [{k: _get(w, k) for k in SNAPSHOT_WAIT_FIELDS} for w in waits]
    if storage:
        body["storage"] = [{k: _get(x, k) for k in SNAPSHOT_STORAGE_FIELDS} for x in storage]
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
