# Go-live: the titles round

Written to be run at STOP 2, not run. Nothing below has been executed. Every command names its
database or its port.

This round has a **migration**, a **code** step and a **data** step, so it has the two rollbacks and
one extra question the previous round did not have: what happens if the migration is interrupted.
That was measured rather than reasoned, and the answer is in section 7.

What it does: migration 062 adds a nullable `recipe_notes.title`, and
`scripts/apply_note_titles.py` writes the 33 changes Andy decided over 21 recipes. 28 notes end up
titled across 18 recipes, 148 of the 176 note rows stay untitled.

## 0. Before anything

```sh
cd "/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
python3.13 backup.py                      # -> backups/recipes-<stamp>.db, ~328 MB
LIVE=$(python3.13 -c 'import sys; sys.path.insert(0,"scripts"); import corpus_guard; print(corpus_guard.live_db())')
shasum -a 256 "$LIVE"                     # record it. It was
                                          # 414595961800c7e0bb2634bd4861daa0f133e11307000ec868c8110a6d236387
                                          # throughout the rehearsal, which is the value
                                          # docs/data-repairs/demo-data-2026-07.md records.
shasum -a 256 "backups/recipes-<stamp>.db"   # MUST equal the line above
git fetch origin && git rev-parse origin/main
```

**The backup is the data rollback**, and a backup nobody fingerprinted is a hope. Take it before the
migration, not after, because the migration is the first thing that writes.

## 1. Prove it on a branch, not on main

```sh
git push origin HEAD:refs/heads/ci/note-titles
# read the checks, step by step (golive/README.md section 2)
git push origin main
git push origin --delete ci/note-titles
```

⚠️ **"Run Postgres integration tests" must read `success`, not `skipped`.** This round adds
`alembic/versions/c5f1a73b2d80_recipe_note_title.py`, and the Postgres leg is the only place that
file is ever applied. A skipped step means the Alembic revision has never run anywhere.

## 2. The MIGRATION goes first, before the deploy

⚠️ **062 IS ADDITIVE, SO IT RUNS BEFORE THE CODE** (the 053 rule). The new code selects
`recipe_notes.title`, so deploying first would fail every recipe page on a column that does not
exist yet. The old code does not name the column at all, so it serves the migrated schema fine,
which is what makes this order available. Proven in section 7b.

```sh
python3.13 migrate.py --db "$LIVE" --i-mean-live
python3.13 -c "
import sqlite3,sys
c = sqlite3.connect('file:$LIVE?mode=ro', uri=True)
print([d[1] for d in c.execute('PRAGMA table_info(recipe_notes)')])
print(c.execute('SELECT max(filename) FROM schema_migrations').fetchone())"
```

Then check :8000 still serves, BEFORE going any further. The running deploy is `f7c41c8` and it must
read the migrated database unchanged.

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/
```

## 3. Repin the serve worktree and restart :8000

```sh
NEW=$(git rev-parse HEAD)
pkill -f scripts/serve_live.py

cd "/Users/andrewhannah/Documents/Local Documents/Food/recipe-app-serve"
git fetch origin && git checkout --detach "$NEW"
npm install && npm run build              # the pinned worktree builds its OWN dist/
git rev-parse HEAD                        # must equal $NEW

nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 &
disown
```

Prove it by the process's directory, never by the bundle name: two worktrees at one commit build
byte-identical bundles.

```sh
lsof -a -p "$(pgrep -f scripts/serve_live.py | head -1)" -d cwd -Fn   # must name recipe-app-serve
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/
shasum -a 256 "$LIVE"            # moved by the migration in step 2, unchanged by this restart
```

## 4. The data step

Read the before state from a FRESH COPY, because the gate wants a before and an after and live is
about to become the after.

```sh
SP=<scratchpad>
cp "$LIVE" "$SP/golive-before.db"                       # copy, never symlink
python3.13 scripts/gates/state.py --db "$SP/golive-before.db" --out "$SP/golive-before.json"

