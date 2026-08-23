# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**Chef's Choice** — a personal, single-user, no-auth recipe web app. The bet: recipes
are a commodity; the scarce asset is **outcome data** — what gets cooked, how it's rated,
and how people modify it. Everything is built to capture structured, timestamped signal
(ratings, cook history, per-person modifications) that can later ground an LLM via RAG.

Key features: quantity scaling (½×·1×·2×·custom), metric/imperial + volume→weight
conversion, cook-gated star ratings, a cook log, per-person recipe versions, and an
import pipeline from Paprika native exports.

## Read these first

- `OVERVIEW.md` — 2-minute orientation and vision
- `CODE_WALKTHROUGH.md` — guided tour, architecture, and living history
- `ROADMAP.md` — features by priority tier
- `docs/design-decisions.md` — "used cookbook" design direction, Round 1/2 staging
- `docs/import-reference-15.md` — regression baseline for the 15 verified recipes

## Tech stack

- **Backend:** Python 3 + Flask (≥3.0) + SQLAlchemy (≥2.0). Single small backend serving a JSON API +
  the built frontend. The serve path queries **entirely through SQLAlchemy** (`app.py::orm_session()`) —
  the raw `sqlite3` path is gone. See `docs/migration-plan.md`.
- **DB:** **SQLite by default** (`recipes.db`, git-ignored, local-only — a fresh clone runs offline, zero
  setup); **Postgres in production**, opt-in via `DATABASE_URL=postgresql+psycopg://…`. The SQLite→Postgres
  migration is **✅ complete** (Alembic owns the PG schema via `alembic/`; the `migrations/*.sql` files are
  SQLite-only history; the app is proven + dual-dialect-CI-tested on both). See `docs/migration-plan.md`.
- **Frontend:** Vanilla JS (`static/app.js`), CSS3 with design tokens, Spectral typeface — no framework,
  but **built by Vite** into `dist/` (git-ignored) which Flask serves; TipTap powers the method-step editor.
- **Tests:** pytest (backend) + Node's built-in `--test` runner (JS suite is **zero-dep** — runs on the
  source without `node_modules`; the app build itself uses Vite + TipTap).
- **CI:** GitHub Actions runs pytest w/ coverage, JS tests, and a SonarQube scan on push/PR.

## Commands

```bash
# Setup (fresh clone → working app at http://localhost:8000)
python3.13 -m pip install -r requirements.txt   # Python runtime: 7 packages — flask,
                                                #   flask-login, SQLAlchemy, alembic, psycopg,
                                                #   pillow, pillow-heif
npm install                          # frontend deps: Vite (build) + TipTap (step editor)
npm run build                        # build the Vite bundle → dist/ (git-ignored)
                                     #   REQUIRED: Flask's "/" serves dist/index.html — skip this and / 500s
python3.13 build_db.py               # apply migrations + load seed.py → recipes.db (never wipes your data)
python3.13 app.py                    # serve the built frontend + API at http://localhost:8000

# Active development (two processes, hot-reload)
npm run dev                          # Vite dev server on :5173 (HMR); proxies /api + /images + /fonts → Flask
FLASK_DEBUG=1 python3.13 app.py      # Flask on :8000 (API + images/fonts). Open the app at :5173.
                                     #   FLASK_DEBUG=1 = reload-on-edit + error pages. OFF by default:
                                     #   the setup block's bare `app.py` is a normal server, which is
                                     #   what the cold-start CI job runs as a stranger would.

# Backup before risky DB work
python3.13 backup.py                 # timestamped copy → backups/

# Tests
python3.13 -m pip install -r requirements-dev.txt   # one-time: pytest
python3.13 -m pytest                 # Python suite
node --test tests/js/*.test.js       # JS suite (zero-dep; scaler, factor-sync, step-adapter)  [also: npm test]
```

After editing frontend source (`static/*.js`, `static/styles.css`), rerun `npm run build` (or use the
`npm run dev` loop). After editing `seed.py`, rerun `build_db.py` then restart `app.py`.

## Architecture & conventions

**Content vs. Your Data — the central rule.** Content (recipes, ingredients, people) lives
in `seed.py` and is rebuilt on every `build_db.py`. User data (ratings, cook history,
per-person changes) lives in `recipes.db` and is *never* touched by rebuilds. Enforced by
two tiers: `source='seed'` (rebuilt) vs `source='app'` (preserved).

