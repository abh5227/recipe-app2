# Chef's Choice — Overview

A two-minute orientation. For the quick start see [README.md](README.md); for the guided code
tour and history see [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md); for the plan see
[ROADMAP.md](ROADMAP.md).

## What it is

A **single-user, local, no-auth personal recipe web app** — Flask + SQLite + vanilla JS, one
cook on one machine, nothing published. Recipes link to a shared ingredient **"field guide"**
(tap an ingredient to see when it's in season, where it grows, and which other recipes use it),
with live **quantity scaling**, **metric/imperial + volume→weight** conversion, **star ratings**,
a **cook log**, and **per-person versions** of cookbook recipes (each person can tweak a quantity,
remove a line, or add an ingredient without forking the original).

## Architecture

The data flows one way and rebuilds safely:

```
seed.py ──► build_db.py (migrate + load) ──► recipes.db ──► app.py (SQL → JSON) ──► static/app.js
```

- **`seed.py`** holds the content (recipes, the ingredient library, the people). **`build_db.py`**
  applies migrations then loads seed content; **`app.py`** is the Flask backend (serves the page
  and answers JSON queries); **`static/app.js`** renders it.
- **Pure "brain" modules**, shared at both build-time and serve-time: **`weights.py`**
  (volume→weight matcher + King Arthur density table, Phase 1c) and **`stepscale.py`**
  (method-text quantity scaler, Phase 1d). **`static/scaler.js`** mirrors the scaling math on the
  client, and a `factor-sync` test reads both `scaler.js` and `weights.py` to keep the JS↔Python
  conversion factors in lock-step.
- **Schema evolves only via numbered migrations** (`migrations/0NN_*.sql`, applied once each by
  `migrate.py`) — never a destructive rebuild, so your ratings and history survive.
- **Two data tiers:** `source='seed'` rows (owned by `seed.py`, rebuilt on every `build_db`) and
  `source='app'` rows (created in the app or imported — ratings, cook log, per-person changes).
  **`build_db` only ever rebuilds the seed tier;** app-tier data is never touched.

## Import pipeline (Phase 15)

A three-stage pipeline, each stage its own module so a new source never touches the hard logic:

```
paprika_native_reader.py ──► import_cleanup.py ──► import_write.py
   (export → normalized)      (structured-or-flagged)   (→ DB rows)
```

- **Reader** maps a Paprika NATIVE export (`.paprikarecipes`) into a source-agnostic normalized
  shape. **Cleanup core** turns each ingredient line into structured-or-flagged data
  (amount/unit/name, sections, parenthetical-gram harvest, ranges), on the rule of
  **decline-over-guess** — extract clear wins, *flag* the ambiguous, never silently mis-structure.
  **Write layer** maps a cleaned recipe to DB rows with **uid-dedup**, slug minting, a review
  queue (`import_flags`), and captured harvested grams.

## Current state

- **Done:** the test suite (P0) and the whole quantity & units system (P1: scaler,
  metric/imperial, volume→weight, step-text scaling).
- **In progress:** Recipe Import (P15) — the reader → cleanup → write machinery is built and
  dry-run-validated, and **15 recipes have been imported** (`source='app'`).
- **Not yet:** library linkage (`ingredient_id`), full image storage, the remaining ~280-recipe
  import, and *using* the harvested gram in display.
- **Tests:** 121 pytest + 22 JS, CI green on every push (with a SonarQube scan).

## The vision

Recipes are a commodity; the scarce, valuable thing is **outcome data** — what real people cook,
how they rate it, what they change. So the project optimizes every feature to **capture
meaningful signal**, structured and timestamped from the start (this is why the cook log,
ratings, and per-person modifications are central). The long-term aim is to **ground a capable LLM
via RAG** over this clean, queryable corpus — for recommendation and, eventually, novel recipe
generation — rather than training a model of our own. See [ROADMAP.md](ROADMAP.md) Tier 0 for the
full reasoning.
