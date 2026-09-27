#!/usr/bin/env python3
"""apply_plan_ahead_proposals.py - write the v3 proposals into a database, in lockstep.

⚠️ TAKES THE DATABASE PATH AS AN ARGUMENT AND REFUSES recipes.db WITHOUT --i-mean-live. Round 3
applies this to a COPY only.

⚠️ LOCKSTEP, AND THIS IS THE WHOLE POINT. A wait row is CONTENT: serialize_recipe_content puts it
in the blob, so writing 126 rows without touching the baselines would make every one of those 82
recipes differ from its reason='original' snapshot and mint a phantom "added a wait" annotation.
The seeded values are not a cook's edit, so the baseline has to carry them from the start.

⚠️ THE BASELINE IS PATCHED, NOT REBUILT. The stored blob is parsed, the waits and storage keys are
inserted, and it is re-dumped with content_blob's own json options. Everything else stays
byte-identical. Rebuilding the baseline from current content would declare each recipe born in its
edited state and ERASE the real annotations 49 of them are carrying.

⚠️ A BLANK-LABEL PROPOSAL IS NOT WRITTEN. 10 rows name a wait the recipe states with no duration
anywhere. label is NOT NULL and an empty one says nothing, so they wait for Andy's words.
"""
import argparse
import csv
import json
import pathlib
import sqlite3
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import planahead                                                      # noqa: E402
import snapshot_serialize                                             # noqa: E402

CSV_PATH = BASE / "previews" / "plan-ahead-proposals-v3.csv"

WAIT_COLS = ("position", "kind", "label", "min_minutes", "max_minutes", "step_position",
             "ext_label", "ext_min_minutes", "ext_max_minutes", "when_kind", "when_label",
             "step_check")
STORE_COLS = ("position", "where_kept", "applies_to", "label", "min_minutes", "max_minutes")


def _i(v):
    return None if v in (None, "") else int(v)


def load(path=CSV_PATH):
    """CSV -> {recipe_id: {"waits": [...], "storage": [...]}}, blanks and non-rows dropped."""
    out, skipped = {}, {"blank": 0, "excluded": 0, "flagged": 0}
    for r in csv.DictReader(path.open()):
        t = r["type"]
        if t == "excluded":
            skipped["excluded"] += 1
            continue
        if t.startswith("flagged"):
            skipped["flagged"] += 1
            continue
        if not (r["label"] or "").strip():
            skipped["blank"] += 1
            continue
        bucket = out.setdefault(r["recipe_id"], {"waits": [], "storage": []})
        if t == "wait":
            bucket["waits"].append(dict(
                kind=r["kind"] if r["kind"] in planahead.KINDS else "other",
                label=r["label"], min_minutes=_i(r["min_minutes"]), max_minutes=_i(r["max_minutes"]),
                step_position=_i(str(r["step_position"]).split(".")[0]),
                ext_label=(r["ext_label"] or None),
                ext_min_minutes=_i(r["ext_min_minutes"]), ext_max_minutes=_i(r["ext_max_minutes"]),
                when_kind=r["when_kind"] or "always",
                when_label=(r["when_label"] or None) if r["when_kind"] == "only_if" else None,
                source_sentence=r["source_sentence"] or ""))
        elif t == "storage":
            bucket["storage"].append(dict(
                where_kept=r["kind"] if r["kind"] in planahead.WHERES else "other",
                applies_to=None, label=r["label"],
                min_minutes=_i(r["min_minutes"]), max_minutes=_i(r["max_minutes"])))
    return out, skipped


