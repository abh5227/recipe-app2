# SQLite → PostgreSQL + SQLAlchemy migration (✅ COMPLETE — Stages 1 + 2 done)

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

### STAGE 2 ✅ COMPLETE — switch engine to Postgres
*(Acceptance met: dual-dialect CI green — the SQLite suite (288 + 6 skipped) AND the PG integration suite (6) on a `postgres:16` service, every push.)*

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
- **2c ✅ DONE — dual-dialect CI + the Postgres-default convention.** The dialect-divergent paths are now CI-covered on a real engine, alongside the unchanged SQLite suite. Chosen **Option S** (a scoped PG integration suite), not Option P (rewriting test_api's ~40 raw-SQL assertions) — the divergence surface is small + enumerable and the roadmap is filter-heavy/ORM-expressible:
  - **2c-1 ✅** (`9006990`) — `tests/pg_harness.py`: dialect-neutral seed (`seed_all` via Core inserts — no `lastrowid`/PRAGMA, reuses the production transformations) + `reset_and_seed` (TRUNCATE … RESTART IDENTITY CASCADE) truncate-reseed isolation primitive (the app commits, so rollback-per-test doesn't fit).
  - **2c-2 ✅** (`7a46442`) — `tests/test_pg_integration.py`: the scoped PG suite covering the real divergence classes — the on_conflict **upserts**, **list ordering / collation** (PG's linguistic sort differs from SQLite's BINARY byte order — the class the byte-identical checks missed), **recipe_stats** aggregations, PG-native **delete-cascade**, **sequence-after-insert**. Module **skips unless `DATABASE_URL` is a postgresql URL**, so the SQLite suite is untouched.
  - **2c-3 ✅** (`6863e1a`) — `build.yml`: a health-gated `postgres:16` service (**trust auth — no credential**, no S2068) + a step that sets `DATABASE_URL`, runs `alembic upgrade head`, and runs the PG suite. **Dual-dialect CI live**: SQLite run (288 + 6 skipped) + PG run (6 passed on the real engine) every push.
  - **2c-4 ✅** (docs) — close-out convention (below). The **code default stays SQLite**; Postgres is opt-in via `DATABASE_URL`.
- ⚠️ **GUARD (carried forward):** verify every data-layer change in the **CI-like condition** (deps as CI installs them; the Postgres **service container**, not a hand-set-up local DB) before trusting green — the "green locally, red in CI" trap the Stage-1b engine-path lesson came from.

## Risk concentration

The **upserts** are the one spot SQLAlchemy does **not** abstract the dialect — written per-DB
(SQLite-flavor in 1c, PG-flavor in 2b), and **tested on the real engine in 2c**. They are **5 upsert
operations across 3 code sites** (`set_line_change`'s 2 + the shared `upsert_rating`), each already
carrying a `# Stage 2b` swap comment. Everything else in `app.py` was ~85% Tier-1 mechanical, now all
funneled through `orm_session()`. `build_db`'s FK-rebuild trick + joins stay raw and are ported in 2b.

## Conventions (post-migration — the durable rules going forward)

- **Engine selection.** The **code default is SQLite** — `orm_session()` resolves
  `os.environ.get("DATABASE_URL") or f"sqlite:///{DB}"`, so a **fresh clone runs offline on SQLite with
  zero setup** (and the SQLite suite + the test harness's per-test DB redirect keep working). **Postgres is
  the intended production engine, opt-in via one env var** — `DATABASE_URL=postgresql+psycopg://…` (2b-3).
  No code-default flip: hardcoding PG would break offline local dev. "PG as the shipped/production default"
  is realized at the future **hosting/deploy** stage by setting `DATABASE_URL` in that environment.
- **Running on Postgres locally:** start the container (`docker start recipe-postgres`), `DATABASE_URL=… alembic upgrade head`
  (schema), then run the app/tests with `DATABASE_URL` set. Data: `scripts/migrate_sqlite_to_pg.py` copies a
  SQLite DB into a fresh PG schema (2b-4).
- **Dialect-divergence rule (forward).** SQLAlchemy abstracts most paths; it does **not** abstract: the
  **on_conflict upserts**, any **raw `text()` SQL**, and **`ORDER BY` on text/nullable columns** (collation +
  NULL-ordering). Any NEW code of those kinds must get coverage in **`tests/test_pg_integration.py`** (it runs
  on the real engine in CI). If that suite keeps growing / catching divergences, that's the signal to escalate
  to **Option P** (the full serve-path suite on PG); until then the scoped suite is sufficient.
- **Known follow-ups:** (a) **NULL-ordering canary** — add a PG test when rescoping introduces an `ORDER BY`
  on a nullable column (SQLite sorts NULLs first, PG last). (b) **`S7637`** — pin the SonarQube scan action to
  a full commit SHA (a separate CI-hardening item, not part of Stage 2).

## Deferred (after the DB migration)

- **Auth** — Flask-Login/sessions: ~14 authorization checks on the mutating routes + login infra + a `users` table.
- **Core-table RESCOPING** — `ratings` PK → `(recipe_id, user_id)`, `cook_log`/`recipes` user columns; ~17 query sites + a **241-row backfill** (116 ratings + 125 cooks). **Depends on auth.**
- **Images → object storage** — isolated: 1 route + 1 column (path string → key/URL) + an upload path (none today).
- **Render hosting** — managed Postgres + object storage; move off local FS (SQLite file, `static/images/`, `backups/`).
- The **per-person change layer** (`recipe_line_changes`/`recipe_additions`, seed-gated) is a multi-user primitive that gets reworked properly **inside** the auth/rescoping work.
