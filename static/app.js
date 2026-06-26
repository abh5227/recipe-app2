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

function cookSummary(stats) {
  if (!stats.cook_count) return "Not cooked yet";
  const times = stats.cook_count === 1 ? "once" : `${stats.cook_count} times`;
  const last = formatDate(stats.last_cooked);
  return `Cooked ${times}${last ? ` · last on ${last}` : ""}`;
}

// The inner contents of the stats bar on a recipe page (re-rendered after each change).
function statsInner(stats) {
  return `
    <div class="rating" role="group" aria-label="Your rating">${starsHTML(stats.rating)}</div>
    <span class="cook-summary">${esc(cookSummary(stats))}</span>
    <span class="cook-actions">
      <button class="btn" data-cook>Cooked it</button>
      ${stats.cook_count ? `<button class="btn ghost" data-uncook>Undo</button>` : ""}
    </span>`;
}

async function updateStats(el, path, body) {
  try {
    el.innerHTML = statsInner(await postJSON(path, body));
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

  const cards = recipes
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
      return `<a class="recipe-card" href="#/recipe/${encodeURIComponent(r.id)}">
                ${photo(r, "thumb")}
                <div class="rc-body">
                  <p class="rc-name">${esc(r.name)}</p>
                  <p class="rc-meta">${bits}</p>
                  ${statsLine}
                </div>
              </a>`;
    })
    .join("");

  app.innerHTML = `
    <div class="site-head">
      <div>
        <h1 class="site-title">Seasonal Kitchen</h1>
        <p class="site-sub">Field notes from the kitchen — recipes, and what goes in them.</p>
      </div>
      <a class="btn new-recipe" href="#/new">+ New recipe</a>
    </div>
    <div class="season-rail">
      <h2>In season now — ${esc(monthName)}</h2>
      <div class="season-chips">${chips}</div>
    </div>
    <div class="recipe-grid">${cards}</div>`;
}

/* ---------- recipe view ---------- */

/* ---------- recipe view ---------- */

/* Quantity scaling / unit conversion (Phase 1a-1d + smart-Metric).
   The pure logic + constants now live in static/scaler.js, loaded as a global before
   this file (and unit-tested under Node, tests/js/). app.js keeps the DOM/rendering and
   passes view.scale / view.units into displayQty() and scaleQty(). */

// Wrap a quantity in its <span class="qty">, marking volume->weight conversions (which
// begin with "~") with an extra class so they read as approximate, not authored.
function qtySpan(qty, gramsPerMl, inlineStyle) {
  const text = displayQty(qty, gramsPerMl, view.scale, view.units);
  const cls = text.charAt(0) === "~" ? "qty approx" : "qty";
  const style = inlineStyle ? ` style="${inlineStyle}"` : "";
  return `<span class="${cls}"${style}>${esc(text)}</span>`;
}

// The metric/imperial toggle beside the scale control.
function unitsControl() {
  const opts = [["imperial", "Imperial"], ["metric", "Metric"]];
  const buttons = opts
    .map(([v, label]) => `<button data-units="${v}" class="${view.units === v ? "on" : ""}">${label}</button>`)
    .join("");
  return `<div class="units-control" role="group" aria-label="Unit system">${buttons}</div>`;
}

// A one-line caption shown in Metric mode, explaining the ~ approximate-weight marker.
function gramsNote() {
  if (!view || view.units !== "metric") return "";
  return `<p class="grams-note">~ weights are estimated from volume; weigh for precision. Lines without a known weight stay as written.</p>`;
}

// The recipe's serving count as a number, if its servings text contains one.
function servingsBase() {
  const sv = view && view.data.recipe.servings;
  const m = sv ? String(sv).match(/\d+/) : null;
  return m ? parseInt(m[0], 10) : null;
}

