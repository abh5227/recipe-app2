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

## 6. ADOPTED: prose-claim consistency

⚠️ **ADOPTED 2026-09-02, as option (c), both.** It is a chat self-check in **operator brief v1.14**
section 6, and a verification step in `previews/verifications/README.md`. **No longer open.**

**An entry's prose may not assert a mechanism that no claim carries.** Every mechanism stated in the
description must have a backing claim, with that claim's tier and chain.

**This recurred across batches**, which is why it reached this register rather than staying in a single
verification record.

- **lemon juice.** The prose said bottled juice has "none of the smell". The claim said the same and was
  false, and **fixing only the claim would have left the false version in the text a reader actually
  sees.** The verification record for that batch flagged it in capitals for exactly that reason.
- **buttermilk, onion powder and za'atar**, all three entries in one batch. Buttermilk's prose asserted
  baking-soda leavening and tenderizing with no claim behind either. Onion powder's asserted a fact
  about onion salt. Za'atar's asserted that sesame makes the mix cling and that sumac makes it sour,
  where the entry's own discussion admitted the chain did not support those mechanisms.

**Two of those four are now fixed by sourcing the mechanism rather than cutting the sentence**, which is
the better outcome where a source exists. **The pattern is what needs a decision, not the instances.**

**Why it matters more than it looks.** The claims carry the tiers and the citations, and the prose is
what ships to a reader. **A mechanism that lives only in prose has no tier, no source and no falsifier,
and nothing in the pipeline checks it.** It reads exactly like the sourced sentences beside it.

**What settled it.** A batch run on a deliberately bare prompt, with no inline steering at all, carried
**nine of ten** loads on the strength of the brief, tracker and card alone. Safety routing around a
blocked host, the corpus check, named give-ups, a cuisine escalation and a self-caught contradiction all
fired unprompted.

⚠️ **The single load it dropped was this one, in 2 of 3 entries.** It was also the only rule on that
list **not written in the brief.** Every rule that was written was followed. The one that was not was
broken. **That is the argument, and it is why the fix was a rule rather than a prompt.**

**Adopted as (c), both**, because **(b) alone is weak**: a chat writing prose from its own claims is the
party least likely to notice it drifted, which is the same reason the draft-and-verify split exists.
The self-check catches the obvious cases and the verifier catches the rest.

⚠️ **One form of it is worth naming separately.** In that batch the prose stated a finding from a paper
the batch had itself listed as a blocked host it never opened. **Citation by osmosis.** The tell is
prose that is stronger than the chain beneath it, and both the brief rule and the verification step
call it out by name.

## 7. Standards decisions pending

Two cases where **two conventions are on disk and one of them is wrong**, so every sourcing batch
re-litigates the question and the answer comes out differently depending on who drafted. Both were
flagged rather than guessed each time, which is correct handling that does not converge. Until the rule
is written once, every batch pays the same cost.

### 7a. The `n` convention

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

### 7b. RESOLVED and IMPLEMENTED: the prose-tier convention

**Decided 2026-09-04. The block-level tier is gone and prose is tiered PER PIECE.**

The question was which of two rules held. Prose follows the claims in its `derived_from` list, or
prose is `generated` unless separately traced. They disagreed on any sentence drawn from one `curated`
and one `generated` claim.

**The answer is the first rule, and the tier is the WEAKEST of the claims a piece names.** Weakest is
the conservative direction and it matches how tiers cap everywhere else in the pipeline.

**The block-level `tier` and `body` fields are DELETED.** A description is now a list of
`[[prose.piece]]` entries, each carrying its own `text` and its own `derived_from`. The tier is not
written down at all, it is derived: an empty `derived_from` makes the piece `generated`, one key makes
it that claim's tier, several make it the weakest of them.

**The measurement that settled it.** Over the 213 sentences in the corpus at the time, **80, or 38
percent, carried the wrong tier under the block model.** 41 sold higher than their evidence and 39
sold lower. That is not a rounding problem, and it is invisible while a paragraph shares one number.

**Where it is now implemented, so this is not a paper decision:**

- All 56 sourced entries are converted. 230 pieces, none on the old shape.
- `migrations/032_library_entries.sql` gives `library_prose_pieces` a `derived_tier` column.
- `library_loader.py::derive_tier()` computes it on load and refuses a `derived_from` that names
  nothing in the entry.
- The operator brief documents the shape in section 6, as of v1.18.

**The earlier warning here, that the fix-pass changes on `cumin`, `white-pepper` and `cumin-seeds`
might need reverting, is withdrawn.** Those passes applied the rule that won, so they were corrections
in the right direction and they stand.

## 8. Parent-child linking, starting with the flour family

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

---

## 9. Wheat, gluten and the allergen statute

**Three items, all surfaced by verification of batch 11 on 2026-09-03, all deferred rather than fixed.**
They share one cause: **21 USC 321 is the corpus's single allergen source and it does less than the
corpus assumes.** The routing card was updated to v3 to stop the pattern spreading. **These three are
the existing instances, and none is fixed.**

### 9a. Five source slugs for one URL

`https://www.law.cornell.edu/uscode/text/21/321` is cited by **twelve safety flags across ten entries**
and carries **five different `source` slugs**:

```
5 x  us-fdca-21usc321-major-allergen     all-purpose-flour, buttermilk, flour, milk, zaatar
2 x  usc-21-321-qq-allergens             ice-cream (both flags)
2 x  cornell-21usc321                    oyster-sauce (both flags)
2 x  fda-major-allergen-21usc321         semolina, whole-wheat-flour  -> FIXED, see below
1 x  cornell-lii-21usc321                cumin
```

**Every batch names it fresh, because no chat can see its siblings.** This is the concrete instance of
the general no-registry problem in section 3, and it is worth recording separately because it needs no
registry to fix. One URL, one agreed name.

**Decided and applied:** the corpus form is **`us-fdca-21usc321-major-allergen`**, the plurality at five
uses, and it names the Act rather than the agency. **Batch 11's two entries were corrected to it**, and
the routing card v3 now names it so chats stop inventing variants.

