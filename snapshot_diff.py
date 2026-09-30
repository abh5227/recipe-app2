"""snapshot_diff.py — the change-tracking DIFF (stage 3): compute what changed between two consecutive
recipe snapshots. PURE + dependency-light (json + difflib only) — two blobs in, a flat list of change
objects out, no DB / no side effects / deterministic. CONSUMED by app.py's `_recipe_annotations`,
which returns the raw entries for the recipe page to render. Stage 4 materializes its OUTPUT
(recipe_changes) and the Journal renders it.

Consumes the STAGE-1 blob format verbatim (serialize_recipe_content): {"recipe": {<11 content fields>},
"ingredients": [<rows>], "steps": [<rows>]}. Keep this in sync with that serializer — it's the contract.

Matching is CONTENT-MATCHED (not position-based — position-based cascades false "modified" on insert/delete):
  - INGREDIENT LINES: match by ingredient_id when BOTH rows carry one (a linked ingredient is a stable
    key -> unambiguous match). The rest (unlinked / id-on-one-side) match by TEXT SIMILARITY on the full
    "amount name" line via difflib (LCS blocks; 'replace' blocks paired by similarity >= THRESHOLD).
  - STEPS / HEADINGS: no key -> difflib content-match on the text (LCS + similarity for rewords).
  - The 11 CONTENT FIELDS: direct key-by-key compare.

MOVES EMIT NOTHING. Content matching is LCS-based, so a reordered row reads as a delete plus an insert
by construction — for ~99% of rows (only id-linked ingredients, ~1.5%, match positionally-independently
in phase 1; steps have no id). A final pass (_suppress_moves) pairs those halves back up and drops both,
because reordering is not a change to the recipe. See that function for the cross-section cost.

AMOUNT COHERENCE: an ingredient's amount is split across qty/quantity/unit, but `qty` is the single
COMBINED form (quantity/unit are its split, always consistent — see write_recipe_rows), so an amount edit
is reported as ONE change from `qty` alone ("sugar: 1 cup -> ¾ cup"), never three field-noise entries.

CHANGE OBJECT SHAPE (a flat, ordered list):
  {"kind": "field"|"ingredient"|"step"|"heading", "type": "added"|"removed"|"modified", ...}
  POSITION (O-c-0): every POSITIONAL change (ingredient/step/heading) carries new_pos/old_pos — the row's
  index in the current/original REAL sequence of its kind, HEADING-EXCLUDED (is_heading rows are NOT
  counted). This is THE O-c-1 ANCHORING CONTRACT: O-c-1 must index its rendered ingredient/step rows the
  SAME way (skip headings) or anchors misalign by the count of preceding headings. Content alone is unsafe
  (18.5% of recipes have duplicate labels). REMOVED items also carry `section` — the text of the heading
  that preceded them in the ORIGINAL list — so a struck item renders at its section's bottom (None => list
  bottom). NB `section` uses the HEADING-INCLUSIVE full position (ordering among headings needs the whole
  list), so new_pos/old_pos and section are deliberately DIFFERENT numbers: two purposes. FIELD changes are
  NAMED, not positional — no new_pos/old_pos/section.
  - field modified:       {kind:"field", type:"modified", field:<name>, from, to}
  - ingredient modified:  {kind:"ingredient", type:"modified", field:"amount"|"name"|"note", label, from, to, new_pos, old_pos}
  - ingredient added:     {kind:"ingredient", type:"added",   text:"<amount name>", label, new_pos, old_pos:None}
  - ingredient removed:   {kind:"ingredient", type:"removed", text:"<amount name>", label, new_pos:None, old_pos, section}
  - step/heading modified:{kind:..., type:"modified", from, to, new_pos, old_pos}
  - step/heading added:   {kind:..., type:"added",   text, new_pos, old_pos:None}
  - step/heading removed: {kind:..., type:"removed", text, new_pos:None, old_pos, section}
"""
import json
from difflib import SequenceMatcher

from snapshot_serialize import kind_change_key, kind_change_name_key   # noqa: F401  (re-exported)
import units   # pure unit abbreviator (mirrors scaler.js) — canonical amount COMPARE, kills unit-repr phantoms

# The modified-vs-(added+removed) boundary for UNLINKED rows / steps, tuned via the unit tests: a reword
# (a shared stem, e.g. "1 cup sugar" -> "¾ cup sugar" ~0.82, "sugar" -> "brown sugar" line ~0.76) reads as
# ONE modified; a wholesale replacement ("1 cup sugar" -> "3 eggs" ~0.2) reads as removed + added. 0.6 sits
# cleanly in the gap. (Linked ingredients ignore this — an ingredient_id match is unambiguous regardless.)
SIMILARITY_THRESHOLD = 0.6

