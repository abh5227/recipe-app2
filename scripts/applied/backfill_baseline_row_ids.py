#!/usr/bin/env python3
"""backfill_baseline_row_ids.py — give every reason='original' baseline its row ids (option C, commit 3).

WHY. A baseline row and the live row it describes were connected by nothing but their text. Option C
gave every content row a stable database id that survives a save (write_recipe_rows updates in place),
and snapshot_serialize now carries that id in the snapshot format. The 300 baselines already on disk
predate it, so without this they would hold `null` where every id belongs — which ends the byte-equal
short-circuit in _recipe_annotations for all 300 recipes at once, and leaves the id-matched diff
(commit 4) nothing to match on.

THE MATCH, IN PASSES, CONSUME-ONCE, NO SIMILARITY. A baseline row is matched to a live row of the same
recipe and takes its id. Nothing is ever matched twice, and a row with no partner keeps a null id
rather than a guess.

  exact       the full projected row, position and id aside, is identical, and unique on both sides.
  exact-dup   identical but the recipe holds more than one such row, so they pair in list order.
  quirk       identical AS THE APP READS IT, after three storage differences that are measured, known
              and systematic are normalized away. See QUIRKS below.
  unassigned  no partner. The row was edited or removed since the recipe was born, and its id stays
              null. Every unassigned row sits in a recipe whose annotations are already non-empty, so
              a null costs that recipe nothing it had.

⚠️ QUIRKS ARE NOT A SIMILARITY TIER, AND EACH ONE WAS MEASURED BEFORE IT WAS ALLOWED. Measured over
live's 300 baselines, the full-row key leaves 125 ingredient rows unmatched, and 97 of them differ from
their live row on nothing a reader or the app could see:

  46 rows   `note` is null in the baseline and '' live, or the reverse. A save writes '' where it
            found null on a column it did not touch, which is a pre-existing defect recorded in
            ROADMAP. snapshot_diff already treats '' and null as the same absence on every field it
            compares, so calling the row different here would contradict the diff.
  27 rows   `ingredient_id` names a library row in the baseline and is null live. Migration 046
            deleted all 36 library ingredients, and live now holds 0 rows in `ingredients` and 0
            recipe rows with a non-null ingredient_id. So a baseline's ingredient_id is ALWAYS a
            pointer to a row that no longer exists, in exactly 6 recipes, and is never evidence that
            the live row is a different row.
  19 rows   both of the above at once.
   5 rows   `note` and `qty` both null-against-empty.

The remaining 28 are real post-birth changes (an amount edited from ½ teaspoon to 1 tsp, a row
removed) and they stay unassigned, which is the right answer.

The quirk key is therefore THE APP'S OWN VIEW OF THE ROW, taken from snapshot_diff's readers rather
than invented here: the canonical amount (_canon_amount, which is what the diff compares), the name
(_ing_name, label falling back to raw_text), the note with '' and null folded together, and the kind.
A pair that agrees on all of those produces NO annotation from the diff, now or after commit 4, so
binding them cannot change what a single recipe page says.

⚠️ EVERY BASELINE IS PROVEN ROW BY ROW, NOT TALLIED. For each of the 300, the rewritten blob has its
id keys stripped back out and is re-serialized, and the result must equal the stored blob BYTE FOR
BYTE. A single mismatch aborts the whole run before anything is written. That is what makes "the ids
are the only thing that changed" a proof rather than a claim.

Run:  python3.13 backup.py
      python3.13 scripts/backfill_baseline_row_ids.py                    # rehearse, write the CSV
      python3.13 scripts/backfill_baseline_row_ids.py --apply            # write
      python3.13 scripts/backfill_baseline_row_ids.py --db /path/copy --apply
"""
import argparse
import collections
import csv
import json
import pathlib
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent   # scripts/applied/ -> scripts/ -> the repo root
sys.path.insert(0, str(REPO))

from snapshot_diff import _canon_amount, _ing_name                    # noqa: E402  THE app's own readers
from snapshot_serialize import content_blob, snapshot_ing_row, snapshot_step_row   # noqa: E402

CSV_OUT = REPO / "docs" / "data-repairs" / "baseline-row-ids-2026-09-29.csv"
TIERS = ("exact", "exact-dup", "quirk", "unassigned")


def _exact_key(row):
    """The full projected row, with the two keys that are not content taken out."""
    return tuple(sorted((k, v) for k, v in row.items() if k not in ("position", "id")))


def _quirk_key_ing(row):
    """The row AS snapshot_diff READS IT — see QUIRKS in the module docstring."""
    if row.get("is_heading"):
        return (1, row.get("raw_text") or "")                  # a heading's text is its raw_text
    return (0, _canon_amount(row.get("qty")), _ing_name(row), row.get("note") or "")


def _quirk_key_step(row):
    return (bool(row.get("is_heading")), row.get("text") or "")


def assign(blob_rows, live_rows, quirk_key):
    """-> [(id or None, tier, differs_on)] for each blob row, in blob order. Consume-once throughout:
    a live row claimed by one pass is invisible to the next, and to every later row in its own pass."""
    out = [None] * len(blob_rows)
    free = list(range(len(live_rows)))
    for keyf in (_exact_key, quirk_key):
        pool = collections.defaultdict(list)
        for i in free:
            pool[keyf(live_rows[i])].append(i)
        dup = {k: len(v) for k, v in pool.items()}
        taken = set()
        for j, b in enumerate(blob_rows):
            if out[j] is not None:
                continue
            bucket = pool.get(keyf(b))
            if not bucket:
                continue
            i = bucket.pop(0)
            taken.add(i)
            live = live_rows[i]
            differs = sorted(k for k in set(b) | set(live)
                             if k not in ("position", "id") and b.get(k) != live.get(k))
            if keyf is _exact_key:
                same_in_blob = sum(1 for x in blob_rows if _exact_key(x) == _exact_key(b))
                tier = "exact" if dup[keyf(b)] == 1 and same_in_blob == 1 else "exact-dup"
            else:
                tier = "quirk"
            out[j] = (live["id"], tier, " ".join(differs))
        free = [i for i in free if i not in taken]
    return [o if o is not None else (None, "unassigned", "") for o in out]