⚠️ **Five flags in three entries are still off-slug**, in `ice-cream`, `oyster-sauce` and `cumin`.
**Deliberately not fixed.** They are outside batch 11's blast radius, they are mechanical, and a
normalization pass over the whole corpus is the right shape rather than a drive-by edit during an
unrelated verification.

### 9b. The gluten clause is uncited on three entries

**Verified by reading the statute in full.** The word **gluten** does not appear in 21 USC 321. Neither
does celiac disease. It names wheat among the nine major allergens and stops.

| entry | flag text says gluten | chain establishes it |
| --- | --- | --- |
| `flour` (rank 71) | yes | **no, and nothing says so** |
| `semolina` (rank 124) | yes | no, **caveat now recorded** |
| `whole-wheat-flour` (rank 127) | yes | no, **caveat now recorded** |
| `all-purpose-flour` (rank 8) | yes | no, **caveat recorded 2026-08-31** |

**Nothing here is false.** Wheat flour contains gluten. **The chain does not carry it**, and gluten is
the half a celiac reader is reading for.

`all-purpose-flour` found this itself and wrote the warning into its own `taken`, with the instruction
to "either trace it or scope the flag text to wheat". **That knowledge went nowhere**, and three more
entries have since made the same statement. Batch 11's two now carry the same caveat, following that
precedent.

⚠️ **`flour.toml` (rank 71) is the remaining untreated instance.** From batch 6, outside batch 11's
blast radius. **Not fixed.**

**What still needs deciding, once, for all four.** Either a source is traced that establishes gluten in
wheat, which would let every wheat flag state it properly, or the flag texts scope to wheat and gluten
moves to prose where it carries no citation weight. **Four entries currently ship a true sentence their
chains do not support.**

### 9c. Is `also = "gluten"` the convention?

**One entry uses it.** `all-purpose-flour` carries `also = "gluten"` on its flag alongside
`allergen = "wheat"`. **No other entry in the corpus has an `also` field at all**, including the three
other wheat entries that name gluten in their text.

**So the same fact is represented two ways**, in a structured field on one entry and in prose only on
three others. **Neither is wrong and they are not the same thing**, which is the reason to decide rather
than let it drift.

**What needs deciding.** Whether `also` is a real field in the schema, and if it is, whether it takes
non-allergens like gluten at all, given that the `allergen` field is defined against the statutory list
of nine and gluten is not on it. **Blocked on nothing except a decision.**

---

## 10. Verified does not mean permanently immune

**Recorded 2026-09-06, after the same thing happened in two consecutive bulk passes.**

| newer entry | exposed a defect in | what it was |
| --- | --- | --- |
| `wheat-tortilla` | `flour`, `all-purpose-flour`, `semolina`, `whole-wheat-flour` | those four state gluten on a chain that is only 21 USC 321, which does not contain the word. The tortilla scopes its flag to wheat and never claims gluten. See section 9b |
| `pepperoni` | `bacon` | bacon bundled the IARC processed-meat finding with nitrosamine formation under one key and a `hazard` field naming only the second, with `n = 1` against two attached chains. Pepperoni filed the IARC finding alone under `hazard = "processed_meat"` |

**In both cases a later entry did the same job more cleanly, and the comparison is what made the older
defect visible.** Neither was found by re-reading the old entry, and neither would have been found
without a newer one to hold it against.

⚠️ **A VERIFIED stamp means checked once, against what was known then and against what existed
then.** It does not mean the entry is finished. As the corpus grows, later entries cover ground earlier
ones already covered, **and every one of those overlaps is a free re-audit of the older entry.**

**This does not argue for re-verifying the corpus on a schedule**, which would cost more than it
returns. **It argues that the cross-entry reconciliation step has a second purpose that is worth as
much as its first.** The usual reason for it is stopping a new entry contradicting an old one. **The
second reason is that the new entry audits the old one, and that only happens if the reconciliation
reads both rather than checking the new work on its own terms.**

**Both defects above are fixed.** The four gluten entries in 9b are not, and they are the standing
instance of this shape.

## 11. Eighteen base words the catalog has no row for

**Recorded 2026-09-14, from the dish facet build.** The dish model's `base` facet resolves a word
to a catalog `library_id` before storing it, so a word with no row stores nothing. 128 of the 146
base vocabulary words resolve. These 18 do not.

⚠️ **This is a queue, not a cut list, and it is not a proposal to admit anything.**
`docs/what-the-library-is-for.md` governs what gets admitted and nothing here overrides it. The
dish keeps every other facet and simply carries no base row, which is a true statement about the
catalog rather than a silent drop.

| word | recipes losing a base facet | what is actually wrong |
| --- | --- | --- |
| turkey | 19,016 | no row in `library_names` |
| mushroom | 18,682 | no row |
| pecan | 17,713 | no row |
| cherry | 15,188 | no row |
| caramel | 12,308 | no row |
| crab | 11,725 | no row |
| lasagna | 9,730 | no row |
| artichoke | 7,255 | no row |
| quinoa | 3,942 | no row |
| sprout | 3,230 | no row |
| pistachio | 3,019 | no row |
| oat | 2,892 | the row is `oats`, and the matcher does not reach it from the singular |
| polenta | 2,143 | no row |
| tortellini | 2,080 | no row |
| rib | 1,442 | the row is `ribs`, same as `oat` |
| gnocchi | 1,407 | **two rows**, `Q20063` and a bare `gnocchi`, so the match is ambiguous |
| gelatin | 1,043 | no row |
| calamari | 490 | no row |

**133,305 recipes in total.** Three different problems are mixed together above and they want
different answers.

**15 are genuinely absent.** A catalog of 10,474 rows has no turkey and no mushroom.

**2 are present under their plural only.** `oats` is `Q24265484` and `ribs` is `Q7322430`. The
linkage matcher finds neither from the singular form. This one is a matcher question rather than
an admission question, and it is the cheapest of the three to answer.

**1 is a duplicate.** `gnocchi` has both a Wikidata row and a bare-string row, so it resolves to
two candidates and the matcher declines. That is a catalog cleanup, not a gap.

