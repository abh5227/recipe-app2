# The corpus passes, and the order they run in

Four scripts carry the Round A repairs over all 300 recipes. They are not interchangeable and they
are not independent. Each one reads the state the one before it left, so running them out of order
produces a different corpus, and running one twice is not always a no-op.

Every one of them takes the database as an argument and refuses live `recipes.db` without
`--i-mean-live`. All four patch the `reason='original'` baseline in the same transaction as the
live row, so a repair creates no "your changes" mark.

## The order

    migrate.py                                  056 to 059, additive, before anything reads them
    scripts/apply_plan_ahead_proposals.py       the v3 waits and storage rows
    scripts/add_missed_waits.py                 the waits a step stated and the import missed,
                                                the ext and alongside step links, and the one
                                                total_includes_waits ruling
    scripts/convert_step_headings.py            steps become headings, lead-in labels are lifted,
                                                Note and Tip steps move to the recipe's notes
    scripts/apply_label_rules.py                the rules Andy's click-through produced, over the
                                                headings the pass above created

`apply_plan_ahead_proposals` applies by default and takes `--dry`. The other three dry-run by
default and take `--apply`.

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
