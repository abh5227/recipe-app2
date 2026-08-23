# Chef's Choice — Roadmap / Feature Tracker

A running list of features, grouped into **priority tiers**. This is a planning document, not a
commitment — reorder, add, or drop items as priorities change. Each feature keeps a stable
**(Pxx)** id (its original phase number) so older cross-references still resolve; the **tier**
conveys priority, the number is just a permanent label.

---

## Tier 0 — Cross-cutting principles

The *why* and the *how* behind everything below. The first principle is the strategic "why"; the
rest are the "how" that serves it.

### Data philosophy — capture meaningful signal, not data for its own sake

Recipes themselves are a commodity: the internet has millions and capable models already know
them, so raw recipe *volume* is nearly worthless — and far too small, at app scale, to train a
model on. The scarce, valuable asset is **outcome data**: which recipes real people actually
cook, how they rate them, and what they modify. That signal exists nowhere else at scale and is
the unique thing that could make grounded recipe suggestions beat a generic model. So optimize
every feature to capture meaningful signal — outcomes, modifications, behavior — **structured and
timestamped from the start**; when designing anything, ask *"does this capture signal worth
having?"* This is why the cook log, ratings, and per-person modifications are strategically
central (Tier 3). The long-term payoff: this signal **grounds a capable LLM via RAG** (retrieval
over our structured corpus), not a model we train ourselves.

### Data-capture — capture signal early, build consumers later

Log cooks, ratings, and edits with TIMESTAMPS and STRUCTURED OUTCOMES from the start: the signal
you don't capture is unrecoverable, but features that consume it can be built anytime. Raises the
bar for how Phases 5 (journal), 18 (analytics), and 19 (recommender) store data. Edit/version
history is cheap to start timestamping now (tie to the per-person change layer).

### Matching — decline over guess, but measure coverage

Whenever the app matches free-text recipe ingredients to structured data (weight table, pantry,
library links, imported recipes), a wrong match is worse than no match: it produces confidently
incorrect output (a false-precision gram value, a mis-linked ingredient). Rule: exact match
first, conservative normalized fallback, curated aliases for known equalities, and on anything
less than a confident match, pass through unchanged — never guess. AND measure how often we
decline (coverage reporting) so we know how big the gap is. Applies to Phases 1c, 13, 15, 16.

### Provenance — cite reference data in the data model

All gathered REFERENCE data (ingredient weights, densities, variances, seasonality…) carries its
SOURCE(S) as a column, so "blended from multiple reliable sources, cited" is traceable and
conflicts (e.g. King Arthur 120 g/cup vs ATK 140) are reconcilable. Apply to the existing
`ingredient_weights` table and every future reference table.

### Ingredient-line data model

