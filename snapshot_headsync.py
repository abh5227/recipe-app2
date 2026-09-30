"""snapshot_headsync.py — sync the reason='original' baseline's HEADING LAYOUT to a recipe's current
headings. PURE + dependency-light (json only, plus the two sibling snapshot modules) — old blob +
current rows in, a new blob string out, no DB / no session / no side effects / deterministic.
Named to match its siblings: snapshot_serialize (the FORMAT), snapshot_diff (the DIFF), this (a
baseline TRANSFORM). Stage 1 shipped the transform + its postcondition, and both are LIVE now.
app.py's sync_original_heading_layout calls them on every save, reached from update_recipe, and
assert_content_safe raising there aborts the whole save.

WHY THIS EXISTS. A removed row's `section` is the text of the heading that preceded it IN THE
BASELINE (snapshot_diff._section_lookup), so once a heading moves, the strike renders in a section
that no longer describes where the row sits on screen. Heading changes emit NO annotations by
existing ruling (annotationIndex ignores kind:"heading"), so the baseline's heading layout carries no
information worth preserving — syncing it to current loses nothing and makes placement match what the
reader sees.

WHOLESALE REPLACEMENT, NEVER DETECTION. Move / add / remove / rename are NOT distinguished, and that
is the point: telling "this heading moved" from "this one was removed and a different one added" is
the same ambiguous matching problem _diff_seq solves imperfectly with an LCS + a similarity
threshold. Because there is nothing to preserve, there is nothing to match — drop every heading from
the baseline, re-interleave CURRENT's headings, renumber. Every case falls out of the one operation.

⚠️ THE DIRECTION THAT MATTERS. The baseline's CONTENT rows are the recipe's birth state and this
transform must never touch them. It reads ONLY the heading rows of `current_*`; current's content
rows are deliberately never consulted. Sourcing content from current would not "merge" anything — it
would overwrite the birth state with the present one, so the user's edits would silently stop
registering as edits and their annotations would vanish. content_safety_problems() exists to make
that failure impossible to ship: it compares the OLD blob's content rows against the NEW blob's, so
it still fails loudly in exactly the case that hides the bug — when current's content differs from
the baseline's.
"""
import json

from snapshot_diff import _split                      # the ONE heading/content partitioner — not a second copy
from snapshot_serialize import (
    content_blob, kind_change_key, kind_change_name_key, snapshot_ing_row, snapshot_step_row,
)

# The step row's three keys (snapshot_serialize spells them inline in its steps projection).
# SNAPSHOT_STEP_FIELDS moved to snapshot_serialize, beside the ingredient list and the two row
# builders that project them. _reinterleave takes a BUILDER now, not a field tuple — see below.


class HeadingSyncViolation(Exception):
    """Raised by assert_content_safe when a transform result would alter CONTENT rows."""


def _get(row, key):
    """Read from a mapping (blob dict / import plan) or an attribute object (ORM row) — mirrors
    snapshot_serialize._get so this module accepts exactly the same row-likes its serializer does."""
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _load(blob):
    return json.loads(blob) if isinstance(blob, str) else blob


def _content_ordinal_of_headings(rows):
    """For each heading in `rows`, how many CONTENT rows precede it — i.e. 'this heading sits just
    before the k-th content row'. Deliberately a content-relative anchor, not the raw full-list index:
    the baseline and current can hold different NUMBERS of content rows (rows added or deleted since
    birth), so a raw index would run off the end of the shorter list or land arbitrarily. The
    content ordinal is the same heading-EXCLUDED counting snapshot_diff._indexer uses for anchoring,
    which keeps this transform speaking the engine's existing coordinate system.

    ⚠️ THIS IS AN APPROXIMATION, and knowingly so. It is exact only while the baseline's and current's
    content sequences still line up. Once they have diverged — rows added or deleted since birth — the
    k-th content row of CURRENT is not necessarily the k-th content row of the BASELINE, so placing a
    heading before the baseline's k-th row is a best guess at which baseline rows lived under it. There
    is no better answer available without solving the row-matching problem, and solving it is exactly
    what the wholesale-replacement ruling declined to do (nothing to preserve -> nothing to match).
    It is acceptable because of what the guess can and cannot affect: the ONLY consumer of the
    baseline's heading layout is snapshot_diff._section_lookup, i.e. the `section` a REMOVED row
    carries, i.e. WHICH SECTION a struck row renders at the bottom of. A wrong guess renders a strike
    under a neighbouring heading. It cannot alter, drop, or invent a content row — that is P1's job,
    and P1 is checked independently."""
    out, seen = [], 0
    for r in rows:
        if _get(r, "is_heading"):
            out.append((seen, r))
        else:
            seen += 1
    return out


