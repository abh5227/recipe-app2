# Seasonal Kitchen — Roadmap / Feature Tracker

A running list of features to implement eventually, ordered into phases. This is a
planning document, not a commitment — reorder, add, or drop items as priorities change.

**Working principle:** slow and gradual. One phase (or sub-step) at a time, each an
independently shippable change we review before moving on. Larger features are split into
sub-steps for the same reason.

**Order rationale:** a test-suite foundation first, then cheap isolated wins and
maintenance, then the recipe metadata that filtering/discovery depend on, then sub-recipes,
then ingredient enrichment, then the large pantry + planning cluster, then output, the two
import methods (free, then paid), and the networked friend feed last. Phase numbers are a
suggested order, not a lock — anything cheap and self-contained can be pulled forward.

**Matching principle — decline over guess, but measure coverage.** Whenever the app
matches free-text recipe ingredients to structured data (weight table, pantry, library
links, imported recipes), a wrong match is worse than no match: it produces confidently
incorrect output (a false-precision gram value, a mis-linked ingredient). Rule: exact
match first, conservative normalized fallback, curated aliases for known equalities, and on
anything less than a confident match, pass through unchanged — never guess. AND measure how
often we decline (coverage reporting) so we know how big the gap is. Applies to Phases 1c,
13, 15, 16.

