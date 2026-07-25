-- 022_shared_posts.sql
-- Social sub-stage 2a (docs/product-vision.md build plan): the deliberate-share feed. Logging stays
-- ALWAYS-PRIVATE; SHARING is a separate opt-in act that creates a feed POST here. A post references
-- WHAT was shared via SEPARATE nullable FK columns (cook_log_id / recipe_id) — NOT a polymorphic
-- post_type+target_id — precisely so the target's deletion CASCADES the post: undo_cook DELETES a
-- cook_log row, delete_recipe cascades a recipe; ON DELETE CASCADE here means a shared post can never
-- be orphaned (the integrity need decided the shape — a polymorphic column can't FK/cascade). The XOR
-- CHECK enforces EXACTLY ONE target, so post_type is DERIVED (cook_log_id set -> 'cook', recipe_id set
-- -> 'recipe'), never stored. Surrogate id PK (a post is a first-class entity, and repeat shares are
-- allowed — no dedup). created_at = now_utc() is share-time = feed-time (structurally resolves the
-- cook_log.cooked_on recency wrinkle). Additive: nothing reads shared_posts until the feed endpoint.
-- SQLite half of the dual schema source; an Alembic revision mirrors it for Postgres.

CREATE TABLE shared_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),               -- the sharer
    cook_log_id INTEGER REFERENCES cook_log(id) ON DELETE CASCADE,   -- set for a 'cook' post
    recipe_id   TEXT    REFERENCES recipes(id)  ON DELETE CASCADE,   -- set for a 'recipe' post
    caption     TEXT,                                                -- optional (<=280 chars, app-enforced)
    created_at  TEXT NOT NULL,                                       -- now_utc(): share-time = feed-time
    CHECK ((cook_log_id IS NOT NULL) <> (recipe_id IS NOT NULL))     -- exactly one target
);
