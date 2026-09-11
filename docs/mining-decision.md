# Mining a recipe corpus for facts

The standing decision about reading a large recipe corpus for **facts**, and the boundaries that
reading stays inside. Read this before writing any code that touches a scraped corpus.

**Status: IN FORCE from September 10, 2026, by the owner's decision.** The boundaries below govern
any code that reads the corpus. The legal reasoning is the position the owner has adopted. It was
drafted for him and he has taken it as his own.

**Going in force does not make this legal advice, and it changes nothing in the legal section.** No
lawyer has reviewed this project. The review-before-ship gate stands, and sections 4 and 6 are the
two to put in front of counsel first.

**Boundary (g) now has its test.** `test_mined_facts_carry_no_brand_names` exists and is proven
to refuse a mined row holding a mark while passing a generic food in the same column.
**Extraction is no longer blocked by (g).** Every boundary in this document is now machine
checked.

## What this decides

Ingredient data worth having does not exist as a licensed dataset. Pairings, substitutions and what
an ingredient is actually used for are all patterns across many recipes, and no vocabulary carries
them. The decision is to read a large corpus for those patterns, to keep only what the reading
produces, and to keep nothing of what was read.

This reverses an earlier position. `source_catalogue` recorded RecipeNLG and Recipe1M+ as declined
on license, before coverage, under a license-first rule. That rule was right and stays. What it
conflated was two different questions, and the split is the point of this document.

- **May this source's data be redistributed?** Still no, for both corpora. Nothing from them ships.
- **May statistics be derived from it?** The question the earlier decline never asked separately.

A source can be closed to the first and open to the second. `source_catalogue` now carries a
third status, `derive_only`, for exactly that case.

## The corpus

**RecipeNLG.** Roughly 2.2 million recipes with named food entities already extracted, published as
a single CSV by Poznan University of Technology.

It is chosen over Recipe1M+ for one reason that matters more than size. RecipeNLG is a **direct
download**. Recipe1M+ publishes image URLs and expects the user to scrape the recipe sites
themselves, which is a boundary crossing before any work starts. Downloading a file someone else
published is not the same act as crawling the sites it came from.

**Probe before ingest.** Every other source in `source_catalogue` carries a `probe_score` against
the ten collapse terms. These two say `not measured`, because the license-first rule stopped the
work before measurement. Measure coverage on a sample before committing to the full read, and
record the number. A corpus that does not cover the catalog is not worth the rest of the pipeline.

## The 10 fact types

Everything extracted is a fact, and everything stored is an aggregate across many recipes. Nothing
in this list is particular to one recipe.

1. **Co-occurrence and pairings.** How often two ingredients appear in the same recipe, against how
   often each appears alone. Lift over the corpus.
2. **Substitutions.** That one ingredient is offered in place of another, counted across recipes.
3. **Generic dish type.** That a recipe is a soup, a braise, a loaf. The functional category, never
   the title.
4. **Cooking method.** Roasted, simmered, fried, raw. Which methods an ingredient appears under.
5. **Aggregate proportions.** Typical ratios between ingredients, across many recipes. Never one
   recipe's quantities.
6. **Core against optional.** Whether an ingredient is load-bearing for a dish type or a garnish,
   measured by how often it is present when the dish type is.
7. **Ingredient roles.** Acid, fat, aromatic, thickener, leavening. What an ingredient does.
8. **Cuisine tags.** Which cuisines an ingredient appears in, and at what rate.
9. **Prep techniques.** Minced, toasted, bloomed, brined. What is commonly done to the thing before
   it is cooked.
10. **Course and meal type.** Breakfast, dessert, side. Where an ingredient turns up in a meal.

## The boundaries, written to be testable

Each of these is a statement a test can check, not a promise in prose. The test named beside it is
what enforces it. A boundary with no test beside it is not yet a boundary.

**(a) Facts only, from ingredient lists and from notes and methods.**
Both fields are read. The ingredient list gives occurrence, co-occurrence and proportion. The notes
and method text give substitution, technique and method. Reading prose for a fact is allowed. What
comes out is the constraint, not what goes in.

**(b) A fact leaves the extractor as a structured tuple. The sentence is never retained.**
The extractor matches a pattern and emits a record of identifiers and numbers. `(substitution,
from=buttermilk, to=milk_plus_lemon_juice, n=1)` and not the clause it was read from. An extractor
that cannot express what it found as a tuple **drops it**. There is no debug mode that keeps the
sentence, because that is how this boundary fails.
*Enforced by:* `test_mined_tables_hold_no_corpus_text`.

