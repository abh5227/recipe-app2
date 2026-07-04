# Chef's Choice — Design Decisions

The settled design direction for the recipe app's front end, plus the Round-1 / Round-2 staging
that governs how it's built. This is the **source of record** for decisions that otherwise live
only in planning conversation — written so the rationale survives and later work doesn't re-litigate
or build against the wrong intent.

- **Product vision** (why outcome data is the point) lives in [OVERVIEW.md](../OVERVIEW.md) →
  *The vision* and [ROADMAP.md](../ROADMAP.md) → *Tier 0*; recapped briefly here, not duplicated.
- **Code history / architecture** lives in [CODE_WALKTHROUGH.md](../CODE_WALKTHROUGH.md).
- **The verified-clean 15** (the real data Round 1 is designed against, incl. the
  `convert_to_grams` flag) is in [docs/import-reference-15.md](import-reference-15.md).

Status: **Round 1 in progress** (Stages A–D built; **Stage E in progress**). Nothing here is rendered on real
data beyond Round 1's scope — see the R1/R2 boundary below.

---

## App name

**Chef's Choice** — the chosen product name (renamed from the prior working name, *Seasonal
Kitchen*). The rename has since been **applied** across the UI + docs (as a standalone commit, kept
separate from the design-code stages).

## Product vision (recap — see OVERVIEW / ROADMAP Tier 0)

The recipe itself is a **commodity** (the internet has millions; models already know them). The
scarce, valuable asset is the user's **outcome data** — what gets cooked, how it's rated, what gets
modified. Every feature optimizes for capturing that signal, structured and timestamped. The design
below is the visual expression of exactly this split.

## Underlying theme — "a recipe is a work in progress"

A recipe evolves, accrues, and is never finished. This theme is **implicit and felt, never stated**
— there are no taglines or UI copy announcing it. It is embodied by the used-cookbook concept, and
it sets a guiding **sensibility**: calm and restraint over cleverness; **empty states read as calm
beginnings, not absences** (a not-yet-cooked recipe, a recipe with no photo, no annotations — none
should feel like something is missing, broken, scolding, or peppy).

---

## The design concept — "used cookbook"

The recipe page reads like a page from a printed cookbook, layered to mirror the vision:

| layer | what it is | maps to |
|---|---|---|
| the **typeset recipe** (printed original) | the recipe as published | the **commodity** |
| the **user's layer** (modifications + notes, in their own hand) | what *this* cook changed | the scarce **asset** |
| the page **wears** subtly with use (driven by `cook_log` count) | a pristine page = uncooked; a worn, marked-up page = personal | the asset *accruing* |

A pristine recipe is the commodity; a worn, hand-marked one is the personal asset. The look *is* the
outcome-data philosophy.

### Character

**"Precise reference cookbook"** — chosen deliberately over a warmer "hand-cookbook" character that
was considered and **rejected**: *precise* showcases the measurement rigor (the ledger, the weights,
the scaling). It evolved from an earlier "newspaper structure + warm cookbook undertone" framing
into this precise-cookbook character.

### Palette — all earth tones (aubergine removed)

A coherent warm-earth system — cream paper, brown ink, green structure — with no cool note.
**Aubergine `#5a3658` was removed entirely** (it was the one cool color and clashed with the warm
paper/brown).

- **Warm brown** — the body + control layer: all reading text (ingredient names, steps, title) is a
  warm rich brown (`--ink #523823`, ~8.5:1 on paper), and the active/primary control ("Cooked it"
  button, active scale pill) is a deeper warm brown (`--btn-fill #4A3220`, cream text). Amounts and
  weights are the muted brown (`--ink-soft`).
- **Warm earthy green `--green #4E4B24`** (drab olive) — the **printed recipe's structure**: section
  labels, **both** section-divider rules, step-number circles, links, the byline. Replaces aubergine
  on everything it used to mark; chosen deep enough to read as small label text (~7.1:1).
- **Warm paper** — unchanged: a layered warm tan/cream with subtle patina, the recipe a page lifted
  off a warm desk.