**Shared "brain" modules** — used at both build-time and serve-time:
- `weights.py` — volume↔weight matcher + King Arthur density lookup
- `stepscale.py` — method-text quantity scaler
- `static/scaler.js` — mirrors the above on the client; kept in sync by
  `tests/js/factor-sync.test.js`. **If you change conversion factors in `weights.py`/
  `stepscale.py`, update `scaler.js` too** or the sync test fails.

**Import pipeline** — three separate stages so a new source never touches core logic:
`paprika_native_reader.py` → `import_cleanup.py` → `import_write.py`, orchestrated by
`import_runner.py`. Guiding rule: **decline-over-guess** — extract the clear cases, *flag*
the ambiguous ones to the `import_flags` review queue, never silently mis-structure.
Import status and counts live in ROADMAP.md.

**Schema** evolves via numbered, apply-once migrations in `migrations/`. Add a new numbered
file rather than editing existing ones; `migrate.py` applies them safely.

**Design** follows a Round 1 / Round 2 split; for the current stage and the reserved R2
hooks, see `docs/design-decisions.md`.

## Voice: the words in the app, and the words about it

From the owner's two style guides. These rules are **stated, not derived.**

An earlier version of this section derived its rules by measuring the 36 library descriptions in
`seed.py` and the 35 error strings in `app.py`. Those were written by an earlier Claude Code session.
They are an example of the voice being avoided, not evidence of it, so the measurement was circular
and every number it produced is void. **Do not support, soften, or amend any rule below by measuring
an existing string, and do not treat a shipped string as a precedent.** The 36 entries are
model-written copy awaiting rewrite.

### The surface split, which governs everything below

The register changes with the surface. Every rule in this section is marked for the surface it
governs.

- **`[A]` UI microcopy and recipe headnotes.** Library and ingredient entries, refusal and error
  messages, empty states, button labels, placeholders, guidance text, and anything generated into the
  app. **Takes contractions and second person.**
- **`[B]` Writing about the app.** README, `ROADMAP.md`, `docs/`, analysis, review files, commit
  bodies, any capstone writeup. **Drops most of that and leans on the concrete numbers instead.**
- **`[A+B]`** governs both.

Guide one describes formal and technical writing. Guide two describes the deliverable voice for this
project. **Where they differ, guide two wins on surface A.**

### Punctuation and mechanics `[A+B]`

Listed first because guide one says these are the rules that actually get checked, and the ones to
keep if anything has to be trimmed.

- **No em dashes.** Use commas, parentheses, or a new sentence.
- **No semicolons.** Two sentences instead.
- **No rhetorical mid-sentence colons** ("The reason is simple: ..."). Guide two states this flat.
  Guide one's exceptions stand, because they are not rhetorical. A colon is fine after a run-in
  heading, before a list, or introducing a URL or an equation.
- **Do not open a sentence with Because, Although, While, or Since.** Restructure so the main clause
  leads.
- **US spelling**, everywhere. Color, flavor, savory, chili, labeled, centimeters, caramelized.
- **Ranges written out in full**, everywhere. "235 to 256", not "235-256". Bracketed intervals like
  [0.03, 0.97] keep their format.
- **No Latin.** No a fortiori, no i.e., no vs. in prose.

### Contractions and person

- `[A]` Contractions are fine. Second person is fine. This is copy read mid-cook.
- `[B]` Lighter on contractions. Lean on the concrete numbers instead.

### Sentences `[A+B]`

Short over compound. One idea per sentence. Split a long sentence into two rather than joining it with
punctuation. Vary the length enough that it does not read like a list.

`[A]` For a library entry, **39 to 73 words describes the spread that exists, not a range to hit.** It
is neither a floor nor a target. Do not pad an entry to reach the bottom of it, and do not trim one to
stay inside the top. A naming entry with one fact in it is finished when the fact is stated. Forcing
variation is the same disease as forcing uniformity.

### Concreteness `[A+B]`

Specifics over abstractions, always. A number, a name, an object. When naming an idea, **anchor it in
something physical rather than a category noun**: "the used cookbook", "handwriting in the margins",
"the journal is the history".