CONTENT_FIELDS = (
    "name", "author", "source_url", "category", "servings", "prep_time",
    "cook_time", "total_time", "descr", "notes", "image",
)


def diff_snapshots(old_blob, new_blob):
    """The stage-3 entry point. old_blob/new_blob are the stage-1 JSON strings (or the parsed dicts).
    Returns a flat, ordered, deterministic list of change objects (empty if identical)."""
    old, new = _load(old_blob), _load(new_blob)
    changes = []
    changes += _diff_fields(old.get("recipe") or {}, new.get("recipe") or {})
    # ⚠️ `or []` ON BOTH SIDES. A baseline written before these keys existed has neither, and an
    #    empty list against a missing key must read as no change rather than as a deletion.
    changes += _diff_rows("wait", old.get("waits") or [], new.get("waits") or [], WAIT_LABEL)
    changes += _diff_rows("storage", old.get("storage") or [], new.get("storage") or [], STORAGE_LABEL)

    ing_h = lambda r: r.get("raw_text") or ""
    o_lines, o_ing_h = _split(old.get("ingredients") or [])
    n_lines, n_ing_h = _split(new.get("ingredients") or [])
    o_line_pos, n_line_pos = _indexer(o_lines), _indexer(n_lines)   # heading-EXCLUDED real-ingredient index
    o_ih_pos, n_ih_pos = _indexer(o_ing_h), _indexer(n_ing_h)       # ingredient-headings sequence
    ing_section = _section_lookup(old.get("ingredients") or [], ing_h)   # preceding heading uses FULL position
    # ⚠️ THE INDEXERS ARE BUILT OVER THE UNFILTERED LISTS, ABOVE THIS LINE. A row that only changed
    # kind is dropped from the MATCHING only — every surviving row keeps the ordinal it renders at,
    # because _indexer is keyed on id(row) and the same objects flow through.
    o_lines, o_ing_h, n_lines, n_ing_h = suppress_kind_changes(o_lines, o_ing_h, n_lines, n_ing_h)
    # ⚠️ THE ROW-ID PASS, AND EVERYTHING AFTER IT IS THE FALLBACK. _id_split takes out every pair the
    # two sides agree on by id and hands back only the rows that need guessing about. A reorder, a
    # rename and a duplicate name all stop being matching problems here rather than downstream.
    ing_pairs, o_lines, n_lines = _id_split(o_lines, n_lines)
    for o, n in ing_pairs:
        changes += _ingredient_pair_changes(o, n, n_line_pos(n), o_line_pos(o))
    changes += _diff_ingredients(o_lines, n_lines, o_line_pos, n_line_pos, ing_section)
    changes += _diff_headings(o_ing_h, n_ing_h, ing_h, o_ih_pos, n_ih_pos)

    step_text = lambda r: r.get("text") or ""
    o_steps, o_step_h = _split(old.get("steps") or [])
    n_steps, n_step_h = _split(new.get("steps") or [])
    o_step_pos, n_step_pos = _indexer(o_steps), _indexer(n_steps)   # heading-EXCLUDED real-step index
    o_sh_pos, n_sh_pos = _indexer(o_step_h), _indexer(n_step_h)     # step-headings sequence
    step_section = _section_lookup(old.get("steps") or [], step_text)
    # ⚠️ THE SAME SUPPRESSION THE INGREDIENTS GET, AND IT WAS MISSING HERE. The rule that a heading
    # change carries no annotation was implemented on one side of the page only. Measured against the
    # real diff before this line existed: converting one step to a heading emitted 2 entries (the step
    # struck through as removed, plus a heading added), and lifting a lead-in label into a heading
    # above its step emitted 4. The identical ingredient conversion emitted 0.
    #
    # It did not matter while nothing could convert a step. sync_heading_layout says so in as many
    # words, and the editor's step row menu still offers only Add step / Add heading / Delete. It
    # matters now, because ~70 steps are about to become headings and a cook who converts one back
    # should not be told they deleted a step.
    o_steps, o_step_h, n_steps, n_step_h = suppress_kind_changes(o_steps, o_step_h, n_steps, n_step_h)
    step_pairs, o_steps, n_steps = _id_split(o_steps, n_steps)
    for o, n in step_pairs:
        if units.compare_text(step_text(o)) != units.compare_text(step_text(n)):
            changes.append(_mod("step", step_text(o), step_text(n),
                                n_step_pos(n), o_step_pos(o), _rid(n)))
    changes += _diff_seq(
        o_steps, n_steps, step_text,
        # Conditional for the same reason _diff_headings' is — see the note there.
        on_pair=lambda o, n: ([_mod("step", step_text(o), step_text(n),
                                    n_step_pos(n), o_step_pos(o), _rid(n))]
                              if units.compare_text(step_text(o)) != units.compare_text(step_text(n))
                              else []),
        on_add=lambda r: _added("step", step_text(r), n_step_pos(r), _rid(r)),
        on_remove=lambda r: _removed("step", step_text(r), o_step_pos(r), step_section(r.get("position"))),
    )
    changes += _diff_headings(o_step_h, n_step_h, step_text, o_sh_pos, n_sh_pos)
    return _suppress_moves(changes)


