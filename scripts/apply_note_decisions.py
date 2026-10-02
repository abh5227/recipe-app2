#!/usr/bin/env python3.13
"""apply_note_decisions.py - apply the recorded note decisions, in lockstep.

Reads docs/data-repairs/note-links-2026-10-01.json, which is COMMITTED because a pass that cannot
be re-run from a fresh clone is a hand edit with more steps.

Three kinds of decision, and one deliberate non-decision:
  - step_links       a note points at a step
  - step_references  a "step N" written in a note's own words resolves to a step id
  - waits            a plan-ahead wait the recipe described only in its notes
  - flagged_references  left unlinked on purpose, reported, never written

⚠️ LOCKSTEP, ONE TRANSACTION PER RECIPE. Every one of these changes a row the snapshot records, so
the reason='original' baseline moves with it or the cook is told they attached a link they never
touched. The gate is 0 new marks, and the script aborts on anything else.

⚠️ EACH ENTRY MUST AGREE ON THREE THINGS BEFORE ANYTHING IS WRITTEN: the recipe, the note's
position, and a fragment of its text. A note that has moved or been reworded stops the pass rather
than being silently mis-linked. The decision was made about a sentence, not about a slot.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from corpus_guard import refuse_live                                        # noqa: E402

DECISIONS = (pathlib.Path(__file__).resolve().parent.parent
             / "docs" / "data-repairs" / "note-links-2026-10-01.json")


def _note(s, sqlalchemy, entry):
    """The one note row an entry names, or an explanation of why it names none."""
    row = s.execute(sqlalchemy.text(
        "SELECT id, text FROM recipe_notes WHERE recipe_id=:r AND position=:p"),
        {"r": entry["recipe_id"], "p": entry["note_position"]}).mappings().first()
    if row is None:
        return None, f"no note at position {entry['note_position']}"
    if entry["text_fragment"] not in row["text"]:
        return None, (f"the note at position {entry['note_position']} does not contain "
                      f"{entry['text_fragment']!r}")
    return row, None


def run(db, apply=False):
    import app
    import models
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)
    plan = json.loads(DECISIONS.read_text())

    todo, refused = [], []
    with app.orm_session() as s:
        for entry in plan["step_links"]:
            row, why = _note(s, sqlalchemy, entry)
            (refused if row is None else todo).append(
                (entry["recipe_id"], "link", entry, row, why))
        for entry in plan["step_references"]:
            row, why = _note(s, sqlalchemy, entry)
            (refused if row is None else todo).append(
                (entry["recipe_id"], "ref", entry, row, why))
        for entry in plan["waits"]:
            todo.append((entry["recipe_id"], "wait", entry, None, None))

    print(f"  decisions to apply        : {len(todo)}")
    for rid, what, entry, row, _why in todo:
        detail = entry.get("text_fragment") or entry.get("label")
        print(f"      {what:5s} {rid:46s} {str(detail)[:44]}")
    print(f"  refused (the note moved)  : {len(refused)}")
    for rid, _w, _e, _r, why in refused:
        print(f"      {rid}: {why}")
    print(f"  flagged, left unlinked    : {len(plan['flagged_references'])}")
    for f in plan["flagged_references"]:
        print(f"      {f['recipe_id']}: {f['text_fragment']!r}")

    if refused:
        sys.exit("ABORT: a recorded decision no longer matches the note it was made about.")
    if not apply:
        print("  DRY RUN. Nothing written. Pass --apply to write.")
        return todo

    touched = sorted({rid for rid, *_ in todo})
    before = {}
    with app.orm_session() as s:
        for rid in touched:
            before[rid] = len(app._recipe_annotations(s, rid))

    for rid in touched:
        with app.orm_session() as s:
            for _rid, what, entry, row, _why in [t for t in todo if t[0] == rid]:
                if what == "link":
                    s.execute(sqlalchemy.text(
                        "UPDATE recipe_notes SET step_id=:sid WHERE id=:nid"),
                        {"sid": entry["step_id"], "nid": row["id"]})
                elif what == "ref":
                    # the mention must still be in the text, and at the ordinal recorded
                    import notes as notes_rules
                    mentions = notes_rules.scan_step_mentions(row["text"])
                    m = next((x for x in mentions if x["ref_index"] == entry["ref_index"]), None)
                    if m is None:
                        sys.exit(f"ABORT on {rid}: no step mention at ref_index "
                                 f"{entry['ref_index']}")
                    s.execute(sqlalchemy.text(
                        "INSERT INTO recipe_note_step_refs (note_id, ref_index, match_text, step_id) "
                        "VALUES (:n, :i, :m, :s)"),
                        {"n": row["id"], "i": m["ref_index"], "m": m["match_text"],
                         "s": entry["step_id"]})
                elif what == "wait":
                    s.execute(sqlalchemy.text(
                        "INSERT INTO recipe_waits (recipe_id, position, kind, label, min_minutes, "
                        "max_minutes, ext_label, ext_min_minutes, ext_max_minutes, when_kind, "
                        "when_label, step_id) VALUES (:r, :p, :k, :l, :lo, :hi, :el, :elo, :ehi, "
                        ":wk, :wl, :sid)"),
                        {"r": entry["recipe_id"], "p": entry["position"], "k": entry["kind"],
                         "l": entry["label"], "lo": entry["min_minutes"],
                         "hi": entry["max_minutes"], "el": entry["ext_label"],
                         "elo": entry["ext_min_minutes"], "ehi": entry["ext_max_minutes"],
                         "wk": entry["when_kind"], "wl": entry["when_label"],
                         "sid": entry["step_id"]})
            # ⚠️ THE OTHER HALF, IN THE SAME TRANSACTION. The baseline is rewritten to the recipe's
            #    content as it now stands, which is correct HERE and nowhere else: every change this
            #    pass makes is a machine repair, so the recipe was always meant to read this way and
            #    the cook has changed nothing. The abort below is what proves it.
            s.execute(sqlalchemy.text(
                "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r AND reason='original'"),
                {"c": app.serialize_recipe_content(s, rid), "r": rid})
            s.commit()

    bad = []
    with app.orm_session() as s:
        for rid in touched:
            now = len(app._recipe_annotations(s, rid))
            if now != before[rid]:
                bad.append((rid, before[rid], now))
    if bad:
        sys.exit(f"ABORT: {len(bad)} recipe(s) changed their mark count: {bad}")
    print(f"  WROTE {len(todo)} decision(s) over {len(touched)} recipe(s) -> {db}")
    print(f"  no recipe's mark count moved")
    return todo


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--i-mean-live", action="store_true")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)
    run(a.db, apply=a.apply)


if __name__ == "__main__":
    main()