**(c) Only aggregates across recipes are stored. Never a per-recipe reproduction.**
A count over many recipes is stored. One recipe's ingredient list is not. Proportions are the sharp
case. A ratio averaged over 900 recipes is a fact about the corpus, and one recipe's quantities
beside its ingredient names is that recipe. Every stored row carries an `n` of how many
recipes it was derived from, and a row with `n=1` is not an aggregate.
*Enforced by:* a minimum `n` on every aggregate table, set when the tables are built.

**(d) Generic dish type is a fact. The recipe title is expression.**
"Braised short rib" as a dish type is a functional label. "Grandma's Sunday Braise That Never Fails"
is someone's writing. The first is stored, the second never is.
*Enforced by:* `test_mined_tables_hold_no_corpus_text`, since a title can only be stored in a text
column.

**(e) Provenance is recorded on every fact.**
Each mined fact carries the corpus it came from and, where the corpus supplies it, the source recipe
URL. The label shown to a reader is the corpus plus the generic dish type, never the title. This
routes through `library_chains` and `library_sources` like every other citation, so a mined fact is
as checkable as a hand-read one.

**(f) No schema may hold a text column sourced from the corpus.**
The structural backstop under all of the above. Mined tables hold identifiers, integers, floats and
a provenance URL. They hold no free text. This is checked against `sqlite_master` rather than
trusted, and the test is written **before** the first ingest rather than after.
*Enforced by:* `test_mined_tables_hold_no_corpus_text` in `tests/test_mining_boundaries.py`,
which runs against **every** database the project owns. It first ran against the sources.db
fixture alone, which was the wrong one, since mined facts key on `library_id` and would land in
`recipes.db`. That version would have passed vacuously forever.

**(g) A brand name is never stored as a generic ingredient or a generic dish type.**
Recipe corpora are full of trademarks. Oreo, Cool Whip, Captain Crunch, Jell-O, Bisquick. A
trademark is not a generic label for a kind of food, and recording one as though it were is the
error this boundary exists to stop. Where an extracted ingredient or dish type is a brand, **no
generic fact is recorded from it**. It is not silently mapped to a nearby generic either, because
"Cool Whip" and "whipped cream" are not the same claim about what a cook used.
*Enforced by:* `test_mined_facts_carry_no_brand_names` in `tests/test_mining_boundaries.py`,
reading `brands.csv` through `brand_guard.py`. **(g) is now a boundary rather than an intention.**

The list is the authority and the heuristic never excludes. A name is blocked only if it is on
`brands.csv`. A name that merely looks like a mark is returned as `suspect`, which is a review
queue, so the default-is-keep rule in `what-the-library-is-for.md` holds. 24 marks across 57
surface forms, built from what the phase 2 probe actually found rather than from imagination.

⚠️ **Two names the probe called brands are deliberately absent from the list.** `oleo` is short
for oleomargarine, a generic term for margarine. `graham cracker` is a generic food and the mark
in that aisle is Honey Maid. Between them they were 9,016 of the 30,114 occurrences the probe's
heuristic flagged, 29.9% of it. Blocking either would have cut a real food, which is the exact
failure the default-is-keep rule exists to prevent. A test pins both open.

⚠️ **A wide heuristic was tried, measured and rejected.** "No word in this name is one the catalog
uses" reads like a brand detector and is a catalog-gap detector. It flagged 81 names whose top
entries were pecans, hamburger, pimento, cherries, mayo and crabmeat, every one a real food the
catalog lacks. A review queue that is mostly wrong gets ignored, and the one real mark in it is
missed with the rest. The narrow rules kept are a possessive shape and a trade word.

## The legal reasoning

**⚠️ A DRAFT, AND NOT LEGAL ADVICE.** This is the owner's working position. No lawyer has reviewed
this project. It records the reasoning he accepts for this bounded, local use, and it is why he
judges the use defensible rather than a guarantee that it is. Before any of this data ships in a
product other people use, the position should be read by someone qualified.

**What published legal writing was read.** Four IP attorneys answering a near-identical question
about scraping and republishing recipes. They are not this project's counsel and have never seen
it. Reading them changed the document in three ways. Sections 1 and 2 got stronger, because the
fact-against-expression reading is the settled part and they agree on it. Two things the document
had missed got sections of their own, Terms of Use at 5 and trademark at 6.

