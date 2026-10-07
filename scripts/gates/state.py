#!/usr/bin/env python3
"""Read one database's byte-equal set and its annotation set, for a before/after gate.

    python3.13 scripts/gates/state.py --db <path> --out <file.json>

A corpus pass, a deploy or a spot-check is checked by reading this twice and comparing the two
readings with gates/compare.py. What it records per database:

  short_circuit    the recipes whose current content is BYTE-EQUAL to their reason='original'
                   baseline, as a sorted list of ids
  annotations      every "your changes" entry the page would show, per recipe, as sorted tuples
  counts           row counts for the content tables, plus the migration count
  integrity_check  PRAGMA integrity_check and the foreign-key violation count

⚠️ READ-ONLY BY CONSTRUCTION, NOT BY INTENTION. Every connection is opened through `open_ro`, which
spells `file:<path>?mode=ro`, so SQLite itself refuses a write rather than this file promising not to
make one. That is why the gates are on the read-only list in tests/test_live_guards.py instead of
wiring `--i-mean-live`: reading live's state IS the job, and a gate that needed a sentence typed out
would not get run.

⚠️ IT CALLS snapshot_serialize.content_blob RATHER THAN REBUILDING THE BLOB. The scratchpad version
this grew from projected the snapshot fields itself, which is a second answer to "what is a recipe's
content". It drifted the moment notes left the blob: the copy still emitted `notes`, so every recipe
differed from its baseline and the gate would have passed while comparing nothing. One rule, one
function, and the one function is the one the app writes snapshots with.

⚠️ THERE IS NO --old-serializer FLAG, AND THAT IS DELIBERATE. The scratchpad version had one, to put
`notes` back in the blob while the notes round was in flight. Implementing it now would mean a second
serializer beside content_blob, which is the duplication above. The notes round has shipped and all
300 stored baselines were stripped in lockstep, so there is nothing left to read the old way.
"""
import argparse
import json
import pathlib
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import snapshot_diff                      # noqa: E402
import snapshot_serialize as ss           # noqa: E402

# Counted everywhere. A table that is missing is a database older than the migration that made it,
# which is a legitimate BEFORE side, so the count reads None rather than raising.
COUNTS = {
    "recipes": "SELECT COUNT(*) FROM recipes",
    "steps": "SELECT COUNT(*) FROM recipe_steps",
    "headings": "SELECT COUNT(*) FROM recipe_steps WHERE is_heading = 1",
    "headings_l1": "SELECT COUNT(*) FROM recipe_steps WHERE is_heading = 1 AND heading_level = 1",
    "headings_l2": "SELECT COUNT(*) FROM recipe_steps WHERE is_heading = 1 AND heading_level = 2",
    "ingredient_lines": "SELECT COUNT(*) FROM recipe_ingredients",
    "waits": "SELECT COUNT(*) FROM recipe_waits",
    "storage": "SELECT COUNT(*) FROM recipe_storage",
    "recipe_notes": "SELECT COUNT(*) FROM recipe_notes",
    "recipe_notes_recipes": "SELECT COUNT(DISTINCT recipe_id) FROM recipe_notes",
    "recipe_notes_original": "SELECT COUNT(*) FROM recipe_notes_original",
    "recipe_note_step_refs": "SELECT COUNT(*) FROM recipe_note_step_refs",
    "snapshots_original": "SELECT COUNT(*) FROM recipe_snapshots WHERE reason = 'original'",
    # ⚠️ THE TOTAL AS WELL AS THE BASELINES, because reason='original' is not the only kind. app.py
    #    writes a reason='cook' snapshot for every logged cook, and recipe_snapshots.cook_log_id is
    #    ON DELETE CASCADE, so a round that removes a cook can take one with it. Counting only the
    #    baselines left the cheap half of the gate blind to exactly that. The table half caught it,
    #    and a gate whose two halves disagree in coverage is one worth making agree.
    "snapshots": "SELECT COUNT(*) FROM recipe_snapshots",
    "migrations": "SELECT COUNT(*) FROM schema_migrations",
    # ⚠️ THE ACCOUNT LAYER IS COUNTED TOO, because a round can move it and the gate has to see
    #    what it moved. All 13 foreign keys pointing at users are ON DELETE NO ACTION, so removing
    #    an account that anything references is REFUSED rather than cascaded: these counts are how
    #    a round declares which of those references it is clearing and proves it cleared no more.
    "users": "SELECT COUNT(*) FROM users",
    "cook_log": "SELECT COUNT(*) FROM cook_log",
    "ratings": "SELECT COUNT(*) FROM ratings",
    "comments": "SELECT COUNT(*) FROM comments",
    "friendships": "SELECT COUNT(*) FROM friendships",
    "shared_posts": "SELECT COUNT(*) FROM shared_posts",
    "invites": "SELECT COUNT(*) FROM invites",
    "cook_photos": "SELECT COUNT(*) FROM cook_photos",
}

