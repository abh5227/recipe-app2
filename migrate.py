#!/usr/bin/env python3
"""migrate.py — apply database migrations.

The schema is no longer one schema.sql file; it's the migrations/ folder, applied
in filename order. Each file runs exactly once. The database records which it has
already run (in the schema_migrations table), so re-running this is safe and only
applies what's new. Crucially, migrations CHANGE the database in place — they never
delete it — so your ratings and cook history survive.

⚠️ IT NAMES ITS DATABASE NOW, AND LIVE IS NOT A DEFAULT YOU CAN REACH BY ACCIDENT.

    python3.13 migrate.py --db /tmp/copy.db      rehearse on a copy
    python3.13 migrate.py --i-mean-live          the real one, said out loud
    python3.13 build_db.py                       the setup path, which calls migrate() directly

This existed as a hole in the middle of the repository's own instructions. docs/data-repairs/README.md
says to rehearse the whole chain on a copy of live before running it for real, and migrate.py is step
one of that chain — and it hardcoded live with no way to point it anywhere else, so the instruction
could not be followed as written. The rehearsals were done by rebinding migrate.DB from a throwaway
Python snippet, which works and is not something a person should have to invent.

The module-global DB is still what migrate() reads when it is called with no path, because that is
what the test harness rebinds (make_kitchen) and what build_db.py relies on.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB = BASE_DIR / "recipes.db"
MIGRATIONS_DIR = BASE_DIR / "migrations"


def already_applied(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               filename   TEXT PRIMARY KEY,
               applied_at TEXT NOT NULL DEFAULT (datetime('now'))
           )"""
    )
    conn.commit()
    return {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}


def migrate(verbose=True, db=None):
    """Apply every pending migration to `db`, defaulting to the module-global DB.

    ⚠️ THE DEFAULT IS READ AT CALL TIME, NOT AT IMPORT. tests/harness.py's make_kitchen rebinds
    migrate.DB to the fixture database, and a default captured in the signature would have pinned the
    real one at import and sent every test's migrations into live recipes.db."""
    conn = sqlite3.connect(DB if db is None else db)
    conn.execute("PRAGMA foreign_keys = ON")
    done = already_applied(conn)

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    pending = [f for f in files if f.name not in done]

    if not pending:
        if verbose:
            print("Schema up to date — no migrations to apply.")
        conn.close()
        return

    for f in pending:
        conn.executescript(f.read_text())
        conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (f.name,))
        conn.commit()
        if verbose:
            print(f"Applied migration: {f.name}")
    conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="apply pending SQLite migrations to a database")
    ap.add_argument("--db", default=None,
                    help=f"the database to migrate (default: {DB})")
    ap.add_argument("--i-mean-live", action="store_true",
                    help=f"required to migrate {DB}")
    a = ap.parse_args(argv)
    db = Path(a.db) if a.db else DB
    # ⚠️ THE SHARED GUARD, NOT A FOURTH COPY OF IT. scripts/corpus_guard.py is the one definition of
    #    "this is live, say so out loud". It is imported here rather than at module scope so that
    #    importing migrate (build_db.py, the test harness) still touches nothing: a command line run
    #    is the only thing that can reach live by accident.
    #    ⚠️ AND IT ASKS THE GUARD, NOT THIS CHECKOUT. It used to pass base=BASE_DIR, so run from a
    #    worktree it compared the target against THAT tree's absent recipes.db and refused nothing.
    #    corpus_guard.live_db() is the one absolute answer, the same from every checkout.
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    from corpus_guard import refuse_live
    refuse_live(db, a.i_mean_live)
    migrate(db=db)


if __name__ == "__main__":
    main()
