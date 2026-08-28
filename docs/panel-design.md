# The Panel: personal and shared ingredients, with submission

**Status: DESIGN DRAFT, and it is not one thing.** It mixes three kinds of claim at three very
different confidence levels, and they are labelled rather than blended:

| label | what it means | who to ask |
| --- | --- | --- |
| **✅ VERIFIED** | checked against the repo or the live `recipes.db` while writing this. The check is named. | nobody, re-run the check |
| **🟢 CONFIRMED INTENT** | rules Andy gave in conversation and has since **reviewed and confirmed**. Settled as intent. How to build them is a separate question. | nobody, they are agreed |
| **🔵 PROPOSED** | an assistant's inference or suggestion. Open to revision, decided by nobody. | Andy |

**Not a build plan.** Nothing here is scheduled and no stage is approved.

## ✅ BLOCKERS: the identity ones are RESOLVED, the privacy one is now a build task

**The identity blockers are answered and the build can proceed.** ⚠️ **The privacy hole is not a
design question and was never resolved by answering one.** It is a missing ownership check on the
detail route, and it stays on the build list. See blocker 2 below, which is kept open on purpose.

A ground-readiness inspection at `f994daf` found the schema could not represent the confirmed model.
A follow-up diagnostic mapped the identity options, and Q1, Q2 and the `[[key]]` semantics are now
decided. **The decisions are recorded below with the problems they solve**, because the problems are the reason the answers look the way they
do, and a later reader who only sees the answer will be tempted to simplify it.

⚠️ **Decided is not built.** Nothing here is staged and no code has moved.

### 🛑 1. The primary key could not express the model  →  ✅ SOLVED BY Q1 BELOW

`ingredients.id` is `TEXT PRIMARY KEY`, globally unique, and `ingredient_slug()` mints it
**deterministically from the name**. So a personal row and a shared row for the same concept want
**the same id** and cannot both exist.

**Proven by probe, not reasoned.** Against a real harness database:

```
user B's personal row exists: id='gochujang'
admin promotes library Q_GOCH -> resolved id = 'gochujang', err = None
>>> the admin was handed user B's PRIVATE row. No shared row was or could be created.
```

The mechanism is `_promote_library_row`'s check-then-link, reading an id set with **no ownership
filter**, `known = set(s.scalars(select(Ingredient.id)))` at `app.py:375`.

⚠️ **This breaks three CONFIRMED rules at once:**
- **Rule 1**, because two rows for one concept is unrepresentable.
- **Rule 3**, because if the shared row exists first, a user's create silently links to it instead
  of making their own.
- **Rule 5**, and worse than overwrite. The admin's shared addition does not clobber the user's
  private row, it **becomes a pointer at it**.

⚠️ **This sits UNDER stage 1, not stage 4. Adding an owner column does not fix it.** The identity
scheme has to change first (a surrogate key with `UNIQUE(owner, slug)`, a composite PK, or
per-owner slugs), because `ingredients.id` is what `recipe_ingredients.ingredient_id` points at,
and that is the durable link target the entire shipped architecture rests on.

### 🛑 2. Personal rows are readable by everyone  →  ⚠️ STILL OPEN, and it is a code fix

⚠️ **Nothing in Q1, Q2 or the `[[key]]` decision closes this.** The per-reader `[[key]]` rule means
a step link never reaches another user's row, which removes one route to the leak. **The detail
route is still wide open**, and it needs an explicit ownership check whenever ownership ships.

Rule 3 says personal is "private to them". `get_ingredient(iid)` at `app.py:1066` is a bare primary
key lookup with **no ownership check**, so any logged-in user can GET any ingredient by id. The ids
are **guessable by construction**, because they are slugified names.

**Proven by probe:** user 2 fetched user B's personal ingredient and got `200 OK`.

Privacy is not only a stage-2 filter on the list route. **The detail route needs an ownership check
too.**

### ⚠️ 3. "Same concept" had no key, and it was blocker 1 wearing a second hat  →  ✅ SOLVED BY Q1

Rule 4 needs a key that says two rows mean the same thing. Every candidate fails:

- **Same `id`** is impossible. It is the primary key.
- **Same `library_id`** is null-on-null for a user-typed row, so it matches nothing.
- **Same `name`** inherits the capitalization mess. `Gochujang` beside `gochujang`, and the shipped
  decision recorded in `docs/ingredient-linkage-state.md` is that **no safe casing transform
  exists**.

**There is no concept key, and decisions A and B do not create one.** Until identity is answered,
"personal wins" **cannot be written as a query**. This is not a separate problem. The identity
decision answers the key structure, what `recipe_ingredients` points at, and "same concept", all at
once.

## ✅ DECIDED: Q2, a user may type any name

**A user creates an ingredient by typing any name, including one the library does not have.** Not
only by picking a library row.

**Why.** The reference library is trustworthy *because* it is incomplete. Its governing rule is
**decline over guess**: it omits anything it cannot confidently source, which is what keeps the
shared list clean. Library-pick-only would turn that virtue into a trap, leaving a user unable to
record a real ingredient the library had declined. **Free-text personal ingredients are the escape
hatch**, and submission plus review is how one earns its way into shared, through the admin's
judgment rather than an automatic rule.

⚠️ **The consequence lands on identity.** A user-typed row has **no `library_id`**, so "same
concept" cannot key on library provenance. Free-text is what forces an explicit concept key, which
is what Q1 answers.

## ✅ DECIDED: Q1, the row-key / concept-key split (Option D)

**`ingredients.id` was doing two jobs at once**, saying which row this is and which concept it is.
The model needs those to differ. **Split them.**

```sql
id       TEXT PRIMARY KEY   -- the ROW. Stable forever. Disambiguated for a personal row.
concept  TEXT NOT NULL      -- the CONCEPT. The plain slug. NOT unique.
owner    INTEGER NULL       -- NULL = shared, otherwise the owning user
UNIQUE (owner, concept)     -- one row per concept per owner
```

**Why this shape, from the identity diagnostic:**

- ✅ **It preserves Decision B.** Promotion flips `owner` to NULL. Both `id` and `concept` are
  untouched, so all 50 existing links stay valid and promote-in-place keeps working.
- ✅ **Ids stay textual, so the 30 `[[key]]`s embedded in recipe prose stay human-authorable.** This
  is the constraint that decides the whole question. `[[bread_flour|flour]]` and `[[potato|potatoes]]`
  are hand-typed into recipe steps today.
- ✅ **Zero migration for the 36 seed rows.** `id = concept = 'garlic'`, `owner = NULL`. Their ids
  never change, so `seed.py`, `build_db.py` and `validate()` are untouched.
- ✅ **Rule 4 becomes a real query**: group by `concept`, prefer `owner = current_user`.

**Why not the alternatives:**

- 🛑 **Composite key `(owner, slug)` BREAKS Decision B.** Promotion flips `owner`, and if `owner` is
  part of the key, **flipping it re-keys the row** and dangles every link at it. Off the table.
- 🛑 **Per-owner disambiguated slugs (`gochujang__u5`) BREAK Decision B** for the same reason.
  Promotion would rename the id. It is a composite key inside a string, with worse ergonomics, and
  the owner leaks into prose. Off the table.
- ⚠️ **A surrogate integer key forces the concept column anyway.** Nobody writes `[[47|flour]]`, so a
  surrogate makes `[[key]]` stop meaning an id, which means inventing a concept key regardless.
  **It ends up needing Option D's column after paying for a full re-key first.**

## ✅ DECIDED: a step's `[[key]]` resolves PER READER

**A `[[key]]` names a CONCEPT and resolves to the reading user's version of it**, not to the row the
author happened to link.

**Why.** It matches how a recipe actually works. When you cook somebody else's recipe,
`[[gochujang]]` means **the gochujang you have**. And it dissolves a conflict rather than managing
one: pinning the link to the author's row would force a choice between leaking a private row to a
reader and dangling the link, and **rule 3 says personal is private**. Per-reader resolution never
reaches another user's row at all.

⚠️ This is a real behavior change and it is deliberate. The same recipe text renders a link to a
different row for different readers. That is rule 4 applied consistently.

## What this is about

