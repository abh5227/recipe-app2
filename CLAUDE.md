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
- `docs/what-the-library-is-for.md` — the ingredient library's standing purpose. Read before
  writing any rule that admits, cuts, renames, or merges a row.
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
an existing string, and do not treat a shipped string as a precedent.** ⚠️ **Updated 2026-09-20.**
The 36 entries were model-written copy, and they were deleted rather than rewritten (migration 046).
They were an early demo of what an ingredient library would look like. The rules below stand on the
two style guides alone, which is what this section always said they did.

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

- **FIX BY RULE, NOT BY ROW.** Every data or display correction is written as a rule that (1) runs
  over every existing recipe, (2) runs in the importer for new recipes, because other people will
  import, and (3) has tests. Where a rule cannot decide, it **flags** the recipe (an import flag and
  a review list) instead of guessing. A person decides once, and that decision is recorded as data
  the corpus pass reads, never as a hand edit to one row. One-off row fixes are allowed **only** as
  recorded decisions on flagged cases.
  *Why:* a hand-fixed row is invisible to the next import and to the next corpus pass, so the same
  defect returns on the next recipe and nothing says it was ever decided. The 300-recipe heading
  repair and the importer that now shares its rules
  (`import_cleanup.plan_step_rows`, imported by `scripts/convert_step_headings.py`) are the shape
  this takes: one rule set, two callers, one review CSV per decision a rule could not make.
  ⚠️ **ONE RULE SET MEANS ONE FUNCTION, AND A COMMENT SAYING SO IS NOT THE SAME THING.** Both files
  said they shared the rules. They had drifted: the importer called `move_link_out_of_label` when it
  lifted a lead-in label and `convert_step_headings._lift` did not, so the corpus pass wrote a
  heading reading `Wilt the [[spinach]]`, which the renderer escapes and never linkifies, so the
  brackets would have printed. **Apply a rule where the row is MADE, in every caller, and give the
  corpus pass an invariant sweep as well** ("no heading carries link markup" reads the headings, not
  a list of rows). **A repair keyed on a step row id cannot see a label an earlier pass already
  lifted**, so a repair that assumes the defect is still in place is only correct by accident of
  order. The test that catches this class has to RUN the scripts, which nothing did until
  `tests/test_corpus_passes.py`.
- **EVERY SCRIPT THAT CAN WRITE NAMES ITS DATABASE, AND LIVE IS NOT A DEFAULT.** It takes the path as
  an argument, defaults to a dry run, and exits on live `recipes.db` without `--i-mean-live`. The one
  guard is `scripts/corpus_guard.py::refuse_live` and every caller imports it. A live run is a
  sentence a person had to type.
  ⚠️ **THE RULE USED TO SAY "A CORPUS PASS", AND THE GAP WAS EVERYTHING ELSE.** Measured in the
  pre-push review: 20 of 24 scripts could write, **13 of them hardcoded live `recipes.db` with no way
  to point them anywhere**, and `archive_import_flags.py` took a `--db` whose DEFAULT was live, so
  `--apply` from a shell with no path argument wrote straight to the real database. `migrate.py` was
  among the 13, which made the repo's own instruction impossible to follow: `docs/data-repairs/README.md`
  says to rehearse the whole chain on a copy, and `migrate.py` is step one of that chain. It takes
  `--db` now. `tests/test_corpus_passes.py` walks the folder rather than naming four scripts, so the
  check holds for the next one written.
- **A SPENT ONE-TIME BACKFILL IS ARCHIVED, NOT LEFT RUNNABLE.** `scripts/applied/` holds the 16 whose
  work is done, each refusing to run with a line saying what it did and how it was verified spent.
  They keep their docstrings and their tests, because what they are still good for is the record of
  what was done to the data. ⚠️ **The refusal is at RUN time, not import time**: eight carry a test
  that imports the module to pin the transform it applied, and an exit on import would delete that
  record as surely as deleting the file. A spent backfill is the most dangerous file in the repo — it
  names live with no `--db`, it writes on a flag somebody could type from memory, and its upside is
  zero because the work is already done. Three are irreversible on SQLite.
- **THE GUARD KNOWS THE FILE, NOT THE NAME OF IT.** `scripts/corpus_guard.py::is_live` compares the
  resolved path AND the device/inode, so `./recipes.db`, `scripts/../recipes.db`, a symlink and a
  HARD LINK are all one answer. A path string says nothing about which file it opens, and a string
  comparison let three of those four through. The resolved-path half stays for the fresh-clone case,
  where live does not exist yet and there is no inode to compare.
- **AND IT KNOWS WHICH FILE NO MATTER WHICH CHECKOUT ASKS.** `corpus_guard.live_db()` is the one
  absolute answer: `$RECIPE_APP_LIVE_DB`, else `~/.config/chefs-choice/live-db`, else the MAIN
  working tree found through `git rev-parse --git-common-dir`, whose parent is that tree from any
  linked worktree. A location it cannot determine **FAILS CLOSED**: every path is treated as live, so
  the write needs the sentence typed out.
  ⚠️ **IT USED TO ASK ITS OWN CHECKOUT, AND THAT UNDID THE WHOLE GUARD FROM A WORKTREE.** `is_live`
  compared against `BASE / "recipes.db"`, where BASE is the repo root of the file it was imported
  from. From the main tree it answered correctly. **From a detached worktree it answered False for
  the real database and `refuse_live` refused nothing** — measured 2026-10-01 from two worktrees,
  with the real 328MB file sitting where it always was. `migrate.py` made it worse by passing
  `base=BASE_DIR` explicitly. Three checkouts had three different ideas of what live meant, and
  `../recipe-app-serve` is a worktree whose whole job is to run against live. `tests/conftest.py`
  had the same bug from the other side: it installed the suite's guard on
  `parent.parent / "recipes.db"`, so a suite run from a worktree guarded an absent file and left the
  real one open. Both now ask `live_db()`. See `tests/test_live_location.py`, which proves it from a
  throwaway repo's linked worktree rather than from this one's `.git`.
