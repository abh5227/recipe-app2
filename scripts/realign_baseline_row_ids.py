#!/usr/bin/env python3.13
"""Put a recipe back in the byte-equal short-circuit when a save moved only its row ids.

⚠️ WHAT THIS REPAIRS, AND WHY IT IS A RULE RATHER THAN ONE ROW. `write_plan_ahead` used to delete
every wait and storage row of a recipe and insert fresh ones, so a save that changed NOTHING gave
each row a new AUTOINCREMENT id. `serialize_recipe_content` records the row id, so the recipe's
content stopped being byte-equal to its `reason='original'` baseline and dropped out of the
short-circuit for good. `snapshot_diff` compares by MEANING, so it reported 0 entries and the page
showed nothing, which is why this went unnoticed until the short-circuit count moved.

Observed on live 2026-10-01: brioche-bread's entire difference from its baseline was `"id": 12`
becoming `"id": 108` and `"id": 13` becoming `"id": 109`, with 0 annotation entries, and the
short-circuit went 275 of 300 to 274. The save path keeps row ids now, so nothing new can arrive
here, and this clears what the old path left behind.

⚠️ THE BASELINE MOVES AND THE LIVE ROWS DO NOT, which is the one case where that is right. Every
other pass patches both halves in lockstep because it CHANGES the live row. Here the live rows are
the truth, down to their ids, and the baseline is the half that went stale. Rewriting the live rows
to match a stale baseline would be inventing data.

⚠️ AND IT REFUSES ANY RECIPE WHERE ANYTHING ELSE DIFFERS. The abort is modelled on
scripts/applied/backfill_baseline_row_ids.py: strip every row id out of BOTH documents, re-serialize
with the same json options, and require them to match byte for byte. If they do not, the cook edited
something real and this script has no business touching that baseline. A recipe with genuine
annotations is skipped, reported, and left exactly as it is.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))             # for corpus_guard
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))      # for app
from corpus_guard import refuse_live, report_target                          # noqa: E402

CSV_NAME = "baseline-row-id-realign.csv"
ID_LISTS = ("ingredients", "steps", "waits", "storage")


def _bare(blob):
    """The document with every child row's id removed, re-serialized the way content_blob writes.
    Two recipes whose only difference is row ids produce the SAME string here."""
    doc = json.loads(blob)
    out = {k: v for k, v in doc.items()}
    for name in ID_LISTS:
        rows = doc.get(name)
        if rows is None:
            continue
        out[name] = [{k: v for k, v in r.items() if k != "id"} for r in rows]
    return json.dumps(out, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _with_ids_from(stored_blob, current_blob):
    """`stored_blob` rewritten so each child row carries the id the CURRENT row has, matched by
    position within its list. Position is the right key here precisely because everything except the
    ids has already been proved identical."""
    stored, current = json.loads(stored_blob), json.loads(current_blob)
    out = {k: v for k, v in stored.items()}
    for name in ID_LISTS:
        rows, live = stored.get(name), current.get(name)
        if rows is None or live is None or len(rows) != len(live):
            continue
        out[name] = [{**r, "id": l.get("id")} for r, l in zip(rows, live)]
    return json.dumps(out, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def run(db, apply=False, record=False):
    import app
    import models
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)

    fixable, already, skipped = [], [], []
    with app.orm_session() as s:
        rids = [r for (r,) in s.execute(sqlalchemy.text(
            "SELECT recipe_id FROM recipe_snapshots WHERE reason='original' ORDER BY recipe_id"))]
        for rid in rids:
            stored = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one()
            current = app.serialize_recipe_content(s, rid)
            if current == stored:
                already.append(rid)
                continue
            if _bare(stored) != _bare(current):
                entries = app.snapshot_diff.diff_snapshots(stored, current)
                skipped.append((rid, len(entries)))
                continue
            fixable.append((rid, stored, current))

    print(f"  already byte-equal              : {len(already)}")
    print(f"  differ only in row ids (fixable) : {len(fixable)}")
    print(f"  differ in something real (left)  : {len(skipped)}")
    for rid, n in skipped[:12]:
        print(f"      {rid}  ({n} annotation entries)")

    rows = []
    for rid, stored, current in fixable:
        a, b = json.loads(stored), json.loads(current)
        moved = []
        for name in ID_LISTS:
            for x, y in zip(a.get(name) or [], b.get(name) or []):
                if x.get("id") != y.get("id"):
                    moved.append(f"{name}:{x.get('id')}->{y.get('id')}")
        rows.append((rid, len(moved), "; ".join(moved[:8])))
        print(f"      {rid}: {len(moved)} id(s) {', '.join(moved[:6])}")

    if rows:
        target = report_target(CSV_NAME, record)
        import csv as _csv
        with open(target, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["recipe_id", "ids_moved", "detail"])
            w.writerows(rows)
        print(f"  report -> {target}")

    if not apply:
        print("  DRY RUN. Nothing written. Pass --apply to write.")
        return fixable

    for rid, stored, current in fixable:
        patched = _with_ids_from(stored, current)
        # ⚠️ THE ABORT, ARMED ON EVERY RECIPE, NOT JUST ON THE SURVEY. The patched baseline must now
        #    equal the current content byte for byte, which is the whole point of the repair, and
        #    stripping its ids must still reproduce what was stored. Either failing means this
        #    script got the shape wrong and it writes nothing at all.
        if patched != current:
            sys.exit(f"ABORT on {rid}: the patched baseline is not byte-equal to current content")
        if _bare(patched) != _bare(stored):
            sys.exit(f"ABORT on {rid}: patching changed something other than the row ids")
    with app.orm_session() as s:
        for rid, stored, current in fixable:
            s.execute(sqlalchemy.text(
                "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r AND reason='original'"),
                {"c": _with_ids_from(stored, current), "r": rid})
        s.commit()
    print(f"  WROTE {len(fixable)} baseline(s) -> {db}")

    with app.orm_session() as s:
        for rid, _stored, _current in fixable:
            cur = app.serialize_recipe_content(s, rid)
            got = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one()
            marks = app._recipe_annotations(s, rid)
            print(f"      {rid}: byte-equal={cur == got}  marks={len(marks)}")
            if cur != got or marks:
                sys.exit(f"ABORT after writing {rid}: byte-equal={cur == got} marks={len(marks)}")
    return fixable


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--record", action="store_true",
                    help="write the report into docs/data-repairs/ instead of reports/")
    ap.add_argument("--i-mean-live", action="store_true")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)
    run(a.db, apply=a.apply, record=a.record)


if __name__ == "__main__":
    main()
