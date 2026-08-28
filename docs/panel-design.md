# The Panel: personal and shared ingredients, with submission

**Status: DESIGN DRAFT, and it is not one thing.** It mixes three kinds of claim at three very
different confidence levels, and they are labelled rather than blended:

| label | what it means | who to ask |
| --- | --- | --- |
| **✅ VERIFIED** | checked against the repo or the live `recipes.db` while writing this. The check is named. | nobody, re-run the check |
| **🟡 STATED INTENT, UNCONFIRMED** | rules Andy gave in conversation, transcribed by an assistant and **not confirmed by him**. | Andy |
| **🔵 PROPOSED** | an assistant's inference or suggestion. Open to revision, decided by nobody. | Andy |

**Not a build plan.** Nothing here is scheduled and no stage is approved.

## What this is about

The add-on-save backend, shipped and pushed, creates a row in the one shared `ingredients` table
when any authenticated user saves a recipe that references a library entry. **🟡 Andy has said he
wants a different model instead:** a curated shared library he controls, personal ingredients each
user owns, and an optional submission path from personal up to shared.

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
  private to them, usable in their own recipes. 🟡 Andy's stated shape.
- ⚠️ **The structural gap is real and verified:** `ingredients` has no owner column, so *nothing*
  in this model is expressible today. ✅

## 🟡 STATED INTENT, PENDING ANDY'S CONFIRMATION

**These eight rules came from Andy in conversation and were transcribed by an assistant. He has not
reviewed the transcription.** They are recorded here so they are not lost, not because they are
settled. Anything built on them should re-confirm them first.

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

## Open decisions, none settled

- **A. What "submit" does mechanically.** A separate suggestions table, or a status flag on the
  ingredient row.
- **B. What approval does to the submitter's personal copy.** Promote in place, create a new shared
  row, or re-point the personal one.
- **C. The review UI's shape.**
- **D. Recipe links across the personal and shared boundary.** What happens to a
  `recipe_ingredients.ingredient_id` when the row it points at changes ownership.
- **E. Whether an admin's add goes straight to shared or also queues.** The rules as transcribed
  read as admin-direct. 🟡 Confirm with Andy.
- **F. Curation of personal ingredients.** A user editing their own row. May fold in the
  promoted-row curation tool already recorded in `docs/ingredient-linkage-state.md`.

## 🔵 PROPOSED build order, and one correction to it

This ordering is an assistant's inference. ⚠️ **The draft called it a "forced" order. Having read
the code, only the first step is genuinely forced.**

1. **An ownership column on `ingredients`.** Genuinely the root: every other step reads it. ✅ The
   blast radius is small, which is the good news. `app.py` touches the `Ingredient` model in only
   five places (the gate's two, the gate's `known` set, `/api/ingredients`, and the drawer), plus
   the search route's existence check and the delete path's tier check.
2. **The effective-library read.** `/api/ingredients` today is
   `select(Ingredient.id, Ingredient.name).order_by(Ingredient.name)` with no scoping at all. ✅
   read. Making it personal-wins is the substantive change.
3. **The create path stamps ownership.** A condition on the shipped gate. ✅ Cheap, since the gate
   can reach `current_user` without plumbing.
4. **The picker.** ⚠️ **Correcting the draft's dependency claim:** the picker does not strictly
   require step 2. It could ship against the flat list and be scoped later. What it *does* require
   is step 3, or it creates rows with no ownership at all. 🔵 Sequencing steps 2 and 4 is a real
   choice, not a forced order.
5. **Submission.** Decision A.
6. **Review UI.** Decisions B and C.
7. **Adopt a shared version.** Rule 6, late by Andy's own framing.

## 🔵 What survives, and what does not

The draft said the shipped backend "is reused, not discarded". ⚠️ **That is roughly right and
slightly too comfortable.** Reading the code:

- **Reused as-is:** `library_names` and its loader and generator, `ingredient_slug`, the provenance
  columns, migrations 029 and 030.
- **Reused with a condition:** the create-gate. One check on `current_user.is_admin` decides shared
  versus personal.
- ⚠️ **Needs rework, not just a condition:** the **search route** answers "is this already
  promoted" with a single `ingredient_id`, which becomes ambiguous the moment two rows can exist
  for one concept (mine and the shared one). ✅ Its existence check is
  `select(Ingredient.id, Ingredient.library_id).where(...)` with no ownership notion. And the
  **delete path** gates on `DELETABLE_INGREDIENT_SOURCES = ("app",)` ✅, a tier check that says
  nothing about who owns the row, so a user could delete another user's personal ingredient.

**Neither is fatal. Both are more than a flag.**

## Where this sits relative to what is shipped

🟡 If Andy confirms the rules above, this supersedes the add-on-save-for-everyone model. **It does
not require undoing anything**, because ✅ the create path is unreachable and no row created by it
exists. The scope change arrived at the cheapest possible moment.

`docs/ingredient-linkage-state.md` remains the handoff doc for the linkage work and is not
superseded by this. Its "Stage 8, the picker" entry is the item this design would redirect.
