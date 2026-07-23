# SQLite → PostgreSQL + SQLAlchemy migration (Stage 1 ✅ complete — Stage 2 next)

The durable record of the data-layer migration. Chat memory is transient; this file is the plan.

## Decision & rationale

- **Postgres-FIRST** (before auth/rescoping): going multi-user eventually, so put the scalable
  substrate in place first — then auth + core-table rescoping get built **once, on the final engine**
  (rework-minimizing). Adopt **SQLAlchemy (ORM)** alongside — "build once, do it properly"; the data
  layer reaches its final form now rather than being rewritten later.
- **Auth mechanism (decided, for a LATER slice):** Flask-Login + server-side **sessions** (not JWT —
  this is a single-origin web SPA, not distributed/mobile; sessions give instant revocation).
- **Hosting target (decided, for a LATER slice):** **Render** (managed Postgres with PITR + backups,
  flat pricing, best docs).
- Auth + hosting are **later slices, after the DB migration** — recorded here so choices point at them.

## Two-phase plan (every sub-commit keeps pytest 288 + JS 44 green)

### STAGE 1 ✅ COMPLETE — adopt SQLAlchemy, STAY on SQLite
*(Zero DB-change risk: SQLAlchemy ran fully on SQLite, proving the ORM conversion before the engine
changes. The **entire serve path** now queries through `app.py::orm_session()`; behavior stayed
byte-identical throughout; still on SQLite.)*

