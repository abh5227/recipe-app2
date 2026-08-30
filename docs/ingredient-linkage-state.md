# Ingredient linkage: where the work stands

First written at `460cae5`, brought current at `622a6a0`. Every count here was re-derived
from the repo, from `recipes.db` read-only, or from the `previews/` CSVs. Where an earlier
figure was quoted from memory and disagreed with the measurement, the measurement won and
the difference is noted in place.

**The one-line state.** The library is built, the matcher is **FINISHED**, and there is
somewhere for a link to go. **Still nothing links.** 50 of 3,332 ingredient lines carry a
stored `ingredient_id`, exactly as before. ⚠️ **The matcher is no longer the constraint.** It
lives at `study/matcher/`, committed in `b42dd14`, runs in about ten seconds, and resolves
2,214 of the 2,997 labelled lines. Five other things stand between that result and a stored
link, and they are listed under "The matcher" below.

⚠️ **Do not read the shipped backend as "linking is done".** It is plumbing with nothing
flowing through it. No UI reaches it, `library_names.csv` exists on no machine, and the
live `recipes.db` has not even had migrations 029 and 030 applied yet (checked: no `source`
column on `ingredients`, no `library_names` table).

## What is committed and pushed

`origin/main` is at `622a6a0`, local matches, zero ahead and zero behind. `recipes.db` was
never written by any of it and holds
`83cd7be8e837beb1a53e2e54ce0a326106ef5f8b03dc38f8d2e107765dcfd9d7` throughout.

| commit | what it did |
| --- | --- |
| `4fee4a0` | `docs/what-the-library-is-for.md`, and the cut rules point at it. The standing purpose test for admitting, cutting, renaming or merging a row. |
| `7b3c74c` | Tracks `seed_links.csv`, the 50 seed-recipe ingredient links. This is the whole of the stored linkage. |
| `f7644ea` | `depluralize` mangled the `-ves` words, `cloves` to `clof`. Cost 46 recipe-line matches. Fixed with a word list. |
| `974c66d` | `normalize` deleted diacritics rather than folding them, `jalapeño` to `jalape o`. Dropped accented ingredients. NFD, not NFKD, and not `build_join`'s NFKC. |
| `bc38181` | `depluralize`'s `ss/us/is` guard blocked real plurals whose singular ends in `-i`. `zucchinis`, `chilis`. Fixed with `I_PLURAL`, a membership set, because the shape is genuinely ambiguous. |
| `460cae5` | Rule 5, the pasta-parent anchor. Admits a Wikidata item that names Q178 "pasta" as a direct superclass, one P279 hop. Plus `bagel` as override number six, filed as a new class C. |
| `14575b4` | This document, first written. |

## The add-on-save backend, shipped

Eight commits, `41aeea6` through `5f2aacd`, all pushed and CI-green. They answer decision 4
and build the whole backend for it. Nothing in the UI calls any of it.

| commit | what it did |
| --- | --- |
| `41aeea6` | `library_names`, a two-column `(library_id, canonical)` lookup. Migration 029. Inert. |
| `fcea950` | `ingredients.source` and `ingredients.library_id`. Migration 030. `source` mirrors `recipes.source` and defaults to `'seed'`, which marks the 36 hand-authored rows without a backfill. |
| `9cb9365` | `build_db.seed_library_names`, which fills the lookup from a gitignored server-side file and leaves the table empty when the file is absent. Mirrors `seed_weights`. |
| `5aa257a` | `build_library.write_library_names`, which writes that file from the kept rowset. Same `not row["cut_by"]` predicate the review sheet uses, so the two describe one list. |
| `644c2e6` | `GET /api/library/search?q=`, plus `ingredient_slug()`. Returns matches with `ingredient_id` and `matched_by`, so a caller knows whether linking would create a row. |
| `dd45959` | The save gate becomes create-or-reject. A line carrying `item_library_id` creates an `ingredients` row and links to it. `validate_recipe_payload` renamed to `resolve_recipe_payload`, because it writes now. |
| `beae33d` | `DELETE /api/ingredients/<iid>`. The undo, landed before the lookup file could exist so a wrong promote was always reversible. |
| `5f2aacd` | Five fixes from a whole-stack review, one of them a real cross-stage bug. See below. |
| `622a6a0` | Stage 7, the drawer. All four panel blocks now follow one rule: no data, no block. The visibility decision moved into `static/panel-blocks.js`, a pure module, and `buildSeason` stopped claiming "A pantry staple, available year-round" for a row with no month data. ⚠️ That line was showing on **22 of the 36 curated rows**, not only on promoted ones, so removing it changed what soy sauce and cumin display. Deliberate. |

