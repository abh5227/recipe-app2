# Open library queues

A **living register** of what is known-wrong or known-unfinished in the ingredient library, and where
the detail sits. Items get added when a read finds them and struck when they close. This is not a
dated snapshot. [reconciliation-2026-08.md](reconciliation-2026-08.md) is one, and it stays that way.

⚠️ **This file exists because none of these queues has a committed home.** The detail lives in
`previews/library-audit.xlsx`, `previews/library-duplicate-scan.xlsx` and `preview/entries-v3/`, and
all three are gitignored. Lose the machine and the queues go with it. So this is a pointer, not a
re-analysis: what is open, how big it is, and which artifact holds the rest.

**Opened 2026-08-31**, after the fold (`178dfae`), the commonality tier (`86bb61e`) and the browse port
(`dd89a05`, `1253206`, `fe8f7d1`). The catalog is **10,515 kept rows** at that point.

---

## 1. The commonality tier is in the file and not in the database

`build_library.mark_commonality` gives every kept row one of **staple, common, everyday, speciality or
obscure**, and `write_library_names` writes it as a third column. **The `library_names` TABLE is still
two columns, so the app cannot query the tier.**

`build_db.seed_library_names` reads its two fields by name through a `DictReader`, which is what lets a
three-column file load into a two-column table without error. Nothing is broken, and nothing is
available either.

Closing it needs a numbered migration plus an Alembic revision. ⚠️ **`build_db.py` never runs against
Postgres** ([migration-plan.md](migration-plan.md)), so the PG side needs its own answer rather than
falling out of the same change. Deferred deliberately, not overlooked.

## 2. Library correctness

The fold closed the twelve pairs the charter settles, where a Latin binomial stood beside the
common-name row it names. It closed nothing else.

- **118 duplicate pairs remain**, where one row's English name is another row's canonical and the two
  share at least two names. **7** are binomial-shaped without a Latin tag, **111** are plain English.
  ⚠️ **Direction is settled by no rule for any of them**, and several are probably two ingredients
  rather than one row duplicated (`cassava` and `tapioca`, `meat` and `fresh meat`, `bacon` and
  `Speck`). The detector points the wrong way on `cookie` and `biscuit`, and on `whole-wheat flour` and
  `wholemeal flour`, where the charter's US-English rule says the left side wins. **A review queue, not
  a defect list.**
- **297 lone rows** carry a common English name with no sibling row to fold into, the shape
  `Tamarindus indica` has. These need a rename rather than a fold.
- **5 entry pairs need merging by hand**, where both rows carry a developed entry:
  `coriandrum-sativum` with `cilantro` (now on one row, `Q65523167`, exposed by the fold),
  `peppercorn` with `black-pepper`, `cassava` with `tapioca`, `ground-beef` with `minced-meat`, and
  `cookie` with `biscuit`.
- **`tamarind`, `lemongrass` and `chile_powder`** have no catalog row that slugifies to the seed id.
  `green_onion` is a naming mismatch against the catalog's correct `scallion`.

Detail: `previews/library-duplicate-scan.xlsx`, four tabs, gitignored.

## 3. Sourcing has barely started

⚠️ **UPDATED 2026-09-02. The paragraph below describes the STUBS, and it is still accurate about them.
What changed is that sourcing has now started.** Twenty entries across five batches are drafted,
harsh-verified citation by citation, and have had their recorded fixes applied. They carry real
resolvable URLs, which is the thing this section says does not exist.

**They are NOT in `preview/entries-v3/` yet.** They live outside the repo in `Library/sourced/`, and
integration is a separate step that has not run. So every count below still holds for the stubs on
disk. The architecture that produced them is in [sourcing-pipeline.md](sourcing-pipeline.md).

The 142 entries in `preview/entries-v3/` carry **220 claims**, of which **185 are GENERATED** stubs with
`source_class = inference`, **32 CURATED** and **3 CITED**. **102 claims are `unresolved`.**

⚠️ **No citation resolves.** 22 entries carry a `[[claims.chain]]` block naming 35 source slugs
(`pubmed-24266426`, `legifrance-decret-88-1204-art-2`), and **no registry maps a slug to a reference**.
**0 of 142 entries contain a URL.** `review_state` is `unreviewed` on all 142. Even the 3 CITED claims
name their authority only in prose, with no citation field.

The tiers, gates and axes these are judged against are in [sourcing-tiers.md](sourcing-tiers.md).

Detail: `previews/library-audit.xlsx`, four tabs, gitignored.

## 4. Known limits that are accepted rather than open

Recorded so they are not re-discovered as bugs.

- **Commonality mis-tiers a specific form of a common thing.** `light brown sugar` holds 0 variation
  names, `Shaoxing wine` 0, `light soy sauce` 9, while their parents hold hundreds. Fixing it properly
  means parent-child inheritance, which is the unbuilt gap in [parent-child-gap.md](parent-child-gap.md).
  A shallow version would be worse than the miss.
- **`n_variations` measures how many languages named a thing**, not kitchen frequency, so `sumac` and
  `gochujang` read everyday.
- **Neither the binomial shape test nor the Latin language tag is complete.** Shape finds 864 rows at
  low precision, the tag finds 121 and is right about them, and `Tamarindus indica` carries no Latin tag
  at all. The duplicate scan therefore keys on the defect (two rows, one ingredient) rather than on
  either test.

## 5. The pilot batch needs a citation re-check

**The nine pilot entries were verified before the source-routing discipline existed.** The routing card
and the rule that a citation must point at a page someone actually opened both came later, so the pilot
was judged against a weaker bar.

