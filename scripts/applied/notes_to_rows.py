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

⚠️ AND THE NOTES LEAVE THE BASELINE ALTOGETHER, WHICH IS WHY THIS PASS TOUCHES ALL 300 AND NOT 95.
Andy's ruling: notes are a playground. They mint no "your changes" entry and editing one must not
cost a recipe its place in the byte-equal set, so neither the rows nor the derived column are in
recipe_snapshots.content any more. Every one of the 300 stored baselines still carries
`recipe.notes` from before that ruling, so the key is stripped here, in the same transaction as the
rows, and the recipe stays byte-equal to its own baseline throughout.

⚠️ AND THE AUTHOR'S WORDS ARE RECORDED BEFORE ANYTHING CHANGES THEM. recipe_notes_original
(migration 061) is written once per recipe from the column as it is read, so a future "restore the
original notes" has something to restore from. Nothing compares it and nothing shows it.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from corpus_guard import refuse_live, report_target                          # noqa: E402

CSV_NAME = "notes-to-rows.csv"


# ⚠️ THE DERIVED-COPY RULE, KEPT HERE FOR THE RECORD. notes.derived_text was the shared version
# while recipes.notes still existed. Migration 063 dropped the column, so the rule left notes.py
# with it and this copy is what the pass below was actually run with.
def _field(row, name):
    """One field off a dict OR an ORM row, absent reading as None."""
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def derived_text(rows, separator="\n\n"):
    """The note rows -> the text recipes.notes held while the column was retired but not dropped.

    ⚠️ A TITLE IS PUT BACK ON THE FRONT, BECAUSE THE TITLES ROUND TOOK IT OUT OF THE TEXT. Reading
    only `text` made one unrelated note edit silently drop the title words from the copy the
    previous deploy served: brioche-bread's column would have lost "Flour" and "Kneading by hand".
    """
    out = []
    for r in rows:
        text = (_field(r, "text") or "").strip()
        title = (_field(r, "title") or "").strip()
        out.append(f"{title}. {text}" if title else text)
    return separator.join(out)


def strip_notes(doc):
    """Take both notes keys out of a stored baseline, in place. The other half of the lockstep.

    ⚠️ A NAMED RULE RATHER THAN TWO INLINE CALLS, so the gate below can be tested by taking it away.
    content_blob stopped emitting either key when notes became a playground, so a baseline that
    keeps one disagrees with the serializer for good and the recipe never reads as untouched
    again."""
    doc.pop("notes", None)
    (doc.get("recipe") or {}).pop("notes", None)
    return doc