**The backend is COMPLETE. The create path is INERT.** `library_names.csv` is gitignored
and exists on no machine and in no clone, so the lookup is empty everywhere. An empty
lookup means every `item_library_id` falls into the reject case, which means the gate
behaves exactly as the old default-deny gate did. **The feature self-disables wherever the
file is absent**, and that is true on a fresh clone, in CI, and on Postgres, where nothing
populates the table at all.

### The architecture, settled

- **The `ingredients` table IS the durable link target, and it GROWS.** Links point at
  `ingredients` rows, the way the existing 50 do. A library link creates a new row from
  `library_names`: slug id, canonical name, `source='app'`, `library_id` recorded,
  `descr`/`pairs` NULL.
- **The library is a WRITE-TIME source, never a link target and never read at serve time.**
  `app.py` has no access to `join.db` (894 MB) or `sources.db` (5.18 GB), and a test checks
  that on the import graph. The only library data the app sees is the small lookup.
- **Why not link to library ids directly:** they are not durable. `460cae5` destroyed seven
  of them in one ordinary rebuild (`en:penne`, `en:lasagne`, `en:linguine` and four more).
  An `ingredients` id is minted once and never recomputed, so churn cannot reach a stored
  link. `ingredients.library_id` is audit provenance and is expected to dangle.
- **Promotion is ADD-ON-SAVE.** The row is created when a save first references it, not by
  a bulk migration and not by an offline batch.
- **`library_names.csv` ships as a gitignored server-side file**, like `recipes.db` and the
  two source databases it is derived from. Placed by hand on a machine that generated it.
  This is precisely why the feature self-disables without it.
- **`ingredient_slug()` is the shared minting rule.** Unicode-preserving (ASCII-folding
  erases 56 of the 10,527 canonicals outright), underscores rather than `slugify()`'s
  hyphens. The search route and the save gate both call it. Two copies would make the
  route's `matched_by: "slug"` answer a lie.
- **Tiers.** `'seed'` is the hand-authored 36 and is protected. `'app'` is promoted and
  deletable. The delete path allowlists `('app',)` rather than refusing `'seed'`, so a
  tier invented later is protected by default.
- **Fail-closed throughout.** Names come from the table and never from the request. An id
  the lookup does not hold creates nothing. Check-then-link runs before every insert,
  because 32 of the 36 seed ids are reproduced exactly by slugifying some library canonical
  and inserting over one is a primary-key conflict.
- ⚠️ **STEP-LINK PROMOTION IS DROPPED.** A step's `[[key]]` still resolves against existing
  ingredient ids exactly as before, and still cannot create. The reverse lookup a step would
  need is not a function: 63 slugs map to 129 library rows. Dropping it also took the `slug`
  column and its index out of `library_names` (624 KB rather than 1,044 KB) and removed four
  of the gate's cases. The ingredient list is the natural entry point for linking anyway.

### The pre-push review, and the lesson

The six commits after `41aeea6` were each reviewed and tested at the time. A critical read
of them **as a set**, before pushing, found five things. One was a real bug.

⚠️ **`_promote_library_row` matched on the slug alone, which is not idempotent.** Promote
`Q1063736` as `penne`, let a rebuild rename its canonical to `penne rigate`, promote the
same library id again, and the new slug missed the old row and inserted a SECOND
`ingredients` row carrying the same `library_id`. `/api/library/search` resolves a
`library_id` through a dict built in a loop with no `ORDER BY`, so in that state it answered
with whichever row the database returned last.

