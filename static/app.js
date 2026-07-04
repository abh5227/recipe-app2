"use strict";

// This file runs in the browser. It has no recipe content of its own — it asks
// the backend (app.py) for data as JSON, builds HTML text from that data, and
// drops it into the page. There's only one real page; clicking around swaps what's
// shown by changing the part of the address after "#". (See the router below.)

const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
const app = document.getElementById("app");

// State for whichever recipe page is open (null on the home list or a form). It
// remembers which view is showing and which line is being edited, so a click can
// re-render the ingredient list without re-fetching from the server:
//   { slug, data, mode, editingPos, addingOpen }
//   - data        : the GET /api/recipes/<id> response
//   - mode        : 'original' | a person id | 'compare'   (which version is shown)
//   - editingPos  : the line position whose inline editor is open, or null
//   - addingOpen  : whether the "add ingredient" form is open
let view = null;
// The ingredient library ({id, name}), fetched when a form or a seed recipe opens,
// to fill the "link to an ingredient" dropdowns.
let INGREDIENT_LIST = [];

/* ---------- tiny helpers ---------- */

// Make text safe to drop into HTML. If a recipe name contained "<" or "&", the
// browser might treat it as code/markup; this swaps those characters for their
// harmless display versions. Every piece of data we insert goes through this.
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
}

// Fetch JSON from one of the backend's GET endpoints. "await" means "wait for the
// server to answer before continuing". If the server returns an error, we throw,
// and the caller (route) shows the error screen.
async function api(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// [[key]] or [[key|label]] in step text -> clickable ingredient button
function linkify(text) {
  return esc(text).replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, key, label) => {
    key = key.trim();
    const shown = (label || key).trim();
    return `<button class="ingredient" data-item="${esc(key)}">${esc(shown)}</button>`;
  });
}

// POST and ignore the body shape (used by the stats bar, which throws on failure).
async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// Send any method and ALWAYS return {ok, status, data} instead of throwing, so the
// caller can show the server's message on a 400 / 403 / 409 (e.g. "name taken").
async function sendJSON(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* no/!json body */ }
  return { ok: res.ok, status: res.status, data };
}

function formatDate(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);   // 'YYYY-MM-DD'
  return new Date(y, m - 1, d).toLocaleDateString("en", {
    month: "short", day: "numeric", year: "numeric",
  });
}

// Five star buttons, filled up to the current rating.
function starsHTML(rating) {
  let out = "";
  for (let n = 1; n <= 5; n++) {
    out += `<button class="star${rating && n <= rating ? " on" : ""}" data-rate="${n}" aria-label="${n} star${n > 1 ? "s" : ""}">★</button>`;
  }
  return out;
}

// The cook-summary line. A provisional last-cook date (a seeded Paprika-import date, not yet a
// confirmed cook) renders soft — the "~" + .approx family from the ledger — so unconfirmed dates
// stand out at a glance for later correction. Returns HTML; the dynamic date is escaped.
function cookSummary(stats) {
  if (!stats.cook_count) return "Not cooked yet";
  const times = stats.cook_count === 1 ? "once" : `${stats.cook_count} times`;
  const last = formatDate(stats.last_cooked);
  const line1 = `<span class="cook-times">Cooked ${times}</span>`;
  if (!last) return line1;                             // cooked but no date -> just the count line
  const dateClause = stats.last_cooked_provisional
    ? `<span class="approx">~ ${esc(last)}</span>`     // provisional (import-seeded) date, kept soft
    : esc(last);
  return `${line1}<span class="cook-last">Last cooked ${dateClause}</span>`;   // two stacked lines, no separator
}

// The inner contents of the stats bar (re-rendered after each change). Three rating states:
//   • cooked            -> stars to the committed rating + the cook-summary; a star click rates directly.
//   • uncooked + unrated -> outline stars + a quiet "Log a cook to rate" hint.
//   • pending-confirm    -> a star was clicked while uncooked: stars held at the chosen rating + an
//     inline "Mark cooked & rate?" confirm (the cook-gate). Yes -> cooked-and-rated; Cancel -> back.
function statsInner(stats) {
  const pending = view ? view.pendingRating : null;
  const starFill = pending || stats.rating;            // hold the chosen rating during the confirm
  // The middle slot (between stars and buttons) is one of: the cook-gate confirm, the two-line
  // cook-summary (once cooked), or the quiet "log a cook to rate" nudge.
  let middle = "";
  if (pending) {
    middle = `<span class="cook-rate-confirm">Mark cooked &amp; rate?
      <button class="btn ghost sm" data-cook-rate-confirm>Yes</button>
      <button class="btn ghost sm" data-cook-rate-cancel>Cancel</button></span>`;
  } else if (stats.cook_count) {
    middle = `<p class="cook-summary">${cookSummary(stats)}</p>`;
  } else if (!stats.rating) {
    middle = `<span class="rate-hint">Log a cook to rate</span>`;
  }
  // Redo is a one-shot: the Undo / Redo pair shows ONLY in the window right after an undo
  // (view.undoneCook set); any other action clears it and we fall back to the plain "Undo".
  const undone = view ? view.undoneCook : null;
  let undoControls = "";
  if (undone) {
    undoControls = `<span class="cook-redo">
      <button class="btn ghost sm" data-uncook${stats.cook_count ? "" : " disabled"}>Undo</button>
      <button class="btn ghost sm" data-redo>Redo</button>
    </span>`;
  } else if (stats.cook_count) {
    undoControls = `<button class="btn ghost sm" data-uncook>Undo</button>`;
  }
  // The soft inset cook block: stars + middle + cook buttons, stacked.
  return `
    <div class="rating" role="group" aria-label="Your rating">${starsHTML(starFill)}</div>
    ${middle}
    <span class="cook-actions">
      <button class="btn" data-cook>Cooked it</button>
      <button class="btn alt" data-backdate-open title="Log a cook on a past date">Log a past cook</button>
      ${undoControls}
    </span>`;
}

// Today's date as YYYY-MM-DD in LOCAL time — used for the backdate input's `max` guard.
// (Note: this is a different clock from the /cooked no-date insert, which uses SQLite
// date('now') in UTC; on this local single-user machine they agree in practice.)
function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Reserved R2 wear signal: mirror the recipe's cook count onto the page root as the --cook-count
// custom property so Round 2 can scale a wear/patina effect from it. Unread in R1; kept in sync
// wherever the count changes so it never goes stale.
function setCookCount(el, count) {
  el.style.setProperty("--cook-count", String(count));
}

async function updateStats(el, path, body) {
  if (view) view.undoneCook = null;   // any stats-mutating action (cook / rate / confirm) ends the one-shot redo window
  try {
    const s = await postJSON(path, body);
    if (view && view.data) view.data.stats = s;   // keep cached stats fresh so the cook-gate reads the new cook_count
    el.innerHTML = statsInner(s);
    setCookCount(app, s.cook_count);   // sync the reserved wear signal from the refreshed stats
  } catch (_) {
    /* leave the bar as-is if the write fails */
  }
}

