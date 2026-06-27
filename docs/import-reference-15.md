# Import reference — the verified-clean 15 (baseline)

A known-good snapshot of the first 15 recipes imported from the Paprika native archive, reviewed
by eye after every cleanup-core fix. Use it as a **regression baseline** for the full ~295
import: compare the 295's behavior (flag rates, parse patterns, populated-field rates) against
these proportions to spot anything that behaves differently than it did on the 15 verified here.

This is documentation, not recipe data — `recipes.db` is git-ignored; this file just records the
verified state so it can be diffed against later.

## Reproduce the selection

```
python3 import_write.py --seed 527700      # dry-run: the same 15 (distinct authors), writes nothing
```

Real write path (data only, never committed): `python3 backup.py` →
`sqlite3 recipes.db "PRAGMA foreign_keys=ON; DELETE FROM recipes WHERE source='app';"` →
the seed-527700 runner with the current cleanup core. Imported recipes are `source='app'`;
uid-dedup skips the 5 seed twins.

## The 15 (title · source)

1. Basic Hummus — Food52 Genius Recipes / Ottolenghi & Tamimi
2. Brownies — Love and Lemons
3. Chicken Pepperoni — Nana
4. Chicken Tikka Masala — cafe delites / Karina
5. Chocolate Chip Cookies — Claire Saffitz, *Dessert Person*
6. Country Ham Croquettes with Parsley Salad — *Seeking the South*
7. Homemade Pasta Dough — Tuscany Air BNB
8. Hummus — Cookie + Kate
9. Italian Turkey Fried Meatballs — skinnytaste simple
10. King Arthur's Original Cake Pan Cake — King Arthur
11. Milky Tea Tres Leches — *I'll Bring Dessert*
12. Oat Bars — Smitten Kitchen Every Day / Deb Perelman
13. Prego Rolls – Steak and Piri Piri Sandwiches — *In Bibi's Kitchen*
14. Sarma Hot Honey Cornbread — LAHBco
15. Thai Tea Ice Cream (ChaTraMue's Thai Tea) — Cooking Therapy

## Verified counts (the baseline)

| metric | value |
|---|---|
| recipes (app) | 15 |
| ingredient rows | 189 |
| step rows | 164 |
| ratings rows | 8 (rating 0 / unrated → no row) |
| import_flags — total | 17 |
| import_flags — `ambiguous_section` | 14 |
| import_flags — `section_suggested` | 3 |
| import_flags — `multiplier` | 0 |
| incomplete recipes (recipe-level flags) | 0 |
| ingredient rows with `grams` | 54 |
| ingredient rows with `secondary_measure` | 38 |

Derived rates, for comparison against the 295: **~9%** of ingredient rows flagged for review
(17/189), **~29%** carry a harvested gram (54/189), **~20%** carry a secondary measure (38/189).
A large deviation from these on the 295 is a signal to inspect, not necessarily a bug.

## The 3 `section_suggested` promotions (confirmed correct by eye)

| recipe | line | signal |
|---|---|---|
| Oat Bars | `crust` | common section word |
| Oat Bars | `filling` | common section word |
| Sarma Hot Honey Cornbread | `Habanero Syrup` | head-noun ends in "syrup" |

Each is `is_heading=1` **and** flagged `section_suggested` for confirmation — never silently
committed. (At scale, a review UI to confirm/reclassify these is the plan; see ROADMAP.)

## What "clean" was verified to mean

- **No leftover `(NNN g)` / `(N cup)` measure-parens** in any ingredient name (0).
- **Weight-first** lines (`100 g (1 cup) sugar`) → clean name + `grams` + `secondary_measure`.
- **Volume-first** lines (`1 cup (250 g) flour`) → clean name + harvested `grams` + `secondary_measure`.
- Dual-unit `/ N unit` and a dangling `(` stripped from names; `raw_text` is always the full original.
- **N=1 multiplier** (`1 x 397 g can of …`) → `1 can` + grams, no flag; N>1 stays flagged.
- **Step section-headers** (colon / ALL-CAPS / trailing-dash) → `is_heading=1` (trailing dash stripped).
- **Source typos preserved faithfully** (e.g. Basic Hummus "14 cups" — the harvested 250 g is the
  authoritative weight; we don't correct source data).

## Cleanup-core commits behind this baseline

- `5bf44a5` — gram-paren strip + grams capture
- `ce684e6` — dual-measure capture (`grams` + `secondary_measure`, either order)
- `fa10f1e` — step + ingredient section-headers + N=1 multiplier
- `ebde9dd` — section-header head-noun (ends-with) widening