- **The user's hand layer** — a **reserved earthy tone** (`--hand`, a warm terracotta/rust,
  finalized at R2), replacing the old oxblood; warm-earth yet contrasting the green structure.
  *Reserved in Round 1* (token defined, unused); rendered in Round 2.
- **Category tags** — re-toned to a warm-earth set (brick / olive / ochre / terracotta / clay-rose),
  muted and distinct; **same category = same color** (cuisine kept as one crisper color, not a shade
  per cuisine). Status tags stay dashed/quiet; unlisted tags stay plain.

So the two structural jobs are now **green = the printed structure** and **the earthy hand color =
the user's layer**, with **brown** carrying the body text and the primary control.

### Type — Spectral serif + a metadata sans (Version 3; mono still dropped)

- **Spectral** (transitional serif) carries the **content voice**: recipe title, ingredient names,
  step text, and the ledger's tabular figures + labels. IBM Plex Mono stays dropped — ledger
  amounts/labels are still distinguished by **treatment** (`tabular-nums`, size, muted color), not a
  mono face (`--font-mono` remains an alias of `--font-serif`).
- **Inter** (self-hosted, `--font-sans`) carries the **metadata voice** (Version 3): byline, category
  tags, serves/time, the two-line cook-summary, and button labels. Rationale: one serif left metadata
  and actions competing at a single weight; a crisp humanist sans lets **metadata/history recede**
  while the serif holds title + content — clearer hierarchy, still calm. A scoped revision of the
  earlier Option C "one voice": one **content** face, one **metadata** face — not a return to mono.
- **Offline:** Inter is bundled at `static/fonts/inter.woff2` (variable weight; `@font-face` in
  styles.css). **Spectral is still Google-Fonts-loaded** (index.html), so offline the *title* falls
  back to Georgia/serif while metadata stays local (see caveats).
- **A pen-like hand** (Caveat / Kalam) — the Round-2 user layer; **reserved**, not loaded in R1.
- **Masthead title face** — `--font-title` remains the one-line swap point (Spectral / Newsreader /
  Fraunces), kept for flexibility.

### Layout — single-column (required, not just aesthetic)

Masthead → ledger → method, one column. Required because the Round-2 handwritten **margin** layer
needs the right **gutter** free, which a two-column layout would consume; single-column also travels
cleanly to mobile.

### Ingredients — a precise ledger

An **amount** column + the **name**, with the gram estimate (`~N g`) shown as a **small muted
sub-line tucked under the amount** — only when present (Option B2). There is **no fixed weight
column**: weightless rows read tight, ingredient names stay aligned at a consistent left edge on
every row, and scaling never flips the layout (the earlier reserved-column design left a dead gap on
weightless rows and could appear/disappear with scale). **No units toggle** — the volume+weight
display replaces it. Which lines show a weight is governed by the `convert_to_grams` flag from the
import work: dry staples / dairy / pastes convert; **oils and raw produce stay in their authored
volume**. (See [import-reference-15.md](import-reference-15.md).)

### Masthead

Byline (author / source) · title · headnote · meta (Serves · time · cooked-count) · a single
finished-dish **photo top-right** (restrained, framed). The **headnote** is subordinate to the title
and, for long imported blurbs, truncated to ~3 lines with a **"more"** expander (so you reach the
ingredients fast). **Graceful empty state:** when there's no photo, the slot collapses and the title
block takes the full width — no placeholder box.

### Control strip + vitals/history zone — the "this is an app" affordances

- **Layout (Hybrid 2b):** below the masthead + a hairline, a quiet **serves/time** line, then a soft
  **inset cook block** (`.cook-block` — lighter `--card`, `--rule-soft` border, rounded, inset pad)
  grouping star rating + two-line cook-summary + cook buttons as one unit; a second faint hairline
  separates the manage zone (**Edit recipe** / **Delete recipe**). Left-aligned; no uppercase labels,
  no vertical dividers.
- **Serves/time — icon + value:** a man+woman figure pair before "Serves N" and a clock before the
  time (inline SVG, `--ink-soft`); the **values are emphasized** (`--ink`, heavier) while icons and
  the "Serves" label stay quiet.
