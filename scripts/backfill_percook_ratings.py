#!/usr/bin/env python3
"""scripts/backfill_percook_ratings.py — move every recipe-level rating onto the cook it was a verdict on.

Migration 048 makes a rating a property of ONE COOKING (cook_log.rating) instead of one per recipe. This
script carries the existing rows across. The `ratings` table is READ AND LEFT ALONE — not emptied, not
dropped — so it stays a frozen copy of the pre-migration state and is the rollback for this script.

⚠️ THE ATTACH RULE, IN ORDER. Each clause is narrower than the one below it, so the first that matches
wins and the result never depends on row order:

  1. ONE COOK                the rating goes to it.                              (measured: 118 of 120)
  2. A 'rating-inferred' COOK   that row was created to carry this rating, so it gets it.        (1)
  3. A COOK DATED == date(rated_on)   the verdict was recorded the day of that cook.             (1)
  4. THE EARLIEST COOK       a last resort so the rule cannot fall off the end.                  (0)
  5. NO COOK AT ALL          ⚠️ STOP. Never invent a cook to hold a verdict. A rating with nowhere
                             to hang is a real question about what the rating meant, and it is
                             Andy's to answer, not this script's to paper over.

Cooks are matched BY THE SAME USER as the rating (ratings.user_id = cook_log.user_id). A rating by one
person must never land on another person's cooking, which is the cross-bleed undo_cook already guards.

rated_on moves to cook_log.rated_at, so the verdict's timestamp survives separately from cooked_on.
Without it, the 108 ratings stamped in one bulk import on 2026-07-01 would all read as though they were
rated on the day of the cook.

⚠️ THE SELF-CHECK IS THE POINT, and it runs on live exactly as it runs in the dry run. Before committing
anything the script proves that every rating landed, that no cook received two, and that the NEW headline
(AVG of rated cooks) equals the OLD stored value for every rated recipe. Any mismatch aborts the
transaction. A silent partial move is the failure worth engineering against.

SQLite only. Postgres gets the schema from the Alembic revision and carries no legacy ratings rows; if
it ever does, this rule is what to port.

    python3.13 scripts/backfill_percook_ratings.py --db /path/clone.db --dry-run   # moves nothing
    python3.13 scripts/backfill_percook_ratings.py --db /path/clone.db             # clone first
    python3.13 scripts/backfill_percook_ratings.py                                 # live (back it up)
"""
import argparse
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "recipes.db"

MIGRATION = "048_ratings_cluster.sql"


def ensure_schema(conn, migrations_dir=None):
    """Apply migration 048 if this DB has not seen it, and stamp it so migrate/build_db skip it later.
    The option-(a) idiom from backfill_rescoping.py: a data-coupled script that needs its own DDL applies
    it and records it, rather than depending on the order someone runs two commands in.

    ⚠️ THE SCHEMA STEP COMMITS, AND --dry-run DOES NOT UNDO IT. executescript issues its own COMMIT, so
    the columns cannot be rolled back with the data. Stamping in the same breath is what keeps the DB
    consistent either way: a dry run leaves a migrated, correctly-stamped database with its ratings not
    yet moved, which is a state migrate and build_db both understand. The alternative leaves columns
    that exist while schema_migrations says they do not, and the next migrate run then fails."""
    done = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
    if MIGRATION in done:
        return False
    path = (migrations_dir or (REPO / "migrations")) / MIGRATION
    conn.executescript(path.read_text())
    conn.execute("INSERT OR IGNORE INTO schema_migrations (filename, applied_at) VALUES (?, datetime('now'))",
                 (MIGRATION,))
    conn.commit()
    return True


def pick_cook(conn, recipe_id, user_id, rated_on):
    """The 5-clause rule. Returns (cook_log_id, clause_name) or (None, 'no cook') for clause 5."""
    cooks = conn.execute(
        "SELECT id, cooked_on, source FROM cook_log WHERE recipe_id = ? AND user_id = ? "
        "ORDER BY cooked_on, id", (recipe_id, user_id)).fetchall()
    if not cooks:
        return None, "no cook"
    if len(cooks) == 1:
        return cooks[0][0], "one cook"
    inferred = [c for c in cooks if c[2] == "rating-inferred"]
    if inferred:
        return inferred[0][0], "rating-inferred cook"
    same_day = [c for c in cooks if c[1] == (rated_on or "")[:10]]
    if same_day:
        return same_day[0][0], "cook dated == rated_on"
    return cooks[0][0], "earliest cook"


