# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**Chef's Choice** — a personal, single-user, no-auth recipe web app. The bet: recipes
are a commodity; the scarce asset is **outcome data** — what gets cooked, how it's rated,
and how people modify it. Everything is built to capture structured, timestamped signal
(ratings, cook history, per-person modifications) that can later ground an LLM via RAG.

Key features: quantity scaling (½×·1×·2×·custom), metric/imperial + volume→weight
conversion, cook-gated star ratings, a cook log, per-person recipe versions, and an
import pipeline from Paprika native exports.

## Read these first

- `OVERVIEW.md` — 2-minute orientation and vision
- `CODE_WALKTHROUGH.md` — guided tour, architecture, and living history
- `ROADMAP.md` — features by priority tier
- `docs/design-decisions.md` — "used cookbook" design direction, Round 1/2 staging
- `docs/import-reference-15.md` — regression baseline for the 15 verified recipes

## Tech stack

- **Backend:** Python 3 + Flask (≥3.0) + SQLAlchemy (≥2.0). Single small backend serving a JSON API +
  the built frontend. (SQLAlchemy landed in DB-migration Stage 1a — `models.py` mirrors the schema but
  is **not wired yet**; queries still use raw `sqlite3`. See `docs/migration-plan.md`.)
- **DB:** SQLite (`recipes.db`, git-ignored, local only); mid-migration to PostgreSQL (see the plan doc).
- **Frontend:** Vanilla JS (`static/app.js`), CSS3 with design tokens, Spectral typeface — no framework,
  but **built by Vite** into `dist/` (git-ignored) which Flask serves; TipTap powers the method-step editor.
- **Tests:** pytest (backend) + Node's built-in `--test` runner (JS suite is **zero-dep** — runs on the
  source without `node_modules`; the app build itself uses Vite + TipTap).
- **CI:** GitHub Actions runs pytest w/ coverage, JS tests, and a SonarQube scan on push/PR.

## Commands

```bash
# Setup (fresh clone → working app at http://localhost:8000)
python3.13 -m pip install -r requirements.txt   # Python runtime: flask, SQLAlchemy
npm install                          # frontend deps: Vite (build) + TipTap (step editor)
npm run build                        # build the Vite bundle → dist/ (git-ignored)
                                     #   REQUIRED: Flask's "/" serves dist/index.html — skip this and / 500s
python3.13 build_db.py               # apply migrations + load seed.py → recipes.db (never wipes your data)
python3.13 app.py                    # serve the built frontend + API at http://localhost:8000

# Active development (two processes, hot-reload)
npm run dev                          # Vite dev server on :5173 (HMR); proxies /api + /images + /fonts → Flask
python3.13 app.py                    # Flask on :8000 (API + images/fonts). Open the app at :5173.

# Backup before risky DB work
python3.13 backup.py                 # timestamped copy → backups/

# Tests
python3.13 -m pip install -r requirements-dev.txt   # one-time: pytest
python3.13 -m pytest                 # Python suite
node --test tests/js                 # JS suite (zero-dep; scaler, factor-sync, step-adapter)  [also: npm test]
```

After editing frontend source (`static/*.js`, `static/styles.css`), rerun `npm run build` (or use the
`npm run dev` loop). After editing `seed.py`, rerun `build_db.py` then restart `app.py`.

## Architecture & conventions

**Content vs. Your Data — the central rule.** Content (recipes, ingredients, people) lives
in `seed.py` and is rebuilt on every `build_db.py`. User data (ratings, cook history,
per-person changes) lives in `recipes.db` and is *never* touched by rebuilds. Enforced by
two tiers: `source='seed'` (rebuilt) vs `source='app'` (preserved).

**Shared "brain" modules** — used at both build-time and serve-time:
- `weights.py` — volume↔weight matcher + King Arthur density lookup
- `stepscale.py` — method-text quantity scaler
- `static/scaler.js` — mirrors the above on the client; kept in sync by
  `tests/js/factor-sync.test.js`. **If you change conversion factors in `weights.py`/
  `stepscale.py`, update `scaler.js` too** or the sync test fails.

**Import pipeline** — three separate stages so a new source never touches core logic:
`paprika_native_reader.py` → `import_cleanup.py` → `import_write.py`, orchestrated by
`import_runner.py`. Guiding rule: **decline-over-guess** — extract the clear cases, *flag*
the ambiguous ones to the `import_flags` review queue, never silently mis-structure.
Import status and counts live in ROADMAP.md.

