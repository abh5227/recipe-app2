# Go-live: the safety round and the time block, together

Two rounds, one deploy. The order is **the code first, then migration 063**, which is the opposite
of the titles round's order and for a stated reason: 063 is DESTRUCTIVE.

> **A migration's order against the deploy follows its direction.** Additive before the deploy,
> destructive after. The question is which of the two versions names something the other side does
> not have. The new code has stopped naming `recipes.notes`, so it serves a database that still has
> the column. The old code still declares it on `Recipe`, so it cannot serve one without it. The
> version that can serve BOTH schemas is the new one, and that is the one that runs in the middle.

Measured both ways on copies, not reasoned out. See section 7.

## 0. Before anything

```sh
LIVE="$(python3.13 -c 'import sys; sys.path.insert(0,"scripts"); import corpus_guard; print(corpus_guard.live_db())')"
python3.13 backup.py
shasum -a 256 "$LIVE" backups/recipes-*.db | tail -2      # the two must match
git fetch origin && git rev-parse origin/main             # expected: 848094f, the titles round
```

Live's sha256 at the end of the rehearsal, 2026-10-07: unchanged all round. Live was opened
`mode=ro` only.

## 1. Prove it on a branch, not on main

```sh
git push origin HEAD:refs/heads/ci/safety-and-time-block
# read the checks step by step (golive/README.md section 2)
# ⚠️ "Run Postgres integration tests" must read success, not skipped
git push origin main
git push origin --delete ci/safety-and-time-block
```

⚠️ **This is the first CI run since `848094f`.** Five commits have never been through it. Two
defects found in review would have taken it red on their own and are fixed in this round: an
assertion on `library_names` that only passes on a machine holding the untracked server-side CSV,
and `tests/pg_harness.py` naming `notes=` in an INSERT against a model that no longer has the
column, which fails at COMPILE time and takes out every test using the `pg` fixture.

## 2. The CODE goes first

```sh
NEW=$(git rev-parse origin/main)
pkill -f scripts/serve_live.py
cd ../recipe-app-serve && git fetch origin && git checkout --detach "$NEW"
npm install && npm run build
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
lsof -a -p "$(pgrep -f scripts/serve_live.py | head -1)" -d cwd -Fn   # must name recipe-app-serve
```

**Then stop and look at the app before touching the schema.** The new code is now serving the OLD
schema, which still has the column. Open three recipe pages, save one, and confirm the time block
reads in two columns. This is the step that makes the whole order safe, and skipping it turns a
reasoned claim back into an unverified one.

## 3. The MIGRATION goes second

```sh
cp "$LIVE" "$SP/before.db"                         # copy, never symlink
python3.13 scripts/gates/state.py --db "$SP/before.db" --out "$SP/before.json"

python3.13 migrate.py --db "$LIVE" --i-mean-live   # applies 063 and nothing else

cp "$LIVE" "$SP/after.db"
python3.13 scripts/gates/state.py --db "$SP/after.db" --out "$SP/after.json"
python3.13 scripts/gates/rounds.py --round golive/rounds/2026-10-07-safety-and-time-block.json \
  --before "$SP/before.json" --after "$SP/after.json" \
  --a-db "$SP/before.db" --b-db "$SP/after.db"
```

The gate must print **THE ROUND DID EXACTLY WHAT IT DECLARED**. It did, on the rehearsal copies.

Measured on a 344 MB copy: migration 063 took **0.08 s**.

## 4. Confirm, and record

- A recipe page, a save, the notes still there, the time block in two columns.
- Live's new sha256, recorded.
- The commit serving :8000.
- A record in `docs/data-repairs/`, in the past tense, **after** the run.

## 5. Rollback

There are two, and which one you need depends on whether 063 has run.

### Before 063: repin, and nothing else

The schema has not moved, so the code rolls back on its own.

```sh
pkill -f scripts/serve_live.py
cd ../recipe-app-serve && git checkout --detach 7d703b7 && npm run build
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
```

### After 063: put the column back, THEN repin

⚠️ **REPINNING ALONE IS NOT A ROLLBACK ONCE 063 HAS RUN, AND THE SYMPTOM IS TOTAL.** Measured: live's
own code at `7d703b7`, served against a copy 063 had been applied to, answers

```
GET /                          200
POST /api/login                200
GET /api/recipes               200      <- the home list survives: it names its columns in text() SQL
GET /api/recipes/brioche-bread 500      <- every recipe page, all 300
```

