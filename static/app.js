"use strict";

import {
  formatAmount, group, scaleQty, abbrevUnits, canonicalizeUnit, amountText, weightText, toUnicodeFractions,
} from "./scaler.js";
import { headingText, toggleRowType, nonEmptyRows, writeIngField } from "./ingredient-row.js";
import { mountStepEditors, destroyStepEditors } from "./step-editor.js";

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

// A note rendered as a distinct secondary annotation on its OWN line below the ingredient (muted,
// italic, smaller — see .inote). Applies to every reading-mode line, linked or plain.
function readNote(row) {
  return row.note && row.note.trim() ? `<span class="inote">${esc(row.note)}</span>` : "";
}
// The clickable-ingredient-or-plain-text body of a line (no quantity, no tools).
function lineBodyHTML(row) {
  if (row.ingredient_id) {
    const label = row.label || row.raw_text || row.ingredient_id;
    return `<button class="ingredient" data-item="${esc(row.ingredient_id)}">${esc(label)}</button>${readNote(row)}`;
  }
  return `${esc(row.label || row.raw_text || "")}${readNote(row)}`;
}

// A plain ingredient line: used for the Original view and for app recipes.
function plainRow(row) {
  // Guard (belt-and-suspenders): never render an empty row as a bare divider line, even if one somehow
  // reaches the reading view — a heading with no text, or a line with no name, is skipped entirely.
  if (row.is_heading) return (row.raw_text || "").trim() ? `<li class="group">${esc(row.raw_text)}</li>` : "";
  if (!(row.label || row.raw_text || "").trim()) return "";
  return `<li>${ledgerCells(row.qty, row.grams_per_ml)}<span class="iname">${lineBodyHTML(row)}</span></li>`;
}

// An added line (a person's new ingredient), shown in their color. In a person's own
// view it carries a × to delete it; in Compare it's read-only.
function additionRow(a, color, withDelete) {
  const body = a.ingredient_id
    ? `<button class="ingredient" data-item="${esc(a.ingredient_id)}">${esc(a.label || a.raw_text || a.ingredient_id)}</button>${readNote(a)}`
    : `${esc(a.raw_text || "")}${readNote(a)}`;
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
      <ul class="ingredient-list">${rows}</ul>`;
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
    <p class="hint">${hint}</p>`;
}

function rerenderIngredients() {
  const el = document.getElementById("ing-section");
  if (el) el.innerHTML = ingredientsSectionInner(view);
}

// The scaler + cook-time + serves are grouped in the .above-ing block just above the Ingredients
// heading (scaler in its own #scaler-host), a SIBLING of #ing-section so an ingredient rebuild can't
// wipe it — so refresh JUST that host on a scale change to move the active pill / reflect the custom
// value. Targets only #scaler-host; never the .stats/cook-block, so redo/cook state is untouched.
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

