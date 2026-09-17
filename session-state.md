# Session state

Where the two databases stand, what is committed, and what is waiting. Written 2026-09-17.

## The two databases

**`recipes.db`, live, `07f8712c`. Not written to at any point in this work.**

**`recipes-preview.db`, the copy, `db07d0c9`. Gitignored, and the canonical build.**

| | live | copy |
|---|---|---|
| `library_names` | 10,489 | **10,123** |
| `library_relations` | 10,204 | **11,505** |
| `kind_of` / `in_category` | 3,801 / 6,399 | 3,759 / 6,259 |
| `made_from` / `part_of` | **4 / 0** | **1,458 / 29** |
| `library_aliases` | 164 | 164, a different 164 |
| `mined_dish` and its four child tables | **0** | 159,496 dishes, 1.36M cells |
| `mined_occurrences` | 3,018 | 2,993 |
| `mined_pairings` | 362,319 | 361,172 |
| `recipes` / `recipe_ingredients` | 299 / 3,563 | 299 / 3,563 |
| `ingredients`, `cook_log`, `ratings` | 36 / 134 / 118 | 36 / 134 / 118 |

### On both

The Tier 0 parent pass, meaning the `duck`, `quail`, `poultry` and `rambutan` renames, the Latin
`kind_of` edges and the Tier 0 aliases. Migrations 040 and 041. All of Andy's own data.

### Copy only, heading toward promotion

- The **dish facet extraction**. Live has zero rows in all five dish tables.
- The **stage 1 web**, 1,458 `made_from` and 29 `part_of` edges. Live has 4 `made_from` and no
  `part_of` at all.
- The **five plain-word renames**. Live still reads `turkey meat`, `lamb meat`, `rabbit meat`,
  `sheep meat` and `bison meat`. The copy reads `turkey`, `lamb`, `rabbit`, `sheep`, `bison`.
- The **`goat` row**. Live does not have it.
- The **whole row cleanup**, 367 rows. Live still holds `PotatoEurope`, `drinking straw`,
  `turpentine`, `Batomorphi` and the rest.
- The alias table's **five demotion aliases**. Live carries the pre-rename promotion aliases
  instead (`turkey` and `bison` as aliases), the copy carries `turkey meat` and `bison meat`.

## Reproducibility

The copy rebuilds from the committed hand files exactly. Measured, not argued:

```
verifying build 10,123    copy 10,123
  in build but not in copy  0
  in copy but not in build  0
  canonical drift           0
  folds refused             0
  removals dangling         0
```

`build_library.build()` takes 27 seconds with `LIBRARY_NAMES_CSV` and `HAND_REMOVALS` pointed at
scratch paths. The databases are gitignored. **What is committed is the code and the hand files
that reproduce them**, which is why the commit is worth making before the promotion is decided.

## Hand files

| File | Decisions |
|---|---|
| `hand_removals.csv` | 610, of which 386 drops, 166 variation trims, 58 folds |
| `hand_links.csv` | 11,791 lines, carrying the stage 1 edges and 4 re-points |
| `hand_aliases.csv` | 167 |
| `hand_renames.csv` | the Tier 0 four plus the five plain-word renames |
| `authored_rows.csv` | 70 authored rows including `goat` |

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

1,296 Python passing, 154 JavaScript passing.

⚠️ One standing failure, **pre-existing and unrelated**:
`tests/test_mining_boundaries.py::test_a_catalog_canonical_is_food_unless_its_exact_form_is_listed`
fails on `Miracle Whip`. It reads **live** `recipes.db`, which this work never touched, and it fails
the same way on a clean checkout. `Miracle Whip` is an authored row with no source entry, so
`hand_removals.csv` cannot reach it. It needs its own resolution.

## Waiting

- **Push is held.** Nothing has been pushed.
- **Promotion of the copy to live** is undecided and is the large open question.
- **Stage 2 of the re-harvest**, 4,407 first-parent `kind_of` edges, scoped and read but not loaded.
  The read found it is a row-admission problem more than an edge-quality one, and the two
  highest-impact edges in it are backwards.
- **Stage 3**, 1,513 second-parent `kind_of` edges, needs axis-labeling in the UI first.
- The **69-row parent-pass review** in `previews/parent-pass-review.html` still awaits a ruling.
- **Gather work**, roughly 25 authored edges plus the 21 lamb preparations to their cuts.
