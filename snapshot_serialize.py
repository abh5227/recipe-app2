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


def content_blob(recipe, ingredients, steps):
    """The stable JSON snapshot of a recipe's content. `recipe` is one row-like; `ingredients`/`steps` are
    lists of row-likes (steps carry 'text'). Projects the content fields, sorts keys, compact + ascii-safe
    -> a byte-stable string. THE format recipe_snapshots.content stores and snapshot_diff consumes."""
    return json.dumps(
        {
            "recipe": {k: _get(recipe, k) for k in SNAPSHOT_RECIPE_FIELDS},
            "ingredients": [{k: _get(row, k) for k in SNAPSHOT_ING_FIELDS} for row in ingredients],
            "steps": [
                {"position": _get(st, "position"), "is_heading": _get(st, "is_heading"), "text": _get(st, "text")}
                for st in steps
            ],
        },
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
