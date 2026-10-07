# The safety round, the time block, and the drop of `recipes.notes`, applied to live

A record, written after the run. Nothing reads it. The plan it followed is
`golive/2026-10-07-drop-notes-column.md` and the declaration the gate held it to is
`golive/rounds/2026-10-07-safety-and-time-block.json`. The one ruling it wrote is in
`scripts/add_missed_waits.py`'s `TOTAL_RULINGS`, which is committed because it IS the decision.

Run 2026-10-07. Two rounds in one deploy, plus three later changes from Andy's click-through and
one deletion. **The code went first and the migration second**, which is the opposite of the titles
round's order, because 063 is destructive and the new code is the version that can serve both
schemas. That claim was verified against both schemas rather than reasoned about. See below.

## What ran, in order

| step | result |
|---|---|
| live's fingerprint before anything | `02ff8d6b579d2252c4e2a031a4e632110ed0dc32bcc5487b58810fc692d77664`, the value the previous round recorded, migration 62, 300 recipes |
| `$DATABASE_URL` | empty, checked before anything ran, because it would make every path in the plan a lie |
| `backup.py` | `backups/recipes-20261007-165403.db`, sha256 equal to live's |
| the orphan photo, copied | `backups/orphan-20261007-165412-baked-cauliflower-…-copy-copy.jpg`, 119,394 bytes, sha256 equal to the original. `backup.py` does not touch `static/images/`, so this was its own step. |
| CI on `ci/safety-and-time-block` | **RED on the first push**, then green. See the defect below. |
| `main` fast-forwarded | `848094f` to `8fe756d`, the exact commit CI proved. The branch was deleted. |
| `../recipe-app-serve` repinned, rebuilt, restarted | `8fe756d`, cwd confirmed as `recipe-app-serve`, bundle `index-ByxU0zL_.js` |
| the new code against the OLD schema | 300 of 300 recipe pages 200, three saves 200 moving nothing. Measured on a copy, not reasoned. |
| `migrate.py --db <live> --i-mean-live` | `063_drop_recipes_notes.sql`, **0.044 s** |
| `add_missed_waits.py <live> --apply --i-mean-live` | 0 waits added, 13 already stored, 2 ext links rewritten to the values they held, `total_includes_waits=1` on all-butter-pie-crust |
| the round gate | **THE ROUND DID EXACTLY WHAT IT DECLARED** |
| the cell check the gate cannot make | 300 recipes x 17 shared columns = **5,100 cells compared, 1 moved**, `notes` the only column dropped |
| `PRAGMA integrity_check` / `foreign_key_check` | `ok` / **0 violations** |
| the orphan photo's three conditions | **ALL THREE HOLD**, exit 0, then deleted. `README.txt` is now the only unreferenced file in the library. |
| the new code against the NEW schema | 300 of 300 pages 200, 176 note rows served, three saves 200 moving nothing |
| live's fingerprint after | `a05f2efc26a9e1e66446e61df093ffd86ee61b43c6b39b8cee1cdb0ef0548e50`, migration 63, 300 recipes |

## The two sets, before and after

| | before | after |
|---|---|---|
| byte-equal short-circuit | 280 of 300 | 280, **the same set**, none joined and none left |
| annotation entries | 49 over 20 recipes | 49 over 20, **identical** |
| note rows / originals | 176 / 177 | 176 / 177 |

No row changed except one cell, so both sets held still. That was the declaration and it is what
happened.

## What the one cell was

`recipes.total_includes_waits = 1` on **all-butter-pie-crust**. The new totals rule flagged it and
could not settle it: the recipe states 1 hr 15 min with a 1 hr chill that always applies and **no
cook time**, so there is no prep + cook + waits upper bound to compare against. The crust alone is
never baked, which is why `cook_time` is empty. Andy read the recipe and answered it: 15 min
hands-on plus the 1 hr chill IS the stated 1 hr 15 min, so the author counted the wait.

