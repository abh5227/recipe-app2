#!/usr/bin/env python3.13
"""apply_label_rules.py - the Round A FIX rules, over every recipe, in LOCKSTEP.

The second corpus pass. convert_step_headings.py lifted the labels; this applies the rules that
came out of Andy's click-through over the result, and the SAME rules run in the importer for new
recipes (import_cleanup). Nothing here is a hand edit: every row it touches is chosen by a rule, and
the handful a rule cannot choose are read from a decisions CSV a person filled in.

  7  A LIFTED LABEL THAT NAMES A SECTION BECOMES ONE.  "To make the chocolate icing", "If using
     dried chickpeas". import_cleanup.label_level is the rule.
  4  A NUMBER-LED LABEL IS A LABEL.  "30 min cool:" is a stage; "1 cup:" is an amount and is left.
  5  NO HEADING CARRIES LINK MARKUP.  A heading is escaped and never linkified, so the heading takes
     the plain words and the link lands on the next mention of the same word in the step below. The
     lift itself applies this (convert_step_headings._lift, import_cleanup.plan_step_rows); the
     sweep here reads every heading in the corpus, so it catches one neither of them made.
  6  THE STEP AFTER A LIFT STARTS WITH A CAPITAL.  Only a step a label was lifted OFF, which is why
     this reads the decision CSVs rather than every step under a heading: karak-chai's "a. Bring the
     pot to a boil" is an author's list marker under an author's heading and must not be touched.
  8  SIBLING ALTERNATIVES DIRECTLY UNDER A SECTION BECOME SUBHEADINGS OF IT, and an author heading
     lost before the shared steps is restored from the source when the decisions CSV names one.

⚠️ LOCKSTEP, for convert_step_headings.py's reason exactly. Every live change is matched by the same
   change to the recipe's reason='original' baseline inside one transaction, so the recipe's "your
   changes" set is byte-identical before and after.

⚠️ THE BASELINE IS PATCHED SURGICALLY. 16 of the 300 recipes have drifted on purpose and
   substituting live's rows wholesale would erase the annotations that drift represents.

Usage:  apply_label_rules.py <db> [--apply]      (default is a dry run)
"""
import argparse
import csv
import json
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import snapshot_serialize                                        # noqa: E402
from import_cleanup import (SECTION, SUBHEADING, _ALTERNATIVE,   # noqa: E402
                            capitalize_first_visible, label_level,
                            move_link_out_of_label, split_lead_label)

REPAIRS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "data-repairs"
DECISIONS_CSV = REPAIRS / "round-a-fix-decisions-2026-10-01.csv"
LIFT_CSVS = (REPAIRS / "step-leadin-labels-2026-09-30.csv",
             REPAIRS / "step-dash-labels-2026-09-30.csv")


def _baseline(c, rid):
    row = c.execute("SELECT content FROM recipe_snapshots WHERE recipe_id=? AND reason='original'",
                    (rid,)).fetchone()
    return json.loads(row["content"]) if row else None