**Physical is necessary, not sufficient.** "Aged in earthenware" is physical and does no work, so it
goes. "Salted to make it undrinkable, which takes it out of the liquor rules" is physical and explains why the salt
is there, so it stays. The mechanism rule below is what separates them.

`[A]` **Going vaguer is not simplifying.** A specific word swapped for a general one is a loss dressed
as a simplification. Two ingredients became two things, black pepper became pepper, ten to eighteen
centimeters became the size of a small banana. Precise and plain are not in tension. Where a term
needs a gloss, add the gloss and keep the term.

### Explanations `[A+B]`, and stricter on `[A]` because the reader cannot look anything up

- **Give the mechanism, not the restatement.** The test is whether removing it leaves the reader
  asking *but why?*
- **A technical term used as an explanation is not an explanation.** "The kelp brings glutamate and
  the fish brings inosinate" reads as though it explains why the two together taste so savory, and it
  only does for a reader who already knew. Say what the thing does. Two different savory compounds
  multiply instead of adding up.
- **Gloss an unusual term at first use, in ordinary words.** Terms of art are fine and stay, but on
  surface A they stay only if they can be glossed in the same breath. Otherwise cut them.
- Plain-language point first, then the detail. Concrete examples beat abstract definitions.
- **Do not explain the fun fact.** A good fact does not need its lesson attached. Trust the reader to
  take the point. "Salted to make it undrinkable, which takes it out of the liquor rules" is the interesting half.
  Adding "which is why you taste before you season" explains the joke and takes it away. This rule and
  the mechanism rule above divide cleanly. **An instruction that would otherwise be arbitrary earns
  its reason. A fact that already implies the instruction does not need it spelled out.**

### Structural tics `[A+B]`, and stricter on `[A]`

A report is read once, top to bottom, so a repeated shape is a mild irritation. **A library is read as
a list**, twenty entries stacked on one screen, so a repeated opening shape is visible in a way it
never is in prose.

- Do not repeat the same rhetorical shape across consecutive paragraphs, **especially "X, not Y" as an
  opener.**
- Do not stack claim-colon-elaboration sentences back to back.
- Do not run several paragraphs of near-identical length and construction.

### Avoid `[A+B]`

- **Marketing register.** Elevate, seamless, journey, delight.
- **Throat-clearing and hedges.** Start at the point. No *generally*, *typically*, *often considered*.
  Where something genuinely varies, name what varies instead of softening the sentence.
- **Gamification language.** Counts, streaks, leaderboards, perfection. **This is a product
  constraint, not only a prose one.** See the achievements framing in
  [docs/product-vision.md](docs/product-vision.md) and `ROADMAP.md`.
- **Any line that flatters the reader for using the app.**
- **Showy words.** Delve, crucial, notably, moreover, furthermore, leverage, utilize, underscore,
  pivotal, landscape, realm, comprehensive, "it is worth noting." The test is whether a careful human
  writer would use that word there.
- **The other tells.** "not just X but Y", "that said", "the key is", triads and balanced clauses
  built for cadence rather than content, explaining the obvious back to the reader, and sentences that
  summarise what you just said instead of telling the reader something new.

### Emotional register `[A+B]`

Understated. **The feeling comes from the detail, not the adjective.** Warmth is allowed but has to be
earned. **Record the care, never farm it.** The app does not congratulate, reassure, or narrate.

### Numbers and evidence

- `[B]` Say what was measured, at what sample size, with what uncertainty. State limitations plainly
  and early rather than defending against them. Pull figures into the text rather than writing "see
  Figure 3."
- `[A+B]` Concrete figures over adjectives. **Distinguish a single-instance result from a general
  one**, which on surface A means never stating one source's claim as settled fact.

### Tone `[A+B]`

Confident without overclaiming. Own weaknesses directly, because a stated limitation reads as rigor
and a hedge reads as evasion. No filler. No summary that repeats what was just said.

### Working process for prose

Andy rewrites prose after a draft exists. **Hand him a complete draft to cut, never an outline and
never three options.** Flag fragments and grammar problems, then let him make the final wording call.

### Existing conventions in the code

Match these so new strings sit beside old ones without looking foreign. They are a consistency
constraint, **not evidence of the voice.** The strings they describe were model-written too.