The add-on-save backend, shipped and pushed, creates a row in the one shared `ingredients` table
when any authenticated user saves a recipe that references a library entry. **🟢 Andy wants a
different model instead, and has confirmed it:** a curated shared library he controls, personal
ingredients each user owns, and an optional submission path from personal up to shared.

⚠️ **🔵 PROPOSED framing, and it may be too generous:** the shipped machinery is largely reusable
rather than wasted. See "What survives, and what does not" below, which is less comfortable than it
first looks.

## ✅ VERIFIED: the ground this stands on

Each line was checked while writing this doc. Where a claim could not be checked, it says so.

**The admin concept already exists and is more than a column.**
- `users.is_admin` is an `INTEGER NOT NULL DEFAULT 0` column. ✅ live schema.
- `admin_required` exists in `auth.py`, one definition, layering `@login_required` then an explicit
  `is_admin` check so 401 and 403 stay distinct. ✅ read.
- It gates **exactly two routes**, both invite-related. Its own docstring says `is_admin` gates
  "ONLY invite generation/listing, not a general superpower over other routes." ✅ read.
- **Exactly one admin exists: user id 1, `andyhannah2014@gmail.com`.** 4 users total. ✅ queried.
- ⚠️ **No route promotes anyone.** `/api/signup` always writes `is_admin=0`, and the only way to
  mint an admin is `scripts/create_admin.py`. ✅ read.

**Ingredients are shared. Nothing about them is per-user.**
- `ingredients` live columns are `id, name, descr, pairs, created_at`. **No owner, no user_id.**
  ✅ queried.
- ⚠️ **The MODEL has two more columns the LIVE DATABASE does not.** `models.Ingredient` declares
  `source` and `library_id` (migration 030), but the live `recipes.db` is at **28 applied
  migrations, last `028_recipe_snapshots.sql`**. ✅ queried. Migrations 029 and 030 have never
  been applied here, so `library_names` does not exist and `ingredients.source` does not exist in
  the database this app currently serves.
- 36 ingredient rows. ✅ queried.

**Ownership exists everywhere else.** `recipes.owner`, and `user_id` on `cook_log`, `ratings`,
`cook_photos`, `recipe_queue`, `recipe_snapshots`, `shared_posts`, plus `comments.author_id`.
✅ queried.
- ⚠️ **But "owner NULL means shared" is a NEW convention, not an existing one.** `recipes.owner` is
  nullable in the DDL, and **0 of 298 recipes have a NULL owner**. ✅ queried. So no table in this
  app currently uses NULL-owner to mean anything.

**A request/approve pattern exists.** `friendships` carries
`status TEXT NOT NULL CHECK (status IN ('pending','accepted'))`, `created_at`, and a nullable
`accepted_at`, keyed `PRIMARY KEY (requester_id, addressee_id)`. ✅ read. Its accept route gets
authorization structurally from the key rather than from an `if`.

**And an anti-pattern exists.** `import_flags` holds **593 rows** with **no review route anywhere
in `app.py`**. ✅ queried and grepped.
- ⚠️ **Correcting a claim in the draft: they are not "593 unreviewed rows".** The table has columns
  `id, recipe_id, position, flag, reason, created_at` and **no status, reviewed or resolved column
  at all**. ✅ queried. There is no concept of reviewed to be outside of. That is a sharper warning
  than "unreviewed", because the shape itself never anticipated review.

**The create-gate can see the user, and today does not look.**
- ⚠️ **Correcting the draft's phrasing.** `resolve_recipe_payload` and `_promote_library_row`
  contain **zero references to `current_user`**. ✅ grepped. What is true is that `current_user` is
  imported at `app.py:21` as a module-level Flask-Login proxy, both call sites are inside
  login-gated handlers, and the edit path reads it one line above the gate call. **So the gate
  *could* read it with no plumbing. It does not currently read it.**

**The create path is unreachable from the UI.**
- **No client file sends `item_library_id`.** ✅ grepped `static/*.js`. The picker's
  `<option value>` comes from `INGREDIENT_LIST`, which is `/api/ingredients`, which returns only
  rows already in the table. ✅ read.
- **So no wrong-tier row can exist, because none can be created.** ✅ follows from the above.

**Git and CI position.**
- `origin/main` is at **`622a6a0`**, and both workflows on it are `completed/success`. ✅ queried
  the Actions API.
