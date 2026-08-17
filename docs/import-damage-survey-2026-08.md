# Import damage survey — August 2026

**Surveyed 2026-08-15**, read-only, against live `recipes.db`. Sibling to
[import-reference-15.md](import-reference-15.md): that file is the *regression baseline* for how the
importer behaves; this one measures **what the importer actually left behind** across the whole
corpus, and what a janitorial cleanup edit costs in the annotation layer.

Why it exists: the annotation layer (O-c) is meant to record how a recipe gets **personalized**
(doubled the garlic, swapped the oil). If most future editing turned out to be **cleanup of import
artifacts**, those corrections would render as personal annotations and dilute the signal. This
survey sizes that risk with real numbers before any cleanup-vs-change mechanism gets designed. The
decisions it justifies live in [../ROADMAP.md](../ROADMAP.md) (importer hardening; the deferred
classification mechanism).

This is documentation, not recipe data — `recipes.db` is git-ignored.

## Denominators

| | count |
|---|---:|
| recipes | **300** (298 `source='app'`, 2 `test`) — *2026-08-17: now **304** (298 `app`, 6 `test`); all 304 carry a `reason='original'` snapshot, 0 missing* |
| ingredient rows | **3,570** — 225 headings + **3,345 real lines**, across 297 recipes |
| step rows | **2,377** — 116 headings + **2,261 real steps**, across 274 recipes |

Import batches by `recipes.created_at`: **5** @ `2026-06-24 00:56:21` (the former seed five),
**293** @ `2026-07-01 21:29:10–11` (the Paprika run), **2** later copies. Every percentage below is
against the "real lines" / "real steps" rows.

## 1. Ingredient damage — 78 rows (2.3%) across 59 recipes (19.9%)

| class | rows | % of 3,345 | recipes |
|---|---:|---:|---:|
| stray punctuation stranded at the name's head/tail | **32** | 1.0% | 21 |
| non-vocabulary compound unit | 23 | 0.7% | 21 |
| measuring unit stranded in the name | 11 | 0.3% | 11 |
| digits/fraction at the head of the effective name | 10 | 0.3% | 9 |
| empty `quantity` though `raw_text` opens with one | 6 | 0.2% | 5 |
| doubled whitespace | 2 | 0.1% | 2 |
| **mojibake / HTML entities / HTML tags** | **0** | 0% | 0 |
| `qty` ≠ `quantity` + `unit` recomposition | **0** | 0% | 0 |
| **union (deduplicated)** | **78** | **2.3%** | **59** |

"Effective name" = `label` when set, else `raw_text` — what `_ing_name` and the ledger actually
show.

**Stray punctuation** — the largest class, almost always a dual-unit construction the splitter cut
mid-token, or a source that put a comma after the amount:

```
chicken-marsala#2         raw='2 Cups, Italian Imported Marsala Wine'    label=', Italian Imported Marsala Wine'
chicken-marsala#11        raw='1-2 Tablespoons, Unsalted Butter, Cold'   label=', Unsalted Butter, Cold'
dan-dan-noodles#8         raw='8 oz. ground pork (225g)'                 label='. ground pork'
lazy-noodles#0            raw='12 oz. dried wheat noodles'               label='. dried wheat noodles'
kale-fennel-…-rishta#13   raw='2 oz./75g linguine'                       label='./75g linguine'
comforting-spinach-…#10   raw='16 oz./500g spinach, roughly chopped'     label='./500g spinach, roughly chopped'
garlic-rice#0             raw='50 – 75g/ 4 – 5 tbsp unsalted butter , divided'  label='/ 4 – 5 tbsp unsalted butter , divided'
chocolate-hazelnut-wedges#6  raw='½-inch cubes'   qty='½'                label='-inch cubes'
```

**Non-vocabulary compound units** — the unit slot captured a size+count phrase the app's unit
vocabulary doesn't know. Mostly *semantically* fine ("2 large cloves garlic" reads correctly); they
matter because the scaler and the volume→weight matcher can't act on them:

```
'small bunch' ×4 · 'large cloves' ×4 · 'package' ×2 · 'large head' ×2 · 'medium head' ·
'large bunches' · 'large handfuls' · 'tins' · 'small handful' · 'head' · 'large bunch' ·
'packages' · 'pieces' · 'medium cloves' · 'small pinch'
```