# ---- helpers ------------------------------------------------------------------------------------

def _load(blob):
    return json.loads(blob) if isinstance(blob, str) else blob


def _split(rows):
    """Partition rows into (lines, headings) so heading shifts never pollute line matching."""
    lines = [r for r in rows if not r.get("is_heading")]
    headings = [r for r in rows if r.get("is_heading")]
    return lines, headings


# kind_change_key is imported from snapshot_serialize, the module that owns the snapshot row format,
# so this reader and snapshot_headsync cannot disagree about what a row is called. Re-exported here
# because the diff's own tests reach for it by this module's name.


def suppress_kind_changes(o_lines, o_heads, n_lines, n_heads):
    """Drop rows that ONLY changed kind from all four matching sequences.

    ⚠️ BEFORE difflib, NOT AFTER. A line that becomes a heading leaves the lines sequence and joins
    the headings sequence, so difflib reports it as an ingredient REMOVED — struck through at the
    bottom of its section, as though the ingredient were gone, when it is still on the page as a
    section title. Worse, the heading arriving in the other sequence shifts that alignment, and an
    UNRELATED heading reads as renamed. Suppressing afterwards can pair the removal away but cannot
    undo the misalignment, because by then difflib has already chosen the wrong pairs. Removing the
    row from both sequences first means neither ever happens.

    Emitting nothing is the right answer, not a convenient one: heading changes carry no annotation
    by existing ruling (they are organizational), and a converted row shows the same words on the
    page in a different style. Nothing about the recipe's content moved.

    ⚠️ CONSUME-ONCE, for the same reason _Carry consumes once. brioche-bread repeats an ingredient
    NAME 9 times. Converting one of two rows called "salt" must retire exactly one old line against
    exactly one new heading and leave the other pair to difflib.

    Returns the four sequences with the paired rows removed. Callers keep indexing positions off the
    UNFILTERED lists — _indexer is keyed on id(row), so a surviving row keeps its true ordinal and
    every anchor below it stays aligned."""
    used, changed = set(), set()

    def pair(froms, tos, key_of, record):
        pool = {}
        for r in tos:
            k = key_of(r)
            if k is not None:
                pool.setdefault(k, []).append(r)
        for r in froms:
            key = key_of(r)
            if key is None:
                continue                       # no key on this side, so nothing to match it against
            bucket = pool.get(key) or []
            while bucket:
                other = bucket.pop(0)
                if id(other) not in used and id(r) not in used:
                    used.add(id(r))
                    used.add(id(other))
                    if record:
                        changed.add(key)
                    break

    # ⚠️ TWO PASSES, THE ID FIRST, AND THE SECOND IS NOT A SIMILARITY TIER. A row with an id is
    # matched on it alone, so a conversion that also retitles the row is still one row. The 24
    # baseline rows the commit-3 backfill left with a null id have no such key, so they fall back to
    # the name matching that has always handled them. Only the name pass feeds the twin trimming
    # below, because a baseline cannot hold the same id twice (proven over all 300) and so cannot
    # produce an id twin.
    for froms, tos in ((o_lines, n_heads), (o_heads, n_lines)):
        pair(froms, tos, kind_change_key, record=False)
    for froms, tos in ((o_lines, n_heads), (o_heads, n_lines)):
        pair(froms, tos, kind_change_name_key, record=True)

    keep = lambda rows: [r for r in rows if id(r) not in used]
    o_lines, o_heads, n_lines, n_heads = (keep(o_lines), keep(o_heads),
                                          keep(n_lines), keep(n_heads))

    # ⚠️ THE HEADING SYNC LEAVES A TWIN IN THE BASELINE, and it is not a bug there. The save that
    # converts a line also runs sync_original_heading_layout, whose rule is "the baseline's content
    # rows, untouched, plus CURRENT's headings". The converted row is a content row of the baseline
    # AND a heading of current, so the baseline comes out holding it both ways. P1 and P2 are both
    # satisfied (no content row was added or dropped, positions still enumerate), so the sync is
    # doing exactly what it is specified to do.
    #
    # The consequence lands here: the old line has been retired against the new heading above, and
    # the twin is left over in the OLD headings sequence with nothing to match, reading as a heading
    # the user deleted. Only the OLD side can carry one — the twin is created in the baseline, and
    # converting BACK removes it again, which is why that direction needs nothing.
    for key in changed:
        excess = (sum(1 for r in o_heads if kind_change_name_key(r) == key)
                  - sum(1 for r in n_heads if kind_change_name_key(r) == key))
        while excess > 0:
            for i, r in enumerate(o_heads):
                if kind_change_name_key(r) == key:
                    o_heads.pop(i)
                    break
            excess -= 1

    return o_lines, o_heads, n_lines, n_heads