def _reinterleave(old_rows, current_rows, row_of, skip_converted=False):
    """Baseline CONTENT rows (order and values untouched) + CURRENT headings, re-interleaved by
    content ordinal, then renumbered so `position` is the row's index in the combined list —
    exactly how write_recipe_rows assigns it (enumerate over the heading-INCLUSIVE list).

    ⚠️ `row_of` IS THE SNAPSHOT'S OWN ROW BUILDER, NOT A FIELD TUPLE, and that is the fix for a real
    defect. This took `fields` and did a plain `{k: row[k] for k in fields}` copy, which quietly
    skipped the projection content_blob applies. Migration 052 let a converted heading keep the
    line's source text in raw_text and hold its title in `heading`, so the plain copy wrote
    "125 g milk lukewarm (95-104°F)" into the BASELINE as a section title. Taking the builder means
    a second copy of the projection cannot drift from the first, because there is no second copy.
    (The generic `_as_dict(row, fields)` helper this used to lean on has been deleted, so there is no
    field-copy builder left in this module for the next change to reach for by mistake.)

    ⚠️ ROW IDS RIDE THROUGH ON BOTH SIDES, and taking the builder is what makes that free. A baseline
    CONTENT row keeps the id the backfill gave it, because the builder copies the key it finds. A
    CURRENT heading contributes its own live id, which is right: the baseline's heading layout is
    replaced wholesale from current, so the heading in the new blob IS that live row."""
    content = [row_of(r) for r in old_rows if not _get(r, "is_heading")]
    heads = _content_ordinal_of_headings(current_rows)
    if skip_converted:
        # ⚠️ A CONVERTED ROW IS NOT A SECTION, AND COPYING IT IN DUPLICATES IT. The baseline holds
        # the recipe's BIRTH content, where this row was an ingredient LINE and still is, above.
        # Current holds it as a heading because the user converted it. Copying current's heading in
        # regardless left the baseline carrying the same row twice, as a line and as a title, which
        # is not a state the recipe was ever in.
        #
        # The damage was in the annotations, and it compounded. The duplicate has no counterpart in
        # current, so it read as a heading the user had deleted; and on a recipe that lists an
        # ingredient twice (brioche-bread has a Metric list and a US list) the extra name collided
        # with the real second row and reported THAT one removed instead. Every further conversion
        # save added another.
        #
        # Skipping it leaves the baseline's heading layout differing from current by exactly the
        # converted rows, which is correct: in the baseline's world those rows are content, and the
        # layout exists only so a REMOVED row can name the section it lived in.
        # ⚠️ BY ID *OR* BY NAME, AND None IS NEVER A KEY. kind_change_key became the row id in
        # commit 4, and keying on it alone broke this: a baseline content row with a null id and a
        # current heading with a null id both keyed as None, so EVERY heading matched and every one
        # was dropped from the baseline. The two checks answer different halves. The id catches a
        # conversion that also RETITLED the row, which the name can never see. The name catches the
        # case where the baseline row is one of the 24 with no id to match on. Their union is the
        # behaviour this had before commit 4 plus the retitle case, so it is never less correct.
        ids = {kind_change_key(r) for r in content} - {None}
        names = {kind_change_name_key(r) for r in content}
        converted = lambda h: (kind_change_key(h) in ids
                               or kind_change_name_key(h) in names)
        heads = [(o, h) for o, h in heads if not converted(h)]

    merged, ci = [], 0
    for ordinal, h in heads:
        stop = min(ordinal, len(content))              # clamp: current may name an ordinal past the
        while ci < stop:                               # baseline's shorter content list
            merged.append(content[ci]); ci += 1
        merged.append(row_of(h))
    while ci < len(content):
        merged.append(content[ci]); ci += 1

    for i, r in enumerate(merged):                     # P2: position == index in the full list
        r["position"] = i
    return merged