/* ---------- router ---------- */
// Decides which view to show based on the address bar. We use the part after "#"
// so the browser never reloads the page or contacts the server for navigation:
//   #/                 -> the home list
//   #/recipe/mussakhan -> that recipe
//   #/new              -> the create form
//   #/edit/mussakhan   -> the edit form (app recipes only)
// route() runs once at startup and again every time the "#" part changes.
async function route() {
  const hash = location.hash || "#/";
  try {
    const mEdit = hash.match(/^#\/edit\/(.+)$/);
    const mRecipe = hash.match(/^#\/recipe\/(.+)$/);
    if (hash === "#/new") {
      await renderForm("create");
    } else if (mEdit) {
      await renderForm("edit", decodeURIComponent(mEdit[1]));
    } else if (mRecipe) {
      await renderRecipe(decodeURIComponent(mRecipe[1]));
    } else {
      await renderHome();
    }
  } catch (err) {
    showError(err);
  }
  window.scrollTo(0, 0);
}

/* ---------- home view ---------- */
// Renders a photo if the file loads, otherwise a tidy labeled placeholder.
// The <img> sits on top of the placeholder; if it 404s, onerror removes it,
// revealing the placeholder beneath. So "no photo yet" still looks intentional.
function photo(r, kind) {
  const label = `<span class="ph-label">${esc(r.name)}</span>`;
  const img = r.image
    ? `<img src="/${esc(r.image)}" alt="${esc(r.name)}" loading="lazy" onerror="this.remove()">`
    : "";
  return `<div class="${kind}">${label}${img}</div>`;
}

async function renderHome() {
  view = null;
  app.className = "page home-view";
  const [recipes, season] = await Promise.all([
    api("/api/recipes"),
    api("/api/in-season"),
  ]);

  const monthName = new Date(2000, season.month - 1, 1).toLocaleString("en", { month: "long" });

  const chips = season.ingredients.length
    ? season.ingredients
        .map((i) => `<button class="chip" data-item="${esc(i.id)}">${esc(i.name)}</button>`)
        .join("")
    : `<p class="season-none">Nothing in the library is flagged for ${esc(monthName)} yet.</p>`;

  // Test (scratch) recipes sink to the bottom; real recipes keep their normal order. A stable sort
  // (partition by is-test) preserves the API's existing name order within each group.
  const ordered = [...recipes].sort((a, b) => (a.source === "test") - (b.source === "test"));
  const cards = ordered
    .map((r) => {
      const bits = [r.author, r.category, r.servings ? `Serves ${r.servings}` : null]
        .filter(Boolean)
        .map(esc)
        .join('<span class="dot">·</span>');
      const stars = r.rating ? "★".repeat(r.rating) + "☆".repeat(5 - r.rating) : "";
      const count = r.cook_count ? `<span class="ct">cooked ${r.cook_count}×</span>` : "";
      const statsLine = stars || count
        ? `<p class="rc-stats">${stars}${stars && count ? '<span class="dot">·</span>' : ""}${count}</p>`
        : "";
      const isTest = r.source === "test";
      return `<a class="recipe-card${isTest ? " is-test" : ""}" href="#/recipe/${encodeURIComponent(r.id)}">
                ${photo(r, "thumb")}
                <div class="rc-body">
                  <p class="rc-name">${esc(r.name)}${isTest ? ` <span class="test-badge">Test</span>` : ""}</p>
                  <p class="rc-meta">${bits}</p>
                  ${statsLine}
                </div>
              </a>`;
    })
    .join("");

  const testCount = recipes.filter((r) => r.source === "test").length;
  const bulkTest = testCount
    ? `<span id="test-bulk"><button class="btn danger-soft sm" data-delete-test>Delete ${testCount} test recipe${testCount > 1 ? "s" : ""}</button></span>`
    : "";

  app.innerHTML = `
    <div class="site-head">
      <div>
        <h1 class="site-title">Chef's Choice</h1>
        <p class="site-sub">Field notes from the kitchen — recipes, and what goes in them.</p>
      </div>
      <div class="site-head-actions">${bulkTest}<a class="btn new-recipe" href="#/new">+ New recipe</a></div>
    </div>
    <div class="season-rail">
      <h2>In season now — ${esc(monthName)}</h2>
      <div class="season-chips">${chips}</div>
    </div>
    <div class="recipe-grid">${cards}</div>`;
}

/* ---------- recipe view ---------- */

/* ---------- recipe view ---------- */

/* Quantity scaling (Phase 1a-1d). The pure logic + constants live in static/scaler.js, loaded as a
   global before this file (and unit-tested under Node, tests/js/). app.js keeps the DOM/rendering
   and passes view.scale into the scaler's amount/weight formatters. */

// One ledger figure cell — the amount or the weight, mono + tabular. A leading "~" (an estimated
// weight, or a humane-rounded amount) earns the shared "approx" treatment. inlineStyle carries a
// person's colour on edited/added lines (seed recipes).
function figCell(cls, text, inlineStyle) {
  const approx = text.charAt(0) === "~" ? " approx" : "";
  const style = inlineStyle ? ` style="${inlineStyle}"` : "";
  return `<span class="${cls}${approx}"${style}>${esc(text)}</span>`;
}

// One ledger amount-cell for a line: the amount, with the gram estimate stacked as a muted sub-line
// beneath it when present (chart-known volume over 2 tbsp) — nothing emitted otherwise, so weightless
// rows reserve no column and names stay aligned (Option B2). Replaces the old metric/imperial toggle.
// R2 hook: this .amount-cell (and its addressable .qty) is the reserved strike target — Round 2
// will strike the printed amount and set the edited value beside it in the hand color. No R1 treatment.
function ledgerCells(qty, gramsPerMl, inlineStyle) {
  const weight = weightText(qty, gramsPerMl, view.scale);
  return `<span class="amount-cell">` +
         figCell("qty", amountText(qty, view.scale), inlineStyle) +
         (weight ? figCell("weight", weight, inlineStyle) : "") +
         `</span>`;
}

// Does any non-heading ingredient produce a weight at the current scale? Drives the weight column's
// presence — a recipe with no convertible volumes shows no empty gram gutter.
// True if any ledger value renders with a "~" at the current scale — an estimated weight, a
// humane-rounded amount, or a count rounded up from <1. Drives the approximate-value footnote.
function anyApprox() {
  return view.data.ingredients.some((row) =>
    !row.is_heading &&
    (amountText(row.qty, view.scale).includes("~") ||
     weightText(row.qty, row.grams_per_ml, view.scale).includes("~")));
}

// A quiet caption for the unified "~" family (estimates, humane rounding, rounded-up counts).
function approxNote() {
  return anyApprox()
    ? `<p class="grams-note">~ an estimate, rounded, or rounded up from a smaller amount — weigh or measure for precision.</p>`
    : "";
}

// The recipe's serving count as a number, if its servings text contains one.
function servingsBase() {
  const sv = view && view.data.recipe.servings;
  const m = sv ? String(sv).match(/\d+/) : null;
  return m ? parseInt(m[0], 10) : null;
}

// The scale control shown beside the Ingredients heading.
function scaleControl() {
  const options = [[0.5, "\u00bd\u00d7"], [1, "1\u00d7"], [2, "2\u00d7"]];   // 3\u00d7 dropped; custom covers the rest
  const buttons = options
    .map(([v, label]) => `<button data-scale="${v}" class="${view.scale === v ? "on" : ""}">${label}</button>`)
    .join("");
  // Custom multiplier \u2014 any positive number. When an active custom factor is set, the field shows
  // its COMMITTED display form "N\u00d7" (right-aligned, reads like the preset pills); on focus it strips
  // to a bare number for editing (see the focusin handler). type=text is deliberate: the control is
  // rebuilt via innerHTML on scale change, and type=number got destroyed mid-interaction.
  const isPreset = options.some(([v]) => v === view.scale);
  const customVal = isPreset ? "" : `${view.scale}\u00d7`;
  const custom = `<input class="scale-custom" type="text" inputmode="decimal" placeholder="custom\u00d7" aria-label="Custom multiplier" value="${customVal}">`;
  return `<div class="scale-control" role="group" aria-label="Scale quantities">${buttons}${custom}</div>`;
}

// Look up a person record / their saved changes by id.
function personById(pid) {
  return view.data.people.find((p) => p.id === pid) || null;
}
function changesFor(pid) {
  // Returns the person's change bucket, or an empty one if they've made none yet.
  return view.data.changes[pid] || { edits: {}, removes: [], additions: [] };
}

// The clickable-ingredient-or-plain-text body of a line (no quantity, no tools).
function lineBodyHTML(row) {
  if (row.ingredient_id) {
    const label = row.label || row.raw_text || row.ingredient_id;
    return `<button class="ingredient" data-item="${esc(row.ingredient_id)}">${esc(label)}</button>${row.note ? esc(row.note) : ""}`;
  }
  return esc(row.label || row.raw_text || "");
}

// A plain ingredient line: used for the Original view and for app recipes.
function plainRow(row) {
  if (row.is_heading) return `<li class="group">${esc(row.raw_text)}</li>`;
  return `<li>${ledgerCells(row.qty, row.grams_per_ml)}<span class="iname">${lineBodyHTML(row)}</span></li>`;
}

// An added line (a person's new ingredient), shown in their color. In a person's own
// view it carries a × to delete it; in Compare it's read-only.
function additionRow(a, color, withDelete) {
  const body = a.ingredient_id
    ? `<button class="ingredient" data-item="${esc(a.ingredient_id)}">${esc(a.label || a.raw_text || a.ingredient_id)}</button>${a.note ? esc(a.note) : ""}`
    : esc(a.raw_text || "");
  const tools = withDelete
    ? `<span class="line-tools"><button class="icon-btn" data-del-add data-add="${a.id}" title="Remove this addition" aria-label="Remove this addition">\u00d7</button></span>`
    : "";
  return `<li>${ledgerCells(a.qty, a.grams_per_ml, `color:${color};font-weight:600`)}` +
         `<span class="iname muted-ing" style="color:${color}">${body}</span>${tools}</li>`;
}

// The view switcher: Original / each person / Compare all. The active person's button
// is filled with their color; Original and Compare use the default ink (the .on class).
function viewSelector(view) {
  const button = (mode, label, color) => {
    const active = view.mode === mode;
    const style = active && color ? ` style="background:${color};border-color:${color}"` : "";
    return `<button class="${active ? "on" : ""}" data-view="${esc(mode)}"${style}>${esc(label)}</button>`;
  };
  let out = button("original", "Original");
  view.data.people.forEach((p) => { out += button(p.id, p.name, p.color); });
  out += button("compare", "Compare all");
  return `<div class="view-seg">${out}</div>`;
}

// The inline editor that opens on a line in a person's view: a quantity box plus
// Save / Remove (or Restore) / Reset / Cancel, depending on the line's current state.
function lineEditor(view, row, pid) {
  const ch = changesFor(pid);
  const pos = row.position;
  const removed = ch.removes.includes(pos);
  const editedQty = ch.edits[pos];                       // a string, or undefined
  const qtyValue = editedQty !== undefined ? editedQty : (row.qty || "");
  const forLabel = esc(row.label || row.raw_text || row.ingredient_id || "");
  const buttons = [
    `<button class="btn sm" data-save-edit data-pos="${pos}">Save</button>`,
    removed
      ? `<button class="btn ghost sm" data-clear-line data-pos="${pos}">Restore</button>`
      : `<button class="btn ghost sm" data-remove-line data-pos="${pos}">Remove</button>`,
    (editedQty !== undefined && !removed)
      ? `<button class="btn ghost sm" data-clear-line data-pos="${pos}">Reset</button>` : "",
    `<button class="btn ghost sm" data-cancel-line>Cancel</button>`,
  ].join("");
  return `<li class="editing">
    <span class="line-editor">
      <input class="le-qty" value="${esc(qtyValue)}" placeholder="quantity" aria-label="Quantity for ${forLabel}">
      <span class="le-for">${forLabel}</span>
      ${buttons}
    </span>
  </li>`;
}

// One person's version: each original line (edited / removed / unchanged) with a
// pencil to change it, then that person's additions at the bottom.
// Walk a recipe's ingredient list and, at the end of each section (just before the next
// heading, and again at the very end), drop in that section's additions. A "section" is
// the run of lines under a heading; its key is the heading text, or null for the area
// before the first heading (and for recipes with no headings at all).
function renderWithSections(ingredients, renderLine, additionsForSection) {
  let out = "";
  let section = null;                        // start in the pre-heading area
  ingredients.forEach((row) => {
    if (row.is_heading) {
      out += additionsForSection(section);   // close out the section we were in
      out += `<li class="group">${esc(row.raw_text)}</li>`;
      section = row.raw_text;                // a new section begins here
    } else {
      out += renderLine(row);
    }
  });
  out += additionsForSection(section);       // flush the final section
  return out;
}

// One person's version: each original line (edited / removed / unchanged) with a pencil
// to change it, and that person's additions placed at the bottom of their own section.
function personRows(view, pid) {
  const person = personById(pid);
  const color = person ? person.color : "var(--ink)";
  const ch = changesFor(pid);
  const tools = (pos) =>
    `<span class="line-tools"><button class="icon-btn" data-edit-line data-pos="${pos}" title="Change or remove" aria-label="Change or remove">\u270e</button></span>`;

  const renderLine = (row) => {
    const pos = row.position;
    if (view.editingPos === pos) return lineEditor(view, row, pid);
    const removed = ch.removes.includes(pos);
    const editedQty = ch.edits[pos];                  // keys arrive as strings; pos coerces
    if (removed) {
      return `<li class="ing-line removed">${ledgerCells(row.qty, row.grams_per_ml, `color:${color}`)}` +
             `<span class="iname muted-ing" style="color:${color}">${lineBodyHTML(row)}</span>${tools(pos)}</li>`;
    }
    if (editedQty !== undefined) {
      return `<li>${ledgerCells(editedQty, row.grams_per_ml, `color:${color};font-weight:600`)}` +
             `<span class="iname muted-ing" style="color:${color}">${lineBodyHTML(row)}</span>${tools(pos)}</li>`;
    }
    return `<li>${ledgerCells(row.qty, row.grams_per_ml)}<span class="iname">${lineBodyHTML(row)}</span>${tools(pos)}</li>`;
  };

  // this person's additions that belong to the given section (null matches null)
  const additionsForSection = (section) =>
    ch.additions
      .filter((a) => (a.section || null) === section)
      .map((a) => additionRow(a, color, true))
      .join("");

  return renderWithSections(view.data.ingredients, renderLine, additionsForSection);
}

// Does anyone have an added ingredient on this recipe? (Drives the Compare view.)
function anyAdditions(view) {
  return view.data.people.some((p) => {
    const ch = view.data.changes[p.id];
    return ch && ch.additions.length > 0;
  });
}

// Compare view: everything anyone has *added*, gathered in one place, each in its
// owner's color. Read-only. Edits and removals stay in each person's own view — this
// is the "communal pot," just the extras everyone brings, side by side.
function compareRows(view) {
  let out = "";
  view.data.people.forEach((p) => {
    const ch = view.data.changes[p.id];
    if (ch) ch.additions.forEach((a) => { out += additionRow(a, p.color, false); });
  });
  return out;
}

// The "add ingredient" control at the bottom of a person's view: a button that opens an
// inline form (quantity, link-to-library dropdown or plain text, optional note, and — when
// the recipe has sections — which section to drop it into).
function addControl(view) {
  if (!view.addingOpen) {
    return `<div class="add-row"><button class="btn ghost sm" data-add-open>+ Add ingredient</button></div>`;
  }
  const options = INGREDIENT_LIST
    .map((i) => `<option value="${esc(i.id)}">${esc(i.name)}</option>`)
    .join("");

  // If the recipe has section headings, offer them. Default to the last one, so an
  // addition lands at the very bottom (the old behavior) unless you pick another section.
  const headings = view.data.ingredients.filter((row) => row.is_heading).map((row) => row.raw_text);
  let sectionField = "";
  if (headings.length) {
    const opts = headings
      .map((h, i) => `<option value="${esc(h)}"${i === headings.length - 1 ? " selected" : ""}>${esc(h)}</option>`)
      .join("");
    sectionField = `<select class="af-section" aria-label="Section"><option value="">\u2014 no section \u2014</option>${opts}</select>`;
  }

  return `<div class="add-form">
    <input class="af-qty" placeholder="qty">
    <select class="af-link"><option value="">\u2014 plain text \u2014</option>${options}</select>
    <input class="af-text" placeholder="ingredient / text">
    <input class="af-note" placeholder="note (optional)">
    ${sectionField}
    <button class="btn sm" data-add-save>Add</button>
    <button class="btn ghost sm" data-add-cancel>Cancel</button>
  </div>`;
}

// The whole Ingredients section. App recipes get a plain list; seed recipes get the
// view switcher, the list for the chosen view, and (in a person's view) the add form.
// Re-rendered on its own so the rest of the page doesn't flicker.
function ingredientsSectionInner(view) {
  if (!view.data.is_seed) {
    const rows = view.data.ingredients.map(plainRow).join("");
    return `
      <div class="col-head"><h2 class="col-title">Ingredients</h2></div>
      <ul class="ingredient-list">${rows}</ul>
      ${approxNote()}
      <p class="hint">Tap any highlighted ingredient to see when it's in season and where it grows.</p>`;
  }

  let rows, hint;
  if (view.mode === "original") {
    rows = view.data.ingredients.map(plainRow).join("");
    hint = "The cookbook original. Pick a name above to see or make that person's version.";
  } else if (view.mode === "compare") {
    if (anyAdditions(view)) {
      rows = compareRows(view);
      hint = "Everyone's add-ins, in one place \u2014 throw it all in the pot and the whole table goes home happy.";
    } else {
      rows = `<li style="color: var(--ink-soft);">No one's added anything yet.</li>`;
      hint = "When someone adds an ingredient in their version, it turns up here \u2014 everyone's extras, gathered in one pot.";
    }
  } else {
    rows = personRows(view, view.mode);
    const name = personById(view.mode) ? esc(personById(view.mode).name) : "this person";
    hint = `${name}'s version \u2014 edits and additions show in their color. Use the pencil to change a quantity or remove a line.`;
  }
  const isPersonView = view.mode !== "original" && view.mode !== "compare";

  return `
    <div class="col-head"><h2 class="col-title">Ingredients</h2></div>
    ${viewSelector(view)}
    <ul class="ingredient-list">${rows}</ul>
    ${isPersonView ? addControl(view) : ""}
    ${approxNote()}
    <p class="hint">${hint}</p>`;
}

function rerenderIngredients() {
  const el = document.getElementById("ing-section");
  if (el) el.innerHTML = ingredientsSectionInner(view);
}

// The scaler now lives in the vitals (its own #scaler-host), decoupled from the ingredients
// rebuild — so refresh JUST that host on a scale change to move the active pill / reflect the
// custom value. Targets only #scaler-host; never the .stats/cook-block, so redo/cook state is untouched.
function rerenderScaler() {
  const el = document.getElementById("scaler-host");
  if (el) el.innerHTML = scaleControl();
}

// Re-render the method steps so tagged "scale" quantities reflect the current factor.
function rerenderSteps() {
  const el = document.getElementById("steps-list");
  if (el) el.innerHTML = view.data.steps.map(renderStepRow).join("");
}

// The masthead serving count reflects the current scale, but the masthead isn't rebuilt on rescale —
// so update just that number when the factor changes.
function rerenderServings() {
  const el = document.querySelector(".serves-count");
  const base = servingsBase();
  if (el && base) el.textContent = formatAmount(base * view.scale);
}

// Render a step. Non-heading steps arrive as tagged spans (Phase 1d): "scale" spans are
// rescaled live with the 1a scaler (so they format identically to the ingredient list);
// "plain" spans are linkified (and may contain [[ingredient]] links). Falls back to raw
// text if a payload has no spans.
function renderStepRow(row) {
  if (row.is_heading) return `<li class="group">${esc(row.text)}</li>`;
  const spans = row.spans || [{ t: "plain", text: row.text }];
  const html = spans
    .map((s) => (s.t === "scale"
      ? `<span class="step-qty">${esc(toUnicodeFractions(abbrevUnits(scaleQty(s.text, view.scale))))}</span>`
      : linkify(s.text)))
    .join("");
  // .step-body wraps the step content inside li.step — the reserved attach point for future
  // per-step photos and R2 step-notes. Inert in R1 (a bare block that fills the same box).
  return `<li class="step"><div class="step-body">${html}</div></li>`;
}

// Long headnotes clamp to 3 lines + a "more" expander; short ones show in full. Measured after
// fonts load so the clamped line-count is accurate (Spectral may change wrapping vs the fallback).
function setupHeadnote() {
  const dek = app.querySelector(".dek");
  const more = app.querySelector(".dek-more");
  if (!dek || !more) return;
  if (dek.scrollHeight > dek.clientHeight + 2) more.hidden = false;  // long -> keep clamp, offer "more"
  else dek.classList.remove("clamped");                              // short -> show full, no expander
}

// Masthead byline: the author / source, linked to source_url when present (green kicker).
function bylineHTML(r) {
  if (!r.author) return "";
  const who = r.source_url
    ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.author)}</a>`
    : esc(r.author);
  return `<p class="byline">${who}</p>`;
}

// Tag -> category: the starter vocabulary from the current 20 recipes (expanded in the 295 data
// pass). Category drives a muted color (.cat-tag.cat-* in styles.css). Anything not listed falls
// back to "neutral" (a plain label) so unknown/future tags degrade gracefully, never miscolored.
// "status" (the Paprika cook-tracking workaround) keeps the quiet treatment and migrates out later.
// To extend: add a `"tag": "category"` line here (and a .cat-tag.cat-<category> rule for a new one).
const TAG_CATEGORY = {
  // status
  "made": "status", "to make": "status", "to-make": "status", "tomake": "status",
  "to cook": "status", "want to make": "status",
  // cuisine
  "italian": "cuisine", "middle eastern": "cuisine", "indian": "cuisine", "southern": "cuisine",
  "korean": "cuisine", "thai": "cuisine", "palestinian": "cuisine", "african": "cuisine",
  // course
  "appetizers": "course", "sides": "course", "desserts": "course",
  // dessert dish-types (distinct from the "Desserts" course tag)
  "cookies": "dessert", "cakes": "dessert", "ice cream": "dessert",
  // bread
  "bread": "bread",
  // main-ingredient
  "chicken": "main", "beef": "main", "pork": "main", "ground meat": "main", "beans": "main",
  "vegetables": "main", "rice": "main", "chocolate": "main",
  // neutral: "vegetarian" and anything unlisted
};

// Category -> discreet mono "filing" labels, tinted by category. Non-clickable for now
// (tag-click-to-filter is the R2 browse redesign). neutral = plain; status = the quiet treatment.
function tagsHTML(r) {
  const tags = String(r.category || "").split("·").map((s) => s.trim()).filter(Boolean);
  if (!tags.length) return "";
  const html = tags.map((t) => {
    const cat = TAG_CATEGORY[t.toLowerCase()] || "neutral";
    const cls = cat === "neutral" ? "cat-tag"
              : cat === "status"  ? "cat-tag status"
              : `cat-tag cat-${cat}`;
    return `<span class="${cls}">${esc(t)}</span>`;
  }).join("");
  return `<p class="cat-tags">${html}</p>`;
}

// Minimal inline icons for the masthead meta — a man+woman figure pair (servings) and a clock
// (time), both --ink-soft via CSS. Hand-drawn paths, no icon library.
const META_FIG = `<svg class="meta-ico fig" viewBox="0 0 30 24" aria-hidden="true"><circle cx="9" cy="6" r="3"/><path d="M4.5 20 a4.5 4.5 0 0 1 9 0"/><circle cx="21" cy="6" r="3"/><path d="M21 9 L17.2 20 H24.8 Z"/></svg>`;
const META_CLOCK = `<svg class="meta-ico clk" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="7.5"/><path d="M12 9 V13 L15 15"/><path d="M9.5 3 H14.5"/></svg>`;

// Compact masthead meta: servings + time — recipe facts only (cook status lives in the stats bar).
// Icon + value; the serving count stays scaled to the current factor (updated by rerenderServings).
function metaLine(r) {
  const items = [];
  const base = servingsBase();
  if (base) items.push(`<span class="meta-item">${META_FIG}<span>Serves <span class="serves-count meta-val">${formatAmount(base * view.scale)}</span></span></span>`);
  const time = r.total_time || r.cook_time || r.prep_time;
  if (time) items.push(`<span class="meta-item">${META_CLOCK}<span class="meta-val">${esc(time)}</span></span>`);
  if (!items.length) return "";
  return `<p class="meta-line">${items.join("")}</p>`;
}

// Take A brass clip (ported verbatim from the approved preview). Gem proportions; three stacked
// strokes make a round wire that catches light: underside shadow, gradient body, specular ridge.
const CLIP_CFG = { grad: "brassA", bodyW: 2.4, glint: "#fffdf2", glintW: 0.85, glintO: 0.92, shadow: "#2e2206", shadowO: 0.45 };
function clipRects(stroke, w) {
  return `<rect x="6" y="5" width="22" height="76" rx="11" fill="none" stroke="${stroke}" stroke-width="${w}" stroke-linejoin="round"/>`
       + `<rect x="11" y="22" width="12" height="53" rx="6" fill="none" stroke="${stroke}" stroke-width="${w}" stroke-linejoin="round"/>`;
}
function clipWire(c) {
  return `<g transform="translate(0.5,0.8)" opacity="${c.shadowO}">${clipRects(c.shadow, c.bodyW + 0.2)}</g>`
       + `<g>${clipRects("url(#" + c.grad + ")", c.bodyW)}</g>`
       + `<g transform="translate(-0.5,-0.8)" opacity="${c.glintO}">${clipRects(c.glint, c.glintW)}</g>`;
}
function clipSvg(cls) { return `<svg class="clip ${cls}" viewBox="0 0 34 86" aria-hidden="true">${clipWire(CLIP_CFG)}</svg>`; }
function clipDefs() {
  return `<svg class="clip-defs" width="0" height="0" aria-hidden="true"><defs>
    <linearGradient id="brassA" x1="0.08" y1="0" x2="0.92" y2="0.15">
      <stop offset="0" stop-color="#4a3708"/><stop offset=".18" stop-color="#8f6f1e"/>
      <stop offset=".40" stop-color="#f6ebc0"/><stop offset=".50" stop-color="#e6cd7d"/>
      <stop offset=".62" stop-color="#b8902f"/><stop offset=".82" stop-color="#6f5314"/>
      <stop offset="1" stop-color="#3d2e07"/></linearGradient></defs></svg>`;
}

// The finished-dish photo (top-right of the masthead) as a Polaroid straddling the recipe card's top
// edge, held by a brass clip. The strip is empty for now (the typed caption is a separate feature).
// No image: an EDITABLE recipe gets an empty clipped Polaroid "+ add a photo" affordance (links to the
// edit flow); a non-editable (seed) recipe returns "" so the masthead collapses to a full-width title.
// A broken URL collapses via the <img> onerror (adds .no-photo to the stage, removes the Polaroid).
function dishPhoto(r, editable) {
  if (r.image) return `<div class="dish-photo polaroid-hero">
    ${clipDefs()}
    ${clipSvg("back")}
    <div class="edge-contact"></div>
    <figure class="polaroid-wrap"><span class="polaroid">
      <img class="photo" src="/${esc(r.image)}" alt="${esc(r.name)}" loading="lazy"
        onerror="this.closest('.recipe-stage').classList.add('no-photo'); this.closest('.dish-photo').remove();">
      <span class="strip"></span>
    </span></figure>
    ${clipSvg("front")}
  </div>`;
  if (editable) return `<a class="dish-photo polaroid-hero polaroid-empty" href="#/edit/${encodeURIComponent(r.id)}" aria-label="Add a photo">
    ${clipDefs()}
    ${clipSvg("back")}
    <div class="edge-contact"></div>
    <span class="polaroid-wrap"><span class="polaroid">
      <span class="photo"><span class="add-photo-mark">+</span><span class="add-label">add a photo</span></span>
      <span class="strip"></span>
    </span></span>
    ${clipSvg("front")}
  </a>`;
  return "";   // seed recipe with no photo: collapse (seed recipes aren't editable — no dead add link)
}

// The owner Edit/Delete row, and the inline two-step delete confirmation it swaps to. The
// confirmation names the recipe and needs a deliberate second click (replaces a single confirm()).
function ownerActionsHTML(r) {
  return `<a class="btn ghost sm" href="#/edit/${encodeURIComponent(r.id)}">Edit recipe</a>
          <button class="btn danger-soft sm" data-delete>Delete recipe</button>`;
}
function deleteConfirmHTML(r) {
  return `<span class="delete-confirm">
    <span class="dc-msg">Delete <strong>${esc(r.name)}</strong>? This can't be undone.</span>
    <button class="btn ghost sm danger" data-delete-confirm>Delete</button>
    <button class="btn ghost sm" data-delete-cancel>Cancel</button>
  </span>`;
}

async function renderRecipe(rid) {
  const data = await api("/api/recipes/" + encodeURIComponent(rid));
  view = { slug: rid, data, mode: "original", editingPos: null, addingOpen: false, scale: 1, pendingRating: null, undoneCook: null };
  app.className = "page recipe-view";
  setCookCount(app, data.stats.cook_count);   // reserved R2 wear signal on the recipe root
  const r = data.recipe;

  // Seed recipes let people add ingredients to their version, so load the library
  // now to fill the "link to an ingredient" picker in the add form.
  if (data.is_seed) {
    try { INGREDIENT_LIST = await api("/api/ingredients"); }
    catch (_) { INGREDIENT_LIST = []; }
  }

  const photoSlot = dishPhoto(r, data.is_editable);

  const owner = data.is_editable ? `<div class="owner-actions">${ownerActionsHTML(r)}</div>` : "";

  // The recipe content lives inside an inner card (.detail-card) so the Polaroid has a real top edge
  // to straddle and the clip.back can tuck behind it. The Polaroid assembly (photoSlot) is a SIBLING
  // of the card inside .recipe-stage — not inside the masthead — so its z-layers straddle the card
  // edge. The ← back-link stays outside/above the card.
  app.innerHTML = `
    <a class="back" href="#/">← All recipes</a>
    <div class="recipe-stage${photoSlot ? "" : " no-photo"}">
      ${photoSlot}
      <div class="detail-card">
        <header class="masthead${data.is_test ? " is-test" : ""}">
          <div class="masthead-text">
            ${bylineHTML(r)}
            <h1 class="recipe-title">${esc(r.name)}${data.is_test ? ` <span class="test-badge">Test</span>` : ""}</h1>
            ${r.descr ? `<div class="headnote"><p class="dek clamped">${esc(r.descr)}</p><button class="dek-more" data-dek-toggle hidden>more</button></div>` : ""}
            ${tagsHTML(r)}
          </div>
        </header>
        <div class="vitals">
          ${metaLine(r)}
          <div class="scaler-line" id="scaler-host">${scaleControl()}</div>
          <div class="stats cook-block" data-rid="${esc(r.id)}">${statsInner(data.stats)}</div>
          ${owner}
        </div>
        <div class="recipe-cols">
          <section id="ing-section">${ingredientsSectionInner(view)}</section>
          <section>
            <h2 class="col-title">Method</h2>
            <ol class="steps" id="steps-list">${data.steps.map(renderStepRow).join("")}</ol>
            ${r.notes ? `<div class="notes"><strong>Note.</strong> ${esc(r.notes)}</div>` : ""}
          </section>
        </div>
      </div>
    </div>`;

  if (document.fonts && document.fonts.ready) document.fonts.ready.then(setupHeadnote);
  else setupHeadnote();
}

// ---- saving per-person changes (everything goes through the change endpoints) ----

// The shared URL prefix for the open recipe + active person. pid is always view.mode,
// because the editing controls only ever appear inside a person's view.
function changeBase() {
  return `/api/recipes/${encodeURIComponent(view.slug)}/people/${encodeURIComponent(view.mode)}`;
}

// Apply a server response (each change endpoint returns the full {changes} map) to the
// open view, then re-render just the ingredient list.
function applyChanges(res, closeAddForm) {
  if (res.ok) {
    view.data.changes = res.data.changes || {};
    view.editingPos = null;
    if (closeAddForm) view.addingOpen = false;
    rerenderIngredients();
  } else {
    alert((res.data && res.data.error) || "Couldn't save that change.");
  }
}

async function saveLineEdit(pos) {
  const input = document.querySelector(".le-qty");
  const qty = input ? input.value.trim() : "";
  if (!qty) { if (input) input.focus(); return; }            // a quantity is required
  applyChanges(await sendJSON("PUT", `${changeBase()}/lines/${pos}`, { kind: "edit", qty }));
}

async function removeLine(pos) {
  applyChanges(await sendJSON("PUT", `${changeBase()}/lines/${pos}`, { kind: "remove" }));
}

// Used by both Reset (undo an edit) and Restore (undo a removal) — same DELETE.
async function clearLine(pos) {
  applyChanges(await sendJSON("DELETE", `${changeBase()}/lines/${pos}`));
}

async function saveAddition() {
  const item = (document.querySelector(".af-link") || {}).value || "";
  const qty = ((document.querySelector(".af-qty") || {}).value || "").trim();
  const text = ((document.querySelector(".af-text") || {}).value || "").trim();
  const note = ((document.querySelector(".af-note") || {}).value || "").trim();
  const section = (document.querySelector(".af-section") || {}).value || "";   // "" if recipe has no sections
  if (!item && !text) { const t = document.querySelector(".af-text"); if (t) t.focus(); return; }
  // Linked: send the ingredient key + an optional custom label. Plain: just the text.
  const body = item ? { qty, item, label: text, note, section } : { qty, text, section };
  applyChanges(await sendJSON("POST", `${changeBase()}/additions`, body), true);
}

async function deleteAddition(addId) {
  applyChanges(await sendJSON("DELETE", `${changeBase()}/additions/${addId}`));
}

// The actual delete, run only after the inline two-step confirmation (data-delete-confirm).
async function doDelete() {
  const res = await sendJSON("DELETE", "/api/recipes/" + encodeURIComponent(view.slug));
  if (res.ok) location.hash = "#/";
  else alert((res.data && res.data.error) || "Couldn't delete the recipe.");
}

/* ---------- create / edit form ---------- */

function ingOptions(selected) {
  return INGREDIENT_LIST
    .map((i) => `<option value="${esc(i.id)}"${i.id === selected ? " selected" : ""}>${esc(i.name)}</option>`)
    .join("");
}

// One editable ingredient row. `o` pre-fills it (used when editing an existing recipe).
function ingRow(o) {
  o = o || {};
  const heading = (o.type || "line") === "heading";
  return `<div class="ed-row">
    <select class="ed-type">
      <option value="line"${heading ? "" : " selected"}>Ingredient</option>
      <option value="heading"${heading ? " selected" : ""}>Heading</option>
    </select>
    <span class="ed-fields ed-line"${heading ? ' style="display:none"' : ""}>
      <input class="ed-qty" placeholder="qty" value="${esc(o.qty || "")}">
      <select class="ed-link"><option value="">— plain text —</option>${ingOptions(o.link || "")}</select>
      <input class="ed-text" placeholder="ingredient / text" value="${esc(o.text || "")}">
      <input class="ed-note" placeholder="note (optional)" value="${esc(o.note || "")}">
    </span>
    <span class="ed-fields ed-head"${heading ? "" : ' style="display:none"'}>
      <input class="ed-heading-field" placeholder="section heading (e.g. For the sauce)" value="${esc(o.heading || "")}">
    </span>
    <button type="button" class="ed-remove" title="Remove" aria-label="Remove">×</button>
  </div>`;
}

function stepRow(o) {
  o = o || {};
  const heading = (o.type || "step") === "heading";
  return `<div class="ed-row">
    <select class="ed-type">
      <option value="step"${heading ? "" : " selected"}>Step</option>
      <option value="heading"${heading ? " selected" : ""}>Heading</option>
    </select>
    <span class="ed-fields ed-line"${heading ? ' style="display:none"' : ""}>
      <textarea class="ed-step-field" rows="2" placeholder="Step text. Link a library ingredient as [[garlic]] or [[garlic|crushed garlic]].">${esc(o.text || "")}</textarea>
    </span>
    <span class="ed-fields ed-head"${heading ? "" : ' style="display:none"'}>
      <input class="ed-heading-field" placeholder="section heading (e.g. To serve)" value="${esc(o.heading || "")}">
    </span>
    <button type="button" class="ed-remove" title="Remove" aria-label="Remove">×</button>
  </div>`;
}

// Convert a saved DB row back into a pre-filled editor row (for the edit form).
function ingToRow(x) {
  if (x.is_heading) return ingRow({ type: "heading", heading: x.raw_text });
  if (x.ingredient_id) return ingRow({ type: "line", qty: x.qty, link: x.ingredient_id, text: x.label || x.raw_text, note: x.note });
  return ingRow({ type: "line", qty: x.qty, text: x.label || x.raw_text });
}
function stepToRow(x) {
  if (x.is_heading) return stepRow({ type: "heading", heading: x.text });
  return stepRow({ type: "step", text: x.text });
}

async function renderForm(mode, slug) {
  view = null;
  app.className = "page form-view";
  let pre = {};
  let ingRowsHTML = ingRow({ type: "line" });
  let stepRowsHTML = stepRow({ type: "step" });

  try { INGREDIENT_LIST = await api("/api/ingredients"); }
  catch (_) { INGREDIENT_LIST = []; }

  if (mode === "edit") {
    let data;
    try { data = await api("/api/recipes/" + encodeURIComponent(slug)); }
    catch (err) { showError(err); return; }
    if (!data.is_editable) {
      app.innerHTML = `
        <a class="back" href="#/recipe/${encodeURIComponent(slug)}">← Back to recipe</a>
        <div class="notice">
          <h2>This recipe is read-only</h2>
          <p>“${esc(data.recipe.name)}” comes from <code>seed.py</code>, so it's edited there rather than in the app. You can still note your own per-line changes on the recipe page.</p>
        </div>`;
      return;
    }
    pre = data.recipe;
    ingRowsHTML = data.ingredients.length ? data.ingredients.map(ingToRow).join("") : ingRow({ type: "line" });
    stepRowsHTML = data.steps.length ? data.steps.map(stepToRow).join("") : stepRow({ type: "step" });
  }

  const cancelHref = mode === "edit" ? "#/recipe/" + encodeURIComponent(slug) : "#/";
  app.innerHTML = `
    <a class="back" href="${cancelHref}">← ${mode === "edit" ? "Back to recipe" : "All recipes"}</a>
    <h1 class="recipe-title">${mode === "edit" ? "Edit recipe" : "New recipe"}</h1>
    <p id="form-error" class="form-error" hidden></p>
    <div class="form">
      <div class="field-grid">
        <label class="field span2"><span>Name *</span><input id="f-name" value="${esc(pre.name || "")}"></label>
        <label class="field"><span>Author / source</span><input id="f-author" value="${esc(pre.author || "")}"></label>
        <label class="field"><span>Category</span><input id="f-category" value="${esc(pre.category || "")}"></label>
        <label class="field"><span>Servings</span><input id="f-servings" value="${esc(pre.servings || "")}"></label>
        <label class="field"><span>Prep time</span><input id="f-prep" value="${esc(pre.prep_time || "")}"></label>
        <label class="field"><span>Cook time</span><input id="f-cook" value="${esc(pre.cook_time || "")}"></label>
        <label class="field"><span>Total time</span><input id="f-total" value="${esc(pre.total_time || "")}"></label>
        <label class="field span2"><span>Image path (optional, e.g. images/my-recipe.jpg)</span><input id="f-image" value="${esc(pre.image || "")}"></label>
        <label class="field span2"><span>Description</span><textarea id="f-descr" rows="2">${esc(pre.descr || "")}</textarea></label>
        <label class="field span2"><span>Note (optional)</span><textarea id="f-notes" rows="2">${esc(pre.notes || "")}</textarea></label>
        ${mode === "create" ? `<label class="field span2 test-toggle"><input type="checkbox" id="f-test"> <span>Make this a test recipe <em>— a scratch recipe you can bulk-delete later (can't be changed after creating)</em></span></label>` : ""}
      </div>

      <div class="editor-block">
        <div class="col-head"><h2 class="col-title">Ingredients</h2></div>
        <div id="ing-editor">${ingRowsHTML}</div>
        <div class="editor-actions">
          <button type="button" class="btn ghost sm" id="add-ing">+ Ingredient</button>
          <button type="button" class="btn ghost sm" id="add-ing-head">+ Heading</button>
        </div>
      </div>

      <div class="editor-block">
        <div class="col-head"><h2 class="col-title">Method</h2></div>
        <div id="step-editor">${stepRowsHTML}</div>
        <div class="editor-actions">
          <button type="button" class="btn ghost sm" id="add-step">+ Step</button>
          <button type="button" class="btn ghost sm" id="add-step-head">+ Heading</button>
        </div>
        <p class="hint">Link a library ingredient inside a step by writing it as <code>[[garlic]]</code>. New ingredients can just be typed as plain text.</p>
      </div>

      <div class="form-save">
        <button type="button" class="btn" id="save-recipe">${mode === "edit" ? "Save changes" : "Create recipe"}</button>
        <a class="btn ghost" href="${cancelHref}">Cancel</a>
      </div>
    </div>`;

  wireForm(mode, slug);
}

// Attach the form's own listeners (kept local to the form rather than in the global
// click handler, since these only exist while the form is on screen).
function wireForm(mode, slug) {
  const ingEd = document.getElementById("ing-editor");
  const stepEd = document.getElementById("step-editor");

  [ingEd, stepEd].forEach((container) => {
    container.addEventListener("change", (e) => {
      if (e.target.classList.contains("ed-type")) {
        const row = e.target.closest(".ed-row");
        const heading = e.target.value === "heading";
        row.querySelector(".ed-line").style.display = heading ? "none" : "";
        row.querySelector(".ed-head").style.display = heading ? "" : "none";
      }
      if (e.target.classList.contains("ed-link")) {
        const row = e.target.closest(".ed-row");
        const text = row.querySelector(".ed-text");
        const opt = e.target.selectedOptions[0];
        if (e.target.value && text && !text.value.trim()) text.value = opt.textContent;
      }
    });
    container.addEventListener("click", (e) => {
      if (e.target.closest(".ed-remove")) e.target.closest(".ed-row").remove();
    });
  });

  document.getElementById("add-ing").addEventListener("click", () => ingEd.insertAdjacentHTML("beforeend", ingRow({ type: "line" })));
  document.getElementById("add-ing-head").addEventListener("click", () => ingEd.insertAdjacentHTML("beforeend", ingRow({ type: "heading" })));
  document.getElementById("add-step").addEventListener("click", () => stepEd.insertAdjacentHTML("beforeend", stepRow({ type: "step" })));
  document.getElementById("add-step-head").addEventListener("click", () => stepEd.insertAdjacentHTML("beforeend", stepRow({ type: "heading" })));
  document.getElementById("save-recipe").addEventListener("click", () => onSaveForm(mode, slug));
}

function gatherPayload() {
  const val = (id) => (document.getElementById(id)?.value || "").trim();
  const payload = {
    name: val("f-name"), author: val("f-author"), category: val("f-category"),
    servings: val("f-servings"), prep_time: val("f-prep"), cook_time: val("f-cook"),
    total_time: val("f-total"), image: val("f-image"), descr: val("f-descr"),
    notes: val("f-notes"), ingredients: [], steps: [],
    is_test: !!document.getElementById("f-test")?.checked,   // create-only; PUT ignores it
  };

  document.querySelectorAll("#ing-editor .ed-row").forEach((row) => {
    if (row.querySelector(".ed-type").value === "heading") {
      const h = row.querySelector(".ed-heading-field").value.trim();
      if (h) payload.ingredients.push({ heading: h });
    } else {
      const qty = row.querySelector(".ed-qty").value.trim();
      const link = row.querySelector(".ed-link").value;
      const text = row.querySelector(".ed-text").value.trim();
      const note = row.querySelector(".ed-note").value.trim();
      if (link) payload.ingredients.push({ qty, item: link, label: text || link, note });
      else if (text) payload.ingredients.push({ qty, text });
    }
  });

  document.querySelectorAll("#step-editor .ed-row").forEach((row) => {
    if (row.querySelector(".ed-type").value === "heading") {
      const h = row.querySelector(".ed-heading-field").value.trim();
      if (h) payload.steps.push({ heading: h });
    } else {
      const t = row.querySelector(".ed-step-field").value.trim();
      if (t) payload.steps.push(t);
    }
  });

  return payload;
}

function showFormError(msg) {
  const el = document.getElementById("form-error");
  if (!el) return;
  el.textContent = msg;
  el.hidden = false;
  window.scrollTo(0, 0);
}

async function onSaveForm(mode, slug) {
  const payload = gatherPayload();
  if (!payload.name) { showFormError("Please give the recipe a name."); return; }
  const res = mode === "create"
    ? await sendJSON("POST", "/api/recipes", payload)
    : await sendJSON("PUT", "/api/recipes/" + encodeURIComponent(slug), payload);
  if (res.ok) location.hash = "#/recipe/" + encodeURIComponent(res.data.id);
  else showFormError((res.data && res.data.error) || ("Couldn't save (HTTP " + res.status + ")."));
}

/* ---------- error state ---------- */
function showError(err) {
  app.innerHTML = `
    <div class="notice">
      <h2>Couldn't reach the kitchen</h2>
      <p>The page loaded but the data request failed (${esc(err.message)}). The
         most common cause is that the backend isn't running. In this folder,
         start it with:</p>
      <pre>pip install flask
python3 app.py</pre>
      <p>Then open <code>http://localhost:8000</code>. If you haven't built the
         database yet, run <code>python3 build_db.py</code> first.</p>
    </div>`;
}

/* ---------- ingredient drawer ---------- */
const scrim = document.querySelector(".scrim");
const panel = document.querySelector(".panel");
const closeBtn = document.querySelector(".panel-close");
let lastTrigger = null;

function buildSeason(months) {
  if (!months || !months.length) {
    return `<p class="season-none">A pantry staple — available year-round.</p>`;
  }
  const strip = MONTHS.map((label, i) => {
    const on = months.includes(i + 1) ? " in" : "";
    return `<div class="month${on}"><div class="bar"></div><div class="m">${label}</div></div>`;
  }).join("");
  return `<div class="season-strip">${strip}</div>`;
}

async function openPanel(key, trigger) {
  lastTrigger = trigger || null;
  let item;
  try {
    item = await api("/api/ingredients/" + encodeURIComponent(key));
  } catch {
    return;
  }

  panel.querySelector(".panel-name").textContent = item.name;
  panel.querySelector(".panel-desc").textContent = item.descr || "";
  panel.querySelector(".season-host").innerHTML = buildSeason(item.season);
  panel.querySelector(".regions").innerHTML =
    (item.regions || []).map((r) => `<span class="tag">${esc(r)}</span>`).join("");
  panel.querySelector(".pairs").textContent = item.pairs || "";

  const used = item.used_in || [];
  panel.querySelector(".used-block").style.display = used.length ? "" : "none";
  panel.querySelector(".used-list").innerHTML = used
    .map((u) => `<li><button data-recipe="${esc(u.id)}">${esc(u.name)}</button></li>`)
    .join("");

  scrim.hidden = false;
  panel.hidden = false;
  // Make the elements visible first, then on the next screen refresh add the
  // "open" class — that two-step lets the CSS slide-in animation actually play
  // (animating from hidden to shown in one step would just snap).
  requestAnimationFrame(() => {
    scrim.classList.add("open");
    panel.classList.add("open");
  });
  closeBtn.focus();
}

function closePanel() {
  scrim.classList.remove("open");
  panel.classList.remove("open");
  setTimeout(() => {
    scrim.hidden = true;
    panel.hidden = true;
  }, 260);
  if (lastTrigger) lastTrigger.focus();
}

/* ---------- Backdate-a-cook modal ---------- */
// Reuses the shared .scrim as its backdrop (the ingredient panel uses the same element; only
// one dialog is ever open at a time). A hand-built calendar + an MM/DD/YYYY type field share
// one selected date; the app stores YYYY-MM-DD, so we convert at the edges.
const backdateModal = document.querySelector(".backdate-modal");
const BD_MONTHS = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"];
const BD_DOW = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
let backdateTrigger = null;   // the button that opened it (focus returns here)
let backdateStats = null;     // the .stats element to re-render on a successful log
let backdateRid = null;
let bdCal = null;             // the live calendar controller
let bdYearPopClose = null;    // close() of the open year popover (Escape routes through it), else null

const isoToDisplay = (iso) => { const [y, m, d] = iso.split("-"); return `${m}/${d}/${y}`; };
function displayToISO(s) {
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec((s || "").trim());
  if (!m) return null;
  const mo = Number(m[1]), da = Number(m[2]), yr = Number(m[3]);
  const iso = `${yr}-${String(mo).padStart(2, "0")}-${String(da).padStart(2, "0")}`;
  // reject non-real dates (e.g. 02/31/2024) by round-tripping through Date
  const dt = new Date(yr, mo - 1, da);
  if (dt.getFullYear() !== yr || dt.getMonth() !== mo - 1 || dt.getDate() !== da) return null;
  return iso;
}

// A vanilla month calendar. onPick(iso) fires when a day is chosen. Future days are disabled;
// month + year are jumpable via <select>s (year never past the current year; a future month in
// the current year is clamped back), plus ‹ › month stepping.
function makeBackdateCalendar(hostEl, onPick) {
  const today = todayISO();                       // 'YYYY-MM-DD', local (reused helper)
  const [ty, tm] = today.split("-").map(Number);  // today's year, month (1-12)
  let viewY = ty, viewM = tm - 1;                 // viewM is 0-based
  let selectedISO = null;

  const clampView = () => { if (viewY === ty && viewM > tm - 1) viewM = tm - 1; };  // never past current month
  const BD_MIN_Y = 1990;

  function setYear(y) {                        // used by both year-popover paths (grid + typed)
    viewY = Math.max(BD_MIN_Y, Math.min(ty, y));
    clampView();
    render();                                  // rebuilds the header, so the popover closes with it
  }
  function yearCells() {
    let out = "";
    for (let y = ty; y >= BD_MIN_Y; y--) {
      out += `<button class="bd-year-cell${y === viewY ? " on" : ""}" data-y="${y}">${y}</button>`;
    }
    return out;
  }
  function render() {
    clampView();
    const startDow = new Date(viewY, viewM, 1).getDay();
    const daysInMonth = new Date(viewY, viewM + 1, 0).getDate();
    let cells = BD_DOW.map((d) => `<div class="bd-dow">${d}</div>`).join("");
    for (let i = 0; i < startDow; i++) cells += `<button class="bd-day empty" tabindex="-1" disabled></button>`;
    for (let day = 1; day <= daysInMonth; day++) {
      const iso = `${viewY}-${String(viewM + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      const cls = ["bd-day"];
      if (iso === selectedISO) cls.push("sel");
      if (iso === today) cls.push("today");
      cells += `<button class="${cls.join(" ")}" data-iso="${iso}"${iso > today ? " disabled" : ""}>${day}</button>`;
    }
    const nextDisabled = (viewY >= ty && viewM >= tm - 1);   // can't step into a future month
    hostEl.innerHTML = `
      <div class="bd-cal-head">
        <span class="bd-monthnav">
          <button class="bd-nav" data-nav="-1" aria-label="Previous month">‹</button>
          <span class="bd-month-label">${BD_MONTHS[viewM]}</span>
          <button class="bd-nav" data-nav="1"${nextDisabled ? " disabled" : ""} aria-label="Next month">›</button>
        </span>
        <span class="bd-year-anchor">
          <button class="bd-yearpill" aria-haspopup="true" aria-expanded="false">${viewY} ▾</button>
          <span class="bd-year-pop" role="dialog" aria-label="Choose year">
            <input class="bd-year-input" type="text" inputmode="numeric" maxlength="4"
                   value="${viewY}" aria-label="Jump to year">
            <div class="bd-year-grid">${yearCells()}</div>
          </span>
        </span>
      </div>
      <div class="bd-grid">${cells}</div>`;
    hostEl.querySelectorAll("[data-nav]").forEach((b) => b.onclick = () => {
      if (b.disabled) return;
      viewM += Number(b.dataset.nav);
      if (viewM < 0) { viewM = 11; viewY--; } else if (viewM > 11) { viewM = 0; viewY++; }
      if (viewY < BD_MIN_Y) { viewY = BD_MIN_Y; viewM = 0; }
      if (viewY > ty) { viewY = ty; viewM = tm - 1; }
      render();
    });
    hostEl.querySelectorAll(".bd-day[data-iso]").forEach((b) => b.onclick = () => {
      if (b.disabled) return;
      selectedISO = b.dataset.iso; render(); onPick(selectedISO);
    });
    wireYearPopover(hostEl, setYear);
  }
  render();
  return {
    getSelected: () => selectedISO,
    setSelected(iso, moveView) {
      selectedISO = iso;
      if (moveView && iso) { const [y, m] = iso.split("-").map(Number); viewY = y; viewM = m - 1; }
      render();
    },
  };
}