- ⚠️ **Correcting the draft: HEAD is not `622a6a0`.** Local HEAD is **`1d952fe`** (the state-doc
  commit), **1 ahead of origin, 0 behind, unpushed**. ✅ queried.
- **50 of 3,332 ingredient lines carry a stored link.** ✅ queried. Unchanged by any of this work.
- **No committed matcher module.** ✅ listed every `*.py` at the repo root. Nothing there is the
  line-to-library matcher.
- `library_names.csv` is **absent on this machine**. ✅ checked. **(unverified)** for any other
  machine, and unverifiable from here.

## The model, in outline

- **SHARED.** Ingredients every user can use. Today's 36 rows are effectively this, since the
  table has no owner column at all. ✅
- **PERSONAL.** A user's own ingredients, server-stored per-user data rather than device-local,
  private to them, usable in their own recipes. 🟢 Andy's confirmed shape.
- ⚠️ **The structural gap is real and verified:** `ingredients` has no owner column, so *nothing*
  in this model is expressible today. ✅

## 🟢 CONFIRMED INTENT: the eight rules

**Andy has reviewed and confirmed these.** They came from him in conversation, an assistant
transcribed them, and he has since checked the transcription against what he meant. They are
settled as intent.

⚠️ **Settled as intent is not settled as design.** Rules 1 to 8 say what the model does. They do
not say how any of it is built, and every 🔵 below is still an assistant's proposal.

1. An ingredient is either shared (no owner) or personal (owned by one user).
2. Admin creates goes to shared, and every user without their own version simply uses it. No
   per-user copy is made.
3. A user creates goes to personal. Private, and not shared unless submitted.
4. Personal wins by default. A user's effective library is their personal rows plus the shared rows
   they have not overridden.
5. Never overwrite. An admin adding to shared never clobbers a user's personal row.
6. Adopt, late. A user can see that a shared version of something they own exists and choose to
   switch to it. A re-linking operation, deliberately staged late.
7. Submission is optional. A user can send a personal ingredient up as a suggestion.
8. Review. The admin approves it into shared, or rejects it. It must have a review UI.

⚠️ Rule 8's "must have a review UI" is the one with teeth, and the reason is ✅ verified above:
`import_flags` is 593 rows in a table with no review route and no status column.

## 🟢 DECIDED: how submit and approve work

**A. Submitting creates a SEPARATE suggestion object.** A new suggestions table, not a status flag
on the ingredient row. **The user's personal ingredient row is left completely untouched by
submitting.**

Three reasons, in order:
- It mirrors `friendships`, which is ✅ verified above as a working request/approve pattern in this
  codebase: a `status` CHECK constraint, a `created_at` and a `reviewed_at`, and authorization that
  falls out of the row key rather than an `if`. Copying a proven shape beats inventing one.
- It keeps the ingredient row clean. An ingredient is a thing you cook with. Whether somebody once
  offered it for review is not a property of the ingredient, and a status column on the row would
  make every reader of `ingredients` step around a workflow field.
- The review gets its own object, so it can carry what a review needs (who asked, when, what the
  admin decided, when) without any of that living on the ingredient.

**B. Approval PROMOTES THE PERSONAL ROW IN PLACE.** The submitter's row flips from owned to shared,
which under rule 1 means its owner is set to null. **The same row, the same id.**

- **Recipe links keep working with nothing to re-point.** The id never changes, so every
  `recipe_ingredients.ingredient_id` pointing at it stays valid. ✅ This matters because the id is
  the durable link target, which is the architecture already shipped and recorded in
  `docs/ingredient-linkage-state.md`.
- **No duplicate is created.** The alternative, minting a fresh shared row, would leave the
  submitter's personal copy shadowing the shared one they themselves asked for.
- ⚠️ **This does not violate rule 5.** Rule 5 says an admin's shared addition never clobbers a
  user's personal row. Promotion is not a clobber, because **the submitter consented by submitting**.
  Rule 5 protects a user from OTHER people's actions, not from the consequences of their own.

## Open decisions, still unsettled

