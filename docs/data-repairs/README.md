# The corpus passes, and the order they run in

Four scripts carry the Round A repairs over all 300 recipes. They are not interchangeable and they
are not independent. Each one reads the state the one before it left, so running them out of order
produces a different corpus, and running one twice is not always a no-op.

Every one of them takes the database as an argument and refuses live `recipes.db` without
`--i-mean-live`. All four patch the `reason='original'` baseline in the same transaction as the
live row, so a repair creates no "your changes" mark.

## The order

    migrate.py --db <path>                      056 to 059, additive, before anything reads them
    scripts/apply_plan_ahead_proposals.py       the v3 waits and storage rows
    scripts/add_missed_waits.py                 the waits a step stated and the import missed,
                                                the ext and alongside step links, and the one
                                                total_includes_waits ruling
    scripts/convert_step_headings.py            steps become headings, lead-in labels are lifted,
                                                Note and Tip steps move to the recipe's notes
    scripts/apply_label_rules.py                the rules Andy's click-through produced, over the
                                                headings the pass above created

`apply_plan_ahead_proposals` takes `--apply` like the other three. (`--dry` is still accepted and
ignored, because it was the flag during the round and a stale command line should not become a write.)
All four dry-run by default.

⚠️ **`migrate.py` TAKES `--db` NOW, WHICH IS WHAT MAKES THE SENTENCE ABOVE TRUE.** It hardcoded live
`recipes.db`, so step one of the chain could not be pointed at a copy and the rehearsal instruction
below could not be followed as written. The rehearsals were done by rebinding `migrate.DB` from a
throwaway Python snippet, which works and is not something a person should have to invent. The whole
chain against one database is now five ordinary command lines:

    python3.13 migrate.py --db "$DB"
    python3.13 scripts/apply_plan_ahead_proposals.py "$DB" --apply
    python3.13 scripts/add_missed_waits.py "$DB" --apply
    python3.13 scripts/convert_step_headings.py "$DB" --apply
    python3.13 scripts/apply_label_rules.py "$DB" --apply

### The notes round, which runs after all of the above

    python3.13 migrate.py --db "$DB"                              060, the recipe_notes tables
    python3.13 scripts/realign_baseline.py "$DB" --apply          first: it moves 5 recipes back
                                                                  into the byte-equal set, so the
                                                                  passes below start from 280
    python3.13 scripts/notes_to_rows.py "$DB" --apply             177 paragraphs become rows
    python3.13 scripts/apply_note_decisions.py "$DB" --apply      the links, the step references
                                                                  and the waits Andy recorded
    python3.13 scripts/strip_author_step_numbers.py "$DB" --apply the author's own numbering, and
                                                                  the labels it was hiding

⚠️ **`strip_author_step_numbers` RUNS AFTER `apply_note_decisions`, AND THE ORDER IS NOT A
PREFERENCE.** A step reference stores a step ID, so renumbering cannot move it. But RESOLVING one
reads the author's numbering out of the step text to find its target, and the number pass is what
deletes that evidence. Run the other way round, aloo-potato-parathas' "step 2" would have nothing
left to match against.

⚠️ **`realign_baseline` RUNS FIRST**, because every pass after it gates on the byte-equal set and a
set that is about to gain five recipes for an unrelated reason makes that gate unreadable.

## What may be written here, and by what

⚠️ **A DRY RUN NEVER WRITES INTO THIS FOLDER.** Five scripts used to write their report CSV here on
every run, dry or not. Their work is applied, so a re-run finds 0 rows — and three of the records in
this folder were truncated to their header lines at once, from dry runs, during the pre-push review.
Restoring them from git was the only reason nothing was lost.

    (default)     reports/<name>.csv          gitignored scratch, overwritten freely
    --record      docs/data-repairs/<name>.csv  and REFUSED if that file is already non-empty

A record is replaced by deleting it on purpose, which is a thing a person does and a script does not.
The decision files the passes READ are inputs: they stay committed and nothing writes to them. See
`scripts/corpus_guard.py::report_target` and `tests/test_live_guards.py`.

## Why the order is what it is

The waits come first because `convert_step_headings` renumbers step positions, and a wait points at
a step by row id rather than by position. Lifting a label inserts a heading row above its step, and
the step keeps its id, so a wait written first still points at the right step afterwards.

`apply_label_rules` comes last because it reads headings. Rule 7 promotes a lifted label to a
section, rule 8 demotes sibling alternatives under one, and neither has anything to read until
`convert_step_headings` has made the headings.

## What the first clean run from live caught