**Two instances found, both fixed.** `all-purpose-flour` and `milk` each cited the FDA major-allergen
page at `read_depth = "full"`. That page is bot-blocked and returned 404 to the fetcher on two separate
attempts, so nobody in the loop had opened either one. **Both are re-routed to the statute itself at
Cornell LII**, under one shared slug, so they now agree with the `flour` entry sourced later. **Zero
chain URLs across the 23 sourced drafts point at fda.gov.**

⚠️ **Both swaps lost something, and both losses are recorded rather than hidden.** The old `taken` on
`all-purpose-flour` said the FDA page defines gluten. The statute does not, so the gluten half of that
flag is now uncited. The old `taken` on `milk` said foods containing it must declare it. That duty lives
in 21 USC 343(w), not in the section cited. Neither flag's shipping text depends on the lost half, and
both are flagged in their discussions for a reviewer.

**The other seven pilot entries have NOT been swept**, and the two found were found by scanning for one
domain. They should be checked for citations pointing at bot-blocked or otherwise unopenable pages, by
resolving every URL rather than by pattern-matching a host. **Not yet done.**

⚠️ **The general shape is worth naming, because it will recur.** A batch verified under an older
standard is not re-verified when the standard tightens. Nothing in the pipeline re-opens finished work,
so each tightening leaves a layer of entries judged against the old bar. **This is the first such
layer.**

## 6. Standards decisions pending

Two cases where **two conventions are on disk and one of them is wrong**, so every sourcing batch
re-litigates the question and the answer comes out differently depending on who drafted. Both were
flagged rather than guessed each time, which is correct handling that does not converge. Until the rule
is written once, every batch pays the same cost.

### 6a. The `n` convention

[sourcing-tiers.md](sourcing-tiers.md) defines it in one line: "**n.** Sample size where it means
anything. Five labels is a sample. One blog is an assertion."

**The corpus does not follow it.** Measured across the sourced drafts, four different meanings are in
use:

```
coriander-seed.toasting_moves_the_aroma   n = 19   19 commercial oils. A real sample size.
cilantro.soap_is_genetic                  n = 1    Eriksson 2012, 14,604 participants. A study count.
coriander-seed.not_the_leaf               n = 2    The same Eriksson study PLUS 19 and 28 oils.
ginger.acid_sets_protein_and_slows_...    n = 0    Three mechanisms, no common sample.
oyster-sauce.reduction_not_extract        n = 2    Two sources. A source count.
```

⚠️ **The sharpest case is one study counted two ways.** Eriksson et al. 2012 is `n = 1` in cilantro and
part of `n = 2` in coriander seed. Same paper, same URL, same slug, two numbers.

**What needs deciding.** Sample size of what, the study's participants or the number of sources. How a
claim resting on several sources that each measure a different mechanism counts. Whether `0` means
absent or measured-and-none, since a field with no meaning arguably should not be present.

**Once decided**, four claims need correcting to match, and any batch drafted before the decision
carries the old reading.

### 6b. The prose-tier convention

Flagged in `preview/categories-v1/_FORMAT-NOTES.md` and never settled. Two entries
(`entries-v2/gochugaru.toml`, `entries-v3/besan.toml`) tier prose `curated` over `generated` claims,
while the five category entries tier prose `generated`, which is what the standard says.

**The two rules.** Prose follows the claims in its `derived_from` list, which is what the sourced drafts
do and what two fix passes enforced on `cumin`, `white-pepper` and `cumin-seeds`. Or prose is
`generated` unless separately traced, which is what the standard says.

**They disagree on the same file.** Prose derived from one `curated` and one `generated` claim is
`curated` under the first rule and `generated` under the second.

**What needs deciding.** Which rule holds, and if it is the first, whether prose takes the best or the
weakest tier among its claims. Weakest is more conservative and matches how tiers cap elsewhere.

⚠️ **If the standard's reading wins, the fix-pass changes were corrections in the wrong direction** and
need reverting.

## 7. Parent-child linking, starting with the flour family

**A plan and a dependency. NOT a blocker on sourcing.**

The general `flour` row (`Q36465`) holds the name "all purpose flour" and **37 recipe lines** that
belong to its child `all-purpose flour` (`Q95388739`). Its own row diagnostic states it: "The general
term wins the lookup and then answers with the wrong specific."

**Sourcing flour is not blocked by this.** Flour's description is valid whatever the lookup does. What
flour is, how protein grades work, why a bag rarely states it, none of that changes. **The routing
defect is a separate problem with a separate fix**, and holding the content hostage to it buys nothing.

**The plan.** Source the family's content as ordinary batches, all-purpose flour being done already.
Then link parent to children. Then fix the routing so a line naming a specific grade reaches that grade.

⚠️ **DEPENDENCY: the mechanism does not exist.** The closest operation is the **fold**, and a fold
merges **duplicates**, two rows that are one ingredient. That is the wrong operation here. **Flour and
all-purpose flour are two different ingredients**, both correct and both wanted, and folding them would
destroy one. See [parent-child-gap.md](parent-child-gap.md), whose own first surfacing is this shape.

**So the linking is deferred until that mechanism exists.** Sourcing the content is not deferred.

**What is already moving toward it.** The `possible_parent` marker, a one-line observation a sourcing
chat drops when its ingredient looks like a specific form of a broader one, with verification curating a
**proposed** structure from the accumulated markers. That accumulates the evidence without building any
of it. See [sourcing-pipeline.md](sourcing-pipeline.md).

⚠️ **This is probably not only flour.** Do not enumerate the other families now. Derive them against the
catalog when the mechanism is built. Two are already known: Wikidata says **kosher salt** is a kind of
**table salt**, where the cook's parent is the authored `salt` row that no automatic edge can reach, and
**black pepper and white pepper** both carry `peppercorn` as a superclass.