```
app.py:1809 in get_recipe
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such column: recipes.notes
```

`models.py` at `7d703b7` declares `notes = Column(Text)`, so `select(Recipe.__table__)` names it.

**The column comes back EMPTY, and it does not need to come back full.**

```sh
pkill -f scripts/serve_live.py
sqlite3 "$LIVE" 'ALTER TABLE recipes ADD COLUMN notes TEXT;'
cd ../recipe-app-serve && git checkout --detach 7d703b7 && npm run build
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
```

Measured: the re-add took **0.003 s** on the 344 MB copy, and the old code then answers 200 on every
recipe page. Section 7c is the proof that an empty column costs the page nothing.

⚠️ **A FULL RESTORE FROM THE BACKUP IS THE HEAVIER OPTION AND IT IS NOT THE ONE TO REACH FOR FIRST.**
It is correct, but it discards everything written to live since step 0, and the thing that broke is a
column nothing reads. Re-adding it empty is a 3 ms, lossless repair. Restore from the backup only if
something OTHER than the column is wrong.

## 6. What was rehearsed, and on what

Everything below ran on copies made with `scratchpad/make_copy.py`, which refuses a destination that
is live by resolved path or by device and inode and refuses one outside the session scratchpad.
Three servers, all from pinned worktrees, none of them `:8000` or `:8002`:

| port | code | data |
|---|---|---|
| 8004 | `7d703b7`, live's commit | `sweep.db`, a copy, column populated |
| 8005 | `9d780a8` plus this round | the same `sweep.db` |
| 8006 | `7d703b7` | `rollback063.db`, 063 applied |
| 8007 | `7d703b7` | `rollback063_readded.db`, 063 applied then the column re-added empty |

## 7. What was proven on a copy

### 7a. The deploy order, forwards

The new code against a database that still HAS the column: `:8005` served all 300 recipes.

### 7b. The page outside the time block is live's page, to the pixel

`:8004` against `:8005`, the same copy, 9 recipes at 1400px and at 390px, 18 comparisons. With
`.above-ing` (the time block and the scaler) hidden on BOTH sides, every page matched in height and
**0 pixels differed**, with no tolerance.

⚠️ **HIDDEN, NOT NEUTRALISED, AND THAT IS THE OPPOSITE OF THE LAST ROUND'S CHOICE.** The titles round
changed a colour, so `display: none` would have been wrong: it removes the element from the flow and
everything under it moves. This round changes the block's HEIGHT, so a raw comparison measures the
displacement rather than the content. Hiding the same element on both sides puts what is above it and
what is below it on identical rows.

The block's own height, before to after, at 1400px: brioche-bread 212 to 190, morning-buns 184 to
232, italian-two-bean-soup 77 to 166, coconut-curried-golden-lentils 94 to 166, no-knead-bread 174 to
195, apple-pie 194 to 171, earl-grey-tea-cake 181 to 180, waffle 58 to 171, beans 52 to 126. Every
page's total height moved by that amount and by nothing else, within a pixel of rounding.

### 7c. The rollback loses nothing on the page

`:8004` (column populated) against `:8007` (column re-added empty), same code, 9 recipes at both
widths, nothing hidden: **18 of 18 pixel-identical, 0 pixels differing**.

The only difference anywhere is in the API payload: `recipe.notes` echoes the raw column, `""` or
`null` instead of the stored text, on 111 of the 300. Nothing on the client reads it. The payload's
top-level `notes` key, which is what the page renders, is the `recipe_notes` ROWS and is byte-equal
on all 300.

### 7d. Nothing is lost by the drop

Measured on live, read-only: 300 recipes, 95 carrying note rows, 95 carrying `recipe_notes_original`,
**0 needing a backfill**. 19 of the 95 already had a derived column that no longer agreed with their
rows, which is what a derived copy that nothing re-derives does.

### 7e. The thirteen migration wraps change nothing

A fresh install built from `migrations/` as it stands, and again with every `BEGIN;`/`COMMIT;`
stripped out, compared as a full `iterdump()`. Identical. `tests/test_migration_equivalence.py`.

⚠️ **Live and every other database past these files is untouched by the edit**, because `migrate.py`
tracks by filename and never by checksum. The wrap protects a FRESH INSTALL, which is the only thing
that still runs them.
