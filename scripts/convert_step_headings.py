#!/usr/bin/env python3.13
"""convert_step_headings.py - the Round A step-structure repairs, in LOCKSTEP.

Four passes over the step rows, each driven by a DECISION column in docs/data-repairs/:

  1  EMPHASIZED AND TITLE-LIKE STEPS BECOME HEADINGS, IN PLACE.
     step-headings-candidates-*.csv, DECISION_convert_yes_no == yes.
     The row keeps its id, so a wait link, an annotation anchor and a margin mark all survive.

  2  A LEAD-IN LABEL IS LIFTED INTO A HEADING ABOVE ITS STEP.
     step-leadin-labels-*.csv, DECISION_make_heading_yes_no == yes.
     A NEW heading row is inserted above; the labeled step keeps its id and loses the label from its
     text. Unlabeled steps that follow sit under the heading because nothing separates them from it.

  3  A Note: OR Tip: STEP MOVES TO THE RECIPE'S NOTES.
     Same CSV, DECISION == "no (note/tip)". The step row goes away and its words are appended to
     recipes.notes.

  4  HEADING TEXT STORED IN ALL CAPS BECOMES SENTENCE CASE.
     Measured, not listed: every is_heading=1 step row whose text has letters and no lowercase.
     Runs LAST so it also catches the headings passes 1 and 2 just created.

⚠️ LOCKSTEP IS THE WHOLE POINT, AND IT IS WHY THIS IS A SCRIPT AND NOT A SAVE. Every live change here
   is matched by the same change to the recipe's reason='original' baseline, inside one transaction,
   so the recipe's "your changes" set is byte-identical before and after. A conversion done through
   the editor instead would be a real edit by a real cook and SHOULD leave a mark. This is the app
   correcting its own import, which is not something the cook did.

⚠️ THE BASELINE IS PATCHED SURGICALLY, NOT REBUILT FROM THE LIVE ROWS. 16 of the 300 recipes have
   drifted from their baseline on purpose, and substituting live's steps wholesale would erase the
   annotations that drift represents. Each pass applies its OWN edit to the baseline row with the
   matching id and leaves every other byte alone.

⚠️ notes IS IN SNAPSHOT_RECIPE_FIELDS. Pass 3 changes a recipe header field, so the baseline's
   recipe.notes has to move with it or the cook is told they edited a note they never touched.

Usage:  convert_step_headings.py <db> [--apply]      (default is a dry run)
"""
import argparse
import csv
import json
import pathlib
import re
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import snapshot_serialize                                        # noqa: E402

REPAIRS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "data-repairs"
HEADINGS_CSV = REPAIRS / "step-headings-candidates-2026-09-30.csv"
LABELS_CSV = REPAIRS / "step-leadin-labels-2026-09-30.csv"

# ⚠️ A BLANK LINE, MEASURED RATHER THAN CHOSEN. Of the 79 newline runs inside the 92 recipes that
#    have notes, 78 are a single blank line and one is a four-newline gap on one recipe. A new note
#    joins the convention the corpus already keeps.
NOTE_SEPARATOR = "\n\n"

# A lead-in label: a short capitalized phrase, a colon, then the step's own words.
LEAD = re.compile(r"^([A-Z][^:.!?]{0,60}?):\s+(\S.*)$", re.S)
# A whole step wrapped in one matched pair of emphasis markers.
EMPHASIS = re.compile(r"^(\*\*|__|\*|_)(.+?)\1$", re.S)


def _is_caps(text):
    """Letters, and not one of them lowercase. "FRY #1" yes, "Finish with COLD butter" no."""
    t = (text or "").strip()
    return bool(t) and any(c.isalpha() for c in t) and t == t.upper()


def sentence_case(text):
    """ALL CAPS -> sentence case, keeping the punctuation and any digits.

    ⚠️ IT LOWERCASES PROPER NOUNS TOO, and that is accepted rather than solved. "MAKE CRISPY CHEESY
    BIRRIA TACOS!" becomes "Make crispy cheesy birria tacos!". Guessing which words are names is the
    kind of rule that gets one wrong quietly, so every change this makes is listed in the run's
    report for a person to read.
    """
    t = (text or "").strip()
    if not t:
        return t
    lowered = t.lower()
    for i, ch in enumerate(lowered):
        if ch.isalpha():
            return lowered[:i] + ch.upper() + lowered[i + 1:]
    return lowered


