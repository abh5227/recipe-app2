-- 017_users_invites.sql
-- Auth data layer (auth-1): user accounts (email + hashed password + is_admin) and single-use invite
-- codes for gated signup. Purely additive — no existing table is touched. NO routes/login yet (auth-2
-- wires Flask-Login + the JSON endpoints). is_admin is an int-boolean (0/1), matching is_heading; it
-- gates invite GENERATION only (a later stage), not a general superpower. created_at has NO DB default
-- (set in code via now_utc()), so there's no SQLite datetime('now') vs Postgres default expression to
-- reconcile. This is the SQLite half of the dual schema source; an Alembic revision mirrors it for PG.

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,           -- stored lowercased
    password_hash TEXT NOT NULL,
    display_name  TEXT,
    is_admin      INTEGER NOT NULL DEFAULT 0,     -- int-boolean; gates invite generation only (later)
    created_at    TEXT NOT NULL                   -- set in code via now_utc()
);

CREATE TABLE invites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL UNIQUE,
    created_by INTEGER NOT NULL REFERENCES users(id),   -- the inviter
    created_at TEXT NOT NULL,
    used_by    INTEGER REFERENCES users(id),            -- NULL until consumed (single-use enforced at consumption)
    used_at    TEXT,
    expires_at TEXT                                      -- present now, unused until a later stage
);