def _similar(a, b):
    return SequenceMatcher(None, a or "", b or "").ratio()


def _diff_headings(o_heads, n_heads, text_of, o_pos, n_pos):
    """Section headings, by row id first and then by text. Both heading sequences of both kinds come
    through here, which is why it is a function rather than four call sites.

    Heading entries are computed and NOT rendered (annotationIndex ignores kind:"heading" — a heading
    change is organizational by existing ruling), so what this really guarantees is that a heading
    never disturbs the matching of the rows around it."""
    out = []
    pairs, o_left, n_left = _id_split(o_heads, n_heads)
    for o, n in pairs:
        if units.compare_text(text_of(o)) != units.compare_text(text_of(n)):
            out.append(_mod("heading", text_of(o), text_of(n), n_pos(n), o_pos(o), _rid(n)))
    out += _diff_seq(
        o_left, n_left, text_of,
        # ⚠️ CONDITIONAL, unlike the pre-commit-4 version. A 'replace' block can now pair two rows
        # whose text differs only in whitespace, and an unconditional _mod would report that as a
        # rename the cook cannot see.
        on_pair=lambda o, n: ([_mod("heading", text_of(o), text_of(n), n_pos(n), o_pos(o), _rid(n))]
                              if units.compare_text(text_of(o)) != units.compare_text(text_of(n))
                              else []),
        on_add=lambda r: _added("heading", text_of(r), n_pos(r), _rid(r)),
        on_remove=lambda r: _removed("heading", text_of(r), o_pos(r), None),
    )
    return out


# ⚠️ row_id IS THE CURRENT ROW'S DATABASE ID, AND IT IS WHAT THE CLIENT ANCHORS ON. The ledger used to
# place a mark by new_pos, the heading-excluded ordinal, which means the client had to count its rendered
# rows exactly as the diff counted its own and skip headings in the same places. Two independent counters
# agreeing by convention. The row id is the row, so the client looks the mark up directly. A REMOVED entry
# has no current row, so its row_id is None and it is still placed by `section` — unchanged.
def _mod(kind, frm, to, new_pos=None, old_pos=None, row_id=None):
    return {"kind": kind, "type": "modified", "from": frm, "to": to, "new_pos": new_pos,
            "old_pos": old_pos, "row_id": row_id}


def _added(kind, text, new_pos, row_id=None):
    return {"kind": kind, "type": "added", "text": text, "new_pos": new_pos, "old_pos": None,
            "row_id": row_id}


def _removed(kind, text, old_pos, section):
    return {"kind": kind, "type": "removed", "text": text, "new_pos": None, "old_pos": old_pos,
            "section": section, "row_id": None}


def _rid(row):
    return row.get("id") if row else None


def _id_split(old_rows, new_rows):
    """(pairs, old_left, new_left) — the ROW-ID pass, which runs before any text matching.

    ⚠️ THIS IS WHAT THE WHOLE OF OPTION C WAS FOR. A row keeps its database id across every save, and
    the reason='original' baseline records the id each of its rows was born as, so "is this the same
    row" is now a lookup rather than a guess. Everything difflib and the similarity threshold were
    doing for these rows was an approximation of this answer.

    What it fixes, in order of how much it mattered:
      - A REORDER emits nothing. Dragging a row changed its position, which changed which baseline row
        difflib lined it up against, so a pure reorder could report a removal and an addition. The
        pair is found by id wherever either row sits.
      - A RENAME stays one row. Rewriting a name past the 0.6 similarity threshold split one row into
        a removal plus an addition. Matched by id, it is one row with a changed name.
      - A DUPLICATE NAME cannot be confused. brioche-bread lists 9 names twice. Text matching has to
        pair them by order and hope.

    ⚠️ CONSUME-ONCE AND NULL IS NEVER A KEY. A null id means the backfill found no partner for that
    baseline row (24 rows over 19 recipes), and two nulls are not a match — they fall through to the
    text matching they have always used. The bucket-per-id form is defensive: the backfill proved no
    id repeats within a recipe, and a repeat would pair in order rather than raise."""
    by_id = {}
    for r in new_rows:
        i = _rid(r)
        if i is not None:
            by_id.setdefault(i, []).append(r)
    pairs, old_left, claimed = [], [], set()
    for o in old_rows:
        bucket = by_id.get(_rid(o)) if _rid(o) is not None else None
        if bucket:
            n = bucket.pop(0)
            pairs.append((o, n))
            claimed.add(id(n))
        else:
            old_left.append(o)
    return pairs, old_left, [n for n in new_rows if id(n) not in claimed]