⚠️ **This list arrived independently of the one already in `docs/mining-decision.md`, and they
overlap.** That document records a wide brand heuristic that was tried and rejected, and the top
of its false-positive queue was "pecans, hamburger, pimento, cherries, mayo and crabmeat, every
one a real food the catalog lacks." Pecan, cherry and crab are on both lists. Two unrelated
measurements finding the same holes is stronger evidence than either one alone.

## 12. The dish floor is 2 on purpose, and the junk in it is deferred work

**Recorded 2026-09-15, when the dish floor was lowered from 10 to 2.**

⚠️ **A reader who finds `ahmad rashad banana pancake` stored as a dish will think the floor is
broken. It is not. This section is why.**

### What the floor does

`mined_dish` stores a dish when the corpus names it at least twice. At 10 it held 19,002 dishes and
covered 48.5% of the corpus. At 2 it holds roughly 159,500 and covers 68.1%.

### Why 2 rather than 10

**Thin dishes are elevation hooks.** A dish this corpus barely names is often a real dish somewhere
else. Measured against the owner's own 298 recipes, these sit below 10:

```
mongolian chicken 8 · agedashi tofu 9 · beef bulgogi 9 · cilantro chutney 8 · toum 6
khichdi 5 · larb 5 · matar paneer 4 · kuku paka 2 · mejadra 2 · chana chaat 2
```

Every one is a real dish. None is junk. They are thin because an English-language web corpus
under-names them, which is the same limit
[what-the-library-is-for.md](what-the-library-is-for.md) already records and the reason recipe-line
count is banned there as a cut signal.

**`source_slug` is in every mined primary key**, so a second source adds rows rather than
overwriting them. A real regional dish gains recipes across sources and rises. **A dish kept at 2
today is a row a future source can elevate. A dish cut today is gone and cannot be.**

### Why the junk is tolerated rather than filtered

The floor also admits one-offs, `ahmad rashad banana pancake` and `mary jane bean pot soup` being
the shape. Three reasons they stay for now.

**It is boundary-safe.** A row at n=2 is an aggregate over two recipes. Boundary (c) forbids n=1 and
this floor never admits one. The cell floor on profiles is separately `n >= 3 OR (n >= 2 AND share
>= 10%)`, so no stored cell rests on a single recipe either.

**Measured, it is rarer than it looks.** Sampling 3,000 dishes per band with the loader's own
refusal test, the rate of a stored role-word name is **0.00% at every band down to n = 2**, and
0.10% at n = 1. The loader accepts the whole n >= 2 set without refusing a row.

⚠️ **The filter that would remove it does not work.** A probe written to catch bare personal names
matched `memphis style pork ribs`, `spanish style fish` and `ethiopian style samosa`. **A filter
that cannot tell a cuisine from a person would cut exactly the dishes the floor was lowered to
keep.** Guessing now is worse than waiting.

### ⚠️ The deferred plan, and the evidence it waits for

**After a second and third source, junk becomes identifiable without guessing.** The query is
already supported by the schema:

> a dish that is still `n = 2` **and still present in only one `source_slug`** after N sources have
> landed is proven unelevatable, and that is evidence rather than a guess.

A real regional dish appears in an Indian or Filipino source and rises. A person's one-off appears
nowhere else, ever. **Cutting on that evidence is defensible. Cutting on a name heuristic today is
not.**

### ⚠️ This is a bet, and the bet is on sources that do not exist yet

**The payoff needs real additional corpora.** Until one lands, the thin rows sit there doing
nothing, taking storage and adding noise to a browse that sorts by `n` anyway. **If no second source
ever arrives, the floor should go back up rather than the junk staying forever.**

That is the honest shape of it. The cost of being wrong is a larger table. The cost of cutting early
is the regional dishes, and those do not come back.

## 13. The class B alias review: refusals, pending items, and two queued categories

**Recorded 2026-09-15.** Class B's top 150, ranked by corpus impact, was read one row at a time.
**109 aliases were loaded** into `library_aliases` from `hand_aliases.csv`. What follows is what
was NOT loaded, so a later pass does not re-propose it.

### Refused outright, 24 rows

Reasons are in `previews/alias-b-review.md`. The largest was **`whipping cream` to
`crème fraîche liquide`, 22,004 recipes**, which is the second-largest alias in the class and
wrong. Bulk-loading class B would have written it.

### Refused with a reason to come back, 4 rows

| alias | proposed | recipes | status | what unblocks it |
| --- | --- | --- | --- | --- |
| `greens` | leaf vegetable | 343 | **pending-recipe-check** | Southern US usage often means collards. Read what the corpus recipes mean before deciding |
| `Soybean paste` | miso | 19 | **pending-cuisine** | means miso in Japanese and **doenjang** in Korean. Same class as `black bean` and `pawpaw` |
| `rice sticks` | bánh phở | 76 | **needs a parent row** | the alias is backwards, a generic pointed at a specific. Wants a generic `rice noodle` row with `bánh phở` under it |
| `Niçoise` | Cailletier | 55 | **refused** | also the salad, the style and the sauce. Too ambiguous to alias to the olive |

⚠️ **The pending-cuisine list now has three members**: `black bean`, `pawpaw` and `Soybean paste`.
All three need a cuisine fact the catalog does not carry. Revisit together.

### Queued as a category, not an alias, 2 rows

`salad greens` (847 recipes) and `leafy greens` (54) were proposed as aliases of `leaf vegetable`
and **should be a parent category instead**, with the specific greens as children. This is a
hierarchy-structure task rather than a naming one, so it is queued here and not built.

**Blocked on the same thing as section 11's general-term gaps:** a parent needs to exist before
children can point at it.

### Held on a dependency, 1 row

`pak choi` (58 recipes) is an accept, **retargeted to the new `bok choy` row rather than to
`Chinese cabbage`**. That row does not exist yet, so the alias is held rather than written to the
wrong target. It loads with the new rows.

### Held for provenance, 6 rows. ⚠️ Wikibooks checked 2026-09-15 and does NOT source them

