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

### Ingredient `qty` → structured `quantity` + `unit` (staged split)

**Why.** The single free-text `qty` ("2 tablespoons") blocks the two things the ledger will need:
**unit conversion** (metric/imperial, volume→weight) driven off a *known* unit, and
**filtering/aggregation** by unit — neither of which a free-text field (or a free-text unit picker)
can do reliably. So `qty` is being split into a structured **`quantity`** (amount expression) +
**`unit`**.

**Storage model — Option B, purely additive.** `qty` is kept **UNTOUCHED as source-of-truth** (still
holds the joined string). Two **nullable** columns are *added* — `quantity` ("2", "1 1/2", "2-3", "4")
and `unit` ("tablespoons", "", "cloves"). The split is **lossless by construction**: `quantity + " " +
unit` (whitespace-normalized) reconstructs `qty` — verified **0 mismatches across 3,425 rows**; any row
that wouldn't reconstruct falls back to the whole string in `quantity` with `unit=""` rather than
mis-structure.

**The split rule** (`import_cleanup.split_qty`, reused by the backfill, the seed-load path, and the
import so all three split identically): number+measuring-unit → `("2","tablespoons")`; number-only →
`("2","")`; empty → `("","")`; **count-nouns fold into the unit** (`"4 cloves"` → `("4","cloves")`);
the ~5 **irreducibles** — slash-duals (`"2 lb / 1 kg"`), compounds (`"3 + 2 tbsp"`), and no-number text
(`"pinch"`, `"to taste"`) — are **kept whole** with `unit=""`.

