# Mining a recipe corpus for facts

The standing decision about reading a large recipe corpus for **facts**, and the boundaries that
reading stays inside. Read this before writing any code that touches a scraped corpus.

**Status: SCAFFOLD. Not yet in force.** The structure below is written. The legal reasoning is a
**draft written for the owner to edit and own**, not a position he has settled. Nothing mines
anything until he has taken that section as his own and changed this line.

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
A count over many recipes is stored. One recipe's ingredient list is not, and proportions are the
sharp case: a ratio averaged over 900 recipes is a fact about the corpus, and one recipe's
quantities beside its ingredient names is that recipe. Every stored row carries an `n` of how many
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
*Enforced by:* `test_mined_tables_hold_no_corpus_text`.

## The legal reasoning

**⚠️ A DRAFT, AND NOT LEGAL ADVICE.** This is the owner's working position. It has not been reviewed
by a lawyer. It records the reasoning he accepts for this bounded, local use, and it is why he judges
the use defensible rather than a guarantee that it is. Before any of this data ships in a product
other people use, the position should be read by someone qualified.

### 1. Facts and functional information are not copyrightable

Copyright protects creative expression. The words a writer chose, the headnote, the way a recipe is
told. It does not protect facts, and it does not protect functional information.

An ingredient list is a functional statement. It says what goes in and how much. That is generally
not copyrightable, and the expressive part of a recipe is the writing around it.

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
