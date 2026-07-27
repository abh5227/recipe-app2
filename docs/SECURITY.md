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