Running the chain end to end against a fresh copy of live, rather than against a database that had
been repaired in pieces, produced a heading reading `Wilt the [[spinach]]` on bulgogi-bowls. The
importer applied `move_link_out_of_label` when it lifted a label and `convert_step_headings._lift`
did not, and the repair meant to catch that looked for a label still sitting inside a step, which
the pass before it had already lifted.

The lift applies the rule now, in both callers, and `apply_label_rules` ends with a sweep over every
heading that contains link markup. `tests/test_corpus_passes.py` runs both scripts, which nothing
did before.

**Run the whole chain against a copy and diff the result before running it against live.** A pass
applied on its own, to a corpus already part way through, agrees with the chain by luck.

# The index: what each file is, and whether it is committed

Two kinds of file live here and the difference is whether code opens it.

**A recorded decision is an input to a pass, and it is committed.** A pass that cannot be re-run
from a fresh clone is a hand edit with more steps. Five of these were untracked until 2026-10-01 and
one sat in gitignored `previews/`, so the 94 waits and 30 storage rows written over 90 recipes
existed on one machine and in no commit.

**A review artifact is the output of a one-time survey that nothing opens, and it may stay
untracked.** It is the evidence behind a decision rather than the decision.

The test is mechanical. **If code opens the file, it is a decision and it is committed.** A doc that
merely CITES a survey as the evidence behind a roadmap item is not code opening it, but a citation a
clone cannot follow is a dangling reference, so a cited survey is committed too. Four of the six
surveys below are cited nowhere and stay untracked, which is what the category is for.

| file | rows | what it is | read by | committed |
|---|---|---|---|---|
| `plan-ahead-proposals-v3-2026-09-27.csv` | 138 | every wait and storage row the v3 pass writes | `apply_plan_ahead_proposals.py` | yes |
| `step-headings-candidates-2026-09-30.csv` | 37 | steps Andy approved for conversion to a heading in place | `convert_step_headings.py` | yes |
| `step-leadin-labels-2026-09-30.csv` | 56 | colon lead-in labels approved for lifting | `convert_step_headings.py`, `apply_label_rules.py` | yes |
| `step-dash-labels-2026-09-30.csv` | 60 | dash lead-in labels approved for lifting | both, same code path | yes |
| `round-a-fix-decisions-2026-10-01.csv` | 4 | the cases a rule could not decide, one row each | `apply_label_rules.py` | yes |
| `waits-missed-multi-duration-2026-09-30.csv` | 265 | the survey the missed-waits table was read off | named in `add_missed_waits.py`, whose table is written out in the file | yes |
| `baseline-row-ids-2026-09-29.csv` | 178 | the baselines that gained step row ids | `backfill_baseline_row_ids.py` | yes |
| `import-flags-archived-2026-09-30.csv` | 562 | the import review queue as archived | `archive_import_flags.py` | yes |
| `note-separators-2026-09-27.csv` | 16 | how each recipe's notes were joined | `restore_notes.py` | yes |
| `note-links-2026-10-01.json` | 10 | the note-to-step links, the step references and the waits Andy decided in the notes round | `apply_note_decisions.py` | yes |
| `paprika-restore-live-rows.csv` | 300 | the Paprika restore, live rows | `restore_from_paprika.py` | yes |
| `paprika-restore-snapshot-rows.csv` | 261 | the Paprika restore, baseline rows | `restore_from_paprika.py` | yes |
| `relink-2026-09-25.csv` | 182 | the ingredient relink pass | `relink_pass.py` | yes |
| `reparse-2026-09-25.csv` | 325 | the line reparse survey | nothing now | yes, historical |
| `brioche-null-header-2026-09-29.csv` | 3 | the one null header case | nothing | yes, historical |
| `cook-time-estimate-2026-09-30.csv` | 197 | survey: recipes whose cook time is an estimate | nothing; cited by ROADMAP Round B | yes |
| `ingredient-parentheticals-2026-09-30.csv` | 332 | survey: parentheticals in ingredient names | nothing; cited by ROADMAP Round B | yes |
| `overnight-waits-2026-09-30.csv` | 25 | survey: waits that run overnight | nothing | no |
| `total-time-unclear-2026-09-30.csv` | 10 | survey: recipes whose total does not add up | nothing | no |
| `extension-step-links-2026-09-30.csv` | 7 | survey: waits whose alternative points at another step | nothing | no |
| `step-heading-level-1-candidates-2026-09-30.csv` | 15 | survey: lifted labels with 2+ steps and no section above | nothing | no |

⚠️ **A survey becomes a decision the moment a pass reads it.** Commit it in the same change that
makes the pass read it, or the next clone cannot run the pass.