- Errors are lowercase with no terminal full stop.
- Empty states name the absence and the next action, and nothing else. Never apologise for emptiness.
  Never fill it with encouragement.
- Pairings and lists are bare lists, with no framing sentence.

The docs still use em dashes and semicolons heavily and are converted in one deliberate pass later.
See the deferred entry under Known limitations and tech debt in `ROADMAP.md`.

## Working conventions

How this project is run:

- **Read-only inspection first.** Inspect and report before changing anything; see the real
  data before acting.
- **Preview-first for visual/UX work.** Before building any visual or UI change for real, build a
  throwaway mock under `preview/` (gitignored) using the real design tokens + bundled fonts, openable
  over `file://` with no app/DB/git changes, and iterate on it until the look is chosen — describing a
  design in words is not a substitute. **Previews MUST use the app's ACTUAL material as closely as
  possible — the REAL design tokens, REAL bundled fonts, and REAL existing components / markup / assets
  pulled VERBATIM from the code** (the `styles.css` classes, the real markup, the real SVG/asset for any
  existing graphic like the paperclip / Polaroid). **NEVER redraw, approximate, or invent a stand-in for
  an element that already exists in the app.** When an existing designed element (paperclip, Polaroid,
  card, pill, scaler, icon) appears in a mock, it must be the REAL one, **verbatim**. If a real element
  can't be cleanly found/lifted, **STOP and report — do not draw a substitute.** An approximated element
  in a returned mock is a **DEFECT to re-lift, not something to evaluate as-is.** (This rule exists
  because approximated previews defeated the exercise **twice in a row** — a generic white Polaroid + a
  bandaid-lozenge for the real paperclip; a redrawn icon — and the whole point is judging what the
  thing will ACTUALLY look like, not a look-alike.) After building any preview, ALWAYS open it in the
  default browser with the macOS `open` command (e.g. `open preview/feed-look.html`) — never just report
  the path and wait. A built preview that hasn't been opened isn't done. Exception: confirmed tiny CSS
  tweaks to a treatment already seen.
- **Previews must exercise the REAL DISPLAY TRANSFORM, not just the real tokens and fonts.** Real
  markup + real CSS is NOT sufficient when the value being judged is *computed* on its way to the
  screen. Every early O-c-1 annotation preview injected the raw stored `qty` instead of running it
  through the ledger's actual `amountText(_, 1)` → `abbrevUnits` pipeline. **Measured consequence:**
  full-word amounts wrapped to **two lines** inside the fixed 80px amount column, where the abbreviated
  forms production actually renders fit on **one** — so four rounds of treatment judgement were made
  against a wrapping problem that does not exist, and nearly locked the wrong design. This is the same
  rule as the verbatim-components rule above, one layer deeper: if the app transforms a value before
  displaying it (scaling, abbreviation, unit conversion, truncation, linkify), the preview must call
  that transform.
- **Propose a spec and STOP for approval** before building anything non-trivial; don't
  draft-and-commit in one shot.
- **Present a full diff and wait for approval** before applying edits.
- **Stage work in per-stage commits;** both test suites (`python3 -m pytest` and
  `node --test tests/js/*.test.js`) green at each commit.
- **Stage UI/client work per-concern, exactly like backend — no omnibus build prompts.** A client
  page is built in checkpointed stages, each ONE concern with its own stop-for-review, not one prompt
  that resets the tree, adds fonts, writes the CSS, wires the JS, and seeds demo data all at once. "It
  stops before commit" is NOT "it was checkable along the way": when many concerns land in a single
  large diff, a wrong call in the middle (e.g. a client wired to an unverified endpoint shape) rides
  along invisibly instead of surfacing at its own seam. For a feed/page build that means roughly:
  tree-reset + font (trivial) → static render you can look at → wire comments → compose modal → demo
  seed — each stopping for review. The diagnostic-first and preview-first rules already govern the
  thinking; this governs the build's granularity.
- **Say whose hours an estimate counts.** Every estimate here has at least two answers that differ by
  tens. One is a person doing the work by hand. Another is the model drafting with Andy reviewing. Both
  are real and they answer different questions, so state the basis in the estimate itself. The saving is
  large for generation and search, and **near zero for anything needing senses or standing**, such as
  verifying a photo, reading a physical label, or making a judgement about the world. Baseline, method
  and the running tally live in **[docs/estimating.md](docs/estimating.md)**.