**Why stage-by-stage testing could not catch it.** Stage 4 tested search's notion of
"already promoted". Stage 5 tested the gate's notion. Both passed. **Neither ever tested the
two notions against each other**, and they had silently diverged. Fixed in `5f2aacd`, where
the resolution order became lookup, `library_id`, slug, insert, and a test now asks search
and the gate the same question and asserts they agree.

**The lesson: cross-stage consistency needs its own review pass.** A staged build with a
stop at each seam catches what is wrong inside a stage. It cannot catch two stages that each
work and disagree.

The other four: a list or dict link key returned 500 rather than 400 (and the `item` half of
that predates add-on-save), an em dash in a refusal string, a promoted line rendering its
slug (`200g egg_pasta`) because `write_recipe_rows` falls back to the id, and the search
route using `LIKE`, which folds ASCII case on SQLite and nothing at all on Postgres.

## The matcher

✅ **It has a committed home and it is FINISHED.** `study/matcher/` holds 23 source files
and a README, committed in `b42dd14`. Re-run at `86671ee` against the live `recipes.db`,
which it opens read-only: **9.0 seconds**, and **2,214 of 2,997 labelled lines resolve,
73.9%**, against the 50 stored today.

⚠️ **Matching is not what blocks linking. Five other things are**, and none of them is the
matcher.

**1. Nobody has read what it found.** 3,038 lines, **91.2%**, have never been individually
read, and 2,410 of those sit in the AGREE block where two matchers landed on the same row and
neither was checked. The confidence bands are **computed** from n-gram length and coverage in
`AGREE.py`, so HIGH means the algorithm is confident, not that a person agreed. **Reading is
the remaining work.**

**2. There is no write path.** No code anywhere writes a matcher result into
`recipe_ingredients.ingredient_id`. Measured by searching every `.py` in the repo. The only
code that sets that column is `write_recipe_rows`, from a save payload, one recipe at a time.

**3. The library file is absent.** A write has to route through the materialization boundary,
`_promote_library_row`, whose first step reads `library_names`. That table is loaded from
`library_names.csv`, which is gitignored and **is not on this machine**.
[ingredient-model.md](ingredient-model.md) is the source of record for why the boundary
exists.

**4. Everything downstream assumes 36 ingredient rows.** Materializing the matches takes
`ingredients` from 36 into the hundreds. **25 assertions across 10 test files** are written
against exactly 36, as is every documented count.

**5. ⚠️ 299 of the 2,214 links are AMBIGUOUS**, 13.5%, meaning the name sits on two or more
library rows and the matcher reports all of them. **There is no tiebreak rule, and choosing
one is its own decision** that has to be made before any of this is built.

### The banked configuration

**seg0-core.** Segment the line on `, ; ( ) /` and on "or", take every consecutive word run
inside each segment, normalize with `build_join.norm_name` (the same function the index is
built with), and rank by **segment first, then longest, then leftmost**. A match in an
earlier segment beats any match in a later one, which is what stops a parenthetical gloss
from winning over the named ingredient.

**No language rule. No clause strip.** Both were measured and both were declined.

Five ranking variants and two clause-strip configurations were measured against the same
hand-judged sets of 62 regressions, 758 recoveries and 93 wrong recoveries. Results are in
`previews/seg0-eval.csv` and `previews/headnoun-eval.csv`.

| variant | matched | ambiguous | miss | regressions still open | recoveries kept |
| --- | --- | --- | --- | --- | --- |
| rightmost, the committed ladder's tie-break | 2,783 | 511 | 38 | 62 of 62 | 758 of 758 |
| **seg0** | 2,771 | 523 | 38 | **5 of 62** | 582 of 758 |
| seg0 plus the language rule, every length | 2,759 | 522 | 51 | 5 of 62 | 584 of 758 |
| seg0 plus the language rule, one word only | 2,759 | 522 | 51 | 5 of 62 | 584 of 758 |
| seg0 plus head-noun | 2,769 | 525 | 38 | 5 of 62 | **652 of 758** |

