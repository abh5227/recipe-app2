# The ingredient and library model

The **source of record** for how ingredients and the ingredient library relate, what the columns on
`ingredients` mean, and which invariants that model rests on.

**This document supersedes [panel-design.md](panel-design.md).** That document inherited one correct
word from [product-vision.md](product-vision.md) and gave it a second meaning it never had, and its
structure is built on the result. It is kept as a record of how that happened. See section 5.

Written as Phase 4 of the August 2026 reconciliation. The measurements it rests on are in
[reconciliation-2026-08.md](reconciliation-2026-08.md), the change-list, which checked every claim
against the code rather than against a summary of it. **This document states the model. It does not
plan a build.**

## How this document cites things

**Code is cited by symbol, never by line number.** The change-list measured why. Every document in
this repo that cites `file:line` has drifted, and `docs/design-decisions.md`, the one large document
that names a function instead, has not (change-list section F). Line numbers appear below only for
prose documents, where the line is the address.

Counts carry their provenance. **Measured** means re-derived against the working tree or the live
`recipes.db` while writing this. **Change-list** means carried from the reconciliation, which
measured it there.

---

# 1. The model

## The library is the one ingredient store

There is one store of ingredients and it is the **library**. Recipes link to library ingredients so
that a person can learn what an item is before cooking with it. That is what the link is for.

The library is built from five public vocabularies (Wikidata, Open Food Facts, AGROVOC, Wikipedia,
Wiktionary), harvested for **names** rather than for concepts. What is allowed in, what gets cut, and
which name wins the display slot are settled in
[what-the-library-is-for.md](what-the-library-is-for.md). That document remains the library's
admission charter and this one does not restate it.

