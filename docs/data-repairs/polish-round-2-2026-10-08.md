# Polish round 2, as it was RUN on live — 2026-10-08

Written after the run. This is a RECORD, not an input: nothing reads it. The inputs are the three
decision files below and `golive/rounds/2026-10-08-polish-round-2.json`, and the plan is
`golive/2026-10-08-polish-round-2.md`.

## What went in

| | |
|---|---|
| live before | `a05f2efc26a9e1e66446e61df093ffd86ee61b43c6b39b8cee1cdb0ef0548e50` |
| live after | `fd74bec9ff5fa1a9140f626161e3f4cca3b353541274a17f8e4dca42c3b6b791` |
| backup taken first | `backups/recipes-20261008-104118.db`, sha256 equal to live before |
| commit | `766f2e3`, four commits, CI green on `ci/polish-round-2` before main moved |
| commit `:8000` served before | `8fe756d` |
| writes | **189 over 84 recipes** |
| schema | **unchanged**, migration 63 on both sides |

## The three decision files

| file | rows | what it decided |
|---|---|---|
| `heading-levels-2026-10-08.csv` | 78 | every lifted heading whose level moved, with the rule's reason, whether the row was in the 66 Andy confirmed, and whether its recipe was in the preview |
| `ingredient-name-case-2026-10-08.csv` | 112 | every capitalized ingredient name the evidence-based rule could not settle |
| `polish-round-2-decisions-2026-10-08.csv` | 15 | the rows no rule could settle, the confirmations from the click-through, and the labels left unruled |

## The parts, as they ran

| part | writes | what moved |
|---|---|---|
| 1. heading levels | 78 | all level 2 to level 1, over 23 recipes, zero demotions |
| 2. ingredient names | 78 | 71 `fix:` texts applied literally, 4 lines converted to headings, 2 `Optional:` lines moved under one inserted heading |
| 3. the green-beans footnote | 2 | two sentences became note 183 linked to step 3650, step 3651 deleted |
| 4. footnote markers | 2 | steps 3650 and 3853 |
| 5. note type labels | 25 | 15 labels stripped, 10 lifted into `recipe_notes.title` |
| 6 and 7. lettering, number, capital | 4 | karak-chai's a/b/c, homemade-pasta-dough step 2536 |

## Both gates, on live

**THE ROUND DID EXACTLY WHAT IT DECLARED.** Short-circuit **280 to 280 and the same set**.
Annotations **49 entries over 20 recipes, identical**. Integrity ok, **0 foreign-key violations**.
Six counts moved and nothing else: `headings_l1` 151 to 229, `headings_l2` 112 to 34,
`ingredient_lines` 3572 to 3573, `recipe_notes` 176 to 177, `recipe_notes_recipes` 95 to 96,
`steps` 2486 to 2485.

**EVERY MOVED CELL WAS DECLARED** (`scripts/gates/cells.py`, new this round). Four tables are in
`tables.except` because the round writes to all four, and an excepted table is not compared by
`rounds.py` at all, so the hole got its own check:

```
  recipe_steps:       2486 rows x  6 columns = 14916 cells,  89 moved;  1 deleted, 0 inserted
  recipe_ingredients: 3572 rows x 18 columns = 64296 cells, 105 moved;  0 deleted, 1 inserted
  recipe_notes:        176 rows x  8 columns =  1408 cells,  35 moved;  0 deleted, 1 inserted
  recipe_snapshots:    306 rows x  7 columns =  2142 cells,  69 moved;  0 deleted, 0 inserted
```

82,762 cells compared, 298 moved, every one on a row and in a column the round named.

⚠️ **AND THE GATE WAS CHECKED FOR BLIND SPOTS BEFORE IT WAS TRUSTED.** All **69** recipes whose
baseline this round rewrote are covered by one half of the first gate or the other: **61** are in the
byte-equal set, where a baseline that did not move with its row drops the recipe out, and **8** are
out of that set but carry annotation entries, where the same failure changes an entry. None is
covered by neither. The two riskiest rows, the inserted ingredient heading and the deleted step, both
land on recipes that were in the 280.

## What the round carried in code

Seven rules, each in `import_cleanup.py` with the importer as a second caller, so a recipe imported
tomorrow is structured the way the corpus was just repaired to be:

- `names_a_stage` — a lifted label naming a stage or a duration is a section. french-fries is the
  case: its author wrote `Fry #1` as a section and the lifted `50 sec fry`, `30 min cool` and
  `Fry #2` sat under it as captions.
- `strip_author_letters` — a run of consecutive steps lettered from "a" is the author's sub-list.
- `strip_author_numbers_by_section` — the author's numbering may restart under each heading, which
  read over the whole recipe is not a sequence at all.
- `continues_the_line_above` — a step directly after a heading is never a continuation.
- `footnote_step_plan` and `strip_footnote_markers` — a step opening with an asterisk under a step
  carrying the matching one is that step's footnote, and the app has no footnotes.
- `optional_ingredient_groups` — consecutive lines opening `Optional:` go under one heading.
- `note_label_plan` — a label that restates its kind comes off, one that says more becomes a title.

## The three things worth remembering

⚠️ **PROVENANCE IS READ OFF THE ROWS, NOT OFF THE REVIEWED CSVs.** 263 headings were 136
pre-existing rows plus **127 the lift passes INSERTED**, and only 104 of the 127 are in
`step-leadin-labels` / `step-dash-labels`: the other 23 were lifted by RULE after that candidate list
was reviewed. Reading provenance from the CSVs made those 23 look author-written, which made them
PARENTS that demoted the lifted headings under them and meant they were never judged themselves. Six
of the 78 came from fixing that, and the count Andy first confirmed was 66. The id test is
cross-checked against the 104 reviewed lifts, because one ordinary step row added after the lifts
would silently undo it.

⚠️ **WHICH LABELS RESTATE A KIND IS A LIST, NOT A GRAMMAR RULE.** The first version compared the
label against the kind's name with a plural rule, which titled `Storing` on the grounds that it is
not spelled `Storage`. Andy's call on the click-through: `Storing` restates Storage and `Reminder`
does not restate Notes. Both are written into `static/note-kinds.json` under `restates_the_kind`,
beside the labels they are drawn from, so the client's display grouping and this rule read one
answer. Twelve labels in the table that no note in the 300 carries are FLAGGED and not decided;
`Keeping` is the one worth a second look, being the same shape as `Storing`.

⚠️ **THREE FRESH REVIEWERS FOUND SEVEN DEFECTS AND NONE OF THEM CHANGED A CELL OF THIS ROUND.**
Measured: the rehearsal before and after the fixes differed by 0 cells. Every one was a path the 300
recipes do not exercise and an IMPORT would, which is the half of FIX BY RULE that has no corpus to
catch it. The worst was the stage counter reading `Serves 4`, `Makes 24` and `Bake 350` as numbered
stages. The others: a shelf life read as a stage, `2 day-old` read as a wait, four alternative shapes
missing from `_ALTERNATIVE`, `McIntosh apples` half-lowered to `mcIntosh apples`, a note title left
lowercase, stale `import_flags` positions after an inserted heading, part 6 reading text part 4 had
already changed, and an abort message claiming nothing was written when every recipe before it was
already committed.

A first attempt at the review produced nothing: all three agents died on a harness watchdog with no
output. The second attempt, with one small brief each instead of one large one, produced all three
reports.

## What was NOT done, and why

- **The live API needs a session**, so the deploy-order check (all 300 pages against the still-old
  data) ran against a copy whose sha256 was byte-for-byte live's, served by the NEW commit from the
  pinned worktree. 300 of 300 built. Putting a throwaway password on live to run it there would have
  been a live write for the sake of a check.
- **`gh` is not installed on this machine** and no previous round used it, so the checks were read
  with the `curl` form every round has used. Both forms are in the plan.
- **No partial rollback of part 1 exists.** Running the pass again is a no-op, measured, and there is
  no reverse pass. 78 heading levels and one deleted step come back from
  `backups/recipes-20261008-104118.db` or not at all.

## The rollbacks, as written

**Code:** repin `../recipe-app-serve` to `8fe756d`, rebuild, restart. Measured 2026-10-08: `8fe756d`
built **300 of 300** recipe pages against a copy with this round APPLIED, so the code rolls back on
its own with the data left in place. `0458c88` was named in an earlier draft and was wrong: it is
where `origin/main` sat, three commits ahead of what `:8000` was running.

**Data:** a whole-file restore of `backups/recipes-20261008-104118.db`, never by re-inserting rows.
This round inserted two rows and deleted one, so a new row would get a new id and every baseline
entry naming an id would be wrong.