- **THE TEST SUITE CANNOT OPEN THE LIVE DATABASE.** `tests/dbguard.py` patches `sqlite3.connect` at
  conftest import, so raw connections, SQLAlchemy and `app.orm_session()` are all covered by one
  patch. *Why:* `make_kitchen` redirects `app.DB` / `build_db.DB` / `migrate.DB`, and a test that
  names a path itself reaches straight past that redirect — one did, and `refuse_live` was the only
  thing between an ordinary `pytest` run and a real migration of 300 recipes. A redirect protects the
  door it is nailed to. ⚠️ **The ONE exception is `@pytest.mark.live_catalog`, and only for a
  `mode=ro` URI**, because the 7 catalog tests check the real 10,020-entry library and a fixture
  database has the tables with no rows. A marked test that opens live for WRITING is refused like any
  other.
- **AND THE SUITE ASKS THE DATABASE ITSELF, NOT ITS ADDRESS.** `tests/dbmarker.py` mints one random
  token per run, the harness marks the database it creates with it, and every path that writes,
  truncates or drops asks the connected database for that token first. *Why:* every other guard here
  answers a question about a NAME. `dbguard` compares a path, and its device and inode, against live.
  `urlguard` reads `$DATABASE_URL` and asks the dialect what it would open. Neither can see a harness
  pointed at a real database that is not live and sits in no variable: a copy of live under another
  name, a restored backup, a colleague's Postgres. A database this run did not create cannot produce
  the token, so it is refused whatever it is called, and the address checks stay in front as the
  first line.
  ⚠️ **THE MARK GOES ON AFTER THE BUILD, NOT BEFORE IT.** `build_db.build()` deletes a database with
  no `schema_migrations` table and recreates it once, and a freshly stamped empty file looks exactly
  like that, so a marker written first is discarded and every later check fails. The pre-build check
  is therefore a different question: the path must not exist, or must already carry this run's token,
  and must lie inside the directory pytest made for this test.
  ⚠️ **AND POSTGRES HAS TO EARN ITS FIRST CLAIM, BECAUSE THE HARNESS DOES NOT CREATE IT.** CI's
  service does, and `alembic upgrade head` builds the schema, so the first `reset_and_seed` meets a
  database with no marker. It may claim one only while every content table is EMPTY, which a database
  anybody cares about is not. A marker holding a different token is a harness database from an earlier
  run, which is what a developer reusing one test database sees on their second run, so the token is
  replaced rather than stopping the run. `current_database()` is compared against what the URL
  resolves to, through `urlguard.effective_database`, so there is one answer to which database opens.

- **A SCRIPT THAT CAN OPEN A DATABASE WIRES THE SHARED GUARD, AND THE SUITE CHECKS IT.**
  `tests/test_live_guards.py` walks `scripts/` plus `migrate.py` and fails on anything that can reach
  a database without `--i-mean-live` and `--db`. Stated over the folder, so the NEXT script written is
  covered before anyone remembers it. A read-only exemption is a named entry with a reason, and the
  same test asserts nothing on that list can write.
- **A DRY RUN NEVER WRITES INTO `docs/data-repairs/`.** A report goes to gitignored `reports/`;
  `--record` is what puts one in the committed folder, and it **refuses to overwrite a non-empty
  file**. *Why:* five scripts wrote their report on every run, their work is applied so a re-run finds
  0 rows, and **three committed records were truncated to their header lines at once, from DRY RUNS**.
  Restoring them from git was the only reason nothing was lost. A record is replaced by deleting it on
  purpose, which is a thing a person does and a script does not. Decision files a pass READS are
  inputs: they stay committed and nothing writes to them.
- **DURING A REHEARSAL, NEVER TYPE THE LIVE PATH. USE THE COPY'S PATH.** The guard is the backstop,
  not the plan. `--db recipes.db` to "test the guard" is how live gets opened: it was done during this
  round, on a script that did not yet have one, and only the fact that the pass had nothing to do kept
  it harmless. Point every command at the copy, and read live's sha256 and counts at the start of a
  session, at the end, and immediately before the first live write.
