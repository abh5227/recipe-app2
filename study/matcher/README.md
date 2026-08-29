# The linkage matcher

**A MEASUREMENT tool. It has no write path.** Not one file here contains `UPDATE
recipe_ingredients` or `SET ingredient_id`, and every one of the 50 opens of `recipes.db`
across the original 328-file scratch tree used `mode=ro`. Running anything in this directory
computes what a linkage pass **would** produce and reports it. Nothing here changes a recipe.

## What it is for

`recipe_ingredients` has 2,997 non-heading lines carrying a label, across 298 recipes. **50 of
them carry a stored `ingredient_id`**, and all 50 sit in 6 recipes and were written by hand in
`seed.py`. The matcher's question is what the other 2,947 should point at.

## Where it came from, and why it is here

It was 328 untracked files in a session scratch directory, 247 MB, one `rm -rf` from gone. This
directory is the irreplaceable part: 12 files that ARE the matcher, and 11 files of hand
judgment. The 244 MB of `.pkl` checkpoints and the generated CSV, HTML and XLSX reports are
regenerable and are gitignored.

## The banked configuration: seg0-core

Segment the line on `, ; ( ) /` and on "or". Take every consecutive word run inside each
segment. Normalize with `build_join.norm_name`, the same function the index is built with. Rank
by **segment first, then longest, then leftmost**, so a match in an earlier segment beats any
match in a later one. That is what stops a parenthetical gloss winning over the named
ingredient.

**No language rule. No clause strip.** Both were measured and both were declined. Five ranking
variants and two clause-strip configurations were measured against the same hand-judged sets.

## What it measured

At HEAD `bc38181`, over 3,332 non-heading lines:

| | lines | share |
| --- | --- | --- |
| MATCHED | 2,771 | 83.2% |
| AMBIG | 523 | 15.7% |
| MISS | 38 | 1.1% |
| reach at least one row | 3,294 | 98.9% |

⚠️ **The confidence bands are computed, not verified.** 3,016 lines (90.5%) are banded HIGH,
which means the algorithm is confident, not that anyone checked. **3,038 lines (91.2%) have
never been individually read**, and 2,410 of those are the AGREE block, where two matchers
landed on the same row and neither was checked. Writing 2,771 links on this basis would put
unverified data into the recipes. **Reading is the remaining work, not matching.**

⚠️ **Two denominators are in circulation.** `LINK.py` runs over the 2,997 lines that carry a
label. The coverage table above is over all 3,332 non-heading lines. 335 lines carry `raw_text`
and no `label`. The two rates are not over the same set.

## The files

### The matcher (12)

| file | what it is |
| --- | --- |
| `lib.py` | rebuilds the library rowset from `join.db` + `sources.db`, kept in step with `build_library.build()`. Every other script starts here |
| `LINK.py` | the ladder resolver. Six reductions, cheapest first, reporting which rule won so an unproductive rule can be dropped |
| `SEG3.py` | the seg0-core segmenter described above |
| `GUARD.py` | the index-key guard, and the three-config measurement |
| `GAPS.py` | coverage pass. Writes `previews/ingredient-gaps.csv` |
| `FEED.py` | does feeding the importer's parsed name help |
| `REGEN.py` | re-runs the full match at a new HEAD |
| `AGREE.py` | the AGREE block, and a seeded uniform 60-line sample (`SEED = 20260827`) |
| `SEG2.py` | re-derives the hand verdicts at a new HEAD, then the four-variant table |
| `cov.py` | writes `previews/current-coverage.csv` |
| `WRITECSV.py` | writes `previews/full-ingredient-match.csv` |
| `verify.py` | verification pass |

### The hand-judged sets (11) — the half that cannot be regenerated

A human read every line of these. Rerunning the matcher reproduces its own output. It does not
reproduce a judgment.

| file | what a human did |
| --- | --- |
| `AJUDGE.py` | 746 lines. Hand verdicts on every row the P279 rule would newly admit, with the method stated so a reader can discount it |
| `VERDN.py` | NEW-ONLY verdicts keyed (phrase, row names), each with a written reason |
| `MVJ.py` | the 174 moved rows, judged one pattern at a time |
| `VERD.py` | DIFFERENT and OLD-ONLY verdicts, carrying a confidence field where LOW means the call could go the other way |
| `RDJ.py` | verdicts on 98 redirect names (cross-concept, legit-alias, borderline) |
| `AJ60.py` | the 60 AGREE-block verdicts, keyed by sample index |
| `NONEREASON.py` | the reason for each MISS. Every REAL-GAP was proven by probing the 183,651-key index |
| `HEADDEF.py` | the head-noun definition and its stress cases |
| `STOP2.py` | the curated stoplist, and why it filters leftover words only |
| `STRIP.py` | the trailing-clause stripper's closed verb lists, stated rather than open-ended so the rule cannot drift |
| `STOPDEF.py` | the earlier stoplist |

⚠️ **`AJ60.py` is keyed by SAMPLE INDEX, so it needs its anchor.** `AGREE.py` seeds the sampler,
which makes the draw reproducible over the same AGREE block. **The block moves**, because the
library rowset changes between HEADs (10,527 rows at one, 10,387 at another). Re-running today
draws a different 60 and the index-keyed verdicts silently misalign. `previews/agree-sample.csv`
pins the 60 lines that were actually read and is committed for that reason, as the one exception
to `previews/` being gitignored.

## Running it

```bash
cd study/matcher
python3.13 LINK.py            # about 10 seconds, recipes.db opened read-only
```

⚠️ **The scripts hardcode an absolute path** to the repo and `os.chdir()` to it. They work on the
machine they were written on and nowhere else. **This is committed verbatim on purpose.** The
tool ran and produced measured results, and rewriting paths during a rescue is how a rescue
breaks. Fix it deliberately later, against a rerun that reproduces the numbers above.

## What it needs

Both are gitignored and neither is ever committed.

| | size | |
| --- | --- | --- |
| `join.db` | 894 MB | name buckets, rebuildable from `sources.db` by `build_join.py` in about 40 seconds |
| `sources.db` | 5.18 GB | entry names and English glosses, read-only |

From the repo itself, all tracked: `build_join.py`, `build_library.py`, `weights.py`,
`import_cleanup.py`, `ingredient_cuts.py`.

## What is not here

There is no write path, no committed home for the output, and no review UI for the 3,038 unread
lines. See `docs/ingredient-linkage-state.md` for the surrounding state and
`docs/panel-design.md` for how this relates to the ingredient corpus work.