def _live(conn, rid):
    ing = [snapshot_ing_row(dict(r)) | {"id": r["id"]} for r in conn.execute(
        "SELECT * FROM recipe_ingredients WHERE recipe_id=? ORDER BY position, id", (rid,))]
    step = [snapshot_step_row(dict(r)) | {"id": r["id"]} for r in conn.execute(
        "SELECT id, position, is_heading, text FROM recipe_steps WHERE recipe_id=? "
        "ORDER BY position, id", (rid,))]
    return ing, step


def _strip_ids(doc):
    """The blob as it read BEFORE this backfill: every row's id key removed, re-serialized with
    content_blob's own json options. Compared against the stored string byte for byte."""
    bare = {k: v for k, v in doc.items()}
    for name in ("ingredients", "steps"):
        bare[name] = [{k: v for k, v in r.items() if k != "id"} for r in doc.get(name) or []]
    return json.dumps(bare, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def run(db, apply=False, csv_out=CSV_OUT):
    conn = sqlite3.connect(db if apply else f"file:{db}?mode=ro", uri=not apply)
    conn.row_factory = sqlite3.Row
    snaps = conn.execute("SELECT id, recipe_id, content FROM recipe_snapshots "
                         "WHERE reason='original' ORDER BY recipe_id").fetchall()
    tally = {"ingredient": collections.Counter(), "step": collections.Counter()}
    audit, writes, skipped = [], [], []
    for sn in snaps:
        doc = json.loads(sn["content"])
        if any("id" in r for r in (doc.get("ingredients") or [])
               + (doc.get("steps") or [])):
            skipped.append(sn["recipe_id"])                    # already carries ids — idempotent re-run
            continue
        ing_live, step_live = _live(conn, sn["recipe_id"])
        new = {k: v for k, v in doc.items()}
        for name, kind, live, qk, build in (
                ("ingredients", "ingredient", ing_live, _quirk_key_ing, snapshot_ing_row),
                ("steps", "step", step_live, _quirk_key_step, snapshot_step_row)):
            rows = doc.get(name) or []
            got = assign(rows, live, qk)
            for row, (rid_, tier, differs) in zip(rows, got):
                tally[kind][tier] += 1
                if tier != "exact":
                    audit.append({
                        "recipe_id": sn["recipe_id"], "kind": kind,
                        "baseline_position": row.get("position"), "assigned_id": rid_,
                        "tier": tier, "differs_on": differs,
                        "text": (row.get("text") if kind == "step"
                                 else f"{row.get('qty') or ''} {_ing_name(row)}".strip()),
                    })
            new[name] = [dict(r, id=i) for r, (i, _t, _d) in zip(rows, got)]

        blob = content_blob(new.get("recipe") or {}, new["ingredients"], new["steps"],
                            new.get("waits"), new.get("storage"))
        # ⚠️ THE PER-BASELINE PROOF. Strip the ids back out and it must be the stored bytes again.
        back = _strip_ids(json.loads(blob))
        if back != sn["content"]:
            raise SystemExit(
                f"ABORT on {sn['recipe_id']}: stripping the ids back out did not reproduce the stored "
                f"baseline, so this rewrite changes more than the ids. Nothing has been written.\n"
                f"  stored: {sn['content'][:300]}\n  rebuilt: {back[:300]}")
        writes.append((blob, sn["id"]))

    if apply:
        conn.executemany("UPDATE recipe_snapshots SET content=? WHERE id=?", writes)
        conn.commit()
    conn.close()

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, lineterminator="\n",     # LF, matching the other docs/data-repairs CSVs
                           fieldnames=["recipe_id", "kind", "baseline_position", "assigned_id",
                                       "tier", "differs_on", "text"])
        w.writeheader()
        w.writerows(audit)

    print(f"{'APPLIED' if apply else 'REHEARSAL'} — {len(writes)} of {len(snaps)} baselines rewritten"
          f"{f', {len(skipped)} already carried ids' if skipped else ''}")
    for kind in ("ingredient", "step"):
        t = tally[kind]
        print(f"  {kind:11} " + "  ".join(f"{name} {t[name]}" for name in TIERS)
              + f"   total {sum(t.values())}")
    where = csv_out.relative_to(REPO) if csv_out.is_relative_to(REPO) else csv_out
    print(f"  audit: {where} ({len(audit)} row(s) that were not a unique exact match)")
    return tally


if __name__ == "__main__":
    # ⚠️ SPENT. See scripts/applied/_spent.py — this refuses rather than running.
    import sys as _sys, pathlib as _pathlib
    _sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
    from _spent import refuse_spent
    refuse_spent(__file__, "gave every reason='original' baseline its row ids (option C, commit 3)", '24 rows over 19 recipes had no content match and never will')
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(REPO / "recipes.db"))
    ap.add_argument("--apply", action="store_true", help="write (default is a read-only rehearsal)")
    ap.add_argument("--csv", default=str(CSV_OUT))
    a = ap.parse_args()
    run(a.db, apply=a.apply, csv_out=pathlib.Path(a.csv))
