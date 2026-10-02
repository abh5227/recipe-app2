#!/usr/bin/env python3.13
"""strip_author_step_numbers.py - take the author's own step numbers out, then re-run the label rules.

⚠️ THE APP PRINTS ITS OWN NUMBER IN A CIRCLE, so a step whose text still begins "1." shows the number
twice, and aloo-potato-parathas reads "① 1. MAKE THE DOUGH: ...". Worse, a lead-in label hiding
behind a number is invisible to the label rule, which is why seven of that recipe's steps kept an
ALL-CAPS title inside the step text instead of above it.

⚠️ ONE RULE SET, TWO CALLERS. The removal is import_cleanup.strip_author_numbers and the lift is
import_cleanup.split_lead_label, which is what plan_step_rows calls for an import. Nothing about
either rule is restated here.

⚠️ IT RUNS AFTER STEP-REFERENCE RESOLUTION, ON PURPOSE. A reference stores a step ID, so renumbering
or rewording cannot move it; but the resolution READS the author's numbering out of the step text to
find its target, and this pass is what deletes that evidence. Order matters once and only here.

⚠️ ALL OR NOTHING, PER RECIPE. A number comes off only where the recipe's steps carry a consecutive
run from 1 that agrees with their own ordinals, so a step reading "2 cups flour, sifted" in an
unnumbered recipe is never touched. See the measurement in import_cleanup.
"""
import argparse
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from corpus_guard import refuse_live, report_target                          # noqa: E402

CSV_NAME = "author-step-numbers.csv"


def plan(s, sqlalchemy, rid, cleanup):
    """What this recipe's step rows should become. None when nothing changes."""
    rows = [dict(r) for r in s.execute(sqlalchemy.text(
        "SELECT id, position, is_heading, heading_level, text FROM recipe_steps "
        "WHERE recipe_id=:r ORDER BY position"), {"r": rid}).mappings()]
    steps = [r for r in rows if not r["is_heading"]]
    stripped = cleanup.strip_author_numbers([r["text"] for r in steps])
    if stripped == [r["text"] for r in steps]:
        return None
    changes = []
    for r, new_text in zip(steps, stripped):
        if r["text"] == new_text:
            continue
        # now that the number is gone, a lead-in label may be visible for the first time
        lift = cleanup.split_lead_label(new_text)
        if isinstance(lift, tuple):
            label, rest = lift
            changes.append({"id": r["id"], "was": r["text"], "text": cleanup.capitalize_first_visible(rest),
                            # ⚠️ SENTENCE CASE ONLY WHERE THE AUTHOR SHOUTED. sentence_case is the
                            #    same rule the heading recasing already uses, and is_caps is what
                            #    says a heading was stored in capitals rather than written that way.
                            "heading": cleanup.sentence_case(label) if cleanup.is_caps(label) else label,
                            "level": cleanup.label_level(label)})
        else:
            changes.append({"id": r["id"], "was": r["text"], "text": new_text,
                            "heading": None, "level": None, "refusal": lift})
    return changes


def run(db, apply=False, record=False):
    import app
    import import_cleanup as cleanup
    import models
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)

    planned = []
    with app.orm_session() as s:
        rids = [r[0] for r in s.execute(sqlalchemy.text(
            "SELECT DISTINCT recipe_id FROM recipe_steps ORDER BY recipe_id")).all()]
        for rid in rids:
            ch = plan(s, sqlalchemy, rid, cleanup)
            if ch:
                planned.append((rid, ch))

    n_steps = sum(len(c) for _r, c in planned)
    n_head = sum(1 for _r, c in planned for x in c if x.get("heading"))
    print(f"  recipes carrying the author's numbering : {len(planned)}")
    print(f"  steps losing a number                   : {n_steps}")
    print(f"  of those, a label lifted into a heading : {n_head}")
    for rid, ch in planned:
        print(f"      {rid}")
        for x in ch:
            if x.get("heading"):
                print(f"          was : {x['was'][:78]}")
                print(f"          now : [{x['level']}] {x['heading']}  ||  {x['text'][:52]}")
            else:
                print(f"          was : {x['was'][:78]}")
                print(f"          now : {x['text'][:78]}")

    if planned:
        target = report_target(CSV_NAME, record)
        with open(target, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["recipe_id", "step_id", "was", "now", "heading_lifted", "heading_level"])
            for rid, ch in planned:
                for x in ch:
                    w.writerow([rid, x["id"], x["was"], x["text"], x.get("heading") or "",
                                x.get("level") or ""])
        print(f"  report -> {target}")

    if not apply:
        print("  DRY RUN. Nothing written. Pass --apply to write.")
        return planned

    before = {}
    with app.orm_session() as s:
        for rid, _ch in planned:
            before[rid] = len(app._recipe_annotations(s, rid))

    for rid, ch in planned:
        with app.orm_session() as s:
            for x in ch:
                s.execute(sqlalchemy.text("UPDATE recipe_steps SET text=:t WHERE id=:i"),
                          {"t": x["text"], "i": x["id"]})
            # a lifted label becomes a heading row ABOVE its step, which means renumbering
            if any(x.get("heading") for x in ch):
                rows = [dict(r) for r in s.execute(sqlalchemy.text(
                    "SELECT id, position, is_heading FROM recipe_steps WHERE recipe_id=:r "
                    "ORDER BY position"), {"r": rid}).mappings()]
                lifts = {x["id"]: x for x in ch if x.get("heading")}
                # push every row out of the way first: positions are not unique on recipe_steps,
                # but keeping them dense and ordered is what every reader of this table assumes
                final, pos = [], 0
                for r in rows:
                    if r["id"] in lifts:
                        final.append(("new", lifts[r["id"]], pos)); pos += 1
                    final.append(("old", r, pos)); pos += 1
                for kind, r, p in final:
                    if kind == "old":
                        s.execute(sqlalchemy.text("UPDATE recipe_steps SET position=:p WHERE id=:i"),
                                  {"p": p, "i": r["id"]})
                for kind, r, p in final:
                    if kind == "new":
                        s.execute(sqlalchemy.text(
                            "INSERT INTO recipe_steps (recipe_id, position, is_heading, heading_level, text) "
                            "VALUES (:r, :p, 1, :l, :t)"),
                            {"r": rid, "p": p, "l": r["level"] or 1, "t": r["heading"]})
            # ⚠️ THE OTHER HALF, SAME TRANSACTION. Every change here is a machine repair: the author
            #    numbered their own steps and the app numbers them again, so the recipe was always
            #    meant to read this way and the cook has changed nothing. The abort below proves it.
            s.execute(sqlalchemy.text(
                "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r AND reason='original'"),
                {"c": app.serialize_recipe_content(s, rid), "r": rid})
            s.commit()

    bad = []
    with app.orm_session() as s:
        for rid, _ch in planned:
            now = len(app._recipe_annotations(s, rid))
            if now != before[rid]:
                bad.append((rid, before[rid], now))
    if bad:
        sys.exit(f"ABORT: {len(bad)} recipe(s) changed their mark count: {bad}")
    print(f"  WROTE {n_steps} step(s) over {len(planned)} recipe(s) -> {db}")
    print(f"  no recipe's mark count moved")
    return planned


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--i-mean-live", action="store_true")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)
    run(a.db, apply=a.apply, record=a.record)


if __name__ == "__main__":
    main()
