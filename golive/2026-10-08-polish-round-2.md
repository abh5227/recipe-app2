# Go-live: polish round 2

**Written, not run.** Every command below is for the day it is run, against live. Nothing here has
been executed against `recipes.db`. The round was rehearsed end to end on a copy on 2026-10-08 and
the figures each step expects are the ones that rehearsal produced.

**What it carries.** 189 writes over 84 recipes, from three committed decision files, plus the code
that makes them. Part 5 is **15 labels stripped and 10 lifted into a title**, after Andy's
2026-10-08 call that "Storing" restates the Storage kind, which is declared in
`static/note-kinds.json` rather than derived by a rule: `import_cleanup.names_a_stage`, `strip_author_letters`,
`strip_author_numbers_by_section`, `continues_the_line_above`, `note_label_plan`,
`footnote_step_plan`, `strip_footnote_markers`, `optional_ingredient_groups`, the importer wiring for
all of them, and `scripts/gates/cells.py`.

**No schema change.** Nothing in this round touches `migrations/` or `alembic/`, so the local
Postgres leg is not required. Confirm that rather than assume it:

```sh
git diff --name-only 0458c88..HEAD | grep -E '^(migrations|alembic)/' && echo "STOP: this round IS structural" || echo "no schema change"
```

**The order against the deploy, and why it is free either way.** The new code reads no new column and
writes nothing at serve time: every rule in it runs in the importer or in a pass. The new data lives
in columns the running code already reads (`recipe_steps.heading_level`, `recipe_ingredients.label`
and `.is_heading`, `recipe_notes.text` and `.title`, all shipped). So the version that can serve BOTH
states is the one already running, and there is no cutover to get wrong. Step 3 verifies that instead
of asserting it.

---

## 0. Before anything

```sh
LIVE="$(PYTHONPATH=scripts python3.13 -c 'import corpus_guard; print(corpus_guard.live_db())')"
SP=/tmp/golive-2026-10-08 && mkdir -p "$SP"
echo "DATABASE_URL=[${DATABASE_URL-}]"            # must print []
shasum -a 256 "$LIVE"
```

Live's fingerprint must read **`a05f2efc26a9e1e66446e61df093ffd86ee61b43c6b39b8cee1cdb0ef0548e50`**,
which is what it has read since the 2026-10-07 go-live finished at 16:59. If it has moved, find out
what moved it before going further. `:8000`'s request log names writes, and nothing in this round's
preparation opened live for writing.

```sh
python3.13 backup.py
BACKUP="$(ls -t backups/*.db | head -1)" && echo "BACKUP=$BACKUP"
shasum -a 256 "$BACKUP" "$LIVE"                               # the two must MATCH
git fetch origin && git rev-parse origin/main                 # expect 0458c88 before the push
```

A backup nobody fingerprinted is a hope. The data rollback in section 6 restores **this exact file**.

⚠️ **WRITE THE VALUE OF `$BACKUP` DOWN, HERE, BEFORE GOING ON.** The rollback used to say "the
newest backup", which is a different file the moment anything else runs `backup.py`, and the one
moment you reach for a rollback is the one moment you are not thinking about that. A restore of the
wrong backup is silent: it is a valid database, it is just not the one this round started from.

    BACKUP = ______________________________________________

## 0b. The CI-condition run, from a FRESH CLONE

```sh
rm -rf /tmp/ci-check && git clone --no-hardlinks . /tmp/ci-check
cd /tmp/ci-check && git checkout --detach "$(git -C "$OLDPWD" rev-parse HEAD)"
python3.13 -m pytest -q && node --test tests/js/*.test.js
cd -
```

⚠️ **A LINKED WORKTREE IS NOT THIS CONDITION.** `corpus_guard.live_db()` finds the MAIN working tree
through `git rev-parse --git-common-dir`, so from a worktree the real database is still live and six
guard tests fail for that reason alone. The clone has its own `.git`, so its `live_db()` names its own
absent file, which is what CI sees.

## 1. Prove it on a branch, not on main

```sh
git push origin HEAD:refs/heads/ci/polish-round-2
# wait, then read the STEPS of both workflows, not just the conclusion
git push origin main
git push origin --delete ci/polish-round-2
```

