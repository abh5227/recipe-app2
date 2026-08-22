"""snapshot_diff.py — the change-tracking DIFF (stage 3): compute what changed between two consecutive
recipe snapshots. PURE + dependency-light (json + difflib only) — two blobs in, a flat list of change
objects out, no DB / no side effects / deterministic. Nothing consumes it yet; stage 4 materializes its
OUTPUT (recipe_changes) and the Journal renders it.

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

    ing_h = lambda r: r.get("raw_text") or ""
    o_lines, o_ing_h = _split(old.get("ingredients") or [])
    n_lines, n_ing_h = _split(new.get("ingredients") or [])
    o_line_pos, n_line_pos = _indexer(o_lines), _indexer(n_lines)   # heading-EXCLUDED real-ingredient index
    ing_section = _section_lookup(old.get("ingredients") or [], ing_h)   # preceding heading uses FULL position
    changes += _diff_ingredients(o_lines, n_lines, o_line_pos, n_line_pos, ing_section)
    o_ih_pos, n_ih_pos = _indexer(o_ing_h), _indexer(n_ing_h)       # ingredient-headings sequence
    changes += _diff_seq(                                   # ingredient headings, kept OUT of line matching
        o_ing_h, n_ing_h, ing_h,
        on_pair=lambda o, n: [_mod("heading", ing_h(o), ing_h(n), n_ih_pos(n), o_ih_pos(o))],
        on_add=lambda r: _added("heading", ing_h(r), n_ih_pos(r)),
        on_remove=lambda r: _removed("heading", ing_h(r), o_ih_pos(r), None),
    )

    step_text = lambda r: r.get("text") or ""
    o_steps, o_step_h = _split(old.get("steps") or [])
    n_steps, n_step_h = _split(new.get("steps") or [])
    o_step_pos, n_step_pos = _indexer(o_steps), _indexer(n_steps)   # heading-EXCLUDED real-step index
    step_section = _section_lookup(old.get("steps") or [], step_text)
    changes += _diff_seq(
        o_steps, n_steps, step_text,
        on_pair=lambda o, n: [_mod("step", step_text(o), step_text(n), n_step_pos(n), o_step_pos(o))],
        on_add=lambda r: _added("step", step_text(r), n_step_pos(r)),
        on_remove=lambda r: _removed("step", step_text(r), o_step_pos(r), step_section(r.get("position"))),
    )
    o_sh_pos, n_sh_pos = _indexer(o_step_h), _indexer(n_step_h)     # step-headings sequence
    changes += _diff_seq(
        o_step_h, n_step_h, step_text,
        on_pair=lambda o, n: [_mod("heading", step_text(o), step_text(n), n_sh_pos(n), o_sh_pos(o))],
        on_add=lambda r: _added("heading", step_text(r), n_sh_pos(r)),
        on_remove=lambda r: _removed("heading", step_text(r), o_sh_pos(r), None),
    )
    return _suppress_moves(changes)


# ---- helpers ------------------------------------------------------------------------------------

def _load(blob):
    return json.loads(blob) if isinstance(blob, str) else blob


def _split(rows):
    """Partition rows into (lines, headings) so heading shifts never pollute line matching."""
    lines = [r for r in rows if not r.get("is_heading")]
    headings = [r for r in rows if r.get("is_heading")]
    return lines, headings


def _similar(a, b):
    return SequenceMatcher(None, a or "", b or "").ratio()


def _mod(kind, frm, to, new_pos=None, old_pos=None):
    return {"kind": kind, "type": "modified", "from": frm, "to": to, "new_pos": new_pos, "old_pos": old_pos}


def _added(kind, text, new_pos):
    return {"kind": kind, "type": "added", "text": text, "new_pos": new_pos, "old_pos": None}


def _removed(kind, text, old_pos, section):
    return {"kind": kind, "type": "removed", "text": text, "new_pos": None, "old_pos": old_pos, "section": section}


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
    out = []
    for f in CONTENT_FIELDS:
        ov, nv = o.get(f), n.get(f)
        if (ov or "") != (nv or ""):                       # None and "" are both "empty" (no spurious change)
            out.append({"kind": "field", "type": "modified", "field": f, "from": ov, "to": nv})
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
    """The canonical COMPARISON form of an amount — unit-abbreviated + lowercased + trimmed (units.
    canon_unit_str), mirroring the client's canonicalizeUnit. The client re-canonicalizes units on EVERY
    save ("1 teaspoon" -> stored "1 tsp"), so an untouched row's baseline-vs-current differs in the unit
    STRING only; comparing canonical forms means that representation-only drift doesn't read as an amount
    edit. Detection only — the emitted from/to keep the RAW strings, so a genuine change shows real values.
    The number is never touched (only unit words match the rules), so a real amount change still differs."""
    return units.canon_unit_str(qty or "")


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
    out = []
    if _canon_amount(o.get("qty")) != _canon_amount(n.get("qty")):   # canonical compare: unit-repr drift is NOT a change
        out.append({"kind": "ingredient", "type": "modified", "field": "amount", "label": label,
                    "from": o.get("qty") or "", "to": n.get("qty") or "", "new_pos": new_pos, "old_pos": old_pos})
    if _ing_name(o) != _ing_name(n):
        out.append({"kind": "ingredient", "type": "modified", "field": "name", "label": label,
                    "from": _ing_name(o), "to": _ing_name(n), "new_pos": new_pos, "old_pos": old_pos})
    if (o.get("note") or "") != (n.get("note") or ""):
        out.append({"kind": "ingredient", "type": "modified", "field": "note", "label": label,
                    "from": o.get("note") or "", "to": n.get("note") or "", "new_pos": new_pos, "old_pos": old_pos})
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
                          "new_pos": n_pos(r), "old_pos": None},
        on_remove=lambda r: {"kind": "ingredient", "type": "removed", "text": _ing_line(r), "label": _ing_name(r),
                             "new_pos": None, "old_pos": o_pos(r), "section": section_of(r.get("position"))},
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
    return (entry["kind"], units.canon_unit_str(text) if entry["kind"] == "ingredient" else text)


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
