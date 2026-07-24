# Chef's Choice — Product Vision (recipe-box / multi-user model)

The **source of record** for the product direction decided in planning conversation, written so it
survives across sessions and shapes the rescoping + later stages rather than being re-litigated. The
outcome-data thesis (why ratings/cooks/modifications are the scarce asset) lives in
[OVERVIEW.md](../OVERVIEW.md); this doc records the **multi-user shape** that thesis takes.

## Recipe-box / multi-user model (decided, mostly not-yet-built)

The app is a **social recipe-box**: each user has their OWN recipe box (collection). The used-cookbook
thesis, extended to multi-user — the recipe is the freely-copyable **commodity**; what's YOURS is your
**curated box** plus your **private personal layer** on the recipes in it.

### Core model

- Every recipe belongs to exactly **ONE box** (exactly one owner). `recipes.owner` identifies whose box.
- The **personal layer** (ratings, cooks, per-line edits/additions) is **per-user and private**; you can
  VIEW others' layers (Model A).
- **Copy semantics:** copying someone's recipe **DUPLICATES** it as a NEW recipe owned by YOU (added to
  your box), independent of the original — so you can modify/rate/cook your copy without affecting
  theirs. One recipe, one owner; **copy = duplicate, NOT a shared recipe in multiple boxes** (no join
  table).
- The **ingredient library stays SHARED / app-global** — the `[[key|label]]` linking vocabulary everyone
  draws on. It is NOT boxed or owned.

### Box features (later social/upload stage — needs multiple users live)

- **Pin/favorite** recipes (curate your box).
- **View other people's** boxes/recipes (social/discovery).
- **Copy-into-my-box** (cross-user copy → a new owned recipe). A `copy_recipe` endpoint already exists
  (single-user today); the box model makes it cross-user with `owner = copier`.
- **Recipe upload** (users add their own recipes → owned, in their box).
- No moderation/review.

## Stage boundary — ownership *data model* now, ownership *rules* later

**RESCOPING (now)** — the data model that makes the box possible, nothing more:
- `recipes.owner` (all 298 existing recipes → my box on migration).
- Per-user personal layer: `ratings` PK → `(recipe_id, user_id)`, `cook_log.user_id`, and the change
  layer's `person_id` → `user_id` (zero-data repoint — the change tables are empty).
- All writes scoped to `current_user`.
- Recipes stay **VISIBLE to all** for now: `owner` is a *recorded attribute*, not yet a visibility filter.

**DEFERRED to the upload/social stage** — the ownership **authorization rules**:
- edit/view/delete of others' recipes, list visibility/filtering, pin/favorite, cross-user copy, upload.
- These need **multiple owners live** to design and test correctly. Building them now would mean
  inventing rules against a one-user fiction — so the data model lands first, the rules follow when
  there's real multi-user data to shape them.