`ground round`, `red currant jelly`, `mentaiko`, `spring cabbage`, `Tape` and `sprout` were
approved as rows and held back because **their only source entry is the row they would split
from**, so each would ship with one name and no provenance. `authored_rows.csv` warns against
exactly that shape.

**Wikibooks was proposed as their provenance and measured. Zero of six hold up.** No Cookbook page
and no `Recipes using X` category for any of them. `Cookbook:Sprout` exists but is a
**disambiguation page** saying the word may mean Brussels sprouts, bean sprouts or germinated
seeds. `Tape` reaches only a recipe for one Indonesian dish.

⚠️ **The sprout result may be telling us to refuse rather than to source.** Wikibooks calling the
term ambiguous is the same signal as `neep` and `meal`, which `linkage_matcher.DROPPED` refuses on
purpose.

**Registering Wikibooks as a source is still licence-clean** (CC-BY-SA-4.0, `share_alike=1`, the
same shape as `wikipedia_redirect` and `wiktextract`, both already ingested) and recording that an
ingredient exists is a fact with attribution rather than republished recipe prose. **It is simply
not justified by these six**, since it supplies nothing for them. If it is registered it should be
for the 1,880 recipes and 10,174 human tags the validation used.

### RESOLVED 2026-09-15: five created unsourced, sprout refused

**The five real ones were created bare and MARKED.** `ground round`, `red currant jelly`,
`mentaiko`, `spring cabbage` and `Tape` are rows with an empty `seed` and an empty `sources`
column, so `build_library` records them as **"authored by hand, no source"** and they ship
**GENERATED** per `docs/sourcing-tiers.md`. Each `reason` in `authored_rows.csv` states outright
that no source we hold names it and that Wikibooks was checked on 2026-09-15 and had nothing. The
catalog is honest about them rather than quietly unsourced. **5,548 recipes.**

⚠️ **`spring cabbage` relates to `cabbage` (Q14328596), not to the binomial.** The edge is in
`hand_links.csv` and `library_relations` went 10,192 to 10,193.

**`sprout` is REFUSED, not created.** It is in `linkage_matcher.DROPPED` beside `meal`,
`blood pudding` and `neep`. ⚠️ **It was nearly given a row on the strength of 3,230 corpus recipes
and 23 existing sprout specifics.** `Cookbook:Sprout` settles it the other way: a disambiguation
page reading *"the term sprout is an ambiguous term that may refer to: Brussels sprouts, Bean
sprouts, Sprouted (germinated) seeds."* Three foods, no safe target. **Refusing costs 3,230
misses. A row would have cost 3,230 wrong matches.** `bean sprout` still resolves EXACT, so the
refusal is on the bare word only.

### RESOLVED 2026-09-15: sources.db register synced

First flagged 2026-09-06. **`recipenlg` AND `recipe1m` both read `declined` while
`build_sources_db.py` declared them `derive_only`.** Both now match the builder, license,
attribution and decision_reason included.

⚠️ **It needed a table rebuild, not an UPDATE.** The live CHECK read
`status IN ('ingest','declined')` and predated `derive_only` entirely, so the register could not
hold the value the builder had been declaring. The 5.18 GB of fetched entry and label data was not
touched. Register is now 9 ingest, 5 declined, 2 derive_only.

**This unblocks registering any new source**, Wikibooks or the India dataset, which could not have
been recorded correctly against the old constraint.

## 14. Class A applied, and the hierarchy work it leaves behind

**Recorded 2026-09-16.** 147 candidates reviewed, ranked by corpus impact over all 2,231,142
recipes. **44 aliases applied**, `library_aliases` 110 to 154. **No row added, renamed or merged.**

### The 11 refusals

`Amaretto` (1,670 recipes), `pastry` (566), `soy` (237), `raw` (78), `dairy` (14), `tartar` (9),
`cut` (3), `buffer` (2), `salt, pepper` (1), `varietal` (0), `celebrity` (0).

⚠️ **Four of the eleven are in `linkage_matcher.DROPPED`, and the split is deliberate.**
`amaretto`, `pastry`, `soy` and `tartar` are words a cook really writes with a target that is
**wrong rather than missing**, so a later pass could re-propose them. The worst is `tartar`: a
baking line means **cream of tartar** and the only near row is `tartar sauce`. **The other seven
are not food words at all** and live here instead, because `DROPPED` exists for food-word
ambiguity and adjectives would bloat it. Verified after the change: `cream of tartar`,
`pastry flour` and `soy sauce` all still resolve EXACT.

### The 3 real unset, resolved. All three are NEEDS-PARENT

| word | Andy's note | catalog evidence | ruling |
| --- | --- | --- | --- |
| `Rabbit` | "rabbit is the parent" | 6 children: rabbit blood, breast, broth, filet, liver, milk | **needs-parent, no alias** |
| `tenderloin` | "tenderloin is a parent of those other" | 3 children: pork tenderloin, raw lean pork tenderloin, raw ostrich tenderloin | **needs-parent, no alias** |
| `ranch` | "ranch as parent, ranch dressing and ranch style as children" | ⚠️ **0 children. Only `ranch dressing` exists** | **needs-parent, with a caveat** |

⚠️ **`ranch` is not the same shape as the other two.** Authoring `ranch` as a parent gives it
exactly **one** child until someone also authors `ranch seasoning` and `ranch style`. Those rows
do not exist in the catalog. The parent is defensible and it does not yet have a family.

### Queued for the parent pass: 17 rows, 108 child edges

**The alias fixed the NAME. The children are separate authoring and were not touched.**

```
  mushroom    -> edible mushroom    ⚠️ NO PARENT   23 children waiting
  fiber       -> dietary fiber      ⚠️ NO PARENT   20
  pistachio   -> pistachio nut      up: nut        11
  cheddar     -> Cheddar cheese     up: cheese     10
  quinoa      -> quinoa seed        up: grain       9
  cashew      -> cashew nut         up: nut         9
  mozzarella  -> mozzarella cheese  up: Italian cheese  8
  horseradish, porridge, artichoke, balsamic, macadamia, pecan,
  raclette, Romanesco, straw, side                              17 rows, 108 edges
```

⚠️ **Five of the 17 have no parent of their own**, so those are chains rather than single edges.

