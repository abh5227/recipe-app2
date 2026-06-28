# Chef's Choice — Code Walkthrough & History

This is the **detailed companion** to the README. The README is the quick start; this
document is the living history — a guided tour of the code, the reasoning behind the
choices, and the tradeoffs worth remembering. **Update it as the app grows** (there's a
dated change log at the bottom for exactly that).

If you're returning after time away, read the "Big picture" section, then skim the
reading order, then jump to whatever you're about to change.

---

## Big picture

The app is three layers with a clean seam between each:

```
seed.py ──build_db.py──▶ recipes.db ──app.py──▶ JSON ──app.js──▶ HTML in the browser
 (your        (loads        (SQLite      (Flask      (over       (renders, no
  content)     content)      file)        backend)    HTTP)        content of its own)
```

- **`seed.py`** is the only file you edit for content: recipes, the ingredient library,
  and the people who can have a version of a recipe.
- **`migrations/`** defines the database *structure* as a numbered history. `migrate.py`
  applies them; `build_db.py` then loads `seed.py` into the tables.
- **`app.py`** is a small Flask backend: it serves the page and answers a JSON API by
  running SQL. It holds no recipe content.
- **`static/app.js`** runs in the browser, fetches JSON, and builds the HTML. It holds no
  recipe content either — it only knows how to render whatever the API returns.

The single most important design idea: **content vs. your data.** Content (recipes,
ingredients, people) comes from `seed.py` and is refreshed on every build. *Your data*
(ratings, cook history, and per-person changes) is created in the app and is **never**
wiped by a rebuild. That split is why migrations exist and why `build_db.py` is careful
about what it touches.

---

## Reading order

Read the files in this order; each builds on the last.

### 1. `seed.py` — the content
Start here because everything downstream is shaped by it.

- **`PEOPLE`** (near the top): the list of people who can keep a version of a recipe, each
  with an `id`, `name`, and a display `color`. *Interesting because* this is the one place
  you manage people — there's deliberately no in-app people management. Keep the `id`s
  stable: saved changes are keyed by them.
- **`INGREDIENTS`**: a dict keyed by short slugs (`garlic`, `sumac`, …). Each entry has a
  description, `season` (month numbers), `regions`, and `pairs`. The slug is the contract:
  recipes reference ingredients by it.
- **`RECIPES`**: a list of recipe dicts. Two line shapes matter: a plain line
  `{"qty", "text"}` (a brand-new ingredient, just text) versus a *linked* line
  `{"qty", "item": <slug>, "label", "note"}` (clickable, joins the field guide). Steps use
  `[[slug]]` or `[[slug|shown text]]` markup to link inline.

### 2. `migrations/` — the database structure, as history
Each file is applied once, in filename order, and recorded. Read them in order to see how
the schema grew. The two most instructive:

- **`005_cascade_history.sql`** — rebuilds `cook_log` and `ratings` so that deleting a
  recipe cascades to them. *Interesting because* it shows SQLite's "make a new table, copy
  the rows, swap names" procedure for changing a constraint (SQLite can't `ALTER` a foreign key
  in place).
- **`006_people_and_changes.sql`** — the per-person change feature's schema. It drops the
  old single-note `ingredient_overrides` table and creates three tables (details in the
  feature section below). *Interesting because* the comments explain the two-table split and
  which columns belong to which kind of change.
- **`007_addition_sections.sql`** — a one-line `ALTER TABLE` adding `section` to
  `recipe_additions`. *Interesting because* it shows the cheap kind of migration (just adding
  a nullable column) versus the table-rebuild procedure in `005` — and the comment explains why
  the section is stored by heading text.

### 3. `migrate.py` — applying migrations
Short. It turns on foreign keys, finds `.sql` files not yet in the
`schema_migrations` table, runs each in a transaction, and records it. It never deletes
data. This is what lets the schema change *in place* without rebuilding from scratch.

### 4. `build_db.py` — loading content safely
This is where the "content vs. your data" rule is enforced.