def run(db_path=None, dry_run=False, verbose=True):
    conn = sqlite3.connect(db_path or DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        applied = ensure_schema(conn)

        already = conn.execute("SELECT COUNT(*) FROM cook_log WHERE rating IS NOT NULL").fetchone()[0]
        if already:
            raise SystemExit(f"refusing: {already} cook_log rows already carry a rating — this looks applied")

        rows = conn.execute("SELECT recipe_id, user_id, rating, rated_on FROM ratings "
                            "ORDER BY recipe_id, user_id").fetchall()
        clauses = {}
        taken = {}
        for recipe_id, user_id, rating, rated_on in rows:
            cook_id, clause = pick_cook(conn, recipe_id, user_id, rated_on)
            if cook_id is None:
                raise SystemExit(
                    f"STOP: {recipe_id} (user {user_id}) is rated {rating} and has no cook by that user. "
                    "Clause 5 — a verdict with nothing to hang on is a question for Andy, not a guess.")
            if cook_id in taken:
                raise SystemExit(f"STOP: cook {cook_id} picked twice ({taken[cook_id]} and {recipe_id})")
            taken[cook_id] = recipe_id
            clauses[clause] = clauses.get(clause, 0) + 1
            conn.execute("UPDATE cook_log SET rating = ?, rated_at = ? WHERE id = ?",
                         (float(rating), rated_on, cook_id))

        moved = conn.execute("SELECT COUNT(*) FROM cook_log WHERE rating IS NOT NULL").fetchone()[0]
        if moved != len(rows):
            raise SystemExit(f"STOP: {len(rows)} ratings but {moved} cook rows carry one")

        # ⚠️ The headline check. The NEW number is AVG over rated cooks; it must equal the OLD stored
        # rating for every rated recipe, or the display changes under Andy without him asking.
        drift = conn.execute("""
            SELECT r.recipe_id, r.rating, AVG(c.rating)
              FROM ratings r JOIN cook_log c
                ON c.recipe_id = r.recipe_id AND c.user_id = r.user_id AND c.rating IS NOT NULL
             GROUP BY r.recipe_id, r.user_id, r.rating
            HAVING AVG(c.rating) <> r.rating""").fetchall()
        if drift:
            raise SystemExit(f"STOP: {len(drift)} recipes would change their displayed rating: {drift[:5]}")

        covered = conn.execute("""
            SELECT COUNT(*) FROM ratings r WHERE NOT EXISTS
              (SELECT 1 FROM cook_log c WHERE c.recipe_id = r.recipe_id
                 AND c.user_id = r.user_id AND c.rating IS NOT NULL)""").fetchone()[0]
        if covered:
            raise SystemExit(f"STOP: {covered} ratings have no rated cook after the move")

        if verbose:
            print(f"migration 048 : {'applied + stamped here' if applied else 'already present'}")
            print(f"ratings read  : {len(rows)}")
            print(f"cooks rated   : {moved}")
            for name in ("one cook", "rating-inferred cook", "cook dated == rated_on", "earliest cook"):
                print(f"  clause: {name:<24} {clauses.get(name, 0)}")
            print(f"headline drift: {len(drift)} recipes  (0 = display unchanged)")
            print(f"ratings table : {conn.execute('SELECT COUNT(*) FROM ratings').fetchone()[0]} rows, left frozen")

        if dry_run:
            conn.rollback()
            if verbose:
                print("DRY RUN - the ratings move was rolled back "
                      "(migration 048 itself stays applied and stamped, see ensure_schema)")
        else:
            conn.commit()
            if verbose:
                print("committed")
        return {"ratings": len(rows), "moved": moved, "clauses": clauses, "drift": len(drift)}
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Move recipe-level ratings onto the cook they were a verdict on.")
    ap.add_argument("--db", default=None, help="SQLite DB path (default: the repo's recipes.db)")
    ap.add_argument("--dry-run", action="store_true", help="do everything, then roll back")
    args = ap.parse_args()
    run(db_path=args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