**Schema** evolves via numbered, apply-once migrations in `migrations/`. Add a new numbered
file rather than editing existing ones; `migrate.py` applies them safely.

**Design** follows a Round 1 / Round 2 split; for the current stage and the reserved R2
hooks, see `docs/design-decisions.md`.

## Working conventions

How this project is run:

- **Read-only inspection first.** Inspect and report before changing anything; see the real
  data before acting.
- **Propose a spec and STOP for approval** before building anything non-trivial; don't
  draft-and-commit in one shot.
- **Present a full diff and wait for approval** before applying edits.
- **Stage work in per-stage commits;** both test suites (`python3 -m pytest` and
  `node --test tests/js`) green at each commit.
- **Conventional Commits:** `feat` = new user-facing capability, `fix` = bug fix,
  `chore` = routine/inert groundwork; the summary line reflects what actually changed.
- **Never push without explicit approval;** after an approved push, watch the GitHub
  Actions run and report green/red.
- **The import runner writes only with `--yes`** and takes a backup first.
- **Blast-radius follows the DATA, not the field.** For any change to the data model, `seed.py`,
  or the build/seed pipeline, scope the analysis to the *rows being changed* (their
  slugs/ids/counts/existence), not just the column/token edited — and grep `tests/` **and** the
  fixture harness (`tests/harness.py`), not only app code. Fixtures and tests are part of the blast
  radius.
- **A dry-run that touches anything the tests build on must RUN THE TEST SUITE,** not just DB/count
  assertions. When a change touches seed content, the build pipeline, fixtures, or schema, one
  `pytest` run in the dry-run copy (after the edit) surfaces fixture coupling before it reaches
  live, at ~zero cost.
- **"Correct data + red suite" is still STOP-before-commit** — but it isn't data corruption: don't
  auto-revert correct live data over a fixable test issue; surface the choice.
- **When you change HOW code reaches the DB (new engine/session/connection path), verify the test
  harness redirects THAT path to the test DB — and PROVE it by running the suite with `recipes.db`
  HIDDEN (the CI condition).** "Suites green locally" is meaningless if the suite is silently hitting
  the *real* `recipes.db` instead of the test's temp DB. A frozen-at-import engine bypasses
  `make_kitchen`'s redirect (it only rebinds `app.DB`/`build_db.DB`/`migrate.DB`); use a **call-time
  factory** that reads the redirected module-global `DB` (see `app.py::orm_session()`, mirroring
  `db()`). This is a *variant of the dry-run-must-run-tests rule*: both are "green locally because the
  tests aren't exercising what CI exercises" — the unifying guard is **run the suite in the CI-like
  environment (deps as CI installs them, `recipes.db` absent) before trusting green.**

*Why the first three exist (the seed→app miss):* converting the 5 seed recipes to app (flip `source` +
empty `seed.py`'s `RECIPES`) was proven rebuild-safe on a DB dry-run and applied correctly to live,
yet broke **31 pytest tests** — the suite builds every fixture DB from `seed.py`'s `RECIPES`
(`make_kitchen` → `build_db`), coupling to the seed slugs (~90 references across `tests/`), not the
`source` column the blast-radius had grepped. The DB dry-run passed because it only asserted on the
DB; a `pytest` run in the same scratch copy would have caught all 31. Reverted cleanly. **Open
follow-up:** the conversion (a numbered migration + the `seed.py` edit) is proven correct and
rebuild-safe and will be re-applied *after* the tests seed their own fixtures instead of the 5 seed
recipes — its own diagnostic + plan, whose dry-run includes `pytest`. `test_changes.py` in
particular used those recipes as the only read-only `source='seed'` recipes, so the decouple
intersects with what those per-person-change tests exercise.

*Why the fourth exists (the Stage-1b CI miss):* the converted ORM read routes used `models.SessionLocal`
(frozen at import to the default `recipes.db`). `make_kitchen` redirects `app.DB`/`build_db.DB`/`migrate.DB`
but not the frozen engine, so the ORM silently queried the **real** `recipes.db` during tests — green
locally (the file exists and its seed-derived ingredients/people happened to match the fixtures) but red
in CI (no `recipes.db` → empty DB → `OperationalError`). Fixed by `orm_session()` reading the redirected
module-global `DB` at call time. Hiding `recipes.db` and re-running `pytest` reproduces the CI failure in
one step — the standing guard for any DB-access-path change.