- **A SAVE KEEPS THE ROWS IT WAS GIVEN.** `write_plan_ahead` deleted every wait and storage row and
  inserted fresh ones, so each came back with a new AUTOINCREMENT id, and `serialize_recipe_content`
  records the wait id. A save that changed NOTHING therefore moved the snapshot bytes and cost the
  recipe its byte-equal short-circuit permanently. Observed on live: brioche-bread's entire
  difference from its baseline was `"id": 12` becoming `108` and `"id": 13` becoming `109`.
  **Rows are matched and UPDATED in place.** `_match_rows` pairs incoming rows to stored ones in two
  passes, and the order is the rule: **by wording first**, each stored row usable once, which is
  where an unchanged save and a pure reorder land entirely, then **by order** over what is left, so
  a reworded row is an EDIT that keeps its id rather than a deletion plus an addition. A new id means
  a genuinely new row, and a stored row nothing claimed is deleted.
  ⚠️ **"MATCHED" AND "MATCHED BY WORDING" ARE DIFFERENT QUESTIONS.** The second decides whether the
  stored MINUTES still describe the row's words. A row matched by order keeps its id and is RE-READ.
  Collapsing them would either re-read a wait nobody edited, which is the defect decision 1 fixed, or
  carry a reviewed figure onto wording it no longer describes.
  ⚠️ **AND THE POSITIONS ARE PUSHED OUT OF THE WAY FIRST.** `recipe_waits` and `recipe_storage` both
  carry `UNIQUE (recipe_id, position)` on BOTH dialects, so writing a reordered list straight back
  collides the moment two rows swap. Survivors go to negative positions in one pass and take their
  final places in a second. `recipe_steps` has no such constraint, which is why `write_recipe_rows`
  can assign positions directly and this dance lives only here.
- **A NOTE IS A ROW, AND recipes.notes IS A DERIVED COPY OF THOSE ROWS.** Migration 060 made
  `recipe_notes` with a kind, a step link and an ingredient-line link. `notes.py` is the shared
  brain the way `planahead.py` is for waits, and it restates nothing: `paragraphs` is the Python
  side of `note-blocks.js::noteParagraphs` and `kind_of` delegates to `import_cleanup.note_kind`,
  which reads the same `static/note-kinds.json` the client inlines.
  ⚠️ **THE TEXT IS STORED VERBATIM, LABEL AND ALL, AND THE KIND SITS BESIDE IT.** Measured over the
  177 corpus paragraphs: 27 lead with a label the kind table does not know (`Blind Bake`,
  `Tomato Bouillon`, `Borlotti`) against 23 that lead with one it does. Stripping a label would
  delete the only thing naming what the note is about, and storing the kind beside the words rather
  than instead of them is what let the corpus move byte for byte.
  ⚠️ **THE KIND IS A LOOKUP TABLE WITH A FOREIGN KEY, NOT A CHECK**, because SQLite cannot widen a
  CHECK in place and a sixth kind would otherwise be a create-copy-drop-rename on the table holding
  every note in the database.
  ⚠️ **AND IT MARKS ONCE.** `notes` left `snapshot_diff.CONTENT_FIELDS` when the column became
  derived. Diffing both would report one note edit twice, the second entry reading as the whole
  notes field replaced. It stays in the SNAPSHOT, because the column still round-trips, and it is
  simply not compared.
- **A WRITE PATH REFUSES WHAT IT CANNOT READ, AND A LIST IT CANNOT READ IS NOT AN EMPTY LIST.**
  `resolve_recipe_payload` checks `waits`, `storage` and `notes` before anything is written, both
  the container and each entry. *Why:* `write_notes` ITERATES what it is given, so a dict iterated
  to its KEYS and a list of numbers filtered to nothing. `notes: [1, 2, 3]` answered **200** and
  left the recipe with 0 note rows and a nulled column, `notes: {"text": "x"}` did the same, and
  `notes: 7` was a 500. The waits key had this check already, with a comment naming the exact
  failure, and notes was left out of the loop. Live carries 177 notes over 95 recipes and the text
  has no second home. ⚠️ **A BARE STRING STAYS LEGAL FOR `notes`**, because that is the previous
  client's single textarea, split by the same rule the corpus move used.
- **A COPY IS STATED OVER THE TABLE, NEVER OVER A LIST OF COLUMN NAMES.** `copy_recipe` builds both
  row inserts from the table's own rows and names only `COPY_RESET_RECIPE_FIELDS`, the small set it
  deliberately does NOT carry. *Why:* every hand-written list in that route has been short at least
  once. `heading_level` was missing and a copy FLATTENED every subheading; the review then measured
  five more on `recipe_ingredients` (`heading` from 052, and `catalog_id`, `link_confidence`,
  `link_rule`, `link_matched` from 033) and one on `recipes` (`total_includes_waits`, 058). **2,851
  of live's 3,572 ingredient rows carry a `catalog_id`**, so copying almost any real recipe dropped
  its entire library linkage, silently, with a 201. Stating the RESET means a column added tomorrow
  is carried by default, and `tests/test_copy_carries_everything.py` compares every column of every
  content table rather than the ones someone remembered.
  ⚠️ **AND `_copy_row_map` RANKS THE ROWS, it does not key on the position VALUE.** It claimed that
  could not collide, which is false for two of the four tables it serves: `recipe_steps` and
  `recipe_ingredients` carry no uniqueness on `(recipe_id, position)`. Two rows sharing one
  collapsed the map and remapped a wait's `step_id` to NULL.