- **`seed_content()`** (line ~99): upserts the ingredient library, then wholesale-rebuilds
  each ingredient's seasons/regions, then (line ~146) **upserts people** and **drops anyone
  removed from `seed.py`** along with their changes, then manages **only** seed-owned
  recipes. *Interesting line:* the people-cleanup loop (~160) deletes child rows explicitly
  because foreign keys are turned **off** during the content load (so the cascade wouldn't
  fire on its own).
- **`seed_weights()`** (line ~201): loads `king-arthur-staples-v2.csv` into
  `ingredient_weights`, computing `grams_per_ml` at seed time (Phase 1c); rebuilt wholesale
  each run, like seasons/regions.
- **`build()`** (line ~340): runs migrations, loads content, then prints a report and a
  **drift warning** (line ~429) — where each per-person change landed, flagging `[!]` any that
  now point at a heading or a missing line. It also prints two **coverage reports**
  (`compute_coverage` for volume→weight match rate, `compute_step_coverage` for method-text
  scaling), each reusing the live parsers so the report can't drift from behavior.

### 5. `app.py` — the backend and the API
The heart of the change feature. Read top to bottom; the helpers come before the routes
that use them.

- **`db()`**: every connection sets `row_factory = Row` (so `row["name"]` works)
  and `PRAGMA foreign_keys = ON` (so deletes cascade). Reading this function first clarifies the rest of the file.
- **`recipe_stats()`**: cook count and last-cooked are **computed from the log**,
  never stored, so they can't drift. Note it's called *inside* the `with db()` block in
  `get_recipe` — a bug was fixed earlier where it ran after the connection context.
- **`changes_for()`**: the key function for the feature. It gathers all of a
  recipe's per-person changes into one map:
  `{ person_id: { edits: {pos: qty}, removes: [pos], additions: [...] } }`. Every change
  endpoint returns this exact shape, and the front end reads it directly. *Interesting note
  in the comment:* JSON turns the integer `edits` keys into strings; the front end's numeric
  lookup coerces to the same string, so it just works.
- **`seed_recipe_person_error()`**: one validation helper used by all four change
  endpoints. Returns `(message, status)` on failure or `None` on success. *Interesting
  because* it centralizes the "changes apply to seed recipes only, and the person must
  exist" rule — the endpoints stay short and consistent.
- **`get_recipe()`**: assembles the recipe, ingredients, steps, stats, the people
  list, and (for seed recipes only) the changes map, plus `is_seed` / `is_editable` flags
  the front end branches on.
- **The change endpoints**:
  - `PUT  /lines/<pos>` (`set_line_change`): edit a quantity or remove a line. Validates the
    position is a real, non-heading ingredient line, then upserts one row.
  - `DELETE /lines/<pos>` (`clear_line_change`): undo an edit or a removal.
  - `POST /additions` (`add_addition`): add a new line, either linked to a library
    ingredient (`item`) or plain `text`.
  - `DELETE /additions/<id>` (`delete_addition`): remove one addition.
  Each one validates, makes one small change, and returns `changes_for(...)`.
- **`set_rating()`** uses SQLite's `ON CONFLICT ... DO UPDATE` upsert so one
  rating per recipe is enforced by the database, not by app logic.
- **`weights.py` + `stepscale.py`** (Phase 1 helpers app.py imports): `weights` matches an
  ingredient name to a King Arthur weight and attaches `grams_per_ml` to each served line
  (volume→weight, 1c); `stepscale` parses method text into scalable vs never-scale spans
  (markup > guard > heuristic, 1d). Both are the single source of truth shared with the
  coverage reports in `build_db.py`.

### 6. `static/app.js` — rendering and interaction
No content of its own; it fetches JSON and builds HTML strings. Read in this order:

- **State**: `view = { slug, data, mode, editingPos, addingOpen, scale, units }`. `mode` is the
  whole UI for the per-person feature (`'original'`, a person id, or `'compare'`); `scale` is
  the quantity multiplier and `units` is the `'imperial'`/`'metric'` toggle. *Interesting because*
  the entire view is recomputed from this one object — a click sets a field and re-renders.
- **`esc()`**: every piece of data inserted into HTML goes through this. It's the
  app's XSS defense; the consistency is the point.