## 2. Read the checks, step by step

With `gh`, which reads the steps in one call and needs no run id:

```sh
gh api "repos/abh5227/recipe-app2/actions/runs?per_page=8&branch=ci/polish-round-2" \
  --jq '.workflow_runs[] | "\(.name): \(.status)/\(.conclusion) \(.head_sha[0:7]) \(.id)"'
gh api "repos/abh5227/recipe-app2/actions/runs/<id>/jobs" \
  --jq '.jobs[] | .name as $j | .steps[] | "\($j)  \(.conclusion)  \(.name)"'
```

⚠️ **`gh` IS NOT INSTALLED ON THIS MACHINE AND NO PREVIOUS ROUND USED IT.** Checked 2026-10-08:
`gh` is on no PATH entry and there is no `GH_TOKEN` or `GITHUB_TOKEN` in the environment. Every round
so far read the checks with the `curl` form below, against the public API. Use `gh` if it is there,
because its job output is easier to read and it authenticates, and otherwise use this, which does the
same job:

```sh
curl -s "https://api.github.com/repos/abh5227/recipe-app2/actions/runs?per_page=8&branch=ci/polish-round-2" \
  | python3.13 -c "import json,sys; [print(f\"{r['name']}: {r['status']}/{r['conclusion']} {r['head_sha'][:7]} {r['id']}\") for r in json.load(sys.stdin)['workflow_runs']]"

curl -s "https://api.github.com/repos/abh5227/recipe-app2/actions/runs/<id>/jobs" \
  | python3.13 -c "import json,sys; [print(' ', s['conclusion'], s['name']) for j in json.load(sys.stdin)['jobs'] for s in j['steps']]"
```

⚠️ **AND THE UNAUTHENTICATED FORM CANNOT READ A JOB LOG** (the API answers 403), so a failure has to
be diagnosed from the code. That is the second reason to run on a branch: a red branch costs nothing
and a red main is a bisect.

⚠️ **"Run Postgres integration tests" must read `success`, not `skipped`.** The module skips on one
mark, so an all-skipped run exits 0 and is indistinguishable from a pass in the job's green tick. This
round changes no schema, which is a reason to expect the step to pass and NOT a reason to accept a
skip: the step is the only place `migrations/*.sql` and `alembic/` are compared at all.

Red means stop. Do not repin, do not apply.

## 3. Repin the serve worktree and restart :8000, BEFORE the data step

```sh
NEW=$(git rev-parse HEAD)
pkill -f scripts/serve_live.py
cd ../recipe-app-serve && git fetch origin && git checkout --detach "$NEW"
npm install && npm run build
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
cd -
```

Prove it by the process's directory, never by the bundle name: two worktrees at one commit build
byte-identical bundles.

```sh
lsof -a -p "$(pgrep -f scripts/serve_live.py | head -1)" -d cwd -Fn    # must name recipe-app-serve
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/
shasum -a 256 "$LIVE"                                                  # unchanged by a restart
```

**Then open the app against the still-old data and confirm the recipe pages work.** This is the half
of the deploy-order rule that is a measurement rather than an argument: the new code is now in front
of data the round has not touched yet, and it has to serve it.

```sh
python3.13 - <<'EOF'
import json, urllib.request
ids = [r["id"] for r in json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/recipes"))["recipes"]]
bad = []
for rid in ids:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:8000/api/recipes/{rid}").read()
    except Exception as e:
        bad.append((rid, str(e)))
print(f"{len(ids) - len(bad)}/{len(ids)} recipe pages built")
print("STOP:", bad[:5]) if bad else print("every page built against the OLD data")
EOF
```

## 4. The data step

⚠️ **NO WRITES IN FLIGHT.** Nobody is in Edit mode, no note is mid-save. The pass takes one
transaction per recipe and the gate reads the whole corpus, so a save landing between the two
readings is a difference the gate will report and nobody will be able to explain.