Size: **10,527 rows** carrying **184,891 variation keys** (change-list E8). The rows are built in
`join.db` and `sources.db`, about 6.07 GB of gitignored input, and reach the app through one
generated file, `library_names.csv`, roughly 330 KB of `library_id` to `canonical` pairs
(`build_db.py`'s loader docstring, corrected in `e3d899b`).

⚠️ **The library is server-side infrastructure and it does not ship.** `library_names.csv` is
gitignored and is **absent from the repo root today** (measured, and change-list H2). A checkout and
CI both run with an empty `library_names` table, which is exactly what holds the promote path
dormant. `LibraryName`'s docstring calls that the self-disabled state and it is deliberate.

## A library row becomes an `ingredients` row on first use

This is the **materialization boundary**, and it is the single most load-bearing mechanism in the
model.

`recipe_ingredients.ingredient_id` is a foreign key to `ingredients.id`. It does **not** point at a
library row and it never has. A save that names a library entry runs `_promote_library_row`, which
resolves the library id to an `ingredients` row, creating it if the concept has not been used before.
The four steps are lookup, then `library_id`, then slug, then insert, and that order is the whole
correctness argument (see the function's docstring, and section 4 below).

**Why the boundary exists.** Library ids are not durable across a rebuild, and seven of them died in
`460cae5`. The library itself is 6 GB of gitignored databases that no server holds. So the durable
link target is the `ingredients` row, which `migrations/030` states in as many words.

`owner IS NULL` on that row means **it is a library row**, visible to everyone.

## Personal ingredients

A user's own ingredient. Private, visible only to them, usable in their own recipes.

- `owner = <user id>` marks it.
- It is readable only by its owner. `get_ingredient` folds ownership into the lookup, so a row you
  may not read is never fetched, and the refusal is a **404 and not a 403**. Section 4 says why.
- A user may type **any name**, including one the library declined. The library is trustworthy
  because it is incomplete, and free text is the escape hatch that keeps that virtue from becoming a
  trap.
- A personal row may be **submitted** for review and added to the library. Approval promotes the row
  in place by clearing `owner`, so the id and the concept both survive and no recipe link needs
  re-pointing.
- **Personal wins.** A user's effective list is their own rows plus the library rows they have not
  overridden. If they have their own version of a concept, theirs leads. If they do not, the library
  row is used.

⚠️ **Confirmed intent, not shipped code.** Submission, review and per-reader resolution are settled
as intent (transcribed in `panel-design.md`'s eight rules and reviewed by the owner) and **none of it
is built**. What is built is the schema that can express it (`eeadb79`, migration 031) and the
privacy gate that keeps a personal row private the moment one exists (`88aeb72`).

## There is no "shared tier"

⚠️ **This is the misreading this document exists to end.**

`product-vision.md:60` says the ingredient library stays **SHARED / app-global**, and that it is
**NOT boxed or owned**. Read in its own context that is correct and it is still correct. "Shared"
there contrasts with **boxed**, which is the recipe-box model's word for per-user ownership. It means
one library that everyone links against, as opposed to a separate copy per user.

`panel-design.md` took the word and gave it a second meaning: a **tier inside the `ingredients`
table**, sitting opposite a personal tier. **That tier does not exist and never did.** Nothing in the
schema, the routes, the import pipeline, the library builder, the matcher or the client implements
one.

**The correction is one substitution.** `owner IS NULL` does not mean "shared". It means **a library
row**. The predicate is unchanged, the mechanism is unchanged, and the privacy gate built on it is
correct as written.

## The 36 curated rows are the owner's corpus

**Measured: 36 rows in `ingredients`, and every one of them is a library row.**

They are early **hand-curated library entries** that predate the library build. They carry
hand-written `descr` and `pairs` prose that the library has no equivalent for and that nothing
regenerates. `_promote_library_row` records the overlap: 32 of the 36 ids are reproduced exactly by
slugifying some library canonical (garlic, red_onion, soy_sauce), which is why the promote path links
to an existing row rather than inserting beside it.

They are **not** a separate tier, and they are **not** a starter set that every installation
receives. Chef's Choice is a hosted service. Nobody clones it to use it, so there is nothing to ship
to anyone. There is the owner's corpus, and there is the library on the server.

⚠️ **How they are loaded today does not match that.** `build_db.seed_content` still upserts all 36
from `seed.py` on every run, keyed `ON CONFLICT(id) DO UPDATE`, and separately deletes and rebuilds
three child tables (`ingredient_seasons`, `ingredient_regions`, `regions`). The ingredient rows
themselves are never deleted, and the comment says why, to protect recipe references.

✅ **DECIDED, and the contradiction that stood here is closed.** The rebuild is **current behavior,
not an intended permanent state.** The 36 are the owner's corpus, the seed-rebuild is slated to be
retired, and once retired they are ordinary durable rows, indistinguishable in kind from any promoted
ingredient. **Stage A shipped in `36f5868`**, which decoupled the test fixtures from `seed.py`'s
`INGREDIENTS`. Nothing after it is scoped.

This was change-list **D1**, its highest-priority contradiction. `CLAUDE.md`'s seed-to-app-miss
paragraph, under Working conventions, called the rebuild intended, and now states the corrected model
and points here. ⚠️ **The mechanism is still undecided**, meaning how the 36 become durable rows and
what becomes of their `seed.py` definitions. That question is entangled with the backfill below.

## The two linking surfaces, and neither is built

Linking a recipe line to an ingredient is one engine, the matcher, reached from two directions.
⚠️ **Neither surface exists.**

**Auto-link at import**, going forward. `import_write` writes `"ingredient_id": None` and says three
times that linkage is a separate later pass. The import pipeline imports nothing library-related, and
that is correct rather than an omission.

⚠️ The constraint is not plumbing. A server holds `library_names` and nothing else, which is
**10,527 canonical names**. The matcher indexes **184,891 variation keys** over the same rows
(change-list). Import-time linking against canonicals alone would be a far weaker matcher, and the
variation index **has no server-side representation at all**. A second constraint sits beside it:
`plan_recipe` is pure by contract and takes no connection, which is what makes the import dry-run
exact, so adding linkage means either handing the pure planner a data source or moving the work into
`commit_plan`.

**Retroactive backfill**, for what is already here. Measured on the live database:

| | measured |
| --- | --- |
| recipes | 298 |
| `recipe_ingredients` rows | 3,555 |
| non-heading lines | 3,332 |
| non-heading lines carrying a label | 2,997 |
| lines with a stored `ingredient_id` | **50** |
| distinct ingredients those 50 reach | **36** |
| recipes carrying at least one link | **6** |

⚠️ The matcher emits `(anchor, library_id, canonical)`, and `library_id` is **not a valid foreign key
value** for `recipe_ingredients.ingredient_id`. A backfill therefore has to resolve each match
through the materialization boundary first, which needs `library_names` populated, which needs the
gitignored CSV. Only then can it write.

⚠️ **A scale consequence nobody has costed.** The matcher's 2,771 matches would materialize up to
2,771 `ingredients` rows against **36** today, and **23 test assertions plus every documented count
are written against 36** (change-list). Its coverage is 2,771 of 3,332 non-heading lines (83.2%) by
one denominator and 2,214 of 2,997 labeled lines (73.9%) by the other. **Both are correct over their
own set** (change-list E10). Its confidence bands are **computed** from n-gram length and coverage in
`AGREE.py`, with no human input, and 91.2% of its lines have never been individually read. HIGH means
the algorithm is confident, not that anyone checked.

The matcher's source lives at [study/matcher/](../study/matcher/), committed in `b42dd14`.

---

# 2. The column semantics, corrected

This is where the confusion lived, so each column gets stated with what reads it and what writes it.

⚠️ **The live `recipes.db` is at 28 of 31 migrations** (measured), so `concept`, `owner`, `source`
and `library_id` are **not present in it yet** and neither is the `library_names` table. Migrations
029, 030 and 031 apply together on the next `build_db.py`. The schema below is what the code, the
tests and CI run against.

## `owner`

`INTEGER NULL`, a reference foreign key to `users.id`.

- **NULL means a library row**, visible to everyone.
- **Set means a personal row**, visible only to that user.

⚠️ **Several comments in the code call NULL "shared".** That word is wrong and it means library.
The sites are enumerated in change-list section A and this document does not edit them.

**One reader, and no writer.** `get_ingredient` is the only code that reads it (measured: the two
occurrences of `Ingredient.owner` in `app.py` are both inside its `or_`). Nothing in the app sets it,
so **every row that exists is a library row**, and the privacy gate is inert on today's data. That is
by design. It landed before the create path that will make the first personal row, so there is no
window in which one exists and the route still hands it to a stranger.

## `concept`

`TEXT NOT NULL`, the plain slug. Not unique on its own.

The **concept key**, opposite `id`, which stays the **row key**. That split is Option D, decided
because a personal and a library row for one concept must coexist while `id` stays stable. `id`
staying stable is what keeps the 50 stored links resolving and keeps the `[[key]]`s hand-typed into
recipe prose (`[[bread_flour|flour]]`, `[[potato|potatoes]]`) human-authorable.

**Zero readers. Three writers.** Nothing reads it, and a test pins that (`test_concept_still_has_no_readers`).
It is pure shape until the create path exists. It is **written** by `_promote_library_row`,
`build_db.seed_content` and `pg_harness.seed_all`, all three of which must supply it explicitly.

⚠️ **The `NOT NULL DEFAULT ''` is a SQLite necessity, not a design choice.** SQLite refuses to add a
NOT NULL column to a populated table without a default, and the table-rebuild escape used by
migration 019 is unavailable here because three tables carry foreign keys into `ingredients`. The
migration overwrites the `''` immediately and a test asserts no row ever holds it. ⚠️ Leaving a
writer to fall back on that default is what broke CI once. `pg_harness.seed_all` omitted `concept`,
the first row took `''`, and the second collided. Fixed in `3ac4799`, and it only ever failed under
Postgres (change-list H4).

## `source`

`TEXT NOT NULL DEFAULT 'seed'`, the same vocabulary as `recipes.source`.

**One reader**, the delete gate in `delete_ingredient`, which refuses anything outside
`DELETABLE_INGREDIENT_SOURCES = ("app",)`.

⚠️ **Under this model the column has no remaining job.** `owner` distinguishes library from personal.
`library_id` distinguishes a promoted row from a hand-authored one. That leaves `source` restating
what two other columns already say. It is a **candidate for eventual removal** and the change-list
records it as such. **Do not remove it as a cleanup.** The delete gate depends on it, the default
direction is a deliberate fail-safe (section 4), and replacing the gate is a separate decision with
its own diagnostic.

## `library_id`

`TEXT NULL`, **audit provenance and deliberately not a foreign key**, because library ids are not
durable across a rebuild and this column is expected to dangle.

Read by `_promote_library_row` at step 2, which is what makes a repeat promote a no-op, and by
`search_library`, which uses it to report a library row as already promoted. `get_ingredient` selects
the whole row, so it is served to the drawer as well.

---

# 3. The index name says "shared", and there is no shared tier

⚠️ **Read this before reading `idx_ingredients_shared_concept` anywhere.**

Two unique indexes sit on `ingredients`, and **one alone is not enough**:

```sql
CREATE UNIQUE INDEX idx_ingredients_owner_concept  ON ingredients(owner, concept);
CREATE UNIQUE INDEX idx_ingredients_shared_concept ON ingredients(concept) WHERE owner IS NULL;
```

- `idx_ingredients_owner_concept` enforces **one row per concept per user**.
- `idx_ingredients_shared_concept` enforces **one LIBRARY row per concept**, which is what its
  partial `WHERE owner IS NULL` selects.

**Both are needed.** SQLite treats NULLs as distinct in a unique index, so `UNIQUE(owner, concept)`
by itself permits `(NULL,'garlic')` twice. That was measured before the migration was written.
Together the two give the four behaviors the model needs: one library row per concept, one personal
row per concept per user, a library row and a personal row for one concept coexisting, and two users
each holding their own.

⚠️ **The name is a historical misnomer. "shared" here means LIBRARY.** It was minted while the
phantom tier was believed in. There is no shared tier, and reading the name as evidence of one is
exactly the mistake this document exists to stop.

**The name is kept.** Renaming an applied index costs a migration on **both** dialects, SQLite and
Alembic, for **zero functional gain**. That is Decision **A10**, resolved as leave-and-document, and
this section is the documentation it was left in favor of. The name appears at eight sites, one of
which is schema (change-list A10).

---

# 4. What this model rests on, and must not be broken

Load-bearing and verified correct. **Do not "fix" these.**

**The materialization boundary.** Recipes link to materialized `ingredients` rows and never to
library rows. Library ids are not durable across a rebuild, seven died in `460cae5`, and the library
is 6 GB of gitignored databases that no server carries. `migrations/030` states the rule: the durable
link target is the `ingredients` row itself. **This is why the link survives a library rebuild**, and
it is the constraint that shapes the entire backfill.

**The four-step order in `_promote_library_row`.** Lookup, then `library_id`, then slug, then insert.
Step 2 was missing once and a pre-push review found what that cost: rename a canonical, promote
again, and the new slug misses the old row and inserts a second row carrying the same `library_id`.

**The canonical comes from `library_names`, never from the request.** That is the whole of the
junk-proofing. A caller supplies a key, the function looks the name up, and a key the table does not
hold creates nothing.

**Check-then-link before insert.** 32 of the 36 hand-authored ids are reproduced by slugifying a
library canonical. When the slug is taken, the existing row is linked to and **left alone**, because
a hand-written row is not improved by a library name.

**The fail-safe direction of `source` defaulting to `'seed'`** (`migrations/030`). A writer that
forgets leaves a row **undeletable** rather than deletable. The direction is the point, not the
default value.

**Ownership folded into the lookup** in `get_ingredient`. One refusal branch, so "no such ingredient"
and "not yours" cannot drift apart later, and a hidden row is never fetched. The season, region and
used-in queries run only on a row that passed, so a hidden row leaks nothing through its children.

**404 rather than 403 for a row you may not read.** ⚠️ This is the app's convention applied, not a
departure from it. The `recipes.owner` gates answer 403 because they are writes on a recipe the
requester can already see, so 403 conceals nothing there. A personal ingredient is the other case.
**Its existence is the private fact**, and ids here are slugified names, the most guessable id space
in the app. A 403 on `/api/ingredients/gochujang` would tell a guesser that somebody keeps a private
gochujang.

**The box model.** All recipes visible to everyone, the personal layer scoped per user, writes gated
on owner at seven sites. `docs/SECURITY.md` describes it accurately.

## ⚠️ The valid senses of "shared". Do not find-replace

Only the **tier** sense is wrong, and only at the sites enumerated in change-list section A. These
eight are correct and a cleanup pass that touches them breaks meaning:

| sense | where |
| --- | --- |
| the library is app-global, **not boxed** | `product-vision.md:60` |
| a shared **corpus of recipes**, the box model | `SECURITY.md:79` |
| shared **brain modules** (`weights.py`, `stepscale.py`, `images.py`, `scaler.js`) | `CLAUDE.md:80`, `design-decisions.md` twelve times |
| a shared **image file** between a copy and its original | `design-decisions.md` five times, `app.py::unlink_unreferenced` |
| `shared_posts`, the table | throughout the social layer |
| a shared **CSS token or DOM element** | `design-decisions.md` four times |
| the hero caption slot, shared between hero and album | `design-decisions.md:1246,1249` |
| **SHARED (a recipe)**, a feed post type | `design-decisions.md:681` |

---

# 5. Where this sits among the other documents

| document | what it owns | status |
| --- | --- | --- |
| **this document** | the ingredient and library model, the column semantics, the index name | **source of record** |
| [what-the-library-is-for.md](what-the-library-is-for.md) | the library's admission charter, what gets in and what is an alias | current, not superseded |
| [product-vision.md](product-vision.md) | the broader product model, the recipe box, the social layer | current, and its `:60` "shared" is correct |
| [ingredient-linkage-state.md](ingredient-linkage-state.md) | the linkage work's handoff state | current, and under-claims the matcher (change-list B6) |
| [reconciliation-2026-08.md](reconciliation-2026-08.md) | the measured change-list this rests on | current |
| [panel-design.md](panel-design.md) | how the panel was designed, and how the phantom tier took hold | ⚠️ **SUPERSEDED by this document** |

**What is deliberately not here.** This document does not plan the panel, the submission flow, the
review queue, the browse surface, the backfill or the import linking. It does not correct the
comments and test names in change-list section A. Those are separate pieces of work with their own
decisions, and the change-list is where they are enumerated.

**Change-list D1 is settled** and its answer is stated above, under "The 36 curated rows are the
owner's corpus". What stays open there is the mechanism, not the direction.