Those figures are from the pre-`bc38181` library and are kept because they are the
comparison that chose the config. The current numbers are in the next section.

**Why the language rule is out.** It buys 2 recoveries and costs 13 misses. That is a bad
trade and the rule rests on language tags that are empty for authored and for many Open
Food Facts names.

**Why the clause strip is out.** Stripping trailing purpose clauses ("plus more for
dusting", "to serve") gains 6 matcher lines and **deletes 4 real ingredients**, because
Paprika wrapped two ingredients onto one line and the second one sits after the marker. An
index-key guard was built to stop that. It removed all 4 losses and all 6 gains, because
`pan`, `dish`, `taste`, `dough` and 8 more ordinary purpose-clause words are themselves
library index keys. The guard cannot tell "for boiling potatoes" from "plus more, black
pepper". **Clause-stripping is not safely buildable in this form.**

⚠️ **head-noun measured better than seg0 and is not banked.** It keeps 652 of 758
recoveries against seg0's 582 for the same 57 regressions fixed, roughly 11 lines net. It
was left out because the head-noun definition (the last content word of the segment, form
words counting as heads) is what fixes `chile powder` and what breaks `panko crumbs`, and
it guesses on a meaningful fraction. That is a judgement call and it can be revisited.

⚠️ **Unresolved.** Language-rule variants (c) and (d) return identical numbers on every
column. Either they are genuinely equivalent over this corpus or the split between them
never took effect. Not chased, because both lose.

### Current coverage, at `460cae5`

Library rebuilt fresh from `join.db` plus `sources.db`: 11,357 rows, 10,527 kept, 184,891
index keys.

**Two numbers, and they are different questions.**

```
STORED in recipes.db right now      50 rows over 6 recipes, 36 distinct ingredient_ids
                                    1.5% of the 3,332 ingredient lines
                                    the ingredients table has 36 rows and is the FK target

WHAT seg0-core WOULD LINK           MATCHED 2,777   83.3%
                                    AMBIG     523   15.7%
                                    MISS       32    1.0%
                                    reach a row 3,300 = 99.0%
```

The 10,527-row library lives in `join.db` and reaches no recipe row at all.
`import_write.py` sets `ingredient_id` to `None` at line 128 and says so, twice.

## Confidence, and what has actually been read

**The AGREE block is 2,414 lines, 72.4 percent of the corpus.** AGREE means the committed
reduction ladder and seg0-core resolved the line to the same row. It was never read until a
60-line sample on 2026-08-27, and every precision figure quoted before that assumed it was
correct.

**Agreement is not verification.** Both matchers query one index built by one normalizer,
so they agree by construction and fail together whenever the library row itself is wrong.

A uniform random 60, seed 20260827, read one at a time. Full judgments in
`previews/agree-sample.csv`.

```
RIGHT, one unambiguous correct row    52 of 60   86.7%   95% CI [75.8%, 93.1%]
BOTH-OK-AMBIGUOUS, 2+ rows, same
  ingredient at two granularities      7 of 60   11.7%   the merge job
WRONG                                  1 of 60    1.7%   95% CI [0.3%, 8.9%]
```

⚠️ **One event in sixty is a ceiling, not a rate.** Extrapolated, the block holds somewhere
between 7 and 214 confidently-wrong links. The point estimate of about 40 should not be
quoted alone.

The one wrong was `1 cup Piri Piri Sauce` landing on `piri piri` (Q512580), which is the
chili pepper. It is a **library** failure, not a matcher failure. The matcher had nothing to
disagree about, because the whole phrase is a legitimate index key on that row.

## Bad-name pollution

Two mechanisms put names on rows that do not belong to them. One is censused. The other is
not.

### Cross-concept Wikipedia redirects, censused

Wikipedia redirects article A to article B when B is the nearest page. The join takes the
redirect as a **name** on B's row. Most are correct aliases. Some are a different
ingredient. Full census in `previews/redirect-defects.csv`.

```
names carrying wikipedia_redirect      18,158 over 2,745 rows
   kinds: redirect 15,247   article_title 2,829   derived 121
non-canonical and ASCII                14,227
flagged by KIND-WORD-GAINED             1,091

read: all 38 that appear in a corpus line, plus 60 sampled from the 880 plausible latents
   FIRING 38:  CROSS-CONCEPT  4   BORDERLINE  4   LEGIT-ALIAS 30
   LATENT 60:  CROSS-CONCEPT 15   BORDERLINE 12   LEGIT-ALIAS 33
```

**Four fire on the corpus now:**

- `Piri-piri sauce` on `piri piri` (Q512580), the chili pepper
- `Pasta water` on `pasta`, the starchy cooking liquid is not pasta
- `Cake` on `Jaffa Cakes` (Q29330), through an `article_title` name
- `Soup` on `broth` (Q275068), through an `article_title` name

**Roughly 220 more are latent**, 95 percent CI 139 to 328, over the 880 plausible latents.
The uglier ones include `Pu'erh tea` on "egg as food", `Dinner salad` and `Garden Salad` on
*Lactuca sativa*, `Pho soup` on the noodle, and `Thin coconut milk` on coconut cream.

**Not rule-removable.** A blanket "drop any redirect gaining a kind word" rule has 19
percent precision, and among the 38 that fire on the corpus it would destroy 30 working
links to fix 4. `Parmesan cheese`, `Feta cheese`, `Miso paste` and `Muscovado sugar` all
resolve real lines and would all go. **This is a hand-list**, seeded by the 19 confirmed
names.

### ⚠️ AGROVOC prefLabel pollution, NOT censused

The AGREE sample turned up six junk names. **Only one is a redirect.** Checked one at a
time:

```
sand                    on granulated sugar   agrovoc/prefLabel/en
artificial intelligence on garlic             agrovoc/prefLabel/en
AI (artificial ...)     on garlic             agrovoc/altLabel/en
Amanita caesarea        on egg yolk           agrovoc/prefLabel in six languages
Brunsli                 on vegetable oil      wikidata/label/de,en,gsw
Green cum               on cucumber           wikidata/alias/en-us
Grana Padano            on Parmesan           wikidata/alias/nb plus wiktextract
extra virgin            on olive oil          wiktextract/word/en
Cucumber plant defense  on cucumber           wikipedia_redirect/redirect
```

**AGROVOC prefLabels look like a separate and probably larger mechanism, and nothing has
measured it.** A prefLabel is AGROVOC's own primary name for a concept, so a wrong one
means the bucket join put two concepts together, which is a different failure from a
redirect following the nearest page. **This is the next place to look.**

### Where the evidence lives

`previews/` is git-ignored, so none of this survives in git.

| file | what it holds |
| --- | --- |
| `agree-sample.csv` | the 60 AGREE lines with hand verdicts and reasons |
| `redirect-defects.csv` | 98 flagged redirect names, judged, with corpus hits |
| `current-coverage.csv` | the stored-versus-would-link breakdown |
| `full-ingredient-match.csv` and `.html` | all 3,332 lines, both matchers, confidence bands |
| `seg0-eval.csv`, `headnoun-eval.csv` | the variant comparison tables |
| `seg0-moved-rows.csv`, `headnoun-moved-rows.csv` | the lines each variant moved, for reading |
| `anchor-rule-admits.csv`, `type-of-pasta-admits.csv` | the anchor-rule head-to-head |
| `merge-evidence.csv` | 1,228 candidate row pairs with evidence columns |

`previews/seed-ingredient-descriptions.csv` holds all 36 hand-authored rows with full
`descr` and `pairs`, per-row link counts, and the word/character measurements behind the
boilerplate finding in the pile.

## The open decisions

### ✅ Decision 4 is ANSWERED and its backend is shipped

**Where a stored link lives.** The three options were an `ingredient_links` table keyed by
Q-id, loading the library into the `ingredients` table, or staying a report.

**None of the three as framed.** The investigation showed the framing was wrong in two
ways. A link "keyed by Q-id" can only address 61 percent of the library, since 38 percent of
row ids are Open Food Facts strings like `en:egg-pasta`. And the real fork was never
"additive versus migration" but **whether `recipes.db` gains a copy of library identity, and
how much**, because option 1 needs a name to display and cannot reach the library at serve
time either.

**What shipped is closer to option 2, lazily.** The `ingredients` table is the durable link
target and it grows one row at a time as links are made. `recipes.db` gains identity plus
display name only, in the small `library_names` lookup. The bulk-load that made option 2
look expensive never happens: the corpus reaches 467 distinct library rows, so the realistic
ceiling is about 500 rows rather than 10,527.

**All four things behind this gate are now unblocked**, though none is built: the merge
tool, the mixes panel, the autochecker, and the matcher, which has had a committed home since
`b42dd14`. ⚠️ **What binds now is not the matcher.** It is the five blockers listed under
"The matcher" above, of which reading the 3,038 unjudged lines is by far the largest.

### ✅ Promoted-row capitalization, DECIDED: accept the canonical's casing

A promoted row shows the library canonical verbatim, so `penne` renders lowercase beside
the title-cased `Soy Sauce`. **Decision: accept it. Transform it nowhere. Fix it per row in
the curation tool when there is one.**

⚠️ **The reasoning matters more than the decision, because the obvious fix is a trap.**

- **The casing is source-given, not ours.** `choose_canonical` returns the anchor's own
  English label verbatim. Every `.casefold()` in `build_library.py` is for comparison,
  sorting or index keys and none touches a stored canonical. `penne` is lowercase because
  Wikidata's label is. "Stop lowercasing upstream" is not an available fix, since nothing
  lowercases.
- **Only two thirds of canonicals are lowercase.** Measured over all 10,527: 66.3% all
  lowercase, 13.6% Title Case, 11.0% Sentence case, 8.4% mixed, 0.6% non-Latin, 6 ALL CAPS.
  The other third carry casing that means something.
- ⚠️ **A blind `.title()` changes 9,079 of 10,527 names and DESTROYS casing in 1,339.**
  938 promote a lowercase particle, 290 flatten interior caps, 111 mangle an apostrophe.
  Real examples: `XO sauce` to `Xo Sauce`, `Elliott's blueberry` to `Elliott'S Blueberry`,
  `half-and-half` to `Half-And-Half`, `leite de castanha` to `Leite De Castanha`.
- **The library is inconsistent with itself**, so no transform can make promoted names agree
  with each other, let alone with the 36. `Dijon mustard` sits beside `honey dijon
  dressing`. `Brie de Meaux` sits beside `brie`.
- **The only safe transform buys the wrong thing.** Uppercasing the first character only
  destroys nothing (verified: 0 of 10,527), but yields sentence case, so `Egg pasta` still
  sits beside `Soy Sauce`. Different, not consistent.

**It affects zero rows today** and cannot until the picker ships. Evidence:
`previews/canonical-casing.csv`, all 10,527 rows with casing bucket, trap flags and both
transforms.

### The merge job, no longer gated

**523 lines hit two or more rows.** They fall into 76 distinct row-sets, 63 of exactly two
rows and 13 of three or more. The top 20 sets cover 409 of the 523, which is 78 percent, so
the job is small even though the line count is not.

```
 65  Allium sativum | garlic          19  peppercorn | white pepper
 64  Allium sativum | garlic clove    18  butter | food paste
 45  Coriandrum sativum | cilantro    17  cow's milk | whole milk
 39  black pepper | peppercorn        14  broth | chicken broth
```

⚠️ Earlier notes said "about 508". The measured figure at `460cae5` with seg0-core is
**523**. The older number predates the depluralize and normalize fixes and the anchor rule.

The anchor rule added to this pile: **2 duplicate canonicals** (`gnocchi`, which collides
with a hand-authored row, and `vermicelli`) and **28 more names carried by two or more
rows**, 34 new against 6 resolved. Seven of the 34 point a pork-cheek name at `pipe rigate`.
None carries a recipe line today.

**The merge operation does not exist and is refused in three places**, each on purpose:
`build_library.py:812` (a rename onto another row's canonical is a merge and needs a
person), `build_library.py:1074` (the 19 "as food" stems), and `build_library.py:1390`
(14,791 marked second-primary names stay, because deciding which entry keeps the row is a
merge question, not a rule).

### Named mixes, decided

Mixes always get rows. A recipe's own version supersedes the library version in the panel.
The description carries the origin. **The panel mechanism is unbuilt** and is downstream of
decision 4.

### Dry pasta is an ingredient, decided and shipped

Settled, and `460cae5` acts on it. Recorded in `pasta_rule`'s docstring with the head-to-head
against Q2625877 "type of pasta" and against two hops.

## The pile

Cheap or known, recorded so it is not lost.

### From the add-on-save build

- ⚠️ **No Postgres coverage for any of the eight commits.** `tests/test_pg_integration.py`
  names none of the new code: not the search route, not the save gate, not the delete path.
  CI's green Postgres job means **the schema applies and the old paths still work**, not that
  the new features are proven there. The `ilike` fix in `5f2aacd` exists *because* Postgres
  behaves differently from SQLite, and nothing has ever run it on Postgres.
- **The Postgres loader, deferred by decision.** `build_db.py` is raw-SQLite by design and is
  never run against PG, so the Alembic revision creates `library_names` there and nothing
  fills it. An empty table self-disables the feature, which is why deferring was safe.
- ⚠️ **A PROMOTED-ROW CURATION TOOL, and it is bigger than "edit a description".** A
  promoted row has `descr` and `pairs` NULL and **no path in the app or the build can ever
  fill them**. It has no `seed.py` entry either, so the one working authoring surface does
  not reach it. The 36 hand-authored rows can only be edited by changing `seed.py` and
  rebuilding, which does propagate (`seed_content`'s upsert names `descr` and `pairs`,
  proven on a database copy).
  **Three symptoms share one root.** The lowercase name, the null `descr` and the null
  `pairs` are not three problems. They are one: *a promoted row is uncurated*. They all
  resolve at the same moment, which is when somebody curates the row. So scope the tool as
  **curate a promoted row** (name, description, pairings, possibly season and regions), not
  narrowly as a description editor. Scoping it narrowly is how the capitalization question
  turns back into a transform nobody should write.
  ⚠️ **It is coupled to stage 8, and the sequencing is an unmade decision.** The picker
  PRODUCES the uncurated rows this tool exists to fix. Shipping the picker first means
  accumulating rows nobody can tidy. Shipping the tool first means building an editor for
  rows that do not exist yet. Pairing them is a third option. Nobody has chosen.
- **The 36 seed descriptions are model-written boilerplate.** 15 to 26 words, 32 of 36 in
  exactly two sentences, 28 of 36 opening with an article, every `pairs` field on the same
  three-to-five-item template. 13 carry a semicolon and 16 an em dash, both of which the
  style guide bans. The facts inside them are often good and specific. The shape is the
  problem. Rewriting is content work in `seed.py`, whenever. Full text in
  `previews/seed-ingredient-descriptions.csv`.
- **`ingredient_slug()` lives in `app.py`**, so build-time code cannot import it without
  importing the Flask app. Fine for its two current callers, wrong for the third. Move it to
  a shared module when one appears.
- **`openpyxl` is missing from `requirements.txt`.** Pre-existing, found while placing the
  generator. `build_library.write_sheet` imports it inside the function, so a machine without
  it loses the review sheet. The lookup file is written before the sheet for that reason.

- **Wrapped-line hand-edit.** Paprika exported about 6 lines pre-split, and the detector for
  them is 18 percent precise, so auto-rejoining corrupts more than it fixes. **Hand-edit,
  not a build.** 4 of the current 32 misses are this damage: three `freshly ground black`
  lines that lost "pepper" and one bare `powder` that lost "instant coffee". Both
  `black pepper` and `instant coffee` are index keys, so all four would resolve. This is
  also the source of the 4 ingredient losses that killed the clause strip.
- **`depluralize` follow-ups**, found while fixing `bc38181` and not fixed:
  `chillies` to `chilly` and `chilies` to `chily` (the `-ies` branch), `molasses` to
  `molass` (the `-sses` branch), `species` to `specy`, `series` to `sery`.
- **True-absence hand-adds.** Aliases for rows that exist: `eschalot` (shallot has a row,
  and so does Echalion), `tumeric` (a misspelling of turmeric), `Parm` (Parmesan). Names
  with no Wikidata item at all: `tubetti`, `rigati`. Absent mixes: furikake, adobo, Old Bay
  and the rest. Mis-mapped mixes: `baharat` on the abstract `spice` row, `bumbu` on
  `condiment`, `sazon` on `sofrito`.
- **A `hand_removals`-style list for bad names**, seeded with the 4 firing redirect defects
  and the 19 confirmed cross-concept names.
- **⚠️ The out-of-corpus coverage test, never run.** The library's real job is other
  people's imports. Every coverage number in this document uses the 298-recipe corpus as a
  proxy for that, and the corpus is one household's cooking. Testing against ingredient
  lists from cuisines the corpus does not cover, Ethiopian and Peruvian and Filipino, is a
  genuinely different measurement and would probably move the numbers a long way.

### Drawer design, a deliberate pass and explicitly not bug-fix scope

Stage 7 made the drawer honest. It did not make it good. Two blocks are thin by design
rather than by accident, and both are a design job rather than a fix.

- **"Where it grows" wants a map.** Today it is a flat tag list, and rows carry up to four
  regions. A clickable map with the list collapsed to the top three would say more in less
  space, and region is the one field where a picture beats words outright.
- **"Pairs well with" wants to be more than a comma list.** Today it is one sentence of
  prose in a single `pairs` column. Chips, or links through to those ingredients' own
  drawers, would make the field guide navigable rather than terminal. ⚠️ Note the schema
  cost: `pairs` is free text, so linkable pairings need the names resolved to ids, which is
  the same linking problem this whole document is about, pointed at a different column.

### Trivial cleanups

- **`.season-none` in `styles.css:1479` is dead CSS.** Nothing has rendered that class since
  `622a6a0` removed the year-round line. One rule to delete, left alone rather than folding
  a CSS change into a JS commit.

## The remaining build plan

**Stages 1 to 7 are shipped. One remains.**

- **Stage 7, the drawer fixes. ✅ SHIPPED in `622a6a0`.** All four panel blocks hide when
  empty. The curation tool that was pencilled in here did NOT ride with it, and it grew in
  the process: see the pile.
- **Stage 8, the picker. THE SWITCH, and the only thing left.** A typeahead over
  `/api/library/search`, replacing the `<select>`. ⚠️ **Nothing a user does reaches the create path until this exists**, because
  the current picker's `<option value>` comes from `/api/ingredients`, which returns only
  already-promoted rows, so the client literally cannot express an un-promoted library row.
  Worth splitting into "the shared search control" then "adopt it at both call sites"
  (`.ed-link` in the edit form and `.linksel` in inline edit), since shipping one leaves two
  inconsistent pickers.
- **Stage 9, DROPPED.** Step-link promotion. See the architecture notes above.

## What died, so it is not resurrected

- **The line-split "fix".** The importer does not split lines. The Paprika export contains
  `'3 tablespoons instant coffee'\n'powder'` verbatim, so those 6 lines arrived pre-split
  from the source. `paprika_native_reader.py:68` splits on newline and that is correct.
- **Prep-clause demotion through `_PREP`.** `_PREP` is a 24-word presence search with no
  notion of position (`import_cleanup.py:106`). It detects prep *state*, not purpose
  clauses, and it fires on none of the seven trailing-clause failures. It is also
  preview-only, consumed at `import_cleanup_preview.py:54` and nowhere else.
- **The junk-keys library cleanup.** 79,362 one-word index keys lack English provenance,
  but only 65 of them occur in the corpus. Foreign function words are in the index by
  design. The matcher retires them, not a library edit.
- **"green pepper" to peppercorn as a bug.** It is a legitimate homograph. Green pepper is
  the vegetable and the unripe peppercorn, and both rows are real.