// Stage 1a (edit mode only): a non-heading step becomes an empty host that mountStepEditors() fills
// with a per-step TipTap editor. `data-i` indexes view.draft.steps, matching the mount lookup.
// Heading steps reuse renderStepRow, so their display is byte-identical to reading mode.
function renderStepEditHost(row, i) {
  if (row.is_heading) return renderStepRow(row);
  return `<li class="step"><div class="step-editor-host" data-i="${i}"></div></li>`;
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

// The control block above the Ingredients heading: cook time (top) + serves (bottom) STACKED on the
// left, the scale control on the right — circular ½×/1×/2× pills, vertically centered against the
// two-line stack. Time, serves, AND the scaler all live here now, none in the vitals strip. The
// serving count stays scaled to the factor (rerenderServings queries .serves-count); #scaler-host is
// the rerenderScaler target.
function scaleMetaBlock(r) {
  const stack = [];
  const time = r.total_time || r.cook_time || r.prep_time;
  if (time) stack.push(`<span class="meta-item">${META_CLOCK}<span class="meta-val">${esc(time)}</span></span>`);
  const base = servingsBase();
  if (base) stack.push(`<span class="meta-item">${META_FIG}<span>Serves <span class="serves-count meta-val">${formatAmount(base * view.scale)}</span></span></span>`);
  const metaStack = stack.length ? `<div class="meta-stack">${stack.join("")}</div>` : "";
  return `<div class="above-ing">${metaStack}<div class="scaler-col" id="scaler-host">${scaleControl()}</div></div>`;
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
  return `<button class="btn ghost sm" data-inline-edit-enter>✎ Edit</button>
          <a class="btn ghost sm" href="#/edit/${encodeURIComponent(r.id)}">Edit form</a>
          <button class="btn ghost sm" data-copy>Copy</button>
          <button class="btn ghost sm copy-test" data-copy-test>Copy as test</button>
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
  view = { slug: rid, data, mode: "original", editingPos: null, addingOpen: false, scale: 1,
           pendingRating: null, undoneCook: null, editMode: false, draft: null, dirty: false };
  app.className = "page recipe-view";
  setCookCount(app, data.stats.cook_count);   // reserved R2 wear signal on the recipe root

  // Seed recipes let people add ingredients to their version, so load the library
  // now to fill the "link to an ingredient" picker in the add form.
  if (data.is_seed) {
    try { INGREDIENT_LIST = await api("/api/ingredients"); }
    catch (_) { INGREDIENT_LIST = []; }
  }
  paintRecipe();
}

// Paint the recipe page in the current mode (reading vs inline-edit) from `view` — no re-fetch, so
// toggling edit mode is instant. Reading reads view.data; edit reads the buffered view.draft (a deep
// copy), so edits are discarded on Cancel and only committed to the server (and to view.data) on Save.
// The Polaroid assembly (photoSlot) stays a SIBLING of the .detail-card so it keeps straddling the edge.
function paintRecipe() {
  const editing = !!view.editMode;
  // Stage 4: mark the PAGE element when editing so .page.recipe-view.editing widens to ~1000px (reading
  // stays 760px). Re-applied on every paint, so the toggle enter/exit updates the width.
  app.className = "page recipe-view" + (editing ? " editing" : "");
  const data = view.data;                        // fetched payload (source flags: is_editable/is_seed/…)
  const src = editing ? view.draft : view.data;  // where displayed field VALUES come from
  const r = src.recipe;
  const photoSlot = dishPhoto(r, data.is_editable);
  const owner = (data.is_editable && !editing) ? `<div class="owner-actions">${ownerActionsHTML(data.recipe)}</div>` : "";

  const mastheadInner = editing
    ? mastheadEditHTML(r)
    : `${photoSlot ? `<div class="photo-reserve" aria-hidden="true"></div>` : ""}
        ${bylineHTML(r)}
        <h1 class="recipe-title">${esc(r.name)}${data.is_test ? ` <span class="test-badge">Test</span>` : ""}</h1>
        ${tagsHTML(r)}
        ${r.descr ? `<div class="headnote"><p class="dek clamped">${esc(r.descr)}</p><button class="dek-more" data-dek-toggle hidden>more</button></div>` : ""}`;

  const vitalsInner = editing
    ? `${vitalsEditHTML(r)}<div class="stats cook-block locked" data-rid="${esc(r.id)}" aria-disabled="true">${statsInner(data.stats)}</div>`
    : `<div class="stats cook-block" data-rid="${esc(r.id)}">${statsInner(data.stats)}</div>
        ${owner}`;

  // Stage 1: ingredients & steps stay DISPLAY-ONLY in edit mode (rendered from the draft, no scaler,
  // no edit affordances) and round-trip unchanged on Save. Discrete inline editing lands in Stage 2/3.
  const ingSection = editing ? editIngredientsHTML() : ingredientsSectionInner(view);
  // Stage 1a: in edit mode, non-heading steps become TipTap mount hosts (mounted right after this
  // paint by enterEditMode); headings stay display-only, and reading mode is unchanged.
  const steps = editing
    ? view.draft.steps.map(renderStepEditHost).join("")
    : data.steps.map(renderStepRow).join("");

  app.innerHTML = `
    <a class="back" href="#/">← All recipes</a>
    <div class="recipe-stage${photoSlot ? "" : " no-photo"}">
      ${photoSlot}
      <div class="detail-card${editing ? " editing" : ""}">
        <header class="masthead${data.is_test ? " is-test" : ""}">
          <div class="masthead-text">${mastheadInner}</div>
        </header>
        ${editing ? ieDescrHTML(r) : ""}
        <div class="vitals">${vitalsInner}</div>
        <div class="recipe-cols">
          <section>
            ${editing ? "" : scaleMetaBlock(r)}
            <div id="ing-section">${ingSection}</div>
          </section>
          <section>
            <h2 class="col-title">Method</h2>
            <ol class="steps" id="steps-list">${steps}</ol>
            ${editing ? ieNoteHTML(r) : (r.notes ? `<div class="notes"><strong>Note.</strong> ${esc(r.notes)}</div>` : "")}
          </section>
        </div>
      </div>
    </div>
    ${editing ? inlineSaveBarHTML() : ""}`;

  if (!editing) {   // edit mode bypasses the description clamp (no .dek); reading keeps it
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(setupHeadnote);
    else setupHeadnote();
  }
}

/* ---------- inline recipe editor — Stage 1: mode toggle, buffered draft, scalar fields ---------- */

// "Mark up the page" (Option 3): scalar fields as real inputs (NOT contenteditable — the f.value
// buffer machinery is unchanged), but styled to KEEP their reading typography with no labels/boxes —
// just a faint dashed baseline at rest and a soft lift on focus. Reads the RAW draft values. Sits in
// the masthead's left column (.editing reserves the Polaroid's right zone in CSS).
function mastheadEditHTML(r) {
  return `
    <textarea class="ie ie-byline ie-line" data-inline-edit-field="author" rows="1" placeholder="author / source" aria-label="Author or source">${esc(r.author || "")}</textarea>
    <input class="ie ie-util" data-inline-edit-field="source_url" value="${esc(r.source_url || "")}" placeholder="+ source link" aria-label="Source link">
    <textarea class="ie ie-title ie-line" data-inline-edit-field="name" rows="1" placeholder="Recipe title" aria-label="Recipe title">${esc(r.name || "")}</textarea>
    <div class="ie-cat-row" id="ie-cat-row">${catRowHTML()}</div>`;
}

// Description gets its OWN full-width block in edit mode (below the masthead, clear of the Polaroid) —
// roomy to type into, rather than pinned into the narrow reserved-column flow. Reading keeps its
// narrow-beside-then-wide float wrap.
function ieDescrHTML(r) {
  return `<div class="ie-descr-wrap"><textarea class="ie ie-prose" data-inline-edit-field="descr" rows="4" placeholder="Add a description…" aria-label="Description">${esc(r.descr || "")}</textarea></div>`;
}

// Category tags as discrete chips (stored as one "·"-delimited string — a UI-only split/join, no schema
// change). Add/remove mutate view.draft.recipe.category and re-render ONLY the chip row (#ie-cat-row),
// so other fields keep their focus. The new-tag input buffers locally and commits on Enter/blur.
function catTags() {
  return String(view.draft.recipe.category || "").split("·").map((s) => s.trim()).filter(Boolean);
}
function catRowHTML() {
  const chips = catTags().map((t, i) =>
    `<span class="ie-tagchip">${esc(t)}<button type="button" class="ie-tag-x" data-inline-edit-rmtag data-tag-i="${i}" aria-label="Remove ${esc(t)}">×</button></span>`
  ).join("");
  return `${chips}<input class="ie-tag-new" placeholder="+ tag" aria-label="Add a tag">`;
}
function renderCatRow() {
  const row = document.getElementById("ie-cat-row");
  if (row) row.innerHTML = catRowHTML();
}
function addTag(text) {
  const t = (text || "").trim();
  if (!t) return false;
  const arr = catTags(); arr.push(t);
  view.draft.recipe.category = arr.join(" · ");
  markDirty();
  return true;
}
function removeTag(i) {
  const arr = catTags(); arr.splice(i, 1);
  view.draft.recipe.category = arr.join(" · ");
  markDirty();
  renderCatRow();
}
// Add the typed tag, clear the input, re-render the row; on Enter keep the adder open + focused so
// several tags can be added in a row. el.value is cleared BEFORE re-render so the ensuing blur (the
// detached input) can't double-add.
function commitNewTag(el, keepOpen) {
  if (!addTag(el.value)) return;
  el.value = "";
  renderCatRow();
  if (keepOpen) { const n = document.querySelector(".ie-tag-new"); if (n) n.focus(); }
}

// Servings / times read like the reading meta line ("Serves 4 · Prep …"), just editable; note + image
// path sit below. Inline lowercase words, never uppercase form labels.
function vitalsEditHTML(r) {
  const num = (field, label, val) => {
    const sz = Math.max(4, String(val || "").length + 2);   // fallback width for browsers without field-sizing
    return `<span class="ie-vlabel">${label}</span><input class="ie ie-num" data-inline-edit-field="${field}" value="${esc(val || "")}" size="${sz}" aria-label="${label}">`;
  };
  return `<div class="ie-vitals">
      ${num("servings", "Serves", r.servings)}<span class="ie-dot">·</span>
      ${num("prep_time", "Prep", r.prep_time)}<span class="ie-dot">·</span>
      ${num("cook_time", "Cook", r.cook_time)}<span class="ie-dot">·</span>
      ${num("total_time", "Total", r.total_time)}
    </div>`;
}

// The note edits at the BOTTOM (after the steps), mirroring reading's closing "Note. …" block.
function ieNoteHTML(r) {
  return `<div class="ie-noterow ie-note-block"><span class="ie-vlabel">Note</span><textarea class="ie ie-prose ie-note" data-inline-edit-field="notes" rows="2" placeholder="A private note…">${esc(r.notes || "")}</textarea></div>`;
}
// (Image path is intentionally NOT editable here — real photo upload is the next feature; the recipe's
// existing image round-trips unchanged on save via draftPayload.)

// Stage 2: ingredients editable inline in the ledger. A SEPARATE raw-field path (not plainRow /
// ledgerCells / lineBodyHTML — those are the cooked reading path). Each draft ingredient renders as
// an editable row reading RAW fields; the display name is label‖raw_text and edits write to `label`
// (the convention ingToPayload reads). Kept fully separate from the seed line-editor.
const ING_GRIP = `<svg viewBox="0 0 9 14" class="grip-ico" aria-hidden="true"><g fill="currentColor"><circle cx="2" cy="2" r="1.3"/><circle cx="7" cy="2" r="1.3"/><circle cx="2" cy="7" r="1.3"/><circle cx="7" cy="7" r="1.3"/><circle cx="2" cy="12" r="1.3"/><circle cx="7" cy="12" r="1.3"/></g></svg>`;
const ING_SECT = `<svg viewBox="0 0 16 16" class="sect-ico" aria-hidden="true"><line x1="3" y1="4" x2="13" y2="4"/><line x1="3" y1="8" x2="10" y2="8"/><line x1="3" y1="12" x2="12" y2="12"/></svg>`;
const ING_TRASH = `<svg viewBox="0 0 16 16" class="ic-trash" aria-hidden="true"><path d="M3 4.5h10"/><path d="M6.5 4.5V3h3v1.5"/><path d="M4.5 4.5l.6 8.5a1 1 0 0 0 1 .9h3.8a1 1 0 0 0 1-.9l.6-8.5"/><path d="M7 7v4M9 7v4"/></svg>`;
const ING_NOTEPLUS = `<svg viewBox="0 0 22 16" class="ic-note" aria-hidden="true"><path d="M3 2.5h10v7.5l-3 3.5H3z"/><path d="M13 10h-3v3.5"/><path d="M18 4v5M15.5 6.5h5"/></svg>`;
const ING_NOTE = `<svg viewBox="0 0 16 16" class="ic-note-sm" aria-hidden="true"><path d="M3 2.5h10v7.5l-3 3.5H3z"/><path d="M13 10h-3v3.5"/></svg>`;

// Hover-revealed row-actions: a divider, then grip · heading-toggle (icon+word) · fenced red trash.
// The divider + cluster are hidden at rest and slide in on hover/focus-within (link + note-icon stay).
function editIngRowTools(i, isHeading) {
  const word = isHeading ? "ingredient" : "heading";
  const tip = isHeading ? "Make this an ingredient line" : "Make this a section heading";
  return `<span class="divider" aria-hidden="true"></span><span class="rtools">
    <span class="rbtn grip" title="Reorder (coming soon)" aria-hidden="true">${ING_GRIP}</span>
    <button type="button" class="rbtn" data-inline-edit-toggle-ing data-i="${i}" title="${tip}">${ING_SECT}<span class="lbl">${word}</span></button>
    <button type="button" class="rbtn rm" data-inline-edit-rm-ing data-i="${i}" title="Remove" aria-label="Remove">${ING_TRASH}</button>
  </span>`;
}
// A raw-field editable cell — the OVERLAY approach: a real <textarea> is the edit surface (plain-text
// paste, clean value/caret — no contenteditable), with a display <div> overlaid that ellipsis-truncates
// the value at REST (a textarea can't show "…"; a div can). On focus the textarea shows through and wraps
// taller (Option B). Buffered via .value on input with no re-render; the overlay text is mirrored from the
// textarea on blur (see the focusout handler). spellcheck off to avoid squiggles on ingredient text.
function ieCell(key, i, val, cls, ph) {
  const v = esc(val || "");
  return `<span class="ie-ov"><textarea class="ie ${cls}" data-inline-edit-ing="${key}" data-i="${i}" rows="1" placeholder="${esc(ph)}" aria-label="${esc(ph)}" spellcheck="false">${v}</textarea><span class="ie-disp ${cls}" aria-hidden="true">${v}</span></span>`;
}
// The UNIT field: a plain <input> backed by the shared #ie-units datalist (suggestions, NOT closed —
// free-text count-nouns/textual still work). Short, so no overlay/caret machinery. Displays the
// canonical short form; buffers to draft.unit (canonicalized again on save in ingToPayload).
function unitCell(i, val) {
  return `<input class="ie e-unit" list="ie-units" data-inline-edit-ing="unit" data-i="${i}" value="${esc(canonicalizeUnit(val))}" placeholder="unit" aria-label="Unit" spellcheck="false">`;
}
// A3: the amount zone spans to one wide field (no unit box) ONLY for a whole-string fallback — a
// non-empty quantity carrying letters/slash/plus ("pinch", "2 lb / 1 kg", "3 + 2 tbsp") where a unit
// makes no sense. A pure number/fraction/range with an empty unit (a count, or a new row) keeps the
// unit box so a unit can still be added.
function amountSpans(quantity, unit) {
  if (unit && String(unit).trim()) return false;
  const q = String(quantity == null ? "" : quantity).trim();
  return q !== "" && /[a-zA-Z/+]/.test(q);
}
function amountZoneHTML(x, i) {
  const span = amountSpans(x.quantity, x.unit);
  const qty = ieCell("quantity", i, x.quantity, "e-qty", "qty");
  return `<span class="amount-zone${span ? " no-unit" : ""}">${qty}${span ? "" : unitCell(i, x.unit)}</span>`;
}
function editIngRowHTML(x, i) {
  if (x.is_heading) {
    return `<li class="erow group-row">
      ${ieCell("heading", i, headingText(x), "e-heading", "Section heading")}
      <span class="tail">${editIngRowTools(i, true)}</span>
    </li>`;
  }
  const name = x.label || x.raw_text || "";
  let linkBit;
  if (x.ingredient_id) {
    const g = INGREDIENT_LIST.find((it) => it.id === x.ingredient_id);
    linkBit = `<span class="linkchip">🔗 ${esc(g ? g.name : x.ingredient_id)}<button type="button" class="lx" data-inline-edit-unlink data-i="${i}" title="Unlink" aria-label="Unlink">×</button></span>`;
  } else {
    linkBit = `<select class="linksel" data-inline-edit-linksel data-i="${i}" title="Link to a library ingredient" aria-label="Link to a library ingredient"><option value="">🔗</option>${ingOptions("")}</select>`;
  }
  // Empty note -> a compact sticky-note+ icon in the row; a present (or just-opened) note renders BELOW.
  const noteOpen = !!((x.note && x.note.trim()) || x._noteOpen);
  const noteIcon = noteOpen ? "" : `<button type="button" class="note-add" data-inline-edit-addnote data-i="${i}" title="Add a note" aria-label="Add a note">${ING_NOTEPLUS}</button>`;
  const main = `<li class="erow${noteOpen ? " has-note" : ""}">
    ${amountZoneHTML(x, i)}
    ${ieCell("name", i, name, "e-name", "ingredient")}
    <span class="tail">${linkBit}${noteIcon}${editIngRowTools(i, false)}</span>
  </li>`;
  if (!noteOpen) return main;
  const below = `<li class="note-row"><span></span><span class="note-below"><span class="n-ico" aria-hidden="true">${ING_NOTE}</span>${ieCell("note", i, x.note, "e-note", "add a note…")}</span></li>`;
  return main + below;
}
function editIngredientsHTML() {
  const rows = view.draft.ingredients;
  const body = rows.length
    ? `<ul class="ingredient-list edit">${rows.map(editIngRowHTML).join("")}</ul>`
    : `<p class="edit-empty">No ingredients yet.</p>`;
  // One shared datalist for every unit combobox — SUGGESTIONS ONLY (free-text still works). Ordered
  // measuring → size → count for scannability (<optgroup> isn't reliably rendered inside <datalist>,
  // so a flat sensibly-ordered list). NB: the size/count words are suggestions HERE ONLY — they are
  // deliberately NOT in the scaler's measure recognizer, so the scaler keeps treating them as counts.
  const units = ["tsp", "tbsp", "cup", "g", "oz", "lb", "ml", "liter", "kg",   // measuring
                 "small", "medium", "large",                                    // size
                 "clove", "sprig", "stalk", "knob", "bunch", "can", "slice", "pinch"];  // count
  const datalist = `<datalist id="ie-units">${units.map((u) => `<option value="${u}">`).join("")}</datalist>`;
  return `<div class="col-head"><h2 class="col-title">Ingredients</h2></div>
    ${datalist}
    ${body}
    <div class="ing-adders">
      <button type="button" class="adder" data-inline-edit-add-ing>+ add ingredient</button>
      <button type="button" class="adder head" data-inline-edit-add-head>+ section heading</button>
    </div>`;
}

// The ONE section re-render for structural actions (add / remove / heading-toggle / link — and Stage 4
// reorder later). Targets #ing-section only. Kept separate from the seed's rerenderIngredients().
// Text keystrokes NEVER call this (they buffer to the draft with no re-render — see the input handler).
function rerenderEditIngredients() {
  const el = document.getElementById("ing-section");
  if (el) el.innerHTML = editIngredientsHTML();
}
function focusIngField(i, key) {
  const el = document.querySelector(`[data-inline-edit-ing="${key}"][data-i="${i}"]`);
  if (el) { el.focus(); if (el.select) el.select(); }
}
function addIngredient(isHeading) {
  const arr = view.draft.ingredients;
  arr.push(isHeading ? { is_heading: 1, heading: "", qty: "", quantity: "", unit: "", label: "", note: "", ingredient_id: null, raw_text: "" }
                     : { is_heading: 0, qty: "", quantity: "", unit: "", label: "", note: "", ingredient_id: null, raw_text: "" });
  markDirty(); rerenderEditIngredients();
  focusIngField(arr.length - 1, isHeading ? "heading" : "quantity");
}
function removeIngredient(i) { view.draft.ingredients.splice(i, 1); markDirty(); rerenderEditIngredients(); }
function toggleIngredientHeading(i) {
  toggleRowType(view.draft.ingredients[i]);   // lossless in-place flip (Option A1; see ingredient-row.js)
  markDirty(); rerenderEditIngredients();
  focusIngField(i, view.draft.ingredients[i].is_heading ? "heading" : "name");
}
function unlinkIngredient(i) { view.draft.ingredients[i].ingredient_id = null; markDirty(); rerenderEditIngredients(); focusIngField(i, "name"); }
function linkIngredient(i, id) {
  const row = view.draft.ingredients[i];
  row.ingredient_id = id;
  if (!(row.label || "").trim()) {                       // seed the name from the library if blank
    const g = INGREDIENT_LIST.find((it) => it.id === id);
    row.label = g ? g.name : id;
  }
  markDirty(); rerenderEditIngredients(); focusIngField(i, "name");
}
// Reveal the below-row note field for a row with no note yet (transient _noteOpen — never saved). Not a
// content change on its own, so no markDirty until the user actually types into the note.
function addNote(i) {
  view.draft.ingredients[i]._noteOpen = true;
  rerenderEditIngredients();
  focusIngField(i, "note");
}

function inlineSaveBarHTML() {
  return `<div class="inline-save-bar" role="group" aria-label="Editing recipe">
    <span class="inline-editing-label">Editing</span>
    <span class="inline-dirty"${view.dirty ? "" : " hidden"}>• Unsaved changes</span>
    <span class="inline-error" hidden></span>
    <button class="btn sm" data-inline-edit-save>Save changes</button>
    <button class="btn ghost sm" data-inline-edit-cancel>Cancel</button>
  </div>`;
}

function enterEditMode() {
  if (!view || !view.data.is_editable || view.editMode) return;
  view.draft = structuredClone(view.data);   // buffered copy — all edits mutate this, never view.data
  view.editMode = true;
  view.dirty = false;
  view.scale = 1;                             // edit at raw 1× (scaler is hidden in edit mode)
  view.undoneCook = null;                     // entering edit is "another action" -> end the one-shot redo
  paintRecipe();                              // repaints stats (statsInner reads undoneCook) -> Redo collapses to Undo
  // Stage 1a: mount the per-step TipTap editors into the hosts this paint just produced. This is
  // safe ONLY because paintRecipe never fires again mid edit-session (see step-editor.js island
  // invariant); a mid-session repaint would orphan these and must re-mount. Wrapped so a step-editor
  // failure can't break the shared enter flow (ingredient editor + Save must survive it).
  try {
    mountStepEditors(view.draft, (i, text) => { view.draft.steps[i].text = text; markDirty(); });
  } catch (e) { console.error("mountStepEditors failed", e); }
  // The ingredient link-select needs the library; it's otherwise only pre-loaded for seed recipes.
  if (!INGREDIENT_LIST.length) {
    api("/api/ingredients")
      .then((list) => { INGREDIENT_LIST = list; if (view && view.editMode) rerenderEditIngredients(); })
      .catch(() => {});
  }
}

// Discard the buffer and return to reading (Cancel). Save has its own path.
function exitEditMode() {
  try { destroyStepEditors(); } catch (e) { console.error("destroyStepEditors failed", e); }
  view.editMode = false; view.draft = null; view.dirty = false; view.scale = 1;
  paintRecipe();
}

// First buffer mutation flips the "unsaved" indicator — WITHOUT re-rendering (keeps input focus/caret).
function markDirty() {
  if (!view || !view.editMode || view.dirty) return;
  view.dirty = true;
  const ind = document.querySelector(".inline-dirty");
  if (ind) ind.hidden = false;
}

// Convert the draft (DB row shape) back into the PUT payload shape write_recipe_rows expects. Stage 1
// sends ingredients/steps through unchanged; the scalar fields carry the edits.
function ingToPayload(x) {
  const oneLine = (v) => (v || "").replace(/[\r\n]+/g, " ");   // name is a .ie-line (soft-wrap only) — no hard newlines
  if (x.is_heading) return { heading: oneLine(x.heading || x.label || x.raw_text) };   // dedicated field, back-compat fallbacks
  // Stage 4 (B): send the STRUCTURED parts — quantity + canonical unit. The server (sub-step A's IF
  // branch) recombines qty = quantity + " " + unit, so qty is omitted. Authority is now quantity+unit.
  const quantity = oneLine(x.quantity);
  const unit = canonicalizeUnit(x.unit);
  if (x.ingredient_id) return { quantity, unit, item: x.ingredient_id, label: oneLine(x.label || x.raw_text), note: x.note || "" };
  return { quantity, unit, text: oneLine(x.label || x.raw_text), note: x.note || "" };
}
function stepToPayload(x) { return x.is_heading ? { heading: x.text || "" } : (x.text || ""); }
function draftPayload() {
  const r = view.draft.recipe;
  const t = (v) => (v == null ? "" : String(v).trim());
  const oneLine = (v) => t(v).replace(/[\r\n]+/g, " ");   // .ie-line fields wrap visually but stay one logical line
  return {
    name: oneLine(r.name), author: oneLine(r.author), source_url: t(r.source_url), category: t(r.category),
    servings: t(r.servings), prep_time: t(r.prep_time), cook_time: t(r.cook_time), total_time: t(r.total_time),
    image: t(r.image), descr: t(r.descr), notes: t(r.notes),
    ingredients: nonEmptyRows(view.draft.ingredients).map(ingToPayload),   // drop blank rows the user left WIP
    steps: view.draft.steps.map(stepToPayload),
  };
}

async function saveInlineEdit() {
  const errEl = document.querySelector(".inline-error");
  const showErr = (m) => { if (errEl) { errEl.textContent = m; errEl.hidden = false; } };
  const payload = draftPayload();
  if (!payload.name) { showErr("A name is required."); return; }
  const slug = view.slug;
  const { ok, data } = await sendJSON("PUT", "/api/recipes/" + encodeURIComponent(slug), payload);
  if (!ok) { showErr((data && data.error) || "Couldn't save."); return; }
  // Tear down the step editors before the re-fetch repaints (renderRecipe -> paintRecipe wipes their
  // hosts); onUpdate already synced each step's text into view.draft, so draftPayload above carried it.
  try { destroyStepEditors(); } catch (e) { console.error("destroyStepEditors failed", e); }
  // Re-fetch the CANONICAL saved recipe rather than keeping the unfiltered draft: the payload dropped
  // blank rows and normalized headings (text -> raw_text), so view.data must reflect the server, not
  // the draft shape (which still holds WIP blanks + the dedicated `heading` field). This lands us back
  // in reading mode with exactly what was saved.
  try { await renderRecipe(slug); }
  catch (_) { showErr("Saved — but couldn't refresh the view. Reload to see it."); }
}

// Sub-dispatch for the inline editor's own click actions (namespaced data-inline-edit-*), kept out of
// the big document click handler's branches. Returns true when it handled the event.
function handleInlineEdit(e) {
  if (!view) return false;
  if (e.target.closest("[data-inline-edit-enter]"))  { enterEditMode(); return true; }
  if (e.target.closest("[data-inline-edit-cancel]")) { exitEditMode(); return true; }
  if (e.target.closest("[data-inline-edit-save]"))   { saveInlineEdit(); return true; }
  const rmtag = e.target.closest("[data-inline-edit-rmtag]");
  if (rmtag) { removeTag(Number(rmtag.dataset.tagI)); return true; }
  // Stage 2 — ingredient structural actions (all re-render the section via rerenderEditIngredients)
  if (e.target.closest("[data-inline-edit-add-ing]"))  { addIngredient(false); return true; }
  if (e.target.closest("[data-inline-edit-add-head]")) { addIngredient(true); return true; }
  const rmi = e.target.closest("[data-inline-edit-rm-ing]");
  if (rmi) { removeIngredient(Number(rmi.dataset.i)); return true; }
  const tgi = e.target.closest("[data-inline-edit-toggle-ing]");
  if (tgi) { toggleIngredientHeading(Number(tgi.dataset.i)); return true; }
  const unl = e.target.closest("[data-inline-edit-unlink]");
  if (unl) { unlinkIngredient(Number(unl.dataset.i)); return true; }
  const ani = e.target.closest("[data-inline-edit-addnote]");
  if (ani) { addNote(Number(ani.dataset.i)); return true; }
  return false;
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

// Copy the open recipe (content only; the copy starts with zero cooks + no rating — the server
// resets the accruing layer). isTest -> a removable test-tier copy. Lands on the new copy.
async function doCopy(isTest) {
  const res = await sendJSON("POST", `/api/recipes/${encodeURIComponent(view.slug)}/copy`, { is_test: !!isTest });
  if (res.ok && res.data && res.data.id) location.hash = "#/recipe/" + encodeURIComponent(res.data.id);
  else alert((res.data && res.data.error) || "Couldn't copy the recipe.");
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
  // Inline recipe editor: enter / save / cancel (namespaced data-inline-edit-*). Handled first.
  if (handleInlineEdit(e)) return;

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
    if (view && view.editMode) return;   // cook/rate is disabled while editing (stats shown locked)
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

    // copy the recipe (a clean duplicate) — plain, or as a removable test-tier copy
    if (e.target.closest("[data-copy-test]")) { doCopy(true); return; }
    if (e.target.closest("[data-copy]")) { doCopy(false); return; }

    // scale control: re-scale every displayed quantity
    const scale = e.target.closest("[data-scale]");
    if (scale) {
      view.scale = parseFloat(scale.dataset.scale);
      rerenderIngredients();
      rerenderSteps();
      rerenderServings();
      rerenderScaler();      // scaler sits above Ingredients now — refresh its own host (active pill)
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
    // Edit-mode step chips carry data-item too; clicking one shouldn't open the reference drawer
    // (it's an editor token, not a reading-mode link). Reading-mode links still open the drawer.
    if (view && view.editMode && ing.closest(".step-editor-host")) return;
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
  // Inline editor "+ tag": Enter adds the tag and keeps the adder open; Escape clears + blurs.
  if (view && view.editMode && e.target.classList && e.target.classList.contains("ie-tag-new")) {
    if (e.key === "Enter") { e.preventDefault(); commitNewTag(e.target, true); }
    else if (e.key === "Escape") { e.target.value = ""; e.target.blur(); }
    return;
  }
  // Ingredient value fields (qty/name/note/heading textareas): Enter commits + closes (blur — the value
  // is already buffered continuously via input→draft), Escape reverts this field to its focus-time
  // snapshot (iePreEdit, captured on focusin) and closes. Neither inserts a newline. Blur is fine — it
  // doesn't re-render (focusout just mirrors the value into the overlay).
  if (view && view.editMode && e.target.dataset && e.target.dataset.inlineEditIng) {
    if (e.key === "Enter") { e.preventDefault(); e.target.blur(); return; }
    if (e.key === "Escape") {
      e.preventDefault();
      const ta = e.target;
      ta.value = iePreEdit;
      const row = view.draft && view.draft.ingredients[Number(ta.dataset.i)];
      if (row) writeIngField(row, ta.dataset.inlineEditIng, iePreEdit);   // restore draft to the snapshot
      ta.blur();
      return;
    }
  }
  if (view && view.editMode && e.key === "Enter" && e.target.classList && e.target.classList.contains("ie-line")) {
    e.preventDefault();
    return;
  }
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
  if (el) { el.value = el.value.replace(/[^\d.]/g, ""); return; }   // digits + decimal point only while editing
  // Inline editor: buffer the scalar field into the draft ONLY — never re-render here, or the input
  // would lose focus/caret mid-typing. Re-render happens solely on mode/save/cancel.
  const f = e.target.closest("[data-inline-edit-field]");
  if (f && view && view.editMode && view.draft) {
    view.draft.recipe[f.dataset.inlineEditField] = f.value;
    markDirty();
    return;
  }
  // Stage 2 — buffer an ingredient field into the draft row (NO re-render → focus/caret preserved).
  const ing = e.target.closest("[data-inline-edit-ing]");
  if (ing && view && view.editMode && view.draft) {
    const row = view.draft.ingredients[Number(ing.dataset.i)];
    if (!row) return;
    writeIngField(row, ing.dataset.inlineEditIng, ing.value);   // real <textarea> -> draft (shared w/ Esc-revert)
    markDirty();
  }
});
document.addEventListener("focusout", (e) => {
  const nt = e.target.closest(".ie-tag-new");
  if (nt && view && view.editMode) { commitNewTag(nt, false); return; }   // blur commits a typed-but-unadded tag
  const el = e.target.closest(".scale-custom");
  if (el && view) commitCustomScale(el);                // blur commits + reformats to "N×"
  // Overlay field: on blur, mirror the textarea's value into its ellipsis display div so the resting
  // (truncated) state reflects the edit. Not a re-render — just the sibling overlay's text.
  const iet = e.target.closest("textarea[data-inline-edit-ing]");
  if (iet) { const d = iet.parentElement.querySelector(".ie-disp"); if (d) d.textContent = iet.value; }
});
// Snapshot a field's value when it gains focus, so Escape can revert it to exactly this (see keydown).
// Any ingredient field (the quantity/name/note textareas AND the unit <input>), so Esc-revert works
// on the unit combobox too — not just the overlay textareas.
let iePreEdit = "";
document.addEventListener("focusin", (e) => {
  const ta = e.target.closest("[data-inline-edit-ing]");
  if (ta && view && view.editMode) iePreEdit = ta.value;
});
// Overlay caret fix: the resting display div is one line while the textarea wraps on focus, so letting a
// click fall through hit-tests against the wrong (reflowed) layout and drops the caret in the wrong spot.
// Instead we OWN the click: read the caret offset from the display div's own (one-line) text via
// caretPositionFromPoint, then focus the textarea and place the caret there. (Once focused, the overlay
// is hidden and further clicks hit the textarea natively.)
function caretOffsetFromPoint(x, y) {
  if (document.caretPositionFromPoint) {
    const p = document.caretPositionFromPoint(x, y);
    return p ? p.offset : null;
  }
  if (document.caretRangeFromPoint) {
    const r = document.caretRangeFromPoint(x, y);
    return r ? r.startOffset : null;
  }
  return null;
}
document.addEventListener("mousedown", (e) => {
  if (!(view && view.editMode)) return;
  const disp = e.target.closest(".ie-disp");
  if (!disp) return;
  const ta = disp.parentElement.querySelector("textarea[data-inline-edit-ing]");
  if (!ta) return;
  e.preventDefault();                                   // take over focus + caret placement from the browser
  const off = caretOffsetFromPoint(e.clientX, e.clientY);
  ta.focus();
  if (off != null) { const n = Math.min(off, ta.value.length); ta.setSelectionRange(n, n); }
});

// In the add-ingredient form, picking a library ingredient pre-fills the text box with
// its name — but only when the box is empty, so a custom label is never clobbered.
document.addEventListener("change", (e) => {
  // Stage 2 — link an ingredient row to the library (structural: sets ingredient_id + re-renders)
  const linksel = e.target.closest("[data-inline-edit-linksel]");
  if (linksel && view && view.editMode && view.draft) {
    if (linksel.value) linkIngredient(Number(linksel.dataset.i), linksel.value);
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

// Dirty-state navigation guard: route() rebuilds `view` from a fresh fetch on any hash change (the
// ← All recipes link, browser back, any #/ nav), which would silently discard an unsaved edit buffer.
// Prompt first; if kept, restore the hash and leave the edit session intact.
let inlineNavSuppress = false;
function onHashChange() {
  if (inlineNavSuppress) { inlineNavSuppress = false; return; }   // our own hash-restore — ignore
  if (view && view.editMode && view.dirty) {
    if (!confirm("Discard unsaved changes?")) {
      inlineNavSuppress = true;
      location.hash = "#/recipe/" + encodeURIComponent(view.slug);   // put the hash back (suppressed above)
      return;                                                        // keep editing; do not re-route
    }
    view.editMode = false; view.draft = null; view.dirty = false;    // discard, then route on through
  }
  // Any navigation that reaches route() repaints a fresh view — tear down step editors first so they
  // aren't orphaned by that repaint. (The "keep editing" branch above returns before reaching here.)
  try { destroyStepEditors(); } catch (e) { console.error("destroyStepEditors failed", e); }
  route();
}
window.addEventListener("hashchange", onHashChange);
// Full page unload / reload / tab-close with unsaved edits → native browser confirm.
window.addEventListener("beforeunload", (e) => {
  if (view && view.editMode && view.dirty) { e.preventDefault(); e.returnValue = ""; }
});
route();