// Wire the year pill + popover of a freshly-rendered calendar header. Both ways in — the grid
// and the typed year — call setYear(), which re-renders (closing the popover with it). Handles
// open/close, scroll-to-selection, click-outside, and exposes close() via bdYearPopClose so the
// modal's Escape can close the popover first (a second Escape then closes the modal).
function wireYearPopover(hostEl, setYear) {
  const pill = hostEl.querySelector(".bd-yearpill");
  const pop = hostEl.querySelector(".bd-year-pop");
  const input = hostEl.querySelector(".bd-year-input");
  if (!pill || !pop) return;
  const shownYear = () => pill.textContent.replace(/\D/g, "");
  let onDocClick = null;
  function close() {
    pop.classList.remove("open");
    pill.setAttribute("aria-expanded", "false");
    if (onDocClick) { document.removeEventListener("click", onDocClick); onDocClick = null; }
    if (bdYearPopClose === close) bdYearPopClose = null;
  }
  function open() {
    pop.classList.add("open");
    pill.setAttribute("aria-expanded", "true");
    pop.querySelector(".bd-year-cell.on")?.scrollIntoView({ block: "center" });
    input.focus(); input.select();
    onDocClick = () => close();
    setTimeout(() => { if (onDocClick) document.addEventListener("click", onDocClick); }, 0); // skip opening click
    bdYearPopClose = close;
  }
  const choose = (y) => { close(); setYear(y); };   // close first (drops the doc listener), then re-render
  const commit = () => {
    // Ignore the blur that fires when render() tears down the focused year-input (a deferred
    // teardown-blur would otherwise re-commit a stale value and snap the view back — the popover
    // is already closed by then, so a real commit can only happen while it's open).
    if (!pop.classList.contains("open")) return;
    const y = parseInt(input.value, 10);
    const cur = new Date().getFullYear();
    if (!isNaN(y) && y >= 1990 && y <= cur) choose(y);
    else input.value = shownYear();                 // out-of-range -> revert to the shown year
  };
  pill.addEventListener("click", (e) => { e.stopPropagation(); pop.classList.contains("open") ? close() : open(); });
  pop.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("input", () => { input.value = input.value.replace(/[^0-9]/g, ""); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } });
  input.addEventListener("blur", commit);
  hostEl.querySelectorAll(".bd-year-cell").forEach((b) => {
    b.addEventListener("mousedown", (e) => e.preventDefault());  // keep input focus -> no premature blur-commit
    b.onclick = () => choose(Number(b.dataset.y));
  });
}