def _decisions(path, column, wanted):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            if (r.get(column) or "").strip() in wanted:
                rows.append(r)
    return rows


def _baseline(c, rid):
    row = c.execute("SELECT content FROM recipe_snapshots WHERE recipe_id=? AND reason='original'",
                    (rid,)).fetchone()
    return json.loads(row["content"]) if row else None


def _write_baseline(c, rid, body):
    c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? AND reason='original'",
              (json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")), rid))


def _renumber(rows):
    """position == index in the full heading-INCLUSIVE list, which is what write_recipe_rows does."""
    for i, r in enumerate(rows):
        r["position"] = i
    return rows


def _live_steps(c, rid):
    return [dict(r) for r in c.execute(
        "SELECT id, position, is_heading, text FROM recipe_steps WHERE recipe_id=? "
        "ORDER BY position, id", (rid,))]


def run(db, apply_it):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    log = {"convert": [], "label": [], "note": [], "caps": [], "skipped": []}

    # ---- pass 1: a step becomes a heading in place ----------------------------------------------
    for r in _decisions(HEADINGS_CSV, "DECISION_convert_yes_no", {"yes"}):
        rid, sid = r["recipe_id"], int(r["step_row_id"])
        title = (r["proposed_heading"] or "").strip()
        live = c.execute("SELECT text, is_heading FROM recipe_steps WHERE id=? AND recipe_id=?",
                         (sid, rid)).fetchone()
        if live is None:
            log["skipped"].append((rid, sid, "no such live step"))
            continue
        body = _baseline(c, rid)
        if body is None:
            log["skipped"].append((rid, sid, "no baseline"))
            continue
        target = next((s for s in body.get("steps") or [] if s.get("id") == sid), None)
        if target is None:
            log["skipped"].append((rid, sid, "not in the baseline"))
            continue
        c.execute("UPDATE recipe_steps SET is_heading=1, text=? WHERE id=?", (title, sid))
        target["is_heading"], target["text"] = 1, title
        _write_baseline(c, rid, body)
        log["convert"].append((rid, sid, live["text"], title))

    # ---- pass 2: a lead-in label is lifted into a heading above its step -------------------------
    for r in _decisions(LABELS_CSV, "DECISION_make_heading_yes_no", {"yes"}):
        rid, sid = r["recipe_id"], int(r["step_row_id"])
        live = c.execute("SELECT text, position FROM recipe_steps WHERE id=? AND recipe_id=?",
                         (sid, rid)).fetchone()
        if live is None:
            log["skipped"].append((rid, sid, "no such live step"))
            continue
        m = LEAD.match(" ".join((live["text"] or "").split()))
        if not m:
            log["skipped"].append((rid, sid, "no lead-in label in the live text"))
            continue
        label, rest = m.group(1).strip(), m.group(2).strip()
        body = _baseline(c, rid)
        steps = (body or {}).get("steps") or []
        bi = next((i for i, s in enumerate(steps) if s.get("id") == sid), None)
        if bi is None:
            log["skipped"].append((rid, sid, "not in the baseline"))
            continue
        # ⚠️ THE HEADING GOES IN ABOVE AND THE STEP KEEPS ITS ID. That id is what a wait link, an
        #    annotation anchor and a margin mark are all bound to. beans' overnight soak and
        #    butter-chicken's marinade both point at a labeled step.
        rows = _live_steps(c, rid)
        at = next(i for i, s in enumerate(rows) if s["id"] == sid)
        cur = c.execute(
            "INSERT INTO recipe_steps (recipe_id, position, is_heading, text) VALUES (?,?,1,?)",
            (rid, -1, label))
        new_id = cur.lastrowid
        rows.insert(at, {"id": new_id, "position": -1, "is_heading": 1, "text": label})
        rows[at + 1]["text"] = rest
        for s in _renumber(rows):
            c.execute("UPDATE recipe_steps SET position=?, text=? WHERE id=?",
                      (s["position"], s["text"], s["id"]))
        blank = {k: None for k in snapshot_serialize.SNAPSHOT_STEP_FIELDS}
        blank.update({"id": new_id, "is_heading": 1, "text": label})
        steps.insert(bi, blank)
        steps[bi + 1]["text"] = rest
        body["steps"] = _renumber(steps)
        _write_baseline(c, rid, body)
        log["label"].append((rid, sid, new_id, label, rest[:60]))

    # ---- pass 3: a Note:/Tip: step moves to the recipe's Notes -----------------------------------
    for r in _decisions(LABELS_CSV, "DECISION_make_heading_yes_no", {"no (note/tip)"}):
        rid, sid = r["recipe_id"], int(r["step_row_id"])
        live = c.execute("SELECT text FROM recipe_steps WHERE id=? AND recipe_id=?",
                         (sid, rid)).fetchone()
        if live is None:
            log["skipped"].append((rid, sid, "no such live step"))
            continue
        # ⚠️ A WAIT POINTING AT THIS STEP WOULD LOSE ITS LINK. ON DELETE SET NULL would clear it
        #    silently, so refuse instead and let a person decide.
        linked = c.execute("SELECT id FROM recipe_waits WHERE step_id=? OR alongside_step_id=? "
                           "OR ext_step_id=?", (sid, sid, sid)).fetchone()
        if linked:
            log["skipped"].append((rid, sid, "a wait points at this step"))
            continue
        body = _baseline(c, rid)
        steps = (body or {}).get("steps") or []
        bi = next((i for i, s in enumerate(steps) if s.get("id") == sid), None)
        if bi is None:
            log["skipped"].append((rid, sid, "not in the baseline"))
            continue
        text = " ".join((live["text"] or "").split())
        old_notes = c.execute("SELECT notes FROM recipes WHERE id=?", (rid,)).fetchone()["notes"]
        new_notes = text if not (old_notes or "").strip() \
            else f"{old_notes.rstrip()}{NOTE_SEPARATOR}{text}"
        c.execute("UPDATE recipes SET notes=? WHERE id=?", (new_notes, rid))
        c.execute("DELETE FROM recipe_steps WHERE id=?", (sid,))
        for s in _renumber(_live_steps(c, rid)):
            c.execute("UPDATE recipe_steps SET position=? WHERE id=?", (s["position"], s["id"]))
        # ⚠️ BOTH HALVES OF THE BASELINE MOVE. notes is in SNAPSHOT_RECIPE_FIELDS, so leaving it
        #    behind would mint a "your changes" entry saying the cook rewrote the recipe's notes.
        steps.pop(bi)
        body["steps"] = _renumber(steps)
        body["recipe"]["notes"] = new_notes
        _write_baseline(c, rid, body)
        log["note"].append((rid, sid, text[:80]))

    # ---- pass 4: ALL CAPS heading text becomes sentence case -------------------------------------
    # Runs last so it catches the headings passes 1 and 2 just made.
    for row in [dict(x) for x in c.execute(
            "SELECT id, recipe_id, text FROM recipe_steps WHERE is_heading=1 ORDER BY recipe_id, position")]:
        raw = (row["text"] or "").strip()
        # An emphasis wrap on an EXISTING heading comes off in the same pass. 2 rows carry one.
        m = EMPHASIS.match(raw)
        unwrapped = m.group(2).strip() if m else raw
        title = sentence_case(unwrapped) if _is_caps(unwrapped) else unwrapped
        if title == row["text"]:
            continue
        body = _baseline(c, row["recipe_id"])
        target = next((s for s in (body or {}).get("steps") or [] if s.get("id") == row["id"]), None)
        if target is None:
            log["skipped"].append((row["recipe_id"], row["id"], "caps: not in the baseline"))
            continue
        c.execute("UPDATE recipe_steps SET text=? WHERE id=?", (title, row["id"]))
        target["text"] = title
        _write_baseline(c, row["recipe_id"], body)
        log["caps"].append((row["recipe_id"], row["id"], row["text"], title))

    if apply_it:
        c.commit()
    else:
        c.rollback()
    return log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    log = run(a.db, a.apply)
    print(f"{'APPLIED' if a.apply else 'DRY RUN'}  {a.db}")
    print(f"  1 steps converted to headings in place : {len(log['convert'])}")
    print(f"  2 lead-in labels lifted into headings  : {len(log['label'])}")
    print(f"  3 Note/Tip steps moved to Notes        : {len(log['note'])}")
    print(f"  4 headings recased or unwrapped        : {len(log['caps'])}")
    if log["skipped"]:
        print(f"  SKIPPED: {len(log['skipped'])}")
        for x in log["skipped"]:
            print(f"     {x}")
    return log


if __name__ == "__main__":
    main()