- **A PASS PROVES ITSELF BEFORE IT COMMITS, AND A SECOND RUN IS A NO-OP.** Each recipe's gate runs
  inside its own transaction and rolls back rather than reporting on data already written. *Why:*
  the gates ran after every recipe had committed, so an abort was a post-mortem: on a 95-recipe
  pass that is a half-migrated corpus and a restore from backup. And both of
  `apply_note_decisions`' writes were bare INSERTs into tables carrying `UNIQUE (note_id,
  ref_index)` and `UNIQUE (recipe_id, position)`, so re-running it died mid-way with earlier
  recipes committed, after a dry run that had shown nothing wrong. An entry already in place is
  detected in the PLANNING phase, which is what makes the dry run a faithful preview of the real
  run.
  ⚠️ **AND THE GATE COMPARES THE ENTRIES, NOT THEIR COUNT**, for the reason the short-circuit rule
  gives: one entry leaving while another joins holds the count still.
- **THE GUARD KNOWS ABOUT `$DATABASE_URL` TOO, BECAUSE THE PATH IS A LIE WHEN IT IS SET.** Every
  pass rebinds `app.DB` and then reads through `app.orm_session()`, which prefers that variable
  over the file it was handed, and the guard only ever inspected filesystem paths. Measured with
  the two lines the passes use: `refuse_live` passed a copy under `/tmp`, the engine opened the
  test Postgres, and the pass read 6 recipes where the copy holds 300. With `--apply` against
  production that writes production while printing the copy's name. `refuse_live` now exits unless
  the run says `--i-mean-live`.
- **THE FIXTURE DATABASE IS PART OF THE BLAST RADIUS, AND REFERENCE DATA THE SCHEMA CREATES HAS TO
  SURVIVE A RESET.** `pg_harness.reset_and_seed` TRUNCATEs every table in the metadata, and
  `note_kinds` joined that metadata the moment `models.py` declared it. Nothing reseeds it, so
  after one reset the Postgres fixture **could not store a single note**: the kind foreign key had
  nothing to point at, every create carrying a note was a 500, and `write_notes` read its allowed
  kinds from the empty table so the fallback was missing too. ⚠️ **KEEPING IT OUT OF THE TRUNCATE
  IS NOT ENOUGH ON ITS OWN**, measured while testing that fix: one run of the old harness emptied
  it and the database stayed broken afterwards, so `ensure_note_kinds` puts the rows back from the
  one file that defines them. The gap that hid it: the Postgres leg runs two files and neither
  wrote a note.
- **A NOTE IS A PLAYGROUND. IT TAKES NO PART IN "YOUR CHANGES" AND COSTS A RECIPE NOTHING.** Andy's
  ruling. Editing a note, moving it between kinds, attaching it to a step or deleting every one of
  them mints no annotation entry AND does not take the recipe off the untouched list. Both halves
  need the notes OUT of `recipe_snapshots.content`, not merely out of the diff, so neither the rows
  nor the derived column are in the blob and `snapshot_diff` does not compare notes at all.
  ⚠️ **MEASURED BEFORE IT WAS BUILT, BECAUSE THE QUESTION WAS WHAT WOULD DISAPPEAR.** None of live's
  49 annotation entries is a note edit. The set is 49 over 20 recipes computed either way, with
  notes excluded as the new code does it and with `notes` restored to `CONTENT_FIELDS` as the
  running deploy does it, and 0 recipes carry notes text that differs from their baseline.
  ⚠️ **THE BASELINE WAS THE ONLY RECORD OF THE AUTHOR'S WORDS, SO THE RECORD MOVED.** Migration 061
  adds `recipe_notes_original`, written once per recipe by `scripts/notes_to_rows.py` and by
  `import_write.commit_plan`, read by nothing on the page and unknown to `snapshot_diff`. A
  playground is only safe if there is a way back.
  ⚠️ **AND THE STRIP RUNS FIRST IN THE CHAIN, WHICH WAS FOUND BY RUNNING IT LAST.** All 300 stored
  baselines name `recipe.notes` until the pass strips it. With `realign_baseline` ahead of it, the
  realign saw that difference, matched it against none of its three declared cases, and wrote 0
  baselines where it should have written 5.
- **A LIFTED LABEL IS A SUBHEADING ONLY WHEN A SECTION SITS ABOVE IT.** Andy's rule, and it makes the
  level a property of the RECIPE rather than of the label: with nothing above it there is no group to
  belong to, so it opens one. A label that names a COMPONENT ("To make", "For the", "If",
  "Make the X", "While …, make the X") is a section whatever sits above it. All four callers read
  what precedes the step before they lift, so `label_level(label, section_above=...)` cannot be
  asked a different question in two places.
  ⚠️ **IT APPLIES AT THE LIFT AND IS NOT SWEPT OVER EXISTING HEADINGS, AND THAT IS MEASURED RATHER
  THAN LAZY.** A sweep reads the level it has just written, so the first heading in a recipe always
  has nothing above it and opens a section, and every later heading that does not name a component
  becomes a subheading under that one. One pass over live's 243 headings changes **86 levels over 49
  recipes, 17 promotions against 69 demotions**, and a second pass changes nothing, so that is the
  rule's fixed point rather than a transient. The demotions are the damage. acqua-pazza loses both of
  its real sections (`To serve:` and `Garlic crostini:`), brioche-bread's "Shaping options" is
  DEMOTED against the alternatives rule it sits above, french-fries loses `Fry #1`, and
  kfc-spicy-chicken-rice-bowl, the case Andy flagged, ends with `Marinade` as its only section and
  `Assembly` demoted under it, which is worse than the seven subheadings under nothing it shows
  today. ⚠️ **An earlier version of this paragraph said 33 levels, with 5 of KFC's 7 promoted.** It
  was measured while `label_level` was answering SECTION for every label it was handed, which the
  independent review then fixed. A case a rule cannot settle is a recorded decision, not a wider rule.