function openBackdate(rid, statsEl, trigger) {
  backdateRid = rid;
  backdateStats = statsEl;
  backdateTrigger = trigger || null;
  const typed = backdateModal.querySelector("[data-bd-typed]");
  const errEl = backdateModal.querySelector("[data-bd-error]");
  errEl.textContent = "";
  typed.value = "";
  bdCal = makeBackdateCalendar(backdateModal.querySelector("[data-bd-cal]"),
    (iso) => { typed.value = isoToDisplay(iso); errEl.textContent = ""; });
  typed.oninput = () => {
    errEl.textContent = "";
    const iso = displayToISO(typed.value);
    if (iso && iso <= todayISO()) bdCal.setSelected(iso, true);
  };
  scrim.hidden = false;
  backdateModal.hidden = false;
  requestAnimationFrame(() => {
    scrim.classList.add("open");
    backdateModal.classList.add("open");
  });
  backdateModal.querySelector("[data-backdate-close]").focus();
}

function closeBackdate() {
  scrim.classList.remove("open");
  backdateModal.classList.remove("open");
  setTimeout(() => {
    scrim.hidden = true;
    backdateModal.hidden = true;
  }, 260);
  if (backdateTrigger && document.contains(backdateTrigger)) backdateTrigger.focus();
}

async function submitBackdate() {
  const errEl = backdateModal.querySelector("[data-bd-error]");
  const iso = bdCal ? bdCal.getSelected() : null;
  if (!iso) { errEl.textContent = "Pick or type a date first."; return; }
  const { ok, data } = await sendJSON("POST", `/api/recipes/${backdateRid}/cooked`, { date: iso });
  if (ok) {
    if (view) view.undoneCook = null;   // logging a (backdated) cook ends any redo window
    if (view && view.data) view.data.stats = data;
    const statsEl = backdateStats;
    closeBackdate();
    if (statsEl) {
      statsEl.innerHTML = statsInner(data);
      setCookCount(app, data.cook_count);
      statsEl.querySelector("[data-backdate-open]")?.focus();
    }
  } else {
    errEl.textContent = (data && data.error) || "Could not log that date.";
  }
}