**The parent pass therefore holds:** these 17 rows and 108 edges, plus `rabbit`, `tenderloin` and
`ranch` as new parent rows, plus the 31 restructures and the 4 mushroom and amaranth collision
rows from the canonical diagnosis, plus the 79 missing general terms with 1,211 children.

⚠️ **Superseded by section 16, which is the complete inventory.** Two more items joined after this
was written: the 11 Latin restructures and the 5 folded-in renames. **Read section 16, not this
paragraph.**

### Still open after this

- **The rename batch**, roughly 54 rows after the `PART` reclassification. ⚠️ See
  `previews/rename-batch-sample.md`: worth only 6,806 recipes and it resisted four filters.
- **The Latin reading list**, 31 confirmed plus 225 to filter. Read, never batched.
- **`broth`**, still deferred pending a re-mine.

## 15. The read-through passes: decided, and what folds into the parent pass

**Recorded 2026-09-16. Documentation only, nothing applied. `recipes.db` unchanged at `07b4fbd4`.**

Both batches were read whole rather than sampled, and both collapsed. **80 rename candidates gave
4 worth applying. 36 Latin rows gave 1 rename.** Neither justifies a rebuild of its own, so the
survivors fold into the parent pass, which is rebuilding anyway.

⚠️ **A count correction against `previews/read-through-passes.md`.** That file says 38 renames and
42 rejects. Re-reading with your four refusals folded in gives **42 renames and 38 refusals**,
because `cat`, `bat`, `seal` and `game` moved to refuse, and `kutha meat` and `sheep tail meat`
moved with them on a second look. `kutha` names a slaughter method and `sheep tail` names a cut.

### REFUSED, 38 rows. Recorded so nothing re-proposes them

| reason | rows | recipes | members |
| --- | --- | --- | --- |
| ⚠️ **sausage-meat mis-parse** | 7 | **2,617** | `pork/chicken/fish/beef/veal/partridge/roe-deer sausage meat` |
| **a texture or a state** | 16 | 1,180 | `boneless`, `lean`, `minced`, `boiling`, `fatty`, `salt-cured`, `cultured`, `fermented`, `mystery`, `junk`, `PSE`, `precooked chicken`, `white chicken`, `minced lamb`, `kutha`, `sheep tail` |
| **a word collision** | 4 | 15 | `cat`, `bat`, `seal`, `game` |
| **a taxonomic class** | 6 | 11 | `bird`, `camelid`, `cetacean`, `crocodilian`, `reptile`, `mollusc` |
| **the qualifier is load-bearing** | 3 | 13 | `wild duck broth`, `wild boar haunch`, `wild boar's back` |
| **a region** | 1 | 6 | `Sicilian meat` |
| **not Latin** | 1 | 0 | `Common pandora` |

⚠️ **The sausage-meat seven carry 2,617 recipes, more than half the batch's value, and the rule
that produced them never had a chance.** `sausage meat` is its own catalog row, `Q995566`,
distinct from `Sausage`. `pork sausage meat` is pork forcemeat, not "pork sausage" plus a
redundant word.

⚠️ **`wild boar is not boar` and `wild duck is not duck`.** Stripping `wild` changes the animal.

### ⚠️ DROPPED from the Latin list: six rows that are not Latin, and the lesson

`Common pandora`, `Himo tougarashi`, `Horikawa gobo`, `Kawachi bankan`,
`Neapolitan papaccella`, `Shishigatani kabocha`.

⚠️ **A CAPITALISED TWO-WORD PHRASE IS NOT A LATIN-BINOMIAL TEST. This is the third time that
shape has fooled a test in this project.**

```
  1st  a bare-first-name probe caught 'memphis style pork ribs' and 'ethiopian style samosa'
       -- cuisine STYLES read as personal names. That result was voided.
  2nd  a binomial regex scored 6% precision, flagging 'Abertam cheese', 'Adzuki bean',
       'African cherry' and 'Albert sauce' -- ordinary English phrases.
  3rd  these six -- Japanese and Italian vegetable and fish names, plus an English fish.
```

**Any future binomial detection must use STRUCTURE, not capitalisation.** What worked here was
capitalised genus plus a **lowercase specific epithet that is not a shared English head noun**,
validated against Wikidata `P225` ground truth at 96% recall. ⚠️ **Even that scored badly on
precision alone**, so the reliable signal was structure **and** a taxon property on the row, which
is why the evidenced set is 36 and the structure-only set of 220 is not a reading list.

### DEDUP QUEUE: lovage

⚠️ **`Ligusticum officinale` is lovage, and `lovage` already exists as a separate row,
`en:lovage`.** Two rows, one concept. **A merge is refused** because it destroys an id and
`mined_dish_ingredient`, `mined_dish_base` and `mined_pairings` hold ids. **This needs a proper
dedup pass** that decides which id survives and what happens to the other's references. Not
forced, not renamed, recorded here.

### No action needed: 5 Latin rows already solved

`Colocasia esculenta` carries `taro`, `Triticum spelta` carries `spelt`, `Eisenia bicyclis`
carries `Arame`, `Dioscorea polystachya` carries `nagaimo`, and
`Brassica oleracea var. palmifolia` carries four kale names. **The plain word already resolves.**
A rename would change only what displays, so it is cosmetic and is not queued.

## 16. THE PARENT PASS: the complete inventory

**Recorded 2026-09-16. Everything real now converges here.** Four separate diagnoses have each
ended by queueing work for this one pass, so this section is the whole of it in one place. Nothing
below is built.

### A. Rows to CREATE

| what | rows | note |
| --- | --- | --- |
| `rabbit` | 1 | Andy: "rabbit is the parent". 6 children waiting |
| `tenderloin` | 1 | 3 children: pork, raw lean pork, raw ostrich tenderloin |
| `ranch` | 1 | ⚠️ **a parent of ONE.** Only `ranch dressing` exists. `ranch seasoning` and `ranch style` are not in the catalog |
| the 79 missing general terms | up to 79 | `broth` (91 children), `powder` (68), `fat` (62), `protein` (59), `paste` (55), `leaf` (45) |