- **C. The review UI's shape.**
- **D. Recipe links across the personal and shared boundary.** ⚠️ **Narrowed by B, not closed.**
  Promotion in place keeps the id, so a link to a promoted row needs no re-pointing at all. What
  remains open is every other crossing: what a link does if a personal row is deleted, and whether
  one user's recipe may link to another user's personal ingredient in the first place.
- **E. Whether an admin's add goes straight to shared or also queues.** The confirmed rules read as
  admin-direct, but they do not say so in as many words. Worth a sentence from Andy.
- **F. Curation of personal ingredients.** A user editing their own row. May fold in the
  promoted-row curation tool already recorded in `docs/ingredient-linkage-state.md`.
- **I. `[[key]]` fallback when the reader has nothing.** A refinement of the per-reader decision,
  not a blocker. When a reader has no personal row for the concept **and there is no shared row
  either**, what does the link do? Fall through to the shared library row, render the concept name
  as plain text with no drawer, or offer to create one. Settle it before `[[key]]` resolution is
  built, since it is the branch that fires most often early on, when few concepts are shared yet.

⚠️ **Deciding B surfaced two more, and neither is answered by it.** Both are listed rather than
assumed, because guessing either one wrong leaves bad data rather than a bad screen.

- **G. What happens to the suggestion row after approval.** Kept as approved-history, which gives an
  audit trail and a record of who contributed what, or deleted, which keeps the table to live work
  only. `friendships` keeps its row and flips `status`, which is a precedent rather than an argument.
- **H. Two users submitting the same concept.** If user A's gochujang is promoted to shared while
  user B already has a personal gochujang with a suggestion still pending, **B's suggestion is now
  for something that exists**, and B's personal row now shadows a shared one. Rule 4 covers the row
  itself: B keeps using theirs, no action needed. **B's pending suggestion still needs a
  resolution**, and there is no obviously right answer. Auto-reject it as redundant, leave it for the
  admin to reject by hand, or surface it to B as "this is already shared, adopt it?", which is rule
  6's adopt operation arriving earlier than rule 6 intends.

## 🔵 PROPOSED build order, now rooted in a decided identity

**Still 🔵 PROPOSED.** The identity question underneath it is settled, so the sequence is real rather
than provisional, but **it is a build plan and nothing is staged**.

⚠️ **This order has been corrected twice, and the history is worth keeping.** It first read "an
ownership column on `ingredients`. Genuinely the root." That was wrong: the column would have been
added to a key that cannot hold two rows for one concept. Identity was the root. **Now that Q1 has
answered identity, the ownership column returns as step 1 not as the root but as one column of the
Option D change**, alongside `concept` and the unique constraint.

