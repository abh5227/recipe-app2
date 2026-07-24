#!/usr/bin/env python3
"""scripts/backfill_rescoping.py — Rescoping R2+R3: one-time backfill + ratings composite-PK rebuild.

IRREVERSIBLE on SQLite (it DROPs + rebuilds the ratings table — the only undo is a backup). Dialect-aware
(SQLite: dev / the real recipes.db; Postgres: CI / prod). DATA-COUPLED: assigns every existing recipe /
cook / rating to ONE owner (--owner-email), then makes ratings' PK composite (recipe_id, user_id) with
user_id NOT NULL — the backfill value feeds the NOT-NULL rebuild, so both must happen in one transaction.
Refuses to double-apply.

recipes.owner and cook_log.user_id are backfilled but STAY NULLABLE (per the locked decisions); only
ratings.user_id becomes NOT NULL, via the composite PK.

Target DB: DATABASE_URL if set (Postgres), else sqlite:///<--db> (default recipes.db). Byte-identity: the
SQLite rebuild copies rated_on EXPLICITLY so the DEFAULT (datetime('now')) never fires; ratings keep their
original rating + rated_on. Run against a CLONE first.

    python3.13 scripts/backfill_rescoping.py --owner-email you@example.com --db /path/clone.db
    DATABASE_URL=postgresql+psycopg://… python3.13 scripts/backfill_rescoping.py --owner-email you@example.com
"""
import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, event, text

REPO = Path(__file__).resolve().parent.parent

# The dual-source migration this script's rebuild corresponds to (option a): after the script rebuilds
# the EXISTING SQLite DB, it marks 019 applied in schema_migrations so build_db/migrate won't rebuild
# ratings a second time. Fresh builds get the composite PK from 019 itself (its 0-row rebuild).
R3_MIGRATION = "019_ratings_composite_pk.sql"


def resolve_owner(conn, email):
    """The owner account. Explicit --owner-email wins (error if unknown). Else default to the SOLE
    is_admin=1 user; refuse (require the arg) if 0 or >1 admins — never blindly guess."""
    if email:
        row = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email.strip().lower()}).first()
        if row is None:
            raise SystemExit(f"error: no user with email {email!r} — create the account first (create_admin.py)")
        return row[0]
    admins = [r[0] for r in conn.execute(text("SELECT id FROM users WHERE is_admin = 1 ORDER BY id"))]
    if len(admins) == 1:
        return admins[0]
    raise SystemExit(f"error: --owner-email is required ({len(admins)} admin users found — refusing to guess)")


def ratings_user_id_not_null(conn, dialect):
    """True once the composite-PK rebuild has run (ratings.user_id is NOT NULL) — the refuse-if-done signal."""
    if dialect == "sqlite":
        return any(r[1] == "user_id" and r[3] == 1 for r in conn.execute(text("PRAGMA table_info(ratings)")))
    row = conn.execute(text(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'ratings' AND column_name = 'user_id'"
    )).first()
    return row is not None and row[0] == "NO"


def _rebuild_ratings_sqlite(conn):
    """005_cascade_history.sql pattern: new table with the composite PK + PRESERVED ON DELETE CASCADE,
    copy rows carrying rated_on EXPLICITLY (byte-identity — the DEFAULT never fires), drop + rename.
    user_id is copied from the (already-backfilled) column, so a stray NULL would fail the NOT NULL here."""
    conn.execute(text(
        "CREATE TABLE ratings_new ("
        " recipe_id TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,"
        " user_id   INTEGER NOT NULL REFERENCES users(id),"
        " rating    INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),"
        " rated_on  TEXT    NOT NULL DEFAULT (datetime('now')),"
        " PRIMARY KEY (recipe_id, user_id))"
    ))
    conn.execute(text(
        "INSERT INTO ratings_new (recipe_id, user_id, rating, rated_on) "
        "SELECT recipe_id, user_id, rating, rated_on FROM ratings"
    ))
    conn.execute(text("DROP TABLE ratings"))
    conn.execute(text("ALTER TABLE ratings_new RENAME TO ratings"))


def _rebuild_ratings_pg(conn):
    """In place (no copy → no rated_on-default risk): drop the sole PK, tighten user_id, add composite PK."""
    conn.execute(text("ALTER TABLE ratings DROP CONSTRAINT ratings_pkey"))
    conn.execute(text("ALTER TABLE ratings ALTER COLUMN user_id SET NOT NULL"))
    conn.execute(text("ALTER TABLE ratings ADD PRIMARY KEY (recipe_id, user_id)"))


def run(engine, email):
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if ratings_user_id_not_null(conn, dialect):
            raise SystemExit("refusing: ratings.user_id is already NOT NULL — R2+R3 appears already applied")
        me = resolve_owner(conn, email)

        # a. backfill (recipes.owner + cook_log.user_id STAY nullable; ratings.user_id populated for the rebuild)
        r_owner = conn.execute(text("UPDATE recipes  SET owner   = :me WHERE owner   IS NULL"), {"me": me}).rowcount
        r_cook  = conn.execute(text("UPDATE cook_log SET user_id = :me WHERE user_id IS NULL"), {"me": me}).rowcount
        r_rate  = conn.execute(text("UPDATE ratings  SET user_id = :me WHERE user_id IS NULL"), {"me": me}).rowcount

        # b. ratings composite-PK rebuild (feeds off the backfilled user_id)
        if dialect == "sqlite":
            _rebuild_ratings_sqlite(conn)
            # option (a): mark 019 applied so build_db/migrate skips it on this already-migrated DB
            # (INSERT OR IGNORE — harmless if somehow already recorded).
            conn.execute(text(
                "INSERT OR IGNORE INTO schema_migrations (filename, applied_at) VALUES (:f, datetime('now'))"
            ), {"f": R3_MIGRATION})
        else:
            _rebuild_ratings_pg(conn)

        # self-check: no NULLs left in the backfilled columns
        left = conn.execute(text(
            "SELECT (SELECT COUNT(*) FROM recipes WHERE owner IS NULL),"
            "       (SELECT COUNT(*) FROM cook_log WHERE user_id IS NULL),"
            "       (SELECT COUNT(*) FROM ratings WHERE user_id IS NULL)"
        )).first()
        assert left == (0, 0, 0), f"NULLs remain after backfill: {left}"

    print(f"[{dialect}] owner id={me}: recipes.owner +{r_owner}, cook_log.user_id +{r_cook}, "
          f"ratings.user_id +{r_rate}; ratings PK -> (recipe_id, user_id), user_id NOT NULL.")


def build_engine(db_path):
    url = os.environ.get("DATABASE_URL") or f"sqlite:///{db_path}"
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _rec):   # enforce FKs (validates the rebuild's inserts + preserves cascade)
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


def main():
    ap = argparse.ArgumentParser(description="Rescoping R2+R3 backfill + ratings composite-PK rebuild.")
    ap.add_argument("--owner-email", help="account that owns all existing data (required unless a single admin exists)")
    ap.add_argument("--db", default=str(REPO / "recipes.db"), help="SQLite DB path (ignored if DATABASE_URL is set)")
    args = ap.parse_args()
    run(build_engine(args.db), args.owner_email)


if __name__ == "__main__":
    main()