⚠️ **`broth` is the largest and is separately blocked.** Splitting it needs a re-mine, because
`Q275068` carries `broth` as its Wikidata **label** with `stock` only an alias, and the row holds
124 dish cells, 787 pairings and 96 edges. **The corpus text needed to split those is discarded by
the mining boundary.** Do not create `broth` as part of a bulk parent pass.

### B. Edges to AUTHOR

| what | edges | note |
| --- | --- | --- |
| the 17 class A rows with children waiting | **108** | ⚠️ **5 have no parent themselves**, so those are chains |
| the 31 restructures from the canonical diagnosis | ~31 | plain word is a genuine parent |
| the 4 collision rows | 4 | `mushroom` twice, `amaranth` twice. A collision proves the parent |
| **the 11 Latin restructures** | 11 | below |
| the 79 general terms' children | **1,211** | only once the parents in A exist |

**The 11 Latin restructures, each one species under a plain word that ALREADY has a row:**

```
  Prunus domestica                    -> plum      Q12372598
  Sparus aurata                       -> bream     Q17767599
  Penaeus monodon                     -> shrimp    Q1517781
  Dioscorea polystachya               -> yam       Q8047551
  Brassica oleracea var. palmifolia   -> kale      Q45989
  Saccharomyces pastorianus           -> yeast     Q45422
  Capsicum annuum var. glabriusculum  -> chili pepper  Q165199
  Acheta domestica                    -> cricket   Q124801245
  Alphitobius diaperinus              -> mealworm  Q124801111
  Citrus sulcata, Citrus voangiala    -> citrus    Q81513
```

⚠️ **That is the `Cancer pagurus` shape eleven times over**, and none of them is a rename. The
parent exists, the child exists, the edge does not.

⚠️ **`Glycyrrhiza uralensis` wants a `licorice` parent that does NOT exist**, so it belongs to
list A rather than here.

### C. Renames to FOLD IN

**Five, and they are folded in rather than run alone because a standalone full-catalog rebuild
for 644 recipes is not worth it.**

| current canonical | becomes | recipes |
| --- | --- | --- |
| `duck meat` | duck | 356 |
| `quail meat` | quail | 227 |
| `capon meat` | capon | 27 |
| `poultry meat` | poultry | 34 |
| `Nephelium lappaceum` | **rambutan** | 0 |

**The qualified form stays as an alias on the same row in every case.** Ids do not move.

⚠️ **The other 38 renames are deferred as low value**, 620 recipes across 38 rows, almost all
animals this corpus never cooks. `zebra meat`, `pangolin meat`, `wapiti meat`. **They are not
refused, they are not worth a rebuild.** If the parent pass is rebuilding anyway they can ride
along at no extra cost, which is a decision for whoever runs it.

### D. What this pass must NOT do

⚠️ **No merges.** `mined_dish_ingredient`, `mined_dish_base` and `mined_pairings` hold
`library_id`. A rename moves a display name and a restructure adds a row beside an existing one,
and **neither deletes an id**. A merge does, and would orphan the staged dish data in
`recipes-preview.db`. **The `lovage` duplicate in section 15 is exactly this and is queued
separately for a dedup pass that can decide it properly.**

### E. Scale

```
  rows to create        3 now (rabbit, tenderloin, ranch) + up to 79 general terms
  edges to author     ~154 now (108 + 31 + 4 + 11) + 1,211 once the general terms exist
  renames to fold       5 (+38 optional)
  hierarchy coverage  61% today -> 85% if every absent source edge is also loaded
```

⚠️ **Do not justify this pass with the extraction recall figure.** Measured in
`previews/missing-links-diagnosis.md`, every edge added raises the random-profile null nearly as
fast as it raises the score. **The case is catalog correctness.**

## 17. Stage 1 of the source re-harvest, loaded. What it left behind

**Recorded 2026-09-16. Loaded into `recipes-preview.db` only, which went `7948aa75` to `9863927d`.
`recipes.db` is untouched at `07f8712c`.**

**1,488 edges from Wikidata `P186` and `P361`, the two axes that were empty.** `made_from` 4 to
1,463 and `part_of` 0 to 29. **Every edge was read before loading**, 1,479 individually and 112
classified by parent. Specs in `previews/reharvest-scoping.md`, `stage1-corrections.md` and
`madefrom-full-read.md`.

⚠️ **10 edges were loaded CORRECTED rather than as the source stated them**, and each carries its
reason in `hand_links.csv`. Six inverted `part_of` claims became `made_from` in the right
direction, three organ rows were retargeted from `fish` to their species, and `chrain` moved from
`root vegetable` to `horseradish root`.

### HELD FOR STAGE 2: 25 edges, corrections already decided

⚠️ **These are real facts on the wrong axis. They are `kind_of` or `part_of`, so they belong with
the kind_of stages rather than with the two empty axes.** The correction is done and recorded here
so stage 2 does not re-derive it.

**From the part_of set, 13.** Four need the direction flipped as well as the kind.

```
  iguana meat kind_of lizard meat        ⚠️ direction flipped
  puffin meat kind_of bird meat          ⚠️ direction flipped
  whale meat kind_of cetacean meat       ⚠️ direction flipped
  poultry kind_of bird meat              ⚠️ direction flipped
  Tupí kind_of Spanish cheese            black tea kind_of tea
  side dish kind_of dish                 Emmental kind_of Swiss cheeses
  fruit kind_of fruits and vegetables    vegetable kind_of fruits and vegetables
  cereal legume kind_of cereals and pseudocereals
  Crimson Bramley kind_of Bramley        Bon Rouge kind_of Williams' bon chrétien
```

**From the made_from set, 12.** Ten to correct and two that need nothing.

```
  Istarski pršut kind_of prosciutto      Njeguška pršuta kind_of prosciutto
  schnitzel Pavlišov kind_of schnitzel   speculaas biscuit kind_of speculaas
  speculoos biscuit kind_of speculoos    crayfish as food kind_of crayfish
  golden raisin kind_of sultana          golden yellow raisin kind_of sultana
  fermented milk product kind_of fermented milk    raw fish kind_of fish
  cut of beef part_of beef               cheese wheel part_of cheese
  ⚠️ chocolate ice cream and vanilla ice cream already carry kind_of ice cream.
     Their made_from edges were refused and need no correction.
```

