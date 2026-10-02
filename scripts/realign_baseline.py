#!/usr/bin/env python3.13
"""Put a recipe back in the byte-equal short-circuit when its baseline drifted for a machine reason.

⚠️ WHAT THIS REPAIRS, AND WHY IT IS A RULE RATHER THAN A ROW EDIT. A recipe's `reason='original'`
baseline is compared to its current content BYTE FOR BYTE to decide whether to run the diff at all.
Three machine-origin changes moved those bytes without changing anything a cook would recognise, so
the recipes dropped out of the short-circuit for good while `snapshot_diff` reported 0 entries and
the page showed nothing. Measured on live 2026-10-01: 6 of 300 recipes, 66 differences, 0 of them
visible anywhere.

⚠️ THE THREE DECLARED CASES, AND NOTHING ELSE IS EVER TOUCHED.

  1. A ROW ID. `write_plan_ahead` used to delete every wait and storage row and insert fresh ones,
     so a save that changed NOTHING gave each row a new AUTOINCREMENT id, and
     `serialize_recipe_content` records that id. brioche-bread's entire difference from its
     baseline was `"id": 12` becoming `108` and `"id": 13` becoming `109`. The save path keeps row
     ids now (`app._match_rows`), so nothing new arrives here.

  2. A RELEASED INGREDIENT LINK. Migration 046 deleted the 36 hand-authored ingredient rows and ran
     `UPDATE recipe_ingredients SET ingredient_id = NULL` over the 50 lines pointing at them. It
     patched the live rows and left the baselines alone, which is a lockstep violation in a
     migration rather than in a corpus pass. `snapshot_diff` never compares `ingredient_id` (it is
     the matching KEY in `_diff_ingredients` phase 1), so nothing showed.
     ⚠️ THE THIRD CLAUSE IS WHAT MAKES THIS PROVABLE, AND IT IS NOT DECORATION. A link counts as
     released only when the row it NAMES is absent from `ingredients`. A cook unlinks a line by
     retyping its name, and `write_recipe_rows` drops the link only when the name changed, so a
     cook-origin unlink always arrives alongside a `label`/`raw_text` change that falls outside
     these three cases and stops the recipe. The direction is enforced too: a baseline with no link
     against a live row that HAS one is a re-link, not a release, and it stops the recipe.

  3. NULL WRITTEN AS AN EMPTY STRING. The client sends every header field as a trimmed string, so a
     column stored as NULL came back as "" and the save wrote the "". `app._kept` fixed the cause
     (keep what is stored when the payload means the same); this clears the residue. The diff folds
     null and empty through `units.compare_text`, so nothing showed.
     ⚠️ ONLY None AGAINST "", NEVER WHITESPACE. `units.compare_text` also folds a re-wrap, and this
     must not: a cook who re-wrapped a headnote has made a real edit, and a realign that collapsed
     whitespace would discard it silently. Compare loosely, write faithfully, and realign narrowly.

⚠️ THE BASELINE MOVES AND THE LIVE ROWS DO NOT, which is the one case where that is right. Every
other pass patches both halves in lockstep because it CHANGES the live row. Here the live rows are
the truth and the baseline is the half that went stale. Rewriting live to match a stale baseline
would be inventing data.

⚠️ AND IT REFUSES ANY RECIPE WHERE ANYTHING ELSE DIFFERS. Both documents are reduced by
`_normalize`, which erases exactly the three cases above and nothing more, and they must then match
byte for byte. If they do not, the cook edited something real and this script has no business
touching that baseline. The recipe is skipped, reported, and left exactly as it is. Two aborts are
armed on every write: the patched baseline must equal the current content, and reducing it must
still reproduce what was stored.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))             # for corpus_guard
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))      # for app
from corpus_guard import refuse_live, report_target                          # noqa: E402

CSV_NAME = "baseline-realign.csv"
# ⚠️ notes IS ONE OF THESE SINCE MIGRATION 060. It was missing, so a machine drift inside a note
#    row (a row id, a released link, an empty string where a null belongs) fell through to the raw
#    comparison and the recipe was reported as differing in something real, which this script is
#    then unable to realign. It failed safe rather than mis-writing, and it failed on exactly the
#    rows this round added.
ROW_LISTS = ("ingredients", "steps", "waits", "storage", "notes")
EMPTYISH = (None, "")

CASE_ID = "row id"
CASE_LINK = "released link"
CASE_EMPTY = "null vs empty"


def _absent_link(value, live_ingredients):
    """True when this ingredient_id names nothing that exists. Empty counts, and so does a name the
    `ingredients` table no longer holds — which is what migration 046 left behind."""
    return value in EMPTYISH or value not in live_ingredients


def _normalize(blob, live_ingredients):
    """The document reduced to what a realign may NOT change. Two recipes differing only in the
    three declared cases produce the same string here, and nothing else does."""
    doc = json.loads(blob)
    out = {}
    for key, value in doc.items():
        if key in ROW_LISTS and isinstance(value, list):
            rows = []
            for r in value:
                row = {}
                for field, v in r.items():
                    if field == "id":
                        continue                                      # case 1
                    if field == "ingredient_id":
                        if _absent_link(v, live_ingredients):
                            continue                                  # case 2
                        row[field] = v
                        continue
                    row[field] = None if v in EMPTYISH else v         # case 3
                rows.append(row)
            out[key] = rows
        elif isinstance(value, dict):
            out[key] = {f: (None if v in EMPTYISH else v) for f, v in value.items()}   # case 3
        else:
            out[key] = None if value in EMPTYISH else value
    return json.dumps(out, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _cases(stored_blob, current_blob, live_ingredients):
    """Which of the three cases this recipe actually carries, and a readable detail line."""
    stored, current = json.loads(stored_blob), json.loads(current_blob)
    seen, detail = set(), []
    for key in ROW_LISTS:
        for a, b in zip(stored.get(key) or [], current.get(key) or []):
            if a.get("id") != b.get("id"):
                seen.add(CASE_ID)
                detail.append(f"{key}:{a.get('id')}->{b.get('id')}")
            if a.get("ingredient_id") != b.get("ingredient_id"):
                seen.add(CASE_LINK)
                detail.append(f"{key}.ingredient_id:{a.get('ingredient_id')}->None")
            for f in set(a) | set(b):
                if f in ("id", "ingredient_id"):
                    continue
                if a.get(f) != b.get(f) and a.get(f) in EMPTYISH and b.get(f) in EMPTYISH:
                    seen.add(CASE_EMPTY)
    sh, ch = stored.get("recipe") or {}, current.get("recipe") or {}
    for f in set(sh) | set(ch):
        if sh.get(f) != ch.get(f) and sh.get(f) in EMPTYISH and ch.get(f) in EMPTYISH:
            seen.add(CASE_EMPTY)
            detail.append(f"recipe.{f}:null->empty")
    return sorted(seen), detail


def _realign(stored_blob, current_blob):
    """`stored` rewritten so each of the three declared cases takes the CURRENT value, and every
    other field keeps what the baseline holds. Surgical on purpose: rebuilding the baseline from
    current content would declare every edited recipe born in its edited state."""
    stored, current = json.loads(stored_blob), json.loads(current_blob)
    out = {}
    for key, value in stored.items():
        if key in ROW_LISTS and isinstance(value, list):
            live = current.get(key) or []
            if len(value) != len(live):
                return None                                   # shapes differ; the caller refuses
            rows = []
            for r, l in zip(value, live):
                row = dict(r)
                if "id" in r or "id" in l:
                    row["id"] = l.get("id")                                      # case 1
                if "ingredient_id" in r or "ingredient_id" in l:
                    row["ingredient_id"] = l.get("ingredient_id")                # case 2
                for f in list(row):
                    if row[f] != l.get(f) and row[f] in EMPTYISH and l.get(f) in EMPTYISH:
                        row[f] = l.get(f)                                        # case 3
                rows.append(row)
            out[key] = rows
        elif isinstance(value, dict):
            live = current.get(key) or {}
            hdr = dict(value)
            for f in list(hdr):
                if hdr[f] != live.get(f) and hdr[f] in EMPTYISH and live.get(f) in EMPTYISH:
                    hdr[f] = live.get(f)                                         # case 3
            out[key] = hdr
        else:
            out[key] = value
    return json.dumps(out, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def run(db, apply=False, record=False):
    import app
    import models
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)

    fixable, already, skipped = [], [], []
    with app.orm_session() as s:
        live_ingredients = {r for (r,) in s.execute(sqlalchemy.text("SELECT id FROM ingredients"))}
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
            if _normalize(stored, live_ingredients) != _normalize(current, live_ingredients):
                entries = app.snapshot_diff.diff_snapshots(stored, current)
                skipped.append((rid, len(entries)))
                continue
            fixable.append((rid, stored, current))

    print(f"  already byte-equal                : {len(already)}")
    print(f"  drifted for a declared reason     : {len(fixable)}")
    print(f"  differ in something real (left)   : {len(skipped)}")
    for rid, n in skipped[:12]:
        print(f"      {rid}  ({n} annotation entries)")

    rows = []
    for rid, stored, current in fixable:
        cases, detail = _cases(stored, current, live_ingredients)
        rows.append((rid, ", ".join(cases), "; ".join(detail[:8])))
        print(f"      {rid}: {', '.join(cases)}  {', '.join(detail[:4])}")

    if rows:
        target = report_target(CSV_NAME, record)
        import csv as _csv
        with open(target, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["recipe_id", "cases", "detail"])
            w.writerows(rows)
        print(f"  report -> {target}")

    if not apply:
        print("  DRY RUN. Nothing written. Pass --apply to write.")
        return fixable

    patched_all = {}
    for rid, stored, current in fixable:
        patched = _realign(stored, current)
        # ⚠️ THE ABORT, ARMED ON EVERY RECIPE, NOT JUST ON THE SURVEY. The patched baseline must now
        #    equal the current content byte for byte, which is the whole point of the repair, and
        #    reducing it must still reproduce what was stored. Either failing means this script got
        #    the shape wrong, and it writes nothing at all.
        if patched is None:
            sys.exit(f"ABORT on {rid}: the row lists are different lengths")
        if patched != current:
            sys.exit(f"ABORT on {rid}: the patched baseline is not byte-equal to current content")
        if _normalize(patched, live_ingredients) != _normalize(stored, live_ingredients):
            sys.exit(f"ABORT on {rid}: patching changed something outside the three declared cases")
        patched_all[rid] = patched

    with app.orm_session() as s:
        for rid in patched_all:
            s.execute(sqlalchemy.text(
                "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r AND reason='original'"),
                {"c": patched_all[rid], "r": rid})
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
