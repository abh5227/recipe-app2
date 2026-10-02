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

⚠️ THE BASELINE IS PATCHED SURGICALLY, ONE ENTRY AT A TIME, NEVER REBUILT. It rebuilt the whole
baseline from current content, and the review proved what that costs: kfc-spicy-chicken-rice-bowl
with one real cook edit to a step came out of this pass with that edit absorbed into the baseline
and its mark gone, because a rebuild declares the recipe born in its edited state. 20 recipes carry
49 entries between them, and one recorded decision on any of them would have erased the lot.
Only the inserted wait's entry moves, read back from the live row. The note links and the step
references need no baseline at all now that notes are a playground, which is Andy's ruling: a note
mints no mark and editing one costs a recipe nothing.

⚠️ AND THE GATE RUNS BEFORE THE COMMIT, NOT AFTER IT. It was a post-mortem: the writes committed
per recipe and the mark check ran at the end, so the abort printed a verdict on data that was
already on disk and half the decision file could be applied with no record of where it stopped.
Each recipe's transaction now proves itself and rolls back if it cannot.

⚠️ AND A SECOND RUN IS A NO-OP, NOT AN IntegrityError. Both writes were bare INSERTs into tables
carrying UNIQUE (note_id, ref_index) and UNIQUE (recipe_id, position), so re-running the pass on an
applied database died mid-way with earlier recipes already committed, and the dry run showed
nothing wrong beforehand. An entry already in place is detected in the planning phase and reported
as a no-op, which is what makes the dry run a faithful preview of the real run.
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
        "SELECT id, text, step_id FROM recipe_notes WHERE recipe_id=:r AND position=:p"),
        {"r": entry["recipe_id"], "p": entry["note_position"]}).mappings().first()
    if row is None:
        return None, f"no note at position {entry['note_position']}"
    if entry["text_fragment"] not in row["text"]:
        return None, (f"the note at position {entry['note_position']} does not contain "
                      f"{entry['text_fragment']!r}")
    return row, None