python3.13 scripts/apply_note_titles.py --db "$LIVE" --i-mean-live            # the dry run, ALWAYS
python3.13 scripts/apply_note_titles.py --db "$LIVE" --apply --i-mean-live

cp "$LIVE" "$SP/golive-after.db"
python3.13 scripts/gates/state.py --db "$SP/golive-after.db" --out "$SP/golive-after.json"
python3.13 scripts/gates/rounds.py \
  --round golive/rounds/2026-10-06-note-titles.json \
  --before "$SP/golive-before.json" --after "$SP/golive-after.json" \
  --a-db "$SP/golive-before.db" --b-db "$SP/golive-after.db"
```

Read the dry run against the round file before typing `--apply`. On the rehearsal it printed
`decisions read: 57`, `to write: 33`, `no-op: 3`, `not this round's business: 21`,
`flagged for a later round: 1`, `refused: 0`.

The gate must print **THE ROUND DID EXACTLY WHAT IT DECLARED** and exit 0. On the rehearsal it did,
with `recipe_notes 177 -> 176`, the short-circuit set `280 of 300` unchanged as a SET, the 49
annotation entries over 20 recipes unchanged entry by entry, `integrity ok`, `0` foreign-key
violations, and `recipes.notes`, `recipe_notes_original` and `recipe_note_step_refs` byte-identical.

⚠️ **A SECOND RUN IS A CLEAN NO-OP**, which is what makes an interrupted pass resumable. Each
recipe's gate runs inside its own transaction and rolls back rather than reporting on data already
written, so an abort part way through leaves the earlier recipes written and correct, and re-running
reports 0 to write for them.

⚠️ **`recipe_notes_original` IS NEVER TOUCHED**, and the retired `recipes.notes` column is left
alone. The originals are a LIST of the author's paragraphs, not a join against the note rows, so the
merge's deleted row keeps its original and the table still holds 177 against 176 note rows. That is
correct, not drift.

## 5. Confirm, and record

```sh
shasum -a 256 "$LIVE"            # it WILL have moved twice, by the migration and by the pass
```

Then on http://127.0.0.1:8000/, logged in as andyhannah2014@gmail.com:
`all-butter-pie-crust`, `brioche-cinnamon-rolls`, `1-2-3-4-5-tofu`, `dan-dan-noodles`, `waffle`,
`french-fries`, `smashed-cucumber-salad`, `key-lime-pie`, `agedashi-tofu`, `chicken-broth`,
`bulgogi-bowls`, `italian-two-bean-soup`. Each on the recipe page and in Edit mode.

A record in `docs/data-repairs/`, in the PAST TENSE, after the run.

## 6. Rollback, both of them

### The code

⚠️ **THE CODE ROLLS BACK ON ITS OWN, AND THE SCHEMA STAYS.** 062 is additive, so `f7c41c8` reads
the migrated database without naming the new column. Measured in section 7b.

```sh
pkill -f scripts/serve_live.py
cd "/Users/andrewhannah/Documents/Local Documents/Food/recipe-app-serve"
git checkout --detach f7c41c8
npm run build                               # node_modules does not move with the checkout
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
```

The titles stop printing, because the old bundle has no `.note-title` in it. They are still in the
column, and section 7b measured that the old Edit-mode Save does not destroy them.

### The data

⚠️ **A WHOLE-FILE RESTORE FROM STEP 0'S BACKUP. There is no row-level undo, and there is no
down-migration.** That is the plan, and it covers both the migration and the pass in one step.

```sh
pkill -f scripts/serve_live.py
cp "backups/recipes-<stamp>.db" "$LIVE"     # the backup from step 0
shasum -a 256 "$LIVE"                       # must equal the value recorded in step 0
# then restart :8000 as above, at whichever commit you want serving
```