- **Scaler in the vitals:** ½× · 1× · 2× · custom moved out of the ingredients area onto its **own
  line in the vitals**, under serves/time, so the **serving number updates live where you adjust it**.
  It drives `view.scale`; serves-count and ingredient/step amounts recompute off it. A scale change
  re-renders only ingredients/steps/serves-count/scaler-host — **never the cook block** — so redo/cook
  state is undisturbed. The **custom field shows its committed factor as "N×"** (right-aligned, like
  the presets); focus strips it to a bare number to edit. (`type=text` is deliberate: the control is
  rebuilt on scale change and `type=number` got destroyed mid-interaction.)
- **Rating:** softened stars (a set rating reads "set", not shouting). Cook-gated as before — a star
  on an uncooked recipe opens the inline "Mark cooked & rate?" confirm (combined cook-and-rate
  endpoint, one transaction); undo-to-zero clears the rating. Provisional/seeded dates keep the `~`.
- **Delete recipe:** relabeled to mirror "Edit recipe"; **subtle-red at rest** (desaturated brick
  text with a soft border, via `color-mix`) deepening to the full danger fill on hover.

### Cook history — summary, backdating, and one-shot redo

- **Cook-summary:** two stacked lines — "Cooked N times" / "Last cooked [date]" (no separator);
  provisional/seeded dates keep the `~`/`.approx` treatment.
- **Backdated cook:** "Log a past cook" logs a cook on a chosen date (`source` stays `app`); validated
  server-side (real calendar date, not future).
- **Undo / Redo — a faithful one-shot.** Undo removes the most-recent cook; the control then shows a
  **text** "Undo" / "Redo" pair (words, not glyphs). Redo restores the **exact** undone cook (same
  `cooked_on` + `source`) and, **only if that undo cleared a rating**, restores the rating too —
  re-adding the **cook before the rating** so the never-uncooked-but-rated invariant holds. The window
  is one-shot: **any other action clears it** (opening the backdate modal repaints the bar so the pair
  collapses). `/uncook` **reports what it removed** (`undone: {cooked_on, source, cleared_rating}`) and
  `/redo-cook` restores it — necessary because the last-**inserted** cook (what undo removes) is not
  the last-**by-date** after a backdated cook, so the client can't infer it.

### The handwritten edit treatment (Round 2)

A changed value renders as the **original struck in print** (a clean strikethrough) **+ the new
value in the earthy hand color** beside it — the **print-vs-hand contrast** is what makes it read as
an *edit* rather than a correction. Notes render in the hand color near the relevant step. This is
**reserved/structural in R1** (see boundary) and **built in R2**.

---

## Round 1 / Round 2 staging

### Round 1 (now) — the clean cookbook page, against the verified-clean 15

The paper/type/color system, the masthead, the ledger, the photo slot, the control strip + the
scaler/rating-cluster fixes, amount formatting, tags, and graceful empty states. **The recipe page
only.**

### Round 2 (deferred) — needs real accruing data we don't have yet

- The handwritten **edit/note layer** (in the reserved earthy hand color).
- The **wear / patina deepening** with cook count.
- The **populated compare / version display**.
- The **list / browse page redesign** (the "scale / browsing review" — after the ~295 import).

### Reserve-not-build (R1 architects for R2 so it isn't a retrofit)

Defined or structured in R1, but **not rendered on real data** — each reserved with its actual mechanism:

