# SQLite → PostgreSQL + SQLAlchemy migration (in progress)

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

## Two-phase plan (every sub-commit keeps pytest 286 + JS 44 green)

### STAGE 1 — adopt SQLAlchemy, STAY on SQLite
*(Zero DB-change risk: SQLAlchemy runs fully on SQLite, so the ORM conversion is proven before the engine changes.)*

- **1a ✅ DONE** (commit `1c14342`): `models.py` — all 15 tables as SQLAlchemy models, **empty-diff-verified** faithful mirror of the live schema; engine/session from `DATABASE_URL` defaulting to `sqlite:///recipes.db`; **purely additive** (nothing wired). `ingredient_weights` = Core Table (no PK in the live schema); 3 composite-PK tables; single-column PKs mirror SQLite's implicit-nullable DDL.
- **1b ✅ DONE** (commits `0c32df3` + fix `2848764`): converted the **4 self-contained read routes** (`list_people`, `list_ingredients`, `get_ingredient`, `in_season` — 7 SELECTs) via `app.py::orm_session()`. **Narrowed** from the original scope: the read *helpers* (`recipe_stats`, `changes_for`, `seed_recipe_person_error`, `validate_recipe_payload`, `attach_weights`, `_unique_copy_id`) and `get_recipe` are **write-transaction-entangled** — called on the caller's connection inside write transactions to read just-written rows, so a separate ORM session would return stale pre-write data — and move to 1c with their write routes.
- **1c** — convert `app.py` **WRITES** (INSERT/UPDATE/DELETE + the **5 SQLite-dialect upserts** via `sqlite.insert().on_conflict_do_update()`, + `list_recipes`'s correlated subqueries via ORM or `text()`), **plus the write-entangled read helpers + `get_recipe` deferred from 1b**. Best staged **per-domain** (e.g. `recipe_stats` + its 5 cook/rating routes together; `changes_for` + `seed_recipe_person_error` + the 3 line-change/addition routes together) so each request is one ORM session and the helper joins it — preserving the in-transaction stats/changes reads.
- ⚠️ **1c GUARD (harness must redirect the ORM path):** every conversion MUST route through `app.py::orm_session()` (the call-time factory that reads the module-global `DB` the harness redirects), **NOT** a frozen-at-import `SessionLocal`. A frozen engine silently queries the real `recipes.db` in tests → green locally, red in CI. **Verify each 1c batch with `recipes.db` HIDDEN** (`pytest` green in the CI condition), not just normal-env green. *(This is why 1b needed fix `2848764` — see CLAUDE.md's fourth working-conventions rule.)*
- `build_db.py` / `import_write.py` / `import_runner.py` / `migrate.py` **STAY raw SQL in Stage 1** (build/import-time, not serve-time; they share the SQLite file fine).

### STAGE 2 — switch engine to Postgres
*(Acceptance: 286 + 44 green on Postgres in CI.)*

- **2a** — **Alembic baseline**: autogenerate the initial migration from the models, **empty-diff-verified** against the live schema, `alembic stamp head`. `alembic_version` replaces `schema_migrations`; the 16 `.sql` files become archived history — **do NOT port them**.
- **2b** — **engine swap + dialect residuals**: `DATABASE_URL` → PG; the **8 upserts → PG-dialect `on_conflict`**; AUTOINCREMENT → SERIAL (auto via `Integer` PK); **keep text-date columns as `Text`** for parity; port `build_db`/import raw SQL to PG-compatible; **REPLACE the `build_db` FK-off rebuild trick** (no `PRAGMA foreign_keys=OFF` in PG — use deferred constraints / correct insert order / `TRUNCATE … CASCADE`).
- **2c** — **test harness → Postgres**: `make_kitchen`/`Kitchen.conn` → PG engine with **transaction-rollback-per-test**; add a `postgres:16` service container to `build.yml`. **This is where the 8 PG-dialect upserts get exercised under test** — the dialect-divergence guard (per CLAUDE.md: no test-vs-prod dialect divergence).

## Risk concentration

The **8 upserts** are the one spot SQLAlchemy does **not** abstract the dialect — written per-DB
(SQLite-flavor in 1c, PG-flavor in 2b), and **tested on the real engine in 2c**. Everything else in
`app.py` is ~85% Tier-1 mechanical, funneled through `db()`. `build_db`'s FK-rebuild trick + joins
stay raw and are ported in 2b.

## Deferred (after the DB migration)

- **Auth** — Flask-Login/sessions: ~14 authorization checks on the mutating routes + login infra + a `users` table.
- **Core-table RESCOPING** — `ratings` PK → `(recipe_id, user_id)`, `cook_log`/`recipes` user columns; ~17 query sites + a **241-row backfill** (116 ratings + 125 cooks). **Depends on auth.**
- **Images → object storage** — isolated: 1 route + 1 column (path string → key/URL) + an upload path (none today).
- **Render hosting** — managed Postgres + object storage; move off local FS (SQLite file, `static/images/`, `backups/`).
- The **per-person change layer** (`recipe_line_changes`/`recipe_additions`, seed-gated) is a multi-user primitive that gets reworked properly **inside** the auth/rescoping work.
