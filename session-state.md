# Session state

Where the two databases stand, what is committed, and what is waiting.
Written 2026-09-17, rewritten 2026-09-21 after the promotion.

## The two databases

**`recipes.db`, live, `07603032`. Promoted 2026-09-20 from the copy.**

**`recipes-preview.db`, the copy, `73b7cee1`. Gitignored, and the source the promotion read.**

⚠️ **They are now identical on 48 of their 52 tables**, hashed on full row content rather than
compared on counts. The four differences are user data and the counters it moved.

| | live | copy |
|---|---|---|
| `library_names` | 10,020 | 10,020 |
| `library_relations` | 15,907 | 15,907 |
| `kind_of` / `in_category` | 8,708 / 5,589 | 8,708 / 5,589 |
| `made_from` / `part_of` | 1,538 / 72 | 1,538 / 72 |
| `library_aliases` | 246 | 246 |
| `mined_dish` | 161,967 rows, 159,609 dish types | 161,967 |
| `mined_dish_*` profile cells | 1,527,864 | 1,527,864 |
| `mined_occurrences` | 4,744 | 4,744 |
| `mined_pairings` | 446,801 | 446,801 |
| `mined_corpus` | 3 sources, N 2,240,854 | 3 sources, N 2,240,854 |
| `mined_substitution_candidates` | 4,964 | 4,964 |
| `recipes` / `recipe_ingredients` | 299 / 3,563 | 299 / 3,563 |
| `ingredients` | **0**, retired by migration 046 | 0 |
| `cook_log` / `ratings` | **135** / 118 | 134 / 118 |

### The four tables that differ

```
cook_log            live 135   copy 134    live's own extra cook
recipe_snapshots    live 303   copy 302    the snapshot of that edit
schema_migrations   47 / 47                same rows, different applied_at
sqlite_sequence     15 / 15                counters moved by the two rows above
```

**Live is ahead only on the user data it was always ahead on.** Everything derived came across row
for row.

### The three mined sources

```
recipenlg-2020    2,231,142 recipes    3,065 occurrence rows
india                 5,938 recipes      521 occurrence rows    derive_only
wikibooks             3,774 recipes    1,158 occurrence rows
```

Stage 5 mined all three together, so the lifts stored on live are combined lifts rather than
RecipeNLG's alone. `mined_combine` is the only correct way to read these tables, since the
per-source rows must be summed rather than averaged.

## Reproducibility

The catalog rebuilds from the committed hand files exactly. Measured after the whole arc, not
argued:

```
library_names.csv now   f7acd87b   10,024 lines
control rebuild         f7acd87b   10,024 lines   BYTE-IDENTICAL
and it matches live's catalog: 10,020 rows, identical
```

The databases are gitignored. **What is committed is the code and the hand files that reproduce
them.**

## Hand files

| File | Decisions |
|---|---|
| `hand_removals.csv` | 723, of which 496 drops, 166 variation trims, 61 folds |
| `hand_links.csv` | 16,166 |
| `hand_aliases.csv` | 246, now carrying a nullable `source_slug` |
| `hand_renames.csv` | 57 |
| `authored_rows.csv` | 80 |
| `hand_repoints.csv` | 61 link decisions the matcher cannot reach |

⚠️ **Three hand files were silently converted to different line endings during this work, and it
was caught before the push.** `hand_links.csv` and `hand_removals.csv` were rewritten from CRLF to
LF by scripts that joined lines with `"\n"`. `authored_rows.csv` gained CRLF from
`csv.writer`, whose `lineterminator` defaults to `\r\n`. Each conversion turned a small content
change into a whole-file rewrite: `hand_links.csv` alone diffed at **22,226 lines** against a real
change of 1,694.

The first diagnosis was wrong. The stage 1 loader had also re-ordered `hand_links.csv`, so the
rewrite was read as an ordering problem, and restoring the original ordering changed the diff by
**exactly zero lines**. Line endings were the whole of it.

All three files now re-emit each surviving line with the ending it had in the baseline and give new
lines that file's dominant ending. The commits that introduced the conversion were rewritten in
place rather than fixed forward, since stacking a corrective commit would have left two whole-file
rewrites in the history instead of none. Content was verified unchanged by rebuilding: the catalog
comes back at 10,123 rows with zero drift and the relations at 11,505, both exact against the copy.

⚠️ **The repo has no `.gitattributes`,** so nothing enforces this. `hand_removals.csv` is genuinely
mixed, 236 LF lines and 41 CRLF, and `authored_rows.csv` is pure LF. Any script that rewrites a hand
file has to preserve the endings it found.

## Suites

1,328 Python passing, 154 JavaScript passing, 22 skipped.

⚠️ One standing failure, **pre-existing and unrelated**:
`tests/test_mining_boundaries.py::test_a_catalog_canonical_is_food_unless_its_exact_form_is_listed`
fails on `Miracle Whip`. It reads **live** `recipes.db` and fails the same way on a clean checkout.
`Miracle Whip` is an authored row with no source entry, so `hand_removals.csv` cannot reach it. It
needs its own resolution. ⚠️ It **skips** under the CI condition, where no `recipes.db` exists, so a
failure of this test in CI would be a new problem rather than this one.

## Waiting

- **Promotion is DONE.** Live carries the copy's derived work as of 2026-09-20.
- **The cocoa re-link**, a live-data change, still needs its own dry-run. 22 of the 27 live link
  disagreements have BETTER stored links, placed by `hand_repoints.csv` on purpose, so a blanket
  re-link would downgrade them.
- **3 `mined_dish_appliance` rows** carry the pre-fix crockpot vocabulary and self-heal on the next
  mine. Left deliberately.
- **The `to taste` parser gap**, 705 lines, still open. `salt to taste` is still UNMATCHED.
- **The 4,964-row substitution queue** is loaded and unreviewed.
- **`CODE_WALKTHROUGH.md` predates the mining stack** and its tour is deferred to its own pass.
- **Stage 2 of the re-harvest**, 4,407 first-parent `kind_of` edges, scoped and read but not loaded.
  The read found it is a row-admission problem more than an edge-quality one, and the two
  highest-impact edges in it are backwards.
- **Stage 3**, 1,513 second-parent `kind_of` edges, needs axis-labeling in the UI first.
- The **69-row parent-pass review** in `previews/parent-pass-review.html` still awaits a ruling.
- **Gather work**, roughly 25 authored edges plus the 21 lamb preparations to their cuts.