def _write_baseline(c, rid, body):
    c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? AND reason='original'",
              (json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")), rid))


def _renumber(rows):
    for i, r in enumerate(rows):
        r["position"] = i
    return rows


def _live_steps(c, rid):
    return [dict(r) for r in c.execute(
        "SELECT id, position, is_heading, heading_level, text FROM recipe_steps WHERE recipe_id=? "
        "ORDER BY position, id", (rid,))]


def _decisions():
    with open(DECISIONS_CSV) as f:
        return list(csv.DictReader(f))


def _lift_targets():
    """The step ids a label was lifted OFF, from the decision CSVs. Rule 6's scope."""
    ids = set()
    for path in LIFT_CSVS:
        with open(path) as f:
            for r in csv.DictReader(f):
                if (r.get("DECISION_make_heading_yes_no") or "").strip().lower() == "yes":
                    ids.add(int(r["step_row_id"]))
    return ids


def _set_text(c, body, sid, text):
    """Write one step's text to the live row and the baseline row together."""
    c.execute("UPDATE recipe_steps SET text=? WHERE id=?", (text, sid))
    for s in body.get("steps") or []:
        if s.get("id") == sid:
            s["text"] = text
            return True
    return False


def _set_level(c, body, sid, level):
    c.execute("UPDATE recipe_steps SET heading_level=? WHERE id=?", (level, sid))
    for s in body.get("steps") or []:
        if s.get("id") == sid:
            if level == SUBHEADING:
                s["heading_level"] = SUBHEADING
            else:
                s.pop("heading_level", None)        # level 1 carries no key (migration 059)
            return True
    return False


def run(db, apply_it):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    log = {"promote": [], "numlabel": [], "link": [], "capital": [], "alternatives": [],
           "restored": [], "removed": [], "flagged": [], "skipped": []}
    decisions = _decisions()
    lift_ids = set(_lift_targets())

    # ---- rule 7: a lifted label that names a section becomes one --------------------------------
    for row in [dict(x) for x in c.execute(
            "SELECT id, recipe_id, text FROM recipe_steps WHERE is_heading=1 AND heading_level=2 "
            "ORDER BY recipe_id, position")]:
        if label_level(row["text"]) != SECTION:
            continue
        body = _baseline(c, row["recipe_id"])
        if body is None or not _set_level(c, body, row["id"], SECTION):
            log["skipped"].append((row["recipe_id"], row["id"], "rule 7: not in the baseline"))
            continue
        _write_baseline(c, row["recipe_id"], body)
        log["promote"].append((row["recipe_id"], row["id"], row["text"]))

    # ---- rules 4 and 5: lift a label still sitting in a step ------------------------------------
    # Rule 4 finds number-led labels by rule. Rule 5's one case is a recorded decision, because the
    # label carries a link and Andy decided it is a heading.
    forced = {int(d["step_row_id"]): d for d in decisions
              if d["action"] == "lift_with_link_moved" and d["step_row_id"]}
    for row in [dict(x) for x in c.execute(
            "SELECT id, recipe_id, position, text FROM recipe_steps WHERE is_heading=0 "
            "ORDER BY recipe_id, position")]:
        sid, rid = row["id"], row["recipe_id"]
        d = forced.get(sid)
        parts = split_lead_label(row["text"], d["value"] if d else None)
        if isinstance(parts, str):
            if d:
                log["skipped"].append((rid, sid, f"rule 5: {parts}"))
            continue
        label, rest = parts
        if not d and not any(ch.isdigit() for ch in label.split()[0] if label.split()):
            continue                                   # rule 4 is the NUMBER-led case only
        label, rest, moved = move_link_out_of_label(label, rest)
        if not moved and "[[" in (row["text"] or ""):
            log["flagged"].append((rid, sid, f"link lost from label {label!r}, needs re-linking"))
        rest = capitalize_first_visible(rest)
        body = _baseline(c, rid)
        steps = (body or {}).get("steps") or []
        bi = next((i for i, s in enumerate(steps) if s.get("id") == sid), None)
        if bi is None:
            log["skipped"].append((rid, sid, "lift: not in the baseline"))
            continue
        level = label_level(label)
        rows = _live_steps(c, rid)
        at = next(i for i, s in enumerate(rows) if s["id"] == sid)
        cur = c.execute("INSERT INTO recipe_steps (recipe_id, position, is_heading, heading_level, "
                        "text) VALUES (?,?,1,?,?)", (rid, -1, level, label))
        new_id = cur.lastrowid
        rows.insert(at, {"id": new_id, "position": -1, "is_heading": 1,
                         "heading_level": level, "text": label})
        rows[at + 1]["text"] = rest
        for s in _renumber(rows):
            c.execute("UPDATE recipe_steps SET position=?, text=? WHERE id=?",
                      (s["position"], s["text"], s["id"]))
        blank = {k: None for k in snapshot_serialize.SNAPSHOT_STEP_FIELDS}
        blank.update({"id": new_id, "is_heading": 1, "text": label})
        if level == SUBHEADING:
            blank["heading_level"] = SUBHEADING
        steps.insert(bi, blank)
        steps[bi + 1]["text"] = rest
        body["steps"] = _renumber(steps)
        _write_baseline(c, rid, body)
        lift_ids.add(sid)
        (log["link"] if d else log["numlabel"]).append((rid, sid, new_id, label, rest[:52]))

    # ---- rule 6: the step a label was lifted off starts with a capital --------------------------
    # ⚠️ LIFT TARGETS ONLY. A step that merely sits under a heading may start lowercase because its
    #    author wrote it that way: karak-chai's "a. Bring the pot to a boil" is a sub-list marker
    #    under the author's own heading, and capitalizing it would rewrite their list.
    for sid in sorted(lift_ids):
        row = c.execute("SELECT id, recipe_id, text, is_heading FROM recipe_steps WHERE id=?",
                        (sid,)).fetchone()
        if row is None or row["is_heading"]:
            continue
        new = capitalize_first_visible(row["text"])
        if new == row["text"]:
            continue
        body = _baseline(c, row["recipe_id"])
        if body is None or not _set_text(c, body, sid, new):
            log["skipped"].append((row["recipe_id"], sid, "rule 6: not in the baseline"))
            continue
        _write_baseline(c, row["recipe_id"], body)
        log["capital"].append((row["recipe_id"], sid, row["text"][:40], new[:40]))

    # ---- rule 8: alternatives, and an author heading restored from the source -------------------
    for rid in [r[0] for r in c.execute("SELECT DISTINCT recipe_id FROM recipe_steps ORDER BY recipe_id")]:
        rows = _live_steps(c, rid)
        for i, r in enumerate(rows):
            if not (r["is_heading"] and r["heading_level"] == SECTION):
                continue
            if not (i + 1 < len(rows) and rows[i + 1]["is_heading"]
                    and _ALTERNATIVE.match(rows[i + 1]["text"] or "")):
                continue
            hits, j = [], i + 1
            while j < len(rows):
                if rows[j]["is_heading"]:
                    if rows[j]["heading_level"] == SECTION and not _ALTERNATIVE.match(rows[j]["text"] or ""):
                        break
                    if _ALTERNATIVE.match(rows[j]["text"] or ""):
                        hits.append(rows[j])
                j += 1
            if len(hits) < 2:
                continue
            body = _baseline(c, rid)
            if body is None:
                log["skipped"].append((rid, None, "rule 8: no baseline"))
                continue
            for h in hits:
                if h["heading_level"] != SUBHEADING:
                    _set_level(c, body, h["id"], SUBHEADING)
            _write_baseline(c, rid, body)
            log["alternatives"].append((rid, r["text"], [h["text"] for h in hits]))

    # a heading the author wrote and the import lost, restored where the decisions CSV says
    for d in decisions:
        if d["action"] != "insert_section_before" or not d["step_row_id"]:
            continue
        rid, before, title = d["recipe_id"], int(d["step_row_id"]), d["value"]
        rows = _live_steps(c, rid)
        at = next((i for i, s in enumerate(rows) if s["id"] == before), None)
        if at is None:
            log["skipped"].append((rid, before, "rule 8: the step named is not there"))
            continue
        if at and rows[at - 1]["is_heading"]:
            log["skipped"].append((rid, before, "rule 8: already has a heading above it"))
            continue
        body = _baseline(c, rid)
        steps = (body or {}).get("steps") or []
        bi = next((i for i, s in enumerate(steps) if s.get("id") == before), None)
        if bi is None:
            log["skipped"].append((rid, before, "rule 8: not in the baseline"))
            continue
        cur = c.execute("INSERT INTO recipe_steps (recipe_id, position, is_heading, heading_level, "
                        "text) VALUES (?,?,1,?,?)", (rid, -1, SECTION, title))
        new_id = cur.lastrowid
        rows.insert(at, {"id": new_id, "position": -1, "is_heading": 1,
                         "heading_level": SECTION, "text": title})
        for s in _renumber(rows):
            c.execute("UPDATE recipe_steps SET position=? WHERE id=?", (s["position"], s["id"]))
        blank = {k: None for k in snapshot_serialize.SNAPSHOT_STEP_FIELDS}
        blank.update({"id": new_id, "is_heading": 1, "text": title})
        steps.insert(bi, blank)
        body["steps"] = _renumber(steps)
        _write_baseline(c, rid, body)
        log["restored"].append((rid, new_id, title, d["source_of_decision"]))

    # ---- recorded decision: a heading a person asked to remove ----------------------------------
    for d in decisions:
        if d["action"] != "remove_heading" or not d["step_row_id"]:
            continue
        rid, sid = d["recipe_id"], int(d["step_row_id"])
        row = c.execute("SELECT is_heading, text FROM recipe_steps WHERE id=? AND recipe_id=?",
                        (sid, rid)).fetchone()
        if row is None:
            continue
        if not row["is_heading"]:
            log["skipped"].append((rid, sid, "remove_heading: not a heading"))
            continue
        linked = c.execute("SELECT id FROM recipe_waits WHERE step_id=? OR alongside_step_id=? "
                           "OR ext_step_id=?", (sid, sid, sid)).fetchone()
        if linked:
            log["skipped"].append((rid, sid, "remove_heading: a wait points at it"))
            continue
        body = _baseline(c, rid)
        steps = (body or {}).get("steps") or []
        bi = next((i for i, s in enumerate(steps) if s.get("id") == sid), None)
        c.execute("DELETE FROM recipe_steps WHERE id=?", (sid,))
        for s in _renumber(_live_steps(c, rid)):
            c.execute("UPDATE recipe_steps SET position=? WHERE id=?", (s["position"], s["id"]))
        if bi is not None:
            steps.pop(bi)
            body["steps"] = _renumber(steps)
            _write_baseline(c, rid, body)
        log["removed"].append((rid, sid, row["text"]))

    # ---- rule 5, corpus-wide: NO HEADING CARRIES LINK MARKUP -----------------------------------
    # ⚠️ THE INVARIANT, NOT A LIST OF ROWS. app.js renderStepRow escapes a heading and never
    #    linkifies it, so "[[spinach]]" in a heading prints the brackets. That is true of every
    #    heading in the corpus however it got there, so this reads the headings rather than a
    #    decision CSV: convert_step_headings._lift and import_cleanup.plan_step_rows both apply
    #    move_link_out_of_label when they make a heading, and this is what catches one they did
    #    not make. It found bulgogi-bowls' "Wilt the [[spinach]]" on the first clean run of the
    #    whole chain, which is the run that matters, since a repair keyed on a step row id cannot
    #    see a label that an earlier pass has already lifted.
    #    The link goes to the step BELOW, which is the step the label was lifted off.
    for row in [dict(x) for x in c.execute(
            "SELECT id, recipe_id, position, text FROM recipe_steps "
            "WHERE is_heading=1 AND text LIKE '%[[%' ORDER BY recipe_id, position")]:
        rid, hid = row["recipe_id"], row["id"]
        below = c.execute("SELECT id, text FROM recipe_steps WHERE recipe_id=? AND position=? "
                          "AND is_heading=0", (rid, row["position"] + 1)).fetchone()
        if below is None:
            log["flagged"].append((rid, hid, f"heading {row['text']!r} carries a link and has no "
                                             "step under it to move it to"))
            continue
        plain, rest, moved = move_link_out_of_label(row["text"], below["text"])
        if not moved:
            log["flagged"].append((rid, hid, f"link lost from heading {plain!r}, needs re-linking"))
        body = _baseline(c, rid)
        if body is None:
            log["skipped"].append((rid, hid, "heading link: no baseline"))
            continue
        _set_text(c, body, hid, plain)
        _set_text(c, body, below["id"], rest)
        _write_baseline(c, rid, body)
        log["link"].append((rid, below["id"], hid, plain, rest[:52]))

    for d in decisions:
        if d["action"] == "flag_only":
            log["flagged"].append((d["recipe_id"], None, d["NOTES"]))

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
    for key, title in (("promote", "7  lifted labels promoted to sections"),
                       ("numlabel", "4  number-led labels lifted"),
                       ("link", "5  labels lifted with their link moved"),
                       ("capital", "6  steps capitalized after a lift"),
                       ("alternatives", "8  alternative groups demoted"),
                       ("restored", "8  author headings restored"),
                       ("removed", "   headings removed by decision")):
        print(f"  {title:<42}: {len(log[key])}")
        for x in log[key]:
            print(f"        {x}")
    if log["flagged"]:
        print(f"  FLAGGED: {len(log['flagged'])}")
        for x in log["flagged"]:
            print(f"        {x}")
    if log["skipped"]:
        print(f"  SKIPPED: {len(log['skipped'])}")
        for x in log["skipped"]:
            print(f"        {x}")
    return log


if __name__ == "__main__":
    main()