```sh
cp "$LIVE" "$SP/before.db"                         # copy, never symlink
python3.13 scripts/gates/state.py --db "$SP/before.db" --out "$SP/before.json"

python3.13 scripts/apply_polish_round_2.py "$LIVE" --i-mean-live            # the DRY RUN, always first
python3.13 scripts/apply_polish_round_2.py "$LIVE" --apply --i-mean-live

cp "$LIVE" "$SP/after.db"
python3.13 scripts/gates/state.py --db "$SP/after.db" --out "$SP/after.json"
python3.13 scripts/gates/rounds.py --round golive/rounds/2026-10-08-polish-round-2.json \
  --before "$SP/before.json" --after "$SP/after.json" \
  --a-db "$SP/before.db" --b-db "$SP/after.db"
```

The dry run must print exactly this, and if it does not, do not type `--apply`:

```
  decisions read            : 78 levels, 112 names, 15 rows
  to write                  : 189 over 84 recipe(s)
      part 1: 78
      part 2: 78
      part 3: 2
      part 4: 2
      part 5: 25
      part 6: 4
  already in place (no-op)  : 0
  refused                   : 0
```

The gate must print **THE ROUND DID EXACTLY WHAT IT DECLARED** and exit 0. Rehearsed 2026-10-08:
short-circuit 280 to 280 and the same set, annotations 49 over 20 and identical, integrity ok, 0
foreign-key violations, and the six declared counts moving and nothing else.

## 4b. The check the GATE CANNOT MAKE

⚠️ **FOUR TABLES ARE IN `tables.except`, AND AN EXCEPTED TABLE IS NOT COMPARED AT ALL.** They have to
be, because the round writes to all four and the row-for-row comparison would fail on every write. The
cost is that the gate then says nothing about any OTHER cell of those four tables, which are the only
tables this round can reach. The exception is a hole, so the hole gets its own check, and this time it
is a committed tool rather than a script in this file.

```sh
python3.13 scripts/gates/cells.py --a "$SP/before.db" --b "$SP/after.db" \
  --round golive/rounds/2026-10-08-polish-round-2.json
```

It must print **EVERY MOVED CELL WAS DECLARED**. Rehearsed 2026-10-08:

```
  recipe_steps:       2486 rows x  6 columns =  14916 cells, 89 moved over 89 rows; 1 deleted, 0 inserted
  recipe_ingredients: 3572 rows x 18 columns =  64296 cells, 105 moved over 102 rows; 0 deleted, 1 inserted
  recipe_notes:        176 rows x  8 columns =   1408 cells, 35 moved over 25 rows; 0 deleted, 1 inserted
  recipe_snapshots:    306 rows x  7 columns =   2142 cells, 69 moved over 69 rows; 0 deleted, 0 inserted
```

82,762 cells compared, 298 moved, every one on a row and in a column the round names. Proved red five
ways on a mutation copy during the rehearsal: a stray write to an undeclared row, a write in an
undeclared column, a declared change that did not happen, an extra inserted row, and a declared column
that moved on no row.

## 5. Confirm, and record

- The login works and all 300 recipes are there.
- Live's new sha256, recorded.
- The commit serving `:8000`, read off the process's directory.
- The spot-check list below.
- A record in `docs/data-repairs/`, **written in the past tense after the run**. A record committed
  ahead of the apply makes the repo assert a change to live that may never happen.

### The spot-check list