def run(db, apply=False, record=False):
    import app
    import models
    import notes as notes_rules
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)

    planned, skipped, strip_only = [], [], []
    with app.orm_session() as s:
        rows = s.execute(sqlalchemy.text(
            "SELECT id, notes FROM recipes WHERE notes IS NOT NULL AND notes != '' ORDER BY id")).all()
        # ⚠️ EVERY RECIPE WHOSE BASELINE STILL NAMES notes, not just the ones with notes to move.
        #    The key was in all 300 baselines before notes became a playground, and a baseline that
        #    keeps it disagrees with the new serializer forever.
        for (rid,) in s.execute(sqlalchemy.text(
                "SELECT recipe_id FROM recipe_snapshots WHERE reason='original' "
                "AND content LIKE '%\"notes\":%' ORDER BY recipe_id")).all():
            strip_only.append(rid)
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
    touched = sorted({rid for rid, _p in planned} | set(strip_only))
    before_state = {}
    with app.orm_session() as s:
        for rid in touched:
            cur = app.serialize_recipe_content(s, rid)
            got = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            # ⚠️ THE ENTRIES, NOT THEIR COUNT. One entry leaving while another joins holds the
            #    count still, and that is exactly the kind of thing a pass should have to explain.
            before_state[rid] = {"byte_equal": got is not None and cur == got,
                                 "marks": json.dumps(app._recipe_annotations(s, rid),
                                                     sort_keys=True)}
    print(f"  baselines to strip        : {len(strip_only)}")
    print(f"  before this run           : {sum(1 for v in before_state.values() if v['byte_equal'])}"
          f" of {len(touched)} byte-equal, "
          f"{sum(len(json.loads(v['marks'])) for v in before_state.values())} mark(s) between them")

    moves = dict(planned)
    written = 0
    for rid in touched:
        paras = moves.get(rid) or []
        with app.orm_session() as s:
            stored = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            # the rows, and the record of what the author wrote, taken before anything changes it
            for i, (p, k) in enumerate(paras):
                s.execute(sqlalchemy.text(
                    "INSERT INTO recipe_notes (recipe_id, position, kind, text) "
                    "VALUES (:r, :p, :k, :t)"), {"r": rid, "p": i, "k": k, "t": p})
                s.execute(sqlalchemy.text(
                    "INSERT INTO recipe_notes_original (recipe_id, position, kind, text, "
                    "recorded_at) VALUES (:r, :p, :k, :t, :w) "
                    "ON CONFLICT (recipe_id, position) DO NOTHING"),
                    {"r": rid, "p": i, "k": k, "t": p, "w": app.now_utc()})
            if paras:
                s.execute(sqlalchemy.text("UPDATE recipes SET notes=:n WHERE id=:r"),
                          {"n": derived_text([{"text": p} for p, _k in paras]),
                           "r": rid})
            # ⚠️ THE OTHER HALF, IN THE SAME TRANSACTION, AND IT STRIPS RATHER THAN ADDS. Notes are
            #    a playground, so the baseline holds neither the rows nor the derived column. Both
            #    keys go, and nothing else in the document is touched.
            if stored is not None:
                doc = strip_notes(json.loads(stored))
                s.execute(sqlalchemy.text(
                    "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r AND reason='original'"),
                    {"c": json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")), "r": rid})
            # ⚠️ PROVE THIS RECIPE BEFORE COMMITTING IT. The gate used to run after every recipe
            #    had committed, which made it a post-mortem: a lockstep failure on recipe 40 left
            #    39 recipes written, the baseline half moved, and an abort message that read as
            #    though nothing had happened. Each recipe now proves itself inside its own
            #    transaction and rolls back if it cannot.
            cur_now = app.serialize_recipe_content(s, rid)
            got_now = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            marks_now = json.dumps(app._recipe_annotations(s, rid), sort_keys=True)
            if marks_now != before_state[rid]["marks"]:
                s.rollback()
                sys.exit(f"ABORT on {rid}: the annotation set moved, so nothing was written.")
            if before_state[rid]["byte_equal"] and not (got_now is not None
                                                        and cur_now == got_now):
                s.rollback()
                sys.exit(f"ABORT on {rid}: it left the byte-equal set, so nothing was written.")
            s.commit()
            written += len(paras)

    print(f"  WROTE {written} note row(s) over {len(planned)} recipe(s), stripped "
          f"{len(strip_only)} baseline(s) -> {db}")

    # ⚠️ THE ABORT COMPARES AGAINST THE BEFORE-STATE OF THIS RUN, NEVER AGAINST A FIXED EXPECTATION.
    #    It read "every moved recipe must be byte-equal afterwards", which is false for a reason that
    #    has nothing to do with this pass: 4 of the 95 carry real annotations and were never
    #    byte-equal. The question worth asking is whether this pass CHANGED anything, so what is
    #    recorded before the write is which recipes were byte-equal and what each one's marks were,
    #    and both have to come back the same.
    lost, changed = [], []
    with app.orm_session() as s:
        for rid in touched:
            cur = app.serialize_recipe_content(s, rid)
            got = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            equal_now = got is not None and cur == got
            if before_state[rid]["byte_equal"] and not equal_now:
                lost.append(rid)
            marks_now = json.dumps(app._recipe_annotations(s, rid), sort_keys=True)
            if marks_now != before_state[rid]["marks"]:
                changed.append((rid, len(json.loads(before_state[rid]["marks"])),
                                len(json.loads(marks_now))))
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
    # ⚠️ SPENT. See scripts/applied/_spent.py — this refuses rather than running. It moved live's
    #    177 note paragraphs over 95 recipes into recipe_notes rows, wrote recipe_notes_original,
    #    and stripped the `notes` key from all 300 stored baselines in lockstep, on 2026-10-04.
    #    Migration 063 then dropped recipes.notes, which was this pass's only input, so there is
    #    nothing left for it to read even if it were wanted.
    import pathlib as _pathlib
    import sys as _sys
    _sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
    from _spent import refuse_spent
    refuse_spent(__file__,
                 "moved recipes.notes into recipe_notes rows (177 paragraphs over 95 recipes), "
                 "wrote recipe_notes_original, and stripped the notes key from 300 baselines",
                 "2026-10-04")