// The scale control shown beside the Ingredients heading.
function scaleControl() {
  const options = [[0.5, "\u00bd\u00d7"], [1, "1\u00d7"], [2, "2\u00d7"], [3, "3\u00d7"]];
  const buttons = options
    .map(([v, label]) => `<button data-scale="${v}" class="${view.scale === v ? "on" : ""}">${label}</button>`)
    .join("");
  // Custom multiplier \u2014 any positive number. Shows the current factor when it isn't a preset.
  const isPreset = options.some(([v]) => v === view.scale);
  const customVal = isPreset ? "" : String(view.scale);
  const custom = `<input class="scale-custom" type="number" min="0" step="0.25" inputmode="decimal" placeholder="custom\u00d7" aria-label="Custom multiplier" value="${customVal}">`;
  const base = servingsBase();
  const servings = (base && view.scale !== 1)
    ? `<span class="scale-servings">${formatAmount(base * view.scale)} servings</span>`
    : "";
  return `<div class="scale-control" role="group" aria-label="Scale quantities">${buttons}${custom}${servings}</div>`;
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
  return `<li>${qtySpan(row.qty, row.grams_per_ml)}<span>${lineBodyHTML(row)}</span></li>`;
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
  return `<li>${qtySpan(a.qty, a.grams_per_ml, `color:${color};font-weight:600`)}` +
         `<span class="muted-ing" style="color:${color}">${body}</span>${tools}</li>`;
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
      return `<li class="ing-line removed">${qtySpan(row.qty, row.grams_per_ml, `color:${color}`)}` +
             `<span class="muted-ing" style="color:${color}">${lineBodyHTML(row)}</span>${tools(pos)}</li>`;
    }
    if (editedQty !== undefined) {
      return `<li>${qtySpan(editedQty, row.grams_per_ml, `color:${color};font-weight:600`)}` +
             `<span class="muted-ing" style="color:${color}">${lineBodyHTML(row)}</span>${tools(pos)}</li>`;
    }
    return `<li>${qtySpan(row.qty, row.grams_per_ml)}<span>${lineBodyHTML(row)}</span>${tools(pos)}</li>`;
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
      <div class="col-head"><h2 class="col-title">Ingredients</h2><div class="ing-controls">${scaleControl()}${unitsControl()}</div></div>
      ${gramsNote()}
      <ul class="ingredient-list">${rows}</ul>
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
    <div class="col-head"><h2 class="col-title">Ingredients</h2><div class="ing-controls">${scaleControl()}${unitsControl()}</div></div>
    ${gramsNote()}
    ${viewSelector(view)}
    <ul class="ingredient-list">${rows}</ul>
    ${isPersonView ? addControl(view) : ""}
    <p class="hint">${hint}</p>`;
}

function rerenderIngredients() {
  const el = document.getElementById("ing-section");
  if (el) el.innerHTML = ingredientsSectionInner(view);
}

// Re-render the method steps so tagged "scale" quantities reflect the current factor.
function rerenderSteps() {
  const el = document.getElementById("steps-list");
  if (el) el.innerHTML = view.data.steps.map(renderStepRow).join("");
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
      ? `<span class="step-qty">${esc(scaleQty(s.text, view.scale))}</span>`
      : linkify(s.text)))
    .join("");
  return `<li class="step">${html}</li>`;
}

async function renderRecipe(rid) {
  const data = await api("/api/recipes/" + encodeURIComponent(rid));
  view = { slug: rid, data, mode: "original", editingPos: null, addingOpen: false, scale: 1, units: "imperial" };
  const r = data.recipe;

  // Seed recipes let people add ingredients to their version, so load the library
  // now to fill the "link to an ingredient" picker in the add form.
  if (data.is_seed) {
    try { INGREDIENT_LIST = await api("/api/ingredients"); }
    catch (_) { INGREDIENT_LIST = []; }
  }

  const meta = [
    r.servings ? ["Serves", r.servings] : null,
    r.prep_time ? ["Prep", r.prep_time] : null,
    r.cook_time ? ["Cook", r.cook_time] : null,
    r.total_time ? ["Total", r.total_time] : null,
  ]
    .filter(Boolean)
    .map(([l, val]) => `<li><span class="label">${esc(l)}</span><span class="value">${esc(val)}</span></li>`)
    .join("");

  const sourceLine = r.author
    ? `<p class="eyebrow">${r.source_url ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.author)}</a>` : esc(r.author)}${r.category ? " · " + esc(r.category) : ""}</p>`
    : (r.category ? `<p class="eyebrow">${esc(r.category)}</p>` : "");

  const owner = data.is_editable
    ? `<div class="owner-actions">
         <a class="btn ghost sm" href="#/edit/${encodeURIComponent(r.id)}">Edit recipe</a>
         <button class="btn ghost sm" data-delete>Delete</button>
       </div>`
    : "";

  app.innerHTML = `
    <a class="back" href="#/">← All recipes</a>
    ${photo(r, "hero")}
    ${sourceLine}
    <h1 class="recipe-title">${esc(r.name)}</h1>
    ${r.descr ? `<p class="dek">${esc(r.descr)}</p>` : ""}
    ${meta ? `<ul class="meta">${meta}</ul>` : ""}
    <div class="stats" data-rid="${esc(r.id)}">${statsInner(data.stats)}</div>
    ${owner}
    <div class="recipe-cols">
      <section id="ing-section">${ingredientsSectionInner(view)}</section>
      <section>
        <h2 class="col-title">Method</h2>
        <ol class="steps" id="steps-list">${data.steps.map(renderStepRow).join("")}</ol>
        ${r.notes ? `<div class="notes"><strong>Note.</strong> ${esc(r.notes)}</div>` : ""}
      </section>
    </div>`;
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