- **THE AUTHOR'S NUMBERS NEED A RUN FROM 1, NOT AGREEMENT WITH THE ORDINALS.** "Only when the
  recipe's steps carry a consecutive 1..N sequence" is the rule, and demanding `number == ordinal` is
  stricter than that: an import that split one step into continuation lines pushes every later
  ordinal along, so the dal recipes carry a perfect 1, 2, 3, 4 at ordinals 1, 4, 6 and 7. The
  separator form is admitted when the numbers read in order form a gapless run from 1. Measured: 3
  more recipes and 10 more steps, every one the author's own numbering, 0 that are not.
  ⚠️ **THE BARE FORM IS NOT RELAXED**, so "2 cups flour" can never be admitted by a run it happens to
  fit. The ordinal and a following capital are the two pieces of evidence that keep it safe.
- **A LOOK-ALIKE LETTER IS REPAIRED BEFORE ANY RULE READS THE TEXT.** Two words in the 300 carry
  Cyrillic inside English sentences and each one defeated a later rule in silence: "МАКЕ THE
  CHICKEN:" never lifted its label because the rule wants Latin capitals, and "З. MAKE THE
  SEASONING:" could not be read as a number at all. `normalize_lookalikes` runs over a text only
  when it contains a Latin letter somewhere, so a sentence that really is in another script is left
  completely alone.
  ⚠️ **A LETTER NEVER BECOMES A DIGIT ON THE STRENGTH OF A SHAPE.** Cyrillic ZE looks like a 3, and
  what proves it IS the 3 is the author's own 1, 2, _, 4 run. `author_step_number` reads it and the
  number is then REMOVED, so no digit is ever written.
- **AN INGREDIENT NAME STARTS LOWERCASE, AND THE CORPUS CANNOT BE THE AUTHORITY ON THE EXCEPTIONS.**
  Proper nouns, brands and acronyms keep their capitals, from a maintained list, plus the library's
  own capitalization wherever the line is linked. *Why the list:* measured over the 455 capitalized
  names, the corpus writes "shaoxing" lowercase 16 times and "chinese" 4 times, so "the corpus does
  it somewhere" would have lowercased two demonyms and a Chinese city. **Evidence of common USE is
  not evidence of a common NOUN.** 296 names have evidence they are ordinary words and are changed;
  the other 159 go in a review CSV with the reason and wait for a decision.
- **THE SECOND TOTAL IS ANCHORED TO THE FIGURE THE PAGE PRINTS.** A conditional wait stays out of the
  Total (`planahead.counts`), and a smaller line under it says what the recipe costs on that path.
  A reader subtracts one line from the other, so the base has to be the Total actually shown: where
  the author STATED a total, that is the base, because no-knead-bread's stated 2 hr 45 min already
  includes its rise and computing from prep plus cook would print two figures whose difference is not
  the wait. ⚠️ **AND A TRAILING "+" IS THE OPEN END**, which `clock_minutes` cannot see, so reading
  the label back has to preserve it or the line states a ceiling the recipe never had.
- **A NOTE IS WRITTEN BY TWO DOORS, AND EVERY RULE THEY SHARE IS ONE FUNCTION.** The per-note
  endpoints write the moment a cook stops typing on the recipe page. The recipe PUT carries the
  whole list and is what Edit mode's Save sends. Four independent reviews of the notes round found
  the same shape four times: a rule stated twice, with both comments claiming to follow the other.
  `_note_step_target` answers "which step may this point at" for all three callers, and
  `_note_ref_rows` answers "what are this note's references now" for both write paths.
  ⚠️ **A STEP THAT IS GONE IS GONE, AND A HEADING IS KEPT WHERE IT WAS STORED AND REFUSED WHERE IT
  IS NEW.** That distinction is what the three copies were groping at. Converting a step to a
  heading has to be reversible, so a link that already named that row survives and simply stops
  printing a number. Creating a link to a heading is a pointer nobody can follow. Before this, a
  reference to a converted step was KEPT by the PUT and DESTROYED by the next text edit through the
  other door, and the id lives nowhere else, so the conversion became irreversible in silence.
  ⚠️ **A SENT NULL IS NOT AN ANSWER AND A STORED NULL IS.** The editor round-trips references
  verbatim and builds a new mention with a null target, because a client cannot know a link the
  server has never told it about. Reading that null as a decision is what made "step 2" link when
  typed in reading view and stay plain when typed in Edit mode. A null the server STORED is a
  decision, which is what lets a deliberate unlink survive a later save.
  ⚠️ **AND ABSENT MEANS KEEP ON A ROW MATCHED BY ID.** `PUT notes:[{"id":1,"text":"…"}]` answered
  200 and cleared the cook's chosen kind and their step link. The documented old-client path made it
  worse: a bare string carries neither key, so one save from anything older than migration 060
  cleared every kind and every step link on the recipe. `_kept` does this for the recipe's header
  fields and `_kept_minutes` for a wait; notes had no equivalent.

- **A HELD DRAFT IS A COPY, AND A COPY GOES STALE.** Edit mode clones `view.data` and every edit
  changes the clone. Two things follow, both measured as defects rather than reasoned.
  ⚠️ **NOTHING MAY CLONE THE LIST WHILE A WRITE IS IN THE AIR.** The click dispatcher runs the note
  handler before the editor's, and its click-away branch fires a note write and returns false, so
  one click on "✎ Edit" saved a note and then cloned synchronously, before the answer landed. The
  draft held the note's OLD words and Save wrote them back over the new ones; a note ADDED that way
  was deleted outright. Not a race, because nothing awaited anything. `noteApi` tracks every call
  and `enterEditMode` waits.
  ⚠️ **AND A FIELD THE SERVER RESOLVES IS STALE THE MOMENT THE DRAFT CHANGES.** A note's `step_no`
  is the number the page prints, resolved by the server. A note added, relinked, or whose step was
  deleted or made a heading this session carries a number that is wrong or absent, and the raw row
  cannot say so. Any rule that reads it (`noteGroupKey`, `linkedStepId`) takes `steps` and resolves
  for itself (`noteGroupsOf`), rather than trusting what it was handed.

