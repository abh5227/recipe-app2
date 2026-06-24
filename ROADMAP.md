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

---

## Cost summary

Everything is free except two items.

| Cost | Features |
|------|----------|
| Free | Test suite, quantity & units, cooking mode + checkoff, dark mode, photo upload, per-cook journal, data health check, trash / soft-delete, recipe metadata — favorites/tags/dietary/cuisine, planning attributes — equipment/difficulty/time/make-ahead/calibration, search & discovery incl. in-season/pairings/reverse-lookup, sub-recipes, ingredient enrichment, pantry + shopping list + meal planner, output — print + export/import, free JSON-LD import, local cooking-activity view (precursor), adding recipes |
| Per-use API cost (cents per call; needs a key) | AI recipe scan/auto-populate; optional: AI-assisted citations, AI-ranked substitutes |
| Ongoing hosting cost + major architecture change | Friend cooking feed, networked version |

---

## Phase 0 — Test suite (foundational + ongoing) · Free

Stand up a persisted `pytest` suite in the repo covering current behavior — the API
endpoints, `migrate`/`build_db`, per-person changes, and rebuild-preservation — replacing
the throwaway tests used so far.

- **Cross-cutting:** every later phase adds tests for its change.
- **Schema:** none. **Why first:** highest-leverage safety net as features stack; cheap now,
  expensive to retrofit later.

## Phase 1 — Quantity & units · Free

Shared machinery: a parser that reads a quantity string into a number + unit.

- **1a — Scaler.** Scale quantities (×0.5, ×2, "serves N"). *(done — ingredient quantities only)*
- **1b — Metric/imperial toggle.** Fixed-factor conversions: volume↔volume, weight↔weight.
- **1c — Volume↔weight (King Arthur table).** Ingredient-specific ("1 cup flour" → "120 g");
  adds a per-ingredient weight field (g per cup/tbsp) from the King Arthur Baking table.
- **1d — Scale quantities in the method text · priority.** When you scale a recipe, amounts
  written into the steps ("add 2 tbsp oil", "stir in 1 cup stock") must scale too, not just
  the ingredient list. The hazard is that step prose mixes scalable amounts with numbers that
  must *not* move — oven temperatures ("350°F"), times ("for 20 minutes"), pan sizes ("9×13"),
  and counts ("cut into 4"). A blind "scale every number" would wreck those. Two candidate
  approaches: (a) **reliable — explicit markup**: mark scalable amounts in the step source the
  way ingredients are already tagged with `[[...]]`, so only marked amounts scale (needs a one-
  time pass over each recipe's steps; no false hits); (b) **convenient — heuristic**: scale only
  `<number> <measuring-unit>` patterns (tbsp/tsp/cup/g/ml/oz/lb/clove…) and explicitly skip
  anything followed by a temperature, time, or dimension marker (still fragile at the edges).
  Likely ship (a) as the dependable default and layer (b) on as an assist. Reuses the 1a parser.
  *Schema:* none (markup lives in the existing step text).
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

## Phase 6 — Data health check · Free

Extend `build_db.py`'s report to flag: unused ingredients, recipes missing a photo, and
plain-text ingredient lines that *could* be linked to the library.

- **Why here:** low-risk maintenance tool. The "could be linked" check directly supports the
  linking prerequisite for pantry (Phase 13) and in-season (Phase 10). Useful before bulk
  recipe entry.

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
- **Capstone view — "what can I cook tonight":** emerges from pantry (13b) + in-season (10c) +
  time (9b) + make-ahead (9d). Not new data, just a combined view.
- **Cross-cutting:** match %, substitutes, in-season, and shopping-list subtraction work only
  on recipe lines **linked** to the library; recurse into sub-recipes (Phase 11).

## Phase 14 — Output & portability · Free

- **14a — Print / PDF export.** Clean printable recipe (print stylesheet or server-side PDF).
- **14b — Export / import recipes.** Back up to / restore from JSON (recipes, changes,
  additions, ratings, cook history). *Placed late on purpose:* earlier phases keep adding
  tables, which would otherwise force repeated rewrites of the export format.

## Phase 15 — Free recipe import (JSON-LD) · Free

Import a recipe by parsing the schema.org Recipe data (JSON-LD) embedded in most recipe-site
pages — ingredients, steps, times, yield — into the form for review.

- **Scope:** fetch a URL, parse JSON-LD, prefill the form; then map ingredients to the
  library. *Schema:* none (writes through the form).
- **Why here:** the free sibling of the AI scan — it handles the common case (sites with
  structured data) with no API cost; AI scan (Phase 16) covers photos and sites without it.
  Can be pulled forward; the main caveat is the ingredient-mapping step.

## Phase 16 — AI recipe scan / auto-populate · Per-use API cost

Read a recipe from a photo or pasted/messy text and auto-fill the form for review.

- **Depends on:** Phase 4 (photos); quality improves with Phase 8/12 metadata. Complements
  Phase 15 (use free JSON-LD when available, AI for the rest).
- **Cost:** per-use API (~cents per recipe), needs a key. Always confirm the parsed result —
  models misread quantities and names.
- **Payoff:** turns "upload more recipes" from typing into review-and-edit.

## Phase 17 — Friend cooking feed / "what's for dinner" · Hosting cost + major change

- **Free local precursor (can be earlier):** attribute `cook_log` to a person and show an
  in-app activity view; one instance only, no cross-device sharing. (Phase 5 already moves
  `cook_log` this way.)
- **Full networked version:** multi-user accounts, a hosted database, a deployed server.
  Largest architectural change here and the only feature with an ongoing monthly cost.
- **Why last:** a different class of project (deployment + multi-user) than the rest, which is
  local and single-user.

---

## Continuous — Upload more recipes & data · Free

Ongoing. Add recipes via `seed.py`, the in-app form, or import (Phases 15/16). Link
ingredients to the library so Phases 10c/13 work on them.

---

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

## Cosmetic / nice-to-have polish

Small display niceties. Low priority, no rush — none of these change behavior, only how a
value reads.

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
