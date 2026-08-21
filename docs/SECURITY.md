# Security & Privacy Principles

Data privacy and protecting users is a **cornerstone** of this project. Every auth, per-user-data, and
deployment change must satisfy these principles — they are the standard the auth / rescoping / hosting
stages build against, not aspirations.

- **Fail closed.** When config is missing or authorization is ambiguous, DENY / refuse — never proceed
  insecurely. Concretely: with a Postgres `DATABASE_URL` (production), the app **refuses to start** if
  `SECRET_KEY` is unset rather than falling back to a public dev key (see `app.py`).

- **Secrets never in the repo.** `SECRET_KEY`, `DATABASE_URL`, and any invite/credential values come
  from environment variables; production fails fast if they're unset. A dev-only fallback must be
  clearly labelled dev-only **and structurally unable to reach production** — e.g. the `SECRET_KEY`
  fallback is rejected the instant `DATABASE_URL` points at the prod (Postgres) database.

- **Least exposure in responses.** Never return more about a user than the client needs. **Never expose
  `password_hash`.** As per-user features land, never leak another user's private data (their email,
  ratings, cook history) except through a deliberately-scoped shared view.

- **Don't leak existence / identity.** Auth errors are generic — login answers `"invalid credentials"`
  whether or not the email is registered (no enumeration). Don't let anyone probe who exists or who did
  what.

- **Authorization is default-deny.** Server-side, you can only read/modify what's yours unless access is
  explicitly granted. Under Model A your personal layer is private; viewing someone else's layer is a
  deliberate, scoped sharing feature, never the default. **Never rely on the client to enforce access.**

- **Passwords.** Always hashed (werkzeug), never logged, never returned. Failure messages are generic.

- **Minimize collection.** Store only what's needed — pilot scope: email, hashed password, display name.

- **Auditability.** Sensitive / administrative actions (invite generation and consumption) are
  traceable. The trackable `invites` table (who created it, who consumed it, when) is an instance of
  this.

## Deferred: public-launch hardening

The pilot is a single-user / invite-gated app, so it **defers** the hardening required before open
public signup: email verification, password reset, rate-limiting, and bot defense. These are **required
before public signup is opened** and are tracked as a public-launch checklist — not optional once the
door is open to the world.

## Deferred: least-exposure follow-up

- **Trim email from the pending friend-request lists.** The accepted-friends list (`GET /api/friends`)
  now **omits email** (committed `e949c5f`) — display name only. The **incoming/outgoing pending-request
  lists still carry email**, because it is the **accept-by-email identifier** the client currently needs
  to act on a request. **Trim it once a friends-management UI exists** and requests can be accepted by an
  opaque id / display name instead — at which point the email is no longer needed client-side.

## Access-control model: current single-user state & multi-user rescoping map

> Access control is one of four areas whose decisions assume a single trusted user. The other three —
> fetching etiquette, product posture, and data defaults — are recorded in
> [single-user-assumptions.md](single-user-assumptions.md), which points back here rather than
> duplicating this map.

A read-only diagnostic (branch `main`) mapped how the app decides who may read/modify what. This
records the current model as an **accepted design for the single-user pilot** — known properties, not
defects — and the map for the eventual multi-user rescoping, so that work starts from a blueprint.
Framed as what the app **enforces and serves**, not as threats.

### Current model — coherent single-user, with per-user data already owner-shaped

- **Recipe writes gate on login + source-tier, not owner.** `PUT` and `DELETE /api/recipes/<id>` check
  only `source ∈ EDITABLE_SOURCES` (`app`/`test` editable; `seed` read-only) — they do **not** check
  `owner == current_user`. The **one exception** is `POST /api/recipes/<id>/image`, which does
  (`rec.owner != current_user.id → 403`) — the reference owner-check pattern. This is the single genuine
  write-ownership gap; it is inert today because there is only one user.
- **Per-user accruing data is ALREADY owner-shaped** (the R1/R3 rescoping, migrations 017–019, is
  complete): `ratings` has a **composite PK `(recipe_id, user_id)`** — one rating per (recipe, user),
  existing rows backfilled to the owner account (id 1) by `scripts/backfill_rescoping.py`; `cook_log`
  carries **`user_id`**; `recipe_queue`, `shared_posts`, `comments`, `friendships` are all keyed to
  `current_user`. Reads/writes here are user-scoped by construction — a user cannot touch another's rows.