- **A DRAG INSIDE A GROUP PERMUTES THAT GROUP'S OWN SLOTS.** `noteBlocks` orders the type blocks by
  where each kind FIRST APPEARS in the flat list, so splicing a row out and back in changes the
  index of every row it passes and silently reorders the HEADINGS. Measured on
  `[Notes#1, Tips#2, Notes#3]`: dropping note 1 back where it already sat reordered nothing inside
  Notes and lifted the whole Tips section above it, with `position` renumbered so it stuck. Read off
  the indices the group occupies, reorder the members among themselves, write them back into those
  same indices. A non-member cannot move, and a gesture that reorders nothing is refused.

- **A CONTROL IS DRAWN ONLY WHERE IT CAN DO SOMETHING.** A note alone in its drag group has no legal
  drop target, so a grip on it promises a move that can only snap back. `noteDragMates` answers for
  the whole list in one pass and the renderer asks it on every repaint, so an add, a delete, a
  relink or a type change gives or takes the handle away as it happens. The ⋯ stays either way.
  The same rule took the step picker's offer of a step the database has never seen: `addStep` puts
  `id: null` in the draft, a link is a row id, and picking one wrote `NaN` and no link, with no
  message. It is counted in the numbering and not offered.

- **A STEP NAMED IN A NOTE'S OWN WORDS IS A REFERENCE TO AN ID, NEVER A FROZEN NUMBER.** "proceed
  with step 9" has to keep meaning the right step after the steps move, so `recipe_note_step_refs`
  stores the step's ID and WHICH mention in the text it belongs to, and the number on the page is
  resolved every time from the step's current position. A reference whose step became a heading
  renders as plain text, which is the rule waits already follow: a wrong number is worse than no
  link.
  ⚠️ **THE NUMBER IN A NOTE IS THE AUTHOR'S, AND RESOLVING IT NEEDS THE AUTHOR'S LIST.** The app's
  numbering has moved: the 2026-09-30 chain lifted 104 labels into headings, converted 21 steps and
  moved 7 Note steps out of the method. the-best-new-york-style-bagel's "step 9" is the app's step
  8, and the offset's cause is visible in the source card — the author's step 2 is the yeast Note
  the importer moved into the notes. Resolve from the original and match by WORDING; where the
  original is unavailable, FLAG, do not guess.
- **THE AUTHOR'S OWN STEP NUMBERS COME OFF, AND ONLY WHERE THE WHOLE RECIPE IS NUMBERED.** The app
  prints its own number in a circle, so a step still beginning "1." shows it twice, and a lead-in
  label hiding behind one is invisible to the label rule. `import_cleanup.strip_author_numbers` is
  all-or-nothing per recipe: a number comes off only where the steps carry a consecutive run from 1
  agreeing with their own ordinals, because **the evidence that a leading number is the AUTHOR'S is
  that the rest of the recipe is numbered too.**
  ⚠️ **A BARE NUMBER NEEDS TWO PIECES OF EVIDENCE AT ONCE**, the ordinal and a capital after it.
  Measured over the 300: that pair admits 7 steps, all of them the author's numbering, and refuses
  the 3 real ones ("30 minutes before you start cooking…", "180 degrees…", "24 pieces…").
  ⚠️ **AND AN ALL-CAPS LEAD-IN ENDING IN A COLON IS A TITLE WHATEVER ITS SHAPE.** The comma, the
  connective and the word-cap refusals all read a label as prose, and prose is not written in
  capitals with a colon after it. Measured: exactly 2 labels in the corpus take that door.
- **LOCKSTEP: A MACHINE REPAIR MAKES NO MARK.** The page's "your changes" is
  `diff(reason='original' snapshot, current rows)`, so a pass that rewrites a row without rewriting
  that baseline is indistinguishable from the cook having hand-edited it. Every corpus pass patches
  the live row and the baseline **in one transaction**, which is what let 300 recipes be restructured
  while the 49 real annotation entries stayed at 49.
  ⚠️ **The baseline is patched SURGICALLY, never rebuilt.** 16 of the 300 have drifted on purpose and
  rebuilding from current content would declare each recipe born in its edited state, erasing exactly
  the annotations the layer exists to show.
- **A GATE COMPARES THE SHORT-CIRCUIT SET AGAINST THE BEFORE-STATE OF THE SAME RUN, NEVER A FIXED
  NUMBER.** "short-circuit 275 of 300" was quoted as a gate figure for a whole round, and it is not
  a property of the corpus. It is a property of which recipes have been saved. A save used to give
  every wait a new row id, the snapshot carries that id, so one spot-check save of brioche-bread took
  the number to 274 with **0 annotation entries and nothing visible on the page**. The save path
  keeps row ids now (`_match_rows`, `_apply_rows`), so an unchanged save leaves the bytes alone, but
  the rule stands on its own: read the set before the chain, read it after, and compare the two SETS.
  A count that drifts for a legitimate reason teaches everyone to ignore the gate.
  ⚠️ **AND COMPARE THE SET, NOT ITS SIZE.** One recipe leaving while another joins holds the count
  still and is exactly the kind of thing a corpus pass should have to explain.