def _patch_baseline(stored, waits, storage):
    """Insert the waits and storage keys into a stored baseline, leaving the rest byte-identical.

    ⚠️ THE KEYS ARE OMITTED WHEN EMPTY, exactly as content_blob omits them, so a recipe with no
    proposals keeps a blob that still compares byte-equal to what the serializer produces."""
    body = json.loads(stored)
    for key, rows, fields in (("waits", waits, snapshot_serialize.SNAPSHOT_WAIT_FIELDS),
                              ("storage", storage, snapshot_serialize.SNAPSHOT_STORAGE_FIELDS)):
        if rows:
            body[key] = [{k: r.get(k) for k in fields} for r in rows]
        else:
            body.pop(key, None)
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def apply(db, plan, dry=False):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    wrote = {"recipes": 0, "waits": 0, "storage": 0, "baselines": 0, "no_baseline": []}
    missing = []
    for rid in sorted(plan):
        if not c.execute("SELECT 1 FROM recipes WHERE id=?", (rid,)).fetchone():
            missing.append(rid)
            continue
        # ⚠️ STEP ORDER, NOT CSV ORDER. The CSV sorts step_position as a STRING, so morning-buns
        #    listed steps 15, 18, 20, 24, 5, 7. A cook reads the method top to bottom and the
        #    breakdown has to agree with it. A wait with no step keeps its relative place at the end.
        waits = sorted(plan[rid]["waits"],
                       key=lambda w: (w.get("step_position") is None, w.get("step_position") or 0))
        storage = plan[rid]["storage"]
        c.execute("DELETE FROM recipe_waits WHERE recipe_id=?", (rid,))
        c.execute("DELETE FROM recipe_storage WHERE recipe_id=?", (rid,))
        # ⚠️ THE SNIPPET COMES FROM THE SOURCE SENTENCE, which is the sentence that stated the
        #    wait, not the step's opening. Measured on the v3 proposals: 88 of the 96 rows carry a
        #    source sentence and every one of them IS a substring of the step at its position.
        #    The other 8 have none recorded, and fall back to the step's opening.
        steps = {r["position"]: r["text"] for r in c.execute(
            "SELECT position, text FROM recipe_steps WHERE recipe_id=? AND is_heading=0", (rid,))}
        for pos, w in enumerate(waits):
            sp = w.get("step_position")
            sp = sp if sp in steps else None
            if sp is None:
                check = None
            else:
                sent = planahead.step_key(w.pop("source_sentence", "") or "")[:planahead.SNIPPET_LEN]
                check = sent if sent and sent in planahead.step_key(steps[sp]) \
                    else planahead.step_snippet(steps[sp])
            w = dict(w, step_position=sp, step_check=check)
            w.pop("source_sentence", None)
            row = dict(w, position=pos)
            c.execute(f"INSERT INTO recipe_waits (recipe_id,{','.join(WAIT_COLS)}) "
                      f"VALUES (?,{','.join('?' * len(WAIT_COLS))})",
                      (rid, *(row[k] for k in WAIT_COLS)))
            wrote["waits"] += 1
        for pos, x in enumerate(storage):
            row = dict(x, position=pos)
            c.execute(f"INSERT INTO recipe_storage (recipe_id,{','.join(STORE_COLS)}) "
                      f"VALUES (?,{','.join('?' * len(STORE_COLS))})",
                      (rid, *(row[k] for k in STORE_COLS)))
            wrote["storage"] += 1
        # ---- LOCKSTEP: the baseline carries the same rows, in the same transaction ----
        stored = c.execute("SELECT content FROM recipe_snapshots WHERE recipe_id=? "
                           "AND reason='original'", (rid,)).fetchone()
        if stored is None:
            wrote["no_baseline"].append(rid)          # never mint one; see snapshot_original
        else:
            db_waits = [dict(r) for r in c.execute(
                "SELECT * FROM recipe_waits WHERE recipe_id=? ORDER BY position, id", (rid,))]
            db_store = [dict(r) for r in c.execute(
                "SELECT * FROM recipe_storage WHERE recipe_id=? ORDER BY position, id", (rid,))]
            patched = _patch_baseline(stored["content"], db_waits, db_store)
            if patched != stored["content"]:
                c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? "
                          "AND reason='original'", (patched, rid))
                wrote["baselines"] += 1
        wrote["recipes"] += 1
    if dry:
        c.rollback()
    else:
        c.commit()
    c.close()
    return wrote, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--i-mean-live", action="store_true")
    a = ap.parse_args()
    db = pathlib.Path(a.db).resolve()
    if db.name == "recipes.db" and db.parent == BASE and not a.i_mean_live:
        sys.exit("refusing to write live recipes.db without --i-mean-live")
    plan, skipped = load()
    print(f"plan: {len(plan)} recipes, "
          f"{sum(len(v['waits']) for v in plan.values())} waits, "
          f"{sum(len(v['storage']) for v in plan.values())} storage")
    print(f"  not written: {skipped}")
    wrote, missing = apply(db, plan, dry=a.dry)
    print(f"{'DRY RUN' if a.dry else 'WROTE'} -> {db}")
    for k, v in wrote.items():
        print(f"  {k}: {v if not isinstance(v, list) else (len(v), v[:6])}")
    if missing:
        print(f"  ⚠️ {len(missing)} proposal recipes are not in this database: {missing[:8]}")


if __name__ == "__main__":
    main()