### ⚠️ THREE BAD ROWS, queued separately. These are rows, not edges

| row | problem | queue |
| --- | --- | --- |
| `ozonated oil` | ⚠️ **a cosmetic and medical product, not a food.** It carried two made_from edges, both refused | **row removal**, beside `drinking straw` |
| `Hellman's Real Mayonnaise` | ⚠️ **a BRAND row** carrying a made_from edge | **brand guard** |
| `drinking straw` Q189211 | tableware, already flagged in `previews/parent-pass-scoping.md`, and the class A pass gave it the alias `straw` | **row removal** |

**Removing a row is not a rename and not a merge, and it is the one operation in this area that
can orphan the staged dish data. It is queued rather than done.**

### What stage 1 refused, so nothing re-proposes it

**112 dropped mechanically.** 70 `made_from table salt`, checked one by one for a real
salt-as-primary case and none found, plus 42 with a catch-all parent (`meat` 12, `vegetable` 9,
`fruit` 7, `spice` 6, `cereal` 5, `condiment` 3). ⚠️ **`flour` at 42 and `milk` at 36 were
deliberately kept.** They are general and real.

**20 refused by name.** 14 made_from (an enzyme, bee anatomy, two cosmetic-oil edges, a chili-oil
confusion, a false claim about pastry flour, five vague parents, and two whose `kind_of` already
exists) and 6 part_of with no real relationship underneath.

**6 redundant inversions dropped.** `almond part_of almond milk` and five like it, where the
correct `made_from` direction is already in this same load. **The source stated those facts twice,
correctly under `P186` and inverted under `P361`.**

### ⚠️ A process note worth keeping

**`load_relations.py` takes no `--db` argument. It hardcodes `DB = "recipes.db"` at line 25.**
Passing `--db recipes-preview.db` is silently ignored and the load goes to LIVE. It happened once
in this pass and was caught immediately by a hash check, and live was restored from
`backups/recipes-20260916-134317.db` with zero loss. **The working call is
`load_relations.load(db=...)` from Python, not a command-line flag.** The same is true of
`load_aliases.py`.

## 18. The inclusion rule, and the row cleanup it settles

### The rule

**Does a person consume this?** That one question is now the library's admission test, recorded in
[what-the-library-is-for.md](what-the-library-is-for.md). It is deliberately broader than the
"cooking ingredient" wording it replaces. Tea and tisane botanicals, coffee, herbal and eastern
medicine taken by mouth, and beverages are all in. Out is anything a person does not consume at all,
meaning events, programs, places, companies, taxonomic ranks, functional-class labels, industrial
and non-ingestible chemicals, and label-parse fragments.

### What the rule did to the 462 cleanup candidates

| Verdict | Rows | |
|---|---|---|
| **KEEP** | 78 | the rule rescues them from the narrower reading |
| **QUEUE** | 24 | the rule does not settle them, they need a read |
| **REMOVE** | 360 | confirmed not consumed |

The 78 keeps break down as 35 branded products, 23 short words the read proved are real consumables
in another language, 10 consumed medicinals, 9 bare element names and 1 object. Three of those
groups are worth stating because a cooking-only rule would have cut them:

- **Branded products are consumed.** `Hellman's Real Mayonnaise`, `Mrs. Dash`, `Yakult`, `Guinness`.
  Whether a brand should be a row's canonical name is `brand_guard.py`'s question, not this one. A
  company, `Kalleh Dairy`, is still out.
- **Swallowed medicinals are consumed.** `castor oil` is an oral laxative, `linctus` is a cough
  syrup, `quinine` is in tonic water, `Drakshasava` is a drunk Ayurvedic tonic, `Pharmaceutical
  glaze` is shellac on both tablets and confectionery.
- **A bare element name is the substance, not a functional class.** `calcium`, `iodine`,
  `Magnesium`, `Fluoride` and five more are consumed nutrients and stay. `Minerals` and `Other
  nutritional substances` are class labels and go.

### The 85 additive rows split exactly as the rule predicts

All 85 are function labels (`gelling agent`, `anticaking agent`, `raising agent`) and all 85 are out.
The consumables they name are separate rows that were never candidates and are untouched: `gelatin`,
`fruit pectin`, `citrus pectin`, `lemon pectin`, `apple pectin`, `soya lecithin`, `baking soda`,
`cream of tartar`.

### Phase 1, applied to the copy

119 rows removed. Clear-not-consumed, zero references anywhere, one source entry each, so the drop
removes the row rather than renaming it.

```
I additive class labels  44    aerating agent, coating agent, meat curing agent, ...
H label fragments        30    no1..no12, n°, Exxx, E15x, FD&C, complet, de fer, monosodique
G classifier labels      20    18 Russian GOST and OKPD product classes, Brotgetreide, Kochfischware
A not consumed            8    manufacture of ice cream, Livsmedelstillsatser i Sverige, Kaga yasai
D industrial              6    Hair Bleaching Agents, tooth bleaching agents, veterinary beta-agonist
E ornamental koi          6    Kōhaku, Showa, Tancho, Asagi, hi utsuri, Shiro Bekko
J abstract classes        2    Other nutritional substances, cooking ingredient
K techniques              2    hot water kneading, rimming
F objects                 1    cookie decorating kit
```

The decision is durable in `hand_removals.csv` as 119 `drop` rows keyed on `(anchor, id)`, 80
wikidata and 39 off_taxonomy. The file now holds 362 decisions, 143 of them drops. The copy went
`aea10240` to `f7baed74`. Live `recipes.db` was not touched.

⚠️ **The copy edit and the hand-file are two separate things, and only one of them is proven.** The
119 rows were deleted from the copy directly. `build_library` has not been run, so the claim that
these 119 `drop` rows reproduce this exact result through a build is reasoned, not measured. The
reasoning is that each row sits on exactly one source entry, which is the case where a drop cannot
leave the row standing under another id.