/* ---------- events ---------- */
// One click listener for the whole page (instead of attaching one to every button,
// which is impossible here since the buttons are rebuilt constantly). When any click
// happens, we look at what was clicked — e.target.closest("X") finds the nearest
// matching element at or above the click — and act on the first kind we recognize.
document.addEventListener("click", (e) => {
  // Bulk-delete all test recipes (home header) — inline two-step confirm, like the recipe delete.
  const bulk = document.getElementById("test-bulk");
  if (e.target.closest("[data-delete-test]")) {
    bulk.innerHTML = `<span class="delete-confirm">Delete all test recipes?
      <button class="btn ghost sm danger" data-delete-test-confirm>Delete all</button>
      <button class="btn ghost sm" data-delete-test-cancel>Cancel</button></span>`;
    return;
  }
  if (e.target.closest("[data-delete-test-cancel]")) { renderHome(); return; }
  if (e.target.closest("[data-delete-test-confirm]")) {
    (async () => {
      const { ok } = await sendJSON("DELETE", "/api/test-recipes", null);
      if (ok) renderHome();
    })();
    return;
  }

  // rating / cooking actions live inside the stats bar on a recipe page
  const stats = e.target.closest(".stats");
  if (stats) {
    const rid = encodeURIComponent(stats.dataset.rid);
    const cookCount = (view && view.data.stats) ? view.data.stats.cook_count : 0;
    const rate = e.target.closest("[data-rate]");
    if (rate) {
      const n = Number(rate.dataset.rate);
      if (cookCount >= 1) {                       // already cooked -> rate directly, no confirm
        if (view) view.pendingRating = null;
        updateStats(stats, `/api/recipes/${rid}/rating`, { rating: n });
      } else {                                    // uncooked -> gate: hold the rating, ask to confirm a cook
        if (view) { view.pendingRating = n; view.undoneCook = null; }   // rating is another action -> ends redo window
        stats.innerHTML = statsInner(view ? view.data.stats : { cook_count: 0 });
      }
      return;
    }
    if (e.target.closest("[data-cook-rate-confirm]")) {
      const n = view ? view.pendingRating : null;
      if (view) view.pendingRating = null;
      updateStats(stats, `/api/recipes/${rid}/cooked-and-rated`, { rating: n });
      return;
    }
    if (e.target.closest("[data-cook-rate-cancel]")) {
      if (view) { view.pendingRating = null; view.undoneCook = null; }
      stats.innerHTML = statsInner(view ? view.data.stats : { cook_count: 0 });
      return;
    }
    if (e.target.closest("[data-cook]"))   { if (view) view.pendingRating = null; updateStats(stats, `/api/recipes/${rid}/cooked`, {}); return; }
    if (e.target.closest("[data-uncook]")) {
      if (view) view.pendingRating = null;
      (async () => {
        const { ok, data } = await sendJSON("POST", `/api/recipes/${rid}/uncook`, {});
        if (!ok) return;
        if (view && view.data) view.data.stats = data;
        // remember exactly what was removed so Redo can restore it (this OPENS the one-shot redo window)
        if (view) view.undoneCook = data.undone ? { rid: stats.dataset.rid, ...data.undone } : null;
        stats.innerHTML = statsInner(data);
        setCookCount(app, data.cook_count);
      })();
      return;
    }
    if (e.target.closest("[data-redo]")) {
      const u = view ? view.undoneCook : null;
      if (!u || u.rid !== stats.dataset.rid) return;   // guard: never redo against the wrong recipe
      (async () => {
        const body = { cooked_on: u.cooked_on, source: u.source };
        if (u.cleared_rating != null) body.rating = u.cleared_rating;   // restore only if the undo cleared one
        const { ok, data } = await sendJSON("POST", `/api/recipes/${rid}/redo-cook`, body);
        if (!ok) return;
        if (view) view.undoneCook = null;              // redo consumed -> back to plain "Undo"
        if (view && view.data) view.data.stats = data;
        stats.innerHTML = statsInner(data);
        setCookCount(app, data.cook_count);
      })();
      return;
    }
    if (e.target.closest("[data-backdate-open]")) {
      if (view) view.undoneCook = null;                // opening the modal ends the redo window
      stats.innerHTML = statsInner(view ? view.data.stats : { cook_count: 0 });   // repaint now so the Undo/Redo pair collapses to plain "Undo"
      openBackdate(rid, stats, e.target.closest("[data-backdate-open]"));
      return;
    }
  }

  // headnote "more" / "less" expander (long imported descriptions)
  const dekToggle = e.target.closest("[data-dek-toggle]");
  if (dekToggle) {
    const dek = app.querySelector(".dek");
    if (dek) dekToggle.textContent = dek.classList.toggle("clamped") ? "more" : "less";
    return;
  }

  // recipe-detail interactions: app-recipe delete + the per-person change layers
  if (view) {
    // Delete: a deliberate two-step — first click swaps to an inline confirm that names the
    // recipe; only data-delete-confirm actually deletes (data-delete-cancel restores the row).
    if (e.target.closest("[data-delete]")) {
      const oa = e.target.closest(".owner-actions");
      if (oa) oa.innerHTML = deleteConfirmHTML(view.data.recipe);
      return;
    }
    if (e.target.closest("[data-delete-cancel]")) {
      const oa = e.target.closest(".owner-actions");
      if (oa) oa.innerHTML = ownerActionsHTML(view.data.recipe);
      return;
    }
    if (e.target.closest("[data-delete-confirm]")) { doDelete(); return; }

    // scale control: re-scale every displayed quantity
    const scale = e.target.closest("[data-scale]");
    if (scale) {
      view.scale = parseFloat(scale.dataset.scale);
      rerenderIngredients();
      rerenderSteps();
      rerenderServings();
      rerenderScaler();      // scaler lives in the vitals now — refresh its own host (active pill)
      return;
    }

    // view switcher: Original / a person / Compare all
    const seg = e.target.closest("[data-view]");
    if (seg) {
      view.mode = seg.dataset.view;
      view.editingPos = null;
      view.addingOpen = false;
      rerenderIngredients();
      return;
    }

    // open / cancel the inline quantity editor on a line
    const edit = e.target.closest("[data-edit-line]");
    if (edit) {
      view.editingPos = Number(edit.dataset.pos);
      rerenderIngredients();
      const inp = document.querySelector(".le-qty");
      if (inp) { inp.focus(); inp.select(); }
      return;
    }
    if (e.target.closest("[data-cancel-line]")) { view.editingPos = null; rerenderIngredients(); return; }

    // save an edit / remove a line / clear a change (Reset or Restore)
    const save = e.target.closest("[data-save-edit]");
    if (save) { saveLineEdit(Number(save.dataset.pos)); return; }
    const rem = e.target.closest("[data-remove-line]");
    if (rem) { removeLine(Number(rem.dataset.pos)); return; }
    const clr = e.target.closest("[data-clear-line]");
    if (clr) { clearLine(Number(clr.dataset.pos)); return; }

    // the add-ingredient form: open / cancel / save, and delete an existing addition
    if (e.target.closest("[data-add-open]")) {
      view.addingOpen = true;
      rerenderIngredients();
      const q = document.querySelector(".af-qty");
      if (q) q.focus();
      return;
    }
    if (e.target.closest("[data-add-cancel]")) { view.addingOpen = false; rerenderIngredients(); return; }
    if (e.target.closest("[data-add-save]")) { saveAddition(); return; }
    const del = e.target.closest("[data-del-add]");
    if (del) { deleteAddition(Number(del.dataset.add)); return; }
  }

  // a clickable ingredient (in a list, a step, or the in-season chips) -> open the drawer
  const ing = e.target.closest("[data-item]");
  if (ing) {
    openPanel(ing.dataset.item, ing);
    return;
  }
  // a recipe link inside the ingredient drawer's "in your recipes" list -> go there
  const rec = e.target.closest("[data-recipe]");
  if (rec) {
    closePanel();
    location.hash = "#/recipe/" + encodeURIComponent(rec.dataset.recipe);
  }
});
closeBtn.addEventListener("click", closePanel);
// The scrim backs both dialogs; close whichever is open (only one ever is).
scrim.addEventListener("click", () => {
  if (!panel.hidden) closePanel();
  else if (backdateModal && !backdateModal.hidden) closeBackdate();
});
backdateModal.querySelector("[data-backdate-close]").addEventListener("click", closeBackdate);
backdateModal.querySelector("[data-backdate-log]").addEventListener("click", submitBackdate);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && backdateModal && !backdateModal.hidden) {
    if (bdYearPopClose) { bdYearPopClose(); return; }   // first Escape closes the year popover…
    closeBackdate(); return;                             // …a second closes the modal
  }
  if (e.key === "Escape" && !panel.hidden) { closePanel(); return; }
  // Enter commits the custom multiplier (blur → focusout handler reformats to "N×" + applies scale)
  if (e.key === "Enter" && e.target.classList && e.target.classList.contains("scale-custom")) {
    e.preventDefault(); e.target.blur(); return;
  }
  // Enter saves / Escape cancels while editing a line's quantity
  if (view && view.editingPos != null && e.target.classList && e.target.classList.contains("le-qty")) {
    if (e.key === "Enter") { e.preventDefault(); saveLineEdit(view.editingPos); }
    else if (e.key === "Escape") { view.editingPos = null; rerenderIngredients(); }
  }
});