- **A DECISION A PASS READS IS COMMITTED. A REVIEW LIST IS NOT.** Two kinds of file live in
  `docs/data-repairs/`, and the difference is whether code opens it.
  - **A recorded decision** is an input to a pass. It **must be committed**, because a pass that
    cannot be re-run from a fresh clone is a hand edit with more steps. Five of them were untracked
    and one sat in gitignored `previews/`, so the 94 waits and 30 storage rows written over 90
    recipes existed on one machine and in no commit.
  - **A review artifact** is the output of a one-time survey that nothing opens. It may stay
    untracked.
  The test is mechanical: **if a committed `.py` OPENS the file, it is a decision and it is
  committed.** `docs/data-repairs/README.md` keeps the index and says, per file, what reads it and
  whether it is committed. ⚠️ **The test used to say "any committed .py or .md NAMES the file", and
  the index is a committed .md that names every one of them**, so the rule declared its own survey
  output to be recorded decisions. Opening the file is the thing that matters, because that is what a
  fresh clone has to be able to do. Measured today: 4 of the 20 files are untracked, no `.py` opens
  any of them, and the index already lists all four as read by nothing.
- **RUN THE WHOLE CHAIN FROM A CLEAN CHECKOUT BEFORE RUNNING IT FOR REAL.** A pass applied on its own
  to a corpus already part way through agrees with the chain by luck. The passes are ordered and each
  reads what the one before it left (`docs/data-repairs/README.md`). Every defect in this round's
  review was found by the first end-to-end run from a fresh copy of live, and none of them by the
  piecewise runs that preceded it.