- **`--hand`** / **`--font-hand`** — the hand color + pen-hand font tokens, declared and unused (the hand font is not loaded in R1).
- **`--hand-gutter`** — the reserved right margin, wired into the recipe reading column's `max-width` at **0** in R1.
- **The amount cell** — the ledger's `.amount-cell` (addressable `.qty` inside) is the R2 **strike target**: R2 strikes the printed value and sets the edited value beside it in the hand color.
- **The step-body wrapper** — each method step's body is wrapped in **`.step-body`** inside `li.step`, the attach point for future per-step photos and R2 step-notes.
- **The `--cook-count` wear signal** — the recipe root (`.page.recipe-view`) carries an inline **`--cook-count`** custom property (the recipe's cook count, kept live on cook/undo); unread in R1, so R2 can scale a wear/patina effect without re-plumbing the count.

### Staged R1 implementation plan (per-stage commits, suite green at each)

| stage | scope |
|---|---|
| **A** | tokens + paper shell + typography |
| **B** | masthead + byline/tags + photo slot + empty states |
| **C** | the ledger + amount-formatting |
| **D** | control strip + the scaler/rating cluster |
| **E** | reserve the R2 hooks (no R2 layer built) |

---

## Punch-list → where each is addressed

| item | stage |
|---|---|
| byline / author-source distinction | B |
| distinguishable tags (split the `·`-joined category) | B |
| section-header styling | C |
| two-column alignment + long-name wrapping (aligned amount cell; weight as a sub-line — B2) | C |
| amount formatting — humane decimals, thousands separators, unit-abbreviation standardization | C |
| post-ingredients → method flow | B/C |
| **scaler/rating cluster** — five-star **hover-preview** (left-to-right fill on hover); rating **gated on a logged cook** (inline "Mark cooked & rate?"); custom-field fixes; servings original-vs-scaled labeling; clamped-count honesty note; layout robust to long custom values | D |
| compare-all-includes-original (now natural via the struck original) | R2 |
| no-person-versions handled gracefully | already true for app recipes |

**One consistent "approximate / adjusted-value" treatment** for the *family* of indicators —
the `~` on estimated weights, the clamped-count honesty note, and humane-rounded decimals — should
be **one** visual treatment, not three ad-hoc ones (decided in D, applied across C/D).

---

## Architecture decisions touched during the design work

- **Grams-wipe-on-edit fix — landed (`0c3f6ae`).** Editing an app-tier recipe used to NULL the
  import-harvested `grams`/`secondary_measure` (the form rewrites the rows wholesale). The edit path
  now **preserves** them for **unchanged** lines, matched on normalized **(qty, label‖raw_text)**
  (`.strip().lower()` only — no unit-stripping/fraction-folding), and **clears** them on a qty/name
  change (a stale weight is never carried). Key uses `label‖raw_text` because the imports are plain
  lines with `label=NULL` (name in `raw_text`). The ledger's weight column is unaffected regardless
  (`grams_per_ml` is matched live, never stored).
- **R2 handwritten layer — architectural tension to resolve** (see ROADMAP): the per-person change
  model (edit/remove lines, additions) currently exists **only for seed recipes** (`is_seed`); the
  imported 15 are app-tier, with the **form-edit** path but **not** the per-person annotation layer.
  Applying the hand layer to the imports requires extending that model to app-tier recipes (or
  unifying the two), and deciding how "edit the canonical recipe" and "annotate by hand" coexist.

## The inline recipe editor ("mark up the page")

The recipe **edit** experience is being rebuilt from a separate admin-style form into **in-place
editing on the real recipe page**: an **✎ Edit** toggle flips the reading page into edit mode and
the same masthead/ledger/steps become editable where they sit. The old form (`renderForm`, the
`#/edit/…` route) is **kept as a fallback** until the inline editor is complete, then retired.

**Interaction model** (chosen after a try-able prototype of the alternatives):
- **Edit-mode toggle + explicit Save** (`view.editMode`; a floating Save/Cancel bar). Not
  click-to-edit-one-field, not autosave — a deliberate reading↔editing switch, safe to make many
  changes in, then commit together.
- **Buffered draft.** Entering edit deep-copies the recipe (`view.draft = structuredClone(view.data)`);
  **all edits mutate the draft, never `view.data`**. Save PUTs the draft and commits it; Cancel
  discards it (zero-risk revert).
- **Dual-mode via one renderer.** `renderRecipe` was split into fetch + **`paintRecipe()`**, which
  paints reading **or** edit from `view` (no re-fetch). Edit mode uses **sub-renderers that read the
  RAW authored fields** — deliberately **not** making the reading spans editable, because the reading
  view is **scaled / volume→weight-converted / `[[…]]`-markup-stripped**, so editing must bind to the
  raw source, not the cooked display. Entering edit forces `view.scale = 1` (scaler hidden) and
  bypasses the description clamp.
- **Focus-preserving buffering.** Text edits write to the draft on **`input` only, with no re-render**
  (re-rendering on a keystroke would drop focus/caret); the page repaints only on structural/mode
  changes.
- **Dirty-state navigation guard.** Hash routing rebuilds `view` from a fresh fetch on any hash
  change, so an unsaved buffer would be silently lost — a **`hashchange` guard** (← link, back button,
  any `#/` nav) prompts "Discard unsaved changes?" and restores the hash if declined; **`beforeunload`**
  covers reload/close.
- Actions are namespaced **`data-inline-edit-*`**, sub-dispatched ahead of the main click handler.

**Core principle — every edit field behaves like its reading-mode counterpart:** same typography,
wrapping and shape, just editable — **no uppercase form labels, no bordered boxes**. The affordance
("Option 3", chosen from a look-preview) is a **faint dashed baseline at rest**, a whisper of tint on
hover, and a **soft rounded lift on focus** (like writing on a note). Fields route through **four
kinds** so edit mode is consistent by construction:

| kind | behavior | fields |
|---|---|---|
| **`.ie-line`** | wrapping, auto-growing **single logical line** (soft-wrap; Enter swallowed; newlines stripped on save) | title, author/byline |
| **`.ie-prose`** | wrapping, auto-growing multi-line (hard newlines allowed) | description, note |
| **`.ie-num`** | short inline, reading-meta register (right-aligned; auto-grows to fit) | servings, prep, cook, total |
| **`.ie-util`** | minimal, faint, full-width single-line (no reading counterpart) | source URL |

**Field-level decisions:**
- **Tags** edit as **discrete chips** (× to remove, "+ tag" to add), re-joined to the stored
  **`·`-delimited `category` string** on save — a UI-only split/join, no schema change.
- **Image path is NOT editable inline** — deferred to the upcoming **photo-upload** feature (which
  wires the Polaroid "+ add a photo" to a real upload). A raw `images/slug.jpg` field is the exact
  form-y stopgap we're eliminating; the existing image **round-trips untouched** from the draft on
  save, so nothing is lost.
- **Note** renders at the **bottom** (after the steps), matching the reading "Note. …" block.
- **Description** is **full-width** in edit mode (the reading narrow-then-wide float is relaxed) — a
  rectangular textarea can't cleanly hug the tilted Polaroid, and a wide field is better to type in;
  it clears the photo via a masthead `min-height`.

**Stage 1 (built):** the **scalar / masthead fields** (title, author, source_url, category/tags,
servings, times, description, note). **Ingredients and steps stay display-only** in edit mode
(rendered from the draft, round-tripped unchanged on save); their discrete inline editing
(add/remove/**reorder** — the data model already supports order via `position`) lands in later stages.
**Backend untouched** — the existing `PUT /api/recipes/<id>` already full-replaces rows from the
payload and preserves harvested grams for unchanged lines.

This is the **"edit the canonical recipe"** path — distinct from the R2 **handwritten annotation
layer** (struck-print + hand color) and from the seed-only per-person change model (see the
architectural tension above).

## Recorded caveats (Version 3 / vitals bundle)

- **`color-mix()`** powers the subtle-red Delete (`.btn.danger-soft`) — a modern-browser dependency;
  fine for this local single-user app; swap to literal tokens if broader support is ever needed.
- **Spectral is CDN-loaded** while Inter is self-hosted, so offline only the *title* serif falls back
  to Georgia. Bundling Spectral locally is the follow-up for full-offline fidelity.
- **`field-sizing: content`** auto-grows the inline edit fields (title/author/prose/meta) to their
  content — a modern-browser dependency (same class as `color-mix()`), with a **`size`-attribute
  fallback** on the short meta fields so they don't balloon where unsupported.
- **Free-text time values** (`prep_time`/`cook_time`/`total_time`) are edited **as-is** (the whole
  `"5 min"` / `"1 hr 15 min"` / `"overnight"` string), not split into number + unit — the stored
  format is free text, so a number-only field would break non-`min` values.

## Open questions

- **Masthead title face** — Spectral vs Newsreader vs Fraunces, decided by eye after Stage B renders
  the real masthead. `--font-title` is the swap point.
