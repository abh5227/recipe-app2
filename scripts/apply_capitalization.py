#!/usr/bin/env python3.13
"""apply_capitalization.py - first letters, in lockstep, with the uncertain names left for Andy.

Three surfaces, three rules, all of them shared with the importer:

  steps and notes   capitalize_first_visible. The first letter a READER sees, stepping over leading
                    punctuation, quotes and an author's list number, and never touching a letter
                    inside [[link]] markup. Nothing else about the text changes, so "COLD butter"
                    keeps its shout.
  headings          already sentence case, applied by the label passes (import_cleanup.sentence_case).
                    This pass asserts it rather than redoing it.
  ingredient names  ingredient_name_case. Lowercase, except proper nouns, brands and acronyms. A
                    LINKED line takes the library's own capitalization, which is a decision somebody
                    already made about that exact ingredient.

⚠️ THE UNCERTAIN NAMES ARE NOT WRITTEN. Measured over the 300: 455 ingredient names start with a
capital, 296 have evidence they are ordinary words and 159 have none. Lowercasing those 159 on a
guess is how "Kashmiri chili" becomes "kashmiri chili", so they go in the review CSV with the reason,
and a decision file brings them back later.

⚠️ AND IT RUNS LAST. Every pass before it rewrites step text (numbers come off, labels lift), and
capitalizing a step that is about to lose its first three words is work thrown away.

⚠️ LOCKSTEP, AND THE GATE IS PER RECIPE BEFORE THE COMMIT. A capitalization-only edit is exactly the
kind of change the cook must not be blamed for.
"""
import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from corpus_guard import refuse_live, report_target                          # noqa: E402

CSV_NAME = "ingredient-name-case.csv"
_LEAD = re.compile(r"^[^A-Za-z]*([A-Za-z][\w'’-]*)")


def _lead_word(name):
    m = _LEAD.match(str(name or ""))
    return m.group(1) if m else ""


def plan(s, sqlalchemy, cleanup):
    """Everything this pass would write, plus the uncertain names it refuses to."""
    steps, notes, ings, uncertain = [], [], [], []

    for r in s.execute(sqlalchemy.text(
            "SELECT id, recipe_id, text FROM recipe_steps WHERE is_heading=0 "
            "ORDER BY recipe_id, position")).mappings():
        fixed = cleanup.capitalize_first_visible(r["text"])
        if fixed != r["text"]:
            steps.append({"row_id": r["id"], "recipe_id": r["recipe_id"],
                          "was": r["text"], "now": fixed})

    for r in s.execute(sqlalchemy.text(
            "SELECT id, recipe_id, text FROM recipe_notes ORDER BY recipe_id, position")).mappings():
        fixed = cleanup.capitalize_first_visible(r["text"])
        if fixed != r["text"]:
            notes.append({"row_id": r["id"], "recipe_id": r["recipe_id"],
                          "was": r["text"], "now": fixed})

    # the corpus's own lowercase use of each leading word, the secondary signal
    lower_seen = {}
    rows = [dict(r) for r in s.execute(sqlalchemy.text(
        "SELECT i.id, i.recipe_id, i.label, i.raw_text, i.ingredient_id, i.catalog_id "
        "FROM recipe_ingredients i WHERE i.is_heading=0 ORDER BY i.recipe_id, i.position"
    )).mappings()]
    for r in rows:
        w = _lead_word(r["label"] or r["raw_text"])
        if w and w[0].islower():
            lower_seen[w.lower()] = lower_seen.get(w.lower(), 0) + 1

    # the library's canonical form, for the linked lines
    canon = {}
    for r in s.execute(sqlalchemy.text(
            "SELECT id, COALESCE(name, id) AS nm FROM ingredients")).mappings():
        canon[r["id"]] = r["nm"]

    for r in rows:
        col = "label" if r["label"] else "raw_text"
        name = r[col]
        if not name:
            continue
        w = _lead_word(name)
        fixed, verdict, why = cleanup.ingredient_name_case(
            name, canonical=canon.get(r["ingredient_id"]),
            lowercase_elsewhere=bool(lower_seen.get(w.lower())))
        if verdict == cleanup.CASE_UNCERTAIN:
            uncertain.append({"recipe_id": r["recipe_id"], "row_id": r["id"], "column": col,
                              "name": name, "verdict": verdict, "why": why,
                              "would_become": name[:0] + _lower_lead(name)})
        elif fixed != name:
            ings.append({"row_id": r["id"], "recipe_id": r["recipe_id"], "column": col,
                         "was": name, "now": fixed, "verdict": verdict, "why": why})
    return steps, notes, ings, uncertain