def sync_heading_layout(old_blob, current_ingredients, current_steps):
    """The transform. `old_blob` is the stored reason='original' JSON (string or parsed dict);
    `current_ingredients` / `current_steps` are the recipe's CURRENT rows (row-likes — dicts or ORM
    rows), of which ONLY the heading rows are read. Returns the new blob STRING.

    Byte-stability is INHERITED, not reimplemented: the result is serialized by
    snapshot_serialize.content_blob, the single source of the format, so sort_keys / ensure_ascii /
    separators and the full key projection come from there. This module never calls json.dumps. That
    also means every key is reproduced on every row by construction — including the nine keys a
    heading row pins to null, which a hand-built dict would be free to omit and thereby change the
    bytes.

    ⚠️ EVERY KEY THIS FUNCTION DOES NOT INTERLEAVE IS HANDED BACK AS IT WAS FOUND. content_blob
    DEFAULTS waits and storage to None, which OMITS them, so calling it with three arguments
    silently stripped both from every baseline a save rewrote. Measured on the round-3 preview
    copy: one save on morning-buns left its baseline with no waits key, and all six of that
    recipe's waits then reported as "added" in "your changes" for good. This function's job is the
    HEADING LAYOUT and nothing else."""
    old = _load(old_blob)
    return content_blob(
        old.get("recipe") or {},
        _reinterleave(old.get("ingredients") or [], current_ingredients, snapshot_ing_row,
                      skip_converted=True),
        # ⚠️ STEPS SKIP TOO NOW. This read "nothing converts a step to a heading or back", which was
        # true of the editor and is no longer true of the data: the heading conversions convert steps
        # in place, keeping the row id. Without the skip the baseline would come out holding a
        # converted row twice, as a content step AND as a title, which is the exact duplicate the
        # ingredient note below describes and the same compounding damage.
        _reinterleave(old.get("steps") or [], current_steps, snapshot_step_row,
                      skip_converted=True),
        old.get("waits"),
        old.get("storage"),
    )


# ---- the postcondition ---------------------------------------------------------------------------

# ⚠️ POSITION AND ID ARE BOTH PROJECTED OUT OF P1, FOR DIFFERENT REASONS. A correct sync renumbers
#    position (see P1's docstring). `id` comes out because P1 is a check on CONTENT and an id is not
#    content — and because projecting it keeps the check honest about a baseline written before the
#    ids existed: such a row has no `id` key at all, while the builder emits `"id": null` for it, so a
#    strict dict compare would fail P1 and abort the save with a 500 on a recipe whose content is
#    perfectly intact. P4 below checks the ids separately, in the tolerant direction.
_BARE_EXCLUDE = ("position", "id")


def _strip_pos(rows):
    return [{k: v for k, v in r.items() if k not in _BARE_EXCLUDE} for r in rows]


