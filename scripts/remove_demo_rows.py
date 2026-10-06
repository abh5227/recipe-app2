#!/usr/bin/env python3
"""Remove the 7 demo rows left under the real account. Dry run by default.

    python3.13 scripts/remove_demo_rows.py --db <copy.db>                 # dry run
    python3.13 scripts/remove_demo_rows.py --db <copy.db> --apply
    python3.13 scripts/remove_demo_rows.py --db recipes.db --apply --i-mean-live

⚠️ WHAT THESE ROWS ARE. Two ad hoc seeding runs on 2026-07-25 and 2026-07-26 wrote a demo social
layer while the feed was being built, and some of what they wrote carries the REAL account's user
id. scripts/remove_demo_accounts.py took the rows belonging to the three demo accounts on
2026-10-05. These 7 look like the owner's own work and are not: 3 shared posts, 1 comment and 3
logged cooks. docs/data-repairs/demo-data-2026-07.md is the record.

⚠️ AN ID IS NOT ENOUGH, SO EVERY ROW CARRIES ITS SIGNATURE TOO. An id is a position in a table, and
a row id that meant one thing when this was written can mean another by the time it runs. Each row
below states what it must still look like, and a single clause that no longer holds stops the whole
run rather than that row. The signatures are the measurements the investigation made:

  - the seeding runs stamped every row they wrote with ONE wall-clock minute and second, "30:45" for
    the 2026-07-25 run and "16:26" for the 2026-07-26 run. That is what gives a script away, and
    it is why these rows are known to be machine-made at all.
  - the three cooks carry source 'demo-seed', which no route writes.
  - and they carry NO rating, NO caption and NO photo. That is the clause that matters most: a cook
    is the outcome data this whole app exists to capture, and a demo-seeded cook somebody later
    rated through the UI would be a person's own work under a machine's source. `edit_cook` writes
    rating, rated_at and caption onto an existing row and never rewrites `source`, so the source
    alone cannot tell the two apart. The same defect was found in remove_demo_accounts.py by
    review; here it is a refusal from the start.

⚠️ THE OWNER IS NAMED BY EMAIL, NEVER BY ID, the lesson remove_demo_accounts.py states. These rows
are being removed BECAUSE they carry that account's id, so the id has to be resolved from the email
rather than written in.

⚠️ AND THE ORDER IS CHOSEN SO NOTHING IS TAKEN BY SURPRISE. Deleting comments, then posts, then
cooks means every row in the list is removed by a statement that names it rather than by a cascade
from another.

⚠️ BUT THE ORDER IS NOT A PROOF, AND AN EARLIER VERSION OF THIS FILE CLAIMED IT WAS. It enumerated
two cascades from memory and concluded "a cascade has nothing left to reach". The schema has FOUR
children of these three tables, not two:

    shared_posts.cook_log_id     -> cook_log.id       ON DELETE CASCADE
    comments.post_id             -> shared_posts.id   ON DELETE CASCADE
    cook_photos.cook_log_id      -> cook_log.id       ON DELETE CASCADE
    recipe_snapshots.cook_log_id -> cook_log.id       ON DELETE CASCADE

`recipe_snapshots` was in no clause at all, and `app.py` writes a `reason='cook'` snapshot for every
logged cook, so a snapshot is the ORDINARY shape for a cook_log row. The ordering also only ever
protected rows this script names: measured on the script's own fixture, a comment the owner wrote
today on demo post 2 and a post the owner shared today of demo cook 212 were both deleted by a
cascade, with 7 printed, exit 0, and `PRAGMA foreign_key_check` clean, because a cascade KEEPS
integrity and `rowcount` counts only direct deletes.

So the claim is checked twice instead of asserted. `unnamed_dependents` reads the cascade children
OUT OF THE SCHEMA and refuses if anything this script does not name points at one of the 7, which a
dry run shows. And after the deletes, before the commit, every table's row count is compared against
its own before-state and the run is rolled back unless exactly the named rows moved and nothing
else did.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

# One guard, imported, never copied.
from corpus_guard import refuse_live  # noqa: E402

# The account these rows are wrongly attributed to. Named, not parameterized.
OWNER_EMAIL = "andyhannah2014@gmail.com"

# The minute and second every row of each ad hoc seeding run carries. Read as substr(ts, 15, 5).
SEEDING_STAMPS = ("30:45", "16:26")

_STAMPED = "substr({col}, 15, 5) IN ('" + "', '".join(SEEDING_STAMPS) + "')"

# No photo points at the cook. cook_photos.cook_log_id is nullable, so this is a real question.
_NO_PHOTO = "NOT EXISTS (SELECT 1 FROM cook_photos p WHERE p.cook_log_id = cook_log.id)"

# The two signatures, each stated once. A post and a comment are known by their stamp, a cook by
# its source and by carrying none of a person's own work.
#
# ⚠️ WRITTEN AS SHARED TUPLES RATHER THAN REPEATED PER ROW, so "what makes a cook a demo cook" has
# one answer. The rows below differ in their id and in what they are, which is the only thing that
# should differ between them.
_OWNER = "user_id = :uid"
_SHARED_CHECKS = (
    ("shared under the owner's id", _OWNER),
    ("stamped by a seeding run", _STAMPED.format(col="created_at")),
)
_COMMENT_CHECKS = (
    ("written under the owner's id", "author_id = :uid"),
    ("stamped by a seeding run", _STAMPED.format(col="created_at")),
)
_COOK_CHECKS = (
    ("logged under the owner's id", _OWNER),
    ("machine-made by source", "source = 'demo-seed'"),
    ("carries no rating", "rating IS NULL"),
    ("carries no caption", "caption IS NULL"),
    ("carries no photo", _NO_PHOTO),
)
_POINTS_AT_A_DEMO_COOK = (
    "points at a demo cook",
    "cook_log_id IN (SELECT id FROM cook_log WHERE source = 'demo-seed')",
)

# (table, id, what it is, the signature). Deletion order is this order: comments, posts, cooks.
DEMO_ROWS = (
    ("comments", 3, 'the reply "will send it over tonight" on post 8', _COMMENT_CHECKS),
    ("shared_posts", 2, 'the recipe post "proud of this one" (bbq-gulf-snapper)', _SHARED_CHECKS),
    ("shared_posts", 8, 'the cook post "sunday bake with the kids" (1-2-3-4-5-tofu)',
     _SHARED_CHECKS + (_POINTS_AT_A_DEMO_COOK,)),
    ("shared_posts", 9, "the recipe post with no caption (aloo-potato-parathas)", _SHARED_CHECKS),
    ("cook_log", 211, "the demo cook of 1-2-3-4-5-tofu on 2026-07-25", _COOK_CHECKS),
    ("cook_log", 212, "the demo cook of acqua-pazza on 2026-07-22", _COOK_CHECKS),
    ("cook_log", 213, "the demo cook of adventist-gumbo on 2026-07-20", _COOK_CHECKS),
)


def owner_id(con, email=OWNER_EMAIL):
    row = con.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    return row[0] if row else None


def _where(checks):
    """The row's whole signature as one WHERE, which is what BOTH the count and the DELETE use.

    ⚠️ THE WRITE CARRIES THE SIGNATURE, NOT ONLY THE CHECK THAT AUTHORIZED IT. A verify-then-delete
    on a bare id is correct only while nothing changes in between."""
    return "id = :rid AND " + " AND ".join(f"({sql})" for _why, sql in checks)


def mismatches(con, uid):
    """Every clause that no longer holds, as readable lines. Empty means the picture is unchanged."""
    out = []
    for table, rid, what, checks in DEMO_ROWS:
        params = {"rid": rid, "uid": uid}
        if not con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE id = :rid', params).fetchone()[0]:
            out.append(f"{table} {rid} ({what}) is not in this database at all")
            continue
        for why, sql in checks:
            ok = con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE id = :rid AND ({sql})',
                             params).fetchone()[0]
            if not ok:
                out.append(f"{table} {rid} ({what}) is no longer {why}")
    return out


def unlisted_demo_cooks(con):
    """A cook_log row carrying a demo source that this script does not name.

    ⚠️ STATED OVER THE SOURCE, NOT OVER THE TIMESTAMP STAMP. A minute-and-second pair is evidence
    about rows that are already known to be machine-made, and it is NOT a safe sweep on its own:
    with roughly 1,500 timestamped personal rows, an ordinary row landing on one of two given
    minute:second pairs by chance is likelier than not. `source` is written by no route, so it is
    the one clause that cannot collide with a real row."""
    listed = {rid for table, rid, _w, _c in DEMO_ROWS if table == "cook_log"}
    rows = con.execute("SELECT id, recipe_id, source, user_id, rating, caption FROM cook_log "
                       "WHERE source LIKE 'demo%' ORDER BY id").fetchall()
    return [dict(r) for r in rows if r["id"] not in listed]


def _id_column(con, table):
    """`id` where the table has one, else `rowid`. A child table is not required to have an id."""
    cols = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
    return "id" if "id" in cols else "rowid"


def cascade_children(con, table):
    """Every (child table, column) whose foreign key into `table` is ON DELETE CASCADE.

    ⚠️ READ OUT OF THE SCHEMA, NEVER OUT OF A LIST SOMEBODY REMEMBERED. The list this file used to
    carry in prose was short by two, and one of those two is written for every logged cook. A child
    added to the schema tomorrow is covered by this the day it lands."""
    out = []
    for (child,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                "AND name NOT LIKE 'sqlite_%'"):
        for row in con.execute(f'PRAGMA foreign_key_list("{child}")'):
            if row["table"] == table and (row["on_delete"] or "").upper() == "CASCADE":
                out.append((child, row["from"]))
    return sorted(out)


def unnamed_dependents(con):
    """Anything a cascade would take that this script does not name.

    The rows this script names may point at each other: comment 3 is on post 8, and post 8 points at
    cook 211. Those are accounted for, which is what the deletion order is about. Anything ELSE
    pointing at one of the 7 is a row somebody made, and taking it silently is the defect this
    refusal exists to stop."""
    named = {(t, rid) for t, rid, _w, _c in DEMO_ROWS}
    out = []
    for table, rid, what, _checks in DEMO_ROWS:
        for child, col in cascade_children(con, table):
            idcol = _id_column(con, child)
            for row in con.execute(
                    f'SELECT "{idcol}" AS cid FROM "{child}" WHERE "{col}" = ?', (rid,)):
                if (child, row["cid"]) not in named:
                    out.append(f"{child} {row['cid']} points at {table} {rid} ({what}) through "
                               f"{child}.{col}, and a CASCADE would take it unnamed")
    return out


def table_counts(con):
    """Every table's row count, read from sqlite_master so nothing is left out by being forgotten."""
    return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                    "AND name NOT LIKE 'sqlite_%'")}