- **The render functions**, which mirror the three view modes:
  - `plainRow()`: the Original view and app recipes.
  - `personRows()`: one person's version — edited lines (new quantity, whole line in
    their colour), removed lines (struck, their colour), unchanged lines, and their
    additions placed at the bottom of *their own section*, each with a pencil/× control. The
    section placement is done by `renderWithSections()` just above it — a small walker that,
    at the end of each section (before the next heading and at the very end), drops in that
    section's additions.
  - `compareRows()`: the Compare view. Renders only the added ingredients — every
    person's additions together, each in their colour, read-only. Quantity edits and removals
    are intentionally excluded here; they appear only in each person's individual view.
  - `lineEditor()`: the inline quantity editor (Save / Remove / Reset-or-Restore /
    Cancel), with buttons that change based on the line's current state.
  - `viewSelector()`: the Original / people / Compare switcher; the active person's
    button is filled with **their colour** (pulled from the API, not hard-coded).
  - `ingredientsSectionInner()`: the dispatcher — picks the right renderer for the
    current `mode` and is the function re-run on every change (so the rest of the page
    doesn't flicker).
  - **The scaler / unit converter** (Phase 1): `scaleControl()` (presets ½×–3× + a custom
    multiplier) and `unitsControl()` (Imperial/Metric) sit by the Ingredients heading.
    `displayQty()` dispatches: counts round to whole (`scaleCount`, so "2 medium" never
    becomes "2 3/8"); Imperial uses `scaleQty` (1a); Metric uses `toMetric` — ≤ 2 tbsp keeps
    the spoon unit, > 2 tbsp → grams when the King Arthur table matches (marked "~"), else
    keeps the unit (decline). `renderStepRow` scales tagged quantities in method text from the
    server's spans (1d).
- **The mutation helpers**: `saveLineEdit`, `removeLine`, `clearLine`,
  `saveAddition`, `deleteAddition`. They all build on `changeBase()` (the URL prefix for the
  open recipe + active person) and funnel through `applyChanges()`, which writes the server's
  returned `changes` map back into `view.data` and re-renders. *Interesting because* the
  person id is always `view.mode` — editing controls only ever appear inside a person's view,
  so there's no separate "who am I editing as" state to track.
- **Event delegation**: one document-level click listener handles the whole app
  via `data-*` attributes (`data-view`, `data-edit-line`, `data-save-edit`, `data-add-save`,
  `data-del-add`, …). *Interesting because* it means freshly-rendered HTML needs no
  re-wiring — there are no per-element listeners to attach. The `change` listener
  is a convenience: selecting a library ingredient pre-fills the label box.

### 7. `static/styles.css` and `index.html`
- **`styles.css`**: the per-person rules live under "Per-person change layers"; the scaler
  control is `.scale-control`. The view switcher fills the active person's button with their
  colour, which is set inline from the API rather than in the stylesheet. (Compare renders
  additions only — there are no per-change pills.)
- **`index.html`**: just the shell — an `#app` container the JS fills, plus the field-guide
  drawer markup (`.panel` / `.scrim`). It rarely changes.

### 8. `tests/` — the pytest suite (Phase 0)
- **`harness.py`** builds a fresh database (migrations + `seed.py`) in a temp directory and
  returns a Flask test client. It has no pytest dependency, so the suite can be exercised
  without pytest if needed.
- **`conftest.py`** exposes that as the `kitchen` fixture; each test gets its own throwaway DB
  and never touches `recipes.db`.
- **`test_build_db.py` / `test_api.py` / `test_changes.py`** cover the build/migration process,
  the HTTP API (including that deleting a recipe cascades to its rating + cook history), and the
  per-person change layers (including rebuild-preservation). **`test_weights.py`** covers the
  volume→weight matcher (exact/alias/decline, kosher-salt default); **`test_stepscale.py`** the
  method-text parser (heaviest on the never-scale guard). Run with `python3 -m pytest`.

---

## The per-person changes feature, in depth

### The data model (migration 006)
Three kinds of change, split across **two tables** so every column is always meaningful:

- **`recipe_line_changes`** — a change to an *existing* line: either a new quantity
  (`kind='edit'`, `new_qty` set) or a removal (`kind='remove'`). Primary key is
  `(recipe_id, person_id, position)`, so a person has at most one change per line.
- **`recipe_additions`** — a *new* line a person adds, linked to a library ingredient
  (`ingredient_id` set) or plain text (`raw_text`), ordered by `id` (insertion order). An
  optional **`section`** (added in migration `007`) holds the *heading text* the addition
  belongs to, so it renders at the bottom of that section; `NULL` means no section (the
  pre-heading area, or a recipe with no headings). Stored by text, not line number, so it
  doesn't drift when quantities or positions change.
- **`people`** — seeded from `seed.py`; id, name, colour, display order.

**Why two tables instead of one** with a `kind` discriminator: edits/removes are keyed by an
existing line *position*; additions are independent rows with their own quantity and link.
Forcing them into one table would mean lots of "this column only applies when kind = X"
nulls. Two focused tables read more clearly and each column always means something — at the
cost of a second set of endpoints. At this scale, clarity wins.

### The interaction decisions (locked)
- **Edit = quantity only.** Changing a line edits its quantity; the *whole* line then renders
  in the person's colour (quantity, name, and note), not just the number. Swapping an
  ingredient is "remove + add," not an edit.
- **Add = a new line** at the bottom of its **section** (you pick which, when the recipe
  has headings; otherwise the bottom of the list), typed plain or linked to the library, in
  the person's colour.
- **Remove = the whole line struck through**, in the person's colour.
- **No text tags** ("added"/"removed"). Colour conveys *who* (via the switcher), and the form
  (changed number / new line / struck line) conveys *what*. In a single person's view an
  edited line and an added line look the same on purpose — that's the point: at a glance,
  their colour shows everything that differs from the original. Toggling to **Original**
  reveals which is which.
- **View switcher is single-select:** Original / each person / Compare all. Compare is
  read-only and shows only the added ingredients from all people, plus a one-line hint. The
  edit and add controls, and the display of quantity edits and removals, appear in a person's
  individual view.
- **Seed recipes only.** App recipes you simply edit directly (Edit/Delete), so they don't
  get change layers.
- **Colours come from the database** (seeded from `seed.py`), so the UI and the data agree.

---

## The recipe import pipeline (Phase 15)

Importing is a three-stage pipeline, each stage its own module so adding a source never touches
the hard logic:

1. **`paprika_native_reader.py`** — reads the Paprika NATIVE export (`.paprikarecipes`, a ZIP of
   gzip'd JSON) in memory and maps each recipe into a source-agnostic **normalized shape**
   (name, ingredient_lines, directions, source/source_url, categories, uid, hash, …).
2. **`import_cleanup.py`** — the source-agnostic **cleanup core**: turns each raw line into a
   structured-or-flagged record (amount/unit/name, sections, parenthetical grams, ranges, risky
   `N x SIZE`/`each`, the dual-unit `/ N unit` secondary-measure strip). Its rule is
   *decline-over-guess*: extract clear wins, FLAG the ambiguous, never silently mis-structure.
3. **`import_write.py`** — maps a cleaned recipe to database rows. This is the write path.

### The write path (`import_write.py`)

It splits into a **pure plan** and **one writer**, so the plan can be dry-run with no DB access:

- **`plan_recipe(cleaned, uid_index, taken_slugs)`** returns a write PLAN (touches no DB):
  - **slug vs. uid.** The **slug** is `recipes.id`, the human primary key minted from the title
    (lowercase, hyphenated, accent-folded; collisions get `-2`/`-3`); every child row
    (ingredients, steps, ratings, flags) references it. The **uid** is the *separate* dedup key —
    the source's stable id. One identifies the row; the other recognises the recipe.
  - **field mapping:** Paprika `source`→`author`, categories list→the `·`-joined `category`
    string, servings parsed-or-blank, `uid`+`hash` carried; `source='app'`.
  - **ingredients → `recipe_ingredients`** (position-ordered, `raw_text` always preserved);
    sections → `is_heading=1`; flagged lines are still written, just marked.
  - **steps → `recipe_steps`** (plain text, no `{{…}}` markup; section-header steps → heading).
  - **rating:** 1–5 → a `ratings` row; **0/unrated → no row** (the table's
    `CHECK(rating BETWEEN 1 AND 5)` would reject 0).
- **`commit_plan(conn, plan)`** is the only writer; the dry-run never calls it.

### uid-dedup and the `source='app'` tier

Before writing, the plan checks the recipe's `uid` against the uids already in the database
(migration `009` added `recipes.uid` + `hash` with a partial unique index). If it's already
present, the recipe is **SKIPPED** — that's what makes re-importing idempotent, and how the **5
seed recipes** (now tagged in `seed.py` with their matched Paprika uids) skip their native twins
instead of duplicating them. Imported recipes are written at the **`source='app'`** tier, so they
live alongside the seed recipes and **survive every rebuild** (`build_db.py` only ever rebuilds
`source='seed'`).

### The review queue (`import_flags`, migration 010)

Nothing is ever dropped. Lines the core couldn't confidently structure are still written (with
`raw_text` intact) and *also* recorded in **`import_flags`** for later review — line-level flags
(`multiplier`, `each_multi`, `ambiguous_section`, `grams_declined`) carry the line's `position`;
recipe-level incompletes (`no_ingredients`, `no_directions`, `photo_only`) use a NULL position.
It's kept out of the rendering tables, so one `SELECT` is the whole queue.

**Validated by a dry-run** (`python3 import_write.py [--seed N]`) on a random 15 recipes with
distinct authors: it prints the full plan for each — field values, minted slug, dedup decision,
ingredient/step rows, rating decision, and review-queue rows — and **writes nothing**.

**Not done here — separate upcoming passes:** library **linkage** (`ingredient_id` stays NULL)
and full **image storage** (`image` stays NULL; `photos[]` is not extracted yet).

---

## Critical pros & cons / future considerations

Known tradeoffs and considerations before extending the app.

1. **Position-keyed edits/removes can drift.** A change points at line *position N*. If you
   reorder or delete ingredients in a seed recipe in `seed.py`, an old change can land on the
   wrong line. *Mitigation:* `build_db.py` prints where every change landed after a rebuild
   and flags `[!]` any that no longer fit. *Pro:* simple, no extra IDs on every line. *Con:*
   the safety net is a printed warning you have to read — it doesn't auto-correct. If recipes
   start getting reordered often, consider keying changes to a stable per-line id instead.

   A related, gentler case: an addition remembers its **section by the heading's text**, not
   a line number — so it survives reordering, but if you *rename or delete that heading* in
   `seed.py`, the addition no longer matches and quietly falls to the bottom of the list.
   `build_db.py` lists those after a rebuild (flagged `[!]`) so you can re-point them in the
   app. Text was chosen over a line number precisely so the common edits (quantities,
   reordering) don't disturb additions; only a heading rename does.

2. **Additions can't be edited yet.** To change an addition's quantity you delete it and add
   it again. *Pro:* fewer endpoints, less UI. *Con:* mildly clunky. A `PUT /additions/<id>`
   plus an inline editor would close this; the data model already supports it.

3. **Only quantities are editable on original lines.** Editing the *name* or *note* of a seed
   line isn't supported (swap = remove + add). Full per-field editing is a deferred option.

4. **Compare shows only additions (intentional).** Compare renders only the added
   ingredients from all people, not their quantity edits or removals. Rationale: it keeps the
   view focused on one question — which ingredients people are adding — and the per-person
   edits are already visible by switching to each person's view. Tradeoff: there is no single
   screen that overlays everyone's quantity edits side by side. If that is wanted later, the
   data supports it — re-add per-person quantity chips / strikethroughs in `compareRows()`.

5. **No in-app people management.** People are config in `seed.py`. *Pro:* dead simple, ids
   stay stable. *Con:* adding a person means editing a file and rebuilding. Intentional for
   now.

6. **"Promote an app recipe into `seed.py`" isn't built.** It's feasible — `build_db.py`
   upserts seed recipes by slug, so a promoted recipe would keep its ratings and history, and
   would automatically gain the comparison overlay (seed recipes get change layers). The only
   friction is transcribing it into `seed.py` by hand.

7. **Seasons/regions are rebuilt wholesale on every build.** Harmless today (that data only
   comes from `seed.py`). It becomes a real risk *only* if you later add "promote an
   ingredient to the library" with app-entered season/region data — that data would be wiped.
   Note it before building that feature.

8. **Security: `debug=True` and the bind host.** `app.py` runs with `debug=True`, which is
   fine for `localhost`. **If you ever change `app.run(...)` to bind `host="0.0.0.0"`** (to
   reach it from a phone on your Wi-Fi), **set `debug=False` at the same time** — Flask's
   debugger allows code execution, so an exposed debug server is a remote-code-execution risk.
   This is the highest-stakes line in the project.

9. **Scaling ceiling.** This setup handles hundreds of recipes for one cook on one machine.
   A larger architecture is warranted only for multi-device or multi-user access (hosting — a
   deployed server and hosted database) or concurrent editing.

---

## Code-quality notes (the explicitness review)

What's deliberately explicit, and why it reads the way it does:

- **`esc()` on every inserted value** (app.js) and **parameterized SQL everywhere** (app.py).
  These are the two safety habits; their *consistency* is what makes them trustworthy. No raw
  string interpolation reaches HTML or SQL.
- **Computed, not stored, derived values.** Cook count and last-cooked are counted from the
  log on every read (`recipe_stats`), so there's no counter to fall out of sync.
- **Foreign-key integrity is on** for every app connection, and `build_db.py` runs a
  `foreign_key_check` after loading. Deletes cascade by design, not by remembering to clean up.
- **One small validation helper per concern.** `seed_recipe_person_error` (the seed+person
  rule) and `validate_recipe_payload` (the recipe form) keep the routes short and the rules in
  one place each.
- **One change shape, one source of truth.** `changes_for` defines the per-person change map;
  every change endpoint returns it and the front end reads it — the structure is never spelled
  out in two places.
- **Event delegation over per-element listeners.** A single click handler dispatches on
  `data-*` attributes, so re-rendered HTML never needs re-wiring.
- **Comments explain *why*, not *what*.** Beginner-level prose on the non-obvious bits (the
  FK-off explicit deletes in `build_db.py`, the JSON-stringifies-keys note in `changes_for`,
  the cascade-rebuild procedure in migration 005).
- **Deliberate simplicity:** `kind` values (`'edit'`/`'remove'`), `source`
  (`'seed'`/`'app'`), and `mode` (`'original'`/`'compare'`) are plain string literals rather
  than named constants/enums. At this surface area they're self-documenting and easy to read.
  If these strings start appearing in many more places, promoting them to shared constants
  would be the next tidy-up.

---

## Change log / history

Newest first. Add an entry whenever the architecture or a feature changes.

- **Recipe import — reader → cleanup core → write (Phase 15)** *(current)* — a three-stage import
  pipeline: `paprika_native_reader.py` (Paprika NATIVE export → normalized shape),
  `import_cleanup.py` (source-agnostic cleanup core, decline-over-guess), and `import_write.py`
  (cleaned recipe → DB rows). Migration `009` added `recipes.uid` + `hash` (uid = dedup key,
  separate from the slug PK); the 5 seed recipes were tagged with their Paprika uids so import
  skips their twins. The write layer mints a slug from the title (collision-safe), writes at the
  `source='app'` tier, maps categories/servings/rating (0 → no `ratings` row), and routes flagged
  lines + recipe-level incompletes to a new `import_flags` review queue (migration `010`) —
  dropping nothing. Validated by a writes-nothing dry-run on a random 15 distinct-author recipes.
  Library linkage (`ingredient_id`) and full image storage remain separate upcoming passes.
  Suite: 116 tests.
- **Quantity & units complete (Phase 1)** — the amount system, built 1a→1d then
  refined. 1a scaler; 1b metric/imperial; 1c volume→weight via a server-side matcher
  (`weights.py`, `ingredient_weights`, seeded from `king-arthur-staples-v2.csv`); 1d step-text
  scaling (`stepscale.py`, markup > guard > heuristic — temps/times/dimensions never scale).
  The toggle was then collapsed to a **2-way Imperial↔Metric smart mode** (≤ 2 tbsp keeps
  tsp/tbsp; > 2 tbsp → grams when KA matches, "~"; else keeps the unit), removing the old
  3-way (separate all-mL + Grams modes and `toGrams`). Two display bugs fixed: counts no longer
  fraction ("2 medium" stays whole); same-unit compounds combine ("3 + 2 tbsp" → grams, not
  "53 + 35 mL"). `build_db.py` gained two coverage reports; the suite is 52 tests (incl.
  `test_weights.py`, `test_stepscale.py`). The client-side converter has no automated harness
  yet — see ROADMAP.
- **Test suite (Phase 0)** — a persisted pytest suite under `tests/` replaces
  the throwaway smoke tests. `tests/harness.py` builds a fresh database (migrations +
  `seed.py`) in a temp directory and returns a Flask test client; `conftest.py` exposes it
  as the `kitchen` fixture, so every test runs against its own throwaway DB and never
  touches `recipes.db`. ~20 tests cover the API, migrate/build_db (idempotent rebuild, FK
  integrity, seed counts), and the per-person change layers including rebuild-preservation.
  pytest is a dev-only dependency (`requirements-dev.txt`); run with `python3 -m pytest`.
  Bump `EXPECTED_MIGRATIONS` in `test_build_db.py` when a migration is added.
- **Quantity scaler (Phase 1a)** — a ×½ / ×1 / ×2 / ×3 control beside the
  Ingredients heading rescales every displayed quantity live. A shared parser (`scaleQty`
  with `normalizeFractions` / `tokenToNumber` / `formatAmount` in `app.js`) multiplies every
  number in a quantity string and leaves units and words alone, so dual units ("2 lb / 1 kg"),
  split amounts ("3 + 2 tbsp"), unicode fractions ("1½ cups"), and non-numeric quantities
  ("to taste") all behave. Scales the *displayed* value, so it composes with per-person edits;
  the inline editor stays unscaled (it edits the base). No schema change. Output prefers common
  kitchen fractions, falls back to a trimmed decimal, never renders a positive amount as "0",
  and rounds large amounts to whole numbers (188 mL, not 187 1/2 mL — a magnitude heuristic
  that 1b will replace with proper per-unit handling). The metric/imperial toggle (1b) and King
  Arthur weight conversion (1c) are intended to reuse this parser.
- **Additions land in their section** — a new ingredient now drops in at the
  bottom of its own section (you pick which, when the recipe has headings) instead of the
  very bottom of the whole list. The section is stored on `recipe_additions` by heading text
  (migration `007`); placement is handled by a small `renderWithSections()` walker shared by
  the person view. The build report flags additions whose section heading was later renamed.
- **Compare view scope** — Compare now shows only the added ingredients from all people
  (each in their colour) plus a one-line hint. Quantity edits and removals appear only in each
  person's individual view. Removed the now-unused compare-chip styling.
- **Per-person change layers** — replaced the single anonymous "my changes" note with
  per-person versions of seed recipes: edit a quantity, remove a line, or add an
  ingredient, each in a person's colour, with an Original / person / Compare-all switcher.
  Schema: migration `006` (drops `ingredient_overrides`; adds `people`,
  `recipe_line_changes`, `recipe_additions`). People are configured in `seed.py`. This is the
  largest, most complex feature so far — it touches the schema, the build script's
  content-vs-data logic, four new API endpoints, and a full rewrite of the recipe view in
  `app.js`.
- **Cascade fix** — migration `005` rebuilt `cook_log` and `ratings` so deleting a recipe
  cascades cleanly; fixed a fragile call where `recipe_stats` ran just outside the database
  connection block.
- **In-app authoring** — migration `004` added a `source` column; recipes are now either
  `seed` (from `seed.py`, read-only in the app) or `app` (created and edited in the app). A
  create/edit form and an earlier single-note override system were added.
- **Cooking features + migrations** — added star ratings and a cook log (migration `002`) and
  `created_at` timestamps (`003`). This was the first data that couldn't be regenerated from
  `seed.py`, which is *why* the migration system exists: to change the schema in place without
  wiping your data.
- **Flask + SQLite** — moved from JSON files served by a plain Python server to a Flask
  backend over a normalized SQLite schema (migration `001`): ingredients in their own tables,
  recipes referencing them, enabling cross-cutting queries (which recipes use an ingredient,
  what's in season now).
- **Earlier** — began as a single self-contained HTML file, then separate files with JSON
  data served by a small Python HTTP server.
