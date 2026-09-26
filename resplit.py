#!/usr/bin/env python3
"""resplit.py - re-read a STORED ingredient line and re-derive its amount/unit/name split.

⚠️ THE ONE SHARED PATH. Every re-split goes through here, so a rule can never be applied to the
live rows and skipped on the baselines.

WHY LOCKSTEP EXISTS. The recipe page shows "your changes" by diffing each row against its
`reason='original'` snapshot. A parser improvement that re-splits a live row and leaves the
baseline alone therefore invents an edit the cook never made. ed6aaf5 did exactly that on
2026-09-23: it lifted the counting noun into the unit on 73 live rows, touched no baseline, and
minted 73 phantom amount-edits that the page has been showing ever since, against 8 real ones.

THE RULE, in three parts:

  1. A re-split writes the live row AND its baseline row, in ONE transaction.
  2. Each side is re-split from ITS OWN raw_text. The baseline NEVER copies the live row's split,
     because the two texts can legitimately differ: an edit made since the baseline was minted has
     to stay visible in the crossed-out view.
  3. raw_text is never touched on either side. A re-split re-reads a line, it does not rewrite it.

WHAT IT WRITES: qty, quantity, unit, label. Nothing else.

⚠️ grams AND secondary_measure ARE NOT RE-DERIVED. A stored weight was harvested from the line as
it read at import, and a re-split that re-harvested could only ever lose one (a row whose gram
paren the old save already stripped out would come back empty). Never lose information.
"""
import json

import import_cleanup as ic
from snapshot_serialize import content_blob

SPLIT_COLUMNS = ("qty", "quantity", "unit", "label")


from import_write import _qty_text          # THE qty join, shared with a fresh import


def split_columns(raw_text, stored_qty=None, hints=None):
    """The split a re-read of `raw_text` produces: {qty, quantity, unit, label}, or None.

    None means DO NOT WRITE, and it is returned for the two cases a re-split must never force:
    the line reads as a section (turning an ingredient into a heading loses it from the list), and
    the line yields no name at all.

    `stored_qty` is passed to the parser as has_stored_amount so a row that already carries an
    amount is never re-read as a section heading. See classify_line.
    """
    text = (raw_text or "").strip()
    if not text:
        return None
    res = ic.classify_line(text, hints, has_stored_amount=bool((stored_qty or "").strip()))
    if res["kind"] == "section":
        return None
    name = (res.get("name") or "").strip()
    if not name:
        return None
    qty = _qty_text(res)
    # ⚠️ NEVER LOSE AN AMOUNT. A stored row can carry a qty its raw_text does not, which is exactly
    #    what the old save left behind: it rewrote raw_text with the displayed name and the amount
    #    survived only in the qty column. Re-reading that text finds no amount, and writing the
    #    result back would throw the stored one away. The re-split then updates the NAME only.
    if qty is None and (stored_qty or "").strip():
        return {"label": name}
    return {
        "qty": qty,
        "quantity": None if qty is None else (res.get("amount") or ""),
        "unit": None if qty is None else (res.get("unit") or ""),
        "label": name,
    }


def plan_row(row, hints=None):
    """One stored row (a mapping with raw_text/qty/quantity/unit/label) -> the columns that would
    change, or {} when the re-split agrees with what is already there."""
    got = split_columns(row.get("raw_text"), row.get("qty"), hints)
    if got is None:
        return {}
    return {k: v for k, v in got.items() if (row.get(k) or None) != (v or None)}


def baseline_rows(conn, recipe_id):
    """{position: row} for a recipe's 'original' baseline, plus the snapshot id and its doc."""
    got = conn.execute("SELECT id, content FROM recipe_snapshots "
                       "WHERE recipe_id = ? AND reason = 'original'", (recipe_id,)).fetchone()
    if got is None:
        return None, None, {}
    snap_id, doc = got[0], json.loads(got[1])
    at = {x["position"]: x for x in doc.get("ingredients") or [] if x.get("position") is not None}
    return snap_id, doc, at


def write_lockstep(conn, recipe_id, changes, hints=None):
    """Apply a re-split to the live rows AND the matching baseline rows. ⚠️ The CALLER owns the
    transaction, so both halves land together or neither does.

    `changes` is {position: {column: value}} for the LIVE rows. The baseline is re-split here, from
    its OWN text, rather than taking anything from `changes`.

    Returns (live rows written, baseline rows written).
    """
    n_live = 0
    for pos, cols in sorted(changes.items()):
        if not cols:
            continue
        sets = ", ".join(f"{k} = ?" for k in cols)
        conn.execute(f"UPDATE recipe_ingredients SET {sets} "
                     "WHERE recipe_id = ? AND position = ? AND is_heading = 0",
                     (*cols.values(), recipe_id, pos))
        n_live += 1

    snap_id, doc, at = baseline_rows(conn, recipe_id)
    if snap_id is None:
        return n_live, 0
    n_base = 0
    for pos in sorted(changes):
        row = at.get(pos)
        if row is None or row.get("is_heading"):
            continue
        got = plan_row(row, hints)          # ⚠️ the BASELINE's own text, never the live row's
        if not got:
            continue
        row.update(got)
        n_base += 1
    if n_base:
        conn.execute("UPDATE recipe_snapshots SET content = ? WHERE id = ?",
                     (content_blob(doc["recipe"], doc["ingredients"], doc["steps"]), snap_id))
    return n_live, n_base


def recipe_hints(conn, recipe_id):
    """The step-heading hints clean_recipe derives, so a re-read sees what an import saw."""
    steps = [r[0] or "" for r in conn.execute(
        "SELECT text FROM recipe_steps WHERE recipe_id = ? ORDER BY position", (recipe_id,))]
    return {ic._step_heading_key(t) for t in steps if ic.classify_step(t)[0]} - {""}