- **The social layer already enforces owner/visibility** — share (your own recipe/cook), unshare
  (sharer only), comment-delete (author or post owner), comment-add (own-or-friend's post), each with
  non-leaking uniform 404s.
- **Recipes are globally visible.** `GET /api/recipes` returns all recipes to every user (`is_mine` is
  computed; nothing is owner-filtered) — a deliberate **shared-corpus / box model**: you see everything,
  and your *accruing layer* (cooks, ratings, queue) is yours. There is **no "private recipe" concept** yet.
- **Photos are served from a public route.** `/images/<file>` is unauthenticated static serving
  (`send_from_directory`, in `PUBLIC_ENDPOINTS`), with no per-file authorization; names are deterministic
  (`images/<slug>.jpg`) and thus guessable.

This is **coherent for a single-user app and is the accepted current design.**

### Deferred (by decision): write-ownership on recipe edits/deletes

`PUT`/`DELETE /api/recipes/<id>` don't enforce `owner`. **Safe today** — one user; no other account can
reach another's recipes. **Deferred to the multi-user rescoping** rather than fixed piecemeal, because
(a) there is no second user to protect, so no present benefit, and (b) it should land with the
visibility model below rather than leave the app in a half-owned state. **Fix shape when it lands
(expected small):** add `owner == current_user` on **app-tier** writes, mirroring the photo endpoint. On
current evidence this is a near drop-in — no inventoried `app`/`test` flow mutates a recipe the actor
doesn't own (created/copied recipes are owned by the actor; `seed` rows are `owner`-NULL, already blocked
by the source-tier gate) — but verify against the flows before the fix. **Preserve** the one deliberate
cross-owner write — `DELETE /api/test-recipes`, the bulk wipe of the shared throwaway `test` tier.

### Deferred (large): authenticated photo serving

`/images/<file>` is world-readable by URL. **Acceptable for the single-user app.** At multi-user, a
private recipe's photo must not be publicly fetchable. **Sizing — LARGE / multi-user infrastructure,
not a small fix:** the hard part is **not** unauthenticated loads (verified — no unauthenticated view
loads `/images`; the login hero is a Vite-bundled `/assets` file, not `/images`). It is **cross-user
visibility**: the feed legitimately renders friends' *shared* recipe photos, so a correct gate must be
**visibility-aware (own OR shared-with-me), not owner-only** — and that presupposes the
private-recipe/visibility model, which doesn't exist yet. **Fix options** (the choice depends on
hosting/auth decisions not yet made): route `/images` through an authenticated app endpoint that checks
own-or-shared before streaming (static → dynamic); or signed/expiring URLs; or per-user storage paths.
**Deferred to the auth/hosting work.**

### The rescoping map — one coherent future project

Multi-user access control is a **known future project** (not now), whose parts are **coupled** — doing
them piecemeal creates incoherence, so they land together when multi-user becomes the active goal:

- **Already in place (the foundation):** ownership column (`recipes.owner`), per-user ratings (composite
  PK), `cook_log.user_id`, per-user `recipe_queue`, and the friends/feed social layer with
  owner/visibility checks.
- **Still to do, together:** enforce `owner` on app-tier recipe writes (`PUT`/`DELETE`); a
  **recipe-visibility model** (private vs shared — today all recipes are visible to all);
  **authenticated / visibility-aware photo serving** (depends on the visibility model); trim the raw
  `owner` id from the single-recipe `GET /api/recipes/<id>` payload (least-exposure, matching the list
  route); and the **auth / hosting** decisions these ride on.

### Guiding principle for the interim (standing rule)

While the app stays single-user: **do not retrofit** the remaining single-user-shaped surfaces (the
write-enforcement and visibility gaps) — premature and incoherent in isolation — **but birth every NEW
per-user table owner-shaped from day one** (a `user_id`/`owner` column is free on a new table), so new
features don't add to the rescoping debt. The multi-user foundation gets built when **recipe-sharing
with friends** (the Tier-5 end goal) becomes the next feature, since sharing cannot be built correctly
on single-user assumptions. Until then, single-user feature work is fine and largely multi-user-neutral.