def _indexer(rows):
    """id(row) -> its ordinal in this list. THE O-c-1 ANCHORING CONTRACT: new_pos/old_pos index the REAL
    (heading-EXCLUDED) sequence of the row's kind — is_heading rows are NOT counted. O-c-1 must anchor by
    indexing its rendered ingredient/step rows the SAME way (skip headings) or anchors misalign by the
    count of preceding headings. Survives the ingredient phase-1/phase-2 split: the same dict objects flow
    through, so id() is stable."""
    m = {id(r): i for i, r in enumerate(rows)}
    return lambda r: m.get(id(r))


def _section_lookup(rows, text_of):
    """(original row position -> the text of the nearest heading PRECEDING it, i.e. its section; None if it
    sits before any heading). Lets a REMOVED item name the section it lived in, so O-c-1 renders it struck
    at that section's bottom (falling back to list-bottom on None / a section since gone). Uses the
    HEADING-INCLUSIVE full `position` (ordering among headings needs the whole list) — deliberately a
    different index than new_pos/old_pos. Pure — derived from the ORIGINAL rows the snapshot already carries."""
    heads = sorted(((r.get("position"), text_of(r)) for r in rows
                    if r.get("is_heading") and r.get("position") is not None), key=lambda x: x[0])
    def section_of(pos):
        if pos is None:
            return None
        name = None
        for hp, ht in heads:
            if hp < pos:
                name = ht
            else:
                break
        return name
    return section_of


def _diff_fields(o, n):
    """The 11 recipe header fields. Compared through units.compare_text, so null and empty are the same
    absence (they always were here) and so is a re-wrap: a headnote whose only difference is trailing
    whitespace or a collapsed line break reads identically once the page lays it out."""
    out = []
    for f in CONTENT_FIELDS:
        ov, nv = o.get(f), n.get(f)
        if units.compare_text(ov) != units.compare_text(nv):
            out.append({"kind": "field", "type": "modified", "field": f, "from": ov, "to": nv,
                        "row_id": None})
    return out


# ⚠️ WAITS AND STORAGE ARE TREATED EXACTLY LIKE prep_time, WHICH IS THE RULING. Both are captured in
#    the snapshot blob and both surface in "your changes" as an ordinary modification. The reason is
#    that they are the same KIND of thing: a fact about the recipe a person typed, which no step edit
#    updates on their behalf. What they are NOT is derived, so they are not diffed as text either.
WAIT_LABEL = ("label", "kind", "min_minutes", "max_minutes", "ext_label", "ext_min_minutes",
              "ext_max_minutes", "when_kind", "when_label")
STORAGE_LABEL = ("label", "where_kept", "applies_to", "min_minutes", "max_minutes")


def _row_text(r, fields):
    """The one line a wait or storage row reads as, so a change reports what a person would see.

    ⚠️ THE QUALIFIER IS PART OF THE LINE. Turning a wait optional changes nothing else about it, so
    without this the "your changes" entry would read as the same words twice."""
    bits = [str(r.get(f)) for f in fields[:2] if r.get(f) not in (None, "")]
    ext = r.get("ext_label")
    return " · ".join(bits) + (f" ({ext})" if ext else "") + when_suffix(r)


def when_suffix(r):
    """" (optional)" or " (if chilled)", and nothing at all for an ordinary wait."""
    wk = r.get("when_kind") or "always"
    if wk == "optional":
        return " (optional)"
    if wk == "only_if":
        return f" (if {r.get('when_label') or ''})".replace(" )", ")")
    return ""


def _differ(o, n, fields):
    return any(units.compare_text(o.get(f)) != units.compare_text(n.get(f)) for f in fields)


