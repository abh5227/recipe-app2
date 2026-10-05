# Go-live: the safety round

Written to be run at STOP 2, not run. Nothing below has been executed. Every command names its
database or its port.

This round is the first with a **data** step as well as a code step, so it has two rollbacks.

## 0. Before anything

```sh
cd "/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
python3.13 backup.py                      # -> backups/recipes-<stamp>.db, ~328 MB
LIVE=$(python3.13 -c 'import sys; sys.path.insert(0,"scripts"); import corpus_guard; print(corpus_guard.live_db())')
shasum -a 256 "$LIVE"                     # record it. It was
                                          # 1528fffb0d00c7c7cd7ddbc4097dc7661c2e45c46295e46819fa68c45100362b
                                          # at the end of the previous round.
git fetch origin && git rev-parse origin/main    # must be 478e33f…
```

**The backup is the data rollback.** It is taken before the push rather than before the removal,
because the removal is the only step that writes and a restore is simpler than an undo.

## 1. Push

```sh
git log --oneline origin/main..HEAD
git push origin main
```

## 2. Wait for the checks, and read the Postgres leg specifically

```sh
curl -s "https://api.github.com/repos/abh5227/recipe-app2/actions/runs?per_page=6&branch=main" \
  | python3.13 -c "import json,sys; [print(f\"{r['name']}: {r['status']}/{r['conclusion']} {r['head_sha'][:7]}\") for r in json.load(sys.stdin)['workflow_runs']]"
```

Then, for the run id of the SonarQube workflow, read the steps rather than only the conclusion:

```sh
curl -s "https://api.github.com/repos/abh5227/recipe-app2/actions/runs/<id>/jobs" \
  | python3.13 -c "import json,sys; [print(' ', s['name'], s['conclusion']) for j in json.load(sys.stdin)['jobs'] for s in j['steps']]"
```

⚠️ **"Run Postgres integration tests" must read `success`, not `skipped`.** This round added
`tests/urlguard.py`, which refuses to start the suite when `$DATABASE_URL` is set without
`RECIPE_APP_TEST_DATABASE=1`. The workflow now sets both, and
`tests/test_database_url_guard.py::test_the_postgres_ci_leg_declares_its_database_so_it_keeps_running`
reads `build.yml` to check they sit together. The step's own ran-nothing guard asserts at least one
test actually ran, so a silent skip fails the step rather than exiting 0. Read it anyway: a guard
that refuses at import would make the leg fail loudly, and a guard that is wrong in the other
direction would let it run against the wrong database.

Red means stop. Do not repin.

## 3. Repin the serve worktree and restart :8000

⚠️ **`serve_live.py` RUNS FROM THE PINNED WORKTREE, NOT FROM THE WORKING TREE.** The script's own
guard refuses the working tree and prints why. The previous round's plan had this wrong and the guard
caught it.

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

Confirm it serves the new commit, and prove it by the process's directory rather than by the bundle
name: two worktrees at the same commit build byte-identical bundles, so a matching name proves
nothing.

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/
lsof -a -p "$(pgrep -f scripts/serve_live.py | head -1)" -d cwd -Fn   # must name recipe-app-serve
curl -s http://127.0.0.1:8000/api/me                                  # {"user":null} while logged out
shasum -a 256 "$LIVE"                                                 # unchanged by the restart
```

## 4. The account removal, on live

Read the before state from a FRESH COPY, not from live, because the gate wants a before and an after
and live is about to become the after.

```sh
SP=<scratchpad>
cp "$LIVE" "$SP/golive-before.db"                       # copy, never symlink
python3.13 scripts/gates/state.py --db "$SP/golive-before.db" --out "$SP/golive-before.json"

# the dry run first, ALWAYS, and read what it says about collateral
python3.13 scripts/remove_demo_accounts.py --db "$LIVE" --i-mean-live

# then the write
python3.13 scripts/remove_demo_accounts.py --db "$LIVE" --apply --i-mean-live

cp "$LIVE" "$SP/golive-after.db"
python3.13 scripts/gates/state.py --db "$SP/golive-after.db" --out "$SP/golive-after.json"
python3.13 scripts/gates/rounds.py \
  --round golive/rounds/2026-10-05-remove-demo-accounts.json \
  --before "$SP/golive-before.json" --after "$SP/golive-after.json" \
  --a-db "$SP/golive-before.db" --b-db "$SP/golive-after.db"
```

The gate must print **THE ROUND DID EXACTLY WHAT IT DECLARED** and exit 0. On the rehearsal it did,
with `users 4 -> 1`, `cook_log 137 -> 133`, `comments 5 -> 1`, `friendships 3 -> 0`,
`shared_posts 10 -> 3`, `invites 1 -> 0`, the short-circuit set 280 unchanged, the 49 annotation
entries over 20 recipes unchanged entry by entry, all 11 content tables identical, integrity ok and
0 foreign-key violations.

⚠️ **THE DRY RUN NAMES YOUR OWN COMMENT BEFORE IT GOES.** `comments.post_id -> shared_posts.id` is
ON DELETE CASCADE, so removing a demo account's post removes every comment on it, including yours.
On live that is one: "how hot was the pan?" on alex@demo.test's post 6. Read that line before typing
`--apply`.

The script refuses outright if any named account owns a recipe, a snapshot, a rating, a queue entry,
a cook photo or a library row. On live today they own none of any.

## 5. Confirm the login

```sh
shasum -a 256 "$LIVE"            # it WILL have moved: the removal wrote. Record the new value.
```

Then log in at http://127.0.0.1:8000/ as andyhannah2014@gmail.com, with the real password. The
rehearsal proved the row survives byte for byte, hash included, and that a login as that id returns
200 with all 300 recipes, so this is a confirmation rather than a test.

Check, on the page: Browse lists 300 recipes, the feed shows your 3 posts, and your post's comment
thread holds only your own line.

## 6. Rollback

**The code, on its own, is safe to roll back at any time.** This round changed no schema and no
migration, so `478e33f` reads the current database exactly as the new code does. The one behaviour
that reverts with it is the owner scoping: the old `DELETE /api/test-recipes` matches every
account's test rows again, which on a one-account database is the same set.

```sh
pkill -f scripts/serve_live.py
cd "/Users/andrewhannah/Documents/Local Documents/Food/recipe-app-serve"
git checkout --detach 478e33f
npm run build                               # node_modules does not move with the checkout
cd "/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
```

About two minutes, almost all of it Vite starting up.

**The data rollback is a restore, because the removal is a delete and there is no undo.**

```sh
pkill -f scripts/serve_live.py
cp "backups/recipes-<stamp>.db" "$LIVE"     # the backup from step 0
shasum -a 256 "$LIVE"                       # must equal the value recorded in step 0
# then restart :8000 as above
```

⚠️ **RESTORE THE WHOLE FILE, DO NOT RE-INSERT THE ACCOUNTS.** Putting three users back by hand gives
them new ids, and 21 rows across six tables referenced the old ones. The backup is the only thing
that returns the database to the state it was in.

⚠️ **AND THE WINDOW MATTERS.** Anything written to live between step 0's backup and the restore is
lost by the restore. The removal takes seconds and nothing else should be running, so keep the two
close together and do not cook or rate anything in between.

## What is NOT in this plan, on purpose

- No migration, no `build_db.py`, no corpus pass. This round adds no column and no table.
- Nothing touching `join-narrow-1.db`. That delete is held pending a decision, because the artifact
  cannot be rebuilt from today's `sources.db` and a measurement in `build_library.py` cites it.
- No change to `GET /api/recipes` being unfiltered by owner. That is the shared library, by design.