def _state(s, sqlalchemy, app, rid):
    """What the gate is stated against: this recipe's annotation ENTRIES and whether it is
    byte-equal to its baseline.

    ⚠️ THE ENTRIES, NOT THEIR COUNT. One entry leaving while another joins holds the count still,
    which is the kind of thing a pass should have to explain."""
    cur = app.serialize_recipe_content(s, rid)
    got = s.execute(sqlalchemy.text(
        "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
        {"r": rid}).scalar_one_or_none()
    return {"byte_equal": got is not None and cur == got,
            "marks": json.dumps(app._recipe_annotations(s, rid), sort_keys=True)}


def _patch_wait(doc, s, sqlalchemy, snapshot_serialize, wait_id):
    """Add exactly the one wait entry this pass inserted, in the serializer's own order."""
    row = s.execute(sqlalchemy.text(
        "SELECT * FROM recipe_waits WHERE id=:w"), {"w": wait_id}).mappings().first()
    doc.setdefault("waits", []).append(
        {k: row[k] for k in snapshot_serialize.SNAPSHOT_WAIT_FIELDS})
    doc["waits"].sort(key=lambda e: (e.get("position") or 0, e.get("id") or 0))


def run(db, apply=False):
    import app
    import models
    import notes as notes_rules
    import snapshot_serialize
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)
    plan = json.loads(DECISIONS.read_text())

    todo, refused, done = [], [], []
    with app.orm_session() as s:
        for entry in plan["step_links"]:
            row, why = _note(s, sqlalchemy, entry)
            if row is None:
                refused.append((entry["recipe_id"], why))
            elif row["step_id"] == entry["step_id"]:
                done.append((entry["recipe_id"], "link", "already points at that step"))
            else:
                todo.append((entry["recipe_id"], "link", entry, row))
        for entry in plan["step_references"]:
            row, why = _note(s, sqlalchemy, entry)
            if row is None:
                refused.append((entry["recipe_id"], why))
                continue
            got = s.execute(sqlalchemy.text(
                "SELECT step_id FROM recipe_note_step_refs WHERE note_id=:n AND ref_index=:i"),
                {"n": row["id"], "i": entry["ref_index"]}).mappings().first()
            if got is None:
                todo.append((entry["recipe_id"], "ref", entry, row))
            elif got["step_id"] == entry["step_id"]:
                done.append((entry["recipe_id"], "ref", "that mention already resolves there"))
            else:
                refused.append((entry["recipe_id"],
                                f"mention {entry['ref_index']} already resolves to step id "
                                f"{got['step_id']}, not {entry['step_id']}"))
        for entry in plan["waits"]:
            got = s.execute(sqlalchemy.text(
                "SELECT id, position FROM recipe_waits WHERE recipe_id=:r AND label=:l"),
                {"r": entry["recipe_id"], "l": entry["label"]}).mappings().first()
            if got is not None:
                done.append((entry["recipe_id"], "wait", "that wait is already on the recipe"))
                continue
            # ⚠️ THE RECORDED POSITION HAS TO BE FREE. recipe_waits carries
            #    UNIQUE (recipe_id, position), so a slot taken by some other wait is an abort the
            #    dry run should show, not an IntegrityError half way through the write.
            taken = s.execute(sqlalchemy.text(
                "SELECT label FROM recipe_waits WHERE recipe_id=:r AND position=:p"),
                {"r": entry["recipe_id"], "p": entry["position"]}).scalar_one_or_none()
            if taken is not None:
                refused.append((entry["recipe_id"], f"position {entry['position']} is taken by "
                                                    f"{taken!r}"))
                continue
            todo.append((entry["recipe_id"], "wait", entry, None))

    print(f"  decisions to apply        : {len(todo)}")
    for rid, what, entry, _row in todo:
        detail = entry.get("text_fragment") or entry.get("label")
        print(f"      {what:5s} {rid:46s} {str(detail)[:44]}")
    print(f"  already applied (no-op)   : {len(done)}")
    for rid, what, why in done:
        print(f"      {what:5s} {rid:46s} {why}")
    print(f"  refused (the note moved)  : {len(refused)}")
    for rid, why in refused:
        print(f"      {rid}: {why}")
    print(f"  flagged, left unlinked    : {len(plan['flagged_references'])}")
    for f in plan["flagged_references"]:
        print(f"      {f['recipe_id']}: {f['text_fragment']!r}")

    if refused:
        sys.exit("ABORT: a recorded decision no longer matches the note it was made about.")
    if not apply:
        print("  DRY RUN. Nothing written. Pass --apply to write.")
        return todo
    if not todo:
        print("  nothing to do. Every decision is already in place.")
        return todo

    touched = sorted({rid for rid, *_ in todo})
    before = {}
    with app.orm_session() as s:
        for rid in touched:
            before[rid] = _state(s, sqlalchemy, app, rid)

    for rid in touched:
        with app.orm_session() as s:
            stored = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            doc = json.loads(stored) if stored is not None else None
            for _rid, what, entry, row in [t for t in todo if t[0] == rid]:
                if what == "link":
                    s.execute(sqlalchemy.text(
                        "UPDATE recipe_notes SET step_id=:sid WHERE id=:nid"),
                        {"sid": entry["step_id"], "nid": row["id"]})
                elif what == "ref":
                    # the mention must still be in the text, and at the ordinal recorded
                    mentions = notes_rules.scan_step_mentions(row["text"])
                    m = next((x for x in mentions if x["ref_index"] == entry["ref_index"]), None)
                    if m is None:
                        s.rollback()
                        sys.exit(f"ABORT on {rid}: no step mention at ref_index "
                                 f"{entry['ref_index']}")
                    s.execute(sqlalchemy.text(
                        "INSERT INTO recipe_note_step_refs (note_id, ref_index, match_text, step_id) "
                        "VALUES (:n, :i, :m, :s)"),
                        {"n": row["id"], "i": m["ref_index"], "m": m["match_text"],
                         "s": entry["step_id"]})
                elif what == "wait":
                    wid = s.execute(sqlalchemy.text(
                        "INSERT INTO recipe_waits (recipe_id, position, kind, label, min_minutes, "
                        "max_minutes, ext_label, ext_min_minutes, ext_max_minutes, when_kind, "
                        "when_label, step_id) VALUES (:r, :p, :k, :l, :lo, :hi, :el, :elo, :ehi, "
                        ":wk, :wl, :sid) RETURNING id"),
                        {"r": entry["recipe_id"], "p": entry["position"], "k": entry["kind"],
                         "l": entry["label"], "lo": entry["min_minutes"],
                         "hi": entry["max_minutes"], "el": entry["ext_label"],
                         "elo": entry["ext_min_minutes"], "ehi": entry["ext_max_minutes"],
                         "wk": entry["when_kind"], "wl": entry["when_label"],
                         "sid": entry["step_id"]}).scalar_one()
                # ⚠️ ONLY THE WAIT NEEDS THE OTHER HALF NOW. A note link and a step reference are
                #    not in recipe_snapshots.content at all since notes became a playground, so
                #    there is nothing to patch for them and nothing they can mark. A wait is still
                #    content, so its entry moves in the same transaction as the row.
                if doc is not None and what == "wait":
                    _patch_wait(doc, s, sqlalchemy, snapshot_serialize, wid)
            if doc is not None:
                s.execute(sqlalchemy.text(
                    "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r "
                    "AND reason='original'"),
                    {"c": json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")), "r": rid})
            # ⚠️ PROVE IT BEFORE COMMITTING, inside the same transaction, against the state read
            #    before this run wrote anything.
            now = _state(s, sqlalchemy, app, rid)
            if now["marks"] != before[rid]["marks"]:
                s.rollback()
                sys.exit(f"ABORT on {rid}: the annotation set moved, so nothing was written. "
                         f"before={before[rid]['marks'][:200]} after={now['marks'][:200]}")
            if before[rid]["byte_equal"] and not now["byte_equal"]:
                s.rollback()
                sys.exit(f"ABORT on {rid}: it left the byte-equal set, so nothing was written.")
            s.commit()

    print(f"  WROTE {len(todo)} decision(s) over {len(touched)} recipe(s) -> {db}")
    print(f"  no recipe's annotation set moved and none left the byte-equal set")
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