def _diff_rows(kind, old_rows, new_rows, fields):
    """Waits and storage. BY ROW ID FIRST, then positionally over whatever is left.

    ⚠️ THE POSITIONAL FALLBACK USED TO BE THE WHOLE THING, and its reason has expired. It read "these
    are short ordered lists a person edits by hand, and tracking identity across a table with no stable
    key in the snapshot is not worth it" — true while the snapshot held no key. It holds one now, so a
    reordered wait is one row that moved rather than two modifications.

    Positions still come from the UNFILTERED lists, so a row the id pass took out does not shift the
    ordinal of a row it left behind. Both tables are empty on live today (0 rows, and the keys are
    omitted from the snapshot entirely when empty), so this is the shape the feature will land on
    rather than a repair of anything currently visible."""
    o_pos = {id(r): i for i, r in enumerate(old_rows)}
    n_pos = {id(r): i for i, r in enumerate(new_rows)}
    pairs, old_left, new_left = _id_split(old_rows, new_rows)
    out = []
    for o, n in pairs:
        if _differ(o, n, fields):
            out.append(_mod(kind, _row_text(o, fields), _row_text(n, fields),
                            n_pos[id(n)], o_pos[id(o)], _rid(n)))
    for i in range(max(len(old_left), len(new_left))):
        o = old_left[i] if i < len(old_left) else None
        n = new_left[i] if i < len(new_left) else None
        if o is None:
            out.append(_added(kind, _row_text(n, fields), n_pos[id(n)], _rid(n)))
        elif n is None:
            out.append(_removed(kind, _row_text(o, fields), o_pos[id(o)], None))
        elif _differ(o, n, fields):
            out.append(_mod(kind, _row_text(o, fields), _row_text(n, fields),
                            n_pos[id(n)], o_pos[id(o)], _rid(n)))
    return out


def _ing_name(r):
    """The ingredient's NAME (no amount): the label for a linked row, else raw_text — which for a
    free-text line is JUST the name (qty is a separate column), so this never folds the amount in."""
    return r.get("label") or r.get("raw_text") or ""


def _ing_line(r):
    """The full "amount name" display — the RAW emitted `text` for added/removed entries. (The phase-2
    similarity KEY is _ing_line_canon, which canonicalizes the qty; this stays raw so the output text
    shows what was actually there.)"""
    return f"{r.get('qty') or ''} {_ing_name(r)}".strip()


def _canon_amount(qty):
    """The canonical COMPARISON form of an amount: units.compare_key, which abbreviates the unit word,
    normalizes the fraction glyph, collapses whitespace, trims and lowercases.

    ⚠️ IT COMPARES WHAT THE COOK SEES, NOT WHAT IS STORED, AND THAT IS THE POINT. The client
    re-canonicalizes units on every save ("1 teaspoon" is stored back as "1 tsp"), and the reading view
    runs every amount through toUnicodeFractions before printing it, so "1/2 tsp" and "½ tsp" are the
    same characters on the page. Comparing the raw strings put a mark on a row reading "½ tsp -> ½ tsp",
    which is a change the cook cannot see and did not make. Measured on live: 608 amounts hold a vulgar
    glyph and 288 an ascii spelling.

    Detection only. The emitted from/to keep the RAW stored strings, so a genuine change shows the real
    values, and the NUMBER is never touched by any of these rules."""
    return units.compare_key(qty)


def _ing_line_canon(r):
    """The phase-2 similarity KEY: the "amount name" line with the qty CANONICALIZED (_canon_amount, the
    same transform as the amount compare). Because the client canonicalizes units on every save
    (teaspoon->tsp), the RAW line drifts (e.g. "1 teaspoon kosher salt" -> "1 tsp sea salt"), which can
    push a borderline rename below SIMILARITY_THRESHOLD and split ONE modify into remove+add. Canonicalizing
    the qty here holds the similarity stable across that representation drift. MATCHING only — the emitted
    text/from/to stay raw (via _ing_line / _ing_name); the name portion is untouched, so a real rename that
    genuinely diverges still falls below threshold."""
    return f"{_canon_amount(r.get('qty'))} {_ing_name(r)}".strip()


