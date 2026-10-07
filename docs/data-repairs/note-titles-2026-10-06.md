# The note titles, applied to live

A record, written after the run. Nothing reads it. The decisions it describes are in
`note-titles-2026-10-05.csv` and `emphasis-marks-2026-10-05.csv`, which are committed because
`scripts/apply_note_titles.py` opens them. The plan it followed is
`golive/2026-10-06-note-titles.md` and the declaration the gate held it to is
`golive/rounds/2026-10-06-note-titles.json`.

Run 2026-10-06. Migration 062 added `recipe_notes.title`, and the pass wrote the 33 changes Andy
decided over 21 recipes. 28 notes over 18 recipes carry a title now. 148 of the 176 note rows do
not, which is the resting state.

## What ran, in order

| step | result |
|---|---|
| live's fingerprint before anything | `414595961800c7e0bb2634bd4861daa0f133e11307000ec868c8110a6d236387`, the value the previous round recorded |
| `backup.py` | `backups/recipes-20261006-201213.db`, sha256 equal to live's |
| CI on `ci/note-titles` at `7d703b7` | Cold start green, SonarQube green, **"Run Postgres integration tests" read `success`** |
| `main` fast-forwarded | `f7c41c8` to `7d703b7`, the exact commit CI proved. The branch was deleted. |
| `migrate.py --db <live> --i-mean-live` | `062_recipe_note_title.sql` applied. 62 migrations recorded, `title` on the table, 0 titles set. |
| `:8000` on the OLD commit, against the migrated schema | 200. The additive-before-the-deploy order held in practice, which is what section 7b measured on a copy. |
| `apply_note_titles.py <live> --i-mean-live` (the dry run) | 57 decisions read, **33 to write**, 3 no-op, 21 not this round's business, 1 flagged, **0 refused** |
| the same with `--apply` | **33 changes over 21 recipes**, "no recipe's annotation set moved and none left the byte-equal set" |
| `gates/rounds.py` | **THE ROUND DID EXACTLY WHAT IT DECLARED**, exit 0 |
| a second dry run | 0 to write, 36 already in place. The pass is a clean no-op, so an interrupted one is resumable. |
| live's fingerprint after | `02ff8d6b579d2252c4e2a031a4e632110ed0dc32bcc5487b58810fc692d77664` |
| `../recipe-app-serve` repinned, rebuilt, `:8000` restarted | serving `7d703b7` from that worktree, proved by the process's own directory |

## What the gate measured

| | before | after |
|---|---|---|
| short-circuit set | 280 of 300 | 280, **the same set**, not merely the same count |
| annotation entries | 49 over 20 recipes | 49 over 20, **entry for entry identical** |
| `recipe_notes` | 177 | 176 |
| migrations | 61 | 62 |
| titled notes | 0 | **28 over 18 recipes**, 0 of them blank |
| `recipe_notes_original` | 177 | 177, byte-identical |
| `recipes.notes` | | byte-identical |
| `recipe_note_step_refs` | | byte-identical |
| baselines moved | | **1 of 306**, brioche-cinnamon-rolls' `reason='original'` |
| integrity, foreign keys | | ok, 0 violations |

⚠️ **THE ONE BASELINE THAT MOVED IS THE DECLARED EXCEPTION, AND IT IS WHY THE OTHER 305 DID NOT.**
A note is a playground, so 31 of the 33 writes are outside `recipe_snapshots.content` entirely and
cost no recipe its byte-equal short-circuit. The two ingredient headings on brioche-cinnamon-rolls
(rows 9213 and 9217, both losing a wrapping `_`) ARE baseline content, so the row and the baseline
were patched in one transaction. That recipe is still in the 280.

⚠️ **`recipe_notes_original` STILL HOLDS 177 ROWS AGAINST 176 NOTES, AND THAT IS CORRECT.** The
originals are a LIST of the author's paragraphs, not a join against the note rows, so the merge's
deleted row keeps its original. Renumbering it would delete the only copy of words nothing else
holds.

## The 33 changes

27 notes took a title with that title removed from the front of their text. Notes 13 and 70 moved to
kind `storage`. Note 19's wrapping marks came off under its label decision. Note 64's title moved
onto note 65 and row 64 was deleted, which is the only row this round removed. The wrapping emphasis
marks came off note 89 and off ingredient headings 9213 and 9217.

Three decisions were already in place and wrote nothing: notes 69, 113 and 173, each a `no title`
that already had none. One case is flagged for a later round, step 3651's split footnote.

## Rollback, if it is ever wanted

**The code** rolls back on its own. Check `../recipe-app-serve` out at `f7c41c8`, rebuild, restart.
The column stays and costs nothing, because that commit never names it. Measured before the run, on
a copy carrying both the migration and the pass: 13 recipe pages rendered with 0 JavaScript errors,
Edit mode's Save kept every title, and rewording a titled note through the old editor kept its title
too, because `f7c41c8`'s `write_notes` names six columns and `title` is not one of them.

**The data** rolls back by restoring `backups/recipes-20261006-201213.db` over live, whole file.
There is no row-level undo and deliberately no down-migration: SQLite cannot drop a column without
rebuilding the table, and `recipe_note_step_refs` names row ids a rebuild would mint again. Anything
written to live after the backup is lost by the restore.