⚠️ **IT CHANGED NO FIGURE ON THE PAGE, AND THAT WAS THE POINT.** `recipe_total` shows a stated total
unchanged either way, so the recipe read "1 hr 15 min" before and after, on this code and on
`7d703b7` (both measured). What the ruling bought is that the question ENDED, so the recipe left
`reports/total-vs-waits.csv` instead of being asked again on every survey. The survey now reports
`unclear: 0` and writes no list at all.

It is the second ruling ever recorded on that column, after miso-tofu-recipe's 0.

## The one visible change

**earl-grey-tea-cake** reads **"Total 2 hr 30 min+ (incl. plan ahead)"** with **"Author's total:
1 hr, before the waits"** under it. It is the one recipe of the 300 whose Total this round changed,
and nothing was written to do it: the figure is computed at display like every other total.

## The defect CI caught, and the one only a clone could catch

⚠️ **THE FIRST PUSH WENT RED, AND THE `ci/**` BRANCH IS WHY THAT WAS CHEAP.** The SQLite leg passed
and the Postgres step failed:

    tests/test_pg_integration.py:425: KeyError: 'notes'

Alembic's `a7c4e81b9d35` drops `recipes.notes` to mirror 063, so the column was gone at head and
the end-to-end import test was still reading it. **That leg runs in CI and nowhere else**, which is
why 3,094 local tests said green. The dead assertion was also the ONLY thing covering notes on that
leg, so the fix asserted the ROWS (`recipe_notes` and `recipe_notes_original`) rather than deleting
the line. Verified on a real Postgres 16 before re-pushing: 64 passed, 1 skipped.

This was the **third instance of one shape** in this round. The plan had already named the other two.
All three were "the notes column is retired" reaching somewhere nobody re-read.

⚠️ **AND ONE TEST WOULD HAVE GONE RED IN CI FOR A REASON NO LOCAL RUN COULD SHOW.**
`test_lockstep_guard` declares the words each pass must print when it declines.
`restore_from_paprika.py` reads a 235 MB archive that is not in the repo, so it declines for one
reason on the owner's laptop and a different one in CI. Found by running the suite in a throwaway
**clone**. A linked worktree is not that environment: `live_db()` finds the main working tree
through `git rev-parse --git-common-dir`, so from a worktree the real database is still live and six
guard tests fail for that alone.

## What was also fixed on the way

- **The stated-total rule read the FLOOR of the author's figure where its own claim needs the
  CEILING.** The open-end guard in `recipe_total` was dead code: `normalize_time` rewrites a trailing
  `+` into ` (+)`, so `rstrip("+")` was a no-op and the branch never ran once. Three shapes were
  being declared arithmetically impossible when they are not, the worst being
  `"35 min (plus 1 hr soaking)"`, which would have printed "Author's total: 35 min, before the
  waits" against an author who had just written that the soaking is on top. All three are the middle
  case now. **Measured over live's 300, every total the page prints, old code against new: 0
  differing.** All 14 stated totals are a single closed figure.
- **A test run was rewriting `reports/`.** Six files replaced with fixture output on every plain
  `pytest`, under the real names. `total-vs-waits.csv` named two recipes called `nocook` and
  `unclear`, which are fixture ids, where live's survey had put a real recipe id. A test two lines
  above the call set `$RECIPE_APP_REPORTS` to redirect it and nothing read that variable.
  `report_target` reads it now and conftest sets it for every test.
- **Two JS checks that could not fail.** The combination test's anti-vacuity floor tolerated three of
  eight marks going dead, and its order check rejected two consecutive conditional totals, which is a
  correct page the project has a fixture for.

## Rollback, not needed

Kept for the record. Before 063 a repin was the whole rollback. After it, the column comes back
**empty** in 0.003 s and the old code answers 200 again, measured; a whole-file restore from
`backups/recipes-20261007-165403.db` is the heavier second option. The ruling needs no rollback in
either direction: `7d703b7` reads that column the same way and shows the same figure, measured. The
photo comes back from `backups/orphan-*`.