⚠️ **DO NOT TRY TO UNDO THE PASS BY HAND.** Clearing 28 titles and putting the labels back on the
front of 28 texts is 28 edits that have to agree with each other, the merge deleted a row whose id
nothing can mint again, and the two ingredient headings were patched in lockstep with their
`reason='original'` baselines. The backup is the only thing that returns the database to the state
it was in.

⚠️ **AND SQLITE CANNOT DROP A COLUMN WITHOUT REBUILDING THE TABLE.** There is deliberately no
`062_down`. A rebuild of `recipe_notes` would mint new row ids and `recipe_note_step_refs` names
them, so the column stays even on a rollback. It is nullable and nothing reads it in `f7c41c8`, so
it costs nothing to leave.

⚠️ **THE WINDOW MATTERS.** Anything written to live between step 0's backup and a restore is lost by
the restore. Keep them close together and do not cook or rate anything in between.

## 7. What was proven on a copy before any of this

### 7a. Migration 062 is all-or-nothing

Measured 2026-10-06 on a copy of live at migration 061, in two shapes:

| shape | result |
|---|---|
| a statement errors after the `ALTER`, inside the transaction | schema identical, row counts identical, `title` absent, 062 not recorded, **sha256 unchanged** |
| the process is killed after the `ALTER`, before the `COMMIT` (`os._exit`, a real crash) | schema identical, row counts identical, `title` absent, 062 not recorded, **sha256 unchanged** |

And the retry works: an ordinary `migrate.py` afterwards applies the file cleanly. The file carries
its own `BEGIN;`/`COMMIT;`, which is what makes all of that true, because `migrate.py` applies each
migration with `executescript` and that opens no transaction of its own.

The check is now standing and in CI rather than a one-off:
`tests/test_migration_atomicity.py::test_a_migration_interrupted_inside_its_transaction_leaves_nothing_behind`
states it over every migration that opens a transaction, and
`test_an_additive_column_migration_carries_its_own_transaction` states it over the folder so the
next additive migration written is covered.

⚠️ **AND IT FOUND SEVEN OLDER MIGRATIONS WITH NO TRANSACTION.** 009, 013, 015, 018, 027, 031 and
048 each add two or more columns under one `executescript`, so an interrupted run leaves some
columns added with the filename unrecorded, and the retry then dies forever on "duplicate column
name". 031 is the worst: two `ADD COLUMN`s followed by two `UPDATE`s, so a backfill can be missing
with the columns in place. **None of them is a risk to live or to any database past them**,
because `migrate.py` tracks by filename and never by checksum. It is a FRESH CLONE that is
exposed. They are
named in `UNWRAPPED_ADDITIVE` in that test file with this reason, and the list is closed. Wrapping
them is a decision for Andy, not something to smuggle into a round about note titles.

### 7b. The code rollback is safe

Measured 2026-10-06. `f7c41c8`, the running deploy, was checked out into its own worktree, given the
`dist/` from `../recipe-app-serve` at the same commit, and pointed at a COPY of the database that
migration 062 **and** the pass had both already touched, on :8003. Live was never opened.

- All 13 recipe pages above rendered: steps present, notes present, **0 JavaScript errors**, no error
  screen. `.note-title` count 0, which is right, because the old bundle has no title rendering in
  it.
- Edit mode opened and **Save changes** succeeded with 0 JavaScript errors. Note ids unchanged, note
  texts unchanged, **both of italian-two-bean-soup's titles still in the column afterwards**.
- Then the harder half: note 83's words were REWORDED through the old editor and saved. The text
  changed, the id did not, and the title `Cannellini` survived.

⚠️ **AND THE MECHANISM, NOT JUST THE RESULT.** `f7c41c8`'s `write_notes` builds
`dict(recipe_id, position, kind, text, step_id, ingredient_row_id)` and `_apply_rows` UPDATEs
exactly those columns on a matched row, so `title` is never named and never cleared. "A save keeps
the rows it was given" is what makes the old code safe over the new column. A note DELETED by the
old client loses its title with its row, which is correct.