def _ingredient_pair_changes(o, n, new_pos=None, old_pos=None):
    """The field-level diff of a MATCHED ingredient pair (id-matched or similarity-matched). AMOUNT is one
    coherent change from `qty`; name and note are their own changes. Emits only the aspects that differ.
    new_pos/old_pos are the heading-excluded real-ingredient indices (the O-c-1 anchor)."""
    label = _ing_name(n) or _ing_name(o)
    rid, out = _rid(n), []
    if _canon_amount(o.get("qty")) != _canon_amount(n.get("qty")):   # what the cook sees, not what is stored
        out.append({"kind": "ingredient", "type": "modified", "field": "amount", "label": label,
                    "from": o.get("qty") or "", "to": n.get("qty") or "", "new_pos": new_pos,
                    "old_pos": old_pos, "row_id": rid})
    if units.compare_text(_ing_name(o)) != units.compare_text(_ing_name(n)):
        out.append({"kind": "ingredient", "type": "modified", "field": "name", "label": label,
                    "from": _ing_name(o), "to": _ing_name(n), "new_pos": new_pos,
                    "old_pos": old_pos, "row_id": rid})
    if units.compare_text(o.get("note")) != units.compare_text(n.get("note")):
        out.append({"kind": "ingredient", "type": "modified", "field": "note", "label": label,
                    "from": o.get("note") or "", "to": n.get("note") or "", "new_pos": new_pos,
                    "old_pos": old_pos, "row_id": rid})
    return out


def _diff_ingredients(old_lines, new_lines, o_pos, n_pos, section_of=lambda p: None):
    changes = []
    # PHASE 1 — match by ingredient_id present on BOTH sides (a linked ingredient = a stable key)
    o_by_id = {}
    for i, r in enumerate(old_lines):
        iid = r.get("ingredient_id")
        if iid:
            o_by_id.setdefault(iid, []).append(i)
    o_used = [False] * len(old_lines)
    n_used = [False] * len(new_lines)
    for j, nr in enumerate(new_lines):
        iid = nr.get("ingredient_id")
        if iid and o_by_id.get(iid):
            i = o_by_id[iid].pop(0)
            o_used[i], n_used[j] = True, True
            changes += _ingredient_pair_changes(old_lines[i], nr, n_pos(nr), o_pos(old_lines[i]))
    # PHASE 2 — the leftovers (unlinked / id-on-one-side) match by text similarity on the full line
    o_left = [r for i, r in enumerate(old_lines) if not o_used[i]]
    n_left = [r for j, r in enumerate(new_lines) if not n_used[j]]
    changes += _diff_seq(
        o_left, n_left, _ing_line_canon,   # MATCH on the canonical line (qty unit-normalized); emit raw text below
        on_pair=lambda o, n: _ingredient_pair_changes(o, n, n_pos(n), o_pos(o)),
        on_add=lambda r: {"kind": "ingredient", "type": "added", "text": _ing_line(r), "label": _ing_name(r),
                          "new_pos": n_pos(r), "old_pos": None, "row_id": _rid(r)},
        on_remove=lambda r: {"kind": "ingredient", "type": "removed", "text": _ing_line(r), "label": _ing_name(r),
                             "new_pos": None, "old_pos": o_pos(r), "section": section_of(r.get("position")),
                             "row_id": None},
        # The ONE opt-in: `note` is not in the match key, so a note-only edit lands in an 'equal' block
        # and its pair never reaches _ingredient_pair_changes (whose note branch has always worked, and
        # is reachable today only via phase-1's ingredient_id match — i.e. on 1.5% of real rows). Safe
        # here and nowhere else because this on_pair emits per-aspect: an unchanged pair yields [].
        pair_equal=True,
    )
    return changes


def _move_key(entry):
    """The comparison key for move detection: (kind, canonical text).

    CANONICAL, not raw, and that distinction is the whole correctness of this feature. A reorder in the
    real app happens THROUGH A SAVE, and the client re-canonicalizes units on every row — so the REMOVED
    entry carries the ORIGINAL snapshot's raw text ('1 litre filtered or soft water') while the ADDED
    entry carries the current rows ('1 liter filtered or soft water'). Comparing raw text passes every
    synthetic reorder test and then suppresses NOTHING in production. Measured, not theorized.

    Reuses units.canon_unit_str — the same transform _ing_line_canon already uses as the phase-2 match
    key — rather than inventing a second notion of "the same line". It normalizes unit WORDS only, never
    numbers or names, so a moved-AND-edited row still differs and survives (see the tests).
    Steps/headings compare raw: their text carries no amount for a unit rule to touch."""
    text = entry.get("text") or ""
    return (entry["kind"],
            units.compare_key(text) if entry["kind"] == "ingredient" else units.compare_text(text))


