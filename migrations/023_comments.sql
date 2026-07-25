-- 023_comments.sql
-- Social (comments on feed posts; docs/product-vision.md "Comments — connection, never engagement
-- machinery"). A comment is the CONVERSATION under a deliberate-share post — the only social-metric-free
-- surface: comments YES, likes/reactions NEVER, no count-as-metric, and (the big simplification) NO
-- notifications of any kind, so a comment is just a row seen when the feed renders. Surrogate id PK
-- (like shared_posts). post_id FK -> shared_posts(id) ON DELETE CASCADE is the INTEGRITY CHAIN: a
-- shared_post already cascades when its cook/recipe is deleted (2a), so the 2-level chain
-- recipe/cook -> shared_post -> comments cleans up the whole conversation with the post (and the unshare
-- path deletes a post's comments too). author_id -> users(id) is a reference FK (no ondelete), matching
-- shared_posts.user_id / friendships / owner. created_at = now_utc(). idx_comments_post backs the feed's
-- batched WHERE post_id IN (...) load. Additive: nothing reads comments until the feed serializer embeds
-- them. SQLite half of the dual schema source; an Alembic revision mirrors it for Postgres.

CREATE TABLE comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL REFERENCES shared_posts(id) ON DELETE CASCADE,   -- the integrity chain
    author_id  INTEGER NOT NULL REFERENCES users(id),                            -- reference FK, no cascade
    body       TEXT    NOT NULL,                                                  -- <=300 chars, app-enforced
    created_at TEXT    NOT NULL                                                   -- now_utc()
);
CREATE INDEX idx_comments_post ON comments (post_id);
