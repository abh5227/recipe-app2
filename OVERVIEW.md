# Chef's Choice — Overview

A two-minute orientation. For the quick start see [README.md](README.md); for the guided code
tour and history see [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md); for the plan see
[ROADMAP.md](ROADMAP.md).

## What it is

A **personal recipe web app** — Flask + SQLAlchemy, SQLite locally and Postgres in production, with a
Vite-built vanilla-JS frontend. It began single-user and no-auth; it now has **accounts and per-recipe
ownership** (default-deny: only the owner may write), though it is still a small private app rather than
a public service. Recipes link to a shared **ingredient library** of 10,020 entries built from
public food vocabularies (the 36-row "field guide" that preceded it was a demo, deleted in
migration 046),
with live **quantity scaling**, **metric/imperial + volume→weight** conversion, **star ratings**,
a **cook log**, and **per-person versions** of cookbook recipes (each person can tweak a quantity,
remove a line, or add an ingredient without forking the original).

A recipe's **notes are rows**, not a text box: each has words, a type, and sometimes the step it
belongs to, so a note about step 4 reads under that step and shows a marker on it. They are a
**playground**. Editing or deleting one leaves no "your changes" mark and costs the recipe nothing,
because note rows are out of the snapshot the page diffs against, and the author's original words
are kept where nothing compares them.

## Architecture

The data flows one way and rebuilds safely:

```
seed.py ──► build_db.py (migrate + load) ──► recipes.db ──► app.py (SQLAlchemy → JSON) ──► dist/ (Vite ◄── static/app.js)
```

- **`seed.py`** holds the seed content — today the **ingredient library** alone (`PEOPLE` went in migration 020); its
  `RECIPES` list is deliberately **empty** (the 5 original examples became ordinary app recipes in
  migration 016, so the DB is their source of truth). **`build_db.py`** applies migrations then loads
  seed content; **`app.py`** is the Flask backend, whose serve path queries **entirely through
  SQLAlchemy**; **`static/app.js`** renders it and is **built by Vite into `dist/`**, which Flask
  serves — so a fresh clone needs `npm run build` before `/` will load.
- **Pure "brain" modules**, shared at both build-time and serve-time: **`weights.py`**
  (volume→weight matcher + King Arthur density table, Phase 1c) and **`stepscale.py`**
  (method-text quantity scaler, Phase 1d). **`static/scaler.js`** mirrors the scaling math on the
  client, and a `factor-sync` test reads both `scaler.js` and `weights.py` to keep the JS↔Python
  conversion factors in lock-step.
- **Schema evolves only via numbered migrations** (`migrations/0NN_*.sql`, applied once each by
  `migrate.py`) — never a destructive rebuild, so your ratings and history survive. Those files are
  SQLite-only history; **Alembic (`alembic/`) owns the Postgres schema.**
- **Two data tiers:** `source='seed'` rows (owned by `seed.py`, rebuilt on every `build_db`) and
  `source='app'` rows (created in the app or imported — ratings, cook log, per-person changes).
  **`build_db` only ever rebuilds the seed tier;** app-tier data is never touched.

## Import pipeline (Phase 15)

A three-stage pipeline, each stage its own module so a new source never touches the hard logic:

```
paprika_native_reader.py ──► import_cleanup.py ──► import_write.py     (orchestrated by import_runner.py)
   (export → normalized)      (structured-or-flagged)   (→ DB rows)     — writes only with --yes
```

- **Reader** maps a Paprika NATIVE export (`.paprikarecipes`) into a source-agnostic normalized
  shape. **Cleanup core** turns each ingredient line into structured-or-flagged data
  (amount/unit/name, sections, parenthetical-gram harvest, ranges), on the rule of
  **decline-over-guess** — extract clear wins, *flag* the ambiguous, never silently mis-structure.
  **Write layer** maps a cleaned recipe to DB rows with **uid-dedup**, slug minting, a review
  queue (`import_flags`), and captured harvested grams.

## Current state

- **Done:** the test suite (P0); the whole quantity & units system (P1: scaler, metric/imperial,
  volume→weight, step-text scaling); the **Paprika import** (P15) — **300 recipes imported**, the
  full corpus, each with a stable `uid`; the **SQLite→Postgres migration** (Alembic owns the PG
  schema; CI tests both dialects); **accounts + per-recipe ownership**; and **photo upload** (a hero
  Polaroid + a per-cook album).
- **In progress:** the **annotation layer + inline editor** (O-c) — a recipe page shows what you
  changed against its birth baseline, in a handwritten layer, and the recipe is editable in place.
  Snapshots are the stored truth (`recipe_snapshots`); the changes are **derived** by diffing them,
  never stored as edits. **300 recipes each carry a `reason='original'` baseline**, and 274 are still
  byte-equal to it. ⚠️ That second number is not a property of the corpus. It drops by one for
  every recipe ever saved, so a gate compares the SET against the before-state of the same run. Also in progress: the "used cookbook" design pass.
- **Not yet:** library linkage is not wired to the catalog yet (**0 of 3,349 ingredient lines** carry an
  `ingredient_id`, since the 36 hand-authored rows they pointed at were deleted in migration 046); full image storage (`image` is primary-only — 121 of 300 recipes have one);
  *using* the harvested gram in display; and importer hardening.
- **Tests:** **2,337 pytest + 255 JS**, CI green on every push (pytest w/ coverage on SQLite **and**
  Postgres, the JS suite, and a SonarQube scan).

For what happens next and in what order, see ROADMAP.md → *Recipe annotations + editor parity
(O-c)* → **Queued sequence**.

## The vision

Recipes are a commodity; the scarce, valuable thing is **outcome data** — what real people cook,
how they rate it, what they change. So the project optimizes every feature to **capture
meaningful signal**, structured and timestamped from the start (this is why the cook log,
ratings, and per-person modifications are central). The long-term aim is to **ground a capable LLM
via RAG** over this clean, queryable corpus — for recommendation and, eventually, novel recipe
generation — rather than training a model of our own. See [ROADMAP.md](ROADMAP.md) Tier 0 for the
full reasoning.