def _suppress_moves(changes):
    """Drop the removed+added PAIR a pure reorder produces, emitting nothing for a move.

    WHY A POST-PASS AND NOT AN EARLIER SEAM: a moved row lands in a `delete` opcode at its old index and
    an `insert` opcode at its new index — two DIFFERENT blocks of _diff_seq's loop. Nothing at pair
    formation can see both halves, so this is the only seam where the pair is visible at all.

    WHY IT DROPS RATHER THAN EMITS: a move is not a change to the recipe, so it gets no entry and no new
    render vocabulary — decided, not incidental.

    ALL moves are suppressed, INCLUDING moves across a section heading. Within-section-only gating was
    considered and rejected: it needs a new-side section lookup that doesn't exist (section_of is built
    from the ORIGINAL rows), and it would make drag behaviour position-dependent — overshooting a heading
    mid-drag would emit annotations the user never intended. THE ACKNOWLEDGED COST: an item that changes
    which section it belongs to leaves no trace. That is a real recipe change ("the salt goes in the
    sauce now, not the marinade") and it is mechanically INDISTINGUISHABLE from a reorder — a delete-here
    plus an identical-add-there produces byte-identical output to a move. Accepted deliberately.

    GREEDY 1:1 — with N removed and M added sharing a key, exactly min(N, M) pairs are suppressed and the
    remainder survive. Never many-to-many: that keeps a genuine deletion visible when a DIFFERENT row
    with identical canonical text is merely moved.

    Pure: drops entries, never rewrites one, so every surviving from/to/text stays RAW. Order among the
    survivors is preserved (deterministic output is part of the contract)."""
    removed_by_key = {}
    for e in changes:
        if e.get("type") == "removed":
            removed_by_key.setdefault(_move_key(e), []).append(id(e))
    drop = set()
    for e in changes:
        if e.get("type") != "added":
            continue
        pool = removed_by_key.get(_move_key(e))
        if pool:                                  # a removed twin is still unclaimed -> it's a move
            drop.add(pool.pop(0))                 # claim that ONE removed entry (greedy, 1:1)
            drop.add(id(e))
    return [e for e in changes if id(e) not in drop]


def _diff_seq(old, new, text_of, on_pair, on_add, on_remove, pair_equal=False):
    """Content-matched diff of two ordered row lists by their text (difflib = LCS-based). 'equal' blocks
    are unchanged; 'delete' -> on_remove; 'insert' -> on_add; a 'replace' block pairs old/new greedily by
    similarity (>= THRESHOLD -> on_pair, a list of changes; else the leftovers -> on_remove/on_add). This
    is what makes an insert read as ONE 'added' (not a position-cascade) and a reword as 'modified'.

    pair_equal (OPT-IN, default OFF) also runs on_pair over 'equal' blocks, index-for-index. It exists
    because the match KEY is not the whole row: a row can be 'equal' by key and still differ on a field
    the key does not carry (an ingredient's `note`), so its pair never reaches on_pair and the change is
    invisible. Widening the key instead was measured and rejected — note text would enter the phase-2
    similarity ratio, where a long note drowns the name and splits a rename into remove+add, the exact
    regression _ing_line_canon exists to prevent.

    ⚠️ WHY OPT-IN RATHER THAN ALWAYS-ON. This function has FOUR callers and only ONE of them passes a
    CONDITIONAL on_pair. The ingredient caller passes _ingredient_pair_changes, which emits only the
    aspects that actually differ (so an unchanged pair yields []). The other three — ingredient
    headings, steps, step headings — pass `lambda o, n: [_mod(...)]`, which emits a 'modified' entry
    UNCONDITIONALLY, because today they only ever see a 'replace' block where the text genuinely
    differs. Turning this on for them would emit a spurious modification for every unchanged step and
    heading; measured, that is 8 failing tests. The default therefore stays OFF and only the ingredient
    call site opts in."""
    o = [text_of(r) for r in old]
    n = [text_of(r) for r in new]
    changes = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, o, n, autojunk=False).get_opcodes():
        if tag == "equal":
            if pair_equal:
                # Same length by construction (an 'equal' opcode spans matching runs), so index-for-index
                # pairing is exact — no matching decision is made or changed here.
                for k in range(i2 - i1):
                    changes += on_pair(old[i1 + k], new[j1 + k])
            continue
        if tag == "delete":
            changes += [on_remove(old[k]) for k in range(i1, i2)]
        elif tag == "insert":
            changes += [on_add(new[k]) for k in range(j1, j2)]
        else:  # replace — pair by similarity within the block
            news = list(range(j1, j2))
            used = set()
            for oi in range(i1, i2):
                best, bj = 0.0, None
                for nj in news:
                    if nj in used:
                        continue
                    r = _similar(o[oi], n[nj])
                    if r > best:
                        best, bj = r, nj
                if bj is not None and best >= SIMILARITY_THRESHOLD:
                    used.add(bj)
                    changes += on_pair(old[oi], new[bj])
                else:
                    changes.append(on_remove(old[oi]))
            for nj in news:
                if nj not in used:
                    changes.append(on_add(new[nj]))
    return changes
