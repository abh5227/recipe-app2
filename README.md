# Seasonal Kitchen

A personal recipe app. Recipes link to a shared **ingredient field guide** — tap an
ingredient to see when it's in season, where it grows, and which other recipes use it —
plus star ratings, a cooking log, and per-person tweaks to cookbook recipes. It's
local-only: one cook, one machine, nothing published.

> For the full design rationale and a guided tour of the code, see
> **`CODE_WALKTHROUGH.md`**. That document is the living history of how and why this is
> built; this README is just the quick start.

## Run it

You need Python 3. From inside this folder:

```
pip install flask         # one-time: installs the backend library
python3 build_db.py       # builds recipes.db from your seed data
python3 app.py            # starts the server
```

Then open **http://localhost:8000**. Stop the server with `Ctrl + C`.

## Edit a recipe

Your content lives in **`seed.py`**: the recipe list, the ingredient library, and the
people who can have a version. After editing it, rebuild and restart:

```
python3 build_db.py       # applies your changes
python3 app.py
```

`build_db.py` checks your work — if a recipe links to an ingredient that isn't in the
library, it stops with a clear message so a typo can't quietly break the page. A rebuild
**never** wipes your ratings, cook history, or per-person changes.

## Two rules worth knowing

1. **Seed vs. app recipes.** Recipes in `seed.py` are your cookbook originals:
   read-only in the app, changed by editing `seed.py`. Recipes you create with
   **+ New recipe** live only in the database and are edited in the app. A rebuild
   refreshes seed recipes and leaves app recipes, ratings, history, and changes alone.

2. **Per-person changes.** Several people (listed in `seed.py`) can each keep their own
   version of a seed recipe without forking it. On a seed recipe, a view switcher flips
   between **Original**, each person, and **Compare all**. In a person's view you can
   change a quantity, remove a line, or add an ingredient — their changes show in their
   colour, and they survive rebuilds.

## Files at a glance

```
seed.py        YOUR CONTENT — recipes, ingredient library, people. Edit this.
migrations/    database structure: numbered .sql files applied in order.
migrate.py     applies any not-yet-applied migrations (never deletes data).
build_db.py    migrates, then loads seed.py into the content tables.
backup.py      makes a timestamped copy of recipes.db into backups/.
app.py         the backend: serves the page and runs the SQL queries.
recipes.db     the generated database (binary; don't hand-edit; git-ignored).
static/        index.html (page shell) · styles.css (the look) · app.js (renders it)
tests/         pytest suite; builds a throwaway DB per test (see Tests below).
requirements.txt      / requirements-dev.txt   runtime (flask) and test (pytest) deps.
ROADMAP.md     planned features, phase by phase.
CODE_WALKTHROUGH.md   a guided tour of the code and the design decisions.
demo_foreign_keys.py  a standalone teaching script (runs on a copy; safe to ignore).
```

## Two safety nets

- **`python3 backup.py`** guards your *data* — ratings, cook history, and per-person
  changes live only in `recipes.db`, which isn't in git. Run it before anything risky.
- **git** guards your *code* — `seed.py`, the Python files, and the migrations.

## Tests

The backend has a pytest suite under `tests/`. From the project folder:

```
pip install -r requirements-dev.txt   # one-time; installs pytest
python3 -m pytest                      # run the suite
```

Each test builds its own throwaway database from the migrations and `seed.py`, so the
tests never touch your real `recipes.db`. They cover the API, the migration/build process,
and the per-person change layers (including that a rebuild preserves your edits). When you
add a migration, bump `EXPECTED_MIGRATIONS` in `tests/test_build_db.py`.

## Keeping it in git

```
git add .
git commit -m "describe what changed"
git push
```

`recipes.db` is git-ignored, so pushing saves your code but not your data — which is why
`backup.py` exists separately.