- **1a ✅ DONE** (commit `1c14342`): `models.py` — all 15 tables as SQLAlchemy models, **empty-diff-verified** faithful mirror of the live schema; engine/session from `DATABASE_URL` defaulting to `sqlite:///recipes.db`; **purely additive** (nothing wired). `ingredient_weights` = Core Table (no PK in the live schema); 3 composite-PK tables; single-column PKs mirror SQLite's implicit-nullable DDL.
- **1b ✅ DONE** (commits `0c32df3` + fix `2848764`): converted the **4 self-contained read routes** (`list_people`, `list_ingredients`, `get_ingredient`, `in_season` — 7 SELECTs) via `app.py::orm_session()`. **Narrowed** from the original scope: the read *helpers* (`recipe_stats`, `changes_for`, `seed_recipe_person_error`, `validate_recipe_payload`, `attach_weights`, `_unique_copy_id`) and `get_recipe` are **write-transaction-entangled** — called on the caller's connection inside write transactions to read just-written rows, so a separate ORM session would return stale pre-write data — and move to 1c with their write routes.
- **1c ✅ DONE** (batches `83ca73f`→`a0e8730`→`d898861`→`7327e8b`→`5a1d83d`; dead-`db()` cleanup `8dafe82`): converted `app.py`'s WRITES (INSERT/UPDATE/DELETE + the SQLite-dialect upserts via `sqlite.insert().on_conflict_do_update()`) + `list_recipes`'s correlated subqueries (via `text()`) + the write-entangled read helpers + `get_recipe` deferred from 1b. Staged **per-domain**: B1 `list_recipes`, B2 recipe-CRUD, B3 change-layer (first upserts), B4 cook/rating (`recipe_stats` + undo/redo, regression-pinned on raw first), B5 `get_recipe` + `attach_weights` + `delete_test_recipes` (finale). Each request is one ORM session; write-entangled helpers join it (decision (b)) — preserving the in-transaction stats/changes reads. `get_recipe` output verified byte-identical; the raw `db()` helper removed — **zero live `db()` call sites** remain in the serve path.
- ⚠️ **1c GUARD (harness must redirect the ORM path):** every conversion MUST route through `app.py::orm_session()` (the call-time factory that reads the module-global `DB` the harness redirects), **NOT** a frozen-at-import `SessionLocal`. A frozen engine silently queries the real `recipes.db` in tests → green locally, red in CI. **Verify each 1c batch with `recipes.db` HIDDEN** (`pytest` green in the CI condition), not just normal-env green. *(This is why 1b needed fix `2848764` — see CLAUDE.md's fourth working-conventions rule.)*
- `build_db.py` / `import_write.py` / `import_runner.py` / `migrate.py` **STAY raw SQL in Stage 1** (build/import-time, not serve-time; they share the SQLite file fine).

### STAGE 2 — switch engine to Postgres  ← **START HERE (fresh session)**
*(Acceptance: 288 + 44 green on Postgres in CI.)*

- **0 · PREREQUISITE (do FIRST — Stage 2 can't start without it):** a **Postgres instance** to develop +
  test against. **Decided: DOCKER (`postgres:16`)** — same image as the 2c CI service container and eventual
  Render prod (local matches CI matches prod — the whole point), disposable/resettable for migration
  testing, no system install. Setup for a fresh session:
  - **Install Docker Desktop for Mac** (one-time); ensure it's running.
  - **Start:** `docker run --name recipe-postgres -e POSTGRES_PASSWORD=<password> -e POSTGRES_DB=recipe -p 5432:5432 -d postgres:16` (example — pick your own for the local throwaway container)
  - **Confirm:** `docker ps` shows `recipe-postgres` running.
  - **`DATABASE_URL`:** `postgresql://postgres:<password>@localhost:5432/recipe`
  - **Lifecycle:** stop `docker stop recipe-postgres` · start `docker start recipe-postgres` · reset (fresh DB) `docker rm -f recipe-postgres` then re-run the `docker run`.
  - **2a runs against this container**, so it must be up first.
- **2a ✅ DONE** (commit `9ba1365`): **Alembic baseline** — autogenerated from the models, **empty-diff-verified** + structural-parity-checked against the live SQLite schema, applied to the PG container (`alembic upgrade head`). Hand-fixed the SQLite-isms autogenerate can't translate (partial-unique `uid` index via `postgresql_where`; PG-native `to_char` date defaults; single-col PKs → NOT NULL). `alembic_version` (at head `72e165e6482e`) replaces `schema_migrations`; the 16 `.sql` files stay SQLite history — **not ported**. App still on SQLite.
- **2b ✅ DONE — engine swap + dialect residuals (Option A: dialect-agnostic + reversible).** The app runs on Postgres via one env var (`DATABASE_URL`); tests stayed on SQLite through 2b (2c moves the harness to PG). Each sub-step kept **pytest 288 + JS 44 green on SQLite**:
  - **2b-1 ✅** (`64cde15`) — dialect-guard the **FK connect-listener**: `PRAGMA foreign_keys=ON` fires **only on SQLite** (syntax error on PG, and unnecessary — PG enforces FKs + `ON DELETE CASCADE` always). Behavior-neutral on SQLite.
  - **2b-2 ✅** (`e0afa14`) — the **5 upserts dialect-agnostic** (`dialect_insert()` picks `sqlite.insert` vs `postgresql.insert` from the session dialect — 3 sites: `set_line_change` ×2 + shared `upsert_rating`) + `upsert_rating.rated_on` off SQLite `datetime('now')` to Python `now_utc()`.
  - **2b-3 ✅** (`7da6910`) — `orm_session()` resolves its engine from **`DATABASE_URL`** (default `sqlite:///<DB>` from the live module-global, so the harness redirect still holds) — makes the flip env-controlled + reversible.
  - **2b-4 ✅** (`a91cb7e`) — data migration `recipes.db` → Postgres: `scripts/migrate_sqlite_to_pg.py` copies **7420 rows / 14 tables** (skips `schema_migrations`; FK-ordered; refuse-if-not-empty; resets the 6 SERIAL sequences via `pg_get_serial_sequence`). Also fixed `grams`/`grams_per_ml` `REAL`→`Float` (float4 truncated densities on PG). Acceptance: row-count parity + **byte-identical `GET`** vs SQLite (incl. full-precision `grams_per_ml`).
  - **2b-5 ✅ PROVEN (docs-only; proof, not cutover)** — ran the **full app on Postgres end-to-end** (`DATABASE_URL=postgresql+psycopg://…`): LIST (298, correlated-subquery fields), byte-identical GET detail, all reads, cook/uncook/redo, rating upsert (set + update-in-place, no dup), cooked-and-rated, the seed-gated change-layer upsert (edit/remove) on PG, full RECIPE-CRUD, **delete-cascade** (PG-native FK), and **sequence correctness** (new autoincrement IDs land above the copied max — the `setval` payoff, verified under the running app). **Reversible**: unset `DATABASE_URL` → back to SQLite. **No app code change was needed** (2b-1..3 made the flip a pure env toggle).
  **Option X — the committed default stays SQLite** (`DATABASE_URL` unset → SQLite) until **2c** (harness → PG + CI service container) makes PG the *tested* default. To run on PG today: `DATABASE_URL=postgresql+psycopg://postgres:<password>@localhost:5432/recipe python3 app.py` (container up + data copied via 2b-4).
  Other residuals: AUTOINCREMENT → SERIAL (automatic via `Integer` PK, confirmed 2a); text-date columns stay `Text`. `build_db` / `migrate` / import **stay raw-SQLite** — Alembic owns the PG schema, so they're not run against PG and the `PRAGMA foreign_keys=OFF` rebuild trick needs **no** PG replacement.
- **2c** — **test harness → Postgres**: `make_kitchen`/`Kitchen.conn` → PG engine with **transaction-rollback-per-test**; add a `postgres:16` **service container** to `build.yml`. **This is where the PG-dialect upserts finally get exercised under test** — the dialect-divergence guard (per CLAUDE.md: no test-vs-prod dialect divergence).
- ⚠️ **GUARD (still applies):** verify every change in the **CI-like condition** (deps as CI installs them; for 2c, against the Postgres **service container**, not a hand-set-up local dev DB) before trusting green — the same "green locally, red in CI" trap the Stage-1b engine-path lesson (CLAUDE.md) came from.

## Risk concentration

The **upserts** are the one spot SQLAlchemy does **not** abstract the dialect — written per-DB
(SQLite-flavor in 1c, PG-flavor in 2b), and **tested on the real engine in 2c**. They are **5 upsert
operations across 3 code sites** (`set_line_change`'s 2 + the shared `upsert_rating`), each already
carrying a `# Stage 2b` swap comment. Everything else in `app.py` was ~85% Tier-1 mechanical, now all
funneled through `orm_session()`. `build_db`'s FK-rebuild trick + joins stay raw and are ported in 2b.

## Deferred (after the DB migration)

- **Auth** — Flask-Login/sessions: ~14 authorization checks on the mutating routes + login infra + a `users` table.
- **Core-table RESCOPING** — `ratings` PK → `(recipe_id, user_id)`, `cook_log`/`recipes` user columns; ~17 query sites + a **241-row backfill** (116 ratings + 125 cooks). **Depends on auth.**
- **Images → object storage** — isolated: 1 route + 1 column (path string → key/URL) + an upload path (none today).
- **Render hosting** — managed Postgres + object storage; move off local FS (SQLite file, `static/images/`, `backups/`).
- The **per-person change layer** (`recipe_line_changes`/`recipe_additions`, seed-gated) is a multi-user primitive that gets reworked properly **inside** the auth/rescoping work.