**Ingredient-line data model (cross-cutting).** Current ingredient text carries three kinds
of noise — combined ingredients ("beef mince ground beef"), embedded instructions/qualifiers
("very warm tap water up to 130 f"), and "X or Y" alternatives ("naan or arabic taboon
bread"). This degrades every feature that treats ingredients as structured: conversion,
pantry matching, library linkage, in-season, dietary flags, search. *Detection* belongs in
Phase 6 (the health scan); *structural* cleanup — cleanly separating quantity · unit ·
ingredient · prep-note, and handling alternatives — is a bulk-import-era task tied to the
ingredient model and the importer, best done at/around import (Phase 15/16) so scraped
recipes are cleaned on the way in rather than after. Not worth hand-cleaning the current 5
recipes; tolerable at this scale, matters at bulk upload. *See Phases 12, 13, 15, 16.*

**Amount-structure cleanup (extends the above).** Amount text also carries forms the numeric
parser can't handle — word-numbers ("half", "a few", "a couple"), parenthetical amounts
("(about half a lime)"), and open-ended amounts ("plus more if needed", "to taste") — each
needing separation from the scalable quantity, handled at import/data-model time (not a
standalone word-number feature). Worked example that fails to scale today: the lime-juice line
"lime juice (about half a lime), plus more if needed". Ties to the import / ingredient-name
cleanup notes.

**Data-capture principle — capture signal early, build consumers later.** Log cooks, ratings,
and edits with TIMESTAMPS and STRUCTURED OUTCOMES from the start: the signal you don't capture
is unrecoverable, but features that consume it can be built anytime. Raises the bar for how
Phases 5 (journal), 18 (analytics), and 19 (recommender) store data. Edit/version history is
cheap to start timestamping now (tie to the per-person change layer).

**Provenance principle — cite reference data in the data model.** All gathered REFERENCE data
(ingredient weights, densities, variances, seasonality…) carries its SOURCE(S) as a column, so
"blended from multiple reliable sources, cited" is traceable and conflicts (e.g. King Arthur
120 g/cup vs ATK 140) are reconcilable. Apply to the existing `ingredient_weights` table and
every future reference table.

**North-Star — a queryable structured recipe dataset (NOT ML training).** The goal is every
recipe decomposed into clean, queryable fields (ingredients, amounts, units, cuisine, tags,
technique) so the whole corpus is queryable — via QUERIES over clean data, not learned models.
The existing normalized schema IS this dataset; the work is ENRICHING it (ingredient-library
linkage + metadata), NOT a separate denormalized all-in-one table (which would duplicate data
and create sync problems). Through-line: Phase 6 (linkage, foundational) → Phase 8
(cuisine/tags) → bulk import (15/16). Volume comes from both published recipes (15/16) and
friends' shared recipes (17). *Agenda + analysis: see "Data gathering & cross-recipe analysis"
near the end.*

---

## Cost summary

Everything is free except two items.

| Cost | Features |
|------|----------|
| Free | Test suite, quantity & units, cooking mode + checkoff, dark mode, photo upload, per-cook journal, data health check, trash / soft-delete, recipe metadata — favorites/tags/dietary/cuisine, planning attributes — equipment/difficulty/time/make-ahead/calibration, search & discovery incl. in-season/pairings/reverse-lookup, sub-recipes, ingredient enrichment, pantry + shopping list + meal planner, output — print + export/import, free JSON-LD import, local cooking-activity view (precursor), adding recipes |
| Per-use API cost (cents per call; needs a key) | AI recipe scan/auto-populate; optional: AI-assisted citations, AI-ranked substitutes |
| Ongoing hosting cost + major architecture change | Friend cooking feed, networked version |

---

## Progress

| Status | Phase | Notes |
|--------|-------|-------|
| ✓ done | Phase 0 — Test suite | 22 tests covering API, build/migrate, and per-person change layers |
| ✓ done | Phase 1a — Scaler | Ingredient list only |
| ✓ done | Phase 1b — Metric/imperial toggle | Ingredient list only; same scope as 1a |
| ✓ done | Phase 1c — Volume↔weight | King Arthur chart; server-side matcher + coverage report |
| ✓ done | Phase 1d — Step-text scaling | Safe-hybrid: markup > guard > heuristic |
| not started | Phases 2–19 | See below |

---

## Phase 0 — Test suite (foundational + ongoing) · Free · ✓ done

Stand up a persisted `pytest` suite in the repo covering current behavior — the API
endpoints, `migrate`/`build_db`, per-person changes, and rebuild-preservation — replacing
the throwaway tests used so far.

- **Cross-cutting:** every later phase adds tests for its change.
- **Schema:** none. **Why first:** highest-leverage safety net as features stack; cheap now,
  expensive to retrofit later.

## Phase 1 — Quantity & units · Free · 1a–1d done · COMPLETE

Shared machinery: a parser that reads a quantity string into a number + unit.

- **1a — Scaler.** Scale quantities (×0.5, ×2, "serves N"). *(done — ingredient quantities only)*
- **1b — Metric/imperial toggle.** Fixed-factor conversions: volume↔volume, weight↔weight. *(done)*
- **1c — Volume↔weight (King Arthur table).** *(done)* Ingredient-specific ("1 cup flour" → "120 g");
  adds a per-ingredient weight field (g per cup/tbsp) from the King Arthur Baking table.
  *See also: preferred-units-on-import (Phase 15, future nice-to-have) — the density
  table built here is a dependency for baking volume→weight conversion at import time.*
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
  `node --test tests/js` (covers `scaleQty`/`formatAmount`, the count + compound logic, and the
  smart-Metric threshold). A `factor-sync` test reads both `scaler.js` and `weights.py` and
  asserts the JS↔Python conversion factors agree. CI runs both the Python and JS suites on
  every push. *(Zero dependencies — no bundler/framework.)*
- **Notes:** parse whole numbers, fractions, ranges; leave "to taste" alone. Convert only
  what's possible. Compose with per-person edits. "Serves N" needs a numeric base yield —
  servings is currently free text, so a small structured-yield field is a dependency. 1c is
  a citable source (ties to Phase 12). *Schema:* per-ingredient weight field (1c); numeric
  yield field.
- **Later:** sub-recipe components should scale with the parent (see Phase 11).

## Phase 2 — Cooking mode · Free

- **2a — Full-screen step-by-step** with the screen kept awake (Screen Wake Lock API).
- **2b — Check off ingredients & steps** (mise en place) while cooking.
- **Schema:** none. **Depends on:** nothing. Isolated, high daily value.

## Phase 3 — Dark mode / theme toggle · Free

App-wide light/dark toggle. Frontend only, no schema. Cheap; pull forward freely.

## Phase 4 — Photo upload · Free

Upload a recipe photo in-app instead of dropping a file in `static/images`.

- **Scope:** Flask multipart endpoint, save locally, store the path. *Schema:* none.
- **Depends on:** nothing. Prerequisite for per-cook photos (Phase 5) and AI scan (Phase 16).
- **Notes:** validate type/size, safe filenames.

## Phase 5 — Per-cook journal · Free

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

## Phase 6 — Data health check · Free

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

## Phase 7 — Trash / soft-delete · Free

Replace permanent deletion with soft-delete: mark a recipe deleted, exclude it from lists,
and provide a Trash view to restore or permanently remove it. Plus undo for the last
destructive action.

- *Schema:* a `deleted_at`/`is_deleted` flag on recipes; the delete endpoint flags instead of
  removing, and list/detail queries exclude deleted rows.
- **Why here:** today deletion is permanent and cascades to a recipe's ratings, history, and
  changes — this prevents accidental loss as more data accrues.

## Phase 8 — Recipe metadata & organization · Free

Small recipe-metadata features that later filtering/discovery depend on.

- **8a — Want-to-try / favorites.** Status flag + filter. Tiny.
- **8b — Tags / collections.** Freeform labels; tags + recipe-tags join (mirrors the regions
  pattern).
- **8c — Dietary flags.** Vegetarian/vegan/GF/allergens, set manually for now; later derived
  from ingredient tags (after Phase 12).
- **8d — Cuisine / region taxonomy + region search.** Hierarchy (Indian → Kolkata,
  Delhi); search/filter by it. Foundational — also feeds origin-based substitutes (Phase 13)
  and AI scan (Phase 16). *Schema:* recipe cuisine/region structure.

## Phase 9 — Planning attributes (equipment, difficulty, time, make-ahead) · Free

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

## Phase 10 — Search, sort & discovery · Free

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

## Phase 11 — Sub-recipes / components · Free

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

## Phase 12 — Ingredient enrichment: citations + flavor/category tags · Free (manual)

- **Citations.** One or more sources per ingredient, shown on the field guide.
- **Flavor/category tags.** Category (allium, chili, herb…), flavor notes, spice grouping —
  distinct from `pairs` ("goes with", not "stands in for").
- *Schema:* citations + tag fields/tables on ingredients.
- **Cost:** schema + manual entry free; AI-assisted gathering is an optional paid upgrade.
- **Why here:** substitutes (Phase 13c), the dietary-derivation upgrade (Phase 8c), and
  richer pairings (Phase 10e) all need these attributes.
- *Depends on clean ingredient identity — see the Ingredient-line data model note (top).*

## Phase 13 — Pantry & planning · Free (rule-based)

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

## Phase 14 — Output & portability · Free

- **14a — Print / PDF export.** Clean printable recipe (print stylesheet or server-side PDF).
- **14b — Export / import recipes.** Back up to / restore from JSON (recipes, changes,
  additions, ratings, cook history). *Placed late on purpose:* earlier phases keep adding
  tables, which would otherwise force repeated rewrites of the export format.

## Phase 15 — Recipe import (multi-source) · Free

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
- **WRITE layer:** recipes → app-tier (uid-dedup); ingredients → seed-tier shared library;
  images → storage. Field-guide AI baseline + linkage run as separate passes (see below).
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

- *Bare "oz" on liquids:* scraped recipes often write fluid ounces as bare "oz". On a
  known-liquid ingredient the importer should normalize "oz" → "fl oz" (or flag for review),
  so a liquid isn't later converted as weight (28.35 g/oz). Decline over guess — normalize
  only when the ingredient is confidently a liquid, else flag. (See the Matching principle
  and the Ingredient-line data model note, top.)

- **Preferred-units-on-import (future, nice-to-have).** When importing a recipe
  (Phase 15/16), convert quantities into the user's preferred unit system, defaultable by
  category (e.g. baking → grams, savory → imperial). Baking volume→weight conversion
  (cups → g) needs the 1c per-ingredient density table; rounding must be to the nearest
  1, not 5, to preserve hydration-percentage accuracy for bread. *Depends on: 1c (density
  data), Phase 15/16 (import), and a per-user/per-category settings store (which a global
  units preference, the Phase 5d weather fields, and the Phase 19 saved-mood preference would
  all use — build that store once for all).*

## Phase 16 — AI recipe scan / auto-populate · Per-use API cost

Read a recipe from a photo or pasted/messy text and auto-fill the form for review.

- **Depends on:** Phase 4 (photos); quality improves with Phase 8/12 metadata. Complements
  Phase 15 (use free JSON-LD when available, AI for the rest).
- **Cost:** per-use API (~cents per recipe), needs a key. Always confirm the parsed result —
  models misread quantities and names.
- **Payoff:** turns "upload more recipes" from typing into review-and-edit.
- *Also the place to apply structural ingredient-line cleanup — see the Ingredient-line data
  model note (top).*

## Phase 17 — Friend cooking feed / "what's for dinner" · Hosting cost + major change

- **Free local precursor (can be earlier):** attribute `cook_log` to a person and show an
  in-app activity view; one instance only, no cross-device sharing. (Phase 5 already moves
  `cook_log` this way.)
- **Full networked version:** multi-user accounts, a hosted database, a deployed server.
  Largest architectural change here and the only feature with an ongoing monthly cost.
- **Why last:** a different class of project (deployment + multi-user) than the rest, which is
  local and single-user.

## Phase 18 — Cooking analytics dashboard · Free

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

## Phase 19 — "What's for dinner" recommender · Free

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

---

## Continuous — Upload more recipes & data · Free

Ongoing. Add recipes via `seed.py`, the in-app form, or import (Phases 15/16). Link
ingredients to the library so Phases 10c/13 work on them.

---

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

## Known limitations / sharp edges

Things that are actually *wrong* in edge cases (not just cosmetic), worth knowing before they
bite. None occur in the current recipes.

- **Scaler — numbers that aren't quantities.** The scaler multiplies every number in a
  quantity string, so any number that isn't an amount-to-scale gets scaled wrongly:
  - *Parenthetical pack sizes:* `1 (14 oz) can` ×2 → `2 (28 oz) can`, when you want
    `2 (14 oz) cans` — the can size shouldn't move.
  - *Comma-grouped numbers:* `1,000 mL` is read as `1` and `000` separately and mangled.
  General fix: the 1d markup approach (mark which number scales). Safe today because no recipe
  uses these forms; add it here if a new recipe ever does.

- **`migrate.py` is not per-migration atomic.** `executescript()` runs statements in autocommit
  mode, so a migration that fails midway leaves a partial schema with no `schema_migrations`
  record. Only affects *future* migrations (the existing 7 are applied and fine). Fix if it
  ever bites: wrap each migration file's statements in an explicit `BEGIN;` / `COMMIT;` block.

- **Tests are coupled to exact seed counts.** Adding recipes or ingredients to `seed.py` will
  make `test_list_recipes` (`== 5`), `test_ingredients_and_in_season` (`== 36`), and
  `test_seed_counts` go red until those three numbers are updated. Expected, not a bug — just
  update the counts when adding seed data.

- **Test harness mutates module globals without teardown.** `tests/harness.py` sets
  `migrate.DB` / `build_db.DB` / `app.DB` on shared module objects with no restore. Fine for
  sequential pytest; would break under parallel runs (pytest-xdist). Only relevant if
  parallelism is ever added.

## Declined

- Step timers.
- Nutrition estimate.
