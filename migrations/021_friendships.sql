-- 021_friendships.sql
-- Social sub-stage 1 (docs/product-vision.md build plan): the friend graph. A mutual friendship is ONE
-- row (requester -> addressee); "are A and B friends" queries BOTH directions. status is a text-IN CHECK
-- (the ratings CHECK idiom); reference FKs -> users(id) with NO ondelete (matching owner/user_id/
-- created_by). created_at/accepted_at are TEXT set in code via now_utc() (no DB default — the auth-1
-- pattern that avoids the SQLite datetime('now') vs Postgres default-expression divergence). Purely
-- additive: nothing reads friendships yet (the feed/sharing sub-stages consume it). The composite PK
-- (requester_id, addressee_id) blocks a duplicate request in one direction; the reverse-duplicate
-- (B->A while A->B pending) is resolved in the request endpoint by auto-accepting. This is the SQLite
-- half of the dual schema source; an Alembic revision mirrors it for Postgres.

CREATE TABLE friendships (
    requester_id INTEGER NOT NULL REFERENCES users(id),   -- who sent the request
    addressee_id INTEGER NOT NULL REFERENCES users(id),   -- who received it
    status       TEXT    NOT NULL CHECK (status IN ('pending','accepted')),
    created_at   TEXT    NOT NULL,                         -- set in code via now_utc()
    accepted_at  TEXT,                                     -- NULL until accepted
    PRIMARY KEY (requester_id, addressee_id),
    CHECK (requester_id <> addressee_id)                   -- no self-friend
);