async function handleDelete() {
  const name = view.data.recipe.name;
  if (!confirm(`Delete “${name}” and its ratings and cook history? This can't be undone.`)) return;
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

/* ---------- events ---------- */
// One click listener for the whole page (instead of attaching one to every button,
// which is impossible here since the buttons are rebuilt constantly). When any click
// happens, we look at what was clicked — e.target.closest("X") finds the nearest
// matching element at or above the click — and act on the first kind we recognize.
document.addEventListener("click", (e) => {
  // rating / cooking actions live inside the stats bar on a recipe page
  const stats = e.target.closest(".stats");
  if (stats) {
    const rid = encodeURIComponent(stats.dataset.rid);
    const rate = e.target.closest("[data-rate]");
    if (rate) { updateStats(stats, `/api/recipes/${rid}/rating`, { rating: Number(rate.dataset.rate) }); return; }
    if (e.target.closest("[data-cook]"))   { updateStats(stats, `/api/recipes/${rid}/cooked`, {}); return; }
    if (e.target.closest("[data-uncook]")) { updateStats(stats, `/api/recipes/${rid}/uncook`, {}); return; }
  }

  // recipe-detail interactions: app-recipe delete + the per-person change layers
  if (view) {
    if (e.target.closest("[data-delete]")) { handleDelete(); return; }

    // scale control: re-scale every displayed quantity
    const scale = e.target.closest("[data-scale]");
    if (scale) {
      view.scale = parseFloat(scale.dataset.scale);
      rerenderIngredients();
      rerenderSteps();
      return;
    }
    const unitBtn = e.target.closest("[data-units]");
    if (unitBtn) {
      view.units = unitBtn.dataset.units;
      rerenderIngredients();
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
scrim.addEventListener("click", closePanel);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !panel.hidden) { closePanel(); return; }
  // Enter saves / Escape cancels while editing a line's quantity
  if (view && view.editingPos != null && e.target.classList && e.target.classList.contains("le-qty")) {
    if (e.key === "Enter") { e.preventDefault(); saveLineEdit(view.editingPos); }
    else if (e.key === "Escape") { view.editingPos = null; rerenderIngredients(); }
  }
});

// In the add-ingredient form, picking a library ingredient pre-fills the text box with
// its name — but only when the box is empty, so a custom label is never clobbered.
document.addEventListener("change", (e) => {
  // Custom multiplier: any positive number scales both ingredients and steps; 0 / negative /
  // blank / non-numeric falls back to ×1 (consistent with the 1a scaler).
  const custom = e.target.closest(".scale-custom");
  if (custom && view) {
    const n = parseFloat(custom.value);
    view.scale = n > 0 ? n : 1;
    rerenderIngredients();
    rerenderSteps();
    return;
  }
  const link = e.target.closest(".af-link");
  if (!link) return;
  const text = document.querySelector(".af-text");
  if (text && !text.value.trim() && link.value) {
    const opt = link.options[link.selectedIndex];
    text.value = opt ? opt.textContent : "";
  }
});

window.addEventListener("hashchange", route);
route();