**This is the repo's FIRST data-transforming change.** Unlike migrations 011/012 (which only *added*
columns and let import fill them), 96% of `qty` data is `source='app'` — persistent in `recipes.db`,
**not** regenerated on rebuild — so it needs a real backfill. Because `migrate.py` runs SQL only
(`executescript`, can't call `parse_amount`), the split can't live in the migration: **migration 015
adds the nullable columns; a separate idempotent Python backfill (`scripts/backfill_qty_unit.py`,
guarded `WHERE quantity IS NULL`) transforms the persistent app rows**, while seed/test rows split on
rebuild via `build_db`. Backfill distribution: **66.1% number+unit, 19.1% number-only, 14.8% empty, 0%
irreducible-fallback**.

**The scaler stays byte-for-byte identical (critical).** Nothing reads `quantity`/`unit` for display
yet — the scaler (`scaler.js`/`stepscale.py`) keeps operating on the recombined `qty`, untouched.
Refactoring it to consume the structured fields is **deferred as an optional Stage 5**, done only if
unit conversion/filtering later hits friction on string-parsing.

**Staged plan.** **1 (done):** schema + backfill. **2 (done):** seed/import split. **3 (done):** the
write path threads `unit` (`write_recipe_rows` re-derives on every write; copy carries them; durable
across edits/copies/creates). **4 (done):** the **editor UI** — the qty cell splits into a **quantity
field + unit combobox**, and the payload sends explicit `quantity`+`unit`, so **authority flipped to
structured quantity+unit (Model B)**: the editor sends the parts and the server (sub-step A's IF branch)
recombines `qty`. The split is now **user-editable end-to-end**. **5 (optional/deferred):** scaler
consumes the structured fields (only if string-parsing later hits friction).

**Stage-3 carry-forward — ✅ closed in Stage 3.** The PUT full-replaces a recipe's ingredient rows via
`write_recipe_rows`, which *used to* write only `qty` → editing a recipe NULLed its `quantity`/`unit`
until re-backfilled. **Resolved:** `write_recipe_rows` now **re-derives `quantity`/`unit` via
`split_qty(qty)`** in the linked and plain branches (headings stay NULL), and the copy `INSERT…SELECT`
carries them — so create, edit, per-person writes, and copies all persist the split, consistent with
`qty`. This is **option (b), shaped as the ELSE branch of a hybrid**: `qty` is authoritative now and the
split is derived from it (client sends only `qty` today). **Stage 4** will add the **IF branch** — when
the editor sends explicit `quantity`/`unit`, the server uses them and recombines
`qty = quantity + " " + unit` — flipping authority to structured `quantity`+`unit` (Model B) without
reworking Stage 3. The scaler stays untouched (still reads `qty`, kept valid by the derive); the read
path was already carrying the split (GET `SELECT *` + `structuredClone`), so Stage 3 was write-side only.

**Stage 4 — the two-field editor (built).** The ingredient row's amount cell is now an **amount zone**:
a **quantity** field (the `ieCell` overlay — truncate-at-rest, expand-on-focus for long fallbacks) at
2.8rem + a **unit** field (`<input list="ie-units">`) at 4.5rem, then name (grows) + trailing controls.
The shared **`#ie-units` datalist** offers **measuring + size + count** suggestions (`tsp…kg`,
`small/medium/large`, `clove/sprig/…`), **flat-ordered** (measuring→size→count) because `<optgroup>`
isn't reliably rendered inside a datalist; suggestions only — **free-text still works**. **A3:** when the
unit is empty *and* the quantity is a whole-string fallback (letters/slash/plus — "pinch", "2 lb / 1 kg"),
the quantity **spans** the zone and the empty unit box is dropped; a bare number keeps the unit box (so a
unit can still be added). **On-save canonicalization:** `canonicalizeUnit` (reuses the scaler's
`UNIT_ABBREV` + lowercases) means the editor **shows and stores the short unit** ("tablespoons"→"tbsp");
reading already abbreviated, so no backfill and **no plural fold**; size/count words pass through
unchanged. **Wider edit mode:** `.page.recipe-view.editing` widens to **1000px** (reading stays 760px) so
names breathe; no width transition yet. **Icon-only link:** the unlinked control is the bare **🔗**
(tooltip + hover); the linked state keeps the pill. **Font-match:** the ingredient name is **15px**
(`--fs-amount`) in both reading and edit (size only — colours unchanged, so reading still differentiates
name vs. muted amount).

**Critical constraint held:** the scaler's **scaling/parsing logic is untouched** — only
`canonicalizeUnit` was added. Size/count words are **datalist suggestions only**, deliberately kept **out
of `MEASURE_UNIT_RE`/`_SCALE_UNITS`**, so the scaler keeps treating them as **counts** (round to whole on
scaling). Scaling+editing is **safe**: scale is display-only, and entering edit resets to 1× and binds to
the un-scaled originals (verified).

**The name→unit backfill (done).** ~272 existing rows carried a size/count descriptor **stuck in the
name** ("1 medium onion" → name "medium onion", unit empty). A standalone, idempotent data transform
(`scripts/backfill_name_unit.py`; backup → dry-run → `--apply`) moved the descriptor into the empty
**unit** field for the clean cases: **256 leading-single-descriptor** rows (+ optional "of": "Pinch of
salt" → unit "pinch", name "salt") and **16 size+count** rows where the **size is kept** ("large cloves
garlic" → unit "large cloves", name "garlic"). The recognizer declines (leaves the row alone) on
**hyphen-compound** ("medium-to-large"), **intrinsic** ("medium-grain rice"), and **empty/paren-only**
remainders. The `qty` recombine is **mandatory** — reading displays `qty`, not the `unit` column, so the
descriptor is written into `qty = quantity + " " + unit` ("1" → "1 medium") or it would vanish from the
ledger; `quantity`, `raw_text`, grams, and secondary_measure are left untouched. **7 rows were flagged
for manual handling** and not transformed: hyphen-compound (4054), pre-mangled/merged-import (2648,
5932), "or …" alternative (4597), and three empty/paren spice-cloves left as-is (2927, 4174, 7210).
Idempotent re-run = 0 rows; all invariants (`qty == quantity+" "+unit`) pass; scaler sanity confirmed the
moved words still scale as **counts** ("5 large cloves" ×2 → "10 large cloves").

**Architectural note — the recognizer is promotable.** `split_leading_descriptor(name)` is a **pure,
DB-free** function (plain string in, `(unit, name)`|`None` out — no sqlite/`conn`/`view`/row objects). It
was built that way **deliberately**: the intent is to **lift it verbatim into a shared import helper**
(alongside `import_cleanup.split_qty`) so future imports split descriptors **at import time**, rather than
relying on re-running this backfill. The backfill-only review policy (pre-mangled/alternative flagging,
the `KNOWN_MANGLED` force-flag) lives in the **caller**, not the recognizer, keeping the promotable core
clean. This is a recorded **follow-on** (its own diagnostic).

**Scaler constraint (held):** the moved descriptors go into `unit`/`qty` **only** and are still kept
**out** of `MEASURE_UNIT_RE`/`_SCALE_UNITS`, so the scaler keeps treating them as counts (round to whole).
The backfill neither touches nor imports the scaler.

**Remaining follow-ons:** (1) **import-integration** — promote `split_leading_descriptor` into the import
path so scraped lines split descriptors at import (its own diagnostic); (2) the deferred **66 trailing
count-noun rows** ("garlic cloves" — a trailing count, not a leading descriptor) are still out of scope.

**Heading detection improved + backfill (done).** Section headings arrive from Paprika as untagged text
lines (no structured marker), so detection is heuristic: `import_cleanup.is_section` promotes a no-amount
line that is **colon-terminated or ALL-CAPS**. Two low-risk patterns were being missed. **(1) Detector
fix (helps future imports):** a new `strip_emphasis(text)` drops a **matched leading+trailing emphasis
pair** wrapping the whole line (`**`/`__`/`*`/`_`, regex `^(\*\*|__|\*|_)(.+?)\1$`); `classify_line` now
tests `is_section(strip_emphasis(line))` and stores the **stripped** text, so a bold colon-heading
`**Other Ingredients:**` is both **detected** and **stored clean** (`Other Ingredients:`). The strip is a
**pre-step** — `is_section` is unchanged — and it's **heading-only**: `import_write` stores a heading's
`raw_text` from the clean text, while the ingredient path's "preserve the original line" contract
(`raw_text = line["raw"]`) is untouched (a trailing footnote like `salt*` or mid-line `**sifted**` has no
wrapping pair, so it's never altered). A corpus scan confirmed the change newly-detects **exactly 14**
rows and nothing else. **(2) Backfill (`scripts/backfill_headings.py`, backup→dry-run→`--apply`):**
promoted **32** existing `is_heading=0` rows to headings (canonical shape: `is_heading=1`, `raw_text` =
clean text, `label/quantity/unit/qty` NULL) — **18** "For the X"/"To finish" rows (already flagged
`suggest section` at import) + **14** palak markdown bold-colon headings (`**…:**` → colon, `**`
stripped). Idempotent re-run = 0.

**Design rationale — bias to "ingredient".** Heading detection deliberately errs toward *ingredient* when
ambiguous, because a wrongly-promoted heading makes a real ingredient **vanish from the list** (the
asymmetric-worse error). So the backfill promoted **only high-confidence patterns** (the `for/to`
suggestions + bold-colon) and **left ~11 ambiguous rows for manual review** via the editor heading-toggle:
the **2 "X Ingredients"** rows (7287, 7295 — title-case, no colon), the italic `_Vanilla Cream Cheese
Icing_` (3047), and the **section-word-ending** rows (`Chopped Parsley for Garnish`, `Fresh parsley for
garnish`, `Pecorino … for Garnish`, `Brown Butter-Cream Cheese Frosting`, …) — about half of which are
genuine ingredients, so a heuristic would eat them.

**Shared, not duplicated:** `strip_emphasis` lives in `import_cleanup` and is imported by both the
detector (import path) and the backfill, so they strip identically.

**Four detection rules — `section_signal` (done, follow-on).** Beyond the emphasis-strip, four
corpus-verified amount-less patterns were added as a **shared helper `section_signal(text)` =
`is_section(text)` OR** (1) **"X Ingredients"** — a whole-word `\bingredients?\b` meta-word naming the
list; (2) **unit-system label** — an exact whole-line `metric`/`imperial`/`us`/… (a units-variant block
header); (3) **"Day N"** — `^\W*day\s+\d` stage labels (e.g. sourdough `Day 1`/`Day 3+`); (4) a
**prep-component allowlist** `{egg wash, dredge, sponge, brine}`. `classify_line` block 3 swapped its
`is_section(stripped)` test for `section_signal(stripped)` (one line; still stores the stripped text).
The backfill promoted **9** existing rows (7287/7295 "…Ingredients", 3014 "Metric", 3768/3771 "Day N",
3022/3033 "Egg wash", 4199 "Flour Dredge", 5746 "Sponge"); idempotent re-run = 0.

**Architecture — a shared helper, NOT a change to `is_section`.** The rules live in `section_signal`, and
`is_section` stays the pure colon/ALL-CAPS predicate — **because `is_section` is also called by
`classify_step`**, and these rules were verified only for *ingredient* lines. Keeping them in
`section_signal` (called only from ingredient block 3) leaves step-parsing untouched. `section_signal` is
defined once in `import_cleanup` and imported by both the import detector and `backfill_headings.py`
(shared, not duplicated).

**The prep-vs-food distinction (why the allowlist is safe).** The corpus draws a clean line:
**preparations made *from* the ingredients below** (egg wash, dredge, sponge, brine — and
glaze/marinade/streusel) are **only ever section headers**, never themselves an ingredient → safe to
auto-detect when amount-less. **Foods that are also ingredients** (sauce, potatoes, salsa, meatballs,
dough, crust) **collide** with real-ingredient usage (amount-bearing *and* amount-less) → not
automatable, hand-toggle. Rule 4's allowlist is the **prep-only core**: the 5 words that overlap block
3b's `_COMMON_SECTION_WORDS` (filling/glaze/topping/marinade/streusel) were **dropped** — they're already
handled by `_is_section_candidate` (which has a ≤3-word guard this guard-less ends-in match lacks, so
"spread the filling evenly" can't wrongly promote).

**Importer intelligence.** Each verified rule is permanent importer knowledge (the state-of-the-art-
importer goal): a pattern harvested against the real corpus and confirmed false-positive-free under the
**asymmetric-bad guard** — a wrongly-promoted heading *hides* a real ingredient, so a rule ships only when
every amount-less match is provably a header.

**Remaining manual to-do (reconciled).** The 4 rules cleared the "X Ingredients" pair (7287/7295) and the
Day-N/Metric/prep rows from the earlier manual list. What's left for hand-toggle: the Pastina variant
labels (4965/4972), `Brown Butter-Cream Cheese Frosting` (5147), `Cheddar Mashed Potatoes` (5476), `Salsa`
(5530), `Meatballs` (5699), `Loaves` (5759), and the italic `_Vanilla Cream Cheese Icing_` (3047) — plus
`Spice Mix` (4799, leave as an ingredient) and the `Mix or Cajun seasoning` merge-fix (2650). All are the
prep-vs-food "food word" collisions or one-offs a heuristic would get wrong.

## Reading-mode polish (control-block restructure + small tweaks)

**Control-block restructure.** The recipe reading page's amount-scaling controls were regrouped:
**cook time + serves (stacked) and the scaler now sit together in a `.above-ing` block directly above
the Ingredients heading** (`scaleMetaBlock`), moved out of the top vitals strip — which now holds just
the title, the cook/rating block, and the edit/copy/delete strip. The scaler is a sibling of
`#ing-section` (so an ingredient rebuild can't wipe it); `#scaler-host` + `.serves-count` keep
live-rescaling on factor change. The `½×/1×/2×` pills render as fixed circles (custom× stays a wider
pill), with a `--border-defined` token for the "defined but soft" outline (reused by the next visual pass).

**`litre`→`liter` is display-only.** A `UNIT_ABBREV` rule in `scaler.js`
(`/\blit(?:re|er)s?\b/gi → "liter"`) normalizes the American spelling **at render** — stored values,
`MEASURE_UNIT_RE`, and `UNIT_TO_ML` are untouched (litre isn't a conversion key; the recognizer already
accepts both spellings), so it self-heals with no backfill. Display-only, JS-side, no `stepscale.py`
mirror.

**Removed two helper lines:** the "Tap any highlighted ingredient…" hint and the "~ = an estimate"
legend (plus the now-dead `approxNote`/`anyApprox` and `.grams-note`); the `~` marker stays on values.
Also: method text sized to match ingredients (15px), and a tighter ingredients↔method gap.

**"More defined" treatment + tokens.** A reading-page pass to lift the plainness, driven by a small
reusable token set: **`--border-defined` (#A19179)** — a "defined but soft" outline (crisper than
`--rule`, not heavy) — plus **`--fill-card` (#F4ECD9)** and **`--fill-surface` (#F6EFDF)** subtle warm
fills. Applied ("Treatment B") to the **cook-block card** (defined border + `--fill-card`), the
**edit-strip buttons** (`.owner-actions .btn`: defined border + `--fill-surface`; Delete keeps its red
text), and the **in-recipe sub-heading underlines** (`.ingredient-list`/`.steps` `li.group`). These are
the reusable "definition" tokens for future visual work.

**Three deliberate distinctions (do NOT "unify" these later):**

1. **Two-tier section headers** — the main **`INGREDIENTS` col-title keeps its green 2px underline**
   (`--green` structure accent); the **in-recipe sub-headings** get the quieter **taupe
   `--border-defined`** underline. Intentional hierarchy, not an inconsistency.
2. **The scaler is deliberately lighter and outline-only** — its circles + custom× pill use a dedicated
   **`--border-scaler` (#BBAD95, 1px)**, *lighter* than `--border-defined`, with **no fill**, so it
   reads as a distinct, quieter **interactive control** that steps back from the defined static surfaces
   (cards/buttons). It is *not* meant to match the B elements.
3. **Tags left original** — `.cat-tag` keeps its color-tinted/dashed treatment; the tags already carry
   their own definition (per-category tints), so the "defined" borders/fills were intentionally not
   applied to them.

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
- **Ingredient notes vs. the recipe note.** The recipe-level **note** (headnote) is this Stage-1
  `.ie-prose` field at the bottom. A **per-ingredient note** is separate: in edit mode it's the
  collapsed sticky-note icon / below-row field; in **reading** mode notes now render as a **distinct
  secondary annotation** — their own line **below** the ingredient (serif italic, muted, smaller,
  indented via `.inote`), replacing the previous inline string-concat. This is a **general change: it
  applies to every recipe's reading view** (linked, imported, and — newly visible — plain-row notes),
  routed through a single `readNote()`.
- **Description** is **full-width** in edit mode (the reading narrow-then-wide float is relaxed) — a
  rectangular textarea can't cleanly hug the tilted Polaroid, and a wide field is better to type in;
  it clears the photo via a masthead `min-height`.

**Stage 1 (built):** the **scalar / masthead fields** (title, author, source_url, category/tags,
servings, times, description, recipe-note).

**Stage 2 (built) — ingredients editable inline.** A **separate edit-mode path** in the ledger (not
the seed line-editor; mutually exclusive by `source`): edit qty / name / note, add & remove lines, add
& edit **section headings**, and **library-link / unlink**. Reuses the existing `PUT` — **backend
untouched except one fix** (plain-row notes now persist; see caveats). **Steps remain display-only**
(Stage 3); **reorder** is deferred to Stage 4 (the grip is a reserved "coming soon" affordance;
`position` already supports it).

- **Overlay value fields — why (not contenteditable).** Fields need to **truncate with "…" at rest**
  *and* **wrap taller on focus** (Option B). Tested: **no single form element does both** — a
  `<textarea>` ignores `text-overflow:ellipsis` (hard-clips, no "…"), and an `<input>` can't wrap.
  Contenteditable does both but was **rejected earlier** (paste-HTML / caret / mangling risk).
  Resolution: an **overlay** — a real `<textarea>` (the edit surface) with a plain display `<div>`
  (`.ie-disp`) that ellipsis-truncates the value at rest and hides on focus. This is **paste-safe by
  construction** (a textarea can't hold HTML) and **honors the earlier inputs-not-contenteditable
  decision**. Click-to-focus: the overlay's `mousedown` maps the click to a caret offset via
  **`caretPositionFromPoint`**, then focuses the textarea and sets the selection (a naive fall-through
  hit-tests the wrong, reflowed layout). Blur mirrors the textarea value back into the overlay.
- **Finalized layout (760px — decided AGAINST widening).** Compact one-line rows at rest: qty · name ·
  link · collapsed **sticky-note icon**; the **grip · icon+word heading-toggle · fenced red trash**
  cluster is **hidden, revealed on hover/focus** behind a divider (space reserved, so no shift). A
  **fixed qty column** + `align-items:start` + matched `line-height` keeps names aligned on the first
  line. A present note renders **on its own line below** the ingredient. The slim row fits at the
  reading width, so edit mode **stays 760px** (no widen → no toggle jump, no Polaroid slide, no new
  responsive floor).
- **Lossless heading-toggle (Option A1).** Heading text lives in a **dedicated `heading` field** (never
  shares `raw_text` with the name); ingredient fields (qty/label/note/link) stay **dormant** across a
  toggle, so a round-trip restores them exactly.
- **Discard-empties + refetch-canonical-after-save.** Save filters blank rows (`nonEmptyRows`) from the
  payload; after a successful PUT the client **re-fetches canonical state** rather than adopting the
  draft. Why: Stage 1 could set `view.data = view.draft` because the draft shape *was* the data shape —
  Stage 2 **diverges** the shape (dedicated `heading`, `label`-as-name, transient `_noteOpen`), so
  adopting the unfiltered draft would leave blanks and shape drift; a refetch is the source of truth.
- **Keyboard.** In an ingredient field, **Enter commits + closes** (value is already buffered
  continuously; just blur — no newline) and **Esc reverts** the field to its **focus-time snapshot**
  and closes.

Pure row transforms (toggle / heading-text / nonEmptyRows / writeIngField) live in
`static/ingredient-row.js` (dual-export like `scaler.js`), unit-tested in node. **Backend** — the
existing `PUT /api/recipes/<id>` full-replaces rows and preserves harvested grams for unchanged lines.

This is the **"edit the canonical recipe"** path — distinct from the R2 **handwritten annotation
layer** (struck-print + hand color) and from the seed-only per-person change model (see the
architectural tension above).

## The social feed — composed page design (LOCKED)

The visual + interaction spec for the social feed ("Cooking") page. Locked after **~8 preview rounds**;
a new chat should **build to this, not re-derive it**. The values behind it (connection-not-consumption,
no-counts, failure-acceptance, achievements) live in
[product-vision.md](product-vision.md); this section is the **design** those values render as. It
belongs to the same **"used cookbook"** direction — warm, inhabited, hand-touched — extended from the
single-recipe page to a full app surface.

### Composed, inhabited page (not a bare list)

A **four-zone composed page**, not a lonely centered column:

- **Masthead** (top) — brand + identity.
- **LEFT — nav / identity:** **Box** (all recipes) · **Cooking** (the feed — sub "what friends made") ·
  **Friends** (your circle) · **Profile** (your chef-page — `SOON`).
- **CENTER — the feed** (see post design below).
- **RIGHT — warm cooking-context:** **Your Friends** · **Want-to-make** (`SOON`) · **In Season** (status
  TBD) · **Cook-it-again** (`SOON`) — all **utility / connection / identity**, **ZERO engagement-pull**.

…all on a **warm surface**. The move: take the **structure / inhabited-ness** of early social feeds but
**reject their engagement machinery** — no Requests, no Birthdays, no Trending, no People-You-May-Know,
no ads, no notifications. The surround is context and utility, never a hook.

- **TITLE:** the feed's heading is **"What's cooking?"** (warm double-meaning); the nav entry is the
  shorter **"Cooking."**

### Color — green carries real weight ("G2")

The fix for "too plain / monochromatic tan": **green (`--green` #4E4B24) carries real weight, not just
accents on a tan field.** Within the **existing palette only** (green + terracotta + ink + cream — **no
new colors**):

- A **solid green left-nav** (soft/lightened — **not** too dark).
- **FILLED, alternating green/terracotta context-card headers** — Your Friends + In Season **green**;
  Want-to-make + Cook-it-again **terracotta**.
- A **deeper sage surface** framing the **cream** feed board.
- Green + terracotta + ink used **generously**, while content still **reads clearly**.

This is connection-not-consumption made **visually warm and alive** — the warmth is chromatic, not
manufactured engagement. (Preview levels ran G1 → G2 → G3; **G2 is the locked target** — soften the
green from the first G2 pass so the nav isn't too dark.)

### Type — Kalam is the app's "personal hand"

**The handwritten font is Kalam** (a design-system decision, **replacing Caveat**). Bundled
**self-hosted woff2** (like Inter/Caveat), and it is the **`--font-hand` primary**. Two roles, both
chosen for Kalam because it is **legible *and* warm**:

- **Now:** feed **captions**.
- **Later:** THE font for the **"your changes / annotations on a recipe" personal layer** — the
  used-cookbook marginalia, whose eventual target is **struck-through-original + handwritten-replacement**
  rendering (the R2 handwritten-edit treatment above).

### Feed post

- **CONSISTENT treatment across ALL posts** — **one** card design. The **only** differences: (a) photo
  present vs absent, (b) accent color. **No** different card shapes, no notecard-ruled-lines on some.
- **ACCENT BAR + LABEL:** a colored **left-edge bar** + a small **tracked-Inter chip** —
  **COOKED = terracotta** (`--hand`), **SHARED** (a recipe) **= green** (`--green`). Bar **+** label (not
  bar alone) so a newcomer can read the distinction.
- **CAPTION:** Kalam, **no quotation marks**, **150-char** limit.
- **FULL NAMES** everywhere (first + last, e.g. "Andy Hannah").
- **IDENTIFY YOUR OWN POSTS:** your own shares are distinguishable **at a glance** from friends' (a
  subtle "you" / mine marker + warm tint) — it's *your* feed.
- **BOUNDED / FINITE:** newest-first, a **recent window + cap**, **no** load-more / infinite-scroll, and
  **no count / tally** at the end — **it just ends** (per no-counts).

### Comments UI

- **PLAIN INTER, not Kalam.** The hierarchy: **handwriting = the sharer's personal voice** (the caption);
  **plain = the conversation.** (Kalam-everything read too busy.)
- Under the post: commenter **full name** (Inter bold) + comment (Inter) + timestamp — clean; an
  intentional **"Say something"** reply input; **lightweight when there are no comments** (bare posts stay
  calm).
- **No like button, no comment-count.** **300-char** comment limit. **Delete-own** + **post-owner-remove**.

### Chef-hat avatar (note)

Friend / identity avatars are a **chef-hat mark** (warm "these are cooks"; real profile photos come later
with the upload stage). The **characterful hand-drawn hat is a DEDICATED later task** — AI-generated SVG
produced stiff/generic icons (and a displacement-wobble pass got closer but still clustered); it likely
needs an **illustrator**, working from **style reference only — original art, no tracing stock**.
**SHIP NOW with a SIMPLE placeholder** (a clean hat or initials): the real mark is polish, **not on the
critical path**.

### Built result — sub-stage 2b (shipped, commit `03d881b`)

The composed **"Cooking"** page is **built to this spec** and merged. A few **deliberate** deviations from
the locked spec — recorded so future work reads them as **decisions, not bugs**:

- **Caption cap is 150 chars CLIENT-side** (the server allows 280) — the client enforces the locked
  **150** ceiling; the wider server limit is headroom, not the product rule.
- **Avatar is a SIMPLE placeholder chef-hat** (inline SVG, `currentColor`) — no initials fallback was
  needed in practice. The **characterful hand-drawn mark stays the deferred dedicated design task**
  (see the note above).
- **Friends nav entry is PRESENT BUT INERT** — the friends-management page is **out of 2b scope**
  (deferred); the entry holds its place in the composed layout without a destination yet.
- **In Season ships REAL** (`GET /api/in-season`); **Profile / Want-to-make / Cook-it-again** are honest
  **`SOON`** slots — present in the surround for structure, no live data behind them yet.

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
- **Overlay ingredient fields** depend on **`field-sizing: content`** (same class as the meta fields)
  for the on-focus auto-grow, and on **`caretPositionFromPoint`/`caretRangeFromPoint`** for the
  click→caret mapping on the display overlay — both fine for this local single-user app.
- **Plain-row notes now persist:** the backend plain-row INSERT writes the `note` column (it already
  existed) and `ingToPayload`'s plain branch sends `note`. Previously only *linked* rows saved a note.
- **The ingredient `SELECT` is `SELECT *`** (app.py), so the added `quantity`/`unit` columns now appear
  in the recipe GET response. Harmless — the client reads only `qty` for display/scaling and ignores
  them — but noted so it's a conscious surface (and because a future column add is likewise auto-exposed).
- **The old form-edit button was removed** from the recipe controls (`ownerActionsHTML`), superseded by
  the inline **✎ Edit** path. The `#/edit` route + `renderForm`/`onSaveForm` are **retained** — still used
  by create (`#/new`) and the **add-a-photo** affordance. **Accepted gap:** no in-app entry point edits an
  *already-set* image path until photo-upload ships (the inline editor excludes `image` by design;
  add-a-photo only appears when there's no image). Existing image paths are untouched and round-trip on
  inline save, and `#/edit` still works by hand.
- **The Custom scaler pill is shape-by-state.** In the scaler row (½× · 1× · 2× preset circles · Custom),
  Custom now reads as a member of the round row rather than a stray oval: **REST** = a 42px "×" circle (a
  quiet round sibling of the presets); **WIDEN-ON-FOCUS** = a compact centered outline stadium pill (room
  to type — brown is *withheld* mid-entry because brown means "committed"); **BROWN-ON-COMMIT** = the
  filled pill via the existing `!isPreset` flag + a mirrored `.scale-custom.on` rule (the preset selected
  rule `.scale-control button.on` is element-scoped to `<button>` and won't reach an `<input>`, so Custom
  needs its own rule — same tokens, no new colors). The widen is **pure CSS `:focus`** (no JS shape toggle,
  doesn't touch the fiddly focus-strip handler), and the committed pill renders from the host rebuild's
  `!isPreset` branch so it **survives `rerenderScaler`**. The `.scale-custom:focus` rule is deliberately
  ordered *after* `.scale-custom.on` so re-editing a committed value reads outline, not brown. Scaler math
  (`scaler.js` / `stepscale.py` / `view.scale`) untouched. **Deferred:** whether a typed custom value
  should *persist* when switching to a preset (today it's cleared, since `customVal` derives from
  `view.scale`) — its own decision, to be taken with the queued "restore prior scale on exit" polish (same
  concern); not decided here.
- **The recipe page carries the feed's desk texture behind the card.** The single-recipe page now paints
  the FEED's surface — feed-exact gradient `#B9B191 → #A7A07E` + the feed's `.13` linen `::before`
  (`feTurbulence`, `mix-blend-mode: multiply`), mirrored verbatim from `.feed-view.page` /
  `.feed-view.page::before` — **behind** the reading card. It's route-scoped via a `body.recipe-bg` class
  the router toggles with a single `classList.toggle("recipe-bg", !!mRecipe)` that recomputes on every
  hash change, so the desk **never bleeds** to home or the create/edit forms (class removed on leave). The
  reading card (`.page.recipe-view`, the warm-paper "page-as-object") is **UNCHANGED** — background-only;
  the recipe-page/card redesign (cream board + mat-frame, as explored in preview) remains a **separate
  parked pass**. Two deliberate body-vs-page adaptations (the feed paints on a sized page element; here the
  target is the shared `body`): `position: relative` (anchors the absolute `::before`) and
  `min-height: 100vh` (keeps the desk full-viewport behind a short recipe). Content sits above the desk via
  a `z-index: 1` lift on the reading card (see the fix note below).
  - **Fix — the lift was over-broad (`> *` → `> #app`).** As first shipped (3654de7), the lift was
    `body.recipe-bg > * { position: relative; z-index: 1 }`, which matches **every** body-level child. Its
    specificity (0,1,1) beats the body-level **fixed overlays** — `.backdate-modal` / `.scrim` / `.panel`
    (each 0,1,0) — so on a recipe page it **clobbered their `position: fixed`** to `relative`: the
    "Log a past cook" modal dropped out of the viewport into document flow at the page bottom (its open
    `.focus()` then scrolled to it), the scrim backdrop collapsed, and the field-guide drawer mispositioned.
    Narrowed to **`body.recipe-bg > #app`** (the reading-card container; the back-link lives inside `#app`,
    so it stays lifted) — the overlays keep their own `position: fixed` + `z-index` (40/50, already above the
    desk `::before` at `z-index: 0`), so they position correctly again while the desk still renders behind
    the card. One-selector CSS fix; the modal/scrim/drawer CSS was already correct and untouched.
- **Resize core extracted to a shared `images.py` (photo uploader, Stage 1).** The image-resize logic —
  open → EXIF-orient → convert to a JPEG-safe mode → downscale the long edge to 1600 (never upscale,
  LANCZOS) → JPEG q85 — was lifted verbatim out of `scripts/backfill_photos.py::process_photo` into a
  root-level shared "brain" module `images.py::resize_image_bytes(raw_bytes) -> bytes` (the `weights.py` /
  `split_qty` shared-helper pattern), so the in-app **photo uploader (later stages) reuses the exact same
  resize** rather than reimplementing it. `process_photo` is now a thin wrapper (b64-decode → shared core →
  recompute reported dims); `LONG_EDGE`/`JPEG_QUALITY` live in `images.py` as the single source of truth.
  **Pillow promoted from dev-only to a runtime dependency** (`requirements.txt`, `pillow>=11`, resolving to
  the same 12.2.0 CI installed before) since it's now imported by an app-shared module. **Scope of proof:**
  the extraction is verified behavior-preserving by **dimension + contract equivalence** (`tests/test_images.py`
  — oversized→1600, small→not-upscaled, non-RGB→RGB, EXIF-oriented; plus `process_photo` still returns
  `(jpeg_bytes, orig, new)` with the same dims for both the resized and not-resized branches) **and by the
  moved code being verbatim — NOT** by a byte-for-byte golden-output comparison against the pre-extraction
  bytes (overkill for a transparent refactor; the observable contract is dimension/shape, not byte identity).
  This module is the seam Stage 2's `save_image()` and the upload endpoint will call.
- **Photo upload — the `save_image()` seam + owner-checked endpoint (Stage 2).** `POST /api/recipes/<id>/image`
  (multipart, field `image`) resizes + stores a dish photo and updates `recipes.image`. Storage lives behind
  a single seam, `images.save_image(bytes, *, slug) -> "images/<slug>.jpg"` — the **only** disk-writing
  boundary, so a later swap to object storage is one contained change (callers see only the returned path;
  the app.py handler does no direct file I/O). **Authorization:** owner-checked (`rec.owner != current_user.id`
  → 403), mirroring the shares gate — deliberately **stronger** than the sibling `PUT`/`DELETE`, which still
  gate on source-tier only (`EDITABLE_SOURCES`) with **no owner check** — a **pre-existing authorization gap,
  recorded here as a follow-up, not fixed in this stage.** Endpoint is login-gated by `before_request` (NOT in
  `PUBLIC_ENDPOINTS`); the response carries **only** the new path (least-exposure). **Input hardening** (first
  endpoint to write user bytes to disk): S1 filename is **entirely server-derived** (`<rec.id>.jpg`; the client
  filename is never read) with an `is_relative_to(IMAGES_DIR)` containment check — *the stored name derives
  from `rec.id`, and that containment guard is what keeps the scheme safe even if recipe-id formats ever change
  to include path characters (live defense, not dead belt-and-suspenders)*; S2 `Image.MAX_IMAGE_PIXELS` cap
  (40 MP) + decompression-bomb error/warning caught → 400; S3 format allowlist `{JPEG,PNG,WEBP}` by Pillow
  **decode** (never Content-Type/filename); S4 EXIF/GPS **stripped** by the re-encode (orientation applied
  first, then dropped — output is served from a public route); S6 **atomic** temp-write + `os.replace`, DB
  updated only after the file lands; S7 `MAX_CONTENT_LENGTH` 10 MB → 413 before decode. **S5 — recorded, not
  fixed:** `/images/<file>` is a **PUBLIC** route, so uploaded photos are world-readable by a guessable URL
  with no owner-check on READ — acceptable for the current local/single-user app, a **multi-user follow-up**
  (a private recipe's photo must not be publicly fetchable — same shape as the `get_recipe` raw-owner
  over-exposure). **Test isolation:** the upload writes files, so `make_kitchen` rebinds `images.IMAGES_DIR`
  to a temp dir (the filesystem analog of the `app.DB` redirect) — the real `static/images/` is never touched.
  UI (the two entry-point hooks) is Stage 3, preview-first.
- **HEIC/HEIF input (Stage 2 follow-up).** The uploader now accepts iPhone/Photos HEIC via `pillow-heif`
  (`register_heif_opener()` in `images.py`, at **module import** so every decode path — upload + backfill —
  gains it). `"HEIF"` added to `ALLOWED_INPUT_FORMATS` — that is the format id a decoded HEIC actually
  reports (confirmed by decoding a real HEIC; there is **no** `"HEIC"` id, and pillow-heif reports `"HEIF"`
  for the whole family, `.heic` and `.heif` alike). **Output is still JPEG** — HEIC is input-only; the
  existing resize/EXIF-strip pipeline re-encodes it unchanged, so everything downstream (resize, GPS strip,
  atomic write, the stored `images/<slug>.jpg` path) is untouched. Added because iPhone/Photos default to
  HEIC. The patent-encumbered HEVC codec is acceptable for this **local/personal** app — libheif ships
  bundled in pillow-heif's manylinux wheels (the CI install step to watch); **revisit licensing at
  commercialization.** Proven by generated-HEIC tests (`format=="HEIF"`, HEIC→JPEG through the core, the
  endpoint happy path, GPS strip from an HEIC source) **and a committed REAL iPhone HEIC**
  (`tests/fixtures/IMG_5424.heic` — HEVC-encoded, 3024×4032, real device EXIF) driven through the endpoint
  in `test_real_iphone_heic_upload_success`, plus a live-DB sanity (real file → 200, 12 MP → 1200×1600
  JPEG, all EXIF stripped). Real-device HEVC/EXIF quirks are thus confirmed end-to-end in CI, not just synthetic.
- **Empty-Polaroid photo upload from the recipe page (Stage 3, part 1).** The empty "+ add a photo"
  Polaroid — previously an `<a href="#/edit">` link — is now a real **drag-drop + click-to-pick** upload
  zone wired to the shipped, HEIC-capable `POST /api/recipes/<slug>/image`. One zone handles both a hidden
  `<input type=file accept=image/*>` (click/keyboard) and `dragenter/over/leave/drop`; on drop-or-pick it
  reads the `File` and POSTs multipart `image`. On **200** it re-pulls via `renderRecipe(slug)` (the
  established post-mutation re-pull + full repaint — `slug == recipe id`, the same key the POST and the
  refetch use) so the actual stored path (server-returned, never client-constructed) fills the **real**
  Polaroid — the clean uploading→filled transition Andy verified (no drop-zone flash / spinner residue /
  double-render). **The Polaroid/clip display is unchanged** — only the empty-state affordance + new
  upload-state styles (rest/drag-over/uploading/error) were added; the filled branch and its `onerror`
  graceful-degradation are untouched. Gated on the existing `is_editable` (no new client owner check); the
  `#/edit` route stays live (router-handled) and the ✎ Edit button is the unchanged edit entry, so nothing
  is orphaned. **File-handoff guard:** if no usable `File` arrives (macOS Photos can hand a reference, not
  bytes), the zone **no-ops gracefully back to REST** — never errors/hangs; click-to-pick is the
  always-works fallback. **Errors stay contained in-frame** (413 "Too large"; 400 "Not an image file";
  other "Upload failed") with "Try again" → REST, and **never blank the page**; the status→message mapping
  is a pure `static/upload-status.js` helper with a JS unit test. Coverage honesty: 400/not-an-image was
  browser-verified; 413/too-large and 403/ownership ride on Stage 2's backend endpoint tests (not manually
  re-forced). **Queued/parked (decisions):** "Update photo" hover on a *filled* Polaroid = **part 2** (next);
  per-cook photo **album** (several photos per cook → its own table; auto-becomes-hero-if-none, opt-in
  "make this the hero" otherwise) = **Stage 4**; mobile **long-press** to reveal "Update photo" = deferred
  to the mobile pass; **drag-from-Apple-Photos** confirmed working on Andy's machine (with the `!file`
  no-op as the fallback if Photos ever hands a reference).
- **Replace an existing photo — "Update photo" hover-reveal (Stage 3, part 2).** On a FILLED editable
  Polaroid, hover reveals a subtle "Update photo" pill (clean photo at rest); click it or drop an image on
  the photo to replace via the **SAME upload path as part 1** — `wirePhotoUpload` now drives both the empty
  (add) and filled (replace) cases off **one implementation** selected by a `filled` flag: the `send()`
  core (FormData POST → `renderRecipe(slug)` re-pull+repaint), the `!file` graceful no-op, `upload-status.js`,
  and the drag/drop + picker wiring are identical; only the three state-painters differ. **Failed update
  preserves the existing photo** (the load-bearing rule): the filled painters never touch the live `<img>` —
  `uploading`/`fail` insert a `.photo-overlay` (dim "replacing…" / a light error panel) and `rest`/"Try again"
  remove it, so an error can never blank or break the Polaroid — the recovery target is **context-aware**
  (empty → the empty zone; filled → the still-present original photo). Browser-verified: a non-image dropped
  on a filled photo surfaced the error and "Try again" returned to the ORIGINAL photo intact. **Stale-cache:**
  deterministic `<slug>.jpg` naming means a replace overwrites the same URL, but the immediate swap showed the
  NEW photo (the full re-pull + repaint sufficed) — **no `?v=` cache-bust needed**. Display unchanged: only
  the hover affordance + reused wiring were added; `.polaroid`/`.clip`/`.photo` base rules and the `<img>`
  onerror degradation are untouched. **Parked (decisions):** mobile **long-press** to reveal "Update photo"
  (touch has no hover) = deferred to the mobile pass; per-cook photo **album** (several photos per cook →
  own table, auto-hero-if-none / opt-in promote) = **Stage 4**.

## Derived "to make" — the Uncooked box mark (Build 1)

"To make" is a DERIVED status, not an explicit list: a recipe is to-make iff
`owner == current_user && cook_count == 0`. There is no control, no bookmark, no stored
flag — nothing to click. On the box card, an owned never-cooked recipe fills the otherwise
empty `.rc-stats` slot with a quiet **"Uncooked"** whisper (direction **B-plus**, chosen over
pure-absence in `preview/to-make-b.html`): the dashed muted-olive status idiom (`.cat-tag.status`
register, tinted `--green`), serif tracked caps, lightest legible weight — serif confirmed by eye,
no font swap. Purely client-derived (`static/tomake.js::isToMake`, unit-tested); the payload already
carried `is_mine` + `cook_count`, so no server change. **Deliberately NOT a category tag** — routing
it through `TAG_CATEGORY`/`tagsHTML` would reopen the free-type "To Make" re-entry footgun; keeping it
derived is the whole point.

**Corollary (expected, not a defect):** the mark — and Build 2's page/filter — are computed correctly
but **invisible on any session not logged in as the corpus owner (users id 1)**, because `is_mine`
is false for everyone else. They light up once rescoping wires login→ownership.

### Parked — decisions, not omissions

- **Box-page redo** — deferred to its own preview-first pass; this build only adds the mark.
- **`#/to-make` page + "haven't made" filter** — Build 2, next.
- **`get_recipe` raw-owner over-exposure** — the single-recipe payload returns the raw `owner` id
  (unlike the list, which pops it to `is_mine`); a SECURITY.md least-exposure follow-up.
- **Access-control / multi-user rescoping map** — the current single-user access model, the two deferred
  gaps (recipe-write ownership; public `/images`), and the coherent multi-user rescoping project are
  mapped in [`SECURITY.md`](SECURITY.md) ("Access-control model" section) — the blueprint for the eventual
  auth/visibility pass.
- **Free-text "To Make"/"status" tag re-entry footgun** — the vestigial `TAG_CATEGORY` "status"
  entries (app.js ~616) are left INERT (0 recipes carry the tag in data); cleaned up later.
- **Queue plumbing + `is_queued`** — left DORMANT: `recipe_queue`, `/api/queue`, `RecipeQueue`,
  migration 024, the Alembic queue revision, and the `is_queued` read flag stay on disk, not rolled
  back and not read by any client. A separate derived mark was added; `is_queued` was not repointed.
- **Two-Andys hazard** — users id 2 (`test@test.com`) has `display_name` "Andy Hannah", colliding
  with the real corpus owner id 1 (`andyhannah2014@gmail.com`, `display_name` NULL). The corpus is
  dormant on any session that isn't id 1. Clean up the account/fixtures during the multi-user
  rescoping — flagged, not fixed here. **Resolution (this pass): log in as id 1; do NOT re-own the
  corpus** — re-owning 298 rows to chase a session mismatch moves data to the wrong account
  backwards. Re-owning is only correct if the daily login is deliberately not id 1, which it isn't.

## Cook-photo album (Stage 4) — the foundation table (Build 1)

A per-cook photo album: several photos per cook, accumulating into a scrollable **per-recipe** album
that sits BESIDE the single hero (`recipes.image` unchanged). Build 1 is schema only — the
`cook_photos` table + `CookPhoto` ORM model + dual-source migration (SQLite `migrations/025` + Alembic
`f5a6b7c8d9e0`, `down_revision` the recipe_queue head); the `save_cook_photo` helper and the
attach/promote/caption endpoints are **Build 2**, the album UI (preview-first) is **Build 3**.

**Table shape** (`cook_photos`, one row per photo):

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | surrogate; a photo is first-class, no natural key |
| `cook_log_id` | INTEGER NOT NULL → cook_log(id) **ON DELETE CASCADE** | the cook this photo belongs to |
| `recipe_id` | TEXT NOT NULL → recipes(id) **ON DELETE CASCADE** | **DENORMALIZED** (see below) |
| `user_id` | INTEGER NOT NULL → users(id), no cascade | interim multi-user-shaped rule |
| `path` | TEXT NOT NULL | stored image path (Build 2 fills via save_cook_photo) |
| `caption` | TEXT **nullable** | optional; ~100-char cap enforced in Build 2/UI |
| `added_at` | TEXT NOT NULL | `now_utc()`, set in code |

Indexes: `idx_cook_photos_recipe` (recipe_id) + `idx_cook_photos_cook_log` (cook_log_id).

- **Denormalized `recipe_id`** — the album view is *"all photos across all this recipe's cooks"*, so
  carrying `recipe_id` makes it a single indexed `WHERE recipe_id = ?` instead of a join through
  `cook_log` (the `shared_posts` idiom of carrying both keys). Its own `ON DELETE CASCADE` keeps it
  consistent when a recipe is deleted.
- **`user_id` from day one** — single-user now, but a new table gets the multi-user-shaped column free
  (set to `current_user` at insert in Build 2), so no rescoping debt is added. Reference FK (no cascade),
  matching `owner` / `cook_log.user_id` / `recipe_queue.user_id`.
- **`added_at` code-set `now_utc()` TEXT (no DB default)** — the deliberate `recipe_queue` /
  `shared_posts` / `comments` convention that dodges the SQLite `datetime('now')` vs Postgres
  default-expression divergence (chosen over a DB default on purpose).
- **Purely additive** — new table only; `cook_log` and `recipes` are untouched, and a new table starts
  empty so there is **no backfill**.

### Locked Stage-4 decisions (implemented in later builds — recorded so they aren't re-litigated)

- **Hero promote = POINT / linked** — a cook photo becomes the hero (auto if the recipe has none, else
  opt-in "make this the hero") by pointing `recipes.image` at the cook photo's OWN path (one file,
  shared), NOT a byte-copy. *(Build 2.)*
- **Cook-photo naming** — `images/cooks/<photo_id>.jpg` (per-photo id under an `images/cooks/`
  subdir), distinct from the hero's `images/<slug>.jpg` so several photos per cook never collide and
  never overwrite the hero. *(Build 2.)*
- **Caption** — optional, ~100-char cap (enforced in Build 2/UI; the column is just nullable TEXT here).
- **Date display** — each album photo shows its cook's full date.
- **`save_cook_photo` sibling** — a sibling of `save_image()` sharing the resize/validate/atomic-write
  core, writing to the `images/cooks/` destination — NOT a `dest` param bolted onto `save_image`. *(Build 2.)*

### ⚠️ Build-2 requirement recorded at the foundation — CASCADE-clears the hero too

Both FKs are `ON DELETE CASCADE`, so a `cook_photo` row can vanish **two** ways: (a) an explicit delete
(Build 2), OR (b) a **cascade** when its `cook_log` (undo-cook) or `recipes` row is deleted. Because the
hero is POINT/linked — `recipes.image` may point at a cook photo's path — **Build 2's hero-clearing
logic must handle the cascade path, not only the explicit-delete path**: if the photo that vanished (by
cascade) was the current hero, `recipes.image` must be cleared, or it dangles. (Undo-cook deletes a
`cook_log` row → cascades its photos → one of them might be the hero.) This is the direct consequence of
choosing POINT over COPY, flagged now so Build 2 doesn't ship a delete path that only covers case (a).

### Build 2a — the image-layer seams + `cook_log_id` nullable (shipped)

Build 2 is staged **2a (image-layer seams + schema) → 2b (attach/caption endpoints) → 2c (promote +
POINT/linked-hero deletion logic)**. Build 2a lays the foundation, **no endpoints/UI** (`app.py` and
`static/` untouched):

- **`images.save_cook_photo(file_bytes)` → `"images/cooks/<uuid>.jpg"`** — a sibling of `save_image`
  that **shares its internals byte-for-byte** (`_validate` + `resize_image_bytes` + `_atomic_write`), so
  validation (format allowlist, decompression-bomb guard), resize (long-edge 1600, EXIF/GPS strip,
  JPEG q85), and the atomic write are identical to the hero. The **only** differences: the name is a
  **server-minted `uuid4` hex** (never a client value or the recipe slug) and it lands in an
  **`images/cooks/` subdir** — so several photos per cook never collide and never overwrite the hero
  `images/<slug>.jpg`. `_atomic_write` mkdirs `cooks/` for free. No DB interaction (2b writes the row).
  *(uuid chosen over `<row-id>` to avoid the insert-then-rename ordering dance — the name needs no DB
  round-trip.)*
- **`images.delete_image(path)` — the FIRST file-deletion seam.** Takes a stored relative path
  (`images/…`), resolves it under `IMAGES_DIR`, **containment-checks** it is inside (refuses otherwise —
  never unlinks outside the images dir, mirroring `save_image`'s `is_relative_to` discipline), and
  `unlink(missing_ok=True)` so a missing/already-deleted file is a **clean idempotent no-op**. Returns
  `True` iff a file was removed. This is the seam **2c** uses for both cook-photo deletion **and** the
  hero-orphan cleanup (the CASCADE-clears-the-hero requirement above). Swap its body for object-storage
  deletion later, alongside `save_image`/`save_cook_photo`.
- **`cook_photos.cook_log_id` is now NULLABLE** (migration 026 + Alembic `a7b8c9d0e1f2`) — a photo may
  be **attached to a cook** *or* **stand alone in the album** (no cook, no date). It shipped `NOT NULL`
  in 025, so 026 makes it nullable: SQLite can't drop `NOT NULL` in place, so it **rebuilds the table**
  (the `019_ratings_composite_pk` / `005` pattern: new table → `INSERT…SELECT` → drop → rename →
  recreate the two indexes; empty today, nothing FKs into it, safe with FKs on), while the Alembic half
  does a trivial in-place `ALTER COLUMN … DROP NOT NULL` for Postgres. **Never edited the shipped 025 —
  additive follow-up migration**, per the repo convention.

**Still to come:** **2b** adds the attach (log-time + later) + caption endpoints (cook-owner gated);
**2c** adds promote-to-hero (recipe-owner gated) + the POINT/linked-hero **deletion** logic that clears
`recipes.image` on both the explicit-delete and the CASCADE paths (via `delete_image`), plus the
optional hero-orphan fix.

### Build 2b — the attach / caption / delete endpoints (shipped)

The cook-photo CRUD over `cook_photos`, reusing the 2a seams (`save_cook_photo` for the file,
`delete_image` for removal), the `CookPhoto` model, and the hero endpoint's owner-check idiom. **No
promote-to-hero and no `recipes.image` write anywhere** — that's 2c.

- **`POST /api/recipes/<rid>/photos`** (multipart `image`, optional form `cook_log_id` + `caption`) —
  **one endpoint, optional cook**: a `cook_log_id` attaches the photo to that cook; omitting it makes a
  **standalone album photo** (`cook_log_id` NULL, the reason 2a made the column nullable). Returns **201
  Created** with the created photo `{id, path, caption, cook_log_id, cooked_on}` (the cook's date is
  echoed only for a cook-linked photo). 201 is the deliberate choice (a new resource — consistent with
  create/copy/queue/comment), distinct from the hero endpoint's 200 (which *updates* a recipe field).
- **`PATCH /api/photos/<id>`** (JSON `{caption}`) — edit the caption; a blank/absent caption **clears**
  it. Returns the updated caption. (First PATCH route in the app.)
- **`DELETE /api/photos/<id>`** — remove the row then the file (`delete_image`, idempotent). **2b scope:
  no hero-clear** — since promote is 2c, no cook photo can be the hero yet, so a 2b delete cannot orphan
  one; 2c adds the hero-clear when it adds promote.
- **Owner-split gating** (the deliberate asymmetry): **attach-to-a-cook** gates on the **cook** owner
  (`cook_log.user_id == current_user`, and the cook must belong to this recipe) — so you can photograph
  **your own cook of anyone's recipe**; **attach-standalone** gates on the **recipe** owner
  (`rec.owner == current_user`) — a standalone photo attaches to the recipe itself, so it's the recipe
  owner's call; **caption/delete** gate on the **photo** owner (`cook_photo.user_id`). Missing → 404,
  not-yours → 403 (the hero 404-then-403 pattern).
- **Caption cap** — `COOK_PHOTO_CAPTION_MAX = 100`, **400 on over-length** (not silent truncation),
  factored into `clean_caption`, mirroring `create_share`'s `CAPTION_MAX` idiom so attach and
  caption-edit enforce it identically.
- **`log_cook` + `cooked-and-rated` now return the new `cook_log_id`** (additive, alongside the existing
  stats) — the at-log-time attach hook, so the client can attach a photo to the cook it just logged.
  Logging and photo-attach stay **separate actions**.

**Still to come:** **2c** — promote-to-hero + the POINT/linked-hero deletion logic (both paths) as above.
**Build 3** — the album UI (preview-first).

### Build 2c — promote-to-hero + POINT/linked-hero deletion (shipped — COMPLETES the album backend)

The POINT/linked-hero model wired end-to-end. The hero (`recipes.image`) may point at a cook photo's
**own** file (they SHARE it — no copy), so every way a cook photo can vanish must keep the hero honest.

- **`POST /api/photos/<id>/promote`** — "make this the hero": sets `recipes.image = photo.path` (the
  `images/cooks/<uuid>.jpg` path — POINT/linked, no file copy), via the same `update(Recipe).values(image=)`
  the hero upload uses. Gated on the **recipe owner** (writing `recipes.image` is the recipe owner's call,
  even when the photo/cook is yours). Returns the new hero path.
- **Auto-promote-if-none** (in the 2b attach flow): when a photo is attached and the recipe has **no**
  hero, it auto-becomes the hero — but **only when you own the recipe** (the no-hijack guard:
  `not rec.image and rec.owner == current_user`), so photographing your cook of a friend's hero-less
  recipe never sets their hero. The attach response carries `is_hero`.
- **Linked-hero CLEAR on all three removal paths** — "is this the hero?" is a **path comparison**
  (`recipes.image == photo.path`), applied consistently via `clear_hero_if_matches`:
  - **explicit delete** (`DELETE /api/photos/<id>`) — clears the hero iff this photo is it (deleting a
    NON-hero photo leaves it untouched), then deletes the row + unlinks the file.
  - **`undo_cook` cascade** — the recipe SURVIVES, so gather the cook's photo paths BEFORE the
    `delete(CookLog)` (which cascade-deletes the `cook_photos` rows), clear the hero if matched
    in-transaction, commit, then unlink the files.
  - **`delete_recipe` cascade** — the recipe row is gone (no hero-clear needed); gather all cook-photo
    paths **+ the hero's own file** before delete, commit, then unlink.
  Structure everywhere: **gather-before → delete → unlink-after-commit**, so a failed delete never
  unlinks files and the cascade has run before cleanup.
- **Hero-orphan fix** (folded in): `delete_recipe` now unlinks the hero's own `images/<slug>.jpg` file,
  which it previously left orphaned (no file deletion existed before 2a's `delete_image`).
- **`unlink_unreferenced` — the copy-shares-image guard.** `copy_recipe` carries the image PATH, so a
  copy and its original can share one file. File cleanup therefore unlinks a path **only if no surviving
  recipe still references it** as its hero (a post-commit reference check) — deleting one of two sharers
  keeps the file; deleting the last one cleans it. Used on all three deletion paths. (Without this the
  spec's raw unlink would break a copy's shared hero.)
- **Renderer unchanged** — confirmed in the diagnostic: `dishPhoto` renders any `images/…` path and
  `/images/<path:>` serves the `cooks/` subdir, so a hero pointing at a cook photo Just Works.

**This COMPLETES the cook-photo album BACKEND** (2a seams + schema, 2b attach/caption/delete, 2c
promote + linked-hero deletion). **Build 3** is the album UI (preview-first).

**Follow-up fix — `delete_test_recipes` was missing 2c's file cleanup.** The bulk "Delete all test
recipes" endpoint (`DELETE /api/test-recipes`) dropped the rows and let the FK cascade remove the
`cook_photos` rows, but — unlike its sibling `delete_recipe` — it **never gathered the paths and never
called `unlink_unreferenced`**, so every bulk-deleted test recipe **orphaned its cook-photo + hero files
on disk** (surfaced by 2 real orphans left from a "Copy as test" recipe deleted during testing). Fixed to
mirror `delete_recipe`: **gather every test recipe's cook-photo paths + hero files before the delete,
unlink after commit** — with the **copy-share guard preserved** (a test recipe whose hero is shared with a
surviving app copy keeps that file; regression-tested). The diagnostic confirmed the other three deletion
paths (explicit `delete_cook_photo`, `undo_cook`, `delete_recipe`) were already correct, and that
`copy_recipe` doesn't duplicate `cook_photos` rows (so cook-photo files are never cross-recipe-shared —
only the hero path is, which is exactly what the guard checks). Pinned by
`tests/test_delete_test_recipes_cleanup.py` (file-unlink + unshared-hero-unlink + shared-hero-preserved).

### Build 3a — the album DISPLAY (shipped)

The first VISIBLE piece of the feature: a dedicated **"Album" section on the recipe page, below the
method** (the alternate placement chosen from the preview, not an inline cook-block roll). Read-only
display — no add affordance (3b), no per-photo actions (3c).

- **Data — folded into `GET /api/recipes/<id>`** (not a separate endpoint): a `photos` array rides along
  with `stats`/`ingredients`/`steps` so the album paints with the page (no second request; the client
  already re-fetches canonical state after mutations). Per photo, **least-exposure**:
  `{id, path, caption, cooked_on, is_hero}` — `cooked_on` via a `cook_log` LEFT JOIN (NULL for a
  standalone photo), `is_hero` = `recipes.image == path` (the POINT/linked hero).
- **Order — newest cook first, undated last.** `ORDER BY (cooked_on IS NULL) asc, cooked_on desc,
  added_at desc, id desc`: cook-linked photos by cook date descending, then standalone/undated photos
  last (by add-time). `(cooked_on IS NULL)` pushes NULLs last **portably** (no reliance on `NULLS LAST`
  syntax — works on SQLite + Postgres). **The hero is NOT floated** — it wears the badge in its natural
  `cooked_on` position (with newest-first ordering the arrangement is already meaningful).
- **Treatment — the real mini-Polaroid** (the approved preview, real tokens): the `--polaroid` frame +
  bottom strip, smaller than the hero, casually rotated, **no clip**. Each shows the photo; the **full
  date** ("March 12, 2024" — `formatFullDate`, `month:"long"`, distinct from the cook-summary's short
  "Mar") for cook-linked, **no date** for standalone; the optional **caption beneath in Kalam**
  (`--font-hand`); the promoted photo carries the **★ Hero badge** (ochre badge + ring). A broken image
  drops its card (`onerror`).
- **Cap — three, then "See all".** **Three** show by default (one clean row — four wrapped); a quiet
  green **"See all N photos ↓"** toggles the `.collapsed` class (CSS hides the 4th onward) for an inline
  desktop expand, and flips to **"See less ↑"** to collapse back. `N` counts the full set. A dedicated
  **mobile album view is deferred** (inline expand serves mobile for now).
- **Empty state:** a recipe with no cook photos renders **no album section** (calm; 3b adds the
  add-photo entry points). The hero Polaroid / clip / reading card / cook block are **untouched** — the
  album is a wholly new section added below the method.

### Build 3b-i — standalone "add to album" upload + aspect-matched masonry (shipped)

Two things landed together (client-only: `static/app.js` + `static/styles.css`):

**The standalone "add to album" upload.** An **in-grid add-tile** at the end of the album grid — the
**real** hero-uploader `.upload-zone` (dashed frame / "+" / drag-or-click / real dragover·working·error
states) sized into a grid cell, not redrawn. **Owner-only** (gated on `data.is_editable`, the same gate
the hero uploader uses; the server still enforces `rec.owner` on the standalone attach). **Multi-file**:
several photos at once run best-effort through **`Promise.allSettled`** — the ones that succeed are kept
(a repaint shows them) and the misses are surfaced in the tile (*"Added X; Y couldn't be added"*), never
all-or-nothing. **Standalone = `cook_log_id` NULL** (no cook, no date). A quiet **(i) cook-logger hint**
nudges: a dated cook captures more signal than a bare album photo. **Empty-album change to 3a:** an
**owner** now sees the section with **just the add-zone** (an entry point for the first photo); a
**non-owner** empty album still renders nothing.

**Album layout → aspect-matched MASONRY.** Photos render **WHOLE at their native aspect ratio** (no
`object-fit: cover` crop) with **ragged heights** — portrait tall, landscape wide. Mechanism:
`layoutAlbum` distributes items **round-robin into column stacks** (`item i → column i mod N`), *not* CSS
`column-count` (which flows top-to-bottom per column and would scramble newest-first). N derives from
width; columns stack naturally so no per-image height measuring is needed (they reflow as images load);
re-run on resize + on the see-all toggle. **Ordering is roughly-newest-first, NOT strict row-major at
every width** — the exact sequence can shift with the column count; Andy **accepted this as the tradeoff**
for the organic masonry look (a deliberate design choice, not a bug). **Extreme-aspect guardrail:** a
very tall portrait caps at `max-height: 300px`, a very wide panorama floors at `min-height: 72px`, with
`object-fit: contain` so a capped extreme letterboxes (still whole) while normal ratios (~0.6–2.3) render
edge-to-edge — one odd photo can't blow out the layout. The collapsed cap moved from CSS (`nth-child`
hide) to JS (render only the first `ALBUM_CAP` = **6**); the see-all/see-less toggle re-distributes.

The hero Polaroid / clip / reading card / cook block / mini-Polaroid strip are **untouched**.

### Build 3b-ii — at-log-time photo attach in the backdate modal (shipped)

Attach photo(s) **when logging a past cook**. The modal's design is unchanged — the "add a photo" stub
(a bare "coming soon" div) is **activated** as a real multi-file **pick/drop** that **stages** files
client-side (the cook doesn't exist until submit): thumbnail previews (object-URLs) in the existing
`.bd-photo` box, each with a **corner × client-only remove** (iPhone "delete app" badge — a small circle
straddling the top-right corner, covering none of the photo; drops the file from the staged set + revokes
its URL, **not** a server delete), + a `＋` add-more tile. **Non-images are rejected AT staging**
(`isStageableImage` mirrors the server allowlist JPEG/PNG/WebP/HEIF — known mime must be allowlisted,
empty-type HEIC trusts the extension) with a brief nudge, so a wrong-type file never becomes a broken
thumbnail or a doomed upload; a JS test keeps that gate synced to `images.ALLOWED_INPUT_FORMATS`.

**Single-button submit:** "Log this cook" logs the cook → reads the returned `cook_log_id` (2b already
returned it; the client used to discard it) → attaches each staged photo to that cook (**dated**) via the
album endpoint, best-effort `Promise.allSettled`. **Hold-until-both-succeed:** the modal stays open on a
photo failure with a retry. **The correctness crux — retry-holds-the-`cook_log_id`:** the log→attach
sequencing is a pure, DOM-free orchestrator (`static/backdate-submit.js`) that **holds the cook id once
logged**, so a retry re-attaches to the *same* cook and **never re-logs it** (a re-log = duplicate cook);
`reset()` on open/close clears it. Unit-tested (`tests/js/backdate-submit.test.js`: a retry after a photo
failure asserts the cook was logged **exactly once**). Full success repaints (`renderRecipe`) so the album
shows the new dated photos. **The photoless path is unchanged** (log + in-place stats patch + close).

**Folded in — the calendar fixed-height fix** (a pre-existing month-change jitter, per Andy's call): the
calendar grid changed row count by month (5 vs 6 weeks), resizing the modal and shifting the "Log this
cook" button under the mouse. `render()` now **pads trailing empties to a constant 42 day-cells (6 rows)**,
so every month occupies the same height and month-nav no longer moves the modal.

Client-only: `static/app.js` + `static/index.html` + `static/styles.css` + the new
`static/backdate-submit.js` (orchestrator + `isStageableImage`) + its test. No `3b-iii`/`3c` code.

### Build 3b-iii — "Cooked it" instant-path photo attach (shipped — COMPLETES the three add-flows)

The one-click **"Cooked it"** logs a cook instantly (no modal), and 3b-iii lets you attach photo(s) to that
just-logged cook **without breaking the instant no-photo path**. The instant log is **completely unchanged**
— `data-cook` still calls `updateStats` exactly as before; the only addition is an ignorable `.then()` that
offers a chip. After the cook logs, a **quiet auto-fading inline chip** (*"✓ Cooked — add photos ×"*) appears
under the cook-actions and **fades on its own after ~8 s** (a calm offer, not a nag; `×` dismisses; ignoring
it loses nothing). Clicking **"add photos"** cancels the fade and opens a **pick/drop zone first** — the real
upload-zone treatment (⊕ / "add photos" / "drag here or click to choose"), **no OS file-dialog ambush**,
consistent with how 3b-i/3b-ii show the zone and let the user act (click-to-browse or drag). Then
stage → review (thumbnails, corner-× remove, `＋` add-more; non-images rejected via the shared
`isStageableImage`) → **"Attach N photos"**.

**Simpler mechanic than 3b-ii:** the cook already exists (logged on the click), so there is **no
cook-create to sequence** — none of 3b-ii's hold-until-both / retry-holds-the-`cook_log_id` machinery is
needed. The attach is a plain best-effort `Promise.allSettled` batch to the held `cook_log_id` (dated); a
partial failure just keeps the misses staged, and a retry re-uploads them to the *same* existing cook (no
double-log possible — there's no cook-create). `updateStats` gained a `return s` so the `data-cook` handler
can read the `cook_log_id` the `/cooked` endpoint already returned. Full success repaints so the album shows
the new dated photos. Client-only: `static/app.js` + `static/styles.css` (the chip; the pick reuses the
shipped `.bd-photo` staging). No `3c` code. Browser-gated (UI + network; the attach mirrors 3b-i's batch).

**This COMPLETES the three add-flows:** **3b-i** standalone "add to album", **3b-ii** at-log-time (backdate
modal), **3b-iii** "Cooked it" instant-path.

**This COMPLETES the three add-flows** — see below for **3c** (manage) which closes the album's core loop.

### Build 3c — per-photo ⋮ actions: make-hero / edit-caption / delete (shipped — COMPLETES the album core loop)

Each album photo gets a per-photo **⋮ menu** (owner-only, gated by `data.is_editable` — the same gate the
add-tile uses). The menu is **calm at rest** (hidden), the ⋮ **revealed on hover/focus**, and **opens on
click** to a small on-theme card: **Make hero / Edit caption / — / Delete** (Delete in danger-red). A click
anywhere outside closes it. The three actions wire to the endpoints **already shipped in build 2b/2c** —
this build is mostly **wiring** known pieces + one render hook + one server constant:

- **Make hero** → `POST /api/photos/<id>/promote` → `renderRecipe` (the ★ badge moves + the hero Polaroid
  updates). On the photo that IS the hero, the item shows **disabled as "Already the hero."**
- **Edit caption** → an inline editable field in the real **Kalam** caption face (pre-filled or placeholder),
  a live **N/60** count + hard `maxlength=60` → `PATCH /api/photos/<id> {caption}` → `renderRecipe`. Blank
  clears it. **Cancel** reverts locally (no network) by rebuilding the strip from `view.data.photos`.
- **Delete** → a **two-step** confirm that dims the whole mini-polaroid (`inset:0`, never clips); on the
  **hero** photo it adds the warning **"Deleting clears the hero."** → `DELETE /api/photos/<id>` →
  `renderRecipe` (the server does 2c's linked-hero clear; the repaint surfaces the empty upload frame — the
  linked-hero behavior driven from a button for the first time).

**The one existing-render change** is the load-bearing **`data-photo-id`** hook on the `.album-photo` figure
(the id was in the payload but not the DOM); everything else is additive. **Refresh** is `renderRecipe(view.slug)`
after each action — the seam the diagnostic confirmed covers all three. **Edge positioning** (the corner-×
lesson): the menu is right-anchored (fits inside a ~168px masonry column) and **flips up** (`.photo-menu.up`)
when it would overflow the viewport bottom; the delete-confirm is `inset:0` so it never clips.

**Caption cap lowered 100→60** (`COOK_PHOTO_CAPTION_MAX`): the album caption is a **short label** under the
polaroid (fits Kalam at readable size). The **feed/share** caption (`create_share`'s `CAPTION_MAX`) is a
**different field, untouched**; the Cooking Journal will hold longer prose. Zero existing cook-photo captions
were >60 (in fact zero exist), so nothing was stranded. The pytest cap test now asserts **60 passes / 61 →
400** on both attach and edit. Diff = `static/app.js` + `static/styles.css` + the one server constant + the
test update; browser-gated (UI + network); the endpoints stay pytest-covered (2b/2c).

**This COMPLETES the album's core loop** — add every way (3b-i/ii/iii) + manage (3c: promote / caption /
delete).

### Build — hero caption slot (SHARED, shipped — resolves the 3c follow-up)

The hero Polaroid (`dishPhoto`) predated cook-photo captions and rendered an **empty `.strip`**. Decided
**SHARED**: the hero shows the **live caption of the cook photo at `recipes.image`**. The recipe payload already
carries the album `photos[]` with `is_hero` computed (`recipes.image == path`) and each photo's caption, so a
tiny pure helper **`static/hero-caption.js` → `heroCaption(photos)`** returns the `is_hero` photo's caption (or
`null`), and `dishPhoto` fills the strip with the album's Kalam `.cap` face (sized up for the larger hero frame,
centered). **Render-only — NO schema, NO endpoint, NO promote change, NO caption editor on the hero.**

- **Editing is free via 3c:** editing that photo's caption through the album ⋮ menu → `PATCH` → `renderRecipe`
  re-reads `data.photos` → the hero shows the new text. Same field, one edit path (no ⋮ on the hero itself).
- **Promote carries the caption** with no new code: `promote` sets the path, and the caption follows because the
  hero reads the (now-`is_hero`) photo's live caption.
- **Graceful fallbacks** (the load-bearing part, unit-tested in `tests/js/hero-caption.test.js`): an
  **uncaptioned** hero → empty strip (as before); a hero with **no matching `cook_photo` row** (legacy/backfilled/
  direct Polaroid upload) → `find` returns undefined → `null` → no caption area, **doesn't break**.

The reserved `.polaroid .strip`/`.cap` CSS is brought to life (`height:54px` → `min-height:54px` so a long
caption grows the strip but it stays ≥54px when empty). Diff = `static/hero-caption.js` + `static/app.js` +
`static/styles.css` + the test; browser-gated. Its one limitation (a directly-uploaded hero still can't be
captioned) is the only reason to consider SEPARATE (`recipes.image_caption`) later — not currently needed.

### Build 3d-i — the position column + cooked_on-seeding backfill + order-by-position (shipped)

3d adds **drag-to-reorder** (**Model B**: `cooked_on` SEEDS a stored order that becomes authoritative once
dragged). 3d-i is the **data foundation** — no reorder endpoint (3d-ii) or drag UI (3d-iii) yet:

- **Column:** a nullable `cook_photos.position` INTEGER (the house-convention name — `recipe_ingredients`/
  `recipe_steps` already store + `ORDER BY position`). **Migration 027 is a plain `ADD COLUMN`** on both
  dialects — **no table rebuild** (026 rebuilt only because SQLite can't DROP NOT NULL; adding a column
  has no such limit) — mirrored by the Alembic revision `b8c9d0e1f2a3` for the PG CI path. A composite
  `(recipe_id, position)` index backs the album read. **No data change IN the migration.**
- **Seed backfill (the data-transforming part, gated):** `scripts/backfill_cook_photo_position.py` assigns
  `position = 0,1,2,…` **per recipe in the album's current display order** (cook-linked newest-first, undated
  last) — so ordering by position looks **identical** to before. Standalone (not in `migrate.py` — the
  qty/unit lesson), idempotent (`WHERE position IS NULL`, continues from a recipe's max — never disturbs a
  set row), **backup → dry-run → review → apply**. Live run: **7 rows / 2 recipes** (shawarma `#44..#39 →
  0..5`, agedashi-copy `#47 → 0`), backup at `backups/recipes-20260804-142342.db`, verified byte-for-byte
  against the reviewed dry-run mapping.
- **Read by position:** the payload `ORDER BY` is now `position IS NULL` → `position ASC` → `id ASC` (the
  portable **NULLs-last** idiom — SQLite sorts NULLs first, PG last). `cooked_on` is still returned and
  still governs each photo's **DATE**: **position governs ORDER, cooked_on governs DATE — independent**
  (reordering never changes dates; pinned by a test).
- **New photos APPEND** (`position = MAX(position)+1`, set at the single attach insert), so no row is ever
  NULL after the backfill. ⚠️ **Intended behavior change (okayed):** a new photo now lands at the **END**
  of the album (previously newest-added showed **first**) — Model B: you drag it where you want. Surfaced
  as honest rewrites of two `test_album_payload` ordering tests (now assert append/position order) + the
  coupled `test_build_db` (26→27) and `test_cook_photos` (schema/index) updates; PG integration gained a
  position/NULLs-last dialect test.

### Build 3d-ii — the reorder endpoint (shipped)

The WRITE that lets positions change: **`PATCH /api/recipes/<rid>/photos/order`**, body `{"order": [id, …]}` —
the FULL ordered list of the recipe's cook_photo ids. **Recipe-owner gated** (`rec.owner == current_user`,
mirroring `promote` — the stored album order is the owner's arrangement; `404` if the recipe is missing,
`403` if not the owner). **Exact-permutation validation** (load-bearing): the body must be a complete, exact
permutation of the recipe's photo ids — the **duplicate check runs BEFORE** the `set(order) != {recipe ids}`
comparison (so a duplicate can't ride through set-dedup as a partial), and that one set-equality catches both
a **foreign/unknown** id and a **missing** id (partial). On accept, `position = the id's index in the list`
for each, in **one transaction** (atomic). Guards that matter: **auth before validation**, and **atomic-on-
reject** — a `400` returns before any write, so a malformed reorder leaves positions intact (proven by the
foreign/partial/duplicate rejection tests, each asserting positions unchanged). Returns `{"ok": true}`.
Backend-only (no drag UI yet); the pytest suite is the gate — happy-path (order persists + GET reflects it
via 3d-i's ORDER BY), idempotent, owner-gate, and the three rejection cases. **No PG test** — a plain per-id
`UPDATE … SET position`, no dialect surface (like the delete-cleanup fix).

**Album roadmap (remaining builds):** **3d-iii** — the drag UI (preview-first, the linearized-reorder-view)
that calls this endpoint; **3e** — anchor a photo to a specific method step (the reserved `.step-body`
per-step-photo hook); then the **Cooking Journal**.

## Open questions

- **Masthead title face** — Spectral vs Newsreader vs Fraunces, decided by eye after Stage B renders
  the real masthead. `--font-title` is the swap point.
