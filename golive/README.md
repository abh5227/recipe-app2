# How a go-live runs

The template every round copies. One file per round beside this one, named
`<date>-<name>.md`, holding the round's own commands and its two rollbacks. The round's declared
changes go in `rounds/<date>-<name>.json`, which the gate holds the run to.

Nothing here is optional, and the order is the content.

## 0. Before anything

- `python3.13 backup.py`, then read the backup's sha256 and live's. **They must match.** The backup
  is the data rollback, and a backup nobody fingerprinted is a hope.
- Record live's sha256. If it has moved since the last explained value, find out what moved it
  before going further. The server's own request log names writes.
- `git fetch origin && git rev-parse origin/main` and confirm it is the SHA the round expects.

## 1. Prove it on a branch, not on main

⚠️ **CI GREEN ON A BRANCH BEFORE main CARRIES IT.** Push the round to `ci/<name>` first, wait for
that branch's checks, and fast-forward main only once they are green.

```sh
git push origin HEAD:refs/heads/ci/<name>
# watch the checks on that branch, read the steps, not just the conclusion
git push origin main          # main is a fast-forward to the commit CI already proved
git push origin --delete ci/<name>
```

*Why:* some of this suite runs in CI and nowhere else. The Postgres leg needs a server, and there is
no local one on macOS: Docker runs, but the sandbox strips published ports and Docker Desktop cannot
forward a mounted unix socket out of its VM. So CI is the only place the dialect suite, the schema
parity comparison and the harness marker's Postgres half execute at all. A round pushed straight to
main makes main the place that discovers a broken test, which happened on 2026-10-05: a test that
dropped the harness marker and left the database in the state the marker exists to refuse took the
step red, and four later tests failed in fixture setup for a reason unrelated to what they check.

⚠️ **THE BRANCH HAS TO CARRY THE TRIGGER.** A `push` event reads the workflow file from the ref being
pushed, so `ci/**` must be in `.github/workflows/*.yml`'s push branches on the branch itself. It is,
in both workflows. A side-branch push before that ran nothing at all and looked like a pass.

## 2. Read the checks, step by step

```sh
curl -s "https://api.github.com/repos/abh5227/recipe-app2/actions/runs?per_page=8&branch=<branch>" \
  | python3.13 -c "import json,sys; [print(f\"{r['name']}: {r['status']}/{r['conclusion']} {r['head_sha'][:7]}\") for r in json.load(sys.stdin)['workflow_runs']]"

curl -s "https://api.github.com/repos/abh5227/recipe-app2/actions/runs/<id>/jobs" \
  | python3.13 -c "import json,sys; [print(' ', s['conclusion'], s['name']) for j in json.load(sys.stdin)['jobs'] for s in j['steps']]"
```

⚠️ **"Run Postgres integration tests" must read `success`, not `skipped`.** The module skips on one
module-level mark, so an all-skipped run exits 0 and a silent skip is indistinguishable from a pass
in the job's green tick. The step carries its own ran-nothing guard for that reason, and the guard
only helps if somebody reads the step.

Red means stop. Do not repin, do not apply.

⚠️ **The job log needs a token this machine does not have** (the API answers 403), so a failure has
to be diagnosed from the code. That is the second reason to run on a branch: a red branch costs
nothing, and a red main is a bisect.

## 3. Repin the serve worktree and restart :8000

⚠️ **`scripts/serve_live.py` RUNS FROM THE PINNED WORKTREE, NOT THE WORKING TREE.** Its own guard
refuses the working tree and says why.

```sh
NEW=$(git rev-parse HEAD)
pkill -f scripts/serve_live.py
cd ../recipe-app-serve && git fetch origin && git checkout --detach "$NEW"
npm install && npm run build          # the pinned worktree builds its OWN dist/
nohup python3.13 scripts/serve_live.py > /tmp/serve8000.log 2>&1 & disown
```

Prove it by the process's directory, never by the bundle name: two worktrees at one commit build
byte-identical bundles, so a matching filename proves nothing.

```sh
lsof -a -p "$(pgrep -f scripts/serve_live.py | head -1)" -d cwd -Fn    # must name recipe-app-serve
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/
shasum -a 256 "$LIVE"                                                  # unchanged by a restart
```

## 4. The data step, if the round has one

```sh
cp "$LIVE" "$SP/before.db"                         # copy, never symlink
python3.13 scripts/gates/state.py --db "$SP/before.db" --out "$SP/before.json"
python3.13 scripts/<pass>.py --db "$LIVE" --i-mean-live              # the dry run, ALWAYS first
python3.13 scripts/<pass>.py --db "$LIVE" --apply --i-mean-live
cp "$LIVE" "$SP/after.db"
python3.13 scripts/gates/state.py --db "$SP/after.db" --out "$SP/after.json"
python3.13 scripts/gates/rounds.py --round golive/rounds/<round>.json \
  --before "$SP/before.json" --after "$SP/after.json" \
  --a-db "$SP/before.db" --b-db "$SP/after.db"
```

Read the dry run's collateral line against the round file before typing `--apply`. The gate must
print **THE ROUND DID EXACTLY WHAT IT DECLARED** and exit 0. If the dry run does not match the
declared shape exactly, do not apply.

## 5. Confirm, and record

- The login works and the recipes are all there.
- Live's new sha256, recorded.
- The commit serving :8000.
- A record in `docs/data-repairs/` describing what happened. ⚠️ **A record is written in the past
  tense only after the run.** A record committed ahead of the apply makes the repo assert a change
  to live that may never happen, which a review caught on 2026-10-05.

## 6. Rollbacks, both of them

**The code** rolls back on its own whenever the round changed no schema: check the serve worktree out
at the previous SHA, rebuild, restart.

**The data** rolls back by restoring the whole file from step 0's backup, never by re-inserting rows
by hand. New rows get new ids and everything that referenced the old ones is wrong. Anything written
to live between the backup and the restore is lost by the restore, so keep the two close together.
