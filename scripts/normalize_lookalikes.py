#!/usr/bin/env python3.13
"""normalize_lookalikes.py - Cyrillic and Greek letters standing in for English ones, in lockstep.

⚠️ FIX BY RULE, NOT BY ROW. The table and the decision both live in
import_cleanup.normalize_lookalikes, which clean_recipe calls on every surface of every import, so a
pasted look-alike is repaired on the way in and this pass is only the corpus half.

⚠️ IT RUNS BEFORE THE LABEL AND NUMBER RULES, AND THAT IS THE WHOLE REASON IT EXISTS AS A SEPARATE
PASS. Measured over the 300: exactly two words carry a look-alike, and each one DEFEATED a later
rule in silence.
    garlic-ginger-chicken-with-cilantro-and-mint step 2   "3. МАКЕ THE CHICKEN:"
        М А К Е are Cyrillic, the label rule wants Latin capitals, so the label never lifted.
    caramelized-onion-dal step 5                  "З. MAKE THE SEASONING:"
        З is Cyrillic ZE where the digit 3 belongs. This pass leaves it alone, because replacing a
        letter with a DIGIT needs the author's own numbering as evidence rather than a shape table:
        author_step_number reads it and strip_author_numbers removes the number rather than
        rewriting the character. Measured afterwards, that recipe was refused for a SECOND and
        unrelated reason, which is the one worth knowing: its author numbers sit at ordinals 1, 4,
        6 and 7 because the import split three steps into continuation lines, so the ordinal test
        declined it. The relaxed separator door in strip_author_numbers is what admits it.

⚠️ LOCKSTEP. Every row this writes has its reason='original' baseline patched in the same
transaction, so a machine repair makes no "your changes" mark. The gate is stated against the
before-state of this run and the pass proves each recipe before it commits.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from corpus_guard import refuse_live, report_target                          # noqa: E402

CSV_NAME = "lookalike-letters.csv"

# ⚠️ DERIVED FROM THE SNAPSHOT FIELDS, NOT LISTED BY HAND. The hand-written list missed five
#    columns that are content by the project's own definition: recipes.author,
#    recipe_storage.label, recipe_waits.ext_label, recipe_waits.when_label and
#    recipe_ingredients.note. A review injected a Cyrillic А into each of them and this pass found
#    0 rows. when_label now reaches the page through conditional_totals as well. Taking the columns
#    from snapshot_serialize means the next one added is covered without anyone remembering this
#    file exists.
#
# (table, the baseline key, the text columns)
_TEXT_COLUMNS = {
    "recipe_steps": ("steps", ("text",)),
    "recipe_ingredients": ("ingredients", ("label", "raw_text", "note", "heading")),
    "recipe_waits": ("waits", ("label", "ext_label", "when_label")),
    "recipe_storage": ("storage", ("label", "applies_to")),
    "recipe_notes": (None, ("text",)),           # a note is a playground: not in the baseline
}
RECIPE_COLUMNS = ("name", "author", "descr", "notes")


def _surfaces():
    """[(table, column, baseline key, the key inside that entry)] for every TEXT column the snapshot
    records, plus the note rows the snapshot deliberately leaves out."""
    import snapshot_serialize as ss
    snap = {"steps": ss.SNAPSHOT_STEP_FIELDS, "ingredients": ss.SNAPSHOT_ING_FIELDS,
            "waits": ss.SNAPSHOT_WAIT_FIELDS, "storage": ss.SNAPSHOT_STORAGE_FIELDS}
    out = []
    for table, (key, cols) in _TEXT_COLUMNS.items():
        for col in cols:
            if key is not None and col not in snap.get(key, ()):
                continue                      # not content, so this pass does not reach it
            out.append((table, "id", col, key, col))
    return out


def run(db, apply=False, record=False):
    import app
    import import_cleanup as cleanup
    import models
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)

    hits = []
    with app.orm_session() as s:
        for table, idcol, col, key, field in _surfaces():
            for row in s.execute(sqlalchemy.text(
                    f"SELECT {idcol} AS rid, recipe_id, {col} AS t FROM {table} "
                    f"WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {idcol}")).mappings():
                fixed = cleanup.normalize_lookalikes(row["t"])
                if fixed != row["t"]:
                    hits.append({"table": table, "row_id": row["rid"],
                                 "recipe_id": row["recipe_id"], "column": col,
                                 "key": key, "field": field, "was": row["t"], "now": fixed})
        # the recipe's own text columns
        for col in RECIPE_COLUMNS:
            for row in s.execute(sqlalchemy.text(
                    f"SELECT id AS rid, {col} AS t FROM recipes "
                    f"WHERE {col} IS NOT NULL AND {col} != '' ORDER BY id")).mappings():
                fixed = cleanup.normalize_lookalikes(row["t"])
                if fixed != row["t"]:
                    hits.append({"table": "recipes", "row_id": row["rid"],
                                 "recipe_id": row["rid"], "column": col,
                                 "key": "recipe", "field": col, "was": row["t"], "now": fixed})

    print(f"  rows carrying a look-alike letter : {len(hits)}")
    for h in hits:
        bad = sorted({c for c in h["was"] if c not in h["now"]})
        print(f"      {h['recipe_id'][:42]:44s} {h['table']}.{h['column']} row {h['row_id']}"
              f"   {''.join(bad)!r}")
        print(f"          was : {h['was'][:88]!r}")
        print(f"          now : {h['now'][:88]!r}")

    if hits:
        target = report_target(CSV_NAME, record)
        import csv as _csv
        with open(target, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=["recipe_id", "table", "column", "row_id",
                                               "was", "now"])
            w.writeheader()
            for h in hits:
                w.writerow({k: h[k] for k in ("recipe_id", "table", "column", "row_id",
                                              "was", "now")})
        print(f"  report -> {target}")

    if not apply:
        print("  DRY RUN. Nothing written. Pass --apply to write.")
        return hits
    if not hits:
        print("  nothing to do.")
        return hits

    touched = sorted({h["recipe_id"] for h in hits})
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
            for h in [x for x in hits if x["recipe_id"] == rid]:
                s.execute(sqlalchemy.text(
                    f"UPDATE {h['table']} SET {h['column']}=:v WHERE {h['table']}.id=:i"
                    if h["table"] != "recipes" else
                    f"UPDATE recipes SET {h['column']}=:v WHERE id=:i"),
                    {"v": h["now"], "i": h["row_id"]})
                # ⚠️ THE OTHER HALF, IN THE SAME TRANSACTION, AND ONLY THE ENTRY THAT MOVED.
                if doc is None or h["key"] is None:
                    continue                      # a note is not in the baseline: it is a playground
                if h["key"] == "recipe":
                    if h["field"] in (doc.get("recipe") or {}):
                        doc["recipe"][h["field"]] = h["now"]
                else:
                    for entry in doc.get(h["key"]) or []:
                        if entry.get("id") == h["row_id"] and entry.get(h["field"]) == h["was"]:
                            entry[h["field"]] = h["now"]
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

    print(f"  WROTE {len(hits)} row(s) over {len(touched)} recipe(s) -> {db}")
    print(f"  no recipe's annotation set moved and none left the byte-equal set")
    return hits


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
                    help="write the report into docs/data-repairs/ instead of reports/")
    ap.add_argument("--i-mean-live", action="store_true")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)
    run(a.db, apply=a.apply, record=a.record)


if __name__ == "__main__":
    main()