### What is still queued

**Phase 2, 84 rows.** Zero references, but several source entries behind each, so a drop may remove
some names and leave the row standing under a different id. Needs a dry-run build to tell which.
The worst are `dish` at 81 entries, `Clupea` at 53, `diet` at 43 and `side dish` at 40.

**Phase 3, 157 rows.** Referenced, so the references come first. Inside it:

- `Guinness` is a real consumable **and** is linked from your Shepherd's Pie. It is a keep.
- `Miracle Whip` is the row behind the standing red boundary test. Both it and `Guinness` are
  authored rows with no source entry, so `hand_removals.csv` cannot reach either one.
- `Trapani salt ponds`, `Swiss cheeses` and `Citrus` are parents. Their children need re-pointing
  first, `Swiss cheeses` to `cheese`, `Trapani salt ponds` to a salt row.
- `semi-sweet` (256 recipes) and `sharp` (136 recipes, all macaroni cheese) are fragments matching
  correctly against truncated label text. They want `fold` onto `semi-sweet chocolate` and a cheddar
  row, not `drop`.

**24 reads the rule does not settle.** 18 are genus rows that are taxonomic ranks and also real
culinary groupings (`Citrus`, `Ribes`, `Pleurotus`, `Laminaria`, `Penicillium`). The other 6 are the
consumption edge itself: `croton oil` twice (a purgative that is an acute toxin), `turpentine` (a
folk remedy that is a solvent), `Charas`, `zinc oxide` (a fortificant and a sunscreen), `emu oil`
(a supplement and a topical) and `sepiolitic clay` (a filter aid removed before eating).

**The non-food recipes in the corpus, unrelated to row admission.** 172 mined dishes over 1,601
recipes are household or cosmetic, led by `play dough` at 528, `dog biscuit` at 89 and `lye soap` at
42. `baby oil` and `turpentine` were linking to them correctly. Removing the rows hides the symptom
and leaves the corpus as it is.

## 19. The row cleanup, finished

Phases 2 and 3 applied to the copy along with the edge reads and the genus ruling. The catalog went
`10,371` to **`10,123`**, and the copy went `f7baed74` to `db07d0c9`. Live `recipes.db` was not
touched at any point.

### What was applied

| Operation | Rows | |
|---|---|---|
| **Drops** | 241 | Phase 2's 84 less one now folded, Phase 3's 146, the 6 edge-read rows, the 4 fish genera, and the 2 re-pointed parents |
| **Folds** | 7 | names and links move to the row that answers for them |
| **Re-points** | 4 edges | children moved to a real parent before their old parent was cut |
| **Keeps confirmed** | 19 | present and absent from every removal verdict |

The folds, with the links measured after the move:

```
sharp                     ->  Cheddar cheese          111,233 recipes  (111,103 + 136 - 6 co-occurring)
semi-sweet                ->  semi-sweet chocolate      5,870 recipes  (5,617 + 256 - 3)
non-nutritive sweetener   ->  sweetener                 1,745 recipes  (236 + 1,509 - 0)
nutritive / bulk / intense / high-intensity sweetener -> sweetener     (no corpus rows to move)
```

`sweetener` stays as a row. The merged recipe counts use inclusion and exclusion, so a recipe holding
both the fragment and its target is counted once rather than twice.

The re-points:

```
Emmentaler Switzerland, Gros-de-vaud, fromage de Bagnes   kind_of   -> Swiss cheese (Q4117114)
Menola salata PAT                                         made_from -> Sale Marino di Trapani PGI
```

The `in_category swiss-cheeses` edges on the same three cheeses were left alone, since a category id
is not a library row. The Menola edge was wrong on its own terms before this, since a salted fish is
made from salt rather than from a salt pond.

### Three traps the work hit, all caught before they landed

**⚠️ A fold must not move edges.** `sharp` carried `kind_of flour`. Moving its edges to the target
would have written `Cheddar cheese kind_of flour` into the catalog. The five sweetener variants
carried `in_category sweetener`, which would have become a self-loop on their own target. Edges are
deleted with the folded row, which is also what `build_library.apply_folds` does, since it moves
names and nothing else.

**⚠️ `mined_pairings` is canonically ordered and has a unique key.** All 362,319 rows satisfy
`a_id < b_id`. A fold has to re-normalize the order after moving an id, merge on the roughly 493 key
collisions rather than overwrite, and delete the self-pair that appears when a fragment already pairs
with its own target. `mined_substitution_candidates` carries a second unique index,
`(from_id, ifnull(to_id,''), source_slug)`, which a first attempt violated and rolled back on. Two
self-referencing substitution rows were dropped for the same reason.

**⚠️ Cutting a fold target resurrects its sources, and only the verifying build found it.** A
PHASE C collision merge had folded duplicate `binder` and `croton oil` rows into the rows this pass
then cut. A fold whose target is cut is refused, and the duplicate comes back as a live row. The
first verifying build produced 10,125 against the copy's 10,123 and named both. They now take the
same ruling as the rows they used to fold into. **A candidate set built from `library_names` cannot
see already-folded rows, so dropping any fold target needs this check.**

### The verifying build

The whole accumulated state reproduces from the hand files, which is what makes the copy a
description of the decisions rather than a hand-edited artifact:

```
verifying build 10,123    copy 10,123
  in build but not in copy  0
  in copy but not in build  0
  canonical drift           0
  folds refused             0
  removals dangling         0
```

`hand_removals.csv` now holds 610 decisions, 386 drops, 166 variation trims and 58 folds.
`hand_links.csv` lost 188 edge lines whose row went away and carries the 4 re-points.

Verified after the apply: 0 new orphans, the 247 unresolved parent ids still the category ids by
design, 299 recipes and 3,563 ingredient lines intact with `Guinness` still linked to the Shepherd's
Pie, the 36 curated rows untouched, cook log at 134 and ratings at 118, integrity ok and the foreign
key check clean. Both suites run at 1,296 Python and 154 JavaScript, with the one standing
`Miracle Whip` boundary failure that reads live `recipes.db` and is unrelated to this work.