**⚠️ TRADEMARK WAS THE GAP.** Section 6 covers a body of law this document did not touch at all
before, and it does not run on the fact-against-expression reasoning the rest of it rests on. Read
section 6 before writing any extractor.

### 1. Facts and functional information are not copyrightable

Copyright protects creative expression. The words a writer chose, the headnote, the way a recipe is
told. It does not protect facts, and it does not protect functional information.

An ingredient list is a functional statement. It says what goes in and how much. That is generally
not copyrightable, and the expressive part of a recipe is the writing around it.

**This is the best-footed part of the whole document.** The US Copyright Office says plainly that a
mere listing of ingredients is not protected. Every one of the four attorneys read said the same
thing in their own words. A bare ingredient list with short functional directions is fact, and the
copyright sits in the creative expression around it, meaning the worded instructions, the headnote,
the story about the author's grandmother, the commentary. Nothing below rests on a novel reading.

What this pipeline takes is on the factual side. Which ingredients appear. How often two appear
together. That one thing is offered in place of another. The dish type, the cooking method, the
prep technique, the role an ingredient plays. All of it is true about the food rather than authored
about the food.

**The line is this. Extract what is factually true about the food. Never retain how the recipe was
written.** The extractor keeps the fact and discards the text it read the fact from. A fact that
cannot be written as a structured value is dropped rather than kept as a sentence.

### 2. An aggregate over a corpus is a fact about the corpus

One recipe's ingredient list, copied out, is that recipe's content. A count across many recipes is
not. It is a statistical fact about the corpus, and no single recipe in it states that fact. It was
derived rather than reproduced.

That is why only aggregates are stored and why `n=1` is excluded. A fact drawn from one recipe is
that recipe's content wearing a different shape. A fact drawn from thousands is a fact about the
pattern.

**No stored value identifies a recipe or lets one be reconstructed.** That is the test to hold the
schema to, and it is stronger than counting rows. Thin cells are the failure case worth watching.
An aggregate over three recipes with an unusual ingredient can point at those three recipes the way
a reproduction would.

The attorneys confirm the foundation this rests on rather than the aggregation step itself. They
say the ingredient list is fact. This section then argues that a count over many such lists is
further from the source again, not closer. That step is the owner's reasoning and not a quotation
of anyone's, so it is worth naming as the part of sections 1 and 2 that a reviewer should test.

### 3. Generic dish types are functional labels, creative titles are expression

"Chocolate chip cookie" is a label for a kind of food. So are stir-fry, soup, bread, braise. They
describe what the thing is, the same way an ingredient name does, and nobody authored them.

"Grandma's Sunday Braise That Never Fails" is somebody's writing.

The pipeline stores the generic type and never the title. Where a title can be reduced to a category,
the category is what is kept. **Where it cannot, no dish type is recorded at all.** Storing the title
because the reduction was hard is the one move that is not available.

### 4. On RecipeNLG's licensing, for this bounded use

RecipeNLG publishes no license statement, and it is built on Recipe1M+, which draws from copyrighted
recipe sites. That is exactly what `source_catalogue` recorded when it declined both corpora for
redistribution.

**That fact has not changed. The use has.** This pipeline does not redistribute the corpus and does
not reproduce any recipe in it. It derives facts and aggregates, stores only those, and holds no
recipe text at all, which is checked against the schema rather than promised. The corpus is
downloaded rather than scraped, it is read locally, and nothing from it is shipped.

The owner accepts the corpus for deriving facts under these boundaries, on the reasoning that
deriving uncopyrightable facts from a source is a different act from redistributing that source.

**⚠️ This section carries more risk than the three above it, and it is the one to take to counsel
first.** Sections 1 to 3 rest on a distinction between fact and expression that is long settled.
This one rests on a judgement about a specific corpus whose own licensing is unstated, and unstated
is not the same as permissive. A second opinion is worth having before anything derived from it
leaves this machine.

Reading the attorneys made this section riskier rather than safer, and three points are why.

**Unstated is not permissive**, which was already the wording here and is exactly how they put it.
Silence is not a grant.

**A recipe can be copyrightable depending on how it is written.** The fact-against-expression line
is settled, but where any particular recipe falls on it is a judgement about that recipe's text.
A corpus of 2.2 million of them contains both kinds, and no rule written here sorts them. Only
someone qualified can draw that line on a given text.