// Custom multiplier: any positive number scales both ingredients and steps; 0 / negative / blank /
// non-numeric falls back to ×1. rerenderScaler() re-renders the field in its committed "N×" display
// form (or empty if we fell back to a preset). parseFloat tolerates the "×", so it stays parseable.
function commitCustomScale(el) {
  const n = parseFloat(el.value);
  view.scale = n > 0 ? n : 1;
  rerenderIngredients();
  rerenderSteps();
  rerenderServings();
  rerenderScaler();
}
// The custom field reads like the preset pills: committed = "N×" (rendered by scaleControl); on focus
// it strips to a bare number for editing; typing is digits + one-kind decimal only; blur commits.
document.addEventListener("focusin", (e) => {
  const el = e.target.closest(".scale-custom");
  if (el) el.value = el.value.replace(/[^\d.]/g, "");   // drop the "×" so the number edits cleanly
});
document.addEventListener("input", (e) => {
  const el = e.target.closest(".scale-custom");
  if (el) el.value = el.value.replace(/[^\d.]/g, "");   // digits + decimal point only while editing
});
document.addEventListener("focusout", (e) => {
  const el = e.target.closest(".scale-custom");
  if (el && view) commitCustomScale(el);                // blur commits + reformats to "N×"
});

// In the add-ingredient form, picking a library ingredient pre-fills the text box with
// its name — but only when the box is empty, so a custom label is never clobbered.
document.addEventListener("change", (e) => {
  const link = e.target.closest(".af-link");
  if (!link) return;
  const text = document.querySelector(".af-text");
  if (text && !text.value.trim() && link.value) {
    const opt = link.options[link.selectedIndex];
    text.value = opt ? opt.textContent : "";
  }
});

// Hover-preview the rating: fill stars 1..N while hovering, restore the committed/pending fill on
// leave. Pure visual — the click handler does the rating/gating; touch devices have no hover.
document.addEventListener("mouseover", (e) => {
  const star = e.target.closest(".rating [data-rate]");
  if (!star) return;
  const rating = star.closest(".rating");
  const n = Number(star.dataset.rate);
  rating.classList.add("previewing");
  rating.querySelectorAll(".star").forEach((s, i) => s.classList.toggle("preview", i < n));
});
document.addEventListener("mouseout", (e) => {
  const rating = e.target.closest(".rating");
  if (!rating || rating.contains(e.relatedTarget)) return;   // ignore star->star moves; clear on a real leave
  rating.classList.remove("previewing");
  rating.querySelectorAll(".star").forEach((s) => s.classList.remove("preview"));
});

window.addEventListener("hashchange", route);
route();
