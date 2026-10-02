#!/usr/bin/env python3.13
"""notes_to_rows.py - move every recipe's notes out of the text column and into rows, in lockstep.

⚠️ FIX BY RULE, NOT BY ROW. The split is notes.paragraphs, which is the Python side of
static/note-blocks.js::noteParagraphs, and the kind is notes.kind_of, which delegates to
import_cleanup.note_kind reading static/note-kinds.json. The importer calls the same two functions,
so a note imported tomorrow is split the way the corpus was moved today. Nothing about either rule
is restated here.

⚠️ LOCKSTEP, IN ONE TRANSACTION PER RECIPE. The page's "your changes" is the diff between the
reason='original' baseline and the current rows, so writing rows without writing the baseline would
tell the cook they had added 177 notes they never touched. Both halves move together and the gate
below proves the annotation set did not change.

⚠️ THE BASELINE GETS THE LIVE ROW IDS, which is what keeps a byte-equal recipe byte-equal. The
snapshot records a note's id, so a baseline holding different ids would pair nothing by id and every
note would read as a change. Measured before writing this: all 95 baselines agree with live on the
notes text, so the rows the baseline describes ARE the rows live now holds.

⚠️ AND recipe.notes MOVES WITH THEM. The column is a derived copy from here on, rebuilt from the
rows, and 6 of the 95 see it renormalize (a four-newline gap, trailing whitespace). It is in the
snapshot, so the baseline's copy has to move too or those 6 stop being byte-equal for a reason
nobody could see on the page.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from corpus_guard import refuse_live, report_target                          # noqa: E402

CSV_NAME = "notes-to-rows.csv"


def run(db, apply=False, record=False):
    import app
    import models
    import notes as notes_rules
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)

    planned, skipped = [], []
    with app.orm_session() as s:
        rows = s.execute(sqlalchemy.text(
            "SELECT id, notes FROM recipes WHERE notes IS NOT NULL AND notes != '' ORDER BY id")).all()
        for rid, text in rows:
            existing = s.execute(sqlalchemy.text(
                "SELECT COUNT(*) FROM recipe_notes WHERE recipe_id=:r"), {"r": rid}).scalar_one()
            if existing:
                skipped.append((rid, f"already has {existing} note row(s)"))
                continue
            paras = notes_rules.paragraphs(text)
            if not paras:
                skipped.append((rid, "no paragraphs after the split"))
                continue
            planned.append((rid, [(p, notes_rules.kind_of(p)) for p in paras]))

    total = sum(len(p) for _rid, p in planned)
    print(f"  recipes with notes        : {len(rows)}")
    print(f"  recipes to move           : {len(planned)}")
    print(f"  note rows to write        : {total}")
    print(f"  skipped                   : {len(skipped)}")
    for rid, why in skipped[:10]:
        print(f"      {rid}: {why}")
    kinds = {}
    for _rid, paras in planned:
        for _p, k in paras:
            kinds[k] = kinds.get(k, 0) + 1
    print(f"  by kind                   : {dict(sorted(kinds.items()))}")

    if planned:
        target = report_target(CSV_NAME, record)
        import csv as _csv
        with open(target, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["recipe_id", "position", "kind", "text"])
            for rid, paras in planned:
                for i, (p, k) in enumerate(paras):
                    w.writerow([rid, i, k, p])
        print(f"  report -> {target}")

    if not apply:
        print("  DRY RUN. Nothing written. Pass --apply to write.")
        return planned

    # read BEFORE anything is written: which of these recipes were byte-equal, and how many marks
    # each one carried. The gate below is stated against this and against nothing else.
    before_state = {}
    with app.orm_session() as s:
        for rid, _paras in planned:
            cur = app.serialize_recipe_content(s, rid)
            got = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            before_state[rid] = {"byte_equal": got is not None and cur == got,
                                 "marks": len(app._recipe_annotations(s, rid))}
    print(f"  before this run           : {sum(1 for v in before_state.values() if v['byte_equal'])}"
          f" of {len(planned)} byte-equal, "
          f"{sum(v['marks'] for v in before_state.values())} mark(s) between them")

    import snapshot_serialize
    written = 0
    for rid, paras in planned:
        with app.orm_session() as s:
            stored = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            # the rows
            ids = []
            for i, (p, k) in enumerate(paras):
                ids.append(s.execute(sqlalchemy.text(
                    "INSERT INTO recipe_notes (recipe_id, position, kind, text) "
                    "VALUES (:r, :p, :k, :t) RETURNING id"),
                    {"r": rid, "p": i, "k": k, "t": p}).scalar_one())
            derived = notes_rules.derived_text([{"text": p} for p, _k in paras])
            s.execute(sqlalchemy.text("UPDATE recipes SET notes=:n WHERE id=:r"),
                      {"n": derived, "r": rid})
            # ⚠️ THE OTHER HALF, IN THE SAME TRANSACTION. Surgical: the baseline gains the notes key
            #    and its recipe.notes moves to the derived text, and nothing else in it is touched.
            if stored is not None:
                doc = json.loads(stored)
                doc["notes"] = [snapshot_serialize.snapshot_note_row(
                    {"id": ids[i], "position": i, "kind": k, "text": p,
                     "step_id": None, "ingredient_row_id": None})
                    for i, (p, k) in enumerate(paras)]
                (doc.setdefault("recipe", {}))["notes"] = derived
                s.execute(sqlalchemy.text(
                    "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r AND reason='original'"),
                    {"c": json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")), "r": rid})
            s.commit()
            written += len(paras)

    print(f"  WROTE {written} note row(s) over {len(planned)} recipe(s) -> {db}")

    # ⚠️ THE ABORT COMPARES AGAINST THE BEFORE-STATE OF THIS RUN, NEVER AGAINST A FIXED EXPECTATION.
    #    It read "every moved recipe must be byte-equal afterwards", which is false for a reason that
    #    has nothing to do with this pass: 4 of the 95 carry real annotations and were never
    #    byte-equal. The question worth asking is whether this pass CHANGED anything, so what is
    #    recorded before the write is which recipes were byte-equal and what each one's marks were,
    #    and both have to come back the same.
    lost, changed = [], []
    with app.orm_session() as s:
        for rid, _paras in planned:
            cur = app.serialize_recipe_content(s, rid)
            got = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            equal_now = got is not None and cur == got
            if before_state[rid]["byte_equal"] and not equal_now:
                lost.append(rid)
            marks_now = len(app._recipe_annotations(s, rid))
            if marks_now != before_state[rid]["marks"]:
                changed.append((rid, before_state[rid]["marks"], marks_now))
    if lost:
        sys.exit(f"ABORT: {len(lost)} recipe(s) left the byte-equal set: {lost[:8]}")
    if changed:
        sys.exit(f"ABORT: {len(changed)} recipe(s) changed their mark count: {changed[:8]}")
    print(f"  no recipe left the byte-equal set and no mark count moved")
    return planned


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