- **NEVER UNDO A CHANGE WITH `git checkout --` OR `git restore` ON A FILE THAT HAS UNCOMMITTED
  WORK. Commit or stash first.** Those commands do not undo the last edit, they throw away every
  uncommitted change in the file, and nothing warns you first.
  *Why:* `import_cleanup.py` was mutated on purpose during this round to prove a test could fail,
  and `git checkout -- import_cleanup.py` was used to put it back. That wiped **four unrelated
  fixes** sitting uncommitted on the same file (the abbreviation list and its tests, the paired-dash
  refusal, the unification of `strip_emphasis` with `strip_wrapping_marks` plus its empty-inner
  guard, and `classify_line`'s unwrap with its `CLEANUP_REASONS` entry). All four had to be written
  again from the transcript. The blast radius of a checkout is the FILE, and the work on a file is
  usually several things at once.
  **How to undo one deliberate mutation:** commit the real work first, or `git stash push <file>`
  and pop it after, or keep the mutation in a scratch copy and never touch the tracked file. A
  deliberate test mutation is itself a reason to commit the surrounding work BEFORE making it.
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
- **:8000 NEVER SERVES THE SHARED `dist/`.** The live server runs from its own git worktree,
  pinned to a pushed commit, with its own `dist/` that no build in the working repo can reach:
  `git worktree add ../recipe-app-serve <pushed-sha>`, `npm install && npm run build` there, then
  `python3.13 scripts/serve_live.py`. That script points the pinned checkout at the REAL database and
  the REAL photo folder (`app.DB`, `models.DB`, `images.IMAGES_DIR` — all redirectable module
  globals, found through git rather than hardcoded), so the bundle and the server are the same commit
  by construction while the data stays the live data. **Nothing is symlinked**, so a stray
  `build_db.py` in that checkout cannot reach live's `recipes.db`. *Why this exists:* `dist/` is
  rebuilt by every `npm run build`, including the ones behind a preview, and a preview build put a
  client that sends `{id, text}` steps in front of a server old enough to read a non-string step as
  `""` — which would have blanked every method step of the first recipe saved, with a 200 and no
  sign anything was wrong. A preview likewise builds in its OWN worktree and never in the working
  repo. **After any push you want live to run, rebuild the pinned worktree at the new SHA; do not
  point :8000 at the working tree "just this once."**

- **A TABLE REBUILD IS ONE TRANSACTION, AND THE WRAP IS PER FILE.** `migrate.py` applies each
  migration with `conn.executescript`, which opens NO transaction, so every statement auto-commits
  on its own. A create-copy-**drop**-rename interrupted in the middle is committed half done.
  Measured by replaying each file truncated and killing the process with `os._exit`: truncated after
  the DROP the table is GONE and the scratch table is left behind, and the retry dies forever on
  "table already exists". Truncated before the `CREATE INDEX`, the rebuild **looks finished and the
  indexes are simply missing**, with the filename recorded, so the drift is permanent and silent.
  The second shape is the dangerous one. `005`, `019`, `026`, `041`, `045` and `056` all carry their
  own `BEGIN;`/`COMMIT;` now, and `tests/test_migration_atomicity.py` states the rule over the
  FOLDER so the next rebuild written is covered before anyone remembers it.
  ⚠️ **DO NOT LIFT THE WRAP INTO `migrate.py` AS A BLANKET RULE.** A `PRAGMA foreign_keys` is a
  silent NO-OP inside a transaction, measured, and `045` sets it off for its rebuild and back on
  after. A central wrap would disarm exactly the thing that makes that file safe. `045` keeps its
  pragmas OUTSIDE its `BEGIN`, in that order, and a test asserts no migration sets that pragma
  inside a transaction.
  ⚠️ **`migrate.py` TRACKS BY FILENAME ONLY**, not by checksum (`schema_migrations` is
  `filename TEXT PRIMARY KEY`). Editing an applied migration therefore neither re-runs it nor is
  rejected, which is what made wrapping these five safe on a database already past them. It also
  means nothing detects an edit that diverges from what was actually run, so a correction goes in a
  LATER migration and an edit is only for something that cannot change the result, such as adding a
  transaction around statements that already ran as a unit.
- **NOTHING KEEPS THE TWO SCHEMAS AGREEING EXCEPT A COMPARISON.** `migrations/*.sql` is the SQLite
  history and `alembic/` owns Postgres, written by hand from the same intention.
  `tests/test_schema_parity.py` reflects both and diffs tables, columns, type affinity, nullability,
  defaults, primary keys, indexes, unique constraints, CHECKs and foreign keys WITH their ON DELETE,
  and it reintroduces six drifts on purpose to prove the comparison catches each one.
  ⚠️ **SQLITE'S `ON DELETE` AND ITS EXPRESSION INDEXES DO NOT COME FROM SQLALCHEMY REFLECTION.**
  `Inspector.get_foreign_keys` returns `options: {}` for SQLite even where the DDL says
  `ON DELETE CASCADE`, and expression indexes come back as "Skipped unsupported reflection". Against
  32 real CASCADEs that gap produced 21 false positives, and a false positive in a parity test gets
  silenced rather than fixed. Both are read from `PRAGMA foreign_key_list` and `sqlite_master`.
  ⚠️ **AND IT IS COMPARED BY MEANING, NOT BY SQL TEXT.** Postgres renders `IN (a,b)` as
  `= ANY (ARRAY[a,b])`, `BETWEEN` as two comparisons, appends `::text` to literals, and reports a
  UNIQUE constraint twice (as a constraint and as its backing index). Each is normalized by a named
  rule with its reason. A type is compared by AFFINITY and an unknown type name is compared
  literally, so introducing one has to be deliberate.
- **A MIGRATION'S ORDER AGAINST THE DEPLOY FOLLOWS ITS DIRECTION. Additive goes BEFORE the deploy,
  destructive goes AFTER.** The question is which of the two versions names something the other side
  does not have. Migration 053 ADDED `recipe_waits.step_id` and the new code selects it, so deploying
  first would have failed every recipe page on a column that did not exist yet. Migration 054 DROPPED
  `step_position` and `step_check`, and the OLD code still declared them on its `RecipeWait` model, so
  `select(RecipeWait.__table__)` emitted them by name and migrating first would have failed every
  recipe page the other way. Same outage, opposite order.
  The rule underneath both: **find the version that can serve BOTH schemas and run that one in the
  middle.** New code that reads a new column cannot serve the old schema, so the schema moves first.
  New code that merely stops declaring a column serves the old schema fine, so the code moves first.
  **Verify it, do not reason it out and proceed:** start the intermediate version against the CURRENT
  schema and confirm the pages build before touching the schema. A column added and a column dropped
  are one command from a live outage in opposite directions, and nothing in the tooling warns you.
  *Corollary for a drop:* retire the column in one commit (stop reading and writing it, keep it in the
  table) and drop it in a later one, which is what 053 and 054 did. That makes the deploy-then-migrate
  order available instead of forcing a simultaneous cutover.

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
- **Measure the shape of the data before writing the parser.** Six defects in one ingestion were the
  same error: an assumption about the SHAPE of the data made instead of a measurement. An ASCII slug
  that erased Cyrillic, a key that assumed no duplicates, a filter that assumed food is tagged as food
  and silently missed 9 of the 10 terms it existed for. Before committing to a key or a filter, count
  what it is unique over, count what fraction of records carry the field it needs, check it keeps the
  terms the source was added for, and state the expected yield BEFORE running. The six cases and the
  rule live in **[docs/measuring-the-premise.md](docs/measuring-the-premise.md)**.
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
rebuild leaves them intact (0 seed duplicates). This is DONE, not a pending follow-up. **NB:** the 36
hand-authored **ingredient** rows are **GONE**, deleted in **migration 046** (2026-09-20) in lockstep
with emptying `seed.py`'s `INGREDIENTS`. They were an early demo of what an ingredient library would
look like, carrying model-written `descr` and `pairs`, and Andy's ruling is that they have no purpose
now or later. ⚠️ **`ingredient_weights` WAS NOT PART OF IT.** Those 129 King Arthur rows are real
reference data, loaded by `seed_weights`, and they stay. Deleted alongside the 36 were their 65
seasons, 102 region links and 44 regions. Stage A (`36f5868`) decoupled the test fixtures first, which
is what made the deletion safe. `ingredients` now holds 0 rows and `seed_content`'s ingredient upsert
runs over an empty dict.
**[docs/ingredient-model.md](docs/ingredient-model.md)** is the source of record for the model. Any
remaining 'stale linked-ingredient' symptom, if real, lives in those records/labels, **not** the
recipe source-tier, and is diagnosed separately rather than re-fixed via a `source` flip.

*Why the fourth exists (the Stage-1b CI miss):* the converted ORM read routes used `models.SessionLocal`
(frozen at import to the default `recipes.db`). `make_kitchen` redirects `app.DB`/`build_db.DB`/`migrate.DB`
but not the frozen engine, so the ORM silently queried the **real** `recipes.db` during tests — green
locally (the file exists and its seed-derived ingredients/people happened to match the fixtures) but red
in CI (no `recipes.db` → empty DB → `OperationalError`). Fixed by `orm_session()` reading the redirected
module-global `DB` at call time. Hiding `recipes.db` and re-running `pytest` reproduces the CI failure in
one step — the standing guard for any DB-access-path change.