def content_safety_problems(old_blob, new_blob):
    """Check the two postconditions and return a LIST OF HUMAN-READABLE PROBLEMS (empty == safe).
    A list rather than a bool so a caller can abort with a message that says what actually broke.

    P1 — CONTENT PRESERVED. The sequence of non-heading rows, with `position` projected out, is
    identical between old and new: same rows, same order, same values on every other key. Position is
    projected out because a correct sync legitimately renumbers content rows — write_recipe_rows
    enumerates position over the heading-INCLUSIVE list, so moving one heading shifts every content
    row after it (measured on a real recipe: [0,2,3,4…] -> [1,3,4,5…]). Asserting byte-equality
    INCLUDING position would therefore fail on every correct sync, which is why P1 is stated this way
    and not the obvious way.

    P2 — POSITIONS WELL-FORMED. Every row's position equals its index in the new full list. Without
    it, P1 could be satisfied by a blob whose positions no longer round-trip through the writer.

    P3 — NO KEY DROPPED. Every top-level key in the old blob is still in the new one. P1 and P2 read
    ingredients and steps only, so a key outside those two could be lost without either firing.

    ⚠️ THE DIRECTION OF P1 IS LOAD-BEARING — DO NOT "FIX" IT TO COMPARE AGAINST CURRENT.
    P1 compares the OLD blob against the NEW blob: the transform's own invariance. The baseline holds
    the recipe's BIRTH content, and the whole purpose of this check is that those rows survive
    verbatim. It looks natural to sanity-check the result against the recipe's CURRENT rows instead —
    "does the baseline still match reality?" — and that reading is exactly backwards. Current's
    content is SUPPOSED to differ from the baseline whenever the user has edited anything; that
    difference IS the annotation set. A check written against current would therefore pass in
    precisely the case that hides the catastrophic bug: if a faulty transform copied current's content
    into the baseline, an old-vs-new check FAILS (loudly, naming the changed fields) while a
    vs-current check would report a perfect match — having just destroyed the birth state, silently,
    permanently, and indistinguishably from the user having made those edits themselves. There is no
    second copy of a baseline to restore from (recipe_snapshots has no versioning and
    snapshot_original is WHERE NOT EXISTS-guarded), which is why this is stated at this length.
    tests/test_heading_sync.py pins the direction from both sides: the adversarial cases give current
    values that appear NOWHERE in the expected output, and the abort-path test feeds a transform that
    sources content from current and asserts this function rejects it."""
    old, new = _load(old_blob), _load(new_blob)
    problems = []

    for name in ("ingredients", "steps"):
        o_content, _ = _split(old.get(name) or [])
        n_content, _ = _split(new.get(name) or [])
        if len(o_content) != len(n_content):
            problems.append(
                f"P1 {name}: content-row COUNT changed {len(o_content)} -> {len(n_content)} "
                f"(a heading sync must never add or drop a content row)")
            continue
        o_bare, n_bare = _strip_pos(o_content), _strip_pos(n_content)
        if o_bare != n_bare:
            for i, (a, b) in enumerate(zip(o_bare, n_bare)):
                if a != b:
                    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
                    problems.append(
                        f"P1 {name}[{i}]: content row CHANGED on {diff} — "
                        f"old={ {k: a.get(k) for k in diff} } new={ {k: b.get(k) for k in diff} }")

        rows = new.get(name) or []
        actual = [r.get("position") for r in rows]
        if actual != list(range(len(rows))):
            problems.append(f"P2 {name}: positions are not 0..{len(rows) - 1} — got {actual}")

    # P3 — NOTHING ELSE IS DROPPED.
    # ⚠️ P1 AND P2 READ ingredients AND steps ONLY, so a key neither of them knows about can vanish
    #    without either noticing. That is exactly how waits and storage were lost: the transform
    #    rebuilt the blob from three arguments, content_blob omitted the two it was not given, and
    #    this function reported no problem. P3 is stated over the KEY SET rather than over a list of
    #    known keys, so the next key added to the snapshot is covered before anyone remembers it.
    missing = sorted(set(old) - set(new))
    if missing:
        problems.append(
            f"P3: the sync dropped top-level key(s) {missing} — a heading sync must carry every "
            f"key it does not interleave straight through")

    # P4 — A CONTENT ROW KEEPS ITS ID.
    # ⚠️ THE ONE-WAY FORM IS DELIBERATE: an id the old row HAS must survive, and an id it lacks may be
    #    filled in. P1 cannot carry this check because it projects `id` out (see above), and without it
    #    a transform could hand back the right content under the wrong row identity — which after
    #    commit 4, where the diff matches on id, would silently re-point every annotation on the
    #    recipe. Stated over the rows P1 already found comparable, so it never fires on a count change.
    for name in ("ingredients", "steps"):
        o_content, _ = _split(old.get(name) or [])
        n_content, _ = _split(new.get(name) or [])
        if len(o_content) != len(n_content):
            continue                                       # P1 already reported it
        for i, (a, b) in enumerate(zip(o_content, n_content)):
            if a.get("id") is not None and a.get("id") != b.get("id"):
                problems.append(
                    f"P4 {name}[{i}]: content row id changed {a.get('id')} -> {b.get('id')} — "
                    f"a heading sync must never re-point a content row")
    return problems


def assert_content_safe(old_blob, new_blob):
    """Raise HeadingSyncViolation (with every problem named) unless the transform preserved content.
    The abort hook for a caller: raising inside the save transaction leaves no partial state, because
    the write is not committed until after."""
    problems = content_safety_problems(old_blob, new_blob)
    if problems:
        raise HeadingSyncViolation("heading sync would alter content:\n  - " + "\n  - ".join(problems))