def expected_moves():
    """How many rows each table should lose, derived from the list rather than written out."""
    moves = {}
    for table, _rid, _w, _c in DEMO_ROWS:
        moves[table] = moves.get(table, 0) + 1
    return moves


def unexplained_moves(before, after):
    """Every table whose count moved by something other than the rows this script named."""
    want = expected_moves()
    out = []
    for table in sorted(set(before) | set(after)):
        moved = before.get(table, 0) - after.get(table, 0)
        if moved != want.get(table, 0):
            out.append(f"{table}: {before.get(table)} -> {after.get(table)}, a change of {moved} "
                       f"where this script accounts for {want.get(table, 0)}")
    return out


def _each_row(con, uid, apply_it, out):
    """Count or delete each row by its own whole signature, and report what happened per row."""
    total = 0
    for table, rid, what, checks in DEMO_ROWS:
        params = {"rid": rid, "uid": uid}
        where = _where(checks)
        # The same WHERE either way, so the dry run counts exactly what the apply deletes.
        n = con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where}', params).fetchone()[0]
        if apply_it:
            n = con.execute(f'DELETE FROM "{table}" WHERE {where}', params).rowcount
        total += n
        out(f"    {f'{table} {rid}':<18} {n}  {what}")
    return total


def run(db, apply_it, out=print):
    import sqlite3
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")       # the cascades only behave when they are on
    try:
        uid = owner_id(con)
        if uid is None:
            out(f"\n  REFUSING: there is no account {OWNER_EMAIL} in this database, so there is no "
                f"owner whose rows these are")
            return 1
        out(f"  owner    : {OWNER_EMAIL} id={uid}")

        bad = mismatches(con, uid)
        if bad:
            out("\n  REFUSING: the rows are not what this script was written against:")
            for line in bad:
                out(f"    {line}")
            out("\n  A row that no longer matches its signature is a decision, not a cleanup.")
            return 1

        extra = unlisted_demo_cooks(con)
        if extra:
            out("\n  REFUSING: cook_log carries demo rows this script does not name:")
            for r in extra:
                out(f"    cook {r['id']} {r['recipe_id']} source={r['source']} "
                    f"user={r['user_id']} rating={r['rating']} caption={r['caption']!r}")
            return 1

        hangers = unnamed_dependents(con)
        if hangers:
            out("\n  REFUSING: a CASCADE would take rows this script does not name:")
            for line in hangers:
                out(f"    {line}")
            out("\n  Those rows are somebody's, and taking them silently is not a cleanup.")
            return 1

        before = table_counts(con)
        out("\n  plan:" if not apply_it else "\n  applying:")
        total = _each_row(con, uid, apply_it, out)

        if total != len(DEMO_ROWS):
            con.rollback()
            out(f"\n  REFUSING: {total} rows matched and this script names {len(DEMO_ROWS)}. "
                f"Nothing written.")
            return 1

        if apply_it:
            # ⚠️ THE WHOLE DATABASE IS COMPARED BEFORE THE COMMIT, NOT THE SEVEN rowcounts.
            # `rowcount` counts direct deletes only, and a cascade keeps integrity, so neither it
            # nor PRAGMA foreign_key_check can see a row taken by a cascade. This can.
            drifted = unexplained_moves(before, table_counts(con))
            if drifted:
                con.rollback()
                out("\n  ROLLED BACK: tables moved that this script does not account for:")
                for line in drifted:
                    out(f"    {line}")
                return 1
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
            if fk:
                con.rollback()
                out(f"\n  ROLLED BACK: {len(fk)} foreign-key violations after the deletes")
                return 1
            con.commit()
            out(f"\n  applied. {total} rows deleted, each by a statement that named it, and "
                f"every other table in the database verified unchanged before the commit.")
        else:
            con.rollback()
            out(f"\n  dry run, nothing written. {total} rows would go.")
            out("  re-run with --apply to write")
        return 0
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="remove the 7 demo rows left under the real account")
    ap.add_argument("--db", required=True,
                    help="the database to work on (a copy, unless you mean live)")
    ap.add_argument("--apply", action="store_true", help="write; without it this is a dry run")
    ap.add_argument("--i-mean-live", action="store_true", help="required to touch the live database")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)
    print(f"  database : {a.db}")
    return run(a.db, a.apply)


if __name__ == "__main__":
    sys.exit(main())