- **Conventional Commits:** `feat` = new user-facing capability, `fix` = bug fix,
  `chore` = routine/inert groundwork; the summary line reflects what actually changed.
- **Never push without explicit approval;** after an approved push, watch the GitHub
  Actions run and report green/red.
- **The import runner writes only with `--yes`** and takes a backup first.
- **Blast-radius follows the DATA, not the field.** For any change to the data model, `seed.py`,
  or the build/seed pipeline, scope the analysis to the *rows being changed* (their
  slugs/ids/counts/existence), not just the column/token edited — and grep `tests/` **and** the
  fixture harness (`tests/harness.py`), not only app code. Fixtures and tests are part of the blast
  radius.
- **A dry-run that touches anything the tests build on must RUN THE TEST SUITE,** not just DB/count
  assertions. When a change touches seed content, the build pipeline, fixtures, or schema, one
  `pytest` run in the dry-run copy (after the edit) surfaces fixture coupling before it reaches
  live, at ~zero cost.
- **"Correct data + red suite" is still STOP-before-commit** — but it isn't data corruption: don't
  auto-revert correct live data over a fixable test issue; surface the choice.
- **When you change HOW code reaches the DB (new engine/session/connection path), verify the test
  harness redirects THAT path to the test DB — and PROVE it by running the suite with `recipes.db`
  HIDDEN (the CI condition).** "Suites green locally" is meaningless if the suite is silently hitting
  the *real* `recipes.db` instead of the test's temp DB. A frozen-at-import engine bypasses
  `make_kitchen`'s redirect (it only rebinds `app.DB`/`build_db.DB`/`migrate.DB`); use a **call-time
  factory** that reads the redirected module-global `DB` (see `app.py::orm_session()`, mirroring
  `db()`). This is a *variant of the dry-run-must-run-tests rule*: both are "green locally because the
  tests aren't exercising what CI exercises" — the unifying guard is **run the suite in the CI-like
  environment (deps as CI installs them, `recipes.db` absent) before trusting green.**

*Why the first three exist (the seed→app miss):* converting the 5 seed recipes to app (flip `source` +
empty `seed.py`'s `RECIPES`) was proven rebuild-safe on a DB dry-run and applied correctly to live,
yet broke **31 pytest tests** — the suite builds every fixture DB from `seed.py`'s `RECIPES`
(`make_kitchen` → `build_db`), coupling to the seed slugs (~90 references across `tests/`), not the
`source` column the blast-radius had grepped. The DB dry-run passed because it only asserted on the
DB; a `pytest` run in the same scratch copy would have caught all 31. Reverted cleanly. **Resolved —
shipped in migration 016 (a later session):** the tests were first decoupled to seed their own fixtures
(`fixtures.TEST_RECIPES`), then the 5 (`aloo-gobhi`, `bulgogi-bowls`, `gai-yang`, `mussakhan`,
`no-knead-bread`) were flipped to `source='app'` and their `seed.py` defs removed (`RECIPES` is now
`[]`). They are ordinary owned app recipes that **no longer lag from build_db's seed-rebuild** — a
rebuild leaves them intact (0 seed duplicates). This is DONE, not a pending follow-up. **NB:** the
ingredient **library** (~36 rows) is *still* seed-rebuilt on every `build_db` (intended — the seed
'bones' stay); any remaining 'stale linked-ingredient' symptom, if real, lives in the library
records/labels, **not** the recipe source-tier, and is diagnosed separately — not re-fixed via a
`source` flip.

*Why the fourth exists (the Stage-1b CI miss):* the converted ORM read routes used `models.SessionLocal`
(frozen at import to the default `recipes.db`). `make_kitchen` redirects `app.DB`/`build_db.DB`/`migrate.DB`
but not the frozen engine, so the ORM silently queried the **real** `recipes.db` during tests — green
locally (the file exists and its seed-derived ingredients/people happened to match the fixtures) but red
in CI (no `recipes.db` → empty DB → `OperationalError`). Fixed by `orm_session()` reading the redirected
module-global `DB` at call time. Hiding `recipes.db` and re-running `pytest` reproduces the CI failure in
one step — the standing guard for any DB-access-path change.