1. **The Option D schema.** `id` stays as it is, add `concept` and `owner`, add
   `UNIQUE (owner, concept)`, and backfill the 36 seed rows as `id = concept`, `owner = NULL`. ✅ No
   existing id changes, so `seed.py`, `build_db.py` and `validate()` are untouched. ✅ The blast
   radius is small: `app.py` touches the `Ingredient` model in five places (the gate's two, the
   gate's `known` set, `/api/ingredients`, and the drawer), plus the search route's existence check
   and the delete path's tier check. ⚠️ The drawer reads `select(Ingredient.__table__)` into
   `dict(ing._mapping)`, so **`owner` and `concept` appear in that JSON the moment they exist**,
   exactly as `source` and `library_id` did.
2. **The effective-library read, and per-reader resolution.** Rule 4 as a query: group by `concept`,
   prefer `owner = current_user`. `/api/ingredients` becomes user-scoped, and `[[key]]` resolution
   uses the same rule. ⚠️ **The privacy fix belongs here**, since the detail route needs its
   ownership check the moment personal rows can exist.
3. **The create path: stamp ownership AND build free-text creation.** ⚠️ **Q2 answered free-text,
   so this is a NEW CREATE PATH, not a condition.** ✅ The gate can reach `current_user` without
   plumbing, so the ownership stamp itself is cheap. But the shipped gate's only insert requires a
   `library_names` hit, so creating from a typed name needs a new route, its own validation, and its
   own id and concept minting. This is the step the earlier "one condition" framing most understated.
4. **The picker.** ⚠️ **An earlier note here said the picker does not strictly require step 2 and
   could ship against the flat list. Option D changes that.** A picker now has to show the reader's
   effective library and offer free-text creation, both of which are steps 2 and 3. It is no longer
   a resequencing choice.
5. **Submission.** Decision A.
6. **Review UI.** Decisions B and C.
7. **Adopt a shared version.** Rule 6, late by Andy's own framing.

## 🔵 What survives, and what does not

The draft said the shipped backend "is reused, not discarded". ⚠️ **That is roughly right and
slightly too comfortable.** Reading the code:

- **Reused as-is:** `library_names` and its loader and generator, `ingredient_slug`, the provenance
  columns, migrations 029 and 030.
- **Partly reused:** the create-gate. Its library-pick branch survives with an ownership stamp
  added. ⚠️ Q2 answered free-text, so **a second branch has to be built beside it**. See the rework
  bullet below.
- ⚠️ **The search route needs REDESIGN, not a tag.** Its contract is one `ingredient_id` per
  library row, resolved through a **last-write-wins dict with no `ORDER BY`**
  (`by_library_id[row.library_id] = row.id`). ✅ Once a personal and a shared row can both exist for
  one library row, that dict silently picks one. **This is the same bug shape `5f2aacd` just
  fixed.** The honest shape is `{shared, mine}` per result, and every caller changes with it.
- ⚠️ **The delete path lets a user delete someone else's personal row.** It gates on
  `DELETABLE_INGREDIENT_SOURCES = ("app",)` ✅, tier alone with no ownership notion, and a personal
  row would be `source='app'`. Small change, real hole.
- ⚠️ **The create-gate needs a REAL FREE-TEXT CREATE PATH, and this is the biggest single piece of
  rework.** Q2 answered free-text, and ✅ the shipped gate's only insert requires a `library_names`
  hit, so **there is no code path today for a typed name**. New route, new validation, new id and
  concept minting. The earlier "one condition on `current_user.is_admin`" framing understated this
  more than anything else in the doc.

**None is fatal. All are more than a flag.**

### ✅ What is genuinely ready

Recorded so the picture is balanced rather than only alarming. Each was checked.

- **The owner column itself.** Nullable FK, trivial backfill, all 36 rows `owner IS NULL`.
- **No positional coupling.** Nothing reads ingredients by column position, so adding one is
  additive.
- **`current_user` is reachable in the gate.** Module-level proxy at `app.py:21`, and
  `update_recipe` reads it one line above the gate call.
- ⚠️ **Decision B survives intact, and is the strongest part of the design.** Promote-in-place works
  **because the id is durable**, which is the same property the identity fix has to preserve. Q1
  should be answered with B in mind: whatever replaces the key must keep a promoted row's identity
  stable, or B stops working.
- **`friendships` transfers as the suggestions template.** One place it does not: friendships is
  symmetric between two users, while a suggestion is one user to **a role**, so the addressee half
  has no person in it.
- **The client cache is fine.** `INGREDIENT_LIST` is a module global fetched once per session, and a
  session is one user. Five read sites, none breaks on a per-user response.
- **The harness supports multi-user.** `ensure_test_user(email=..., is_admin=...)` and
  `login_test_client(client, uid)` both parameterize, and `tests/test_auth.py` already builds a
  second client. ⚠️ But `make_kitchen` logs in exactly one user, so **every per-user scoping test
  needs a second client built by hand**, and no existing ingredient test does that.
- **Migrations 029 and 030 being unapplied is a non-issue.** The panel migration would be 031, next
  in sequence. It only means the live database gains three at once on the next `build_db.py`.

## Where this sits relative to what is shipped

🟢 The rules above are confirmed, so this supersedes the add-on-save-for-everyone model. **It does
not require undoing anything**, because ✅ the create path is unreachable and no row created by it
exists. The scope change arrived at the cheapest possible moment.

⚠️ **And so did the blockers.** They were found before a column was added, before a row was
promoted, and before a single stage was staged. Nothing has to be unwound to act on them. Finding
the identity problem three stages in, with promoted rows already carrying ids that cannot hold the
model, is the version of this that would have cost something.

`docs/ingredient-linkage-state.md` remains the handoff doc for the linkage work and is not
superseded by this. Its "Stage 8, the picker" entry is the item this design would redirect.