| open | and look for |
|---|---|
| `#/recipe/french-fries` | five sections, then `Fry #1`, `50 sec fry`, `30 min cool` and `Fry #2` all at the SAME level. This is the case the stage rule was written for. |
| `#/recipe/acqua-pazza` | eight sections, no subheadings left |
| `#/recipe/kfc-spicy-chicken-rice-bowl` | `Fry the chicken (the first time)` and `Fry the chicken again` both sections, `Assembly` unchanged |
| `#/recipe/brioche-bread` | `Option 1:` and `Option 2:` still SUBHEADINGS, and `Baking` still a section. Both are author-written and nothing in this round may touch them. |
| `#/recipe/karak-chai` | steps 8 to 10 read `Bring`, `Remove`, `Once`, with no a/b/c |
| `#/recipe/homemade-pasta-dough` | the step under `Cooking` reads `Bring a salted water to a boil`, with no `1.` |
| `#/recipe/stir-fried-green-beans-with-pork` | nine steps, not ten. No asterisk in the method. One note, linked to the charring step. |
| `#/recipe/vanilla-mug-cake` | `70-90 seconds` with no asterisk |
| `#/recipe/the-best-new-york-style-bagel` | a note titled `Same day version`, and a second note with no `Note:` in front of its words |
| `#/recipe/all-butter-pie-crust` | two storage notes, titled `To Store` and `To Freeze`, and the total still reading 1 hr 15 min |
| `#/recipe/quick-easy-hainanese-chicken-rice-khao-mun-gai` | an `Optional` ingredient heading over two lines reading `extra chicken stock...` and `fresh cucumber slices...`, and `Basic Asian-Style Chicken Stock` now a heading |
| `#/recipe/red-wine-braised-short-ribs` | five lowercased names, `boneless short ribs` first |
| `#/recipe/minestrone-soup` | `grated Parmesan cheese for garnish` — lowercased except the brand-name cheese |
| `#/recipe/chicken-marsala` | four lowercased names, `crimini mushrooms, sliced or quartered` among them |
| any of the above | the page must NOT say your changes. Every one of these is a machine repair in lockstep. |

## 6. Rollbacks, both of them

**The code** rolls back on its own, because this round changes no schema.

```sh
pkill -f scripts/serve_live.py
cd ../recipe-app-serve && git checkout --detach 8fe756d && npm run build
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
cd -
lsof -a -p "$(pgrep -f scripts/serve_live.py | head -1)" -d cwd -Fn    # must name recipe-app-serve
```

⚠️ **`8fe756d`, NOT `0458c88`, AND THE DIFFERENCE IS WHICH ONE IS ACTUALLY RUNNING.** `origin/main`
is at `0458c88`, and the worktree serving `:8000` is pinned at `8fe756d`, three commits behind it.
An earlier draft of this file named `0458c88` on the assumption that main and the serve pin were the
same thing. Rolling back to a commit `:8000` has never run is not a rollback.

The three commits between them (`91f232e`, `5104094`, `0458c88`) touch `CLAUDE.md`,
`golive/README.md`, two files in `docs/data-repairs/`, `tests/test_mining_boundaries.py` and
`brand_guard.py`. Only the last is code, and **`app.py` does not import it**: `brand_guard` is read
by `dish_facets.py`, `substitution_run.py`, `load_dish_facets.py`, `dish_facet_run.py` and
`library_viewer.py`, none of which the serving app touches. So the two commits are identical as far
as serving goes, and `8fe756d` is the one with a running record.

**Measured rather than reasoned, 2026-10-08:** `8fe756d` was pointed at a copy of live with this
round APPLIED and built **300 of 300 recipe pages**. The code rollback therefore stands on its own
with the data left in place, which is the case that matters: it is the rollback you reach for when
the data step was fine and the deploy was not.

**The data** rolls back by restoring **the exact file step 0 recorded**, not the newest one.

```sh
pkill -f scripts/serve_live.py
echo "restoring $BACKUP"                           # if $BACKUP is unset, read it off step 0's note
cp "$BACKUP" "$LIVE"
shasum -a 256 "$LIVE"                              # must match step 0's reading of $BACKUP
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
```

⚠️ **"THE NEWEST BACKUP" IS NOT THIS BACKUP.** `backup.py` is run by the import runner and by hand,
so the newest file changes under you, and a restore of the wrong one is silent: it is a valid
database, just not the one this round started from. The name is written down at step 0 for that
reason.

⚠️ **NEVER BY RE-INSERTING ROWS BY HAND.** This round INSERTS two rows and DELETES one. A new row
gets a new id, and `recipe_notes.step_id` and every baseline entry that names an id would be wrong.
Anything written to live between the backup and the restore is lost by the restore, so keep the two
close together.

⚠️ **AND THERE IS NO PARTIAL ROLLBACK OF PART 1.** Running the pass again does nothing (it is a
no-op, measured), and there is no reverse pass. 78 heading levels and one deleted step come back from
the file or not at all.
