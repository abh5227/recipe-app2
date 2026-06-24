#!/usr/bin/env python3
"""migrate.py — apply database migrations.

The schema is no longer one schema.sql file; it's the migrations/ folder, applied
in filename order. Each file runs exactly once. The database records which it has
already run (in the schema_migrations table), so re-running this is safe and only
applies what's new. Crucially, migrations CHANGE the database in place — they never
delete it — so your ratings and cook history survive.

Run it directly with:  python3 migrate.py
(build_db.py also calls it for you.)
"""
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


def migrate(verbose=True):
    conn = sqlite3.connect(DB)
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


if __name__ == "__main__":
    migrate()