# What each count needs, so a database too old to answer it reports None rather than raising. A
# plain name is a TABLE. A pair is a table and a COLUMN that arrived later than the table did, which
# is the same story one step down: recipe_steps exists from the first migration and heading_level
# only from 059, so a reading taken before 059 can count the steps and not the subheadings.
# ⚠️ DECLARED, NOT CAUGHT. Wrapping the counts in `except OperationalError` would also swallow a
# typo in a query, and a gate that quietly reports None where it should report a number is worse
# than one that raises.
_NEEDS = {
    "recipes": "recipes", "steps": "recipe_steps",
    "headings": ("recipe_steps", "is_heading"),
    "headings_l1": ("recipe_steps", "heading_level"), "headings_l2": ("recipe_steps", "heading_level"),
    "ingredient_lines": "recipe_ingredients", "waits": "recipe_waits",
    "storage": "recipe_storage", "recipe_notes": "recipe_notes",
    "recipe_notes_recipes": "recipe_notes", "recipe_notes_original": "recipe_notes_original",
    "recipe_note_step_refs": "recipe_note_step_refs",
    "snapshots_original": ("recipe_snapshots", "reason"), "snapshots": "recipe_snapshots",
    "migrations": "schema_migrations",
    "users": "users", "cook_log": "cook_log", "ratings": "ratings", "comments": "comments",
    "friendships": "friendships", "shared_posts": "shared_posts", "invites": "invites",
    "cook_photos": "cook_photos",
}


def open_ro(db):
    """The ONE way this package opens a database. mode=ro means SQLite refuses a write itself."""
    con = sqlite3.connect(f"file:{pathlib.Path(db)}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def entry_key(e):
    """One annotation entry as a comparable tuple. Long text is cut, so a reworded paragraph is one
    difference rather than a wall of it, and the fields that identify the entry are all kept."""
    return [str(e.get("kind")), str(e.get("type")), str(e.get("field")),
            str(e.get("label") or e.get("text") or "")[:80],
            str(e.get("from") or "")[:80], str(e.get("to") or "")[:80]]


def current_blob(con, rid, have=None):
    """A recipe's content as the app would serialize it RIGHT NOW, through the app's own function.

    ⚠️ A TABLE THE SCHEMA DOES NOT HAVE YET READS AS EMPTY, which is the same answer the counts
    above already give for one. A database older than migration 049 has no recipe_waits and no
    recipe_storage, and that is a legitimate BEFORE side: tests/test_lockstep_guard.py reads this
    state at every point in the folder's history. It costs nothing in the blob either, because
    content_blob omits both keys when the list is empty, so a schema without the tables serializes
    byte-identically to one that has them and no rows."""
    if have is None:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows = lambda table, sql: ([dict(x) for x in con.execute(sql, (rid,))] if table in have else [])
    recipe = dict(con.execute("SELECT * FROM recipes WHERE id = ?", (rid,)).fetchone())
    return ss.content_blob(
        recipe,
        rows("recipe_ingredients",
             "SELECT * FROM recipe_ingredients WHERE recipe_id = ? ORDER BY position, id"),
        rows("recipe_steps", "SELECT * FROM recipe_steps WHERE recipe_id = ? ORDER BY position, id"),
        rows("recipe_waits", "SELECT * FROM recipe_waits WHERE recipe_id = ? ORDER BY position, id"),
        rows("recipe_storage",
             "SELECT * FROM recipe_storage WHERE recipe_id = ? ORDER BY position, id"),
    )


def read_state(db):
    """The whole reading for one database. Opens read-only and writes nothing."""
    con = open_ro(db)
    try:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        short, anns = [], {}
        if "recipe_snapshots" in have:
            stored = {r["recipe_id"]: r["content"] for r in con.execute(
                "SELECT recipe_id, content FROM recipe_snapshots WHERE reason = 'original'")}
            for rid, baseline in sorted(stored.items()):
                cur = current_blob(con, rid, have)
                if cur == baseline:
                    short.append(rid)
                    continue
                entries = snapshot_diff.diff_snapshots(baseline, cur)
                if entries:
                    anns[rid] = sorted(entry_key(e) for e in entries)
        cols = {}

        def answerable(need):
            """Does this database have what the count needs: the table, and the column if named."""
            table, column = (need, None) if isinstance(need, str) else need
            if table not in have:
                return False
            if column is None:
                return True
            if table not in cols:
                cols[table] = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
            return column in cols[table]

        counts = {}
        for name, sql in COUNTS.items():
            counts[name] = con.execute(sql).fetchone()[0] if answerable(_NEEDS[name]) else None
        return {
            "db": str(db),
            "short_circuit": sorted(short),
            "annotations": anns,
            "annotation_entries": sum(len(v) for v in anns.values()),
            "annotation_recipes": len(anns),
            "counts": counts,
            "integrity_check": con.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(con.execute("PRAGMA foreign_key_check").fetchall()),
        }
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="read one database's gate state, read-only")
    ap.add_argument("--db", required=True, help="the database to read (a copy, or live read-only)")
    ap.add_argument("--out", required=True, help="where to write the JSON reading")
    a = ap.parse_args(argv)
    st = read_state(a.db)
    pathlib.Path(a.out).write_text(json.dumps(st, indent=1, ensure_ascii=False, sort_keys=True))
    print(f"  db            : {st['db']}")
    print(f"  opened        : read-only")
    print(f"  short-circuit : {len(st['short_circuit'])} of {st['counts']['recipes']}")
    print(f"  annotations   : {st['annotation_entries']} entries over "
          f"{st['annotation_recipes']} recipes")
    print(f"  integrity     : {st['integrity_check']}   "
          f"fk violations: {st['foreign_key_violations']}")
    for k in sorted(st["counts"]):
        print(f"      {k:24} {st['counts'][k]}")
    print(f"  written       : {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
