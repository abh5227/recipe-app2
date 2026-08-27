# Ingredient linkage: where the work stands

Written 2026-08-27 at `460cae5`. Every count here was re-derived from the repo, from
`recipes.db` read-only, or from the `previews/` CSVs at the time of writing. Where an
earlier figure was quoted from memory and disagreed with the measurement, the measurement
won and the difference is noted in place.

**The one-line state.** The library is built and the matcher works. Nothing links. 50 of
3,332 ingredient lines carry a stored `ingredient_id`, and the matcher that could raise
that to about 3,300 has no committed home and nowhere to write. That second half is a
decision, not an engineering task, and it is recorded under "The gate" below.

## What is committed, and not pushed

Six commits ahead of `origin/main`, zero behind. Nothing pushed. `recipes.db` was never
written by any of it and holds `83cd7be8e837beb1a53e2e54ce0a326106ef5f8b03dc38f8d2e107765dcfd9d7`
throughout.

| commit | what it did |
| --- | --- |
| `4fee4a0` | `docs/what-the-library-is-for.md`, and the cut rules point at it. The standing purpose test for admitting, cutting, renaming or merging a row. |
| `7b3c74c` | Tracks `seed_links.csv`, the 50 seed-recipe ingredient links. This is the whole of the stored linkage. |
| `f7644ea` | `depluralize` mangled the `-ves` words, `cloves` to `clof`. Cost 46 recipe-line matches. Fixed with a word list. |
| `974c66d` | `normalize` deleted diacritics rather than folding them, `jalapeño` to `jalape o`. Dropped accented ingredients. NFD, not NFKD, and not `build_join`'s NFKC. |
| `bc38181` | `depluralize`'s `ss/us/is` guard blocked real plurals whose singular ends in `-i`. `zucchinis`, `chilis`. Fixed with `I_PLURAL`, a membership set, because the shape is genuinely ambiguous. |
| `460cae5` | Rule 5, the pasta-parent anchor. Admits a Wikidata item that names Q178 "pasta" as a direct superclass, one P279 hop. Plus `bagel` as override number six, filed as a new class C. |

## The matcher

**It has no committed home.** It lives only in the session scratch directory as
`LINK.py`, `GAPS.py`, `FEED.py` and about forty other files. None of those paths exists in
the repo. Confirmed at the time of writing by looking for them. **If the scratch directory
is lost, the matcher is lost** and only the `previews/` CSVs survive as a record of what it
produced. Giving it a home is one of the things gated on the decision below.

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

## The open decisions

### ⚠️ Decision 4 is the gate

**Where a stored link lives.** Three options.

1. **An `ingredient_links` table keyed by Q-id.** The leaning. Additive, touches no serving
   path, and the library keeps its own identifiers.
2. **Load the library into the 36-row `ingredients` table.** Changes the drawer and the
   picker, because those read that table today.
3. **Stay a report.** The matcher output is a CSV that nobody's code consumes.

**Nothing downstream ships until this is answered**, and that is why it is the gate. Four
things sit behind it: the merge tool, the mixes panel, the autochecker, and the matcher
having a committed home at all. Every one of them needs to know what a link *is* before it
can be written.

### The merge job, gated on decision 4

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