**All four said to consult counsel before operating a recipe site.** Four independent attorneys
reaching the same recommendation is the strongest signal in anything read. It makes the
review-before-ship step in the header a real gate rather than a polite formality, and it applies
the moment this becomes something other people use.

### 5. Terms of use are a different claim from copyright

A website's terms of use can forbid scraping and copying by contract, whatever copyright says about
the content. Breaching that is a contract claim, and it stands on its own. The attorneys flag it as
a live risk for anyone crawling recipe sites, and they are right that it does not care whether the
material is fact.

**This pipeline does not scrape.** It reads a CSV that Poznan University of Technology published for
download. No recipe site is visited, no terms of use are presented, and nothing is agreed to. The
risk the attorneys describe attaches to the act of crawling, and this project does not perform that
act.

That distinction is real and it is worth stating plainly, because it is the clearest point in the
owner's favor anywhere in this document. It is also narrow. It says nothing about whether the
dataset's own compilers were entitled to publish what they published, which is section 4 and is
unchanged by any of this.

### 6. ⚠️ Trademark, and this is the gap

**Everything above this point is about copyright. Trademark is a different body of law and none of
the reasoning above reaches it.** This document did not cover it at all until now, and it is the
single largest thing the original scaffold missed.

Recipe corpora are thick with brand names. Oreo, Cool Whip, Captain Crunch, Jell-O, Bisquick, Old
Bay. They appear in ingredient lists and they appear in dish names. They are marks owned by
somebody, and the fact-against-expression argument has nothing to say about them, because a
trademark is not protected as expression in the first place. It is protected as an indicator of who
made a thing.

Two of the four attorneys raised this without being asked. One raised publicity rights alongside it.

**What it means for this pipeline.** An extractor that treats "Cool Whip" as a generic ingredient is
recording a mark as though it were a kind of food. A dish type surfaced as "Oreo cheesecake" carries
someone's mark into this project's own output, where it would sit beside hand-written prose and read
as this library's word for a thing. Neither is a copyright problem and neither is answered anywhere
above.

Boundary (g) is the rule that follows. A brand is not stored as a generic, and no generic fact is
recorded from it rather than mapping it to a near neighbor. **That boundary has no test yet**, which
by this document's own standard means it is not yet a boundary, only an intention.

**⚠️ This is a question for counsel, and it is a different question from section 4.** Section 4 asks
whether facts may be derived from this corpus. This asks what may be done with a mark that turns up
inside those facts. An answer to one is not an answer to the other, so both need putting.

## The founding-principle line

> **Mined data may order, flag, and inform. It may never cut.**

This is not a style preference. `docs/what-the-library-is-for.md` governs what may remove a row, and
it is explicit:

> Do not use recipe-line count as a cut signal. A real ingredient nobody in these 298 recipes happens
> to use, a regional spice or an obscure sauce, stays, because it will be in someone else's import. A
> zero-line row is evidence about this corpus and never about the row.

A 2.2 million recipe corpus is still a corpus. It is English-language and web-scraped, so it
under-represents the cuisines the library exists to serve, which that document names as Filipino,
Ethiopian and Peruvian among everything else. A row's absence from it is a fact about the corpus.

There is a separate reason this matters less than it looks. The noise problem mining might seem to
solve is already solvable without it. **2,261 of the 10,474 catalog rows, 21.6%, are separable on
shape alone**, being 1,334 industrial descriptors of the "50-63% unsalted vegetable fat" kind, 888
Latin binomials and 39 non-Latin-script rows. That is a sourcing problem with a known origin,
concentrated in Open Food Facts at 17.8% of its rows. Mining is the wrong instrument for it.

**Mined facts arrive at `state='open'` and in their own tier, `mined`.** They are never folded into
`cited`. A hand-read extension bulletin and a count over 2.2 million recipes are different kinds of
knowing, and the tier is how a reader tells them apart. 402 hand-made claims exist today, and mined
facts at scale would swamp them, so they stay out of entry prose by default.

## What Phase 1 does and does not do

Phase 1 is this document plus the `source_catalogue` and test changes that stop the repo
contradicting it.
No corpus is downloaded. No parser is written. No table is created.

The next phase acquires the corpus and probes coverage on a sample, and **stops there to report the
number** before anything is built on it.