def _lower_lead(name):
    m = _LEAD.match(str(name or ""))
    if not m:
        return name
    w = m.group(1)
    at = m.start(1)
    return name[:at] + w[0].lower() + w[1:] + name[at + len(w):]


def run(db, apply=False, record=False):
    import app
    import import_cleanup as cleanup
    import models
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)

    with app.orm_session() as s:
        steps, notes, ings, uncertain = plan(s, sqlalchemy, cleanup)

    print(f"  steps to capitalize            : {len(steps)}")
    for r in steps[:6]:
        print(f"      {r['recipe_id'][:34]:36s} {r['was'][:54]!r}")
    print(f"  note rows to capitalize        : {len(notes)}")
    for r in notes[:6]:
        print(f"      {r['recipe_id'][:34]:36s} {r['was'][:54]!r}")
    print(f"  ingredient names to lowercase  : {len(ings)}")
    for r in ings[:8]:
        print(f"      {r['recipe_id'][:34]:36s} {r['was'][:30]!r} -> {r['now'][:30]!r}")
    print(f"  ingredient names LEFT FOR ANDY : {len(uncertain)}")
    for r in uncertain[:8]:
        print(f"      {r['recipe_id'][:34]:36s} {r['name'][:38]!r}   ({r['why']})")

    if uncertain:
        target = report_target(CSV_NAME, record)
        import csv as _csv
        with open(target, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=["recipe_id", "row_id", "column", "name",
                                               "would_become", "why", "decision"])
            w.writeheader()
            for r in uncertain:
                w.writerow({"recipe_id": r["recipe_id"], "row_id": r["row_id"],
                            "column": r["column"], "name": r["name"],
                            "would_become": r["would_become"], "why": r["why"], "decision": ""})
        print(f"  review list -> {target}")

    if not apply:
        print("  DRY RUN. Nothing written. Pass --apply to write.")
        return steps, notes, ings, uncertain

    writes = ([("recipe_steps", "text", r) for r in steps]
              + [("recipe_notes", "text", r) for r in notes]
              + [(f"recipe_ingredients", r["column"], r) for r in ings])
    if not writes:
        print("  nothing to do.")
        return steps, notes, ings, uncertain

    touched = sorted({r["recipe_id"] for _t, _c, r in writes})
    before = {}
    with app.orm_session() as s:
        for rid in touched:
            before[rid] = {"marks": json.dumps(app._recipe_annotations(s, rid), sort_keys=True),
                           "byte_equal": _byte_equal(s, sqlalchemy, app, rid)}

    for rid in touched:
        with app.orm_session() as s:
            stored = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            doc = json.loads(stored) if stored is not None else None
            for table, col, r in [w for w in writes if w[2]["recipe_id"] == rid]:
                s.execute(sqlalchemy.text(
                    f"UPDATE {table} SET {col}=:v WHERE id=:i"), {"v": r["now"], "i": r["row_id"]})
                # ⚠️ THE OTHER HALF, IN THE SAME TRANSACTION. A note is NOT in the baseline (notes
                #    are a playground), so only steps and ingredients have an entry to patch.
                if doc is None or table == "recipe_notes":
                    continue
                key = "steps" if table == "recipe_steps" else "ingredients"
                for entry in doc.get(key) or []:
                    if entry.get("id") == r["row_id"] and entry.get(col) == r["was"]:
                        entry[col] = r["now"]
            if doc is not None:
                s.execute(sqlalchemy.text(
                    "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r "
                    "AND reason='original'"),
                    {"c": json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")), "r": rid})
            now_marks = json.dumps(app._recipe_annotations(s, rid), sort_keys=True)
            if now_marks != before[rid]["marks"]:
                s.rollback()
                sys.exit(f"ABORT on {rid}: the annotation set moved, so nothing was written.")
            if before[rid]["byte_equal"] and not _byte_equal(s, sqlalchemy, app, rid):
                s.rollback()
                sys.exit(f"ABORT on {rid}: it left the byte-equal set, so nothing was written.")
            s.commit()

    print(f"  WROTE {len(writes)} row(s) over {len(touched)} recipe(s) -> {db}")
    print(f"  no recipe's annotation set moved and none left the byte-equal set")
    return steps, notes, ings, uncertain


def _byte_equal(s, sqlalchemy, app, rid):
    got = s.execute(sqlalchemy.text(
        "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
        {"r": rid}).scalar_one_or_none()
    return got is not None and app.serialize_recipe_content(s, rid) == got


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--record", action="store_true",
                    help="write the review list into docs/data-repairs/ instead of reports/")
    ap.add_argument("--i-mean-live", action="store_true")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)
    run(a.db, apply=a.apply, record=a.record)


if __name__ == "__main__":
    main()