Current ingredient text carries three kinds of noise — combined ingredients ("beef mince ground
beef"), embedded instructions/qualifiers ("very warm tap water up to 130 f"), and "X or Y"
alternatives ("naan or arabic taboon bread"). This degrades every feature that treats ingredients
as structured: conversion, pantry matching, library linkage, in-season, dietary flags, search.
*Detection* belongs in Phase 6 (the health scan); *structural* cleanup — cleanly separating
quantity · unit · ingredient · prep-note, and handling alternatives — is a bulk-import-era task
tied to the ingredient model and the importer, best done at/around import (Phase 15/16) so scraped
recipes are cleaned on the way in rather than after. Not worth hand-cleaning the current 5
recipes; tolerable at this scale, matters at bulk upload. *See Phases 12, 13, 15, 16.*

### Amount-structure cleanup

Amount text also carries forms the numeric parser can't handle — word-numbers ("half", "a few",
"a couple"), parenthetical amounts ("(about half a lime)"), and open-ended amounts ("plus more if
needed", "to taste") — each needing separation from the scalable quantity, handled at
import/data-model time (not a standalone word-number feature). Worked example that fails to scale
today: the lime-juice line "lime juice (about half a lime), plus more if needed". Ties to the
import / ingredient-name cleanup notes.

### North-Star — a queryable structured recipe dataset (NOT ML training)

The goal is every recipe decomposed into clean, queryable fields (ingredients, amounts, units,
cuisine, tags, technique) so the whole corpus is queryable — via QUERIES over clean data, not
learned models. The existing normalized schema IS this dataset; the work is ENRICHING it
(ingredient-library linkage + metadata), NOT a separate denormalized all-in-one table (which
would duplicate data and create sync problems). Through-line: Phase 6 (linkage, foundational) →
Phase 8 (cuisine/tags) → bulk import (15/16). Volume comes from both published recipes (15/16)
and friends' shared recipes (17). *Agenda + analysis: see "Data gathering & cross-recipe
analysis" near the end.*

### Working principle — slow and gradual

One phase (or sub-step) at a time, each an independently shippable change we review before moving
on. Larger features are split into sub-steps for the same reason.

### Order rationale

A test-suite foundation first, then cheap isolated wins and maintenance, then the recipe metadata
that filtering/discovery depend on, then sub-recipes, then ingredient enrichment, then the large
pantry + planning cluster, then output, the two import methods (free, then paid), and the
networked friend feed last. Phase numbers are a suggested order, not a lock — anything cheap and
self-contained can be pulled forward. *(The tiers below now reflect this priority directly.)*

---

## Cost summary

Everything is free except two items.

| Cost | Features |
|------|----------|
| Free | Test suite, quantity & units, cooking mode + checkoff, dark mode, photo upload, per-cook journal, data health check, trash / soft-delete, recipe metadata — favorites/tags/dietary/cuisine, planning attributes — equipment/difficulty/time/make-ahead/calibration, search & discovery incl. in-season/pairings/reverse-lookup, sub-recipes, ingredient enrichment, pantry + shopping list + meal planner, output — print + export/import, free JSON-LD import, local cooking-activity view (precursor), adding recipes, recipe collections (playlists), share-by-file export |
| Per-use API cost (cents per call; needs a key) | AI recipe scan/auto-populate; optional: AI-assisted citations, AI-ranked substitutes |
| Ongoing hosting cost + major architecture change | Friend cooking feed, networked version, recipe/collection sharing (public link or multi-user) |

---

## Tier 1 — Done / in progress

### Test Suite (P0) · ✓

Stand up a persisted `pytest` suite in the repo covering current behavior — the API
endpoints, `migrate`/`build_db`, per-person changes, and rebuild-preservation — replacing
the throwaway tests used so far.

- **Cross-cutting:** every later phase adds tests for its change.
- **Schema:** none. **Why first:** highest-leverage safety net as features stack; cheap now,
  expensive to retrofit later.

### Quantity & Units (P1) · ✓

Shared machinery: a parser that reads a quantity string into a number + unit.

- **1a — Scaler.** Scale quantities (×0.5, ×2, "serves N"). *(done — ingredient quantities only;
  the scaler now lives in the vitals beside Serves-N and updates the serving count live. Still
  multiplier-based — the type-a-target "Serves-N scaling" below remains future.)*
- **1b — Metric/imperial toggle.** Fixed-factor conversions: volume↔volume, weight↔weight. *(done)*
- **1c — Volume↔weight (King Arthur table).** *(done)* Ingredient-specific ("1 cup flour" → "120 g");
  adds a per-ingredient weight field (g per cup/tbsp) from the King Arthur Baking table.
  *See also: preferred-units-on-import (future nice-to-have, see Known limitations & tech debt) —
  the density table built here is a dependency for baking volume→weight conversion at import time.*
- **1d — Scale quantities in the method text.** *(done)* When you scale a recipe, amounts written
  into the steps ("add 2 tbsp oil", "stir in 1 cup stock") must scale too — but step prose
  also holds numbers that must *never* move: temperatures ("350°F"), times ("20 minutes"),
  pan sizes ("9×13"), doneness temps ("to 160°F"), and counts ("cut into 4").
  **Safe-hybrid model — three layers, strict priority (markup > guard > heuristic):**
  1. **Explicit markup wins, always.** `{{2 tbsp}}` = scale this quantity; `{{!350°F}}` =
     lock, never scale (manual override). Kept distinct from ingredient links (`[[...]]`) so
     the two can't collide.
  2. **Hard never-scale guard**, runs regardless of the heuristic: any number adjacent to a
     temperature (°F/°C/degrees), time (min/hour/sec), dimension (inch/", cm, mm, N×N), or
     doneness marker is blocked — an absolute block *above* the heuristic, not the heuristic
     choosing to skip.
  3. **Heuristic** scales the rest: a `<number>` immediately followed by a recognized
     volume/weight unit (the existing unit list) that survived layers 1–2.
  **Bias to under-match:** when unsure, do not scale. A missed quantity is a visible, harmless
  inconvenience; a wrongly-scaled temperature or time is a silent hazard. Bare unitless numbers
  ("divide into 4", "3 sets of folds") are left alone (usually counts/structure) and flagged
  "unitless — review" in the coverage report. **Failure mode is "miss a quantity," never
  "scale a fixed number."** Reuses the 1a parser for the math. *Schema:* none (markup lives in
  the existing step text).
  *See also: heuristic accuracy on bulk-imported recipes ties to import-cleanup (Phases 15/16)
  and the Ingredient-line data model note (top) — method text arrives messy on import, the
  same era of work.*
- **Serves-N scaling (future, its own step).** Scale step + ingredient quantities to a target
  serving count (factor = target ÷ original yield) instead of a raw multiplier. Needs a
  **numeric yield field** per recipe — servings is currently free text (or absent) — so it's
  deferred. 1d ships preset multipliers (×½/×1/×2/×3) plus a custom multiplier input;
  serves-N layers on top once the yield field exists.
- **Smart-Metric (1b/1c refinement, done).** The metric toggle is 2-way (Imperial ↔ Metric)
  and picks each ingredient's unit: ≤ 2 tbsp stays tsp/tbsp; > 2 tbsp converts to grams when
  the KA weight table has it (incl. liquids, shown "~"), else keeps the original unit
  (decline). Replaces the old separate all-mL "Metric" and "Grams" modes. *Future (needs
  Phase 8 tags):* recipes tagged baking/dessert default to grams and ignore the 2-tbsp
  threshold — see Phase 8.
- **JS test harness.** *(done)* The pure scaler/converter is extracted to `static/scaler.js`
  (UMD: browser global + Node `require`) and tested with Node's built-in `node:test` — run
  `node --test tests/js/*.test.js` (covers `scaleQty`/`formatAmount`, the count + compound logic,
  and the smart-Metric threshold). A `factor-sync` test reads both `scaler.js` and `weights.py` and
  asserts the JS↔Python conversion factors agree. CI runs both the Python and JS suites on
  every push. *(Zero dependencies — no bundler/framework.)*
- **Notes:** parse whole numbers, fractions, ranges; leave "to taste" alone. Convert only
  what's possible. Compose with per-person edits. "Serves N" needs a numeric base yield —
  servings is currently free text, so a small structured-yield field is a dependency. 1c is
  a citable source (ties to Phase 12). *Schema:* per-ingredient weight field (1c); numeric
  yield field.
- **Later:** sub-recipe components should scale with the parent (see Phase 11).

### Recipe Import (P15) · IN PROGRESS

Import recipes from multiple sources into clean, structured records. **Architecture: thin
source-specific READERS feed a single source-agnostic CORE through a NORMALIZED shape** — so
adding a source never touches the hard logic.

- **Source format — Paprika NATIVE (`.paprikarecipes`), not HTML.** The native export is a ZIP
  of gzip'd-JSON `.paprikarecipe` entries. Chosen over the HTML export because: images are
  embedded (base64) and complete (HTML's image story was folder-dependent and linked only the
  primary); it's structured JSON (no entity decoding / `<strong>` / PhotoSwipe boilerplate);
  `categories` is a real list and `rating` an int; and each recipe carries a stable `uid`
  (→ idempotent / no-duplicate import) and a content `hash` (→ change-detection). **Cost:**
  native has no `<strong>` amount hint, so leading-amount parsing falls to the cleanup core —
  acceptable, because the core must parse amounts robustly anyway (the hint never solved ranges,
  secondary amounts, "2 x 6oz"). The HTML reader + format study stay as a documented fallback
  and for the friends-migration tool (Project B).
- **Source-specific READERS** (thin adapters, one per source) — each extracts a source's raw
  fields and emits the SAME normalized shape:
  - **Paprika-native reader** — build now (the Paprika files on hand).
  - **URL / JSON-LD reader** — build later: ONE reader covering NYT, Woks of Life, RecipeTin,
    and most recipe sites (they share the schema.org standard) — NOT a per-site reader.
  - **AI-scan reader** — Phase 16 fallback for sites without structured data, and for photos.
- **NORMALIZED shape (the contract / seam):** `{name, ingredient_lines (list of raw strings),
  directions, source (raw) + source_url, servings_raw, categories (list), notes, description,
  images, uid, hash, times, rating}`. The core ONLY sees this; it never knows the source. Adding
  a source = a new thin reader producing this shape; the core is untouched.
- **Shared CLEANUP CORE** (source-agnostic — the real engineering): parse amount / unit / name
  per ingredient line; flag section-headers for review (the ~5% ambiguous Title-Case / no-amount
  lines); harvest parenthetical grams; servings conservative-or-blank; library linkage
  (decline-over-guess). The hard engineering lives here and is reused across all readers.
- **WRITE layer:** recipes → app-tier (uid-dedup) — **recipes-write now BUILT** (see
  "Recipe-write — BUILT" below); ingredients → seed-tier shared library and images → storage are
  still to come. Field-guide AI baseline + linkage run as separate passes (see below).
- **Build order:** Paprika-native reader + the core now; URL and AI-scan readers later — don't
  build ahead of need, but the core is designed against the normalized shape so they slot in
  without a refactor.
- *Cleanup-core concerns, exercised at scale on import: cross-reference the
  ingredient-name-cleanup / amount-structure / data-capture / provenance notes (top).*

**Phase 15 design decisions (settled):**

- **Two projects, sequenced.** Project A = import MY 298 Paprika files (build now). Project B
  = a general Paprika→app migration tool for friends (roadmapped, AFTER A; needs friends' real
  exports to harden against format variation — not available yet).
- **Import ALL — flag incompletes, never drop.** All 298 recipes import, including photo-only
  entries (e.g. a photo-journal salmon folder with no text). Incompletes — no-directions
  (26 found), no-ingredients (3), or photo-only — are FLAGGED for review, never dropped:
  "empty" can be intentional and the parser can't tell intentional from junk.
- **Data tiering.** Imported RECIPES → app-tier (mine, live in the DB, not rebuilt). Imported
  INGREDIENTS → seed-tier SHARED library (ships to others), so the field guide grows into a
  built-in knowledge base others benefit from on import.
- **Cleanup = aggressive + decline-over-guess.** Parse aggressively where the pattern is clear
  (amount via leading-token parse, sections, unit/name split); when a line is genuinely
  ambiguous, FLAG it for review rather than guess. Failure mode must be "flagged a line," never
  "structured it wrong."
- **Harvest parenthetical grams** (e.g. "(226 grams)") as authoritative weights — better than
  volume→weight conversion; feeds 1c.
- **Source field = flexible provenance.** Store whatever's there (cookbook, cookbook+author,
  URL, URL+author, or none); don't require a URL; preserve the raw value + structure what's
  detectable.
- **Carry original notes faithfully** (including storage tips in notes — the author's content,
  preserved as-is). Distinct from AI generation below.
- **Field-guide AI baseline (separate pass, NOT during import).** A separate pass generates a
  first-pass field guide per ingredient — seasons, regions, pairings, general culinary info — so
  the library ships useful, not as empty stubs. **Bounded:** AI does NOT generate food-safety,
  allergen, or storage-safety claims (sourced-or-blank only — a wrong claim there has real
  stakes a disclaimer doesn't cover). Every AI field carries provenance ("AI-generated,
  baseline") + a needs-sourcing flag (tracker), via the per-field provenance model. Marking is
  present/findable but visually QUIET — must not clutter the design. The user replaces AI
  content with sourced data over time; the tracker shows what's still baseline.
- **Batch-then-link rhythm.** Per batch: import recipes → generate field-guide baseline for NEW
  ingredients → run a dedicated LINKAGE pass (link confident library matches, flag uncertain,
  leave no-match as free text). Linkage improves each round as the library grows.
- **Staged rollout.** Build the import core → validate on a hand-picked, deliberately varied /
  messy ~15 → then ship all 298.
- **Images in scope** — bringing across recipe photos is part of a "seamless transition."
- *Cross-reference: the data-capture, provenance, ingredient-name-cleanup, and amount-structure
  notes (top) are the cleanup core's concerns, exercised at scale here.*

**Recipe-write — BUILT (the write layer's first persisting step; Project A):**

- **Migration 009** adds `recipes.uid` (the source's stable id) + `recipes.hash` (content hash),
  with a partial UNIQUE index on `uid` (where non-null). `uid` is the DEDUP key; it is NOT the
  primary key — `recipes.id` stays the slug every child row references. `hash` is stored now for
  later change-detection (not yet used).
- **5 seed recipes tagged** with their matched Paprika `uid`s (in `seed.py`, written by
  `build_db.py`), so importing the native archive SKIPS their twins instead of duplicating them.
- **Mapping (`import_write.py`)** consumes the cleanup core's output as a pure write PLAN (no DB),
  committed by a single writer (`commit_plan`):
  - **slug (PK) minted from the title** (lowercase, hyphenated, accent-folded, punctuation
    stripped); collisions get `-2`/`-3`. The slug identifies the row; the `uid` is the SEPARATE
    dedup key.
  - recipes → **`source='app'`** tier (survives every rebuild — `build_db` only rebuilds
    `'seed'`); Paprika `source`→`author`, categories LIST→`·`-joined `category` string (each
    stripped), servings **parsed-or-blank**, `uid`+`hash` carried, `created_at`=now.
  - ingredients → `recipe_ingredients` (position-ordered, **`raw_text` always preserved**);
    sections → `is_heading=1`; `ingredient_id` left NULL.
  - steps → `recipe_steps` (**plain text, no `{{…}}` markup**); section-header steps → heading.
  - **rating 0 (unrated) → NO `ratings` row** (avoids `CHECK(rating BETWEEN 1 AND 5)`); 1–5 → a row.
  - **DEDUP:** a recipe whose `uid` is already present is SKIPPED (this skips the 5 seed twins).
  - **image:** primary photo only if trivially available, else NULL — `photos[]` is NOT extracted.
  - **dual-unit secondary-measure strip** (cleanup core): a `2 tsp / 6 g salt` line keeps the
    primary qty and strips the leading `/ 6 g` from the LABEL (kept in `raw_text`) so the
    label / future linkage key stays clean; an in-note `/60 ml` and a parenthetical `(N g)` are
    left intact.
- **Review queue — `import_flags` table (migration 010).** Flagged lines (`multiplier`,
  `each_multi`, `ambiguous_section`, `grams_declined`) and recipe-level incompletes
  (`no_ingredients`, `no_directions`, `photo_only`) land here, told apart by a nullable
  `position` (NULL = recipe-level). Kept OUT of the rendering tables so one SELECT is the whole
  queue; app-owned, cascades with its recipe. Lines are still WRITTEN — nothing is dropped.
- **Harvested grams captured (migration 011).** A `(NNN g)` weight is harvested and stored in
  `recipe_ingredients.grams`, and the gram parenthetical is stripped from the name. Captured
  only — not yet displayed/scaled (see Known limitations & tech debt).
- **Validation → full import (DONE):** validated via a writes-nothing dry-run on a random 15 with
  distinct authors (full plan + dedup decisions), then ran the full import. **All ~298 Paprika
  recipes are now imported** — the DB holds **301 recipes** (293 app-tier imports + 5 seed twins
  tagged with their `uid`s + 3 test fixtures) and **3,634 ingredient rows** (3,406 ingredients +
  228 headings).

**Remaining work:**

- Library **linkage** pass (`ingredient_id`) — link confident library matches, flag uncertain,
  leave no-match as free text.
- Full **image storage** (extract `photos[]`; today `image` is primary-only / NULL).
- **Use the harvested gram** as the authoritative display + scaling weight (captured now, not yet
  used — see Known limitations & tech debt).
- **Importer hardening — catch errors at the door and DECLINE, don't silently mis-structure.** A
  full-corpus survey (**[docs/import-damage-survey-2026-08.md](docs/import-damage-survey-2026-08.md)**)
  measured what the import actually left behind: **78/3,345 ingredient rows (2.3%) across 59 recipes**,
  plus **75 steps carrying a redundant `"1. "` numbering prefix** across 22 recipes *(re-counted
  2026-08-17: **78 rows / 23 recipes** — drift from the `-copy` recipes made since; the survey's figure
  stands as a dated measurement, it has not been overwritten)*. Thin, but the
  *failure mode* is the problem — **79% of the damaged ingredient rows passed the importer with no flag
  at all**, and steps are **100% unflagged by construction**. Silently mis-structuring is strictly more
  dangerous than declining, which is the pipeline's own stated principle. Targets, in survey order:
  - the damage classes themselves — stray punctuation stranded at a name's head/tail (32 rows, the
    largest, almost always a dual-unit split like `'2 oz./75g'`); non-vocabulary compound units (23 —
    `'small bunch'`, `'large head'`, `'tins'`, `'package'`); a measuring unit stranded in the name (11 —
    `waffle#4 '480mL cups milk'`); compound quantities never split out (`'1 28 oz'`, `'2 x 6oz'`);
    parenthetical duplicates (`'(120mL, 120mL)  heavy cream'`); underscore-wrapped pseudo-headings.
  - **strip the redundant leading step number** (75 rows / 22 recipes). Priority is higher than the
    count suggests: the source's numbering and the app's margin circle **contradict each other on the
    page** — observed live, circle **3** beside text beginning **"2."** — because the source numbers
    logical steps while the app numbers rows, and the import split some logical steps across several
    rows. Wrong from import, on never-edited recipes; a reader following "2." lands on the wrong step.
  - **promote ALL-CAPS `PREFIX:` section titles to `is_heading` rows** (24 rows / 11 recipes; a
    stricter re-count on 2026-08-17 found **21 rows / 11 recipes**, of which **15 / 9** sit in
    heading-less recipes — treat the lower figures as a **floor**. The **recipe** counts agree exactly;
    only the row counts differ, because the two passes used different tolerance for what counts as an
    ALL-CAPS title, so the detector's own strictness is the variable to settle when it is built) — the same
    class as the underscore-wrapped pseudo-headings but a different surface form, needing its own
    detector. **18 of those rows sit in 9 recipes with ZERO real step headings**, and that propagates:
    with no sections, a removed step there carries `section: null` and the annotation layer can only
    place it at list bottom. **Importer damage degrades the annotation layer downstream** — fixing the
    import is what makes annotations read properly on those recipes.
  - **normalize Cyrillic homoglyphs** (2 rows: `'З. MAKE THE SEASONING'` where `З` is U+0417, and
    `'МАКЕ THE CHICKEN'` in Cyrillic). Trivial in count but it must land *before* the prefix-stripper —
    `'З.'` doesn't match `^\d+\.`, so a naive strip leaves the row with a bogus number. Also the one
    class the scripted survey missed outright: it checked for mojibake and entities, not for characters
    that render correctly as the wrong codepoint.
  - **a step-level flag mechanism — none exists.** `_line_flag_rows` is only called from
    `_ingredient_rows`, so `import_flags.position` indexes ingredients only.
  - **surfacing the queue at all.** 593 flags across 209 recipes (69.7%) are written at import and read
    by nothing but a one-off backfill script — no route, no page (`import_flags` appears in `app.py`
    only inside a comment). Ties into the review-UI idea already recorded under Known limitations.
    **Worth doing BEFORE the hardening work**, so the hardening's output is legible as it lands rather
    than accumulating in a queue nobody can see.

**Hardening splits in two, and the second half is UNDECIDED.** Applying these corrections to *existing*
recipes is not the same operation as applying them at the door, because annotations are derived as
`diff(reason='original' snapshot, current rows)` and `snapshot_original` captures **once and never
re-captures** (guarded `WHERE NOT EXISTS`). So a data migration that rewrites rows without rewriting the
baseline is indistinguishable, to the annotation layer, from the cook having hand-edited every one of
those steps.

Simulated against the real corpus on 2026-08-17 — each affected recipe's actual `original` snapshot,
restructured, run through the real `diff_snapshots`:

| | |
|---|---|
| recipes the corrections would restructure | **25** |
| annotations generated | **112** |
| …of which **visible on the page** | **91** |
| dominant class | **77 × `step/modified`** |
| corpus effect | **298 clean → 273 clean** |

`step/modified` renders as the full original text struck through *plus* the new text in ink, so the
worst recipes (`aloo-potato-parathas`, 8) would show most of their method twice. The **21
`heading/added` entries are invisible** — `annotationIndex` ignores `kind:"heading"` — so the structural
half of the fix lands silently, which is the desired outcome.

- **E — door only (safe, unblocked).** Apply every detector to *future* imports. Changes no existing
  row, so it generates no annotations and needs no ruling.
- **E′ — backfill the 25 (needs a decision).** Correcting existing recipes requires **re-baselining**:
  rewriting `reason='original'` in the same transaction, which declares *"the corrected structure is
  what this recipe always was."* Defensible for import artifacts the cook never typed — but it discards
  any genuine divergence it overwrites. **6 recipes are ALREADY divergent from their baseline and must
  be inspected individually first**, since a blanket rewrite would silently swallow real edits.
  **Status: UNDECIDED — pending a ruling. Not a plan.**

### Recipe annotations + editor parity (O-c) · IN PROGRESS

The recipe page's handwritten annotation layer (current-vs-ORIGINAL) and the inline editor work it
pulled in. Design + the shipped commit arc in
**[docs/design-decisions.md](docs/design-decisions.md)**; standing code contracts in
**[CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md)**; corpus measurements in
**[docs/import-damage-survey-2026-08.md](docs/import-damage-survey-2026-08.md)**.

- **Shipped (pushed, CI-green through `cea7ade`):**
  - **O-c-0 anchoring** — position+section anchors, `(position, id)` ordering so they align by guarantee
    rather than coincidence, the `annotations` block on `get_recipe`, and the two diff-correctness fixes
    (canonical amount compare; canonical phase-2 similarity key).
  - **the client render** for amount / name / step / added, and for **removed** items struck at their
    section's bottom. That includes **preamble placement** — a `section: null` item belongs *before the
    first heading*, not at the bottom of the whole list, which is only right when the list has no
    headings at all — and the **renamed/missing-section fallback**, which stays at list bottom
    deliberately: the preamble is a real section, and routing genuinely unplaceable rows into it would
    put rows there that were never in it.
  - **heading add/remove is deliberately NOT rendered** (`annotationIndex` ignores `kind:"heading"`) —
    headings are organizational, not a change to the recipe.
  - a removed step renders **unnumbered** — `li.step-removed`, not `li.step`, so it takes no counter.
  - the **"−" marker** on both removed kinds, and **no "+" on added steps** (a whole paragraph of Kalam
    ink against printed prose announces itself) while **added ingredients keep theirs** (a terse ledger
    row does not). The asymmetry is deliberate; the "−" also earns its place by delimiting stacked
    removals from one another.
  - **editor parity:** clearing a step's text deletes it on save; per-step delete through the
    destroy→re-render→re-mount cycle; **editable step headings** (a plain `.ie` input in its own
    `data-inline-edit-step` namespace, flushed on `input`); and the **add-step adder**.
  - **drag-reorder for BOTH editor lists (C0–C2)** — the pure drop-index module
    (`static/drop-index.js`, height-agnostic, returns a *before-reference* rather than a landing index),
    the ingredient list, and the step list. Reorder emits **no annotations** by construction: a pure
    reorder changes no row's content, and `write_recipe_rows` re-derives `position` from the array
    order on save, so no backend change was needed. **Shipped, together with C3's grip finishing.**
    Mouse-only — see Known limitations & tech debt.
- **Still open in this area:**
  - **the "+ section heading" adder.** Now **unblocked** — its prerequisite, the step-heading field,
    shipped in `0099227`. Small: the adder button, `addStep(isHeading)`, one dispatch branch.
  - **the blank-step prune is CLIENT-SIDE ONLY** — a raw `PUT` carrying a blank step still stores it;
    `validate_recipe_payload` / `write_recipe_rows` stay permissive. Belt-and-suspenders server pruning
    was proposed and **deferred, not ruled on** — it also covers the orphaned `#/edit` form and direct
    API calls.
  - **remaining step-vs-ingredient parity.** A step row carries only a trash; an ingredient row carries
    grip · heading-toggle · trash. Both missing controls land with the row-actions menu (A below).
- **Then — a per-row ACTIONS MENU.** Delete, add-above, add-below, heading toggle, and eventually the
  reorder grip are accumulating past what a row edge can hold, on **both** lists. An overflow menu is
  the likely shape; not decided.
- **Then — DRAG-REORDER for both lists**, deliberately split out and **GATED on deciding the annotation
  semantics first.** Reorder is diff-noisy: swapping two rows emits a `removed`+`added` phantom pair for
  anything without a stable key, and only **50 of 3,384 ingredient lines (1.5%)** are id-linked while
  steps have no id at all. Options: teach the engine a **"moved"** concept (detect `removed`+`added` with
  identical text → emit `moved`, or suppress); ship and accept the phantoms; or linked-only, which helps
  1.5% of rows. **The fix belongs in `snapshot_diff`, not the editor.** Note also that dragging a
  *heading* silently re-sections every row beneath it — section membership is purely positional and
  nowhere recorded.
- **Also pending (pre-existing):** O-c-2 per-user ink picker (`users.annotation_ink` → `--ink-pen`);
  change-tracking **stage 4** (`recipe_changes` rows + the notes model); album **stage 3e** (anchor a
  photo to a method step); and the Cooking Journal itself, which all of the above feeds. Sequencing is
  recorded under Per-cook Journal (P5).

#### Queued sequence (decided 2026-08-17)

These items touch overlapping seams, so the order is not arbitrary — the wrong one means building the
same rows, or the same CSS, twice.

| # | Item | Why here |
|---|------|----------|
| **F** | docs refresh (this) | Both files described a state that no longer exists; everything below edits them |
| **D** | the **"moved"** diff concept | Hard prerequisite for C, and the one item with an undecided render question — start deciding early while the engine work lands |
| **A** | row-actions menu (both lists) | The biggest item; every later editor change is cheaper once the row edge and the step gutter settle **once** |
| **B** | per-row insert (add above/below) | Rides inside A's menu; no new seams |
| **C** | drag-reorder (both lists) | Unblocked by D; geometry already settled by A |
| **E** | importer hardening — **door only** | Orthogonal to A–C; safe because it only changes *future* imports |
| **E′** | the 25-recipe backfill | Needs a ruling on re-baselining (see P15) — **not** a plan yet |

**Hard dependencies** (cannot be reordered):

- **D before C.** Without a `moved` concept, ~99% of reorders emit a phantom `removed`+`added` pair —
  only 1.5% of ingredient lines are id-linked and steps have no id — and **both halves render**, so a
  user dragging two steps sees the old one struck at the section bottom *and* the new one in ink.
- **A before B.** B is menu items; there is no menu without A.

**Soft, but it saves real rework:**

- **A ships the reorder grip DISABLED**, so the step gutter is re-sized **once** (36px → ~62px). The
  gutter fits exactly one 25px control today; a two-control cluster measures 51px and overlaps the step
  text by 23px. Without the disabled grip that re-measure happens twice — the second time against live
  drag hit-areas.
- **The `handleInlineEdit` dispatch-table tidy belongs inside A**, before B and C add branches to what
  is currently a flat `if`-chain of `closest()` probes. It is the one function all of A, B and C edit.
- **Surface the `import_flags` queue before E** (see P15) so E's output is legible as it lands.

**Build constraint on C** (not an ordering matter — read this *before* building C, not after):

- **C MUST be height-agnostic.** Drop-target calculation must use **per-element `dragover` with
  `getBoundingClientRect()` midpoints**, never `index = Math.floor(y / rowHeight)` or anything else
  that assumes uniform rows. The album's existing reorder already works this way (`app.js`, the four
  document-level DnD listeners) — there is no row-size arithmetic anywhere in it, and the drop
  position is read back off the DOM position of the inserted `.drop-bar` rather than computed. So the
  mechanism transfers; choosing the arithmetic shortcut instead would be silently fine today and
  broken later.
  **But the AXIS does not transfer.** The album is a horizontal strip and tests
  `e.clientX < r.left + r.width / 2`. Both editor lists are vertical, so the test becomes
  `e.clientY < r.top + r.height / 2`. That is the single axis assumption in the borrowed code, and
  the one line that must change when it is lifted.
  **Why:** ingredient rows are uniform at 44px *only because* the name column truncates rather than
  wraps. If wrapping is ever adopted — deferred, not rejected, and the phone decision is its trigger
  (see the inline-editor section of [docs/design-decisions.md](docs/design-decisions.md)) — measured
  row heights range **44px to 140px** in a single list, and any uniform-height assumption breaks. C
  built against uniform rows would have to be redone; C built height-agnostic survives the change
  untouched.

### Frontend design pass — "used cookbook" recipe page · IN PROGRESS

A redesign of the recipe page into a printed-cookbook aesthetic that embodies the outcome-data
vision (the typeset original = the commodity; the user's hand-layer + wear = the asset). Full
direction — palette, type, the R1/R2 boundary, the punch-list — in
**[docs/design-decisions.md](docs/design-decisions.md)**.

- **Round 1 (now):** the clean cookbook page against the verified 15 — paper/type/color tokens, a
  single-column shell, the masthead, the volume+weight **ledger** (no units toggle; the
  `convert_to_grams` flag governs which lines show grams), control strip + scaler/rating fixes,
  amount formatting, tags, graceful empty states. Staged A (tokens/shell/type) → B (masthead) →
  C (ledger + formatting) → D (controls/rating) → E (reserve R2 hooks); per-stage commits, suite
  green at each. **Recipe page only.**
- **Round 2 (deferred — needs real accruing data):** the handwritten **edit/note layer** (earthy hand color),
  the **wear/patina** deepening with cook count, the populated compare/version display, and the
  **list/browse page redesign** (the scale/browsing review, after the ~295 import).
- **Method step check-off (R2 use-layer).** Each step's number becomes a **checkbox**; checking it
  **crosses out** that step and marks it done — a live cooking aid. **Session-only** (ephemeral
  front-end state, clears on refresh; no persistence/backend — a "where am I now" aid, not stale
  marks carried over from past cooks). **Cook-log link:** when **all** steps are checked, **offer**
  to log a cook (a nudge, not automatic) — completing every step in a live session signals it was
  just cooked; ties into the existing "Cooked it" flow. Belongs to the R2 personal layer (same family
  as the handwritten edits + cook-count wear) — the marks should read as *yours*, drawing on the
  reserved `--hand` hooks, not system UI. Refines **P2·2b** (check off steps while cooking) with a
  decided design. *Open (resolve at build):* the touch/mobile affordance — hover doesn't exist on a
  phone at the stove, arguably the **primary** case, so design a touch-first reveal/toggle — one-click
  vs hover-to-reveal, keyboard/a11y, whether crossed-out steps stay put or recede, and the cook-log
  offer's exact form (and whether re-unchecking retracts it).
- **Inline "mark up the page" recipe editor.** Replaces the admin-style form with in-place editing on
  the recipe page (edit-mode toggle + explicit Save + buffered draft; every field follows the
  reading-mode-parity principle + four field-kinds — see design-decisions.md). **Stage 2 done** —
  ingredients editable inline (edit qty/name/note, add/remove, headings, library-link/unlink; overlay
  fields; lossless heading-toggle; discard-empties + refetch on save). **Steps display-only (Stage 3)**;
  **reorder Stage 4**. Then polish (validation, source_url, image upload). Old form (`renderForm`)
  kept as fallback until complete, then retired.
- **Qty/unit split** (structured `quantity` + `unit` for conversion + filtering). **Stages 1–4 done** —
  additive nullable columns (migration 015) beside the untouched `qty`; a lossless split
  (`import_cleanup.split_qty`, 0 mismatches over 3,425 rows); an idempotent app-row backfill
  (`scripts/backfill_qty_unit.py`) + seed/import split; the write path threads `unit` (recombine on
  write, durable); and **Stage 4 — the editor** splits qty into a **quantity field + unit combobox**,
  flipping authority to structured quantity+unit (editor sends parts, server recombines `qty`). Wider
  edit mode (1000px; reading stays 760px), icon-only link, name font matched to the measurement size,
  on-save unit canonicalization. The **scaler stays untouched** (size/count words are datalist
  suggestions only, kept out of the measure recognizers). **Stage 5 optional/deferred** (scaler consumes
  structured fields, only if string-parsing hits friction). **Name→unit backfill done** — a standalone
  backup→dry-run→`--apply` transform (`scripts/backfill_name_unit.py`) moved leading size/count
  descriptors out of **272 rows'** names into the unit field (256 single-descriptor + 16 size+count
  keeping the size), recombining `qty`; 7 rows flagged for manual handling. Its recognizer
  (`split_leading_descriptor`) is a **pure, DB-free** function built **promotable** to a shared import
  helper. **Queued:** (a) **import-integration** — lift the recognizer into the import path (split
  descriptors at import time); (b) the deferred **66 trailing count-noun rows** ("garlic cloves").
- **Heading detection + backfill done.** The importer now strips a whole-line wrapping emphasis pair
  before the section test (`import_cleanup.strip_emphasis`), so bold colon-headings (`**Other
  Ingredients:**`) are detected **and stored clean** — a heading-only change (ingredient "preserve
  original line" contract untouched); scan-confirmed exactly 14 new detections, no collateral. A
  standalone backfill (`scripts/backfill_headings.py`, backup→dry-run→`--apply`) promoted **32** existing
  rows to headings (18 "For the X"/"To finish" already flagged suggest-section + 14 palak markdown
  bold-colon). Detection biases to *ingredient* when ambiguous (a wrongly-promoted heading hides a real
  ingredient), so **~11 ambiguous rows** (2 "X Ingredients", 1 italic, the section-word garnish/frosting
  rows) are a **small manual to-do** via the editor heading-toggle.
- **Heading detection rules + backfill done (follow-on).** Added a shared `import_cleanup.section_signal`
  helper with **4 corpus-verified amount-less patterns** — "X Ingredients" (meta-word), unit-system
  labels, "Day N" stage labels, and a prep-component allowlist `{egg wash, dredge, sponge, brine}` —
  layered on top of `is_section` (which stays pure, since `classify_step` also uses it). A backfill
  promoted **9** more existing rows. The **prep-vs-food distinction**: preparations *made from*
  ingredients (egg wash/dredge/sponge/brine, glaze/marinade) are only ever headers → safe to detect;
  foods that are also ingredients (sauce/potatoes/salsa/meatballs/dough) collide → hand-toggle. **~10
  ambiguous rows** (Pastina variants, Frosting, Cheddar Mash, Salsa, Meatballs, Loaves, italic Vanilla,
  plus Spice Mix left-as-ingredient and the 2650 merge-fix) remain a manual to-do.
- **App rename pending:** "Seasonal Kitchen" → **"Chef's Choice"** across UI + docs (decided; not
  yet applied — see design-decisions.md).

---

## Tier 2 — Near-term core experience

### Cooking Mode (P2)

- **2a — Full-screen step-by-step** with the screen kept awake (Screen Wake Lock API).
- **2b — Check off ingredients & steps** (mise en place) while cooking.
- **Schema:** none. **Depends on:** nothing. Isolated, high daily value.

### Recipe Metadata & Organization (P8)

Small recipe-metadata features that later filtering/discovery depend on.

- **8a — Want-to-try / favorites.** Status flag + filter. Tiny.
- **8b — Tags / collections.** Freeform labels; tags + recipe-tags join (mirrors the regions
  pattern).
- **8c — Dietary flags.** Vegetarian/vegan/GF/allergens, set manually for now; later derived
  from ingredient tags (after Phase 12).
- **8d — Cuisine / region taxonomy + region search.** Hierarchy (Indian → Kolkata,
  Delhi); search/filter by it. Foundational — also feeds origin-based substitutes (Phase 13)
  and AI scan (Phase 16). *Schema:* recipe cuisine/region structure.

### Search, Sort & Discovery (P10)

Builds on Phases 8–9.

- **10a — Search ranking & sort.** Rank matches (name > ingredient > notes); sort by
  rating, cook count, recency, cuisine, time, tag. Sets the home list's default order.
- **10b — Filters.** Cuisine/region, tags, dietary, equipment, difficulty, time, favorites.
- **10c — In-season recipe filter.** Recipes whose linked ingredients are in season now
  (global or local season — see 10g; linked lines only).
- **10d — Surprise me.** Random recipe, optionally honoring active filters.
- **10e — Pairing / side suggestions.** Accompaniments from the existing ingredient `pairs`
  data; richer version after enrichment (Phase 12).
- **10f — Reverse lookup.** From an ingredient's field guide, list recipes that feature it.
  Basic version already exists via the field guide's "used in"; this expands it, and with the
  pantry (Phase 13) becomes "recipes you could make using what you have."
- **10g — Local / regional seasonality.** Today an ingredient's season is one global month
  list. This makes it location-aware: set a home location (e.g. Boston) and "in season"
  reflects the *local* calendar — asparagus and tomatoes peak weeks apart in New England
  vs. California. Surfaces in the field guide ("in season near you") and feeds the 10c filter.
  *Schema:* region-scope the season data (a region/zone dimension on the per-ingredient
  season rows, or a separate region-season table) plus a stored home location/region.
  *Depends on:* sourcing real regional seasonal calendars (state agricultural / extension
  guides, CSA charts) and transcribing them with you rather than approximating — same
  discipline as the King Arthur weights (1c), and shares the data-entry character of
  ingredient enrichment (Phase 12). Global season stays the fallback where a region has no
  local data.

### Trash / Soft-delete (P7)

Replace permanent deletion with soft-delete: mark a recipe deleted, exclude it from lists,
and provide a Trash view to restore or permanently remove it. Plus undo for the last
destructive action.

- *Schema:* a `deleted_at`/`is_deleted` flag on recipes; the delete endpoint flags instead of
  removing, and list/detail queries exclude deleted rows.
- **Why here:** today deletion is permanent and cascades to a recipe's ratings, history, and
  changes — this prevents accidental loss as more data accrues.

### Dark Mode / Theme Toggle (P3)

App-wide light/dark toggle. Frontend only, no schema. Cheap; pull forward freely.

---

## Tier 3 — Data-asset features

**Strategically central (see the Data philosophy, Tier 0).** These exist to capture the scarce,
valuable signal — what gets cooked, how it turns out, what gets changed — structured and
timestamped from the start. Grouped together because together they build the outcome dataset that
grounds the long-term vision; individually modest, collectively the whole point.

### Photo Upload (P4)

Upload a recipe photo in-app instead of dropping a file in `static/images`.

- **Scope:** Flask multipart endpoint, save locally, store the path. *Schema:* none.
- **Depends on:** nothing. Prerequisite for per-cook photos (Phase 5) and AI scan (Phase 16).
- **Notes:** validate type/size, safe filenames.
- **4b — Inline step-reference photos.** Attach a photo to a SPECIFIC step ("what the dough should
  look like at this point") for cooking-time reference — distinct from the single finished-dish
  image. *Depends on:* image storage (the roadmapped write-layer step) + a step-level media relation
  (`recipe_steps` → image). Groups with the cooking-mode / richer-step cluster (Phase 2; the
  per-step-duration refinement in 9b). The Round-1 design **reserves layout room** (a step-body
  wrapper) so it attaches later without a retrofit — see docs/design-decisions.md.

### Per-cook Journal (P5)

Notes (and an optional result photo) on each cook-log entry — what changed, how it turned
out. Optionally record how long it **actually** took (feeds time calibration, Phase 9e).

- *Schema:* columns on `cook_log` (note, photo path, actual active/elapsed time).
- **Depends on:** Phase 4 for the optional photo.
- **Why here:** moves `cook_log` toward the detail that time calibration and the friend feed
  (Phase 17) need.
- **5d — Bake conditions (weather).** Optional temperature + humidity fields on each
  cook-log entry, to correlate ambient conditions with how a bake turned out (fermentation
  speed, proof time, dough feel) — mainly for bread/sourdough. Manual entry is cheap and
  rides on the Phase 5 journal record (near-zero extra schema). Automatic weather (fetch by
  date + home location) is deferred: needs a weather API + a stored home-location setting —
  the same per-user settings store that a global units preference (import-units note) and the
  Phase 19 recommender's saved-mood preference would also use. Build that store once for all
  three. Niche (irrelevant to most savory cooking) — keep it an optional field, not a
  prominent feature.
- **5e — Per-cook ratings → displayed average (significant; own design pass).** Move from one rating
  per **recipe** to one rating per **cook**; the recipe's displayed stars become the **average**
  across cooks (cook it 3×, rate those 3/4/5 → shows 4; each cook keeps its own score). Fits the
  used-cookbook idea — the rating becomes a record of experience over time (dialing a recipe in), not
  a static verdict. **Substantial, hence future:** (a) **data model** — the rating attaches to a
  `cook_log` row, not the recipe (schema change / migration); (b) **ripples through what was just
  built** — the redo feature, the cook-gate, the "undo clears the rating when cook_count hits zero"
  invariant, and `/cooked-and-rated` all assume **one rating per recipe**, so this unwinds that
  coupling; (c) **migration** of the existing ~117 recipe-level ratings to the per-cook model (attach
  each to which cook?); (d) **display/UX** — showing an average (halves? — a granular-rating display
  choice), rating a specific cook, whether the cook log shows each cook's score, editing a past cook's
  rating. Needs its own real design pass when tackled.
- **5f — The Cooking Journal (the reflective per-recipe history; big, its own project).** The full
  realization of this per-cook layer: each cook becomes an **annotatable ENTRY**, with notes that are
  **both free-text AND optionally LINKED to specific recipe changes**, so a note can capture *"changed X on
  this cook → here's how it went,"* forming a record of how a dish **evolves across attempts**. This is the
  **"used cookbook" thesis made into a feature** — the accumulated personal layer made explicit.
  **Composes several existing layers:** the cook-photo **album** (P4 / Stage 4), the **cook-gated ratings**,
  and (once built) the **change-tracking layer** below.
  - **⚠️ CORRECTION — change-tracking is NOT built (a diagnostic this session):** an earlier version of this
    entry linked notes into "the existing edit-tracking layer (`recipe_line_changes` / `recipe_additions`)."
    Those tables were **dropped in migration `020_drop_change_layer.sql`** — a per-person overlay on read-only
    SEED recipes (`source='seed'`, 0 in prod), **always empty**, made redundant by the box model (recipes
    owned + directly editable, copy = duplicate). Editing today is a **destructive rewrite**
    (`write_recipe_rows` replaces the ingredient/step rows in place) — **no before/after, no timestamp, no
    per-change identity.** So there is **no change-tracking today**; the Journal's real prerequisite is to
    **build one from scratch** — NOT to adopt a rich-text editor framework (that's **DONE** — TipTap + the
    Vite build + the `[[key|label]]` step adapter are shipped; see `docs/design-decisions.md`).
  - **The change-tracking prerequisite — LOCKED design (this session):**
    - **HYBRID (snapshot + derived diff):** **snapshots** (full recipe VERSIONS) are the stored truth; the
      "specific changes" are **DERIVED by diffing consecutive snapshots** — one source of truth + a diff
      function (no separately-tracked per-line change rows).
    - **TRIGGER:** snapshot **on COOK** (capture recipe-state when a cook is logged) **+ a manual "save a
      version"** — BOTH from the start. A snapshot carries a **REASON** (`cook` | `manual`), so the trigger
      is a **parameter**, not baked into the cook path (keeps the model general).
    - **"The Journal IS the history":** no separate diff/history-view feature; the **Journal is the surface**
      that shows recipe evolution — a cook-entry shows the **version-cooked-from** AND the **diff-from-
      previous-snapshot** ("what I changed since last time").
    - **Notes link to changes:** a journal note can reference a **specific change from the derived diff** (the
      "improvements associated with changes" core).
  - **SEQUENCING:** the change-tracking layer is the Journal's **prerequisite** — build it, **THEN** the
    Journal. The album's last stage (**3e — anchor-photo-to-method-step**) is itself deferred **behind both**
    (order: change-tracking → Journal → 3e).
  - **Build the tracking layer needs its OWN diagnostic FIRST** (flagged, not assumed): where the snapshot is
    captured in the **cook-log** + **manual-save** paths; **WHAT** a snapshot stores (full recipe rows? a
    serialized blob?) + its size/shape; how the **diff** computes over the stored form; how a **note attaches
    to a change** (a change's referenceable identity **from the diff**); how it composes with
    `write_recipe_rows`' destructive rewrite + the box-model ownership. The next session on this **opens with
    that read-only diagnostic → then scope the build.**
  - **Deferred design decisions (settle at its own design pass):** *page-vs-drawer* (a separate route/page
    vs. a panel over the recipe); and the *journal-vs-album relationship* (do cook-photos live INSIDE
    journal entries, or does the recipe-page album coexist?). **Preview-first** (a whole new surface).

### Analytics Dashboard (P18)

A `#/dashboard` view that surfaces patterns in your cook log — when you cook, what you
cook most, and what your weekly rhythm looks like — so you can spot preferences at a
glance and sketch a plan for the week.

**What's possible with current data (no schema change):**
- **Seasonality.** Which months you cook most, and which recipes appear in which seasons —
  built from the existing `cooked_on` date on every `cook_log` entry.
- **Top recipes.** Most-cooked recipes ranked by count, with last-cooked dates.
- **Weekly pattern.** Which days of the week you tend to cook, and which recipes appear on
  which days, derived from `cooked_on`.
- **Cook frequency.** Cooks per week/month shown as a bar chart or calendar heatmap.

**What needs a small schema addition:**
- **Time of day.** An optional `cooked_time` column (`HH:MM`) on `cook_log`, recorded when
  you log a cook and null for existing entries. Unlocks morning/afternoon/evening breakdowns.
  *Schema:* one nullable `TEXT` column — a one-line `ALTER TABLE` migration, same pattern
  as `007`.
- **Meal type.** An optional `meal_type` label (breakfast / lunch / dinner / snack) for
  explicit tagging rather than inferring from time. *Schema:* one more nullable `TEXT`
  column on `cook_log`.

**Weekly schedule helper:**
Shows your historical day-of-week patterns ("you tend to try new things on Sundays") and
lets you pin a recipe to each day to sketch a plan. Read-only pattern view first; the
pin-to-day layer follows. A deliberate precursor to the full meal planner (Phase 13e) —
when Phase 13e ships, this view folds into it rather than sitting alongside it.

- *Depends on:* Phase 5 (per-cook journal) for richer per-entry context; the core
  seasonality and top-recipe views work on current data and can ship before Phase 5.
- *Synergy:* weekly pattern data feeds Phase 13e (meal planner); time-of-day data feeds
  Phase 9e (time calibration); observed cooking habits make a planner feel personal rather
  than generic.
- **Can be pulled forward** to right after Phase 5 — the core analytics need no new
  schema and no dependencies beyond what's already built.
- *See also: Phase 19 (recipe recommender) — shares cook_log as its data source;
  analytics patterns (day-of-week, recency) inform the recommender's scoring.*

### Data Health Check (P6)

Extend `build_db.py`'s report to flag: unused ingredients, recipes missing a photo, and
plain-text ingredient lines that *could* be linked to the library.

- **Why here:** low-risk maintenance tool. The "could be linked" check directly supports the
  linking prerequisite for pantry (Phase 13) and in-season (Phase 10). Useful before bulk
  recipe entry.
- **Grow into a coverage/health suite** reusing one data scan: (1) ingredient-library
  linkage — % of recipe lines linked to the library (foundational; gates in-season and
  pantry); (2) volume→weight conversion coverage (being built now with Phase 1c — see the
  conversion-coverage report in `build_db.py`); (3) recipes never cooked / never rated (feeds
  the Phase 19 recommender); (4) recipes missing a photo; (5) flag **messy ingredient names**
  — lines whose ingredient text looks combined ("beef mince ground beef"), instruction-laden
  ("very warm tap water up to 130 f"), or alternative-bearing ("naan or arabic taboon bread"),
  detected cheaply by reusing the coverage scan. Conversion coverage ships now with
  1c; bring the rest forward into Phase 6 when ready.

---

## Tier 4 — Later features

### Planning Attributes (P9)

Recipe attributes for deciding what and when to cook. Their filters surface in Phase 10.

- **9a — Equipment list + filter.** "Needs a wok / blender". *Schema:* equipment field/table.
- **9b — Structured time (active vs wait).** Replace coarse prep/cook/total with **active**
  time (hands-on), **hands-off/wait** time (marinate, rise, chill, rest, cool), and **cook**
  time; total derived. Waits can be itemized, so a recipe shows both active and elapsed
  (wall-clock) time. *Schema:* structured time fields on recipes.
  - *Later refinement:* per-step durations (each step tagged active/passive with a time) —
    more accurate, auto-derives totals, powers cooking-mode pacing and a backwards schedule.
- **9c — Difficulty + filter.** Manual, or later derived from active time.
- **9d — Make-ahead prep.** Flag ingredient lines that can be prepped ahead, with an optional
  storage note (e.g. "airtight, fridge, 5 days"). A "prep plan" view splits the recipe into a
  **prep-ahead list** (do anytime) and a **day-of list**. *Schema:* a flag (+ note) on recipe
  ingredient lines.
  - *Later:* combine with the meal planner (Phase 13e) for a weekly batch-prep list, and with
    9b to show *day-of* active time (active minus what's prepped ahead).
- **9e — Calibrate times from your cooks.** Using actual durations logged in the journal
  (Phase 5), show your personal average against the recipe's stated time and optionally adjust
  the estimate. Most accurate with per-step durations (9b refinement). The most direct fix for
  inaccurate recipe times.

### Sub-recipes / Components (P11)

Let a recipe reference another recipe as a single ingredient line (e.g. the bulgogi drizzle
sauce as its own recipe, reused in the bowl). Same idea as ingredient linking, aimed at the
recipes table.

- **v1 scope:** a line links to another recipe (`{component: "..."}` in `seed.py`), clicking
  opens that recipe, and `build_db.py` validates the reference exists. *Schema:* a
  component-recipe reference on recipe lines.
- **Notes / complexity:** cycle detection + a nesting-depth limit; v1 references a whole
  batch (fractional scaling later); v1 links out (inline expansion later). Synergy with
  make-ahead (a prepped component). Add notes to Phase 1 (scale components with the parent)
  and Phase 13 (recurse into components for match %, substitutes, shopping lists).

### Ingredient Enrichment: citations + flavor/category tags (P12)

- **Citations.** One or more sources per ingredient, shown on the field guide.
- **Flavor/category tags.** Category (allium, chili, herb…), flavor notes, spice grouping —
  distinct from `pairs` ("goes with", not "stands in for").
- *Schema:* citations + tag fields/tables on ingredients.
- **Cost:** schema + manual entry free; AI-assisted gathering is an optional paid upgrade.
- **Why here:** substitutes (Phase 13c), the dietary-derivation upgrade (Phase 8c), and
  richer pairings (Phase 10e) all need these attributes.
- *Depends on clean ingredient identity — see the Ingredient-line data model note (top).*

### Recipe Cost — cost-effective meals (new)

Surface which recipes are **cheap**: a cost dimension on the existing recipe/ingredient data — *"what do
these ingredients cost → rank/flag cost-effective meals."* A wanted Chef's Choice **feature** (in-app, not
a separate tool).

**Feasibility findings (from a research pass — these RESHAPE the idea; recorded honestly):** the original
*"live Instacart prices"* premise has a real hole.
- **No clean official Instacart pricing API** — only third-party **scrapers** (~$10 / 1k products,
  legally + technically fragile).
- **Bigger: Instacart now uses PERSONALIZED algorithmic pricing** — the same item shows **different prices
  to different shoppers** (~75% of items, up to ~23% variance, per a **Dec 2025 Consumer Reports**
  investigation). So *"the live Instacart price of an ingredient"* **isn't a single number anymore.**
- **Implication:** the live-precise-Instacart version is **NOT viable.**

**Viable shape:** use a **STABLE source** instead — **USDA average retail food prices** (public, free),
store-**circular** data, OR just **RELATIVE / APPROXIMATE** costing (rank recipes cheap→expensive from rough
ingredient-cost estimates, no live feed). Capture this as **"approximate / relative cost per recipe from a
stable source"** — **NOT "live Instacart prices."**

- **Needs its own design + a data-source decision** (which stable source). *Depends on clean ingredient
  identity (the linking prerequisite — see the Ingredient-line data model note, top). Synergy: the shopping
  list (13d) and pantry (13b).*

### Pantry & Planning (P13)

The large data cluster.

- **13a — Essential-ingredient flag.** Missing an essential ingredient rules a recipe out
  entirely, regardless of match %. *Schema:* a flag on recipe lines.
- **13b — Pantry inventory + match %.** What you have; "you have X% of this" / "you're 2
  away". *Schema:* a pantry table.
- **13c — Substitute suggestions.** For a missing ingredient, suggest library substitutes by
  shared attributes (region/origin, flavor/category, spices) from Phase 12. Rule-based/free;
  AI-ranked is an optional paid upgrade.
- **13d — Shopping list.** Aggregate ingredients from selected recipes, minus the pantry.
- **13e — Meal planner.** Assign recipes to days/week; generate a shopping list (and, with
  9d, a weekly prep-ahead list) from the plan. *Schema:* a meal-plan table.
  *See also: Phase 19 (recipe recommender) — the "what should I cook" single-pick view
  that feeds naturally into this planner once it exists.*
- **Capstone view — "what can I cook tonight":** emerges from pantry (13b) + in-season (10c) +
  time (9b) + make-ahead (9d). Not new data, just a combined view.
- **Cross-cutting:** match %, substitutes, in-season, and shopping-list subtraction work only
  on recipe lines **linked** to the library; recurse into sub-recipes (Phase 11). Linkage
  quality depends on clean ingredient identity — see the Ingredient-line data model note (top).

### Output & Portability (P14)

- **14a — Print / PDF export.** Clean printable recipe (print stylesheet or server-side PDF).
- **14b — Export / import recipes.** Back up to / restore from JSON (recipes, changes,
  additions, ratings, cook history). *Placed late on purpose:* earlier phases keep adding
  tables, which would otherwise force repeated rewrites of the export format.

### Recipe Collections ("playlists") + Sharing (P20)

Group recipes into named, ORDERED collections — "playlists" of recipes (e.g. "Thanksgiving",
"Weeknight dinners") — and, separately and much later, SHARE recipes and whole collections with
friends. **Two tiers by cost; they are very different lifts.** Tier 1 (collections) is buildable in
the current architecture and lives here in Tier 4. Tier 2 (sharing) — anything beyond
export-a-file — is a major networked/hosted/multi-user DIRECTION, not a feature; it escalates into
Tier-5 territory and overlaps Phase 17 (decide the architecture before committing).

**Tier 1 — Collections (local organizing; moderate, fits current architecture):**

- A collection = a named, ORDERED set of recipe references. New tables (`collections` +
  a `collection_recipes` join), CRUD, a collections view, and add/remove a recipe to/from
  collections.
- Purely local / single-user — no networking needed. Consistent with the current app.
- **Benefit:** organize recipes by occasion/theme; a natural fit with the existing recipe model.
- **Cost:** a new entity + join table + UI — moderate but self-contained. *Schema:* `collections`,
  `collection_recipes` (ordered).
- *Relation:* a first-class, ordered, named-collection feature that extends the lightweight
  "8b — Tags / collections" idea (Tier 2); if 8b ships first, this builds on it.

**Tier 2 — Sharing (BIG — breaks the local-only / single-user / no-auth assumptions):**

Sharing recipes/collections with other people requires the app to be reachable by others — hosting
a server others can hit (not just localhost), and possibly identity (who shares with whom) + a
sharing mechanism. A spectrum, smallest to largest:

- **(a) Export / import a file** — export a recipe or collection as a self-contained file (JSON, or
  a standalone HTML page) the friend opens/imports. Gives "sharing" WITHOUT becoming a multi-user
  server app. **Smallest lift; the pragmatic first version.** Rides on Phase 14b (export/import).
- **(b) Public read-only LINK** — host the app (or a static export) so a friend opens a URL.
  Requires hosting + a public/shareable representation. Medium.
- **(c) Full MULTI-USER** — accounts, auth, per-user data, sharing between users. Large; a
  fundamental change from the current single-user local app. **This IS Phase 17** (friend feed /
  multi-user / hosted) — track the heavy version there.
- **Benefit:** share recipes/collections with friends. **Cost:** ranges from small
  (export-a-file) to a major re-architecture (multi-user). Sharing an individual recipe is the same
  spectrum (export → link → accounts).

**Note:** Tier 1 is buildable now within the current architecture. Tier 2 — especially anything
beyond export-a-file — is a major direction (networked/hosted/multi-user), not a feature; decide
the architecture before committing. **Export/import (2a) is the recommended first step for sharing**
if/when pursued. *Cross-ref: Phase 14b (export/import), Phase 17 (multi-user / hosting).*

---

## Tier 5 — Far-future vision

Depends on the full dataset (corpus + linkage + the Tier-3 outcome data).

### Friend Cooking Feed / multi-user (P17)

- **Free local precursor (can be earlier):** attribute `cook_log` to a person and show an
  in-app activity view; one instance only, no cross-device sharing. (Phase 5 already moves
  `cook_log` this way.)
- **Full networked version:** multi-user accounts, a hosted database, a deployed server.
  Largest architectural change here and the only feature with an ongoing monthly cost.
- **Why last:** a different class of project (deployment + multi-user) than the rest, which is
  local and single-user.

### Ingredient-compatibility — social discovery (deferred)

Compare two friends' recipe boxes by **shared-ingredient overlap** ("you both cook heavily with
doubanjiang / sumac") — a lightweight social-discovery angle. **Computable cheaply from existing joins**
(`recipe_ingredients` ⨝ the ingredient library, per owner) — **no new data**. **Discovery-polish, not
foundational:** it needs a working friend network (P17 / the social layer) first, so it's deferred to
after that lands. Doubles as a **soft on-ramp to the ingredient-adjacency moat** (hook A / the P19
recommender): the same ingredient-overlap machinery that surfaces "you two cook alike" is a first step
toward "you like X, try adjacent Y." *See [docs/product-vision.md](docs/product-vision.md) (the moat +
the finalized social-layer build plan).*

### Chef profile — a personal cook-page (identity, not competition)

Each user has a profile / "wall" — who they are **as a cook**: their achievements (cuisines explored,
techniques tried — **variety not volume**, per the achievement rule), their box / signature dishes, a bit
of "this is me as a cook." The MySpace **"this is me" warmth** — WITHOUT MySpace's death (the
performance/competition dynamic).

⚠️ **THE LINE** (same as comments/feed — identity/connection YES, competition/metrics NO):

- ✅ **Identity / expression:** your dishes, who you are as a cook. Your friends see **you**.
  Achievements are the private part. They sit on your own profile page and a friend never sees them.
- ❌ **Performance / competition:** NO follower counts, NO "Top 8 friends" ranking, NO visitor counts, NO
  "most cooked" leaderboards — nothing that makes the profile a scoreboard or popularity contest (that's
  the exact MySpace/Facebook drift the connection-not-consumption principle rejects). The nostalgia is for
  the **identity/expression**, not the competition.
- The **achievements** system is hidden until earned, awarded for range rather than repetition, and
  private. It IS the profile's core content and the profile is where achievements live and get shown,
  on your own page. Nothing is ranked and nothing is compared, which is what keeps it on the right side
  of THE LINE above. See the engagement hooks in
  [docs/product-vision.md](docs/product-vision.md). So **"chef profile + achievements" likely build
  together as one future sub-stage.**

**Market signal** (a viral 2026 Reddit thread on missing early-Facebook/MySpace): people are nostalgic
for the friends-only feed + the "this is me" profile, and explicitly hate what killed them (ads,
algorithms, "impressing random people," feature-pile-on/games, non-private opening-up). Every principle
enshrined here maps to something that thread mourns — strong directional validation of the thesis (though
nostalgia ≠ proven willingness to switch; the real test is friends actually using it).

**Sequencing:** deferred — its own sub-stage, **AFTER** the current feed + comments work. Do NOT derail
the in-flight feed.

### Eventual architecture (north-star — FUTURE, not current work)

The long-term destination for taking the app multi-user. **This is NOT current work** — the app
is deliberately local, single-user, and no-auth today, and that is the right shape for now. This
records *where it's headed* so today's choices point toward it; actually building the multi-user
stack is a big, deliberate future project for when multi-user genuinely arrives. It's the shape
and an honest cost map, not a build plan. (Pressure-tested against the real codebase, so the costs
below reflect what's actually in the repo, not an idealized version of it.)

1. **Backend — the API/UI boundary is already clean** (not merely "partway"). 20 of 21 routes are
   already JSON `/api/…` endpoints; the one non-API route just serves the static `index.html`
   shell — there is no Jinja, no `templates/`, no server-rendered HTML anywhere. So the multi-user
   backend work is mostly: **add CORS** (there is none today) locked to the frontend origin, and
   decide whether Flask keeps serving the shell/assets or that moves to a CDN / static host.

2. **Frontend — already a pure JSON SPA** (hash-routed, talks JSON exclusively, paints via
   `innerHTML`, no forms or full-page loads). The eventual frontend is likely **React**. Note the
   sequence: the near-term editor work introduces a **build step (Vite)** as the first toolchain
   move; the eventual React frontend is a later, larger rebuild on top of that.

3. **Database — SQLite → PostgreSQL, but this is a data-access-layer REWRITE, not a config change.**
   *(NOW IN PROGRESS — this piece was pulled forward ahead of auth/rescoping; the staged plan +
   decisions live in [docs/migration-plan.md](../docs/migration-plan.md). Stage 1a done: SQLAlchemy
   models mirroring the live schema.)*
   There is **no ORM today** — it's raw `sqlite3` throughout (`app.py`, `build_db.py`, `migrate.py`,
   `import_write.py`). The migration means: introduce an ORM or a Postgres driver and **port every
   hand-written query**; port SQLite-dialect DDL (`INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL` /
   `IDENTITY`; `TEXT`-stored dates via `datetime('now')` → real `timestamptz` plus a data-coercion
   pass; the `PRAGMA foreign_keys` handling and `build_db.py`'s foreign-key rebuild trick are
   SQLite-only); and adopt a real migration tool (today: 15 hand-written SQLite-dialect `.sql` files
   run by a custom `migrate.py`, not Alembic). *Bright spot:* the `ON CONFLICT … DO UPDATE` upserts
   port to Postgres fine. The data **shape** (e.g. `recipe_steps.text` with `[[key|label]]` / `{{}}`
   markup) is DB-agnostic and unaffected.

4. **Auth — deeper than "accounts + password hashing."** The single-user assumption is woven into
   the **schema** and must be rescoped. Today: the `people` table is **not** auth — it's a seeded
   "whose version am I viewing" config switcher (no passwords, sessions, or login); `ratings` is
   global one-per-recipe (`recipe_id` as `PRIMARY KEY` — multi-user breaks this; it needs
   `(recipe_id, user_id)`); `cook_log` has no user column; recipes have no owner (only a `source`
   tier). So real auth drags behind it a **rescoping of the core outcome tables** (`ratings` +
   `cook_log` — the app's stated scarce asset, currently global/single-user), plus an `owner_id`
   and authorization on every mutating route. *(A former "head start" note here — that
   `recipe_line_changes` / `recipe_additions` already carried `person_id`, so the multi-actor model was
   half-built there — **no longer applies:** those tables were dropped in migration
   `020_drop_change_layer.sql` as vestigial (always empty). See the Journal (P5·5f) correction.)*

5. **Hosting — a cloud platform.** Render for a simple Flask + React deploy; Docker / Nginx if it
   outgrows that.

6. **Editor implication — TipTap is forward-compatible (and already ADOPTED).** The step editor is
   **shipped today** — TipTap over vanilla JS, steps-only, with live `[[key|label]]` link chips, over the
   unchanged `recipe_steps.text` storage via a pure parse/serialize adapter (`static/step-adapter.js`); see
   `docs/design-decisions.md`. It's framework-agnostic and has first-class React bindings (carries into the
   eventual React frontend). *Honest caveat:* `paintRecipe`'s full `innerHTML` re-render is hostile to a
   mounted editor instance (it destroys the node) — **handled today** by the "ISLAND INVARIANT" (paint fires
   only at load/enter/exit, so mount-on-enter / destroy-on-exit suffices), but **TipTap-in-React is what
   removes the friction outright** (React owns the DOM). So #2 (the React rebuild) and #6 stay coupled — the
   React frontend is what pays off the editor-integration tax; the *adoption* itself is not pending.

7. **Image / file storage.** Images are currently **filesystem path strings** served off local
   `static/images/`, with **no upload endpoint**. On an ephemeral-filesystem host (e.g. Render),
   uploaded files vanish on redeploy, so multi-user with user-supplied photos needs **object
   storage** (S3 / R2-class) plus a real upload path. Not built today.

8. **The seed / build-db / source-tier content model is itself a single-user conceit.** The current
   "content lives in `seed.py`, rebuilt every build, user data preserved by source tiers"
   architecture assumes one curator. In a multi-user UGC world, recipes become user-generated and
   `source='seed'` vs `'app'` stops being the right axis — **ownership** does. Expect the
   rebuild-from-seed model to largely dissolve; this is a conceptual shift, not just a schema change.

**Caveat:** implementation specifics — the exact auth mechanism, the Postgres migration steps, the
hosting choice, the object-storage approach — are **not decided**. Each gets its own research and
design when multi-user gets closer. This section is the direction and the honest cost map, not a
build plan.

### AI Recipe Scan / auto-populate (P16)

Read a recipe from a photo or pasted/messy text and auto-fill the form for review.

- **Depends on:** Phase 4 (photos); quality improves with Phase 8/12 metadata. Complements
  Phase 15 (use free JSON-LD when available, AI for the rest).
- **Cost:** per-use API (~cents per recipe), needs a key. Always confirm the parsed result —
  models misread quantities and names.
- **Payoff:** turns "upload more recipes" from typing into review-and-edit.
- *Also the place to apply structural ingredient-line cleanup — see the Ingredient-line data
  model note (top).*

### "What's for Dinner" Recommender (P19)

Suggests ONE recipe for tonight from cook history + ratings, driven by a mood.
Answers "what should I cook" with a single decisive pick, not a list.

- **Moods (pick one):**
  - *New* — favors never-cooked then rarely-cooked; rating mostly irrelevant (exploration).
  - *Old* — longest gap since last cooked, gated by a good rating (resurface a forgotten
    favorite, not a flop); never-cooked excluded.
  - *Surprise* — balanced: mostly rating, a variety bonus for a longer gap, a dash of novelty.
- **Universal:** exclude anything cooked in the last ~14 days (tunable); pick via weighted
  random choice among the top ~5 by score so "show another" varies; show a "why this pick"
  line; graceful fallback when filters leave nothing (relax and explain, never error).
- **Scoring:** a transparent weighted score from recency, frequency, rating, novelty — not ML.
  Weights are tunable constants; expect a tuning round.
- *Schema:* none. Read-only endpoint + small view. Can be pulled forward — v1 needs no
  schema change.
- *Scale note:* low value at ~5 recipes; compounds at 20–50+.
- *Deferred:* seasonality weighting (cheap later); quick/weeknight (needs Phase 9b structured
  time); day-of-week (overlaps Phase 18); multiple suggestions / planning (that's Phase 13e).
- *Settings store:* a saved-mood preference (remember your default mood) would use the same
  future per-user settings store as Phase 5d (weather fields) and the import-units note —
  build it once for all three.
- *See also: Phase 18 (analytics) — shares cook_log; Phase 13e (meal planner) — the natural
  next step once you have a single-pick recommender.*

### Recipe recommendation — bandit framing + honest limitations (research; P21)

Capstone/thesis-adjacent research framing of the recommender problem — **not a near-term feature**.
Companion to **Phase 19** (the pragmatic single-pick recommender); this entry records the
multi-armed-bandit framing that was explored and, more importantly, why it does *not* transfer to
this app as-is.

- **Origin:** surfaced alongside a separate RL-course (CS5180) project reproducing the
  Auer/Cesa-Bianchi/Fischer multi-armed bandit algorithms (UCB1 etc.). **That bandit reproduction
  and its simulated-recipe recommender are coursework (separate repo) — NOT part of this app.** This
  entry is only about a potential *real* recommender feature here.
- **The idea:** the app already has the two ingredients a bandit recommender needs — recipes
  (**arms**) and a cook signal (`cook_log` = did the user actually cook it = **reward**) — so "learn
  which recipes to surface from whether they get cooked" sits naturally on the existing data, and
  ties to the app's IR/recommender thread (capstone interest).

**Honest caveats (why this is NOT a quick feature):**

- **Cold start is the killer.** ~295 recipes, one user cooking a handful of times a week = extremely
  sparse data. A plain multi-armed bandit over hundreds of arms needs many pulls per arm to
  converge; one person's dinner cadence will basically never give a MAB enough signal. The bandit
  math that works in simulation (many seeds, 2000 rounds) does not transfer to one real user.
- **Stationarity.** A user's tastes drift; standard UCB assumes fixed reward distributions.
- **Independence.** Similar recipes are correlated (cook one Thai curry → likely cook another);
  plain MAB ignores this.

**Realistic paths (if pursued):**

- **Near-term / pragmatic — heuristics, not a bandit:** recommend by tag affinity, cook frequency,
  recency, ingredient overlap. No convergence problem; fits sparse single-user data. *(This is
  essentially Phase 19's transparent weighted score — start there.)*
- **Ambitious / research — contextual / feature-based:** a recipe + user feature approach addresses
  correlation and cold-start better than a plain MAB, but it's substantially more complex and only
  makes sense with enough data. **Capstone/thesis territory** (ties to the IR / ML-on-recipe-data
  thread, the King Arthur ingredient ontology, prior RAG work) — not an app feature.

- **Cost:** a real recommender is large + data-dependent; a simple heuristic version is moderate
  (≈ Phase 19). **Benefit:** surfaces relevant recipes — but only worthwhile once there's enough
  usage data and a clear approach (heuristic first; bandit/contextual only if justified).

### AI Recipe Generation (new)

A capable LLM (via API) generates **novel** recipes through RAG — grounded in our structured
corpus plus the outcome / pairing / cuisine data — rather than free-associating like a generic
model. Every generated recipe is marked **AI-generated + untested**, and **bounded away from
trusted food-safety-critical claims** (cook temperatures, preservation/canning, allergen safety):
those stay sourced-or-blank, and validation is *actually cooking it*. Depends on the full dataset,
library linkage, and the Tier-3 data-asset features being in place.

- **Strategic arc:** multi-user (P17) → more outcome data → better grounding + ranking — a
  grounding/signal **flywheel, NOT a training one**. We never train a model; we accumulate the
  signal that lets a capable off-the-shelf model do this well for *our* corpus.

---

## Continuous — Upload more recipes & data

Ongoing. Add recipes via `seed.py`, the in-app form, or import (Phases 15/16). Link
ingredients to the library so Phases 10c/13 work on them.

## Data gathering & cross-recipe analysis

A gathering agenda, decoupled from when the consumers get built. All blended-from-multiple-
sources-and-cited (see the Provenance principle). Enrich the existing ingredient/recipe tables,
NOT a separate dataset table.

- **Reference data:** savory/global ingredient densities (USDA etc. — directly lifts conversion
  coverage past today's 10/62); per-ingredient cup-variance (for the grams→cups range);
  substitutions; shelf-life/storage (USDA FoodKeeper — feeds pantry + storage-category sort);
  regional seasonality calendars (feeds in-season / Phase 10g).
- **Ingredient attributes (the dataset backbone):** category/type; flavor-pairing affinities
  (e.g. Flavor Network / shared-compound data — powers cross-recipe similarity); dietary flags;
  nutrition (USDA FoodData Central).
- **Recipe metadata:** cuisine, technique, course, difficulty, total/active time, equipment,
  numeric yield (also unblocks serves-N scaling).
- **Personal-generated:** per-cook outcomes (Phase 5), bake conditions (5d), edit/version
  history, cook frequency/recency/ratings over time.

**Cross-recipe analysis (late-stage, queryable — NOT ML).** Shared-ingredient overlap, cuisine
clustering, ingredient co-occurrence / pairings, similar-recipe finding — all QUERIES over the
clean corpus, not learned models. Depends on Phase 6 (linkage) + 8 (metadata) + 15/16/17
(volume); correctly late — meaningful only once linkage + metadata + corpus volume exist.

## Parking lot / undecided

- **Telling CLEANUP edits apart from PERSONAL changes in the annotation layer — DEFERRED, with
  reasoning.** The worry: ~298 recipes came from Paprika, imports land slightly wrong, and if much
  future editing is really janitorial cleanup then those corrections render as personal annotations and
  dilute the outcome signal the whole app is built to capture. Measured before designing anything
  (**[docs/import-damage-survey-2026-08.md](docs/import-damage-survey-2026-08.md)**) and deferred
  because every leg of the argument came back thin: the damage is **2.3% of ingredient rows**; a
  cleanup costs **~1 annotation entry, 1:1, no cascade**; **re-splitting a mis-parsed amount — the most
  valuable cleanup class — already produces ZERO entries**; **298/304 recipes are still byte-equal to
  baseline** (re-counted 2026-08-17; was 298/300 at survey time — the corpus grew by 4 test copies, the
  divergent set by 4), so the pollution is prospective rather than observed; and every cheap discriminating
  signal is unavailable (`import_flags` miss 79% of ingredient damage and 100% of step damage; there is
  no `updated_at`, no snapshot on manual save, and no non-`original` snapshots — so **no edit-time datum
  exists** for a grace-window). The chosen direction is to **fix imports at the source** (importer
  hardening under P15) rather than classify edits after the fact. Revisit only if real cleanup editing
  starts making the margins noisy.
- Backwards cook schedule ("start the rice at 6:40") — becomes feasible once per-step
  durations exist (Phase 9b refinement).
- AI-ranked substitutes (paid upgrade to Phase 13c).
- AI-assisted citation/tag gathering (paid upgrade to Phase 12).
- Derive dietary flags from ingredient tags (upgrade to Phase 8c, after Phase 12).
- Sub-recipe refinements: inline expansion, fractional batch scaling (Phase 11).
- Automatic backups (a build-time and/or scheduled hook around `backup.py`).
- Cloud image storage (only relevant if Phase 17 hosting happens).
- Voice / hands-free step navigation (reliable version needs a paid speech API).
- **Step-grouped, category-sorted ingredient view.** Group a recipe's ingredients by STEP
  (outer), within each step sort by STORAGE CATEGORY (inner — fridge/pantry/produce), so you
  see everything a step needs together and grab same-location items in one trip. Gated on two
  structures that don't exist yet: (a) an authored ingredient↔step link carrying PER-STEP
  PORTIONS (so a divided ingredient — "oil, divided" — appears under each step with the right
  amount; authored, NOT inferred from prose — decline-over-guess); (b) a per-ingredient
  storage-category field (Phase 13 pantry). Display is easy once both exist; the work is the
  data, and divided-across-steps is the design crux. Cross-ref Phase 2 (cooking mode) and 4b
  (step photos) for the shared ingredient↔step link, and 13/14 (pantry/grocery) for the
  category field + aisle-ordered shopping lists.
- **App-wide textured background (deferred; preview-first).** The Cooking feed page uses a
  linen-textured "desk" (an inline `feTurbulence` data-URI) + a lifted-page board treatment (see the
  sub-stage-2b feed work). Extend that textured surface to the rest of the app (home / recipe pages) so
  the whole app reads as ONE warm surface rather than "textured feed, plainer everything-else." NOT a
  copy-paste: the recipe/home pages already carry their own `--backdrop` desk gradient + patina
  (`.page.recipe-view`), so this is a RECONCILIATION — decide whether the linen texture replaces or
  layers over the existing gradient, and keep one coherent desk across pages. Its own preview-first
  stage (mock the recipe/home pages with the treatment, react, then build app-wide in one go). Likely
  pairs with the deferred logo/identity pass — both are "make the whole app cohere" work. Raised during
  the 2b feed build; parked per the out-of-lane-goes-to-roadmap rule.
- **Hand-drawn chef-hat avatar + logo/identity pass (deferred; own preview-first stage; pairs with
  app-wide texture).** 2b ships a SIMPLE placeholder chef-hat (inline SVG); the characterful hand-drawn
  mark is a dedicated later task (AI-generated SVG came out stiff/generic — likely needs an illustrator
  working from style reference only). Do it as its own preview-first stage alongside the app-wide texture
  above — both are "make the whole app cohere" identity work.

## Cosmetic / nice-to-have polish

Small display niceties. Low priority, no rush — none of these change behavior, only how a
value reads.

- **Show both units in Metric (near-term polish).** In Metric mode, for a line with a genuine
  volume→weight pair, show BOTH instead of grams-only — e.g. "4 tbsp (~36 g)": the volume
  primary (the exact authored value), grams in parens as the approximate hint (the "~" stays
  on the grams). *Open questions for build time:* applies only to genuine pairs — no-match
  lines, declined items, and already-metric amounts show their single unit unchanged; and
  whether showing both eventually makes the Imperial↔Metric toggle redundant. *Rationale:*
  grams-primary serves precision (bread/hydration), but showing both also serves cooks who
  don't always weigh. Refines Smart-Metric (Phase 1).
- **Dual-measure toggle display (next).** A line with BOTH measures (grams + secondary_measure
  volume, captured at import) should show the VOLUME in Imperial and GRAMS in Metric — symmetric
  across source orderings (weight-first "100 g (1 cup)" or volume-first "1 cup (250 g)"). The data
  is now captured (`recipe_ingredients.grams` + `secondary_measure`, migrations 011/012); wiring
  the toggle to pick the right one is the next step, folded with "show both units in Metric" above.
  Also covers count+weight lines like "1 can" + grams (e.g. condensed milk): show the count
  always, with the weight in the toggle's unit — Imperial "1 can (14 oz)" (grams→oz, a clean
  weight conversion), Metric "1 can (397 g)".
- **Grams→cups range, on hover (gated on variance data).** For cooks without a scale,
  highlighting a gram amount shows an honest RANGE in cups (e.g. "450 g ≈ 3¼–3¾ cups"), not a
  false-precise single value — grams→cups is lossy (packing variance). Range from real
  per-ingredient/per-category cup-variance (flours wide, liquids ~none, sugars medium), blended
  and cited (provenance principle); a flat ±% would show fake uncertainty on water and is worse
  than nothing. Reuses 1c density for the midpoint; weight-table-matched ingredients only
  (silent on unmatched — decline-over-guess). Hover keeps the display clean. Cheaper relatives
  on the same spectrum: the shipped "~" marker and "show both units" above.
- **Pluralize scaled units.** "2 medium head" should read "2 medium heads"; "1/2 large egg"
  ideally "1/2 large eggs". Needs unit-aware pluralization rules.
- **Friendlier tiny amounts.** Scaling a very small quantity down shows an honest small
  decimal (1/16 tsp ÷ 2 → "0.031 tsp") instead of rounding to a misleading "0". A nicer touch
  would render negligible amounts as words like "a pinch", but the app can't reliably infer
  when that's right.
- **Metric fractions on small values.** Large metric amounts now round to whole
  numbers (188 mL, not 187 1/2 mL), but a small one can still show a fraction ("1/2 kg"). Proper
  per-unit handling lands with the metric/imperial toggle (1b).

## Delight / easter eggs

Pure-delight extras — low-stakes, **do after the core R1 work is solid** (reward-yourself items).

### Hidden "photo of Theo" easter egg (the dev's dog)

A hidden, **unsignposted** trigger surfaces a **random** photo of Theo (the dog) — a private bit of
joy, deliberately *not* a feature.

- **Trigger:** genuinely hidden / unlabeled — a tiny easy-to-miss-but-clickable glyph, or the
  "Chef's Choice" wordmark itself. NOT a labeled button (the whole point is that it isn't
  signposted).
- **Reveal:** Theo appears as a small **framed snapshot** — a polaroid/photo tucked into the
  cookbook (reuse the existing framed-photo treatment, perhaps slightly rotated), fitting the
  used-cookbook aesthetic — NOT a generic modal/popup.
- **Photos:** a small set of Theo images in `static/` (e.g. `static/theo/`), random pick via
  `Math.random()`. Public repo is fine (just dog photos).
- **Scope:** trivial — a hidden click handler + a few images + a small framed reveal.
- **Cost:** trivial. **Benefit:** makes a personal app feel personal.

## Known limitations & tech debt

Things that are actually *wrong* in edge cases (not just cosmetic), plus deferred cleanups —
worth knowing before they bite. None of the *data* limitations occur in the current recipes.

- **`field-sizing: content` is Chromium-only — long ingredient names are unreadable while editing on
  Safari and Firefox.** `styles.css` sets `field-sizing: content` on `.ie-ov textarea.ie`, and the
  shipped focus-expand behaviour (Option B: the field wraps taller on focus to show the whole value)
  **depends entirely on it**. Neither Safari nor Firefox supports the property, so there the textarea
  stays one line and the user cannot see what they are editing. Measured with the property disabled,
  on the 44-character row `soft or silken tofu (drained for 20 minutes)` at a 560px viewport: the
  textarea renders **27.0px against a `scrollHeight` of 98** — clipped, with no scrollbar and no
  ellipsis. **Not caused by any recent work; it ships today.** Fix shape: a JS auto-height fallback
  (~10 lines) hung off the existing `input` handler — set `style.height = scrollHeight` when
  `CSS.supports("field-sizing", "content")` is false. This gets **more** important if the name column
  is ever made to wrap (see the wrapping deferral in
  [docs/design-decisions.md](docs/design-decisions.md), inline-editor section): a wrapped textarea
  without auto-height *clips* rather than ellipsising, which is strictly worse than today.

- **Row reorder is MOUSE-ONLY — no touch, and no keyboard path anywhere.** Drag-reorder (C0–C2)
  is built on **HTML5 native drag-and-drop**, which fires only for a mouse: there is no touch
  equivalent, and the spec defines no keyboard interaction. So on a phone or tablet, and for anyone
  navigating by keyboard, **rows cannot be reordered at all** — in the ingredient editor, the step
  editor, **or the photo album**, which has had the same gap since it shipped. This is a genuine
  accessibility gap, recorded here rather than left silent.
  The reorder grips are `aria-hidden` **because of** this, not as an oversight: a control announced to
  a screen reader that cannot be operated by one is worse than an unannounced one. **Un-hiding the
  grips is therefore GATED on building the alternate path — it is not an independent tidy-up.**
  Fix shape: one keyboard reorder mechanism covering **all three** lists together (the natural seam is
  `static/drop-index.js`, which is already pure and list-agnostic — `applyRowDrop` takes the same
  before-reference a keyboard "move up/down" would produce). Doing the two editor lists now and the
  album later would mean designing the same interaction twice and leaving the album inconsistent.

- **Lowercase ingredient section-headers — narrow detection + flag, not silent auto-classify.**
  Bare lowercase headers (e.g. "crust", "filling") are promoted to section headings only via a
  NARROW signal — a common-section-word list plus a same-recipe step-section mirror — and every
  promotion is FLAGGED (`section_suggested`) for confirmation, never committed silently. At scale
  (~295) the better answer than a broader auto-classifier is a quick review UI to confirm /
  reclassify flagged lines: broad auto-detection risks mis-classifying a real amountless
  ingredient, and a wrongly-promoted ingredient *disappears* from the list (the worse error).

- **Scaler — numbers that aren't quantities.** The scaler multiplies every number in a
  quantity string, so any number that isn't an amount-to-scale gets scaled wrongly:
  - *Parenthetical pack sizes:* `1 (14 oz) can` ×2 → `2 (28 oz) can`, when you want
    `2 (14 oz) cans` — the can size shouldn't move.
  - *Comma-grouped numbers:* `1,000 mL` is read as `1` and `000` separately and mangled.
  General fix: the 1d markup approach (mark which number scales). Safe today because no recipe
  uses these forms; add it here if a new recipe ever does.

- **`migrate.py` is not per-migration atomic.** `executescript()` runs statements in autocommit
  mode, so a migration that fails midway leaves a partial schema with no `schema_migrations`
  record. Only affects *future* migrations (the existing ones are applied and fine). Fix if it
  ever bites: wrap each migration file's statements in an explicit `BEGIN;` / `COMMIT;` block.

- **Tests are coupled to exact seed counts.** Adding recipes or ingredients to `seed.py` will
  make `test_list_recipes` (`== 5`), `test_ingredients_and_in_season` (`== 36`), and
  `test_seed_counts` go red until those three numbers are updated. Expected, not a bug — just
  update the counts when adding seed data.

- **Test harness mutates module globals without teardown.** `tests/harness.py` sets
  `migrate.DB` / `build_db.DB` / `app.DB` on shared module objects with no restore. Fine for
  sequential pytest; would break under parallel runs (pytest-xdist). Only relevant if
  parallelism is ever added.

- **Range scaling — per-item ranges (import).** The cleanup core parses ranges (`1–2 tbsp`) with
  both ends, and scaling multiplies BOTH — correct for divisible amounts, but WRONG for per-item
  ranges (`5–7 blueberries per cookie` shouldn't grow with batch size). Distinguishing
  discretionary from per-item ranges is itself an ambiguity problem; revisit later, don't force
  it at parse time.

- **Fractional counts for divisible ingredients (scaling).** The scaler humane-rounds counts to
  whole numbers, but some ingredients divide fine (½ an onion, ½ a pepper, ½ a lemon) while others
  don't (½ an egg, ½ a can). Allow fractional counts where sensible instead of always rounding up.
  *Open design question:* how does the app know which divide? — a per-ingredient **"divisible"**
  property (a natural field-guide attribute — the entry carries the flag; see Ingredient Enrichment,
  Phase 12), a heuristic, or a manual override. Connects to the field-guide work; sibling to the
  per-item range-scaling note above (both are "not all counts scale the same way").

- **Bare "oz" on liquids (import).** Scraped recipes often write fluid ounces as bare "oz". On a
  known-liquid ingredient the importer should normalize "oz" → "fl oz" (or flag for review),
  so a liquid isn't later converted as weight (28.35 g/oz). Decline over guess — normalize
  only when the ingredient is confidently a liquid, else flag. (See the Matching principle
  and the Ingredient-line data model note.)

- **Orphaned ingredient asterisks (import).** Web recipes (e.g. King Arthur) often footnote
  ingredients — `half-and-half*`, `cocoa, Dutch-process or natural*` — where the footnote text lives
  on the website but is **not captured by Paprika**, so the ingredient name imports with a trailing
  `*` pointing to a note that exists nowhere (not in Paprika's `notes`/`directions`, and not
  recoverable). Only King Arthur has this (2 ingredients) in the current 20, but it will recur at
  295 scale. **Handling:** STRIP a trailing orphaned `*` from an ingredient name when the recipe has
  **no note/footnote it could reference** (the marker promises a footnote that doesn't exist → just
  noise). The footnote text is unrecoverable (absent from the source), so there's nothing to link it
  to. Consistent with decline-over-guess: strip only when there's demonstrably no note to point to.
  (King Arthur's 2 asterisks are left as-is for now — cosmetic, one recipe, not worth a one-off fix.)

- **Source-formatting artifacts on pre-formatted steps (import).** Some imported recipes (e.g. the
  potato paratha) carry the source's **own** step numbering verbatim in the step text
  (`1. MAKE THE DOUGH:`), sometimes ALL-CAPS — and the app **also** renders its own circled step
  number, so the number doubles (① + "1."). Frame broadly as *source-formatting artifacts*: the
  leading "N." is the visible one, but such recipes often have siblings (all-caps headers, trailing
  colons) worth one cleanup pass together. **When tackled:** FIRST a read-only check of what's
  actually **stored** (is the "1." in the step text? is the all-caps stored, or a CSS
  `text-transform`?), then choose **data-cleanup-at-import** (cleaner long-term — the importer strips
  it so future imports are clean, plus a one-time pass over the ~295 existing) vs **strip-at-render**
  (non-destructive). Safe strip: a leading integer + `.`/`)` + whitespace at the very start of a step
  — almost always leftover ordinal numbering. Same category as the orphaned-asterisk cleanup above.

- **Preferred-units-on-import (future, nice-to-have).** When importing a recipe
  (Phase 15/16), convert quantities into the user's preferred unit system, defaultable by
  category (e.g. baking → grams, savory → imperial). Baking volume→weight conversion
  (cups → g) needs the 1c per-ingredient density table; rounding must be to the nearest
  1, not 5, to preserve hydration-percentage accuracy for bread. *Depends on: 1c (density
  data), Phase 15/16 (import), and a per-user/per-category settings store (which a global
  units preference, the Phase 5d weather fields, and the Phase 19 saved-mood preference would
  all use — build that store once for all).*

- **Step-text Metric conversion (future, gated).** Step / method-text amounts SCALE but do not
  Metric-convert: the ingredient list smart-converts volume→grams (Phase 1c), but step amounts
  render through the scale-only path (`stepscale.api_spans` → the 1a `scaleQty`), never
  `toMetric` — so "stir in 2 cups stock" stays "2 cups" (scaled) in Metric view while the same
  ingredient shows grams. Deliberate for now (a step gram value with no per-line density match
  would read inconsistently, and the >2 tbsp gram threshold is an ingredient-list rule). Future,
  gated: route step scalable-spans through the same Smart-Metric path as ingredients (reusing the
  server-attached density), behind the same baking/dessert tag gate as the ingredient converter
  (Phase 8). *Documented in docs/import-reference-15.md, Known limitations (ii).*

- **Oils convert in baking-tagged recipes (future, gated on tags).** `convert_to_grams=FALSE`
  (migration 013) keeps pure cooking oils & raw produce in their authored VOLUME under Metric —
  right for everyday cooking (you pour a glug of oil or scoop a cup of diced onion, you don't
  weigh it). But baking weighs oil by the gram. Future, gated: when a recipe is tagged
  baking/dessert (Phase 8), let the `convert_to_grams=FALSE` *oils* (olive/vegetable/coconut oil,
  lard, shortening) convert to grams anyway — the same recipe-tag gate as the "baking defaults to
  grams" Smart-Metric note (Phase 1). Raw produce/aromatics stay volume regardless of tag.
  *Depends on: Phase 8 tags.*

*Tech debt:*

- **Harvested-gram display (deferred).** Parenthetical grams are HARVESTED and STORED in
  `recipe_ingredients.grams` (migration 011) — and the harvested `(NNN g)` is stripped from the
  name — but the value is NOT yet displayed / scaled / preferred; the app still shows the
  density-matched weight (1c). Future: use the harvested gram as the authoritative display +
  scaling weight — better than density conversion, and it sidesteps source volume typos (e.g. the
  "14 cups (250g)" chickpeas line, where the cup measure is wrong but the harvested 250 g is
  correct). Pairs with the linkage pass. Feeds 1c.

- **Extract a shared public `amounts.py`.** The fraction/amount parser now exists
  three times — `stepscale._to_value`, `weights._to_number`, and the JS `tokenToNumber` — and
  `import_cleanup` imports `stepscale`'s underscore-private `_NUM` / `_to_value` / `_SCALE_UNIT`
  / `_normalize_unicode`. Consolidate into one public module later; deferred now because it
  would touch tested Phase-1 code mid-import-build.

- **Sonar coverage gap.** `sonar.sources` in `sonar-project.properties` is a hand-listed set
  (`app.py, build_db.py, migrate.py, seed.py, backup.py, static`) — it omits `weights.py`,
  `stepscale.py`, the `import_*` modules, and the `paprika_*`/`study` scripts, so those are NOT
  scanned by SonarQube in CI (only local SonarLint sees them). Add them to `sonar.sources` (or
  point it at a directory) to close the gap.

- **The SonarQube quality gate is NOT enforced — deliberate.** CI runs the scan and never checks its
  verdict, so a red gate cannot fail a build. The gate uses Sonar's *default* thresholds rather than
  ones chosen for this project, and one of its conditions is structurally unreachable: `new_coverage`
  demands 80% while `static/app.js` — a browser entry point the zero-dep node suite never loads — is
  1,739 of the project's 3,534 coverable lines (49%) sitting at 0.0%, and accounts for 1,739 of its
  1,829 uncovered lines (95%). Until that file has a DOM harness, perfect coverage everywhere else
  still caps line coverage near 51%. The gate has read ERROR since 2026-07-06 on three conditions:
  `new_security_rating` (4/D), `new_reliability_rating` (3/C), and `new_coverage` (51.8 vs 80).

  The five open issues driving the two rating conditions are **understood, not unexamined**:
  - `python:S4502` (CRITICAL, `app.py:49`) fires on the `Flask()` constructor for *any* app without a
    CSRF extension — it is not a finding about our routes. No GET route writes, so there is no exposure.
  - `python:S2068` (MAJOR, `app.py:79`) is the dev-only `SECRET_KEY` fallback, fenced by a
    `RuntimeError` that fires the moment `DATABASE_URL` points at Postgres.
  - The two accessibility findings are simply wrong about this code: `static/index.html:69` is told to
    add a keyboard handler it already has (`static/app.js:2982` — Enter/Space on the `role="button"`
    zone), and `:74` is the file input that zone drives, deliberately `aria-hidden` + `tabindex="-1"`.
  - `javascript:S6544` (MAJOR, `static/app.js:1604`) flags `document.fonts && document.fonts.ready`;
    `.ready` is always a truthy Promise, so the guard is redundant but correct.

  The scan still earns its place **for what it measures rather than for its verdict** — it caught the
  imported HTML-fixture noise (356 issues raised against other people's inline analytics scripts), and
  its coverage figure is now honest at 51.8% instead of falsely 32.6%.

  To *enforce* it later, all three of these have to happen: disposition all five issues in SonarCloud
  (a rating takes the **worst** open issue, so clearing them partially lands at C rather than A —
  clearing only S4502 still leaves S2068 holding security at C); move the new-code baseline off
  2026-06-24, which is what the coverage condition actually turns on; and add a gate-check step to
  `.github/workflows/build.yml`. Dispositions alone leave the gate red.

- **The import parser's equivalence baseline — `67eeda9e…` (was `bacd5f45…`).** The 298-recipe
  Paprika archive run through `reader.normalize` → `clean_recipe` → `plan_recipe`, with
  `plan_recipe(now=…)` pinned for determinism, hashes to
  `67eeda9e22ed7f2a43a761907ac8569dd861ac7b34486a2debe0ea8c9e3e34d4`. **Any change to the parser must
  be diffed against this**: the corpus is 298 recipes the user curated over years, the Paprika path is
  no longer exercised by anything else, and a regression there is silent — nothing fails, the text just
  quietly gets worse. Re-run it before and after; an identical hash is the proof that a URL-import fix
  did not reach the archive. Recorded because there was no stored value before `d2ae519` and several
  briefs referenced a baseline (`e2e4a6c2…`) that exists nowhere in this repository.
  - **Superseded value, kept so the number's history is legible:**
    `bacd5f45e909564f35aa167683b380b56f5179f68198edb81a7f97cdd041f860` — the FIRST one stored, valid
    from `d2ae519` until `7b7cd34`.
  - **Why it moved.** `7b7cd34` (harvest the gram from a restatement parenthetical, "16 Tbsp; 226g")
    populates `grams` on lines that previously declined, and `grams` is one of the fields inside the
    hashed plan — so the digest MUST move. An unchanged hash there would have meant the fix did
    nothing. A moved hash is not by itself evidence of a regression.
  - **The hash alone was not the gate, and cannot be.** It says only "something moved" — not what, not
    where, not whether the change was the intended one. The gate that actually ran for `7b7cd34` was a
    **plan-level diff, HEAD parser vs tree parser**, over every archive ingredient row: 24 of 3,533
    rows changed, across 18 recipes, all `grams: None → value`, with no recipe-field and no step
    changes. Pair the hash with that diff whenever the number is expected to move; treat the hash as a
    tripwire, not a verdict.

- **`" ," → ","` is deliberately NOT a cleanup rule.** It looks like a sibling of the two rules that
  did ship in `d2ae519`, and by itself the shape is unambiguous. It stays out because it matches **73
  stored Paprika rows** (`5 garlic cloves , peeled`, `1 small onion , roughly sliced`), so applying it
  would change recipes already imported and move the hash above. That makes it a decision about the
  user's existing data rather than a parser fix — which is the same bar the module's own comment sets:
  a rule must be corpus-neutral, or it is a migration wearing a regex costume.

- **10 orphaned parenthetical continuations in the stored corpus (open finding, Paprika path).** Ten
  ingredient rows across nine recipes are a bare parenthetical with no ingredient — `(thinly sliced)`
  sitting as its own row directly beneath `chicken breast`, `(450g, medium thickness)` beneath
  `fresh or dried white noodles`. `raw_text` equals the label, so the SOURCE LINE was already just the
  parenthetical: this is line-splitting in the Paprika import, not the amount parser, and it predates
  the URL importer entirely. Not fixed, and deliberately not guessed at — recovering them means
  deciding whether a continuation row merges upward into the line above, which is an edit to existing
  user data. ⚠️ **Do not confuse this with the 366 rows whose `label` is NULL**: those carry a perfectly
  good `raw_text` (`extra virgin olive oil`) and render correctly, since the editor reads
  `label || raw_text`. An earlier report of this session conflated the two and called it "376 rows";
  `d2ae519`'s commit body names that error and its cause. The real count is **10**.

- **R2 handwritten layer — extend the per-person model to app-tier (architectural).** The
  per-person change model (edit/remove lines, additions) currently exists ONLY for seed recipes
  (gated on `is_seed`); the imported recipes are app-tier and have the **form-edit** path but NOT
  the per-person annotation layer. The Round-2 handwritten edit/note layer (see
  docs/design-decisions.md) needs that model extended to app-tier recipes (or the two unified), and
  the coexistence of "edit the canonical recipe" vs. "annotate by hand" decided. Architect-only in
  R1 (reserved tokens / gutter / strike-able cell); resolve before building R2.

- **Edit-form authoring polish (deferred).** The create/edit form (`#/new`, `#/edit`) is a separate
  full-page view, OUT of the Round-1 design scope. It inherits the new tokens (so it stays
  coherent) but isn't purpose-designed — a later small authoring-polish pass (or fold into R2).

- **Re-harvest-on-save (future capability — distinct from the grams-preservation fix).** If a user
  types a weight parenthetical (e.g. "(300 g)") into the edit form, run the edited line through
  `import_cleanup.classify_line` on save to harvest it. This is a NEW capability — *not* the
  grams-wipe fix, which already landed (`0c3f6ae`: it preserves EXISTING harvested grams across an
  edit but can't recover a paren the import already stripped from the editable text).

- **Punctuation conversion across the docs (deferred, do it once).** The CLAUDE.md voice rules ban em
  dashes, semicolons and rhetorical mid-sentence colons in every string a person reads, and new prose
  is already written that way. `ROADMAP.md`, `docs/product-vision.md`, `CODE_WALKTHROUGH.md`,
  `OVERVIEW.md` and `docs/design-decisions.md` still use all three heavily, so the documents currently
  read in two registers. Convert them in one deliberate pass **after the CLAUDE.md voice section is
  settled**, not opportunistically, because a half-converted document is worse than an unconverted one.
  Lines edited for other reasons get converted as they are touched, which is how the achievements
  rewrite handled it.

## Adjacent product ideas (separate apps — NOT Chef's Choice features)

Ideas for **separate applications** — explicitly *not* Chef's Choice features — that **could reuse the
infrastructure Chef's Choice is building** (the recipe / ingredient model, the Flask / SQLAlchemy / Postgres
stack, the import pipeline, the user / ownership structure). Recorded here so they're durable, **with their
feasibility findings stated honestly** — each has open questions that reshape or gate it.

### A. Kids nutrition education (separate app)

A fun / interactive tool for **parents + kids to learn about food** — e.g. non-shaming food-**FREQUENCY**
bucketing (**Always / Sometimes / Almost Never**, like the reference screenshot). Aligns with Kenji
López-Alt's kids-book philosophy (*"Every Night is Pizza Night"*).

**Feasibility / open questions (research pass):**
- **Could NOT confirm a specific Kenji *app / tool*** to model on — found his kids' **book** + Patreon /
  YouTube, **not** a bucketing app. Need the **specific source that inspired this** + the real gap.
- The space already has education-focused entries (**This Is My Food**, **Eat and Move-O-Matic**,
  **Nutrition.gov** games).
- **Least fraught of the three** (simple data: food→bucket; no medical / financial risk) and **most
  buildable** — but needs a **sharper target** (what specifically, and what's the actual gap).

### B. IBS / FODMAP food journal (separate app)

Track **foods + symptoms**, correlate triggers, and filter recipes to a restricted (**low-FODMAP**) diet.

**Feasibility / open questions (research pass — these RESHAPE the idea; recorded honestly):**
- **(i) The CORE DATA is the wall.** FODMAP content **cannot be derived from ingredient lists** — foods must
  be **LAB-TESTED** (Monash built a certification lab for this). So the data is **empirical clinical IP**,
  not derivable or hand-rollable. Monash's is the world's largest DB, cited in **ACG clinical guidelines**. A
  real product needs **LICENSED tested data** or another validated source — you can't copy Monash or wing it,
  and getting FODMAP data **wrong has health consequences.**
- **(ii)** Monash's app is **~$8–10 (one-time), NOT $80** — the *"$80, heard it's trash"* premise appears to
  be a **different product**; re-check what was actually seen.
- **(iii) The space is CROWDED** (IBS Coach, Nerva, FODMAP A–Z already exist).
- **(iv) The genuine opportunity** is a **PRODUCT / UX gap** (Monash's app draws maintenance / UX complaints —
  Android not updated since Oct 2025) — **but a better UX doesn't solve the data-IP wall.**
- **Verdict:** **HIGH value, HIGH responsibility, BLOCKED on the data source.**

## Prior art / why our model differs

**Cooklang** (cooklang.org) was considered — a clean plain-text recipe markup format with an
ownership pitch and a tooling ecosystem — but we chose a **relational model (SQLite)** because the
goal is queryable, outcome-rich structured data for the grounding/recommendation vision, which a
folder-of-text-files model doesn't serve well. Its explicit scale/no-scale ingredient syntax
(`@salt{}` vs `@flour{2%cups}`) is, however, a useful reference for our step-text scaling if we
ever add user-authored scaling hints (cf. the 1d markup).

## Declined

- Step timers.
- Nutrition estimate.
