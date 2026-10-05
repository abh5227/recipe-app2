#!/usr/bin/env python3
"""Remove named demo accounts and the demo social rows they carry. Dry run by default.

    python3.13 scripts/remove_demo_accounts.py --db <copy.db>                 # dry run
    python3.13 scripts/remove_demo_accounts.py --db <copy.db> --apply
    python3.13 scripts/remove_demo_accounts.py --db recipes.db --apply --i-mean-live

⚠️ NOTHING CASCADES HERE, SO EVERY REFERENCE IS CLEARED ON PURPOSE. All 13 foreign keys pointing at
`users` are ON DELETE NO ACTION, which means an account anything still references cannot be deleted
at all: SQLite refuses the row. That is the right default and it makes this script's job explicit
rather than implicit. The order below is the dependency order, and the final DELETE on `users` is
the proof: it only succeeds once nothing points at them.

⚠️ IT REFUSES TO TOUCH AN ACCOUNT THAT OWNS ANYTHING REAL. A recipe, a snapshot, a logged cook that
is not a demo row, a queue entry, a cook photo or a library row makes an account a real user,
whatever its email looks like, and this script stops rather than deciding what should happen to
that. Measured on live before it was written: the three demo accounts own 0 of each, their 4
cook_log rows are all `demo-seed` or `demo-2b` and none is rated, and all 300 recipes, 306
snapshots, 120 ratings and 135 cook photos are the real account's.

⚠️ AND IT DELETES THE CALLER'S OWN ROWS WHERE A POST CASCADE REACHES THEM, WHICH IS STATED AND NOT
HIDDEN. `comments.post_id -> shared_posts.id` is ON DELETE CASCADE, so removing a demo account's
post removes every comment on it, including the real account's own words. On live that is one
comment, "how hot was the pan?" on a demo post. The dry run prints each such row before anything
happens, because a person should see their own sentence before it goes.

⚠️ THE ACCOUNTS ARE NAMED BY EMAIL, NEVER BY ID. An id is a position in a table and the wrong one
deletes the wrong person. An email is the thing a human recognizes, and an email this script cannot
find is reported rather than skipped.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus_guard import refuse_live        # noqa: E402  one guard, imported, never copied

# The accounts this script exists to remove. Stated here so a run cannot be pointed at a different
# set from the command line: removing an account is not a thing to parameterize.
DEMO_EMAILS = ("test@test.com", "alex@demo.test", "mira@demo.test")

# The cook_log sources a demo setup wrote. A row carrying one of these is machine-made, and every
# one of live's demo rows carries one. Anything else is somebody's actual cook.
DEMO_COOK_SOURCES = ("demo-seed", "demo-2b")

# Owning any of these makes an account a real user, and this script refuses rather than deciding.
# Each entry is (table, column, what to call it, an extra condition or None).
#
# ⚠️ cook_log IS ON THIS LIST AND ratings IS THE ONE THAT CANNOT FIRE. Migration 048 moved ratings
# INTO cook_log.rating, and nothing outside the tests and one applied backfill has written the
# `ratings` table since. So the refusal was guarding a frozen table while cook_log, which holds the
# outcome data this whole app exists to capture, sat on the delete list with no refusal at all.
# Measured: an account with 25 cooks of which 12 were rated was deleted with no REFUSING line and
# exit 0. `ratings` stays on the list because the table still exists and a row in it would still be
# real, and it is marked so nobody reads its silence as coverage.
#
# ⚠️ AND THE cook_log CHECK EXCLUDES THE DEMO SOURCES, because the demo rows are exactly what this
# script is for. Live's three accounts hold 4 cook_log rows between them, all `demo-seed` or
# `demo-2b` and none rated, so this refusal is silent on live as it stands and fires the moment a
# real cook is logged from one of these accounts. test@test.com is precisely the account somebody
# logs a cook from while testing.
#
# ⚠️ A RATING OR A CAPTION OVERRIDES THE SOURCE, BECAUSE THE SOURCE IS NEVER REWRITTEN. `edit_cook`
# writes rating, rated_at and caption onto an EXISTING row and leaves `source` alone, so a
# demo-seeded cook that a person later rated through the UI is machine-made by its source and
# somebody's own work by its content. Measured: a demo-seed row carrying rating 4.5 and a caption
# was deleted with no refusal and exit 0, and the gate could not see it either, because
# `cook_log 137 -> 133` reads the same whether or not a rating went with the rows.
REAL_OWNERSHIP = (
    ("recipes", "owner", "recipes", None),
    ("recipe_snapshots", "user_id", "snapshots", None),
    ("cook_log", "user_id", "logged cooks that carry a person's own work",
     "source IS NULL OR source NOT IN ('demo-seed', 'demo-2b') "
     "OR rating IS NOT NULL OR caption IS NOT NULL"),
    ("ratings", "user_id", "rows in the frozen ratings table", None),
    ("recipe_queue", "user_id", "queue entries", None),
    ("cook_photos", "user_id", "cook photos", None),
    ("ingredients", "owner", "library rows", None),
)


def _ids(con, emails):
    rows = {e: None for e in emails}
    for e in emails:
        r = con.execute("SELECT id FROM users WHERE email = ?", (e,)).fetchone()
        rows[e] = r[0] if r else None
    return rows


def real_holdings(con, ids):
    """What these accounts own that makes them real users. Empty means they are safe to remove."""
    found = []
    for table, col, label, extra in REAL_OWNERSHIP:
        where = f'"{col}" = ?' + (f" AND ({extra})" if extra else "")
        for e, uid in ids.items():
            if uid is None:
                continue
            n = con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where}', (uid,)).fetchone()[0]
            if n:
                found.append(f"{e} owns {n} {label}")
    return found


def collateral(con, ids):
    """Rows belonging to OTHER accounts that a cascade here would take. Printed before anything."""
    uids = [u for u in ids.values() if u is not None]
    if not uids:
        return []
    marks = ",".join("?" * len(uids))
    return [dict(zip(("id", "author", "body", "post"), r)) for r in con.execute(
        f"""SELECT c.id, u.email, c.body, c.post_id
              FROM comments c
              JOIN shared_posts p ON p.id = c.post_id
              LEFT JOIN users u ON u.id = c.author_id
             WHERE p.user_id IN ({marks}) AND c.author_id NOT IN ({marks})""",
        uids + uids)]


def plan(con, ids):
    """Every delete this run would make, in dependency order, as (label, sql, params)."""
    uids = [u for u in ids.values() if u is not None]
    if not uids:
        return []
    marks = ",".join("?" * len(uids))
    return [
        ("comments they wrote", f"DELETE FROM comments WHERE author_id IN ({marks})", uids),
        # their posts, which cascades the comments ON those posts (anyone's)
        ("posts they shared", f"DELETE FROM shared_posts WHERE user_id IN ({marks})", uids),
        # their cooks, which cascades any post still pointing at one
        ("cooks they logged", f"DELETE FROM cook_log WHERE user_id IN ({marks})", uids),
        ("friendships either side",
         f"DELETE FROM friendships WHERE requester_id IN ({marks}) OR addressee_id IN ({marks})",
         uids + uids),
        ("invites they used or made",
         f"DELETE FROM invites WHERE used_by IN ({marks}) OR created_by IN ({marks})", uids + uids),
        # last, and it only succeeds because every NO ACTION reference above is gone
        ("the accounts", f"DELETE FROM users WHERE id IN ({marks})", uids),
    ]


def _delete_parts(sql):
    """A DELETE's table and its WHERE, so a dry run can COUNT the identical set.

    ⚠️ ONE WHERE, TWO USES. Writing the count as its own query is how a preview stops describing
    the run it previews. The plan above is the only place a condition is written."""
    head, where = sql.split(" WHERE ", 1)
    return head.split()[2].strip('"'), where


def run(db, apply_it, out=print):
    import sqlite3
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")       # NO ACTION only bites when they are on
    try:
        ids = _ids(con, DEMO_EMAILS)
        for e, uid in ids.items():
            out(f"  {e:<22} {'id=' + str(uid) if uid else 'NOT PRESENT'}")
        if not any(v is not None for v in ids.values()):
            out("  nothing to do: none of these accounts is in this database")
            return 0

        holdings = real_holdings(con, ids)
        if holdings:
            out("\n  REFUSING: these accounts own real content, which is a decision, not a cleanup:")
            for h in holdings:
                out(f"    {h}")
            return 1

        hit = collateral(con, ids)
        if hit:
            out("\n  ⚠️ these rows belong to ANOTHER account and a post cascade will take them:")
            for c in hit:
                out(f"    comment {c['id']} by {c['author']} on post {c['post']}: {c['body']!r}")

        out("\n  plan:" if not apply_it else "\n  applying:")
        total = 0
        for label, sql, params in plan(con, ids):
            # The same WHERE either way, so the dry run counts exactly what the apply would delete.
            # A second hand-written query here is how a preview and a run drift apart.
            table, where = _delete_parts(sql)
            n = con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where}', params).fetchone()[0]
            if apply_it:
                n = con.execute(sql, params).rowcount
            total += n
            out(f"    {label:<28} {n}")
        left = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if apply_it:
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
            if fk:
                con.rollback()
                out(f"\n  ROLLED BACK: {len(fk)} foreign-key violations after the deletes")
                return 1
            con.commit()
            out(f"\n  applied. {total} rows deleted DIRECTLY, {left} account(s) left")
            out("  (the total counts the six statements above. Rows removed by a CASCADE from one "
                "of them, such as a comment on a deleted post, are not in it and are named "
                "individually in the warning before the plan.)")
        else:
            con.rollback()
            out(f"\n  dry run, nothing written. {total} rows would go DIRECTLY, "
                f"{left - len([v for v in ids.values() if v])} account(s) would be left")
            out("  (plus anything a CASCADE takes with them, named above rather than counted here.)")
            out("  re-run with --apply to write")
        return 0
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="remove the named demo accounts and their demo rows")
    ap.add_argument("--db", required=True, help="the database to work on (a copy, unless you mean live)")
    ap.add_argument("--apply", action="store_true", help="write; without it this is a dry run")
    ap.add_argument("--i-mean-live", action="store_true", help="required to touch the live database")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)
    print(f"  database : {a.db}")
    return run(a.db, a.apply)


if __name__ == "__main__":
    sys.exit(main())
