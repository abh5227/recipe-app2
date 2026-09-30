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
# ⚠️ `id` IS THE ROW'S DATABASE PRIMARY KEY, AND IT IS THE WHOLE POINT OF OPTION C. Every other key
# here describes the row's CONTENT. This one says WHICH ROW IT IS, which is the question text could
# never answer: two rows can read "1 tsp salt" and a renamed row reads as a stranger. A save now
# updates the rows it was given in place (write_recipe_rows matches by id), so a live row keeps its id
# for life, and a baseline row carrying that id is bound to its live counterpart no matter how the
# text is edited afterwards.
#
# ⚠️ ADDING IT CHANGED THE BYTES OF ALL 300 STORED BASELINES, WHICH IS WHY IT SHIPPED WITH A BACKFILL.
# _recipe_annotations short-circuits when the stored baseline equals the recipe's current
# serialization, so a key that current emits and the baselines lack would end that short-circuit for
# every recipe at once. The waits/storage keys dodged this by being omitted when empty (see
# content_blob) and a row id cannot: NULL is a meaningful answer here, not an absence.
# scripts/backfill_baseline_row_ids.py wrote the ids into all 300 in the same commit, and
# docs/data-repairs/ holds the row-by-row audit of what it assigned.
#
# ⚠️ THE DIFF STILL MATCHES ON TEXT. Nothing in snapshot_diff reads this key yet — it compares named
# keys and derived text, never whole rows, so an id cannot add or remove an annotation on its own.
# Matching by id is commit 4, and kind_change_key below is the one line that swaps over.
SNAPSHOT_ING_FIELDS = (
    "id", "position", "is_heading", "qty", "ingredient_id", "label", "note",
    "raw_text", "grams", "secondary_measure", "quantity", "unit",
)


def _get(row, key):
    """Read `key` from a mapping (dict — the import plan) or an attribute object (ORM row)."""
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


SNAPSHOT_STEP_FIELDS = ("id", "position", "is_heading", "text")   # `id` — see the note above


def kind_change_key(row):
    """THE row identity across an ingredient <-> heading conversion: the database id.

    ⚠️ THIS WAS THE ROW'S NAME UNTIL COMMIT 4, and the id answers the question the name only
    approximated. A conversion that ALSO retitles the row was invisible to the name key, so it read as
    the ingredient being removed and an unrelated heading appearing. The id does not care what the row
    is called.

    ⚠️ None IS NOT A KEY, AND kind_change_name_key BELOW IS WHY THAT IS SAFE. 24 baseline rows over 19
    recipes carry no id, because the commit-3 backfill found no content match for them. Two nulls are
    not a match, so those rows keep the name matching they have always used.

    ⚠️ IT LIVES HERE, in the module that owns the snapshot row format, because BOTH readers need the
    same answer: snapshot_diff, to recognize a row that only changed kind, and snapshot_headsync, to
    avoid writing a heading into the baseline for a row the baseline already holds as a line."""
    return _get(row, "id")


def kind_change_name_key(row):
    """The FALLBACK key, for a row on either side that has no id. This was kind_change_key's whole
    body before commit 4 and its reasoning is unchanged.

    ⚠️ ONE EXPRESSION FOR BOTH KINDS, AND IT WORKS BECAUSE OF WHAT EACH KIND KEEPS. A line's name is
    its `label`, falling back to raw_text for the handful of live rows that have none. A heading
    converted from a line keeps that same `label` dormant beside its title (migration 052), and a
    heading that was BORN one has no label, so it falls back to raw_text — which for a born heading
    IS its title. The same read answers "what is this row called" on either side of a conversion.

    ⚠️ AND `text` ANSWERS IT FOR A STEP, which is the third arm. A step row carries neither `label`
    nor `raw_text`, so before this arm existed every step keyed to "" and the fallback was useless
    for the kind it was about to be asked about. An ingredient row never carries `text`, so the arm
    is a pure addition on that side rather than a change of meaning.

    ⚠️ IT IS THE WEAKER HALF FOR A STEP, ON PURPOSE. Converting a step to a heading usually REWRITES
    its text (an emphasis wrap comes off, a lead-in label is lifted out), so the name will not match
    across the conversion and the id is what carries it. Exactly one baseline step row in 300
    recipes has no id, so the id is available for 2,366 of 2,367."""
    name = _get(row, "label") or _get(row, "raw_text") or _get(row, "text") or ""
    return " ".join(name.split()).lower()


def snapshot_step_row(row):
    """One step row, projected for the snapshot. Public for the same reason snapshot_ing_row is."""
    return {k: _get(row, k) for k in SNAPSHOT_STEP_FIELDS}


def snapshot_ing_row(row):
    """One ingredient row, projected for the snapshot.

    ⚠️ PUBLIC, AND EVERY BUILDER OF A SNAPSHOT ROW MUST COME THROUGH HERE. It was private, and
    snapshot_headsync._reinterleave built its rows with a plain field copy instead. That was
    harmless while a heading's title WAS its raw_text, and wrong the moment migration 052 let a
    converted heading keep the line's source text in raw_text: the heading sync then wrote
    "125 g milk lukewarm (95-104°F)" into the baseline as a section title, and the recipe page
    reported an unrelated heading as renamed. One projection in one place, used by both.

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


# `id` here for the same reason it is on a row above, and at no cost: both keys are OMITTED from the
# snapshot entirely when the list is empty (see content_blob), and live holds 0 waits and 0 storage
# rows, so not one of the 300 stored baselines carries either key to be invalidated. This is the shape
# the feature lands on rather than a change to anything currently stored.
SNAPSHOT_WAIT_FIELDS = (
    "id", "position", "kind", "label", "min_minutes", "max_minutes",
    "ext_label", "ext_min_minutes", "ext_max_minutes",
    "when_kind", "when_label",
)
# ⚠️ step_id, alongside_step_id AND ext_step_id ARE NOT IN THE SNAPSHOT, deliberately and for the
# reason step_position was not (see content_blob). They record WHICH STEP a wait was read from or
# points at, which is provenance rather than content, and a step that moved would otherwise read as
# an edit to the wait.
SNAPSHOT_STORAGE_FIELDS = (
    "id", "position", "where_kept", "applies_to", "label", "min_minutes", "max_minutes",
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
        "ingredients": [snapshot_ing_row(row) for row in ingredients],
        "steps": [snapshot_step_row(st) for st in steps],
    }
    if waits:
        body["waits"] = [{k: _get(w, k) for k in SNAPSHOT_WAIT_FIELDS} for w in waits]
    if storage:
        body["storage"] = [{k: _get(x, k) for k in SNAPSHOT_STORAGE_FIELDS} for x in storage]
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