**Measuring unit stranded in the name** — the unit word ended up in the name instead of the unit
column, so the amount is silently under-specified:

```
waffle#4                  raw='480mL cups milk'          qty='480 mL'  label='cups milk'
chicken-pepperoni#5       raw='28 oz large tomato can with some water'  label='large tomato can with some water'
quick-easy-hainanese-…#31 raw='3 L water'                qty='3'       label='L water'
karak-chai#6              raw='2 Cloves'                 qty='2'       label='Cloves'
```

**Compound quantities / amount-in-name** — the amount never got split out at all:

```
minestrone-soup#5         raw='1 28 oz Whole Canned Tomatoes, pureed'   qty='1'  label='28 oz Whole Canned Tomatoes, pureed'
roasted-pumpkin#0         raw='1 2-3 lb. sugar pumpkin'                 qty='1'  label='2-3 lb. sugar pumpkin'
acqua-pazza#0             raw='2 x 6oz halibut fillets, …'              qty=''   label=NULL
jamaican-rice-and-peas-beans#7  raw='2 x 400g / 14oz cans red kidney beans, drained'  qty=NULL
```

**Parenthetical duplicates** — a converted amount left behind in the name:

```
earl-grey-tea-cake#1      raw='1 cup/240 milliliters (120mL, 120mL)  heavy cream'
                          qty='1 cup'  label='(120mL, 120mL)  heavy cream'
```

### Deliberately NOT counted as damage

Three large populations look alarming and aren't. Counting them would roughly triple the headline
number dishonestly:

- **416 rows (12.4%) with no amount at all.** Only 75 contain any digit in `raw_text`, and those are
  legitimate lines — `'Juice of 2 lemons, plus zest'`, and the `beans` reference recipe
  (`'• Black beans: 90 minutes to 2 hours'` ×20). The rest are "salt to taste" / "for serving".
