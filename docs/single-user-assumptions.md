# Decisions contingent on one trusted user

Many choices in this app are **correct for one trusted person on their own laptop** and become wrong,
or merely arbitrary, the moment that stops being true. Each was made deliberately and most are
documented where they live — but they are scattered across seven files, so flipping the premise would
mean rediscovering them one bug at a time.

This file is the **single list to re-read when the premise changes**. It is not a plan and not a
to-do: it records what was assumed, where the assumption is implemented, and what specifically comes
back into question. The route is a separate exercise; this is the map.

**Scope note.** The multi-user *access-control* rescoping is already mapped in detail in
[SECURITY.md](SECURITY.md#access-control-model-current-single-user-state--multi-user-rescoping-map) —
ownership enforcement, the visibility model, authenticated photo serving. That map is not repeated
here. This file covers the assumptions that live **outside** it: fetching etiquette, product posture,
and data defaults, plus the security items that map doesn't name.

---

## Security

**The SSRF guard's accepted gaps are argued from who the user is.** `url_fetch.py` resolves the
hostname and re-checks every redirect hop, and says of what it does not close:

> ⚠️ TOCTOU IS DOCUMENTED, NOT CLOSED, AND THAT IS A DELIBERATE CHOICE. … The race needs an attacker
> controlling DNS for a name the user pasted AND sub-second timing … **Revisit if this app ever accepts
> URLs from someone who is not its owner.**

The reasoning is sound and the trigger is already written into the source. What this file adds is that
the trigger is now foreseeable rather than hypothetical. The closure it describes — connecting to the
already-validated IP while preserving `Host` and passing `server_hostname` for SNI — was rejected
because a hand-rolled transport's failure mode (silently broken certificate validation) is worse than
the race. That trade is re-argued, not simply reversed, when the premise changes.

**The `SECRET_KEY` fence uses `DATABASE_URL` as a proxy for "production."** A Postgres URL makes the
app refuse to start without `SECRET_KEY`; SQLite gets a dev fallback ([SECURITY.md](SECURITY.md), the
fail-closed principle). This is a good fence for **one deployment shape** — laptop SQLite vs hosted
Postgres. It stops meaning "production" as soon as there is a staging environment on Postgres, a
laptop pointed at a shared database, or a second deployment of any kind. The fence isn't wrong; its
*proxy* is what's single-deployment-shaped.

**The SonarQube quality gate is deliberately unenforced** (see ROADMAP, "Known limitations & tech
debt"). CI runs the scan and never checks its verdict. The reasoning is specific — default thresholds
rather than chosen ones, and a structurally unreachable `new_coverage` condition because
`static/app.js` is 49% of coverable lines at 0.0% with no DOM harness — and the five open issues are
individually examined. That reasoning is about *this* repo's coverage shape, not about how many people
use the app. It is listed here because "nobody is depending on this but me" is part of why an
unenforced gate has been tolerable, and that part expires.

---

## Fetching etiquette

**The user agent is honest, and no browser impersonation is used.** `url_fetch.py` states the
measurement it was decided on:

> Measured across the 15 sampled sites, an honest identifier costs ZERO pages: 14 of 15 served it, the
> same 14 that served a Chrome string, with byte-identical content.

⚠️ **That measurement is now known to be out of date.** Food Network and Blue Apron are reported to
refuse the honest identifier. This has **not** been measured into the repo — it is recorded here as a
known gap in the evidence, not as a finding, and the claim in `url_fetch.py` still says "costs ZERO
pages." Re-measure before either changing the identifier or re-affirming it. The decision itself was
never "impersonation is ineffective"; it was "impersonation buys nothing **and** makes us dishonest
about who is calling." Only the first half is in question.

**There is no `robots.txt` check**, justified as:

> robots.txt governs CRAWLERS … This is a single fetch of a single page the user has explicitly pasted,
> on their behalf, no different in kind from their browser opening it. There is no traversal, no
> discovery, and no second request.

That argument holds precisely because of **volume and provenance**: one page, pasted by the person who
wants it. It weakens with many users pasting many URLs through one server, and it fails outright for
anything that discovers or traverses. The trigger is not "multi-user" as such — it is *aggregate
request volume from one host*, which multi-user is the likely cause of.

**Refusals are treated as acceptable losses.** A site that says no produces a refusal *value* with a
reason shown to the user (maangchi.com's Cloudflare 403 is the modelled case), and nothing retries,
queues, or works around it. That is right when the person who pasted the URL is standing there and can
read the reason and decide. It is a different proposition when a refusal is one of many, seen by
someone who cannot act on it.

---

## Product posture

**Import opens in the editor to be corrected before confirming** (`072bd6f`). The baseline is captured
at first save rather than at fetch, so corrections made before confirming leave no annotations and
edits after it do. This assumes a user who **will** correct things, understands the difference between
fixing a parse error and changing a recipe, and is willing to do that work at import time. A user who
imports and walks away gets an uncorrected recipe whose birth state is the publisher's text plus
whatever they didn't fix.

**Decline-over-guess** is the guiding rule of the import pipeline (CLAUDE.md, OVERVIEW.md,
`import_cleanup.py`): extract the clear cases, flag the ambiguous, never silently mis-structure. It
routes ambiguity to a **review queue that a person reads**. The rule stays right; what is
single-user-shaped is the assumption that flagged items are seen at all. `import_flags` has 597 rows.

**Parse defects were allowed to accumulate before being fixed.** The August 2026 damage survey
(`docs/import-damage-survey-2026-08.md`) measured what the importer left behind across the whole
corpus *after* the corpus existed, and fixes have been landing since. That sequence — ship, measure the
damage, repair — is affordable when the damaged data is your own and you remember which recipes are
suspect.

---

## Data defaults

**Bare "kosher salt" resolves to Diamond Crystal.** `weights.py` is explicit that this is a personal
default, not a general one:

> Single-user default: bare "kosher salt" is genuinely ambiguous (Diamond Crystal ~8 g/tbsp vs Morton's
> ~16 — an imported recipe assuming Morton's would convert ~2x light). We resolve it to MY kitchen's
> salt (Diamond Crystal) on purpose, not by guessing.

This is the clearest case in the file: a **correct** single-user decision that becomes a **wrong**
multi-user one, silently, with a 2× error in a direction the user cannot see. Everything else here
degrades; this one inverts.

**The 298 backfilled `reason='original'` baselines are a one-time compromise.** O-b's backfill
(`scripts/backfill_original_snapshots.py`) set every existing recipe's baseline to its **current**
content rather than its true birth state, because the birth state was not retained. Change-tracking
therefore starts fresh from that moment: edits made before the backfill are invisible and always will
be. Accepted because the only person whose history was flattened is the one who made the call.

---

## The pattern worth copying

⚠️ **Correction to the brief:** the safe-temperature design described as "cite a source's range, the
preference within it is the user's" **does not exist in this repo.** What exists is two different,
narrower things: the never-scale guard in Phase 1d, where any number adjacent to a temperature is
blocked from scaling *above* the heuristic rather than by it ("a missed quantity is a visible, harmless
inconvenience; a wrongly-scaled temperature is a silent hazard"); and the bound on AI generation, where
food-safety, allergen and storage-safety claims stay **sourced-or-blank** because "a wrong claim there
has real stakes a disclaimer doesn't cover."

Those two share the shape the brief was reaching for, and it is worth naming: **where the stakes are
real, the app carries the source and refuses to supply the judgement itself.** It does not invent a
temperature, and it does not let a heuristic move one. If a "cite the range, let the user choose within
it" feature is wanted, it would be new work — and the reason it is a good pattern is that it is the one
posture on this list that does **not** depend on who the user is.

---

## What is NOT on this list

Deliberately excluded, because they are already mapped or already correct:

- The access-control rescoping — see [SECURITY.md](SECURITY.md). Ownership enforcement on recipe
  writes, the recipe-visibility model, and authenticated photo serving are named there with sizing and
  a standing interim rule.
- Public-launch hardening (email verification, password reset, rate limiting, bot defense) — already
  deferred explicitly in [SECURITY.md](SECURITY.md#deferred-public-launch-hardening).
- **Ratings are not, in fact, uniformly cook-gated**, so there is nothing single-user-shaped to record.
  `POST /api/recipes/<id>/rating` accepts a rating for a never-cooked recipe (`app.py`: "NOT
  cook-gated: rating an uncooked recipe is allowed"), pinned by `tests/test_api.py`. The cook-gated
  path is the *combined* "Mark cooked & rate" flow. The design intent — outcome data comes from
  cooking — is real and is why `aggregateRating` is dropped on import, but the gate is a UI affordance
  rather than a server rule.