- **329 rows (9.8%) across 27 recipes with a NULL `label`.** This is the *storage convention* for an
  unlinked row, not damage: the name lives in `raw_text` and `_ing_name` falls back to it
  ([snapshot_diff.py:167-170](../snapshot_diff.py#L167-L170)). A save NULLs `label` on **every** row
  anyway — see §4.
- **Fraction style.** 687 rows carry unicode fractions, 290 ASCII, and **21 recipes mix both** in
  `qty`. Source variation, not a mis-parse; nothing normalizes it, and nothing needs to.

## 2. Step damage — per class (no union; see the exclusion note)

| class | rows | % of 2,261 | recipes |
|---|---:|---:|---:|
| **redundant `"1. "` numbering prefix** | **75** | **3.3%** | **22** |
| very short, heading-like (<12 chars) | 10 | 0.4% | 6 |
| underscore-wrapped pseudo-heading | 5 | 0.2% | 3 |
| empty / whitespace-only | 1 | 0.04% | 1 |
| doubled whitespace | 1 | 0.04% | 1 |
| **mojibake / entities / HTML tags / stray leading-trailing whitespace / bullet prefixes** | **0** | **0%** | **0** |
| *(excluded)* no terminal punctuation, >60 chars | *71* | *3.1%* | *46* |

**Recorded per class rather than as a union, deliberately.** A union has to encode which classes
were judged non-damage, and that judgement rots the moment someone re-runs the scan and gets a
different total. The classes are stable; the union isn't.

The **excluded 71** are rows with no closing punctuation. Inspected by hand: essentially all are a
missing final period, not a truncation — `banana-bread#1 'Add combined remaining ingredients,
mixing just until moistened'`. No genuinely cut-off sentence was found anywhere in the corpus.

**The `"1. "` prefix is the largest step class and the most mechanically fixable** — the source
numbered its steps as text, and the UI numbers them again, so they render doubled:

```
aloo-potato-parathas#0  '1. MAKE THE DOUGH: In a medium bowl, mix all the dough ingredients…'
aloo-potato-parathas#1  '2. WHILE THE DOUGH IS RESTING, MAKE THE FILLING: …'
matar-paneer#2          '3.  In the same pan over medium-high heat, warm the remaining 2 tablespoons ghee…'
```

**Browser-observed 2026-08-16 — the two numberings DISAGREE, and not only after editing.** Seen live
on `caramelized-onion-dal-copy` during an annotation click-through: the app's margin circle read **3**
beside text beginning **"2."**. The cause is structural, not editing damage — the source numbers
*logical* steps while the app numbers *rows*, and the import split several logical steps across
multiple rows. It is therefore already wrong at import, on untouched recipes:

```
caramelized-onion-dal (never edited)          khichdi (never edited)
  circle 1  '1. MAKE THE DAL: …'      agree     circle 1  '1. MAKE THE DAL: …'         agree
  circle 4  '2. MEANWHILE, MAKE …'    DISAGREE  circle 4  '2. MAKE THE SEASONING: …'   DISAGREE
  circle 7  '4. Top the dal and …'    DISAGREE  circle 6  '3. Add the seasoning …'     DISAGREE
```

This is the concrete argument for stripping the prefix at import: the count alone understates it,
because the two numbers don't merely duplicate — they **contradict each other on the page**, and a
reader following "2." lands on the wrong step.

**Browser-observed 2026-08-16 — ALL-CAPS `PREFIX:` section titles flattened into step text.**
`'MAKE THE DAL:'`, `'MEANWHILE, MAKE THE ONION:'` are section headings the parser left inline instead
of promoting to `is_heading` rows. Same class as the underscore-wrapped pseudo-headings below, but a
**different surface form**, so it needs its own detector. Measured after the observation:
**24 rows across 11 recipes (1.0% of steps)**, and **18 of those rows sit in 9 recipes with ZERO real
step headings** — i.e. the recipe ends up with no step-section structure at all.

```
caramelized-onion-dal#0  '1. MAKE THE DAL: In a deep medium skillet over high heat, combine the lentils,…'
caramelized-onion-dal#3  '2. MEANWHILE, MAKE THE ONION: In a large skillet over medium-high heat, warm t…'
beans#1                  'RINSE: Rinse dried beans well, discarding any dirt or rocks.'
beans#2                  'OVERNIGHT SOAK: Put beans in a pot and cover with 2 inches of water…'
garlic-ginger-chicken-…#0  '1. MAKE THE MARINADE: In a medium bowl, mix the garlic, ginger, mint,…'
```

**Consequence — importer damage degrades the annotation layer downstream.** Because these never
became headings, a removed step in such a recipe has no `section` to name, so `diff_snapshots` emits
`section: null` and the render falls back to list-bottom placement (§the preamble rule in
`annotation-place.js`). The annotation is correct given the data; the data is wrong. Fixing the
importer is what makes the annotation layer read properly on these recipes — the two are not
independent.

**Browser-observed 2026-08-16 — Cyrillic HOMOGLYPHS where Latin/digits belong.** Spotted while
verifying the numbering above, and **missed entirely by the scripted survey**, whose encoding checks
looked for mojibake byte-sequences (`Ã`, `â€`) and HTML entities — not for characters that *render
correctly but are the wrong codepoint*. Corpus sweep of the Cyrillic + Greek blocks found **2 rows**:

```
caramelized-onion-dal#5                  'З. MAKE THE SEASONING: …'   З = U+0417 CYRILLIC CAPITAL ZE, not "3"
garlic-ginger-chicken-…#2                '3. МАКЕ THE CHICKEN: …'     МАКЕ = Cyrillic М А К Е, not "MAKE"
```

Tiny in count, but it **qualifies the "encoding is spotless" line below**: spotless of *mojibake*,
not of homoglyphs. It also breaks any prefix-stripper that matches `^\d+\.` — `'З.'` is not a digit,
so that row would survive a naive fix and silently keep its bogus number. Almost certainly OCR or a
Cyrillic-keyboard slip upstream in the source, not an import bug — but the importer is where it can
be caught.

**Underscore-wrapped pseudo-headings** — a real section heading the source emphasised with
underscores, imported as an ordinary numbered step:

```
brioche-bread#9  '_Cold Proof_'   ·  brioche-cinnamon-rolls#7  '_Shaping_'
brioche-cinnamon-rolls#15  '_The frosting:_'  ·  cappuccino-muffins#1  '_Streusel_'  ·  #4  '_Muffins_'
```

Seven more heading-like steps carry no wrapper at all and are indistinguishable from prose by
pattern: `'Assembly'`, `'Filling'`, `'Sponge'`, `'Dough'`, `'Loaves'`, `'Rolls'`, `'Additions'`.

The single empty step (`khichdi-copy#1`) is a **test artifact of the editor work**, not an import
product.

**Encoding is spotless across both tables: zero mojibake, zero HTML entities, zero tags.**

## 3. `import_flags` — 593 rows, 209 recipes (69.7%), surfaced nowhere

| flag | rows | recipes |
|---|---:|---:|
| `ambiguous_section` | 471 | 182 |
| `grams_declined` | 37 | 28 |
| `section_suggested` | 30 | 20 |
| `no_directions` | 26 | 26 |
| `each_multi` | 18 | 14 |
| `multiplier` | 6 | 5 |
| `no_ingredients` | 3 | 3 |
| `photo_only` | 2 | 2 |

All stamped `2026-07-01 21:29:10–11`. A row records only `(recipe_id, position, flag, reason,
created_at)` — no field, no suggested correction.

**They are written and never read.** No Flask route, no `/api/` endpoint, no client reference, no
page. The only reader in the codebase is
[scripts/backfill_headings.py:94](../scripts/backfill_headings.py#L94), a one-off backfill.

**They mark ambiguity the parser NOTICED, not damage it PRODUCED.** Of the 78 damaged ingredient
rows, **16 (21%) carry a flag** at that position and **62 (79%) passed silently**. Conversely there
are 558 line-level flag positions and only those same 16 overlap — the two populations are largely
disjoint:

```
FLAG ['multiplier']       comforting-spinach…#8   '2 x 14 oz./400g cans of chickpeas'    ← caught
FLAG ['grams_declined']   chickpea-rice-pilaf#5   '1 1/2 tins (21 oz / 600g) chickpeas'  ← caught
silent                    chicken-marsala#2       '2 Cups, Italian Imported Marsala Wine'
silent                    dan-dan-noodles#8       '8 oz. ground pork (225g)'
silent                    chicken-pepperoni#5     '28 oz large tomato can with some water'
silent                    earl-grey-tea-cake#1    '1 cup/240 milliliters (120mL, 120mL)  heavy cream'
```

**That 79% is an INGREDIENT figure. Steps are 100% unflagged by construction:** `_line_flag_rows` is
only ever called from `_ingredient_rows`
([import_write.py:146-148](../import_write.py#L146-L148)), so `import_flags.position` indexes
ingredient positions only — **no step-level flag mechanism exists.** All 75 numbered-prefix steps
and all 5 underscore-wrapped steps were unflaggable, not merely unflagged.

## 4. What a cleanup edit actually costs

**Editing to date: 298 of 300 recipes (99.3%) are byte-equal to their `reason='original'` baseline.**
The only two with a non-empty diff are test copies made during this work (`french-fries-copy`, 1
entry; `khichdi-copy`, 9 entries of which 8 are genuinely personal). **Cleanup pollution is
prospective, not observed.**

> *Re-counted 2026-08-17: **298 of 304** are byte-equal — the clean count is unchanged; the corpus grew
> by 4 further test copies, all of them divergent. The conclusion holds.*
>
> *A later simulation put a number on what a **backfill** would cost, which this section did not
> measure: restructuring the 25 recipes the importer corrections would touch generates **112
> annotations, 91 of them visible**, 77 being `step/modified` — because `snapshot_original` captures
> once and never re-captures, so corrected rows read as hand-edits against an uncorrected baseline. That
> is the argument for splitting the work into door-only (safe) and backfill (needs a re-baselining
> ruling). See ROADMAP → Recipe Import (P15).*

Simulated read-only through the full round trip — original → what a save actually rewrites → the
fix → `diff_snapshots`:

| cleanup | entries |
|---|---:|
| **re-save with NO edit** (baseline, all six recipes) | **0** |
| strip a stray `.` from one name (`dan-dan-noodles#8`) | 1 |
| strip `, ` from **two** names in one session (`chicken-marsala`) | 2 |
| **split a mis-parsed amount out of the name** (`acqua-pazza#0`) | **0** |
| promote `_Shaping_` to a real heading (`brioche-cinnamon-rolls#7`) | 2 |
| just unwrap the underscores on that step | 1 |
| remove `'(120mL, 120mL)  '` from a name (`earl-grey-tea-cake#1`) | 1 |

**One cleanup ≈ one annotation entry, 1:1, no cascade.** Fixing one row never disturbs its
neighbours.

**The zero-baseline is not trivial.** `write_recipe_rows` NULLs `label` and rewrites `raw_text` on
**100%** of ingredient rows on every save ([app.py:298-311](../app.py#L298-L311)) — verified on real
data:

```
french-fries-copy pos1:  label 'white vinegar' -> None
                         raw_text '2 tbsp white vinegar' -> 'white vinegar'
```

The diff absorbs all of it, because it compares only three aspects. See the standing rule in
[../CODE_WALKTHROUGH.md](../CODE_WALKTHROUGH.md).

**Re-splitting a mis-parsed amount is free, and that is the most valuable cleanup class.** The
phase-2 match key `_ing_line_canon` recomposes `qty + " " + name`, so moving `'2 x 6oz'` out of the
name yields the *identical* canonical line on both sides; difflib marks the pair `equal` and
`_diff_seq` skips `equal` blocks before `on_pair` ever runs. Zero entries.

The heading-promotion case emits a second entry of `kind:"heading"`, which the render ignores by
design — so on screen it reads as one struck removed step, not two marks.

## 5. Reorder is diff-noisy — and why it gates drag-reorder

Swapping two rows produces a **removed + added phantom pair** for any row the diff can't match by a
stable key. Ingredient lines match by `ingredient_id` when both sides carry one; **only 50 of 3,345
non-heading rows are id-linked (1.5%)**, and **steps have no id at all**. So ~98.5% of ingredient
lines and 100% of steps would go noisy on a pure reorder. This is why drag-reorder is split out and
gated on deciding the annotation semantics first — the fix belongs in `snapshot_diff`, not the
editor.

## 6. Signals available to tell cleanup from personalization

**Present:**

1. **Import time** — `recipes.created_at`, and the `reason='original'` snapshot's `created_at` is
   **identical to it in 300/300 cases** ([import_write.py:282](../import_write.py#L282) passes
   `r["created_at"]`). Sharp batch boundaries (§Denominators).
2. **`import_flags`** — position-level for ingredients, with a type and a human reason string.
3. **Cook activity** — `cook_log.cooked_on` (**DATE only, no time**), `cook_log.source`
   (`'app'` / `'demo-seed'`), `ratings.rated_on`. 132 cook rows.
4. **Edit magnitude / shape**, derivable from the diff itself: entry count, `kind`, `type`, `field`,
   and the `from`/`to` strings — `field:"amount"` `"1"→"2"` is numerically clean, while
   `field:"name"` `". ground pork"→"ground pork"` has near-1.0 string similarity and differs only by
   punctuation.

**Absent — the ones any time-window idea would need:**

1. **`recipes` has no `updated_at`.** Nothing anywhere records *when* a recipe was edited.
2. **No snapshot is written on manual save.** `snapshot_recipe` is called for `'original'`
   ([app.py:373](../app.py#L373)) and `'cook'` ([:906](../app.py#L906), [:985](../app.py#L985),
   [:1022](../app.py#L1022)) — **never on the PUT path**.
3. `recipe_snapshots` holds **300 rows, all `reason='original'`; zero `'cook'` rows** — no
   intermediate history, no second point on any time axis.

A "grace window" therefore has an import timestamp but **no edit timestamp to measure it against**;
that side would have to be built first.

## Reproduce

Read-only; all figures above come from `recipes.db` plus the real `snapshot_serialize` /
`snapshot_diff` modules (no fixtures, no mocks). The scans were throwaway scripts: pattern checks
over `recipe_ingredients` / `recipe_steps`, a `(recipe_id, position)` join against `import_flags`,
a full-corpus `content_blob` + `diff_snapshots` pass, and in-memory mutation of an original blob to
simulate a save + cleanup. Re-run against a fresh corpus by rebuilding those; the per-class
definitions in §1 and §2 are the part worth keeping stable.
