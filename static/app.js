"use strict";

import {
  formatAmount, group, canonicalizeUnit, amountText, weightText,
} from "./scaler.js";
import { headingText, toggleRowType, nonEmptyRows, writeIngField } from "./ingredient-row.js";
import { showLinksAsWords } from "./step-adapter.js";
import { nonEmptySteps, focusIndexAfterRemove, writeStepField,
         stepLevel, toggleStepType, setStepLevel } from "./step-row.js";
import { insertIndexFor } from "./row-insert.js";
import { removedInsertIndex } from "./annotation-place.js";
import { annotationIndex } from "./annotation-index.js";
import { wordDiffParts } from "./word-diff.js";
import { editedAmountParts, removedAmountText, stepSpanTexts } from "./annotation-amount.js";
import { timeParts, bindUnits } from "./timefmt.js";
import { ingToPayload, stepToPayload } from "./save-payload.js";
import { feedRelTime, feedDateShort } from "./feedtime.js";
import { isToMake } from "./tomake.js";
import { browseList, cardTags, monthYear } from "./browse.js";
import { panelBlocks } from "./panel-blocks.js";
import { noteSections, displayText, STEP_NOTES_HEADER } from "./note-blocks.js";
import { noteRowHTML, newNoteBoxHTML, newNoteRow, NEW_NOTE_ID, notePatchBody, noteTextChanged,
         noteTitleChanged, noteEditText,
         undoToastHTML, addNoteButtonHTML, tagLabel, kindOf, pickBarHTML,
         noteStepChanged } from "./note-ui.js";
import { pickerRows, filterRows, startCursor, moveCursor, stepRowsOf } from "./step-picker.js";
import { resolveNoteSteps, draftSetText, draftSetTitle, draftSetKind, draftSetStep, draftAdd, draftDelete,
         draftRestore, notesPayload, draftReorder, draftAddBeside,
         nextDraftId, noteGroupKey, noteDragMates } from "./note-draft.js";
import { noteTextHTML, stepNoteIndex } from "./note-text.js";
import { makeHold, HOLD_MS } from "./hover-hold.js";
// ⚠️ THE KIND TABLE IS ONE FILE, IMPORTED, NOT A COPY KEPT IN STEP BY A TEST. Vite inlines
// the JSON at build time and import_cleanup reads the SAME path for the data rule, so the
// display and the importer cannot disagree about what "Storing." means.
import NOTE_KINDS from "./note-kinds.json";
import { uploadErrorHTML } from "./upload-status.js";
import { makeBackdateSubmit, isStageableImage } from "./backdate-submit.js";
import { RATING_MAX, ratingPct, ratingText, nextRating } from "./star-fill.js";
import { mountStepEditors, destroyStepEditors, focusStepEditor } from "./step-editor.js";
import { heroCaption } from "./hero-caption.js";
import { reorderBefore } from "./reorder.js";
import { applyRowDrop, dropBeforeIndex } from "./drop-index.js";
import heroUrl from "./login-hero.jpg";   // auth-4 login hero — Vite hashes it into dist/assets (served via /assets)

// This file runs in the browser. It has no recipe content of its own — it asks
// the backend (app.py) for data as JSON, builds HTML text from that data, and
// drops it into the page. There's only one real page; clicking around swaps what's
// shown by changing the part of the address after "#". (See the router below.)

const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
const app = document.getElementById("app");
const authGate = document.getElementById("auth-gate");   // login/signup split-spread (auth-4)
let CURRENT_USER = null;                                  // set from /api/me|login|signup (never stored)

// State for whichever recipe page is open (null on the home list or a form). It
// remembers which view is showing and which line is being edited, so a click can
// re-render the ingredient list without re-fetching from the server:
//   { slug, data, scale, editMode, draft, dirty }
//   - data        : the GET /api/recipes/<id> response
//   - addingOpen  : whether the "add ingredient" form is open
let view = null;
// The ingredient library ({id, name}), fetched when a form or a seed recipe opens,
// to fill the "link to an ingredient" dropdowns.
let INGREDIENT_LIST = [];

/* ---------- tiny helpers ---------- */

// Make text safe to drop into HTML. If a recipe name contained "<" or "&", the
// browser might treat it as code/markup; this swaps those characters for their
// harmless display versions. Every piece of data we insert goes through this.
// Display-only whitespace hygiene for the pre-wrap prose blocks (.dek / .notes). The stored value
// keeps its INTERNAL line structure, which is the whole point of pre-wrap, but leading and trailing
// blanks would become visible dead space now that they are no longer collapsed by HTML. Measured on
// the live data: 6 descr and 12 notes values carry trailing whitespace. Nothing is written back.
const proseText = (s) => String(s ?? "").trim();

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
}

// Fetch JSON from one of the backend's GET endpoints. "await" means "wait for the
// server to answer before continuing". If the server returns an error, we throw,
// and the caller (route) shows the error screen.
async function api(path) {
  const res = await fetch(path, { cache: "no-store", credentials: "same-origin" });
  if (res.status === 401) { showAuth(); throw new Error("__auth__"); }   // session lost -> login view
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
    credentials: "same-origin",
    body: JSON.stringify(body || {}),
  });
  if (res.status === 401) { showAuth(); throw new Error("__auth__"); }
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// Send any method and ALWAYS return {ok, status, data} instead of throwing, so the
// caller can show the server's message on a 400 / 403 / 409 (e.g. "name taken").
async function sendJSON(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    credentials: "same-origin",
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* no/!json body */ }
  if (res.status === 401) showAuth();   // an app write hit a lost session -> drop to the login view
  return { ok: res.ok, status: res.status, data };
}

// Auth-endpoint calls (/api/me|login|signup|logout). Kept SEPARATE from api()/sendJSON so a 401 here
// (a bad login) does NOT trip the session-lost gate above — the login/signup form shows the message
// itself. Cookie is the session (credentials sent/received); nothing is stored client-side.
async function authRequest(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    credentials: "same-origin",
    cache: "no-store",
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

// The album's date treatment: the FULL month ("March 12, 2024"), distinct from the cook-summary's
// short "Mar" (history-recedes). Pure — 'YYYY-MM-DD' in, formatted string (or null) out; unit-tested.
function formatFullDate(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);   // 'YYYY-MM-DD'
  return new Date(y, m - 1, d).toLocaleDateString("en", {
    month: "long", day: "numeric", year: "numeric",
  });
}

// ── Stars ────────────────────────────────────────────────────────────────────────────────────
// ONE renderer, two modes, because a recipe's number and a cook's verdict are different things.
//
//   READ-ONLY   the recipe's average. Fills CONTINUOUSLY to the exact fraction — 4.3 reads as 86%
//               of the way across, not "4" and not "4.5". Rounding an average to a half is a lie
//               about a number that is not a half, and the whole point of averaging nine cooks is
//               that the result sits between the steps. The figure is printed beside it, since a
//               bar of stars cannot tell 4.3 from 4.4 and the exact value is the useful part.
//   INTERACTIVE one cooking's verdict, which IS on a half step. Snaps to 0.5.
//
// ⚠️ THE FILL IS A CLIPPED OVERLAY, NOT A PER-GLYPH DECISION. Five outline stars sit underneath and
// five gold ones are laid over them, clipped to a percentage width. That is what makes an arbitrary
// fraction renderable at all. The old path was `"★".repeat(r.rating)`, which on a 4.5 returned FOUR
// stars and an empty string for the remainder, so the row silently lost a character.
function starFillHTML(value) {
  return `<span class="starfill-empty" aria-hidden="true">★★★★★</span>` +
         `<span class="starfill-on" aria-hidden="true" style="width:${ratingPct(value)}">★★★★★</span>`;
}

// Read-only: the recipe's average, plus the figure and what it is an average OF. "4.5 · 2 cooks"
// answers the question a single number cannot, which is how much the number is standing on.
function starsReadHTML(rating, ratedCooks) {
  if (rating == null) return `<span class="rate-none">Unrated</span>`;
  const n = Number(ratedCooks) || 0;
  const over = n > 1 ? `<span class="rating-over">· ${n} cooks</span>` : "";
  return `<span class="starfill" role="img" aria-label="${ratingText(rating)} out of 5${n > 1 ? `, averaged over ${n} cooks` : ""}">
      ${starFillHTML(rating)}
    </span><span class="rating-num">${ratingText(rating)}</span>${over}`;
}

// Interactive: ten hit targets laid over the stars, one per half step.
// ⚠️ HALF A STAR IS ABOUT 13px WIDE, which is under the ~44px a finger wants, and there is no way
// around that while a half-star has to be clickable at the size a star is drawn. What can be fixed
// is the other axis and the feedback: the hit row is 40px tall so each target is 13x40 rather than
// 13x13, and hovering fills to exactly the value under the cursor, so the value is visible BEFORE
// the click commits it. The glyphs are the SAME size as the read-only average, so the block does
// not resize the moment a second cook turns the one into the other.
function starsInputHTML(value) {
  let hits = "";
  for (let i = 1; i <= RATING_MAX * 2; i++) {
    const v = i / 2;
    hits += `<button type="button" class="star-hit" data-rate="${v}" tabindex="${i % 2 ? -1 : 0}"
      aria-label="${v} star${v === 1 ? "" : "s"}"></button>`;
  }
  return `<span class="starfill">
      ${starFillHTML(value || 0)}
      <span class="star-hits">${hits}</span>
    </span>`;
}

// The cook-summary line. A provisional last-cook date (a seeded Paprika-import date, not yet a
// confirmed cook) renders soft — the "~" + .approx family from the ledger — so unconfirmed dates
// stand out at a glance for later correction. Returns HTML; the dynamic date is escaped.
function cookSummary(stats) {
  if (!stats.cook_count) return "Not cooked yet";
  const last = formatDate(stats.last_cooked);
  const dateClause = !last ? "" : (stats.last_cooked_provisional
    ? `<span class="approx">~ ${esc(last)}</span>`     // provisional (import-seeded) date, kept soft
    : esc(last));
  // ⚠️ ONE COOK SAYS ITS DATE ONCE. "Cooked once" above "Last cooked 14 Mar" is the same fact told
  // twice, and "last" means nothing when there is no earlier one.
  if (stats.cook_count === 1) {
    return last ? `<span class="cook-times">Cooked ${dateClause}</span>` : `<span class="cook-times">Cooked once</span>`;
  }
  const line1 = `<span class="cook-times">Cooked ${stats.cook_count} times</span>`;
  if (!last) return line1;                             // cooked but no date -> just the count line
  return `${line1}<span class="cook-last">Last cooked ${dateClause}</span>`;   // two stacked lines, no separator
}

// The inner contents of the stats bar (re-rendered after each change). THE RATING APPEARS ONCE, and
// which form it takes depends on how much there is to say:
//   • no cooks    -> no stars at all, just the nudge. An empty star row invites a click that the
//                    model has nowhere to put, since a verdict belongs to a cooking.
//   • ONE cook    -> ONE EDITABLE row. There is exactly one verdict, so the average IS it, and
//                    showing a read-only average above an editable copy was the same number twice.
//   • MANY cooks  -> the read-only average and what it averages over. Rating an individual cooking
//                    from here would need a row per cook, which is DEFERRED to the cook journal.
function statsInner(stats) {
  const many = stats.cook_count > 1;
  let ratingRow = "";
  if (stats.cook_count === 1 && stats.last_cook_id != null) {
    ratingRow = `<div class="rating rating-input" data-cook-stars role="group" aria-label="Your rating"
      data-cook-id="${stats.last_cook_id}" data-rating="${stats.rating == null ? "" : stats.rating}"
      >${starsInputHTML(stats.rating)}</div>`;
  } else if (many) {
    ratingRow = `<div class="rating rating-read">${starsReadHTML(stats.rating, stats.rated_cooks)}</div>`;
  }
  let middle = "";
  if (stats.cook_count) {
    middle = `<p class="cook-summary">${cookSummary(stats)}</p>`;
  } else {
    middle = `<span class="rate-hint">Log a cook to rate it</span>`;
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
  // The soft inset cook block: the rating (once), the summary, then the buttons.
  return `
    ${ratingRow}
    ${middle}
    <span class="cook-actions">
      <button class="btn" data-cook>Cooked it</button>
      <button class="btn alt" data-backdate-open title="Log a cook on a past date">Log a past cook</button>
      ${undoControls}
    </span>`;
}

// ⚠️ THE PER-COOK ROW LIST IS DEFERRED, NOT LOST. Each cooking already stores its own rating and
// note (migration 048), and GET /api/cooks?recipe=<id> already returns them. What is not built is
// the surface: a list of every cooking with its own stars and note belongs in the cook journal,
// where a cooking is the subject. On the recipe page it repeated the rating and the date the block
// above already showed. The route that writes one cooking's verdict stays, because the single-cook
// stars use it.

// Write one cooking's verdict. Only reachable while a recipe has exactly ONE cook, where that
// cooking's verdict and the recipe's number are the same thing.
async function patchCook(holder, body) {
  const id = holder.dataset.cookId;
  const { ok, data } = await sendJSON("PATCH", `/api/cooks/${encodeURIComponent(id)}`, body);
  if (!ok) return;
  if (view && view.data) view.data.stats = data;
  // Repaint the stars in place rather than re-rendering the whole block: statsInner would rebuild
  // the buttons under the cursor, which drops the hover state mid-gesture.
  holder.dataset.rating = body.rating == null ? "" : String(body.rating);
  holder.innerHTML = starsInputHTML(body.rating);
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
    return s;   // 3b-iii: expose the response (incl. cook_log_id) so "Cooked it" can offer the photo chip
  } catch (_) {
    /* leave the bar as-is if the write fails */
  }
}

// ---- 3b-iii: the "Cooked it" follow-on photo chip -------------------------------------------------
// After the one-click "Cooked it" logs a cook, a quiet auto-fading chip offers to attach photo(s) to THAT
// cook (dated). Purely additive — the no-photo path is unchanged; ignore the chip and it fades away. The
// cook already exists (logged on the click), so the attach is a plain best-effort batch to the held
// cook_log_id (no cook-create to sequence -> none of 3b-ii's hold-until-both / retry-holds-the-id needs).
let cookChip = null;   // { block, rid (raw slug), cookLogId, staged: [{file,url}], timer, el } | null

function clearCookChip() {
  if (!cookChip) return;
  if (cookChip.timer) clearTimeout(cookChip.timer);
  cookChip.staged.forEach((s) => URL.revokeObjectURL(s.url));   // free any staged previews
  if (cookChip.el && cookChip.el.parentNode) cookChip.el.remove();
  cookChip = null;
}

function fadeCookChip() {   // quiet auto-fade when the offer is ignored
  if (!cookChip || !cookChip.el) return;
  const el = cookChip.el;
  el.classList.add("fading");
  setTimeout(() => { if (cookChip && cookChip.el === el) clearCookChip(); }, 420);
}

function offerCookPhotoChip(block, rid, cookLogId) {
  clearCookChip();                                  // one offer at a time
  const el = document.createElement("div");
  el.className = "cook-followon";
  el.innerHTML = '<span class="cf-check">&#10003;</span> Cooked &mdash; ' +
    '<button class="cf-add" type="button" data-cf-add>add photos</button>' +
    '<button class="cf-x" type="button" data-cf-x aria-label="Dismiss">&times;</button>';
  block.appendChild(el);                            // sits under the cook-actions, in-context
  cookChip = { block, rid, cookLogId, staged: [], timer: null, el };
  cookChip.timer = setTimeout(fadeCookChip, 8000);  // calm 8s window if untouched — an offer, not a nag
  wireCookChipDnd(el);   // drag-drop + keyboard for the (later) staging zone; el persists across inner re-renders
}

// Drag-drop + keyboard for the chip's staging zone. Wired ONCE on the persistent chip element (el); the
// inner .bd-photo box is recreated by renderCookChipStaging, but these live on el and act on whatever
// .bd-photo is currently inside. Click-to-browse is the delegated [data-cc-add] handler.
function wireCookChipDnd(el) {
  const zone = () => el.querySelector(".bd-photo");
  ["dragenter", "dragover"].forEach((ev) => el.addEventListener(ev, (e) => { e.preventDefault(); const z = zone(); if (z) z.classList.add("dragover"); }));
  ["dragleave", "dragend"].forEach((ev) => el.addEventListener(ev, (e) => { if (!el.contains(e.relatedTarget)) { const z = zone(); if (z) z.classList.remove("dragover"); } }));
  el.addEventListener("drop", (e) => { e.preventDefault(); const z = zone(); if (z) z.classList.remove("dragover"); cookChipStage(e.dataTransfer && e.dataTransfer.files); });
  el.addEventListener("keydown", (e) => {   // Enter/Space on the empty zone (role=button) opens the picker
    if ((e.key === "Enter" || e.key === " ") && e.target.closest("[data-cc-add]")) { e.preventDefault(); el.querySelector(".cc-input").click(); }
  });
}

// Render the chip's staging surface — the SHIPPED .bd-photo thumbnail staging (reused verbatim) + an
// Attach button. Recreated on each change; the file input's change bubbles to the delegated listener.
function renderCookChipStaging() {
  if (!cookChip) return;
  const staged = cookChip.staged;
  const n = staged.length;
  let box;
  if (!n) {   // EMPTY: the real upload-zone invite (click-to-browse / drag) — no OS dialog ambush
    box = `<div class="bd-photo zone" data-cc-add tabindex="0" role="button" aria-label="Add photos to this cook">` +
      `<span class="bd-photo-ico">&oplus;</span><span class="bd-photo-lbl">add photos</span>` +
      `<span class="bd-photo-cap">drag here or click to choose</span></div>`;
  } else {    // STAGED: the shipped thumbnail grid + ＋ add-more
    const thumbs = staged.map((s, i) =>
      `<span class="bd-thumb"><img src="${s.url}" alt="" onerror="this.style.opacity=.3"><button class="x" type="button" data-cc-remove="${i}" aria-label="Remove photo">&times;</button></span>`
    ).join("");
    box = `<div class="bd-photo has-thumbs"><div class="bd-thumbs">${thumbs}` +
      `<button class="bd-thumb-add" type="button" data-cc-add aria-label="Add photos">＋</button></div>` +
      `<span class="bd-photo-cap">${n} photo${n > 1 ? "s" : ""} staged</span></div>`;
  }
  const attachBtn = n ? `<button class="btn sm" type="button" data-cc-attach>Attach ${n > 1 ? n + " photos" : "photo"}</button>` : "";
  cookChip.el.className = "cook-followon picking";
  cookChip.el.innerHTML = box +
    `<div class="cc-actions">${attachBtn}` +
    `<button class="btn ghost sm" type="button" data-cc-cancel>Cancel</button>` +
    `<span class="cc-err" data-cc-err></span></div>` +
    `<input class="cc-input" type="file" accept="image/*" multiple tabindex="-1" aria-hidden="true">`;
}

function openCookChipPick() {   // chip "add photos" -> stop the fade, SHOW the drop zone (user clicks/drags — no auto-open)
  if (!cookChip) return;
  if (cookChip.timer) { clearTimeout(cookChip.timer); cookChip.timer = null; }
  renderCookChipStaging();
}

function cookChipStage(files) {                      // stage picked images (isStageableImage rejects non-images)
  if (!cookChip) return;
  const list = Array.from(files || []).filter(Boolean);
  let rejected = 0;
  for (const f of list) {
    if (!isStageableImage(f)) { rejected++; continue; }
    cookChip.staged.push({ file: f, url: URL.createObjectURL(f) });
  }
  renderCookChipStaging();
  if (rejected) {
    const err = cookChip.el.querySelector("[data-cc-err]");
    if (err) err.textContent = rejected === 1
      ? "That's not an image — JPEG, PNG, WebP, or HEIC only."
      : `${rejected} files skipped — images only (JPEG, PNG, WebP, HEIC).`;
  }
}

function cookChipRemove(i) {                          // × : client-only unstage (pre-upload)
  if (!cookChip) return;
  const s = cookChip.staged[i];
  if (s) { URL.revokeObjectURL(s.url); cookChip.staged.splice(i, 1); renderCookChipStaging(); }
}

async function cookChipAttach(btn) {
  if (!cookChip || !cookChip.staged.length) return;
  const { rid, cookLogId, staged } = cookChip;      // rid is the RAW slug; cook already exists (no create/sequence)
  btn.disabled = true;
  const post = (s) => {
    const fd = new FormData();
    fd.append("image", s.file);
    fd.append("cook_log_id", String(cookLogId));    // DATED -> attach to the just-logged cook
    return fetch(`/api/recipes/${encodeURIComponent(rid)}/photos`,
                 { method: "POST", credentials: "same-origin", body: fd }).then((r) => r.status);
  };
  const results = await Promise.allSettled(staged.map(post));   // best-effort batch (3b-i)
  if (results.some((r) => r.status === "fulfilled" && r.value === 401)) { showAuth(); return; }
  let ok = 0; const failed = [];
  results.forEach((r, i) => {
    const st = r.status === "fulfilled" ? r.value : 0;
    if (st >= 200 && st < 300) { URL.revokeObjectURL(staged[i].url); ok++; }
    else failed.push(staged[i]);                    // keep the misses staged -> retry re-uploads to the SAME cook (no double-log)
  });
  if (failed.length) {
    cookChip.staged = failed;
    renderCookChipStaging();
    const err = cookChip.el.querySelector("[data-cc-err]");
    if (err) err.textContent = `Added ${ok}; ${failed.length} didn't upload. Try again.`;
    if (btn.isConnected) btn.disabled = false;
    return;
  }
  clearCookChip();                                  // all attached -> repaint so the album shows the new dated photos
  renderRecipe(rid);
}

/* ---------- router ---------- */
// Decides which view to show based on the address bar. We use the part after "#"
// so the browser never reloads the page or contacts the server for navigation:
//   #/                 -> the home list
//   #/recipe/mussakhan -> that recipe
//   #/new              -> the create form
//   #/edit/mussakhan   -> the edit form (app recipes only)
/* ---------- auth gate (auth-4) ----------
   A top-level state BEFORE the app renders: boot() asks GET /api/me; if logged out we show the
   login/signup split-spread and route()/the app never runs; once authenticated we hand off to the
   existing route(). The app's rendering (route/renderHome/paintRecipe/…) is untouched — it only runs
   inside showApp(). This is the whole integration seam. */

const HERO_SRC = heroUrl;   // the approved clean-B hero — bundled by Vite (committed source: static/login-hero.jpg)

function authGateHTML() {
  return `
  <main class="auth-spread">
    <section class="auth-hero">
      <img src="${HERO_SRC}" alt="">
      <div class="auth-hero-inner">
        <span class="auth-hero-kicker">Chef&rsquo;s Choice&ensp;&middot;&ensp;Est. 2026</span>
        <div>
          <h2 class="auth-hero-statement login-only">Cook what you love.<br><em>Remember</em> what worked.</h2>
          <h2 class="auth-hero-statement signup-only">A kitchen that<br><em>learns</em> your taste.</h2>
          <p class="auth-hero-cred">Ratings, cook history &amp; your own versions — in one place.</p>
        </div>
      </div>
    </section>
    <section class="auth-panel">
      <p class="auth-brand">Private&ensp;&middot;&ensp;Invite&nbsp;only</p>
      <h1 class="auth-wordmark">Chef&rsquo;s Choice</h1>
      <hr class="auth-divider">
      <form id="auth-form" novalidate autocomplete="on">
        <h2 class="auth-formhead login-only">Sign in to your kitchen</h2>
        <h2 class="auth-formhead signup-only">Create your account</h2>
        <div class="auth-field signup-only">
          <label for="auth-name">Display name</label>
          <input id="auth-name" name="display_name" type="text" autocomplete="name" placeholder="Your name">
        </div>
        <div class="auth-field">
          <label for="auth-email">Email</label>
          <input id="auth-email" name="email" type="email" autocomplete="email" placeholder="you@example.com">
        </div>
        <div class="auth-field">
          <label for="auth-pw">Password</label>
          <input id="auth-pw" name="password" type="password" autocomplete="current-password" placeholder="••••••••">
        </div>
        <div class="auth-field signup-only">
          <label for="auth-invite">Invite code</label>
          <input id="auth-invite" name="invite_code" type="text" autocomplete="off" placeholder="Enter your invite code">
        </div>
        <p class="auth-error" id="auth-error" role="alert" aria-live="polite"></p>
        <button class="auth-btn login-only" type="submit">Sign in</button>
        <button class="auth-btn signup-only" type="submit">Create account</button>
        <p class="auth-toggle login-only">Have an invite code? <button type="button" data-auth-toggle>Create an account</button></p>
        <p class="auth-toggle signup-only">Already have an account? <button type="button" data-auth-toggle>Sign in</button></p>
      </form>
    </section>
  </main>`;
}

function showAuth() {
  CURRENT_USER = null;
  // tear down any open drawer / modal so nothing floats over the login view
  document.querySelectorAll(".scrim, .panel[role='dialog'], .backdate-modal").forEach((el) => el.setAttribute("hidden", ""));
  app.style.display = "none";
  if (!authGate.dataset.wired) {
    authGate.innerHTML = authGateHTML();
    wireAuthGate();
    authGate.dataset.wired = "1";
  }
  authGate.classList.remove("signup");                 // default to the login state
  // Privacy (docs/SECURITY.md): the APP must not retain the previous session's typed credentials in the
  // DOM after logout. reset() clears our own field values; it does NOT disable the browser's own
  // password-manager/autofill (that re-populates on user focus and stays user-friendly).
  const form = document.getElementById("auth-form");
  if (form) form.reset();
  const err = document.getElementById("auth-error");
  if (err) err.textContent = "";
  authGate.hidden = false;
}

function showApp() {
  authGate.hidden = true;
  app.style.display = "";
  route();                                             // hand off to the existing renderer
}

function wireAuthGate() {
  authGate.querySelectorAll("[data-auth-toggle]").forEach((b) =>
    b.addEventListener("click", () => {
      authGate.classList.toggle("signup");
      document.getElementById("auth-error").textContent = "";
    })
  );
  document.getElementById("auth-form").addEventListener("submit", onAuthSubmit);
}

async function onAuthSubmit(e) {
  e.preventDefault();
  const signup = authGate.classList.contains("signup");
  const errEl = document.getElementById("auth-error");
  errEl.textContent = "";
  const email = document.getElementById("auth-email").value.trim();
  const password = document.getElementById("auth-pw").value;
  if (!email || !password) { errEl.textContent = "Please enter your email and password."; return; }

  let res;
  if (signup) {
    const display_name = document.getElementById("auth-name").value.trim();
    const invite_code = document.getElementById("auth-invite").value.trim();
    if (!invite_code) { errEl.textContent = "An invite code is required to sign up."; return; }
    res = await authRequest("POST", "/api/signup", { email, password, display_name, invite_code });
  } else {
    res = await authRequest("POST", "/api/login", { email, password });
  }

  if (res.ok && res.data && res.data.id) {               // login/signup return the user object
    CURRENT_USER = res.data;
    showApp();
    return;
  }
  // Failure: signup surfaces the SPECIFIC server message (bad/used/expired invite, duplicate email);
  // login stays GENERIC ("invalid credentials" from the backend — no email enumeration).
  const msg = (res.data && res.data.error) ? res.data.error : "Something went wrong — please try again.";
  errEl.textContent = msg.charAt(0).toUpperCase() + msg.slice(1);
}

async function boot() {
  try {
    const me = await authRequest("GET", "/api/me");      // public: 200 {user:null} or {user:{…}}
    if (me.ok && me.data && me.data.user) { CURRENT_USER = me.data.user; showApp(); }
    else { showAuth(); }
  } catch (_) {
    showAuth();                                          // network hiccup -> show login rather than a blank page
  }
}

// route() runs once at startup and again every time the "#" part changes.
async function route() {
  const hash = location.hash || "#/";
  try {
    const mEdit = hash.match(/^#\/edit\/(.+)$/);
    const mRecipe = hash.match(/^#\/recipe\/(.+)$/);
    // Recipe-page desk (the feed's surface texture) is route-scoped: paint it behind the recipe card
    // only, and strip it on every other route so it never bleeds onto home / the create/edit forms.
    document.body.classList.toggle("recipe-bg", !!mRecipe);
    // Browse desk, same surface at a bolder linen. Scoped the same way and for the same reason: the
    // background lives on <body> (the page itself is capped at 1400px and would leave the old taupe
    // showing at the edges), so home gets a body class rather than a rule the forms would inherit.
    // The condition is the router's own else-branch, spelled out: whatever falls through to renderHome.
    const isHome = !mRecipe && !mEdit && hash !== "#/new" && hash !== "#/feed";
    document.body.classList.toggle("browse-bg", isHome);
    if (hash === "#/new") {
      await renderForm("create");
    } else if (hash === "#/feed") {
      await renderFeed();
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
// The finalised wordmark, lifted VERBATIM from the approved logo (preview/LOGO-FINAL.html,
// sha f9a9cff6927c4668) — the three-lobe toque perched on the "Chef's" C at the locked em
// placement. It is one lockup: .bh-brand's font-size scales the mark, the wordmark AND the
// perch together, because the mark is positioned in em against the wordmark. Do not resize
// the mark or the wordmark separately, and do not edit the em values.
// FONT: the .wm rule uses the LITERAL "Kalam","Caveat",cursive, never var(--font-hand) — an
// em-positioned mark drifts if the family resolves differently. See styles.css.
// The only edit to the approved markup is the class token .cap -> .wm-cap, renamed off a
// collision with the Polaroid/album caption .cap. Nothing load-bearing: no font, no colour,
// no placement value changed.
const BRAND_LOCKUP = `<span class="wm" style="color:#7a4718"><span class="ch"><span class="wm-cap" style="color:#4E4B24">C</span><span class="mk" style="bottom:calc(0.952em + -0.046em);left:calc(50% + 0.176em);width:0.917em;transform:translateX(-50%) rotate(-9deg)"><svg viewBox="4 12 56 43" style="width:100%;height:auto;display:block" aria-hidden="true"><path d="M 26.8 19.3 A 11 11 0 1 0 26.8 36.7" fill="none" stroke="#4E4B24" stroke-width="6" stroke-linecap="round"/><path d="M 21.5 30 A 11.5 11.5 0 0 1 42.5 30" fill="none" stroke="#4E4B24" stroke-width="6" stroke-linecap="round"/><path d="M 50.8 19.3 A 11 11 0 1 0 50.8 36.7" fill="none" stroke="#9C4A2E" stroke-width="6" stroke-linecap="round"/><rect x="16" y="42" width="32" height="13" rx="3.5" fill="#4E4B24"/></svg></span></span>hef&rsquo;s <span class="wm-cap" style="color:#9C4A2E">C</span>hoice</span>`;

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
  const recipes = await api("/api/recipes");

  // ⚠️ MY TEST RECIPES, NOT EVERYONE'S. GET /api/recipes is deliberately not owner-filtered (every
  // recipe appears for every account, only the personal-layer aggregates are per-user), so counting
  // source === "test" alone counted other accounts' copies. The button then offered to delete them,
  // and the endpoint did. The server scopes the delete to the caller now, so a count that included
  // somebody else's would promise a delete that no longer happens.
  // ⚠️ is_mine, NOT owner. list_recipes pops the raw owner id and sends the boolean instead, as a
  // least-exposure signal, so reading r.owner here is undefined on every row and the count would be
  // a flat zero: the button would never appear and the fix would look like a feature removal.
  const testCount = recipes.filter((r) => r.source === "test" && r.is_mine).length;
  const bulkTest = testCount
    ? `<span id="test-bulk" data-count="${testCount}"><button class="btn danger-soft sm" data-delete-test>Delete ${testCount} test recipe${testCount > 1 ? "s" : ""}</button></span>`
    : "";

  // Browse runs wider than the 920px .page default (see .page.home-view), so all five nav items sit
  // on ONE row beside the 58px lockup: 311 + 408 + 200 + 165 = 1128 inside a 1312px content box.
  // The row still wraps, because a narrower viewport (a 1000px window gives 912px) cannot hold it.
  // Order is the old masthead's: bulk-delete, the three actions, then who. Every delegated hook is
  // preserved verbatim — [data-delete-test], [data-import-url], [data-logout].
  app.innerHTML = `
    <header class="browse-head">
      <h1 class="bh-brand">${BRAND_LOCKUP}</h1>
      <nav class="bh-nav">${bulkTest}<a class="btn ghost" href="#/feed">What&rsquo;s cooking?</a><button type="button" class="btn ghost" data-import-url>Import from URL</button><a class="btn new-recipe" href="#/new">+ New recipe</a>${
        CURRENT_USER ? `<span class="site-user">${esc(CURRENT_USER.display_name || CURRENT_USER.email)}<button type="button" data-logout>Sign out</button></span>` : ""
      }</nav>
    </header>
    <!-- .browse-body wraps everything BELOW the header so the left accent rule can hang off it: its
         top edge already sits 30px under the header's horizontal rule (the header's 46px margin less
         the rule's 16px drop), which is what keeps the two lines from closing a corner. -->
    <div class="browse-body">
      <div class="browse-tools">
        <span class="bt-field"><input id="browse-q" type="search" autocomplete="off" spellcheck="false"
          placeholder="Search recipes, sources and tags" aria-label="Search recipes, sources and tags"></span>
        <span class="bt-sort"><label class="bt-label" for="browse-sort">Sort</label>
          <select id="browse-sort">
            <option value="name" selected>Name</option>
            <option value="rating">Rating</option>
            <option value="cooks">Times cooked</option>
            <option value="last">Last cooked</option>
          </select></span>
      </div>
      <div class="recipe-grid" id="browse-grid"></div>
    </div>`;

  // All 298 recipes are already in memory, so search and sort are pure array work — no endpoint, no
  // round-trip, nothing to debounce. The two controls live OUTSIDE #browse-grid and only the grid's
  // innerHTML is rewritten, which is what keeps the caret, the typed value and the sort selection
  // intact across a repaint rather than needing to be restored afterwards.
  const gridEl = app.querySelector("#browse-grid");
  const qEl = app.querySelector("#browse-q");
  const sortEl = app.querySelector("#browse-sort");
  let query = "";
  let mode = "name";                                   // Name is the default sort

  const paint = () => {
    // Test (scratch) recipes still sink to the bottom. Array#sort is stable, so partitioning on
    // is-test AFTER browseList preserves the chosen order within each group.
    const shown = browseList(recipes, query, mode)
      .sort((a, b) => (a.source === "test") - (b.source === "test"));
    gridEl.innerHTML = shown.length
      ? shown.map((r) => browseCard(r, mode === "last")).join("")
      : `<p class="browse-empty">nothing matches &ldquo;${esc(query.trim())}&rdquo;, try fewer words</p>`;
  };

  qEl.addEventListener("input", (e) => { query = e.target.value; paint(); });
  sortEl.addEventListener("change", (e) => { mode = e.target.value; paint(); });
  paint();
}

// One card. showDate is true ONLY in "Last cooked" sort, where the date is what the reader is
// scanning by; in the other three modes it would be noise, so the footer omits it.
function browseCard(r, showDate) {
      const tags = cardTags(r);
      // The tab takes the first remaining tag. WHICH tag deserves the tab (a promoted course/type)
      // is a later tag pass — this keeps the existing order rather than inventing a mapping now.
      // 6 of 298 recipes have no tag once "Made" is removed, and those cards simply get no tab.
      const lead = tags[0];
      const tab = lead ? `<span class="rc-tab cat-${tagCategory(lead)}">${esc(lead)}</span>` : "";
      // Fit as many of the remaining tags as a card width takes, then count the rest. Colour comes
      // from the SHIPPED .cat-tag.cat-* rules (same class names the recipe page uses), not a copy.
      let used = 0;
      const shown = [];
      for (const t of tags.slice(1)) {
        if (shown.length && used + t.length > 34) break;
        shown.push(t);
        used += t.length + 2;
      }
      const over = tags.length - 1 - shown.length;
      const tagRow = tags.length > 1
        ? `<span class="rc-tags">${shown.map((t) => `<span class="cat-tag cat-${tagCategory(t)}">${esc(t)}</span>`).join("")}${
            over > 0 ? `<span class="rc-more">+${over} more</span>` : ""}</span>`
        : "";
      // The footer is the reader's own marks, in the annotation hand. Rating on the left, cooked
      // state on the right. The last-cooked date belongs here too but only makes sense once the
      // list can be sorted by it, so it lands with sort in stage (c).
      // ⚠️ WAS `"★".repeat(r.rating)`, which returned four stars and no remainder on a 4.5 — the row
      // lost a character rather than showing a half. The average is a fraction now, so the card uses
      // the same clipped-overlay fill the recipe page does, in the annotation hand.
      const stars = r.rating != null
        ? `<span class="rc-hwstars">${starsReadHTML(r.rating, r.rated_cooks)}</span>`
        : `<span class="rc-hw dim">not rated</span>`;
      // Cooked state reads cook_count. The "Uncooked" mark stays gated on isToMake() — is_mine AND
      // never cooked — so another user's uncooked recipe gets no mark (static/tomake.js, unit-tested).
      const when = (showDate && r.last_cooked) ? ` <span class="rc-hwdate">· last ${monthYear(r.last_cooked)}</span>` : "";
      const state = r.cook_count
        ? `<span class="rc-hw">cooked <span class="rc-hwnum">${r.cook_count}×</span>${when}</span>`
        : (isToMake(r) ? `<span class="rc-uncooked">Uncooked</span>`
                       : `<span class="rc-hw dim">not cooked yet</span>`);
      const isTest = r.source === "test";
      return `<a class="recipe-card${isTest ? " is-test" : ""}" href="#/recipe/${encodeURIComponent(r.id)}">
                ${tab}${photo(r, "rc-img")}
                <span class="rc-body">
                  <span class="rc-name">${esc(r.name)}${isTest ? ` <span class="test-badge">Test</span>` : ""}</span>
                  <span class="rc-by">${esc(r.author || "—")}</span>
                  ${tagRow}
                  <span class="rc-foot">${stars}${state}</span>
                </span>
              </a>`;
}

/* ---------- recipe view ---------- */

/* ---------- recipe view ---------- */

/* Quantity scaling (Phase 1a-1d). The pure logic + constants live in static/scaler.js, loaded as a
   global before this file (and unit-tested under Node, tests/js/). app.js keeps the DOM/rendering
   and passes view.scale into the scaler's amount/weight formatters. */

// One ledger figure cell — the amount or the weight, mono + tabular. A leading "~" (an estimated
// weight, or a humane-rounded amount) earns the shared "approx" treatment. (inlineStyle is unused
// now that the per-person coloured overlay is gone — R6; kept as an optional arg.)
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

// The amount-cell for a row whose AMOUNT was edited: the struck original over the ink correction,
// with the same gram sub-line an unedited row gets. The numbers come from annotation-amount.js
// (pure, tested); this is only the markup, so every value is esc()'d in one place.
function editedAmountCell(from, to, gramsPerMl, inlineStyle) {
  const p = editedAmountParts(from, to, gramsPerMl, view.scale);
  return `<span class="amount-cell">` +
         `<span class="qty"><span class="was">${esc(p.was)}</span><span class="fix">${esc(p.fix)}</span></span>` +
         (p.weight ? figCell("weight", p.weight, inlineStyle) : "") +
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
  const custom = `<input class="scale-custom${isPreset ? "" : " on"}" type="text" inputmode="decimal" placeholder="\u00d7" aria-label="Custom multiplier" value="${customVal}">`;
  return `<div class="scale-control" role="group" aria-label="Scale quantities">${buttons}${custom}</div>`;
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

// O-c-1 stage 3: place synthesized REMOVED rows at the BOTTOM of their original section — after the
// heading whose text matches entry.section, just before the NEXT heading (or the list end). A null
// section, or a section since renamed/removed (no match), falls back to the very bottom of the list.
// `items` is the built row list ({isHeading, headingText, html}); rows are spliced in, so the caller's
// heading-EXCLUDED counter is never advanced by them (they aren't in the diff's current sequence — see
// ingredientsSectionInner/renderStepsList, where the counter is driven solely by REAL rows).
function insertRemovedRows(items, removed, buildHTML) {
  for (const entry of removed) {
    // Placement is the pure rule in annotation-place.js (section bottom / preamble / list bottom).
    // Already-inserted removals aren't headings, so the index recomputes past them and a later removal
    // for the same section lands AFTER the earlier one — their old_pos order is preserved.
    const at = removedInsertIndex(items, entry.section);
    items.splice(at, 0, { isHeading: false, headingText: null, html: buildHTML(entry) });
  }
}

// A struck REMOVED ingredient, synthesized from the entry (the row is gone from the current data, so
// there is nothing to map over). `text` is the RAW combined "qty label" line and `label` is the name,
// so the amount is whatever precedes the name (removedAmountText, pure + tested). It renders
// abbreviated like the ledger, and ⚠️ AT view.scale: a struck row is still a row of this recipe, and
// it used to hold its printed amount while everything around it doubled. Same .amount-cell/.qty +
// .iname structure as a live row, so it sits in the ledger grid; .was gives it the shared 1px strike.
function removedIngredientRow(e) {
  const text = String(e.text || "");
  const label = String(e.label || "");
  const shown = removedAmountText(text, label, view.scale);
  return `<li class="removed">` +
    `<span class="amount-cell"><span class="qty">${shown ? `<span class="was">${esc(shown)}</span>` : ""}</span></span>` +
    `<span class="iname"><span class="was">${esc(label || text)}</span></span></li>`;
}

// A struck REMOVED step. Deliberately NOT li.step: that class carries the CSS step counter, so a removed
// step rendered as one would consume a number and renumber the live method. li.step-removed is UNNUMBERED
// and opts out of the counter, keeping 1,2,3… unbroken. .step-body gives .was the shared strike.
function removedStepRow(e) {
  return `<li class="step-removed"><div class="step-body"><span class="was">${esc(e.text || "")}</span></div></li>`;
}

// A plain ingredient line: used for the Original view and for app recipes. `ann` (O-c-1) is the row's
// grouped annotation slot ({amount?, name?, added?}) or undefined — undefined falls through to today's
// EXACT markup, so an unannotated row is byte-identical (clean recipes render unchanged).
// O-c-1 refinement: a WORD-LEVEL diff for name/step edits — strike only removed words, ink only added
// words, leave shared words as plain print. The tokenising + LCS live in word-diff.js (pure, tested);
// this is only the markup, so every token is esc()'d in one place before it reaches the DOM (no raw HTML
// from names). Parts carry their own leading `gap`, so they concatenate with no separator here —
// punctuation stays welded to the word it follows.
//
// `is-tight` carries gap=="" THROUGH TO CSS, because the markup alone cannot express it: .iname .fix has
// a deliberate 5px margin-left (the ink sits off the print), which still renders a visible space in front
// of an ink run that OPENS WITH PUNCTUATION — "garlic , finely grated" on screen from
// `garlic<span class="fix">, finely grated</span>`, with no whitespace anywhere in the markup. The class
// zeroes that one margin without touching the nudge everywhere else. Only .fix needs it: .was carries no
// margin (a struck tail already binds tight) and neither does .step-body .fix.
//   `i > 0` is required, not defensive: the FIRST part's gap is "" because nothing precedes it, not
//   because it binds to anything, so keying on gap alone would strip the nudge off a name-initial ink
//   run ("olive oil" -> "extra-virgin olive oil") that should keep it.
function wordDiffHTML(fromStr, toStr) {
  return wordDiffParts(fromStr, toStr).map((p, i) => {
    const text = esc(p.text);
    const tight = i > 0 && !p.gap;
    if (p.t === "del") return `${p.gap}<span class="was">${text}</span>`;
    if (p.t === "ins") return `${p.gap}<span class="fix${tight ? " is-tight" : ""}">${text}</span>`;
    return p.gap + text;
  }).join("");
}

function plainRow(row, ann) {
  // Guard (belt-and-suspenders): never render an empty row as a bare divider line, even if one somehow
  // reaches the reading view — a heading with no text, or a line with no name, is skipped entirely.
  // headingText, not raw_text: since migration 052 a heading converted from a line keeps the line's
  // source text in raw_text and its title in `heading`. A heading renders as its TITLE and nothing
  // else — the dormant amount, weight, note and links never reach the page.
  // showLinksAsWords for the same reason the step heading gets it: no heading is linkified, so any
  // markup that reached one would print its brackets. No live ingredient heading carries any, and
  // the rule is stated over headings rather than over the rows that happen to have some.
  if (row.is_heading) return headingText(row).trim() ? `<li class="group">${esc(showLinksAsWords(headingText(row)))}</li>` : "";
  if (!(row.label || row.raw_text || "").trim()) return "";
  // Added ingredient: the whole current line in the hand ink, "+"-prefixed (see li.added CSS).
  if (ann && ann.added) return `<li class="added">${ledgerCells(row.qty, row.grams_per_ml)}<span class="iname">${lineBodyHTML(row)}</span></li>`;
  const amt = ann && ann.amount, nm = ann && ann.name;
  // Amount edit stacks the struck original over the Kalam ink value INSIDE the 5rem cell (li.edited).
  // ⚠️ BOTH HALVES RENDER AT view.scale, like every other row. They used to render at a hardcoded 1,
  //    so an edited row stayed at its printed amount while the rows around it doubled. The gram
  //    sub-line comes back with them: an edited row is still a ledger row and keeps the column.
  const amountCell = amt
    ? editedAmountCell(amt.from, amt.to, row.grams_per_ml)
    : ledgerCells(row.qty, row.grams_per_ml);
  let iname;
  if (nm && amt) {
    // BOTH amount AND name change on one row: stack the name whole-field (struck over ink) so the struck
    // originals share the top line and the ink corrections share the bottom line — aligned with the amount
    // stack, reading as one line across (rather than the amount stacked and the name starting elsewhere).
    iname = `<span class="iname is-stacked"><span class="was">${esc(nm.from)}</span><span class="fix">${esc(nm.to)}</span>${readNote(row)}</span>`;
  } else if (nm) {
    // Name-only edit: WORD-LEVEL strike/ink — only the changed words are marked (see wordDiffHTML).
    iname = `<span class="iname">${wordDiffHTML(nm.from, nm.to)}${readNote(row)}</span>`;
  } else {
    iname = `<span class="iname">${lineBodyHTML(row)}</span>`;
  }
  const cls = amt ? ' class="edited"' : "";
  return `<li${cls}>${amountCell}${iname}</li>`;
}

// The whole Ingredients section — a plain list. R6 removed the per-person view switcher (the box
// model has no "switch person"; every recipe is your own, edited directly via the recipe editor).
// Re-rendered on its own (e.g. on a scale change) so the rest of the page doesn't flicker.
function ingredientsSectionInner(view) {
  const { ing, removedIng } = annotationIndex(view.data.annotations);   // O-c-1: edits keyed by ROW ID
  // Headings are tracked alongside each row so a removed entry can find its section (exact-string match
  // on the heading's raw_text). ⚠️ NO COUNTER ANY MORE: a mark is looked up by the row's own id, so
  // nothing here has to agree with the diff about where headings sit or which inserted rows to skip.
  const items = view.data.ingredients.map((row) => ({
    isHeading: !!row.is_heading,
    headingText: row.is_heading ? headingText(row) : null,
    html: row.is_heading ? plainRow(row) : plainRow(row, ing.get(row.id)),
  }));
  insertRemovedRows(items, removedIng, removedIngredientRow);
  const rows = items.map((x) => x.html).join("");
  return `
    <div class="col-head"><h2 class="col-title">Ingredients</h2></div>
    <ul class="ingredient-list">${rows}</ul>`;
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
  if (el) el.innerHTML = renderStepsList(view.data.steps);
}

// The masthead serving count reflects the current scale, but the masthead isn't rebuilt on rescale —
// so update just that number when the factor changes.
function rerenderServings() {
  const el = document.querySelector(".serves-count");
  const base = servingsBase();
  if (el && base) el.textContent = formatAmount(base * view.scale);
}

// A step's body: the tagged spans rendered, with the scalable ones at view.scale (stepSpanTexts,
// pure + tested) and the plain ones linkified. One place, so an added step and an ordinary step
// cannot drift apart on which numbers move.
function stepBodyHTML(row) {
  const spans = (row.spans && row.spans.length) ? row.spans : [{ t: "plain", text: row.text }];
  return stepSpanTexts(spans, view.scale)
    .map((s) => (s.t === "scale" ? `<span class="step-qty">${esc(s.text)}</span>` : linkify(s.text)))
    .join("");
}

// Render a step. Non-heading steps arrive as tagged spans (Phase 1d): "scale" spans are
// rescaled live with the 1a scaler (so they format identically to the ingredient list);
// "plain" spans are linkified (and may contain [[ingredient]] links). Falls back to raw
// text if a payload has no spans.
// ⚠️ THE TRAILING COLON IS DROPPED AT DISPLAY AND KEPT IN STORAGE. 90 of the 116 stored step
//    headings end in one, because a colon is how the importer RECOGNIZED them as headings in the
//    first place (import_cleanup.is_section). It is punctuation joining the label to text that is no
//    longer beside it, so it reads as a stray mark once the heading has a rule under it. Rewriting
//    90 rows to delete one character each would be a data change that buys nothing, and the editor
//    has to keep showing what is stored.
function stepHeadingTitle(text) {
  // showLinksAsWords FIRST: a trailing "[[garlic]]:" has to lose its brackets before the colon rule
  // can see the colon. See the note on showLinksAsWords — the markup stays in the stored text.
  return showLinksAsWords(text).trim().replace(/\s*:+$/, "");
}

// A heading's level as a class (migration 059). .h1 is a section heading, .h2 a subheading; both
// keep .group so every existing selector, the annotation reader and the edit-mode row all still see
// the row they always saw.
function stepHeadingClass(row) {
  return `group h${stepLevel(row)}`;
}

function renderStepRow(row, ann, notes) {
  if (row.is_heading) return `<li class="${stepHeadingClass(row)}">${esc(stepHeadingTitle(row.text))}</li>`;
  // O-c-1: an added step -> the whole line in the hand ink (NO "+" marker — a full paragraph of ink
  // against printed prose announces itself; see the .step-add note in styles.css); a reworded step ->
  // the struck original + the Kalam correction. Both are plain prose (no scaling/abbreviation — that's
  // amount-only).
  // ⚠️ AN ADDED STEP GOES THROUGH THE SPAN PATH, exactly like an unedited one, so its quantities
  //    move with the factor. It used to render row.text raw, which froze "add 1 tbsp oil" at its
  //    printed amount inside a doubled recipe.
  // ⚠️ THE MARKER IS APPENDED IN ALL THREE RETURNS. Both annotation branches returned before it,
  //    so a cook who attached a note to a step and then reworded that step lost the marker with
  //    nothing saying the link was still there. The row keeps its step_id either way, so this was
  //    the display dropping it. Live carries 49 annotation entries over 20 recipes.
  const marker = stepNoteMarkerHTML(notes, row.id);
  // ⚠️ "+ note" IS IN THE MARKUP ALWAYS AND REVEALED BY CSS, for the reason the ⋯ clusters already
  //    follow: a control that appears on hover by being INSERTED moves the text as the pointer
  //    crosses it. It is a real button, so :focus-visible reveals it for a keyboard user with no
  //    second code path.
  // ⚠️ OWNER ONLY. is_mine gates the markup and every note route asks again.
  // ⚠️ AND A PHONE HAS NEITHER HOVER NOR A TAB KEY. The tap target sits over the
  //    step's number circle, which is the one part of a step row that is not words, so tapping it
  //    cannot be mistaken for tapping the sentence. It is transparent and display:none above the
  //    phone breakpoint, so the reading page is unchanged on every other screen. `tapStep` is what
  //    the tap reveals, and the adder below reads it.
  const owns = !!(view && view.data && view.data.is_mine) && !(view && view.editMode);
  const tapped = String(noteState.tapStep) === String(row.id);
  const adder = owns ? addNoteButtonHTML(row.id, esc) : "";
  const numTap = owns
    ? `<button type="button" class="step-num-tap" data-step-tap="${row.id}" aria-expanded="${tapped}" aria-label="Notes on this step"></button>`
    : "";
  const box = noteNewBoxHTML(row.id);
  const cls = `step${tapped ? " step-tapped" : ""}`;
  if (ann && ann.added) return `<li class="${cls}">${numTap}<div class="step-body"><span class="step-add">${stepBodyHTML(row)}</span>${marker}${adder}</div>${box}</li>`;
  // ⚠️ A REWORDED STEP IS DELIBERATELY NOT SCALED, and this is the one gap left open. The word diff
  //    needs two raw strings, and only the CURRENT text has tagged spans, so scaling the pair means
  //    running the scaler over raw prose. Measured on the corpus's one reworded step, that turns
  //    "simmer for 4-6 minutes" into "8-12 minutes" at 2x. Doubling a cooking time is worse than
  //    leaving a quantity unscaled, so it waits for a tagger that can mark the baseline too.
  if (ann && ann.mod) return `<li class="${cls}">${numTap}<div class="step-body">${wordDiffHTML(ann.mod.from, ann.mod.to)}${marker}${adder}</div>${box}</li>`;
  const html = stepBodyHTML(row);
  // .step-body wraps the step content inside li.step — the reserved attach point for future
  // per-step photos. The note marker lives INSIDE it, at the end of the step's own text, which is
  // what keeps it out of the margin where the "your changes" marks are.
  return `<li class="${cls}">${numTap}<div class="step-body">${html}${marker}${adder}</div>${box}</li>`;
}

// O-c-1: render the step list with its annotation layer. Own 0-based li.step counter (heading-EXCLUDED,
// a SEPARATE index space from ingredients) == snapshot_diff step new_pos. Empty annotations -> byte-identical.
// The plan-ahead bullet's "Step 4" link. n is the number the page PRINTS, which is the CSS
// counter's sequence, so it indexes li.step specifically — li.group headings and the synthesized
// li.step-removed rows are both unnumbered and both correctly skipped by this selector.
// ⚠️ NO-OP IF THE STEP IS NOT THERE. The server already refuses to send a number whose check
//    failed, and this is the second guard for a repaint that has not landed yet.
// ⚠️ THE SAME FIGURE AS THE CSS ANIMATION, AND THEY HAVE TO MOVE TOGETHER. Removing the class
// before the animation ends cuts the highlight off mid-fade; leaving it on past the end means a
// second tap on the same step cannot restart it (the class is already there and the reflow trick
// below is what covers that). 2s of hold plus a 1.6s fade. See @keyframes step-ping in styles.css.
const STEP_PING_MS = 3600;

function jumpToStep(n) {
  const li = document.querySelectorAll("#steps-list li.step")[n - 1];
  if (!li) return;
  li.scrollIntoView({ behavior: "smooth", block: "center" });
  li.classList.remove("step-ping");
  void li.offsetWidth;                 // restart the animation if the same step is tapped twice
  li.classList.add("step-ping");
  setTimeout(() => li.classList.remove("step-ping"), STEP_PING_MS);
}

// ⚠️ THE HARDCODED "Note." IS GONE, AND IT IS WHAT ANDY SAW ON beans. This read
//    `<strong>Note.</strong> ${esc(note)}`, a label the renderer put in front of the WHOLE blob, so
//    a recipe whose author had already written "Note:" showed "Note. Note: Some legumes...". The
//    label was never in the data, which is why no amount of looking at the stored text found it.
//
//    Paragraphs now group under a header named for the kind their own label gives, and that label
//    comes off the shown text. A paragraph with no label, or one the table does not list, stays
//    under Notes with its text untouched — 17 of the corpus's labelled paragraphs are in that shape
//    ("Blind Bake:", "Tomato Bouillon:") and stripping a label nobody has approved would delete the
//    only thing naming what the note is about.
// ⚠️ KEEP IN STEP WITH notes.py STEP_MENTION AND note-blocks.js. A note names a step by NUMBER and
// by nothing else: measured over the 177 corpus paragraphs, 2 do that and 0 say "the step above" or
// "see step". Every match here becomes a link on the page, so a pattern that guessed at prose would
// put links on phrases nobody meant as a reference.
// ⚠️ THE SAME COMPONENT THE STEP POPOVER AND EDIT MODE USE (note-ui.js). This built its own <p> per
// note and was read-only, so a cook could read a note here and edit the same note somewhere else
// through different code. One renderer, one editor.
// ⚠️ "+ note" IS OWNER-ONLY AND THE SERVER AGREES. is_mine decides whether it is drawn, and every
// note route asks the same question again, because a hidden button is not an access rule.
function notesSectionHTML(rows) {
  const mine = !!(view && view.data && view.data.is_mine);
  const body = notesBodyHTML(rows, { editable: mine, place: "section" });
  if (!body && !mine) return "";
  // ⚠️ ONE QUIET ADDER, AT THE FOOT, FOR A NOTE THAT BELONGS TO NO STEP. A note about a step is
  //    added from that step, where the cook is already looking.
  const adder = mine
    ? `<button type="button" class="notes-add" data-add-note="general" aria-label="Add a note to this recipe">+ Add a note</button>`
    : "";
  if (!body) {
    // ⚠️ NO NOTES MEANS NO CARD. Live prints nothing at all under the method on a recipe with no
    //    notes, and an empty bordered box with "No notes yet." in it is a visible change to 205 of
    //    the 300 recipes — measured against the live commit, 116px of furniture where the page had
    //    none. The owner still gets the one quiet way in, and nothing else appears until there is
    //    something to show.
    return `<div class="notes-none">${noteNewBoxHTML("general")}${adder}${noteUndoHTML()}</div>`;
  }
  return `<div class="notes">${body}` +
    `${noteNewBoxHTML("general")}${adder}${noteUndoHTML()}</div>`;
}

// ⚠️ ONE ARRANGEMENT, BOTH VIEWS, AND THAT IS WHAT "THE SAME LOOK EVERYWHERE" MEANS IN CODE. The
// recipe page and Edit mode's Notes block called noteBlocks separately and laid the groups out
// themselves, so the two could drift by one template edit. There is one function now, and a group
// drawn here is the group drawn there.
// ⚠️ THE STEP NOTES GROUP COMES FIRST AND ONLY WHEN THERE IS ONE. No empty heading on the 294
// recipes with nothing attached to a step, and no "General" heading over the type groups either:
// the type IS the heading, so a second one above it names nothing.
// ⚠️ A MARKER MARKS A LIST, SO A GROUP OF ONE GETS NONE. The bullet says "these belong together
// and there are several"; drawn over a single note it is a list that is not a list. The hanging
// indent is what makes it worth having, because a wrapped second line then starts under the words
// rather than under the bullet.
function notesBodyHTML(rows, { editable, place }) {
  const { steps, blocks } = noteSections(rows || [], NOTE_KINDS.kinds);
  // ⚠️ EDIT MODE WRAPS EACH NOTE IN A ROW AND THE READING PAGE DOES NOT. The wrapper is what cuts
  //    the gutter the grip and the ⋯ sit in, which is the step row's own geometry; the reading
  //    page has no cluster, so its markup stays exactly as it was.
  // ⚠️ AND AN OPEN NOTE CARRIES NO CLUSTER. The panel already holds the type, the step link and
  //    the delete, so a second delete beside it would be two answers to one question, and there is
  //    nothing to drag while a note is being typed.
  // ⚠️ WHICH NOTES CAN BE DRAGGED IS ASKED ONCE, FOR THE WHOLE LIST. The answer depends on the
  //    other notes, not on the note, so asking per row would be the same count computed N times and
  //    a second place for the rule to live.
  const movable = place === "ie"
    ? noteDragMates(rows || [], currentSteps(), NOTE_KINDS.kinds) : null;
  const one = (n, led) => {
    const html = noteOne(n, {
      editable, place, where: "section",
      lead: led ? { no: n.stepLinkNo, type: tagLabel(kindOf(NOTE_KINDS.kinds, n.kind)) } : null,
    });
    if (place !== "ie") return html;
    const open = noteEditing(n.id, place);
    return `<div class="ie-noterow${open ? " open" : ""}" data-note-row="${n.id}">` +
      `${html}${open ? "" : noteRowToolsHTML(n.id, movable.has(String(n.id)))}</div>`;
  };
  const group = (header, notes, led) =>
    `<h3 class="notes-kind">${esc(header)}</h3>` +
    `<div class="notes-group${notes.length >= 2 ? " marked" : ""}">` +
    notes.map((n) => one(n, led)).join("") + `</div>`;
  return (steps.length ? group(STEP_NOTES_HEADER, steps, true) : "") +
    blocks.map((b) => group(b.header, b.notes, false)).join("");
}

// A note row's hover cluster. THE STEP ROW'S OWN, not a copy: the same .rtools, the same draggable
// .rbtn.grip carrying ING_GRIP, and the same ⋯ from rowMoreHTML, so the two rows share one control
// vocabulary, one stylesheet and one menu component.
// ⚠️ data-i CARRIES THE NOTE'S ID, NOT AN INDEX, which is the ONE thing that differs from the other
//    two callers. Every path to a note in this file is by id (and a note added this session has a
//    negative one, which is no list index at all), so handleRowMenuAction reads the value as an id
//    when the kind is "note" and as an index otherwise. The attribute is shared; its meaning is
//    branched in exactly one place.
// ⚠️ THE GRIP IS DRAWN ONLY WHERE IT CAN DO SOMETHING. A note alone in its drag group has no legal
//    drop target, so a handle on it offers a move that always snaps back. noteDragMates decides,
//    read from the draft on every repaint, so an add, a delete, a relink or a type change gives or
//    takes the handle away as it happens. The ⋯ stays either way: adding and deleting are still
//    there for a lone note. STEPS ARE UNCHANGED — a step list is one group, so a step always has
//    somewhere to go and its grip is unconditional.
function noteRowToolsHTML(id, canDrag) {
  const grip = canDrag
    ? `<span class="rbtn grip" draggable="true" title="Drag to reorder" aria-hidden="true">${ING_GRIP}</span>`
    : "";
  return `<span class="rtools">
    ${grip}${rowMoreHTML(id, "note")}
  </span>`;
}

// One call site for every place a note is drawn, so the four opts that decide what it looks like are
// read from one piece of state rather than spelled out three times.
function noteOne(n, opts) {
  return noteRowHTML(n, NOTE_KINDS.kinds, esc, {
    ...opts,
    editing: noteEditing(n.id, opts.place),
    draft: noteDraft(n.id),
    titleDraft: noteTitleDraft(n.id),
    saved: noteJustSaved(n.id),
    steps: currentSteps(),
    kindMenu: noteState.kindMenuFor === n.id,
    stepMenu: noteState.stepMenuFor === n.id,
    pick: noteState.stepMenuFor === n.id ? pickState(n) : null,
  });
}

// ⚠️ THE STEPS THE PICKER OFFERS ARE THE ONES ON SCREEN. In Edit mode that is the draft, which
// may already hold a step added this session and no longer hold one deleted in it. Offering
// view.data would list a step the cook has just removed and refuse one they have just written.
function currentSteps() {
  const d = (view && view.editMode && view.draft) ? view.draft : (view && view.data);
  return (d && d.steps) || [];
}

// ⚠️ IN EDIT MODE A NOTE IS A DRAFT ROW, AND IT IS RESOLVED AGAINST THE DRAFT'S STEPS. The server
// resolved step_no for the rows it sent, and the draft may since have gained a step or lost one, so
// a link to a step the cook has just deleted has to read as unlinked BEFORE the save rather than
// only after it. Reading view.data here is what made Edit mode show the database rather than the
// edit.
function noteRows() {
  if (view && view.editMode && view.draft) {
    return resolveNoteSteps(view.draft.notes || [], view.draft.steps || []);
  }
  return (view && view.data && view.data.notes) || [];
}

// Whether a note write goes to its own endpoint now or waits for Save changes. One question, asked
// in one place, so the six write paths below cannot answer it differently.
function noteHeld() {
  return !!(view && view.editMode && view.draft);
}

// A held write: swap the draft's list, mark the page dirty exactly as a step or an ingredient edit
// does, and repaint. Nothing reaches the network.
function holdNotes(next) {
  view.draft.notes = next;
  markDirty();
  repaintNotes();
  return Promise.resolve();
}

// The note as the DRAFT holds it, which is what a held write has to read and change.
function draftNote(id) {
  return (view.draft.notes || []).find((n) => String(n.id) === String(id));
}

// The picker's rows for one note: the method, filtered by what has been typed, with the cursor on
// the current link unless the filter has hidden it.
function pickState(note) {
  const rows = filterRows(pickerRows(currentSteps(), stepPickText), noteState.pickQuery);
  const steps = stepRowsOf(rows);
  const cursor = steps.some((r) => String(r.id) === String(noteState.pickCursor))
    ? noteState.pickCursor
    : startCursor(rows, note.step_id);
  return { rows, query: noteState.pickQuery, cursor };
}

// The cleaner step-picker.js is handed. A heading loses its trailing colon the way the method's own
// heading does (stepHeadingTitle) and a step loses its [[key|label]] markup the way the method's own
// text does (showLinksAsWords), so a row in the list reads as the step reads on the page.
function stepPickText(text, isHeading) {
  return isHeading ? stepHeadingTitle(text) : showLinksAsWords(text);
}

// --- the note component's session state ----------------------------------------------------------
// ⚠️ WHICH NOTE IS OPEN IS VIEW STATE, NOT DRAFT STATE, and it lives here rather than in view.draft
// because notes are edited in READING view too, where there is no draft at all. One place, read by
// both renderers.
// ⚠️ THE TITLE HAS ITS OWN DRAFT MAP, NOT A FIELD INSIDE THE TEXT ONE. `drafts` holds a STRING per
// note id and a dozen places read it that way (noteDraft, noteTextChanged, the growNoteInput
// handler), so widening it to an object would be a change to every one of them for one new field.
// ⚠️ A NOTE THAT DOES NOT EXIST YET IS AN OPEN EDITOR LIKE ANY OTHER. "+ note" sets editingId
// to NEW_NOTE_ID and newRow to the row the panel is drawn over, so the caret restore, the
// click-away save, Enter, Escape, the type menu and the step picker are the SAME code they are for
// a stored note. `newOn` says WHERE the box is drawn, which is still a separate question: the box
// belongs to one step row or to the Notes section, and nothing else may draw it.
const noteState = { editingId: null, editingPlace: null, drafts: new Map(),
                    titleDrafts: new Map(), focusField: "text", newOn: null,
                    newRow: null, savedId: null, savedBefore: null, savedNew: false,
                    kindMenuFor: null,
                    stepMenuFor: null, undo: null, tapStep: null,
                    // the picker: what has been typed, where the arrows are, and which note is
                    // waiting for a step to be clicked on the page
                    pickQuery: "", pickCursor: null, pickingFor: null };

// ⚠️ (NOTE, PLACE), NOT JUST NOTE. A note linked to a step is drawn in the Notes section and in that
// step's popover, so keying on the id alone opened a textarea in both and the one that blurred last
// decided what was saved. Measured on the bagel: one click, three editors.
function noteEditing(id, place) {
  return noteState.editingId === id && noteState.editingPlace === place;
}
function noteDraft(id) { return noteState.drafts.has(id) ? noteState.drafts.get(id) : null; }
function noteTitleDraft(id) {
  return noteState.titleDrafts.has(id) ? noteState.titleDrafts.get(id) : null;
}
function noteJustSaved(id) { return noteState.savedId === id; }

// ⚠️ ONE UNDO AT A TIME, AT THE FOOT OF THE NOTES. A toast per deleted note would stack, and the
// offer only covers the most recent delete.
function noteUndoHTML() {
  const u = noteState.undo;
  return u ? undoToastHTML(u.what, u.token, esc) : "";
}

// The "+ note" panel, drawn where it was opened and nowhere else. `where` is a step id or
// "general".
// ⚠️ THE SAME OPTIONS noteOne PASSES, FROM THE SAME STATE. The panel carries a type menu and a
//    step picker now, and those read noteState.kindMenuFor and noteState.stepMenuFor exactly as a
//    stored note's do. Spelling them out differently here is how one of the two stops working.
// ⚠️ AND step_no IS RESOLVED, NEVER STORED. The row has a step_id and no number, because a
//    number is a position in the list the page is drawing right now.
function noteNewBoxHTML(where) {
  if (String(noteState.newOn) !== String(where) || !noteState.newRow) return "";
  const row = resolveNoteSteps([noteState.newRow], currentSteps())[0];
  return newNoteBoxHTML(row, where, NOTE_KINDS.kinds, esc, {
    place: `new:${where}`,
    draft: noteDraft(NEW_NOTE_ID),
    titleDraft: noteTitleDraft(NEW_NOTE_ID),
    steps: currentSteps(),
    kindMenu: noteState.kindMenuFor === NEW_NOTE_ID,
    stepMenu: noteState.stepMenuFor === NEW_NOTE_ID,
    pick: noteState.stepMenuFor === NEW_NOTE_ID ? pickState(row) : null,
  });
}

// {step id -> the notes attached to it}. Built once per render so a step row does not scan the list.
// ⚠️ INLINE, AT THE END OF THE STEP, IN BODY COLOUR — NEVER IN THE MARGIN. The margin is where the
// "your changes" marks live, and a reader who learns that the left edge means "you edited this"
// must not meet a second marker there meaning something else entirely. This one sits in the text
// flow, is a BUTTON rather than a passive dot, and carries the note it opens.
// ⚠️ TWO NOTES ON ONE STEP GET ONE MARKER SHOWING BOTH, because two markers on one sentence reads
// as two different kinds of thing.
function stepNoteMarkerHTML(notes, stepId) {
  if (!notes || !notes.length) return "";
  const id = `note-pop-${stepId}`;
  const label = notes.length > 1 ? `${notes.length} notes on this step` : "a note on this step";
  // ⚠️ NO WHITESPACE INSIDE THE BUTTON. .step-body is white-space: pre-wrap, so a newline and an
  //    indent in this template render as a gap between the step's full stop and the marker. Written
  //    on one line on purpose.
  // ⚠️ A WORD, NOT A GLYPH. The circled i was one of three options previewed on :8003 and the tag is
  //    the one that cannot be missed or mistaken for punctuation. The word is in the MARKUP rather
  //    than in a ::after, so a screen reader and a copy-paste both get it.
  // ⚠️ role="dialog", NOT role="tooltip", NOW THAT IT HOLDS CONTROLS. A tooltip is a description and
  //    is announced as one, so the Delete button and the type control inside it were unreachable in
  //    that role. The popover is still opened by hover and focus exactly as before.
  // ⚠️ EACH NOTE CARRIES ITS OWN TYPE LABEL. Two notes on one step are two different kinds of thing
  //    as often as not ("Tip" above "Storage"), and one shared header above a stack cannot say so.
  // ⚠️ AND A REFERENCE TO THIS VERY STEP READS AS WORDS. See noteBodyHTML's selfStepId: a link that
  //    scrolls the reader to where they already are is noise.
  const mine = !!(view && view.data && view.data.is_mine);
  return ` <button type="button" class="step-note-marker" aria-expanded="false" aria-controls="${id}" aria-label="${esc(label)}" data-step-note="${stepId}">note</button>` +
    `<span class="step-note-pop" id="${id}" role="dialog" aria-label="${esc(label)}" hidden>` +
    notes.map((n) => noteOne(n, {
      editable: mine, selfStepId: stepId, place: `pop:${stepId}`, where: "pop",
    })).join("") +
    `</span>`;
}

function renderStepsList(steps) {
  const { step, removedStep } = annotationIndex(view.data.annotations);   // keyed by ROW ID
  // ⚠️ A NOTE ON A ROW THAT IS NOW A HEADING IS NOT SHOWN, and its link is still stored. The server
  //    keeps step_id and simply resolves no number, so this index only ever reaches ordinary steps.
  const noteBy = stepNoteIndex(view.data.notes, NOTE_KINDS.kinds);
  const items = steps.map((row) => ({
    isHeading: !!row.is_heading,
    headingText: row.is_heading ? (row.text || "") : null,
    html: row.is_heading ? renderStepRow(row)
                         : renderStepRow(row, step.get(row.id), noteBy.get(row.id)),
  }));
  insertRemovedRows(items, removedStep, removedStepRow);
  return items.map((x) => x.html).join("");
}

// The per-step controls: the SAME hover-revealed cluster the ingredient rows use (.rtools / .rbtn /
// ING_GRIP), minus the affordances that are ingredient-only.
// A stage 2 completes this cluster. The inline trash is GONE — step delete is now a .danger item in
// the ⋯ menu — and the deferred reorder grip lands in its place, so the cluster is grip + ⋯ = 52px and
// the 62px gutter is settled for good (see the table in styles.css).
// The two lists are deliberately ASYMMETRIC about delete: ingredients keep a one-click trash, steps do
// not. That is not an oversight — a step row's cluster is absolutely positioned into a fixed gutter cut
// out of the text column, so every inline control there costs step text width; the ingredient row's
// cluster sits in a flexible .tail and costs only the name column's slack. Steps pay more for the same
// control, and step deletion is rarer than ingredient deletion.
// The grip is LIVE as of C2 and is now the DRAG SOURCE itself (the drag listeners are still delegated,
// so the grip carries no handler). It stays aria-hidden because the drag is mouse-only — there is no
// keyboard path for it to announce. See ROADMAP, "Known limitations & tech debt".
// GRIP-ONLY DRAG (supersedes C1/C2's draggable-on-the-whole-row). `draggable` lives on the .rbtn.grip
// spans, NOT on the row. Two reasons, and the second was measured:
//   1. Wanted on its own: a drag should start from the visible handle, not from anywhere in the row.
//   2. A draggable ancestor COMPETES WITH TEXT SELECTION, but only past the end of the text. Over a
//      glyph, Chromium gives the press to the field; past the last character there is no glyph to
//      select from, so it falls back to the draggable ancestor and the drag wins — selection never
//      starts. Measured on both lists: with draggable on the row, pressing past the text and dragging
//      left selected ""; with it removed, the same gesture selected "mirin" (ingredient) and
//      "months." (step). A bare textarea with no draggable ancestor selects there natively.
// C1/C2 rejected grip-only because the browser's default drag image would be the 24px grip. That
// objection is dead: setDragPill builds its own element and calls setDragImage on it, never touching
// the source element, so the source's size no longer affects what is carried. The ONE residual is
// setDragPill's silent-failure path (see its comment) — if setDragImage ever fails, the fallback
// snapshot is now the grip rather than the row. Cosmetic, and the rAF-deferred .ghost-origin already
// exists for exactly that fallback.
// Both dragstart handlers already resolve upward (`e.target.closest(... li ...)`), so moving the
// attribute changed no handler: e.target becomes the grip (or its SVG) and .closest still finds the row.
function editStepRowTools(i) {
  return `<span class="rtools">
    <span class="rbtn grip" draggable="true" title="Drag to reorder" aria-hidden="true">${ING_GRIP}</span>
    ${rowMoreHTML(i, "step")}
  </span>`;
}

// Stage 1a (edit mode only): a non-heading step becomes an empty host that mountStepEditors() fills
// with a per-step TipTap editor. `data-i` indexes view.draft.steps, matching the mount lookup.
// Heading steps stay display-only (byte-identical to reading mode's li.group), but — matching the
// ingredient side, where editIngRowHTML gives a heading row the same trash — they get the remove
// control too. The heading markup is spelled out here rather than delegating to renderStepRow so the
// annotation reading path stays untouched.
function renderStepEditHost(row, i) {
  const tools = editStepRowTools(i);
  // Grip-only: the row is NOT a drag source (see the note above editStepRowTools).
  if (row.is_heading) return `<li class="${stepHeadingClass(row)} step-edit">${editStepHeadingField(i, row.text)}${tools}</li>`;
  return `<li class="step step-edit"><div class="step-editor-host" data-i="${i}"></div>${tools}</li>`;
}

// A step heading's editable field. A PLAIN <input> — not TipTap: a section label has no [[key|label]]
// chips, no scale spans and no meaningful undo history, and keeping it out of step-editor.js means the
// island invariant is never extended to a second row type.
// It carries its OWN data-inline-edit-step namespace, deliberately NOT ieCell's data-inline-edit-ing:
// four delegated handlers dispatch on that attribute and index view.draft.ingredients[data-i], so a
// heading rendered with ieCell would silently write into the INGREDIENT array at the step's index.
// No .ie-ov overlay either — that machinery (with the focusout mirror and the mousedown caret
// hit-test) exists because the ingredient NAME column is narrow and a <textarea> can't ellipsize; a
// step heading spans the full method column and is short. Placeholder copy matches the ingredient
// heading's, so the two columns read the same when empty.
function editStepHeadingField(i, text) {
  // ⚠️ THE WORDS, NOT THE MARKUP, AND THAT COSTS NOTHING BECAUSE THIS FIELD ONLY WRITES ON `input`.
  // The delegated handler flushes sh.value into the draft row when the user TYPES; a heading nobody
  // touches keeps the text it was rendered from, markup included. So the brackets are never on
  // screen and the link still comes back if the row is converted to a step again. A cook who does
  // edit the heading gets exactly the words they see, which is the only honest answer for a field
  // whose value is written back verbatim.
  return `<input type="text" class="ie e-step-heading" data-inline-edit-step="heading" data-i="${i}" value="${esc(showLinksAsWords(text))}" placeholder="Section heading" aria-label="Section heading" spellcheck="false">`;
}

// Editor parity stage 3: the step list's adder — the SAME .adder control the ingredient list ends with,
// so no new vocabulary. It lives OUTSIDE #steps-list for two reasons: rerenderEditSteps() owns that
// <ol>'s innerHTML (anything inside would be destroyed and rebuilt on every add/remove), and a <div> is
// not a legal <ol> child. Being a sibling, it survives every remount cycle untouched and needs no
// re-render of its own. NB: no "+ section heading" here yet — the heading field lands in this stage;
// the adder that uses it is stage 2.
function stepAddersHTML() {
  return `<div class="step-adders">
      <button type="button" class="adder" data-inline-edit-add-step>+ add step</button>
    </div>`;
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

// One lookup, shared by the recipe page's tagsHTML and the browse card, so the two can never drift
// onto different colour vocabularies.
const tagCategory = (t) => TAG_CATEGORY[String(t).toLowerCase()] || "neutral";

// cardTags now lives in static/browse.js, because the SEARCH reads the same list the card shows:
// a tag hidden from the card ("Made") must not quietly match a query either.

// Category -> discreet mono "filing" labels, tinted by category. Non-clickable for now
// (tag-click-to-filter is the R2 browse redesign). neutral = plain; status = the quiet treatment.
function tagsHTML(r) {
  const tags = String(r.category || "").split("·").map((s) => s.trim()).filter(Boolean);
  if (!tags.length) return "";
  const html = tags.map((t) => {
    const cat = tagCategory(t);
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
// ⚠️ TWO NEW ICONS, and they are the only drawn elements in this feature. The clock, the figure and
// every other mark on the page were lifted rather than redrawn. These are new because the app has no
// hourglass and no jar, and reusing the clock for the wait row put two clocks in one stack.
// Same 24-box, same 1.5 stroke, same round caps and joins, same 15px render as .meta-ico.clk.
const META_HOURGLASS = `<svg class="meta-ico hg" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3 H18"/><path d="M6 21 H18"/><path d="M7 3 V6.5 C7 9 12 11 12 12 C12 11 17 9 17 6.5 V3"/><path d="M7 21 V17.5 C7 15 12 13 12 12 C12 13 17 15 17 17.5 V21"/></svg>`;
const META_JAR = `<svg class="meta-ico jar" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 2.5 H16 V5 H8 Z"/><path d="M7.5 5 H16.5 A2 2 0 0 1 18.5 7 V19 A2.5 2.5 0 0 1 16 21.5 H8 A2.5 2.5 0 0 1 5.5 19 V7 A2 2 0 0 1 7.5 5 Z"/><path d="M5.5 10.5 H18.5"/></svg>`;
// ⚠️ MIRRORS planahead.VERBS. The breakdown bullet reads as an instruction ("Chill 4 hr"), not as
// a label with the verb tacked on the end ("4 hr chilling").
const WAIT_VERBS = { marinating: "Marinate", chilling: "Chill", rising: "Rise", soaking: "Soak",
                     resting: "Rest", freezing: "Freeze", brining: "Brine", other: "Wait" };
// The place in the words the storage bullet uses. "other" names no place and drops out.
const STORE_PLACE = { fridge: "fridge", freezer: "freezer", "room temp": "room temperature", other: "" };
const META_CLOCK = `<svg class="meta-ico clk" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="7.5"/><path d="M12 9 V13 L15 15"/><path d="M9.5 3 H14.5"/></svg>`;

// The time block above the Ingredients heading: the times on the left, what has to be planned
// ahead on the right, the scaler underneath. Round 3's layout (Andy picked B off the preview).
//
// ⚠️ THE SECOND COLUMN EXISTS ONLY WHEN SOMETHING IS IN IT. A recipe with no waits reads as one
//    column at full width rather than as a half-empty row, which is the whole reason the split is
//    conditional rather than a grid every recipe pays for. Keeps is the one that moves: on its own
//    it belongs with the times, and beside Plan ahead it belongs with the waits, because that is
//    where a cook reads "this needs tomorrow" and "this will last".
//
// ⚠️ AND EACH TIME GETS ITS OWN LINE. They were one line joined by middots, which fits in a
//    581px column and wraps into three ragged lines in a 245px one. A column that can wrap a value
//    away from its label is a column that cannot hold a value, so the line break is stated.
//
// ⚠️ THE ROW NEVER SCALES. It lives here beside the times, which the scaler already passes through
//    untouched: doubling a recipe does not double a rise.
function scaleMetaBlock(r) {
  // ⚠️ TOTAL IS THE SERVER'S ANSWER, NOT r.total_time. A recipe with no stated total still gets one,
  //    computed from prep + cook + the counted waits, and a recipe whose prep already swallowed its
  //    marinade can be ruled the other way. That decision needs the waits and a per-recipe ruling, so
  //    it is made once in planahead.recipe_total and printed here. r.total_time is still what the
  //    EDITOR shows, because a field being edited must show what is stored.
  const totals = (view.data && view.data.total) || {};
  const conds = (view.data && view.data.conditional_totals) || [];
  const waits = view.waits || [];
  const storage = view.storage || [];

  // One row of the stack: the 26px icon column, then the text. Only the first row of a group
  // carries an icon, so Prep / Cook / Total read as one thing rather than as three clocks.
  const row = (icon, body, cls) =>
    `<span class="meta-item${cls ? " " + cls : ""}">${icon || `<span aria-hidden="true"></span>`}`
    + `<span>${body}</span></span>`;

  // ⚠️ THE TOTAL IS NOT RE-SPLIT HERE. Prep and Cook are raw stored strings and need timeParts. The
  //    Total arrives from the server already normalized and already split, and running timeParts
  //    over it TRUNCATED A RANGE: the segment reader stops at the en dash, so "40 min – 45 min" came
  //    back as "40 min". Measured on miso-tofu, butter-chicken and brioche-bread.
  // ⚠️ NORMALIZED ON THE WAY OUT, AND THE STORED TEXT IS NEVER REWRITTEN. 40 of the 63 distinct
  //    stored spellings are another way of writing the same duration ("10 min", "10 mins",
  //    "10 minutes"), and normalizing on save would edit a cook's own words for them.
  const times = [["Prep", r.prep_time, ""], ["Cook", r.cook_time, ""],
                 ["Total", totals.label || "", totals.note || ""]]
    .filter(([, v]) => (v || "").trim())
    .map(([label, v, serverNote], i) => {
      const isTotal = label === "Total";
      const { value, note } = isTotal ? { value: v, note: serverNote } : timeParts(v);
      // The note is its own span so it can stay at the inherited 400 while .meta-val carries the
      // 600 that makes the figure land. The parentheses and the weight then say the same thing.
      const tail = note ? `<span class="meta-note"> (${esc(bindUnits(note))})</span>` : "";
      return row(i === 0 ? META_CLOCK : "",
                 `${label} <span class="meta-val">${esc(bindUnits(value))}</span>${tail}`);
    }).join("");

  // ⚠️ THE SECOND TOTAL SITS UNDER THE TOTAL AND IS SMALLER. One line per conditional wait, each
  //    naming its own condition, so a cook who is going to take that path reads the figure instead
  //    of working it out from the Total and a bullet. The main Total is unchanged. The server
  //    computes both (planahead.conditional_totals) and writes the wording
  //    (planahead._conditional_phrase, "if you soak"), for the reason it computes the Total: one
  //    implementation, and the client prints what it is handed.
  const second = conds.filter((c) => c && c.label).map((c) =>
    row("", `<span class="meta-val">${esc(bindUnits(c.label))}</span>`
            + (c.when ? ` ${esc(c.when)}` : ""), "meta-conditional")).join("");

  // ⚠️ THE KIND READS AS A VERB AND IT LEADS. "Chill 4 hr" is an instruction. "4 hr chilling" is a
  //    label with the verb tacked on the end. Mirrors planahead.VERBS.
  const verb = (w) => WAIT_VERBS[w.kind] || WAIT_VERBS.other;
  // ⚠️ THE STEP NUMBER LINKS ONLY WHEN THE SERVER SAYS THE POINTER STILL HOLDS. step_no comes back
  //    null when the stored pointer names no numbered step, and the line then reads with no step
  //    number rather than scrolling to the wrong one.
  const stepTag = (no, label) => (no
    ? `<a class="meta-step" href="#" data-wait-step="${no}">${label || "step " + no}</a>` : "");
  // ⚠️ "alongside step N" IS A QUALIFIER, NOT A SECOND STEP LINK. It says why this wait is not in
  //    the total: it happens during another one. A pointer the server could not resolve leaves
  //    alongside_no null and the wait reads without the phrase rather than with a wrong number.
  const qual = (w) => {
    const k = w.when_kind || "always";
    if (k === "optional") return `<span class="meta-when">(optional)</span>`;
    if (k === "only_if") return `<span class="meta-when">if ${esc(w.when_label || "")}</span>`;
    if (k === "alongside") return w.alongside_no
      ? `<span class="meta-when">alongside step ${w.alongside_no}</span>` : "";
    return "";
  };
  // ⚠️ THE ALTERNATIVE TAKES ITS OWN LINE, IN BOTH PLACES IT CAN APPEAR. It is an INVITATION rather
  //    than part of the range, so it reads quieter than the figure it qualifies. beans soaks
  //    overnight at step 2 and describes its 90 minute quick soak at step 3, so the alternative can
  //    carry its own step link that the wait's own does not.
  // ⚠️ THE LEADING SPACE IS NOT DECORATION, AND THE REBUILD DELETED IT ONCE ALREADY. Without it the
  //    markup runs "(optional)or a 90 minute quick soak" with nothing between the two spans. On
  //    screen the block display hides that, and a COPY of the line shows it. A block element is one
  //    CSS line away from not being one, and the text should read correctly either way. 9 of live's
  //    111 waits carry an ext_label, so 9 lines read that way for the fortnight it was gone.
  const ext = (w) => (w.ext_label
    ? ` <span class="meta-ext">${esc(bindUnits(w.ext_label))}`
      + (w.ext_no ? ` (${stepTag(w.ext_no)})` : "") + `</span>` : "");
  const DOT = `<span class="meta-sep"> · </span>`;
  // ⚠️ label_text, NOT label. The server decides what a wait PRINTS (planahead.display_label), so
  //    "overnight" arrives as "8 hr+ (overnight)" and there is no second copy of that rule here.
  //    label is still the stored text and is what the editor shows.
  const waitLine = (w) => {
    const bits = [`<span class="meta-do">${esc(verb(w))}</span> `
                  + `${esc(bindUnits(w.label_text || w.label || ""))}`];
    if (w.step_no) bits.push(stepTag(w.step_no));
    const q = (w.when_kind || "always") !== "always" ? qual(w) : "";
    if (q) bits.push(q);
    return `<li class="meta-bullet">${bits.join(DOT)}${ext(w)}</li>`;
  };

  // ⚠️ THE LABEL SHOWS WHENEVER THERE ARE WAITS, which it did not. `head` was empty when no wait
  //    counted toward a figure, so a recipe whose only wait is optional (coconut-curried-golden-
  //    lentils, beans) printed an hourglass and a bullet with nothing naming what they were.
  // ⚠️ AND THE SUMMED FIGURE ONLY WHEN THERE IS MORE THAN ONE WAIT. With one wait the figure IS
  //    that wait's own label, so printing both reads as two facts where there is one.
  const planAhead = waits.length
    ? row(META_HOURGLASS,
          `<span class="meta-lead">Plan ahead</span>`
          + (waits.length > 1 && (view.waitTotal || {}).label
             ? ` <span class="meta-val">${esc(bindUnits(view.waitTotal.label))}</span>` : "")
          + `<ul class="meta-break">${waits.map(waitLine).join("")}</ul>`, "wait")
    : "";

  // ⚠️ STORAGE IS NOT A WAIT. It reaches no total and no filter, and it says WHERE.
  //    ⚠️ THE PLACE IS NAMED, NOT PREPOSITIONED. 11 of the 30 proposals keep at room temperature
  //       and 3 say "other", so "in the ___" was wrong for 14 of them.
  const keeps = storage.length
    ? row(META_JAR, `<span class="meta-lead">Keeps</span><ul class="meta-break">`
          + storage.map((st) => `<li class="meta-bullet">`
              + (st.applies_to ? `<span class="meta-do">${esc(st.applies_to)}</span>: ` : "")
              + [STORE_PLACE[st.where_kept] ?? "", bindUnits(st.label || "")]
                  .filter(Boolean).map(esc).join(", ") + `</li>`).join("")
          + `</ul>`, "wait")
    : "";

  const base = servingsBase();
  const serves = base
    ? row(META_FIG, `Serves <span class="serves-count meta-val">${formatAmount(base * view.scale)}</span>`)
    : "";

  // ⚠️ TWO COLUMNS ONLY WHEN BOTH OF THEM HAVE SOMETHING IN THEM. Keeps on its own does not earn a
  //    column: it is one short line, and a lone Keeps opposite three times reads as a layout the
  //    page fell into rather than one it chose.
  // ⚠️ AND THE LEFT SIDE IS HALF THE QUESTION, WHICH ASKING ABOUT THE WAITS ALONE MISSED. A recipe
  //    can carry a wait and state no prep, no cook, no total and no serving count, and 27 of the
  //    300 do: beans, hummus, key-lime-pie, chocolate-chip-cookies among them. Those drew the grid
  //    with a 277px EMPTY left half and the dividing rule hanging in it, which is the half-empty
  //    row this split exists to avoid, mirrored. Measured on the rendered page, not reasoned about.
  const leftBody = times + second + serves;
  const twoCol = waits.length > 0 && leftBody.trim() !== "";
  // One column takes everything, waits included, in the order the phone reads them.
  const left = twoCol ? leftBody : times + second + planAhead + keeps + serves;
  const right = twoCol ? planAhead + keeps : "";
  const block = (left + right).trim()
    ? `<div class="time-block${twoCol ? " two-col" : ""}">`
      + `<div class="meta-stack tb-col">${left}</div>`
      + (twoCol ? `<div class="meta-stack tb-col tb-right">${right}</div>` : "")
      + `</div>`
    : "";
  // ⚠️ THE SCALER IS NOT PART OF THE BLOCK AND MUST NOT SHARE ITS FATE. An earlier version of this
  //    returned "" when the block had nothing to say, which took #scaler-host with it: 78 of the
  //    300 recipes state no time and no serving count, and every one of them lost the ½×/1×/2×
  //    control entirely. rerenderScaler null-checks the host, so nothing threw and nothing said so.
  //    An empty block renders as no block at all, and the scaler is drawn either way.
  // The scaler sits BELOW the block now rather than beside it. At the reading width the two columns
  // and a 195px row of fixed controls cannot share a line without the text wrapping, which is what
  // the preview showed.
  return `<div class="above-ing">${block}`
    + `<div class="scaler-col" id="scaler-host">${scaleControl()}</div></div>`;
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

// The empty, uploadable hero Polaroid (dashed frame / "+" / drag-or-click). Used BOTH by dishPhoto's
// image-falsy+editable branch AND by wirePhotoUpload's broken-<img> degrade (Stage B) — one source so
// the two never drift.
function emptyDishPhotoHTML() {
  return `<div class="dish-photo polaroid-hero polaroid-empty" data-upload-zone>
    ${clipDefs()}
    ${clipSvg("back")}
    <div class="edge-contact"></div>
    <span class="polaroid-wrap"><span class="polaroid">
      <span class="photo upload-zone" tabindex="0" role="button" aria-label="Add a photo — drag one here or click to choose">
        <span class="add-photo-mark">+</span><span class="add-label">drag a photo here<br>or click to choose</span>
      </span>
      <span class="strip"></span>
    </span></span>
    ${clipSvg("front")}
    <input class="photo-input" type="file" accept="image/*" tabindex="-1" aria-hidden="true">
  </div>`;
}

// The finished-dish photo (top-right of the masthead) as a Polaroid straddling the recipe card's top
// edge, held by a brass clip. The strip is empty for now (the typed caption is a separate feature).
// No image: an EDITABLE recipe gets an empty clipped Polaroid that IS a photo drop-zone + click-to-pick
// (wired to POST /api/recipes/<id>/image by wirePhotoUpload); a non-editable (seed) recipe returns "" so
// the masthead collapses to a full-width title. A broken URL: an EDITABLE recipe DEGRADES to that empty
// uploadable Polaroid (Stage B, bound in wirePhotoUpload); a non-editable one collapses via the inline
// <img> onerror (adds .no-photo to the stage, removes the Polaroid).
function dishPhoto(r, editable, photos) {
  if (r.image) {
    // Part 2: an EDITABLE owner gets the hover-reveal "Update photo" pill + drop-to-replace, wired to the
    // SAME upload path as the empty zone (wirePhotoUpload). Non-editable (seed / other users) is byte-for-
    // byte the original filled Polaroid — no affordance. The <img> onerror degradation is preserved verbatim.
    const editHook   = editable ? " polaroid-filled" : "";
    const editAttr   = editable ? " data-upload-zone" : "";
    // ⚠️ THE PILL SAYS "Photos" NOW, AND IT NO LONGER OPENS THE FILE PICKER. "Update photo" described
    // neither what it did nor what happened: it added a photo to the album and promoted it, leaving
    // the old one in place, so nothing was ever updated. It opens the album overlay, where adding,
    // choosing the hero, captioning and deleting all live.
    const updatePill = editable ? `<button class="update-photo" type="button" data-album-open aria-label="All photos">Photos</button>` : "";
    const fileInput  = editable ? `<input class="photo-input" type="file" accept="image/*" tabindex="-1" aria-hidden="true">` : "";
    // Stage B: an editable recipe's broken hero <img> degrades to the empty upload zone (bound in
    // wirePhotoUpload) — so NO inline collapse here. A NON-editable broken image still collapses inline.
    const brokenCollapse = editable ? "" :
      ` onerror="this.closest('.recipe-stage').classList.add('no-photo'); this.closest('.dish-photo').remove();"`;
    // SHARED hero caption: if recipes.image is a promoted cook photo, show that photo's caption in the strip
    // (heroCaption reads the is_hero photo from the payload). null -> empty strip, as before (uncaptioned hero,
    // or a hero with no matching cook_photo row). Edited via that photo's 3c ⋮ menu — same field, re-read here.
    const cap = heroCaption(photos);
    const capHTML = cap ? `<span class="cap">${esc(cap)}</span>` : "";
    return `<div class="dish-photo polaroid-hero${editHook}"${editAttr}>
    ${clipDefs()}
    ${clipSvg("back")}
    <div class="edge-contact"></div>
    <figure class="polaroid-wrap"><span class="polaroid">
      <img class="photo" src="/${esc(r.image)}" alt="${esc(r.name)}" loading="lazy"
           data-album-open role="button" tabindex="0"${brokenCollapse}>
      ${updatePill}
      <span class="strip">${capHTML}</span>
    </span></figure>
    ${clipSvg("front")}
    ${fileInput}
  </div>`;
  }
  if (editable) return emptyDishPhotoHTML();
  return "";   // seed recipe with no photo: collapse (seed recipes aren't editable — no dead add link)
}

// The cook-photo ALBUM (Stage 4 build 3a — DISPLAY only). A dedicated "Album" section below the method:
// a grid of mini-Polaroids (a lighter form than the hero — no clip), each with the cook's full date (if
// cook-linked) + optional Kalam caption, the promoted photo flagged with the ★ Hero badge. Photos render
// WHOLE at their native aspect ratio in an order-preserving MASONRY (layoutAlbum); SIX show by default,
// "See all N photos" expands the rest. No per-photo actions (3c). 3b-i adds the owner-only add-tile (below)
// + shows the section (add-zone only) for an empty owner album; a non-owner empty album still renders nothing.
const ALBUM_CAP = 6;   // masonry: ~1–2 ranks shown collapsed, then "See all" (one-clean-row no longer applies)
const ALBUM_CAPTION_MAX = 60;   // client mirror of app.py::COOK_PHOTO_CAPTION_MAX (UI cap matches the server)
function albumStripInner(p) {   // the resting figcaption body (date + caption) — reused by render + caption-edit cancel
  const date = p.cooked_on ? `<span class="date">${esc(formatFullDate(p.cooked_on))}</span>` : "";   // cook-linked only
  const cap = p.caption ? `<span class="cap">${esc(p.caption)}</span>` : "";
  return `${date}${cap}`;
}
function albumPhotoHTML(p, canManage) {
  const badge = p.is_hero ? `<span class="hero-badge">&#9733; Hero</span>` : "";
  // 3c: the owner-only per-photo ⋮ (calm at rest, hover-revealed) + the data-photo-id hook every action targets
  const menu = canManage ? `<button class="pm-btn" data-photo-menu aria-haspopup="true" aria-label="Photo actions">&#8942;</button>` : "";
  return `<figure class="album-photo${p.is_hero ? " is-hero" : ""}" data-photo-id="${p.id}">${badge}${menu}
    <img class="ph" src="/${esc(p.path)}" alt="" loading="lazy"
      onerror="this.closest('.album-photo').remove();">
    <figcaption class="strip">${albumStripInner(p)}</figcaption></figure>`;
}
// The standalone "add to album" tile (3b-i): the REAL hero-uploader .upload-zone (dashed frame / "+" /
// drag-or-click, MULTI-file) sized into an album grid cell, plus the (i) cook-logger nudge. Owner-only;
// standalone = attaches with NO cook (cook_log_id NULL -> no date). Wired by wireAlbumUpload after paint.
function albumAddTileHTML() {
  return `<figure class="album-photo album-add" data-album-add>
    <span class="polaroid-empty">
      <span class="photo upload-zone" tabindex="0" role="button" aria-label="Add photos to the album">
        <span class="add-photo-mark">+</span><span class="add-label">drag photos here<br>or click to choose</span>
      </span>
    </span>
    <input class="album-photo-input" type="file" accept="image/*" multiple tabindex="-1" aria-hidden="true">
    <figcaption class="strip"><span class="add-cap">add to album</span><span class="add-hint"><span class="i" tabindex="0" role="img" aria-label="About album photos">i</span><span class="tip">A photo added here <b>won&rsquo;t have a date</b>. To track <b>when &amp; how</b> you cook this over time, <b>log a cook</b> and add photos to it.</span></span></figcaption>
  </figure>`;
}
function albumSectionHTML(data) {
  const photos = (data && data.photos) || [];
  // OWNERSHIP, not tier. The comment always said "owner-only"; the value used to be is_editable
  // (source-derived), so a non-owner was shown an add-zone that add_cook_photo then 403'd on its
  // rec.owner check. is_mine is the flag that matches the server's gate.
  const canAdd = !!(data && data.is_mine);   // owner-only add-zone — same gate as the hero uploader (dishPhoto)
  const addTile = canAdd ? albumAddTileHTML() : "";
  if (!photos.length) {
    // 3b-i change to 3a's empty state: an OWNER gets the section with just the add-zone (entry point for the
    // first photo); a NON-owner still sees nothing (calm empty state — they can't add).
    return canAdd
      ? `<section class="album-section" id="album-section">
    <div class="col-head"><h2 class="col-title">Album</h2></div>
    <div class="album-grid masonry">${addTile}</div></section>`
      : "";
  }
  const many = photos.length > ALBUM_CAP;
  const more = many
    ? `<div class="album-more"><button class="see-more" data-album-toggle>See all ${photos.length} photos <span class="chev">&#8595;</span></button></div>`
    : "";
  // 3d-iii: the owner-only "Reorder" entry — needs ≥2 photos to be meaningful; calm at rest, in the header.
  const reorderEntry = (canAdd && photos.length >= 2)
    ? `<button class="album-reorder-enter" data-album-reorder aria-label="Reorder photos">&#8645; Reorder</button>` : "";
  return `<section class="album-section${many ? " collapsed" : ""}" id="album-section">
    <div class="col-head"><h2 class="col-title">Album</h2>${reorderEntry}</div>
    <div class="album-grid masonry">${photos.map((p) => albumPhotoHTML(p, canAdd)).join("")}${addTile}</div>
    ${more}</section>`;
}

// Aspect-matched MASONRY layout for the album. Photos render WHOLE at native ratio (no crop) with ragged
// heights. Mechanism: order-preserving ROUND-ROBIN column distribution — item i -> column (i mod N),
// stacked within each column. This reads LEFT-TO-RIGHT in source (cooked_on) order (newest top-left, the
// next-newest to its RIGHT), unlike CSS column-count which flows top-to-bottom per column and would
// scramble newest-first. No gap backfilling (no `dense`) -> order is never reshuffled to fill holes. The
// column count N derives from width; columns stack naturally (+ reflow as images load) so no per-image
// height measuring is needed. Collapsed shows the first ALBUM_CAP photos; the add-tile always trails last.
const ALBUM_COLW = 168, ALBUM_GAP = 18, ALBUM_MAXCOL = 4;
function layoutAlbum(grid) {
  if (!grid) return;
  if (!grid._items) grid._items = Array.from(grid.children);   // cache the flat items (photos in order + add-tile)
  const sec = grid.closest(".album-section");
  const collapsed = !!(sec && sec.classList.contains("collapsed"));
  const photos = grid._items.filter((el) => !el.classList.contains("album-add"));
  const addTile = grid._items.find((el) => el.classList.contains("album-add")) || null;
  const shown = collapsed ? photos.slice(0, ALBUM_CAP) : photos;
  const seq = addTile ? shown.concat(addTile) : shown;   // the add-tile trails the shown photos (end of the masonry)
  const W = grid.clientWidth || 760;
  const N = Math.max(1, Math.min(ALBUM_MAXCOL, Math.floor((W + ALBUM_GAP) / (ALBUM_COLW + ALBUM_GAP))));
  const cols = [];
  for (let i = 0; i < N; i++) { const c = document.createElement("div"); c.className = "album-col"; cols.push(c); }
  seq.forEach((el, i) => cols[i % N].appendChild(el));   // round-robin: i -> col (i mod N), source order kept -> row-major reading
  grid.replaceChildren(...cols);
}
let _albumResizeBound = false;
function bindAlbumResize() {
  if (_albumResizeBound) return;                          // one listener for the app's lifetime (paint re-finds the grid)
  _albumResizeBound = true;
  let raf = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => layoutAlbum(app.querySelector(".album-grid.masonry")));
  });
}

// Stage 4 (3c): per-photo album actions. The ⋮ opens a small menu (Make hero / Edit caption / Delete);
// each action targets the figure's data-photo-id and refreshes via renderRecipe(view.slug) — the seam the
// diagnostic confirmed covers all three (promote -> hero badge + hero Polaroid; caption -> new text; delete
// -> photo gone, and if it was the hero, the empty upload frame returns). Endpoints shipped in build 2b/2c.
function albumPhotoById(id) {
  return ((view && view.data && view.data.photos) || []).find((p) => String(p.id) === String(id));
}
function capEditHTML(cur) {
  const n = cur.length;
  const cls = n >= ALBUM_CAPTION_MAX ? " at" : n >= 50 ? " near" : "";
  return `<span class="cap-edit"><textarea class="cap-input" data-cap-input rows="2" maxlength="${ALBUM_CAPTION_MAX}"
      placeholder="add a note about this cook…">${esc(cur)}</textarea>
    <span class="cap-foot"><span class="cap-count${cls}" data-cap-count>${n} / ${ALBUM_CAPTION_MAX}</span>
      <span class="cap-actions"><button class="btn sm" data-cap-save>Save</button>
        <button class="btn ghost sm" data-cap-cancel>Cancel</button></span></span></span>`;
}
function delConfirmHTML(isHero) {
  const heroLine = isHero
    ? `<span class="dc-hero">Deleting clears the hero.</span>`
    : "";
  return `<div class="del-confirm"><span class="dc-q">Delete this photo?</span>${heroLine}
    <span class="dc-actions"><button class="btn sm danger" data-del-confirm>Delete</button>
      <button class="btn sm ghost-light" data-del-cancel>Cancel</button></span></div>`;
}
function closePhotoMenu() { const m = app.querySelector(".photo-menu"); if (m) m.remove(); }
function openPhotoMenu(btn) {
  closePhotoMenu();                                        // single-open: any other menu closes first
  const fig = btn.closest(".album-photo");
  const heroItem = fig.classList.contains("is-hero")
    ? `<button disabled><span class="mi">&#9733;</span> Already the hero</button>`
    : `<button data-pm-hero><span class="mi">&#9733;</span> Make hero</button>`;
  fig.insertAdjacentHTML("beforeend", `<div class="photo-menu">${heroItem}
    <button data-pm-caption><span class="mi">&#9998;</span> Edit caption</button>
    <div class="sep"></div>
    <button class="danger" data-pm-delete><span class="mi">&#128465;</span> Delete</button></div>`);
  const menu = fig.querySelector(".photo-menu");           // EDGE: flip above the ⋮ if it'd overflow the viewport bottom
  if (menu.getBoundingClientRect().bottom > window.innerHeight - 8) menu.classList.add("up");
}
function openCaptionEdit(fig) {
  const p = albumPhotoById(fig.dataset.photoId);
  const dateHTML = p && p.cooked_on ? `<span class="date">${esc(formatFullDate(p.cooked_on))}</span>` : "";
  const strip = fig.querySelector(".strip");
  strip.innerHTML = `${dateHTML}${capEditHTML(p && p.caption ? p.caption : "")}`;
  const ta = strip.querySelector("[data-cap-input]");
  if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
}
// ⚠️ These three end in afterPhotoChange, NOT renderRecipe. The overlay and the lightbox live
// outside #app, so a bare repaint leaves them on screen showing the state before the action.
async function promotePhoto(id, rid) { const { ok } = await sendJSON("POST", `/api/photos/${id}/promote`, {}); if (ok) await afterPhotoChange(rid); }
async function deletePhoto(id, rid)  { const { ok } = await sendJSON("DELETE", `/api/photos/${id}`, null);     if (ok) await afterPhotoChange(rid); }
async function saveCaption(fig, rid) {
  const ta = fig.querySelector("[data-cap-input]");
  const { ok } = await sendJSON("PATCH", `/api/photos/${fig.dataset.photoId}`, { caption: ta ? ta.value.trim() : "" });
  if (ok) await afterPhotoChange(rid);                     // blank clears it (server allows blank)
}
// ── The photo album overlay + lightbox (items 6 + 7) ─────────────────────────────────────────
// ⚠️ THE OVERLAY RENDERS albumPhotoHTML VERBATIM. It is the same component the inline Album section
// uses, so the ★ Hero badge, the per-photo ⋮ menu and its three actions are shared rather than
// reimplemented. handleAlbumPhotoAction is delegated on document, so those menus already work inside
// the overlay with no extra wiring. The only thing the overlay adds is the container.
const albumOverlay = document.querySelector(".album-overlay");
const lightbox = document.querySelector(".lightbox");
let albumTrigger = null;    // what opened the overlay (focus returns there)
let lbIndex = -1;           // the photo the lightbox is showing, as an index into view.data.photos

const albumPhotos = () => (view && view.data && view.data.photos) || [];

function renderAlbumOverlay() {
  if (!albumOverlay || albumOverlay.hidden) return;
  const grid = albumOverlay.querySelector("[data-ao-grid]");
  const hint = albumOverlay.querySelector("[data-ao-hint]");
  const photos = albumPhotos();
  const canManage = !!(view && view.data && view.data.is_mine);
  grid.innerHTML = photos.length
    ? photos.map((ph) => albumPhotoHTML(ph, canManage)).join("")
    : `<p class="ao-empty">No photos yet. Add one to get started.</p>`;
  hint.textContent = photos.length
    ? "Click a photo to see it large. The ⋮ menu sets the hero, edits a caption or deletes."
    : "";
  albumOverlay.querySelector("[data-ao-add]").hidden = !canManage;
}

function openAlbumOverlay(trigger) {
  if (!albumOverlay) return;
  albumTrigger = trigger || null;
  albumOverlay.querySelector("[data-ao-status]").textContent = "";
  albumOverlay.hidden = false;
  scrim.hidden = false;
  renderAlbumOverlay();
  requestAnimationFrame(() => { scrim.classList.add("open"); albumOverlay.classList.add("open"); });
  albumOverlay.querySelector("[data-album-close]").focus();
}

function closeAlbumOverlay() {
  if (!albumOverlay || albumOverlay.hidden) return;
  closePhotoMenu();
  scrim.classList.remove("open");
  albumOverlay.classList.remove("open");
  setTimeout(() => { scrim.hidden = true; albumOverlay.hidden = true; }, 260);
  if (albumTrigger && document.contains(albumTrigger)) albumTrigger.focus();
}

// ⚠️ EVERY PHOTO ACTION REPAINTS THE PAGE, AND THE OVERLAY LIVES OUTSIDE #app. promotePhoto,
// deletePhoto and saveCaption all end in renderRecipe, which rebuilds #app and leaves the overlay
// standing with stale contents. This re-renders it from the refreshed view.data, and keeps the
// lightbox honest too: a deleted photo must not stay on screen.
async function afterPhotoChange(rid) {
  await renderRecipe(rid);
  renderAlbumOverlay();
  if (lightbox && !lightbox.hidden) {
    const photos = albumPhotos();
    if (!photos.length) closeLightbox();
    else showLightbox(Math.min(lbIndex, photos.length - 1));
  }
}

// ---- the lightbox ----------------------------------------------------------------------------
function showLightbox(index) {
  const photos = albumPhotos();
  if (!photos.length) return;
  // Wrap at both ends: with two photos, "next" that dead-ends on the second is a worse answer than
  // coming back round, and there is no scroll position to lose.
  lbIndex = (index + photos.length) % photos.length;
  const ph = photos[lbIndex];
  lightbox.querySelector("[data-lb-img]").src = `/${ph.path}`;
  const where = ph.cooked_on ? formatFullDate(ph.cooked_on) : "";
  const cap = ph.caption || "";
  lightbox.querySelector("[data-lb-where]").textContent = [where, cap].filter(Boolean).join(" · ");
  lightbox.querySelector("[data-lb-count]").textContent =
    photos.length > 1 ? `${lbIndex + 1} of ${photos.length}` : "";
  const heroBtn = lightbox.querySelector("[data-lb-hero]");
  const canManage = !!(view && view.data && view.data.is_mine);
  heroBtn.hidden = !canManage;
  heroBtn.disabled = !!ph.is_hero;
  heroBtn.innerHTML = ph.is_hero ? "&#9733; Already the hero" : "&#9733; Set as hero";
  heroBtn.dataset.photoId = ph.id;
  // Paging is pointless with one photo, and two dead arrows read as broken rather than absent.
  lightbox.querySelectorAll(".lb-nav").forEach((b) => { b.hidden = photos.length < 2; });
}

function openLightbox(photoId) {
  if (!lightbox) return;
  const idx = albumPhotos().findIndex((p) => String(p.id) === String(photoId));
  if (idx < 0) return;
  lightbox.hidden = false;
  showLightbox(idx);
  requestAnimationFrame(() => lightbox.classList.add("open"));
  lightbox.querySelector("[data-lb-close]").focus();
}

function closeLightbox() {
  if (!lightbox || lightbox.hidden) return;
  lightbox.classList.remove("open");
  setTimeout(() => { lightbox.hidden = true; lightbox.querySelector("[data-lb-img]").src = ""; }, 200);
  lbIndex = -1;
  // Return to whatever is underneath: the overlay if it is open, else the trigger in the page.
  if (albumOverlay && !albumOverlay.hidden) albumOverlay.querySelector("[data-album-close]").focus();
}

// ---- adding a photo from the overlay -----------------------------------------------------------
// ⚠️ POSTS TO /photos, NOT /image. /image ALWAYS promotes, which would silently steal the hero every
// time you added a picture. /photos promotes only when the recipe has no hero yet, which is right for
// a first photo and right to leave alone for a twelfth.
async function albumOverlayUpload(files) {
  const rid = view && view.slug;
  const list = Array.from(files || []).filter(Boolean);
  const status = albumOverlay.querySelector("[data-ao-status]");
  if (!rid || !list.length) { status.textContent = ""; return; }
  status.textContent = `Adding ${list.length > 1 ? list.length + " photos" : "photo"}…`;
  const results = await Promise.allSettled(list.map((file) => {
    const fd = new FormData();
    fd.append("image", file);              // no cook_log_id -> a standalone album photo (no date)
    return fetch(`/api/recipes/${encodeURIComponent(rid)}/photos`,
                 { method: "POST", credentials: "same-origin", body: fd }).then((r) => r.status);
  }));
  if (results.some((r) => r.status === "fulfilled" && r.value === 401)) { showAuth(); return; }
  const ok = results.filter((r) => r.status === "fulfilled" && r.value >= 200 && r.value < 300).length;
  const bad = results.length - ok;
  if (ok) await afterPhotoChange(rid);
  status.textContent = bad
    ? (ok ? `Added ${ok}. ${bad} couldn’t be added.` : "Couldn’t add that. JPEG, PNG, WebP or HEIC.")
    : "";
}

// Delegated handler — returns true if it owned the click. Wired into the main document click listener.
function handleAlbumPhotoAction(e) {
  const rid = view ? view.slug : null;
  const pm = e.target.closest("[data-photo-menu]");
  if (pm) { const f = pm.closest(".album-photo");
    f.querySelector(".photo-menu") ? closePhotoMenu() : openPhotoMenu(pm); return true; }
  const fig = e.target.closest(".album-photo");
  if (!fig) return false;
  if (e.target.closest("[data-pm-hero]"))     { closePhotoMenu(); promotePhoto(fig.dataset.photoId, rid); return true; }
  if (e.target.closest("[data-pm-caption]"))  { closePhotoMenu(); openCaptionEdit(fig); return true; }
  if (e.target.closest("[data-pm-delete]"))   { closePhotoMenu();
    fig.insertAdjacentHTML("beforeend", delConfirmHTML(fig.classList.contains("is-hero"))); return true; }
  if (e.target.closest("[data-cap-save]"))    { saveCaption(fig, rid); return true; }
  if (e.target.closest("[data-cap-cancel]"))  { const p = albumPhotoById(fig.dataset.photoId);
    if (p) fig.querySelector(".strip").innerHTML = albumStripInner(p); return true; }   // revert, no network
  if (e.target.closest("[data-del-confirm]")) { deletePhoto(fig.dataset.photoId, rid); return true; }
  if (e.target.closest("[data-del-cancel]"))  { const dc = e.target.closest(".del-confirm"); if (dc) dc.remove(); return true; }
  // ⚠️ A TAP VIEWS, IT DOES NOT SET THE HERO. Last, so every menu target above wins over it, and
  // scoped to the image itself so a click on the caption strip or a blank part of the figure does
  // nothing. One rule, both surfaces: the overlay grid and the inline Album tiles (item 7).
  if (e.target.closest("img.ph") && !fig.querySelector(".cap-edit") && !fig.querySelector(".del-confirm")) {
    openLightbox(fig.dataset.photoId);
    return true;
  }
  return false;
}

/* ---------- A stage 1: the inline editor's per-row ⋯ menu ----------
   Not a new dropdown — the album's .photo-menu component with a second class on its selectors
   (styles.css). Same box, same items, same .danger / [disabled] / .sep, same viewport-edge .up flip.
   What is NOT shared is the OPEN STATE, and that is deliberate rather than incidental. The two
   families need separate close() pairs because each one's "is this click exempt?" test names its own
   trigger and its own container: the photo pre-branch exempts .photo-menu / [data-photo-menu], the row
   pre-branch exempts .row-menu / [data-row-menu]. Give the row menu the .photo-menu CLASS and the
   existing photo pre-branch matches it as a stranger and deletes it on the very click that opens it —
   click ⋯, closePhotoMenu() removes the menu, the toggle then re-opens it, and the menu can never be
   dismissed by its own trigger. Two classes, two closers, two pre-branches; mutual exclusion comes
   from openRowMenu() calling BOTH closers, and from the row pre-branch firing on any photo-⋮ click. */
// ⚠️ ONE SELECTOR FOR THE THREE ROW TYPES THAT CARRY A ⋯ MENU, named once. It was spelled out at
// three call sites, and a note row added to two of them is a menu that opens and cannot be closed.
const ROW_MENU_ROW = ".erow, li.step-edit, .ie-noterow";

function closeRowMenu() {
  const m = app.querySelector(".row-menu");
  if (!m) return;
  const row = m.closest(ROW_MENU_ROW);
  if (row) {
    row.classList.remove("menu-open");
    const trig = row.querySelector("[data-row-menu]");
    if (trig) trig.setAttribute("aria-expanded", "false");
  }
  m.remove();
}
// A stage 2: the real items. Text-only, no .mi glyph: the album's items all carry one, but no real
// icon exists for the inserts and inventing one is exactly what the fidelity rule forbids — a
// half-populated icon column is worse than none.
// The heading state is read from the DRAFT rather than passed in, so the label can never disagree with
// the row it belongs to (the menu is rendered at open time, after any re-render).
// The inserts come FIRST, separated from the row's own actions by the same .sep the album menu uses
// before its destructive item: the top group acts on the LIST (add a neighbour), the bottom group acts
// on THIS row (retype it, delete it).
//
// EVERY ITEM ACTS RELATIVE TO ITS OWN ROW AND INSERTS BELOW IT, so no label carries a direction: the
// menu hangs off one row, which makes "below" the only sensible reading, and "Add step" reads as an
// action where "Add below" reads as a coordinate. This replaced an Add above / Add below PAIR.
// ⚠️ THE CONSEQUENCE IS REAL AND ACCEPTED: there is no menu path to insert above the FIRST row. For
// any other row you use the menu of the row above it; for row 0 you add below and drag it up. That is
// only acceptable BECAUSE drag-reorder shipped (C0-C3) — before it, dropping the "above" item would
// have made the top of the list unreachable. Do not re-add an "above" item to work around this.
// Labels no longer have to be short. The row menu widens to fit them (see .rtools .row-menu in
// styles.css); the album's .photo-menu keeps its 140px.
function rowMenuItemsHTML(kind, i) {
  if (kind === "note") return noteMenuItemsHTML();
  const inserts = `<button type="button" data-rm-act="add-row">${kind === "step" ? "Add step" : "Add ingredient"}</button>
    <button type="button" data-rm-act="add-heading">Add heading</button>
    <div class="sep"></div>`;
  if (kind === "step") {
    // ⚠️ THE STEP MENU OFFERED NO CONVERSION AT ALL UNTIL NOW, and the ingredient menu has had one
    // since A stage 2. That gap stopped mattering the moment 67 steps became headings: the only way
    // to undo a wrong conversion was Delete plus Add step, which mints a NEW row id and takes the
    // wait link, the annotation anchor and any margin mark with it. The toggle keeps the id both
    // ways, which is the whole reason it is a toggle and not a delete-and-insert.
    const row = view.draft.steps[i];
    const isHeading = !!(row && row.is_heading);
    const level = `<button type="button" data-rm-act="level">${stepLevel(row) === 2 ? "Make section heading" : "Make subheading"}</button>`;
    return `${inserts}<button type="button" data-rm-act="toggle">${isHeading ? "Convert to step" : "Convert to heading"}</button>
      ${isHeading ? level : ""}
      <div class="sep"></div><button type="button" class="danger" data-rm-act="delete">Delete</button>`;
  }
  const row = view.draft.ingredients[i];
  const toHeading = !(row && row.is_heading);
  return `${inserts}<button type="button" data-rm-act="toggle">${toHeading ? "Convert to heading" : "Convert to ingredient"}</button>`;
}

// A NOTE's items. Same component, same .sep, same .danger delete, and `i` is the note's ID (see
// noteRowToolsHTML).
// ⚠️ THE STEP-ONLY ITEMS ARE ABSENT BECAUSE THEY NAME THINGS A NOTE IS NOT. Convert to heading and
// Make section / subheading are questions about the METHOD's shape; a note's type and its step link
// are asked in the note's own panel, where they already are, so they are not repeated here.
// ⚠️ AND THIS ONE HAS BOTH DIRECTIONS, WHERE THE STEP MENU HAS ONLY "below". The step menu dropped
// its Add above on the grounds that drag-reorder makes the top of the list reachable. That reason
// does not carry: a note may only be dragged among the notes of its OWN group (draftReorder), so
// the first note of a group has nowhere to be dragged from and "above" is the only way to reach the
// top of it. The step menu is unchanged either way.
// ⚠️ THERE ARE NO Move up / Move down ITEMS TO MIRROR. The step menu has none, so neither has this.
function noteMenuItemsHTML() {
  return `<button type="button" data-rm-act="add-above">Add note above</button>
    <button type="button" data-rm-act="add-below">Add note below</button>
    <div class="sep"></div><button type="button" class="danger" data-rm-act="delete">Delete</button>`;
}
function openRowMenu(trigger, i, kind) {
  closePhotoMenu();                                        // single-open ACROSS both families
  closeRowMenu();
  const row = trigger.closest(ROW_MENU_ROW);
  const cluster = trigger.closest(".rtools");
  row.classList.add("menu-open");                          // the cluster rests at opacity:0 — see styles.css
  trigger.setAttribute("aria-expanded", "true");
  cluster.insertAdjacentHTML("beforeend",
    `<div class="row-menu" data-i="${i}" data-row-kind="${kind}">${rowMenuItemsHTML(kind, i)}</div>`);
  const menu = cluster.querySelector(".row-menu");         // EDGE: flip above the ⋯ if it'd overflow the viewport bottom
  if (menu.getBoundingClientRect().bottom > window.innerHeight - 8) menu.classList.add("up");
}
// Delegated handler — returns true if it owned the click. Scope-guarded on the ROW first, mirroring
// handleAlbumPhotoAction's `.album-photo` guard, so a click anywhere else costs one closest() call.
// The row index and kind are resolved ONCE here — from the trigger when opening, from the menu's own
// data-i/data-row-kind once open — so the item branches below never re-probe the DOM for them.
// A stage 2: the items dispatch HERE, not through new handleInlineEdit branches. They call the SAME
// functions the removed inline controls called (toggleIngredientHeading / removeStep) — this stage
// changes how an action is reached, never what it does. Each closes its menu first, mirroring
// handleAlbumPhotoAction's items; the re-render that follows would take the menu with it anyway, but
// relying on that would leave the menu orphaned the moment an action stops re-rendering.
function handleRowMenuAction(e) {
  const row = e.target.closest(ROW_MENU_ROW);
  if (!row) return false;
  const host = e.target.closest("[data-row-menu], .row-menu");
  if (!host) return false;
  const i = Number(host.dataset.i);
  const kind = host.dataset.rowMenu || host.dataset.rowKind;
  const trigger = e.target.closest("[data-row-menu]");
  if (trigger) {
    // ⚠️ THE CLICK CAN HAVE REPAINTED THE PAGE UNDER ITSELF. handleNoteAction runs first in the
    //    dispatcher and a click anywhere commits an open note, which rewrites the whole notes host,
    //    so the trigger carried by the event may be a node that is no longer in the document. A
    //    menu inserted beside a detached node is simply never seen. Re-find the live one by the two
    //    attributes that name it.
    const live = trigger.isConnected ? trigger
      : app.querySelector(`[data-row-menu="${kind}"][data-i="${i}"]`);
    if (!live) return true;
    const liveRow = live.closest(ROW_MENU_ROW);
    if (liveRow && liveRow.querySelector(".row-menu")) closeRowMenu();
    else openRowMenu(live, i, kind);
    return true;
  }
  const item = e.target.closest("[data-rm-act]");
  if (!item) return false;
  const act = item.dataset.rmAct;
  closeRowMenu();
  // ⚠️ A NOTE IS REACHED BY ID, SO IT BRANCHES BEFORE THE INDEX ARITHMETIC BELOW. `i` is the note's
  //    id here, and draft.steps[i] would be a different row entirely (or undefined for the
  //    negative id a note added this session carries).
  if (kind === "note") {
    if (act === "delete") { deleteNote(i); return true; }
    if (act === "add-above" || act === "add-below") {
      addNoteBeside(i, act === "add-above" ? "above" : "below");
      return true;
    }
    return true;
  }
  // B: both lists share the index arithmetic (insertIndexFor) and differ only in which array is
  // measured and which adder runs. A null index means the row this menu claimed to belong to is not a
  // real row any more — do nothing rather than guess a position; see row-insert.js.
  // BOTH inserts land in the same place — directly below this row — and differ only in the SHAPE of the
  // row that arrives, so they share one branch rather than owning two copies of the arithmetic.
  // insertIndexFor still implements both cases and its tests still cover both; only this CALLER
  // narrowed to "below" when the Add above item was removed. The "above" case stays because it is the
  // honest general statement of the rule, and re-adding a caller must not mean re-deriving it.
  if (act === "add-row" || act === "add-heading") {
    const arr = kind === "step" ? view.draft.steps : view.draft.ingredients;
    const at = insertIndexFor("below", i, arr.length);
    if (at == null) return true;
    const isHeading = act === "add-heading";
    if (kind === "step") addStep(at, isHeading); else addIngredient(isHeading, at);
    return true;
  }
  if (kind === "ing"  && act === "toggle") { toggleIngredientHeading(i); return true; }
  if (kind === "step" && act === "toggle") { toggleStepHeading(i); return true; }
  if (kind === "step" && act === "level")  { toggleStepHeadingLevel(i); return true; }
  if (kind === "step" && act === "delete") { removeStep(i); return true; }
  return true;                                             // an item of this menu, but not one we know
}

// Stage 4 (3d-iii): drag-to-reorder — a dedicated Reorder MODE. The scatter masonry stays for DISPLAY;
// "Reorder" re-lays the photos into a clean LINEAR draggable sequence (albumReorder holds the working
// order), you drag to rearrange (native HTML5 DnD — the ⋮⋮-gripped photo's origin dims to a ghost, an ochre
// bar tracks the drop point), and "Done" commits the FULL order ONCE via the 3d-ii endpoint (PATCH
// .../photos/order) -> renderRecipe -> back to the scatter masonry in the new order. "Cancel" discards
// (re-fetch). Nothing persists until Done; the reorder is client-side + a single write.
let albumReorder = null;   // { order:[ids], original:[ids] } while reordering, else null
let albumDragId = null;    // the photo id being dragged (native DnD)

function albumReorderPhotoHTML(p) {
  const badge = p.is_hero ? `<span class="hero-badge">&#9733; Hero</span>` : "";
  return `<figure class="album-photo${p.is_hero ? " is-hero" : ""}" data-photo-id="${p.id}" draggable="true">
    ${badge}<span class="grip" aria-hidden="true">&#8942;&#8942;</span>
    <img class="ph" src="/${esc(p.path)}" alt="">
    <figcaption class="strip">${albumStripInner(p)}</figcaption></figure>`;
}
function reorderStripHTML(order) {
  const byId = Object.fromEntries((view.data.photos || []).map((p) => [p.id, p]));
  return order.map((id) => albumReorderPhotoHTML(byId[id])).join("");
}
function albumReorderSectionHTML(order) {   // replaces #album-section while reordering (auto-expanded: ALL photos)
  return `<section class="album-section reordering" id="album-section">
    <div class="album-head"><h2 class="col-title">Album</h2>
      <span class="reorder-actions"><span class="reorder-err" data-reorder-err hidden></span>
        <button class="btn sm" data-album-reorder-done>Done</button>
        <button class="btn ghost sm" data-album-reorder-cancel>Cancel</button></span></div>
    <div class="reorder-mode">
      <p class="reorder-hint"><span aria-hidden="true">&#8645;</span> Drag photos to rearrange — the album keeps its scatter look; this view is just for ordering.</p>
      <div class="reorder-strip" id="reorder-strip">${reorderStripHTML(order)}</div>
    </div></section>`;
}
function enterAlbumReorder() {
  if (!view || !view.data || albumReorder) return;
  const order = (view.data.photos || []).map((p) => p.id);
  if (order.length < 2) return;                            // need ≥2 to reorder (matches the entry gate)
  albumReorder = { order, original: [...order] };
  const sec = app.querySelector("#album-section");         // auto-expand happens for free: the strip lists ALL photos
  if (sec) sec.outerHTML = albumReorderSectionHTML(order);
}
function repaintReorderStrip() {
  const strip = app.querySelector("#reorder-strip");
  if (strip && albumReorder) strip.innerHTML = reorderStripHTML(albumReorder.order);
}
async function commitAlbumReorder() {
  if (!albumReorder || !view) return;
  const rid = view.slug;
  const { ok } = await sendJSON("PATCH", `/api/recipes/${encodeURIComponent(rid)}/photos/order`, { order: albumReorder.order });
  if (ok) { albumReorder = null; renderRecipe(rid); return; }
  const err = app.querySelector("[data-reorder-err]");     // keep the mode + the arrangement; allow retry
  if (err) { err.textContent = "Couldn't save the order — try again."; err.hidden = false; }
}
function cancelAlbumReorder() {
  if (!view) { albumReorder = null; return; }
  const rid = view.slug;
  albumReorder = null;
  renderRecipe(rid);                                       // discard: re-fetch the server order -> scatter unchanged
}
// The drag itself (native HTML5 DnD, scoped to #reorder-strip — nothing persists until Done)
function reorderDragStart(e) {
  const fig = e.target.closest("#reorder-strip .album-photo");
  if (!fig || !albumReorder) return;
  albumDragId = Number(fig.dataset.photoId);
  try { e.dataTransfer.setData("text/plain", String(albumDragId)); e.dataTransfer.effectAllowed = "move"; } catch (_) {}
  requestAnimationFrame(() => fig.classList.add("ghost-origin"));   // after the drag-image snapshot -> dim the origin
}
function reorderDragOver(e) {
  const strip = e.target.closest("#reorder-strip");
  if (!strip || albumDragId == null) return;
  e.preventDefault();
  let bar = strip.querySelector(".drop-bar");
  if (!bar) { bar = document.createElement("div"); bar.className = "drop-bar"; }
  const target = [...strip.querySelectorAll(".album-photo")].find((f) => {
    if (Number(f.dataset.photoId) === albumDragId) return false;    // never target the dragged photo
    const r = f.getBoundingClientRect();
    return e.clientX < r.left + r.width / 2;
  });
  if (target) strip.insertBefore(bar, target); else strip.appendChild(bar);
}
function reorderDrop(e) {
  const strip = e.target.closest("#reorder-strip");
  if (!strip || albumDragId == null || !albumReorder) return;
  e.preventDefault();
  const bar = strip.querySelector(".drop-bar");
  let n = bar ? bar.nextElementSibling : null;
  while (n && !n.classList.contains("album-photo")) n = n.nextElementSibling;
  const beforeId = n ? Number(n.dataset.photoId) : null;   // null -> dropped at the end
  albumReorder.order = reorderBefore(albumReorder.order, albumDragId, beforeId);
  albumDragId = null;
  repaintReorderStrip();
}
function reorderDragEnd() {
  albumDragId = null;
  const g = app.querySelector("#reorder-strip .ghost-origin"); if (g) g.classList.remove("ghost-origin");
  const b = app.querySelector("#reorder-strip .drop-bar"); if (b) b.remove();
}

// The owner Edit/Delete row, and the inline two-step delete confirmation it swaps to. The
// confirmation names the recipe and needs a deliberate second click (replaces a single confirm()).
// ⚠️ COPY IS DELIBERATELY NOT OWNER-GATED. Edit and Delete are owner-only (mirroring the PUT/DELETE
// routes, which now check owner as well as tier), but copy_recipe is owner-agnostic BY DESIGN — it is
// the cross-owner "take her recipe" mechanism (docs/product-vision.md's box model: copying someone
// else's recipe duplicates it into YOUR box). Gating this whole block on is_mine would have removed
// the only UI path to that, which is why the split is per-button rather than around the block.
function ownerActionsHTML(r, isMine) {
  const mine = isMine
    ? `<button class="btn ghost sm" data-inline-edit-enter>✎ Edit</button>` : "";
  const del = isMine
    ? `<button class="btn danger-soft sm" data-delete>Delete recipe</button>` : "";
  return `${mine}
          <button class="btn ghost sm" data-copy>Copy</button>
          <button class="btn ghost sm copy-test" data-copy-test>Copy as test</button>
          ${del}`;
}
function deleteConfirmHTML(r) {
  return `<span class="delete-confirm">
    <span class="dc-msg">Delete <strong>${esc(r.name)}</strong>? This can't be undone.</span>
    <button class="btn ghost sm danger" data-delete-confirm>Delete</button>
    <button class="btn ghost sm" data-delete-cancel>Cancel</button>
  </span>`;
}

async function renderRecipe(rid) {
  clearCookChip();   // 3b-iii: any pending "add photos?" offer is stale once we refetch/repaint
  albumReorder = null;   // 3d-iii: leaving reorder mode on any repaint (defensive; commit/cancel already clear it)
  const data = await api("/api/recipes/" + encodeURIComponent(rid));
  view = { slug: rid, data, scale: 1,
           waits: data.waits || [], storage: data.storage || [], waitTotal: data.wait_total || null,
           undoneCook: null, editMode: false, draft: null, dirty: false };
  app.className = "page recipe-view";
  setCookCount(app, data.stats.cook_count);   // reserved R2 wear signal on the recipe root

  paintRecipe();
  // U5: a just-imported recipe opens straight in the editor. Set AFTER paintRecipe (enterEditMode
  // repaints and mounts the step editors itself), and cleared first so a later visit to the same
  // recipe — back button, a link — opens in reading mode like anything else.
  if (importOpening && importOpening === rid) {
    importOpening = null;
    view.importUnconfirmed = true;    // drives the save-bar note below; client-only, see promptImport
    enterEditMode();
  }
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
  const data = view.data;                        // fetched payload (tier: is_editable/is_seed/… — ownership: is_mine)
  const src = editing ? view.draft : view.data;  // where displayed field VALUES come from
  const r = src.recipe;
  // The hero uploader is OWNER-gated server-side (upload_recipe_image checks rec.owner), so it keys on
  // is_mine, not the tier flag. The actions block still renders on the TIER (a seed recipe offers
  // nothing, as before); which BUTTONS it contains is the ownership question — see ownerActionsHTML.
  const photoSlot = dishPhoto(r, data.is_mine, data.photos);   // data.photos carries the is_hero caption (SHARED)
  const owner = (data.is_editable && !editing)
    ? `<div class="owner-actions">${ownerActionsHTML(data.recipe, data.is_mine)}</div>` : "";

  // Reading-view prose, trimmed for the pre-wrap blocks. Edit mode is untouched: its textareas
  // round-trip the stored value byte-for-byte, so saving cannot rewrite what was never changed.
  const dek = proseText(r.descr);

  const mastheadInner = editing
    ? mastheadEditHTML(r)
    : `${photoSlot ? `<div class="photo-reserve" aria-hidden="true"></div>` : ""}
        ${bylineHTML(r)}
        <h1 class="recipe-title">${esc(r.name)}${data.is_test ? ` <span class="test-badge">Test</span>` : ""}</h1>
        ${tagsHTML(r)}
        ${dek ? `<div class="headnote"><p class="dek clamped">${esc(dek)}</p><button class="dek-more" data-dek-toggle hidden>more</button></div>` : ""}`;

  const vitalsInner = editing
    ? `${vitalsEditHTML(r)}<div class="ie-planahead">${waitsEditHTML(data)}${storageEditHTML(data)}</div><div class="stats cook-block locked" data-rid="${esc(r.id)}" aria-disabled="true">${statsInner(data.stats)}</div>`
    : `<div class="stats cook-block" data-rid="${esc(r.id)}">${statsInner(data.stats)}</div>
        ${owner}`;

  // Stage 1: ingredients & steps stay DISPLAY-ONLY in edit mode (rendered from the draft, no scaler,
  // no edit affordances) and round-trip unchanged on Save. Discrete inline editing lands in Stage 2/3.
  const ingSection = editing ? editIngredientsHTML() : ingredientsSectionInner(view);
  // Stage 1a: in edit mode, non-heading steps become TipTap mount hosts (mounted right after this
  // paint by enterEditMode); headings stay display-only, and reading mode is unchanged.
  const steps = editing
    ? view.draft.steps.map(renderStepEditHost).join("")
    : renderStepsList(data.steps);

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
            ${editing ? stepAddersHTML() : ""}
            ${editing ? `<div class="ie-notes">${ieNotesHTML(view.draft)}</div>`
                      : notesSectionHTML(data.notes)}
          </section>
        </div>
        ${editing ? "" : albumSectionHTML(data)}
      </div>
    </div>
    ${editing ? inlineSaveBarHTML() : ""}`;

  if (!editing) {   // edit mode bypasses the description clamp (no .dek); reading keeps it
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(setupHeadnote);
    else setupHeadnote();
    wirePhotoUpload();   // Stage 3: the editable Polaroid becomes an upload/replace surface (no-op otherwise)
    wireAlbumUpload();   // Stage 4 (3b-i): the album add-tile becomes a multi-file upload surface (no-op if none)
    const albumGrid = app.querySelector(".album-grid.masonry");
    if (albumGrid) { layoutAlbum(albumGrid); bindAlbumResize(); }   // aspect-matched masonry (order-preserving columns)
  }
}

// Stage 3 photo upload: wire the editable Polaroid as an upload surface — part 1 (EMPTY: add) and part 2
// (FILLED: replace) share ONE implementation. Called after each reading-mode paint on the freshly rendered
// zone — paintRecipe rebuilds the DOM, so the previous zone (and its listeners) are discarded, no
// accumulation. No-ops when there's no editable Polaroid (dishPhoto only tags it when data.is_mine).
// The send() core, the !file guard, and the drag/drop + picker wiring are IDENTICAL for both modes; only
// how each STATE is painted differs — EMPTY rewrites the zone cell (nothing to lose); FILLED overlays the
// live <img> WITHOUT touching it, so a failed replace can never blank/destroy the existing photo.
function wirePhotoUpload() {
  const wrap = app.querySelector(".dish-photo[data-upload-zone]");
  if (!wrap) return;
  const input = wrap.querySelector(".photo-input");
  const rid = view && view.slug;              // id == slug in this app: the SAME key the POST endpoint
  if (!input || !rid) return;                 // (s.get(Recipe, rid)) and the success re-render use
  const filled = wrap.classList.contains("polaroid-filled");   // part 2: replacing an existing photo

  let rest, uploading, fail;
  if (!filled) {
    const zone = wrap.querySelector(".upload-zone");
    if (!zone) return;
    rest = () => {
      wrap.classList.remove("dragover", "error");
      zone.className = "photo upload-zone";
      zone.innerHTML = '<span class="add-photo-mark">+</span><span class="add-label">drag a photo here<br>or click to choose</span>';
    };
    uploading = () => {
      wrap.classList.remove("dragover", "error");
      zone.className = "photo upload-zone working";
      zone.innerHTML = '<div class="uploading"><span class="spinner"></span>uploading…</div>';
    };
    fail = (status) => {
      wrap.classList.remove("dragover");
      wrap.classList.add("error");
      zone.className = "photo upload-zone";
      zone.innerHTML = uploadErrorHTML(status);   // stays inside the frame; "Try again" returns to rest
    };
  } else {
    const polaroid = wrap.querySelector(".polaroid");
    const clearOverlay = () => { const o = polaroid.querySelector(".photo-overlay"); if (o) o.remove(); };
    rest = () => { wrap.classList.remove("dragover"); clearOverlay(); };   // the <img> stays; drop any overlay
    uploading = () => {                                                    // dim + spinner OVER the photo
      wrap.classList.remove("dragover"); clearOverlay();
      polaroid.insertAdjacentHTML("beforeend", '<div class="photo-overlay replacing"><span class="spinner"></span>replacing…</div>');
    };
    fail = (status) => {   // CRITICAL (part 2): overlay the error; NEVER remove the existing <img>
      wrap.classList.remove("dragover"); clearOverlay();
      polaroid.insertAdjacentHTML("beforeend", `<div class="photo-overlay errored">${uploadErrorHTML(status)}</div>`);
    };
  }

  const send = async (file) => {
    if (!file) { rest(); return; }              // GUARD: macOS Photos may hand a reference, not bytes ->
                                                // graceful no-op (never error/hang; click-to-pick still works)
    uploading();
    const fd = new FormData();
    fd.append("image", file);
    let res;
    try {
      res = await fetch(`/api/recipes/${encodeURIComponent(rid)}/image`,
                        { method: "POST", credentials: "same-origin", body: fd });
    } catch (_) { fail(0); return; }            // network/abort -> generic, recoverable (filled: photo preserved)
    if (res.status === 401) { showAuth(); return; }
    if (!res.ok) { fail(res.status); return; }
    renderRecipe(rid);                          // 200 -> re-pull by the SAME key + full repaint; the new photo fills the real Polaroid
  };

  // Trigger + "Try again". ⚠️ THE FILLED POLAROID NO LONGER OPENS THE PICKER ON CLICK. Its pill opens
  // the album overlay instead (data-album-open), and adding from there goes to /photos so it cannot
  // steal the hero. The EMPTY zone still picks straight to /image, which is right: a recipe with no
  // hero should get one from its first photo. Drag-and-drop onto a filled Polaroid is left alone —
  // dropping a picture ON the hero is an unambiguous "put this here", and it still goes to /image.
  wrap.addEventListener("click", (e) => {
    if (e.target.closest(".err-retry")) { rest(); return; }
    if (!filled && e.target.closest(".upload-zone")) input.click();
  });
  if (!filled) {   // the empty zone is a role=button; the filled pill is a native <button> (keyboard built in)
    wrap.querySelector(".upload-zone").addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    });
  }
  input.addEventListener("change", () => { send(input.files[0]); });   // undefined on cancel -> guarded no-op

  if (filled) {   // Stage B robustness: a broken hero <img> (a dead image pointer) degrades to the empty
    const heroImg = wrap.querySelector("img.photo");   // uploadable Polaroid + re-wires it, not a hole.
    let degraded = false;                              // (Non-editable filled has no data-upload-zone -> never here.)
    const degrade = () => {
      if (degraded || !heroImg) return;
      degraded = true;
      wrap.outerHTML = emptyDishPhotoHTML();
      wirePhotoUpload();                               // bind the fresh empty zone's upload path
    };
    if (heroImg) {
      heroImg.addEventListener("error", degrade);
      if (heroImg.complete && heroImg.naturalWidth === 0) degrade();   // already 404'd before this wiring ran
    }
  }

  // drag-and-drop (Finder/Desktop files land here too). preventDefault on dragover is what enables the
  // drop; scoped to this zone so a stray file dropped elsewhere on the page keeps the browser default.
  ["dragenter", "dragover"].forEach((ev) => wrap.addEventListener(ev, (e) => {
    e.preventDefault();
    if (!wrap.classList.contains("error")) wrap.classList.add("dragover");
  }));
  ["dragleave", "dragend"].forEach((ev) => wrap.addEventListener(ev, (e) => {
    if (!wrap.contains(e.relatedTarget)) wrap.classList.remove("dragover");   // ignore moves between children
  }));
  wrap.addEventListener("drop", (e) => {
    e.preventDefault();
    wrap.classList.remove("dragover");
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    send(f);                                    // f undefined (Photos reference) -> guarded no-op in send()
  });
}

// Stage 4 (3b-i) standalone "add to album" upload: the album add-tile (owner-only) is a MULTI-FILE upload
// surface. Reuses the hero uploader's state-painting (rest/uploading/error via uploadErrorHTML) and drag/drop
// + picker wiring, but POSTs to the album attach endpoint with NO cook_log_id (standalone -> no date) and
// runs the batch best-effort via Promise.allSettled: the successes are kept (a repaint shows them) and the
// misses are surfaced in the tile — never all-or-nothing. No-ops when there's no add-tile (non-owner / edit
// mode). Rewired on every reading-mode paint, like wirePhotoUpload — no listener buildup.
function wireAlbumUpload() {
  const wrap = app.querySelector(".album-photo.album-add[data-album-add]");
  if (!wrap) return;
  const input = wrap.querySelector(".album-photo-input");
  const zone = wrap.querySelector(".upload-zone");
  const pe = wrap.querySelector(".polaroid-empty");
  const rid = view && view.slug;
  if (!input || !zone || !pe || !rid) return;

  const rest = () => {
    pe.classList.remove("dragover", "error");
    zone.className = "photo upload-zone";
    zone.innerHTML = '<span class="add-photo-mark">+</span><span class="add-label">drag photos here<br>or click to choose</span>';
  };
  const uploading = (n) => {
    pe.classList.remove("dragover", "error");
    zone.className = "photo upload-zone working";
    zone.innerHTML = `<div class="uploading"><span class="spinner"></span>uploading ${n > 1 ? n + " photos" : "photo"}&hellip;</div>`;
  };
  const fail = (html) => {
    pe.classList.remove("dragover");
    pe.classList.add("error");
    zone.className = "photo upload-zone";
    zone.innerHTML = html;
  };
  const setDrag = (on) => {   // preview's "drop to add" label swap (skip while working/errored)
    if (zone.classList.contains("working") || pe.classList.contains("error")) return;
    pe.classList.toggle("dragover", on);
    const lbl = zone.querySelector(".add-label");
    if (lbl) lbl.innerHTML = on ? "drop to add" : 'drag photos here<br>or click to choose';
  };

  // POST one file as a STANDALONE album photo (no cook_log_id); resolves to the HTTP status, rejects on
  // network error. allSettled below turns each into fulfilled(status) / rejected(err) — nothing aborts the batch.
  const postOne = async (file) => {
    const fd = new FormData();
    fd.append("image", file);                             // NO cook_log_id -> STANDALONE (cook_log_id NULL, no date)
    const res = await fetch(`/api/recipes/${encodeURIComponent(rid)}/photos`,
                            { method: "POST", credentials: "same-origin", body: fd });
    return res.status;
  };

  const uploadMany = async (files) => {
    const list = Array.from(files || []).filter(Boolean);   // Photos may hand a reference -> filter it out
    if (!list.length) { rest(); return; }                   // nothing pickable -> guarded no-op (never hang)
    uploading(list.length);
    const results = await Promise.allSettled(list.map(postOne));   // best-effort batch — settle them all
    if (results.some((r) => r.status === "fulfilled" && r.value === 401)) { showAuth(); return; }   // session gone
    let ok = 0, failCount = 0, firstStatus = 0;
    for (const r of results) {
      const st = r.status === "fulfilled" ? r.value : 0;    // rejected (network/abort) -> 0 (generic recoverable)
      if (st >= 200 && st < 300) ok++;
      else { failCount++; firstStatus = firstStatus || st; }
    }
    if (ok && failCount) {                                  // PARTIAL: keep the good ones (repaint), flag the misses
      await renderRecipe(rid);
      const t = app.querySelector(".album-photo.album-add[data-album-add]");
      if (t) {
        const tpe = t.querySelector(".polaroid-empty"), tz = t.querySelector(".upload-zone");
        tpe.classList.add("error"); tz.className = "photo upload-zone";
        tz.innerHTML = `<span class="err-msg">Added ${ok}; ${failCount} couldn&rsquo;t be added.</span><span class="err-sub">JPEG, PNG, WebP, or HEIC</span><button class="err-retry">Try again</button>`;
      }
      return;
    }
    if (ok) { renderRecipe(rid); return; }                  // all succeeded -> repaint; the new photos appear
    fail(uploadErrorHTML(firstStatus));                     // none succeeded -> in-frame error (nothing changed)
  };

  wrap.addEventListener("click", (e) => {
    if (e.target.closest(".add-hint")) return;              // the (i) hint isn't a trigger
    if (e.target.closest(".err-retry")) { rest(); return; } // "Try again" -> back to rest (no picker)
    if (e.target.closest(".upload-zone")) input.click();
  });
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
  });
  input.addEventListener("change", () => { uploadMany(input.files); input.value = ""; });  // clear -> re-picking the same files re-fires

  ["dragenter", "dragover"].forEach((ev) => wrap.addEventListener(ev, (e) => { e.preventDefault(); setDrag(true); }));
  ["dragleave", "dragend"].forEach((ev) => wrap.addEventListener(ev, (e) => {
    if (!wrap.contains(e.relatedTarget)) setDrag(false);    // ignore moves between the tile's own children
  }));
  wrap.addEventListener("drop", (e) => {
    e.preventDefault(); setDrag(false);
    uploadMany(e.dataTransfer && e.dataTransfer.files);     // empty / reference -> guarded no-op in uploadMany
  });
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

// Plan-ahead + storage editing (round 2). ONE text box per wait, exactly as the times above are one
// box each: the numbers are read from what you type, on the server, on save. Unreadable words are
// kept and the numbers stay blank, the same contract normalize_time already has for a time column.
//
// ⚠️ THE EXTENSION IS ITS OWN BOX, and that is the whole reason this is not a single field. Typing
// "10 min to an hour or overnight if time allows" into one box gives a range of 10 minutes to 8
// hours, which is a promise the recipe never made. Two boxes keep the invitation beside the range.
const WAIT_KINDS = ["marinating", "chilling", "rising", "soaking", "resting", "freezing", "brining", "other"];
const STORE_WHERE = ["fridge", "freezer", "room temp", "other"];
// The stored value and the word the editor shows for it. "only if" needs a condition after it.
const WAIT_WHENS = [["always", "always"], ["optional", "optional"], ["only_if", "only if"],
                    ["alongside", "alongside"]];

function pickHTML(list, val, attr, i) {
  // Each entry is either a bare value or [value, the word to show].
  return `<select class="ie ie-pick" data-${attr}="${i}">`
    + list.map((k) => { const [v, w] = Array.isArray(k) ? k : [k, k];
        return `<option value="${esc(v)}"${v === val ? " selected" : ""}>${esc(w)}</option>`; }).join("")
    + `</select>`;
}

// The step picker's options: every ordinary step, numbered as the page numbers them, with enough
// of its text to recognise. ⚠️ THE VALUE IS THE POSITION, NOT THE NUMBER. Headings carry positions
// too, so the two sequences diverge the moment a recipe has a heading.
// ⚠️ THE VALUE IS THE STEP'S ROW ID, NOT ITS POSITION. A position is a slot, and every save renumbers
// the slots, so a wait linked by position pointed at whatever moved into that slot afterwards. The
// number shown to the user is still the printed step number, counted heading-excluded here exactly as
// the CSS counter does — the id is what travels. Migration 053.
function stepChoices(d, blank = "no step") {
  const out = [["", blank]];
  let n = 0;
  for (const st of (d.steps || [])) {
    if (st.is_heading) continue;
    n += 1;
    const txt = String(st.text || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    out.push([String(st.id), `${n}. ${txt.slice(0, 40)}${txt.length > 40 ? "\u2026" : ""}`]);
  }
  return out;
}

function waitsEditHTML(d) {
  // ⚠️ THE CONDITION BOX IS ALWAYS IN THE DOM and CSS hides it unless the picker says only_if. The
  //    alternative is repainting the block on a select change, which takes focus off the select the
  //    user just used.
  const rows = (d.waits || []).map((w, i) => `<div class="ie-wait-row" data-when="${esc(w.when_kind || "always")}">
      ${pickHTML(WAIT_KINDS, w.kind || "other", "wait-kind", i)}
      <input class="ie ie-wait" data-wait-label="${i}" value="${esc(w.label || "")}" placeholder="1 hr rise" aria-label="Wait">
      <input class="ie ie-wait-ext" data-wait-ext="${i}" value="${esc(w.ext_label || "")}" placeholder="or overnight if time allows" aria-label="Extension">
      ${pickHTML(WAIT_WHENS, w.when_kind || "always", "wait-when", i)}
      <input class="ie ie-wait-if" data-wait-when-label="${i}" value="${esc(w.when_label || "")}" placeholder="chilled" aria-label="Only if">
      ${pickHTML(stepChoices(d), w.step_id == null ? "" : String(w.step_id), "wait-step-pick", i)}
      ${pickHTML(stepChoices(d, "alongside which step?"), w.alongside_step_id == null ? "" : String(w.alongside_step_id), "wait-aside-pick", i)}
      ${pickHTML(stepChoices(d, "the alternative's step?"), w.ext_step_id == null ? "" : String(w.ext_step_id), "wait-ext-pick", i)}
      <button type="button" class="ie-x" data-wait-del="${i}" aria-label="Remove this wait">×</button>
    </div>`).join("");
  return `<div class="ie-block"><span class="ie-vlabel">Plan ahead</span>${rows}
      <button type="button" class="ie-add" data-wait-add>+ add a wait</button></div>`;
}

function storageEditHTML(d) {
  const rows = (d.storage || []).map((x, i) => `<div class="ie-wait-row">
      ${pickHTML(STORE_WHERE, x.where_kept || "fridge", "store-where", i)}
      <input class="ie ie-wait-ext" data-store-what="${i}" value="${esc(x.applies_to || "")}" placeholder="the dough" aria-label="Applies to">
      <input class="ie ie-wait" data-store-label="${i}" value="${esc(x.label || "")}" placeholder="up to 1 week" aria-label="Keeps for">
      <button type="button" class="ie-x" data-store-del="${i}" aria-label="Remove this">×</button>
    </div>`).join("");
  return `<div class="ie-block"><span class="ie-vlabel">Storage</span>${rows}
      <button type="button" class="ie-add" data-store-add>+ add storage</button></div>`;
}

// One delegated handler for both sections. Mutates the draft and repaints just the two blocks, so a
// keystroke in a text box never repaints the page out from under the caret (only add/remove do).
function handlePlanAheadAction(t) {
  const d = view && view.draft;
  if (!d) return false;
  // ⚠️ THE NOTES BLOCK IS REPAINTED TOO, AND IT IS NOT INSIDE .ie-planahead. The notes editor
  //    renders into the Method section, so a repaint that rewrote only the plan-ahead host left
  //    every note action invisible: "+ add a note" put a row in the draft and nothing appeared, ×
  //    removed one that stayed on screen, and ↑/↓ swapped the draft objects while the DOM kept the
  //    old order AND the old data-note-text indices. That last one corrupts: on [A, B, C], moving
  //    A down made the draft [B, A, C], the box still showing "B" was index 1, and typing in it
  //    wrote over A. paintRecipe cannot be used here (it would orphan the mounted step editors),
  //    which is why each block owns a host.
  const repaint = () => {
    const host = document.querySelector(".ie-planahead");
    if (host) host.innerHTML = waitsEditHTML(d) + storageEditHTML(d);
    const notesHost = document.querySelector(".ie-notes");
    if (notesHost) notesHost.innerHTML = ieNotesHTML(d);
  };
  if (t.closest("[data-wait-add]")) {
    (d.waits = d.waits || []).push({ kind: "other", label: "", ext_label: "", when_kind: "always",
                                     when_label: "", step_id: null, alongside_step_id: null });
    view.dirty = true; repaint(); return true;
  }
  if (t.closest("[data-store-add]")) {
    (d.storage = d.storage || []).push({ where_kept: "fridge", applies_to: "", label: "" }); view.dirty = true; repaint(); return true;
  }
  const wd = t.closest("[data-wait-del]");
  if (wd) { d.waits.splice(+wd.dataset.waitDel, 1); view.dirty = true; repaint(); return true; }
  const sd = t.closest("[data-store-del]");
  if (sd) { d.storage.splice(+sd.dataset.storeDel, 1); view.dirty = true; repaint(); return true; }
  // ⚠️ THE NOTE ACTIONS LEFT THIS FUNCTION ENTIRELY. They edited view.draft.notes and waited for
  //    Save, which is the second editor this round removed. A note is written through its own
  //    endpoint by the shared component (handleNoteAction), in Edit mode exactly as in reading view,
  //    so there is nothing here to keep in step with it.
  return false;
}

function handlePlanAheadInput(el) {
  const d = view && view.draft;
  if (!d || !el.dataset) return false;
  const set = (arr, i, key) => { if (arr && arr[i]) { arr[i][key] = el.value; view.dirty = true; } return true; };
  if (el.dataset.waitLabel  !== undefined) return set(d.waits, +el.dataset.waitLabel, "label");
  if (el.dataset.waitExt    !== undefined) return set(d.waits, +el.dataset.waitExt, "ext_label");
  if (el.dataset.waitKind   !== undefined) return set(d.waits, +el.dataset.waitKind, "kind");
  if (el.dataset.waitWhen   !== undefined) {
    const row = el.closest(".ie-wait-row");
    if (row) row.dataset.when = el.value;     // shows or hides the condition box, no repaint
    return set(d.waits, +el.dataset.waitWhen, "when_kind");
  }
  if (el.dataset.waitWhenLabel !== undefined) return set(d.waits, +el.dataset.waitWhenLabel, "when_label");
  if (el.dataset.waitExtPick !== undefined) {
    // ⚠️ THE STEP THAT DESCRIBES THE ALTERNATIVE, and it is left blank for most waits on purpose.
    //    5 of the 7 stored extensions say the alternative in the wait's own step, and the server
    //    stores NULL rather than a repeat of step_id, so a second link only ever appears where
    //    there is a second step worth reading.
    const i = +el.dataset.waitExtPick;
    if (d.waits && d.waits[i]) {
      d.waits[i].ext_step_id = el.value === "" ? null : +el.value;
      view.dirty = true;
    }
    return true;
  }
  if (el.dataset.waitAsidePick !== undefined) {
    // ⚠️ THE STEP THIS WAIT RUNS ALONGSIDE, for when_kind='alongside'. It names a STEP and never
    //    another wait: waits are deleted and reinserted on every save, so a wait id survives nothing.
    //    The server drops a pointer that names no step of this recipe, or names this wait's own step.
    const i = +el.dataset.waitAsidePick;
    if (d.waits && d.waits[i]) {
      d.waits[i].alongside_step_id = el.value === "" ? null : +el.value;
      view.dirty = true;
    }
    return true;
  }
  if (el.dataset.waitStepPick !== undefined) {
    const i = +el.dataset.waitStepPick;
    if (d.waits && d.waits[i]) {
      // ⚠️ NOTHING TO CLEAR ALONGSIDE IT ANY MORE. This used to null step_check too, so the server
      //    would read a fresh snippet off the newly picked step. The id needs no corroboration.
      d.waits[i].step_id = el.value === "" ? null : +el.value;
      view.dirty = true;
    }
    return true;
  }
  if (el.dataset.noteText !== undefined) return set(d.notes, +el.dataset.noteText, "text");
  if (el.dataset.noteStepPick !== undefined) {
    const i = +el.dataset.noteStepPick;
    if (d.notes && d.notes[i]) {
      d.notes[i].step_id = el.value === "" ? null : +el.value;
      view.dirty = true;
    }
    return true;
  }
  if (el.dataset.storeWhere !== undefined) return set(d.storage, +el.dataset.storeWhere, "where_kept");
  if (el.dataset.storeWhat  !== undefined) return set(d.storage, +el.dataset.storeWhat, "applies_to");
  if (el.dataset.storeLabel !== undefined) return set(d.storage, +el.dataset.storeLabel, "label");
  return false;
}

// The note edits at the BOTTOM (after the steps), mirroring reading's closing "Note. …" block.
// ⚠️ ONE TEXTAREA PER NOTE, NOT ONE FOR ALL OF THEM. A note is a row with its own id, kind and
// links since migration 060, and a single blob of prose has nowhere to put any of that. The shape
// mirrors the plan-ahead list beside it, deliberately: a cook learns one set of controls.
// ⚠️ REORDERING IS BUTTONS, NOT DRAG. Up and down work from the keyboard with no pointer and no
// drop target, which is the accessible default; drag can be added beside them later without
// changing anything stored.
// ⚠️ EDIT MODE RENDERS THE SAME NOTE COMPONENT THE READING PAGE DOES, AND THAT REPLACED A SECOND
//    EDITOR. This block had its own textarea per note, its own kind picker, its own step picker and
//    its own up/down/× controls, and the reading page had none of them. Two renderings of one note
//    where only one could be edited is two opinions about what a note is, and the brief's rule is
//    that they must not be able to disagree. So there is one.
//
// ⚠️ AND A NOTE SAVES IMMEDIATELY HERE, SO Cancel DOES NOT REVERT IT. That is the honest consequence
//    of notes being a playground: they take no part in the tracked edit that Save and Cancel exist
//    for, they mint no annotation entry and they cost the recipe nothing. One rule for the cook in
//    both views, which is "a note is saved when you finish typing it". `notes` left draftPayload
//    entirely, and write_notes reads an absent key as "leave them alone".
//
// ⚠️ IT READS view.data, NOT THE DRAFT. The draft is a structuredClone taken when Edit mode opened,
//    so a note written through its own endpoint afterwards is not in it. Reading the live rows is
//    what keeps this block showing what the database actually holds.
function ieNotesHTML(_d) {
  const rows = noteRows();
  // ⚠️ THE SAME ARRANGEMENT THE RECIPE PAGE DRAWS, from the same function. This built its own
  //    group loop with its own heading class, so the STEP NOTES group and the markers would have
  //    had to be written twice and kept in step by hand.
  const body = notesBodyHTML(rows, { editable: true, place: "ie" })
    || `<p class="notes-empty">No notes yet.</p>`;
  // ⚠️ THE HINT IS GONE BECAUSE THE BEHAVIOUR IT WARNED ABOUT IS. "Notes save as you type" was
  //    there so Cancel would not surprise a cook whose note had already been written. Notes are
  //    held in the draft now and Cancel discards them like everything else on this screen, so the
  //    line would be wrong as well as unnecessary.
  // ⚠️ AND THE ADDER WEARS "+ add step"'s CLOTHES, which is the same .adder in the same
  //    .step-adders row the method uses. A second look for the same gesture is a second thing to
  //    learn.
  return `<div class="ie-block ie-note-block"><span class="ie-vlabel">Notes</span>
      ${body}${noteNewBoxHTML("general")}
      <div class="step-adders">
        <button type="button" class="adder" data-add-note="general">+ Add a note</button>
      </div>
      ${noteUndoHTML()}</div>`;
}
// (Image path is intentionally NOT editable here — real photo upload is the next feature; the recipe's
// existing image round-trips unchanged on save via draftPayload.)

// Stage 2: ingredients editable inline in the ledger. A SEPARATE raw-field path (not plainRow /
// ledgerCells / lineBodyHTML — those are the cooked reading path). Each draft ingredient renders as
// an editable row reading RAW fields; the display name is label‖raw_text and edits write to `label`
// (the convention ingToPayload reads). Kept fully separate from the seed line-editor.
const ING_GRIP = `<svg viewBox="0 0 9 14" class="grip-ico" aria-hidden="true"><g fill="currentColor"><circle cx="2" cy="2" r="1.3"/><circle cx="7" cy="2" r="1.3"/><circle cx="2" cy="7" r="1.3"/><circle cx="7" cy="7" r="1.3"/><circle cx="2" cy="12" r="1.3"/><circle cx="7" cy="12" r="1.3"/></g></svg>`;
const ING_TRASH = `<svg viewBox="0 0 16 16" class="ic-trash" aria-hidden="true"><path d="M3 4.5h10"/><path d="M6.5 4.5V3h3v1.5"/><path d="M4.5 4.5l.6 8.5a1 1 0 0 0 1 .9h3.8a1 1 0 0 0 1-.9l.6-8.5"/><path d="M7 7v4M9 7v4"/></svg>`;
const ING_NOTEPLUS = `<svg viewBox="0 0 22 16" class="ic-note" aria-hidden="true"><path d="M3 2.5h10v7.5l-3 3.5H3z"/><path d="M13 10h-3v3.5"/><path d="M18 4v5M15.5 6.5h5"/></svg>`;
const ING_NOTE = `<svg viewBox="0 0 16 16" class="ic-note-sm" aria-hidden="true"><path d="M3 2.5h10v7.5l-3 3.5H3z"/><path d="M13 10h-3v3.5"/></svg>`;
// A stage 1: the row-actions ⋯ trigger. Deliberately NOT a third icon style — it is ING_GRIP's own
// primitive (circle r=1.3, fill currentColor) laid out horizontally, so the cluster speaks one
// vocabulary. 14×4 viewBox because the dots ARE the glyph; there is no surrounding box to reserve.
const ING_MORE = `<svg viewBox="0 0 14 4" class="more-ico" aria-hidden="true"><g fill="currentColor"><circle cx="2" cy="2" r="1.3"/><circle cx="7" cy="2" r="1.3"/><circle cx="12" cy="2" r="1.3"/></g></svg>`;

// The ⋯ button itself, shared by both lists. `kind` ("ing" | "step") rides on the attribute so the
// handler can branch without re-deriving it from the DOM, and `data-i` is the row index in the
// matching view.draft array — the SAME convention every other row control uses.
function rowMoreHTML(i, kind) {
  return `<button type="button" class="rbtn more" data-row-menu="${kind}" data-i="${i}" title="More actions" aria-label="More actions" aria-haspopup="true" aria-expanded="false">${ING_MORE}</button>`;
}

// Hover-revealed row-actions: a divider, then grip · fenced red trash · ⋯. The divider + cluster are
// hidden at rest and slide in on hover/focus-within (link + note-icon stay).
// A stage 2 removed the labelled heading-toggle (an ≡ icon carrying a visible "heading"/"ingredient"
// word) — it is now a menu item, so the cluster is 87px instead of 134.75px and the name column gets
// the difference back. The TRASH DELIBERATELY STAYS INLINE: deleting an ingredient is the common
// editing action, and one-click delete is the decided end state for this list (steps are the
// asymmetric case — their delete moved into the menu because their cluster had no room for both).
// This is the FINAL shape of the ingredient cluster; C1 made the grip live, and it is now the drag
// source itself — see the GRIP-ONLY DRAG note above editStepRowTools.
function editIngRowTools(i) {
  return `<span class="divider" aria-hidden="true"></span><span class="rtools">
    <span class="rbtn grip" draggable="true" title="Drag to reorder" aria-hidden="true">${ING_GRIP}</span>
    <button type="button" class="rbtn rm" data-inline-edit-rm-ing data-i="${i}" title="Remove" aria-label="Remove">${ING_TRASH}</button>
    ${rowMoreHTML(i, "ing")}
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
      ${ieCell("heading", i, showLinksAsWords(headingText(x)), "e-heading", "Section heading")}
      <span class="tail">${editIngRowTools(i)}</span>
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
  // Grip-only: the row is NOT a drag source (see the GRIP-ONLY DRAG note above editStepRowTools).
  // The below-note row is likewise not a target: it belongs to the row above it and travels with it
  // (the draft holds one object per ingredient, note included), which is also why the drag indexes
  // by li.erow and not by li.
  const main = `<li class="erow${noteOpen ? " has-note" : ""}">
    ${amountZoneHTML(x, i)}
    ${ieCell("name", i, name, "e-name", "ingredient")}
    <span class="tail">${linkBit}${noteIcon}${editIngRowTools(i)}</span>
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
// B generalised this from append-only to insert-at: `at` omitted means the end, which is exactly what
// the two adders under the list still want, so their call sites are unchanged and there is no second
// row template to keep in sync. The row SHAPE and the post-insert behaviour (markDirty -> re-render ->
// focus the new row) are shared by both entry points by construction.
function addIngredient(isHeading, at) {
  const arr = view.draft.ingredients;
  const at_ = at == null ? arr.length : at;
  // id: null is the row template saying "the database has never seen me". ingToPayload sends it as
  // such, and the server inserts rather than looks it up (option C).
  arr.splice(at_, 0, isHeading ? { id: null, is_heading: 1, heading: "", qty: "", quantity: "", unit: "", label: "", note: "", ingredient_id: null, raw_text: "" }
                               : { id: null, is_heading: 0, qty: "", quantity: "", unit: "", label: "", note: "", ingredient_id: null, raw_text: "" });
  markDirty(); rerenderEditIngredients();
  focusIngField(at_, isHeading ? "heading" : "quantity");
}
function removeIngredient(i) { view.draft.ingredients.splice(i, 1); markDirty(); rerenderEditIngredients(); }

// ---- C1: ingredient drag-reorder (native HTML5 DnD, the album's mechanism on the other axis) --------
// No backend work is involved or needed: write_recipe_rows assigns position from enumerate over the
// saved list, so the DRAFT ARRAY'S ORDER *IS* the stored order. A reorder is a pure client edit that
// markDirty() carries into the ordinary save.
//
// HEADINGS MOVE FREELY, exactly like any other row — decided, not an oversight. Sections here are
// positional (see row-insert.js), so dragging a heading moves one row and the rows beneath it change
// section. That is visible as it happens, undone by dragging back, and emits no annotation (heading
// changes are organizational); the baseline's heading layout follows current via the sync in 9861fe4.
//
// MOUSE-ONLY, inherited from the album: HTML5 DnD does not fire on touch and there is no keyboard
// path. Not opened here.
let ingDragFrom = null;                                 // draft index of the row being dragged

// The rows in DOM order. Indexing by li.erow (not by li) is what makes this correct in the presence
// of below-note rows, which are a SECOND <li> emitted after their owner — so the <ul>'s children are
// not 1:1 with the draft array, but its .erow children are. Reading the index from DOM position also
// means there is no data-i to go stale between a splice and its re-render.
function editIngRowEls(list) { return [...list.querySelectorAll("li.erow")]; }

// ---- shared by BOTH editor lists (C1 ingredients, C2 steps) ---------------------------------------
// The drop bar's placement and read-back are pure DOM and identical for the two lists, so they live
// once. `rows` is the list's row elements in order; the bar is inserted BEFORE rows[before], or
// appended when before is null ("the end"). Deliberately NOT merged with the album's version: that one
// is horizontal, lives in a flex strip, and opens a gap on purpose.
// ⚠️ TWO OPTIONS, BOTH FOR THE NOTE LIST, AND BOTH DEFAULT TO THE BEHAVIOUR THE TWO EDITOR LISTS
//    ALREADY HAD. `tag` is <li> for a list and <div> for the notes section, which is divs. And
//    `afterLast` is what "the end" means when `rows` is a RUN inside its container rather than the
//    whole of it: the bar goes after the last of them, not after the container's last child. The
//    ingredient list is the reason that is opt-in — its rows are not its only children (a below-note
//    row follows its owner), so changing the default would move its bar by one row.
function paintDropBar(list, rows, before, { tag = "li", afterLast = false } = {}) {
  let bar = list.querySelector(".drop-bar");
  if (!bar) { bar = document.createElement(tag); bar.className = "drop-bar"; bar.setAttribute("aria-hidden", "true"); }
  if (before != null) list.insertBefore(bar, rows[before]);
  else if (afterLast && rows.length) rows[rows.length - 1].after(bar);
  else list.appendChild(bar);
}
// Read the drop target back off the BAR rather than recomputing from clientY, so what lands is exactly
// what the user was looking at. Walking forward to the next element that IS a row skips anything in
// between — an ingredient's below-note row, say. Returns the before-index, null for "the end", or
// undefined when no bar was ever painted (a drop with no preceding dragover), which the caller
// distinguishes from null because they mean different things.
function beforeIndexFromBar(list, rows) {
  const bar = list.querySelector(".drop-bar");
  if (!bar) return undefined;
  let n = bar.nextElementSibling;
  while (n && rows.indexOf(n) < 0) n = n.nextElementSibling;
  return n ? rows.indexOf(n) : null;
}
// dragend cleanup for either list. Scoped to the two editor lists BY NAME: .ghost-origin and .drop-bar
// are also the album's class names, and a bare querySelectorAll would reach into a photo reorder.
function clearRowDragArtifacts() {
  document.querySelectorAll(".ingredient-list.edit .ghost-origin, #steps-list .ghost-origin,"
                            + " .ie-note-block .ghost-origin")
    .forEach((el) => el.classList.remove("ghost-origin"));
  document.querySelectorAll(".ingredient-list.edit .drop-bar, #steps-list .drop-bar,"
                            + " .ie-note-block .drop-bar")
    .forEach((el) => el.remove());
  const h = document.getElementById("drag-img-host"); if (h) h.innerHTML = "";   // release the pill
}

// The DRAG IMAGE is a compact pill naming the row — set explicitly, so the browser never falls back to
// its default, which is a snapshot of the dragged element itself. That default is what made the drop
// bar unfindable: a row is 820px wide, exactly the width of the bar, and its snapshot band contains
// the cursor at 4 of 5 grab offsets, so it covered the very thing the user aims with. A pill is a few
// hundred pixels of chip that floats clear of the cursor and hides nothing.
function ingPillLabel(x) {
  if (!x) return "ingredient";
  if (x.is_heading) return headingText(x) || "heading";           // headings carry no name field
  const name = (x.label || x.raw_text || "").trim();
  return name || String(x.qty || x.quantity || "").trim() || "ingredient";
}
// setDragImage requires its element to be IN THE DOCUMENT AND LAID OUT at snapshot time — display:none,
// visibility:hidden and detached nodes each yield the DEFAULT image instead, and the API accepts all of
// them without throwing, so a mistake here is silent and looks like "the fix didn't work". Hence a
// fixed, off-viewport host (styles.css): genuinely rendered, never visible. Emptied on dragend rather
// than a frame later, so nothing races the snapshot.
function setDragPill(e, label) {
  if (!e.dataTransfer || !e.dataTransfer.setDragImage) return;
  let host = document.getElementById("drag-img-host");
  if (!host) { host = document.createElement("div"); host.id = "drag-img-host"; document.body.appendChild(host); }
  host.innerHTML = "";
  const pill = document.createElement("span");
  pill.className = "chip drag-pill";                              // the EXISTING chip, not a new look
  pill.textContent = label;
  host.appendChild(pill);
  // The cursor sits 12px in from the pill's left edge and 8px BELOW its bottom edge — offsets outside
  // the image are legal and simply shift it — so the pill floats up and to the right and can never
  // straddle the drop bar, whichever side of the cursor the bar lands on.
  e.dataTransfer.setDragImage(pill, 12, Math.round(pill.getBoundingClientRect().height) + 8);
}

function ingDragStart(e) {
  const row = e.target.closest(".ingredient-list.edit li.erow");
  if (!row || !view || !view.editMode || !view.draft) return;
  const at = editIngRowEls(row.closest(".ingredient-list.edit")).indexOf(row);
  if (at < 0) return;
  ingDragFrom = at;
  try { e.dataTransfer.setData("text/plain", String(at)); e.dataTransfer.effectAllowed = "move"; } catch (_) {}
  setDragPill(e, ingPillLabel((view.draft.ingredients || [])[at]));
  // .ghost-origin dims the row LEFT BEHIND, and it stays deferred a frame even though the pill — not
  // this row — is now what gets carried. setDragImage fails SILENTLY (see setDragPill): if it ever
  // does, the browser snapshots this row after all, and a synchronous dim would be baked into the
  // image. The rAF costs nothing and keeps that failure mode cosmetic. Same reason the album defers
  // it (app.js:1460).
  requestAnimationFrame(() => row.classList.add("ghost-origin"));
}

// Paint only — NEVER re-render here. Repainting the section during dragover destroys the element the
// drag is over, which kills the drag mid-flight. The bar is inserted into the list but is laid out at
// ZERO net height (see styles.css), so painting it cannot shift the rows the next dragover measures.
function ingDragOver(e) {
  if (ingDragFrom == null) return;
  const list = e.target.closest(".ingredient-list.edit");
  if (!list) return;
  e.preventDefault();                                   // required, or no drop event fires
  const rows = editIngRowEls(list);
  paintDropBar(list, rows, dropBeforeIndex(rows.map((r) => r.getBoundingClientRect()), e.clientY, ingDragFrom));
}

function ingDrop(e) {
  if (ingDragFrom == null) return;
  const list = e.target.closest(".ingredient-list.edit");
  if (!list) return;
  e.preventDefault();
  const rows = editIngRowEls(list);
  let before = beforeIndexFromBar(list, rows);
  if (before === undefined) {                           // dropped with no dragover having painted one
    before = dropBeforeIndex(rows.map((r) => r.getBoundingClientRect()), e.clientY, ingDragFrom);
  }
  const next = applyRowDrop(view.draft.ingredients, ingDragFrom, before);
  ingDragFrom = null;
  if (next) { view.draft.ingredients = next; markDirty(); }
  rerenderEditIngredients();                            // the re-render belongs HERE, once, after the move
}

// Defensive by necessity: drop already re-rendered the section, so the ghost row and the bar are
// usually gone by the time this fires (the album's if (g) / if (b) shape, same reason).
function ingDragEnd() {
  ingDragFrom = null;
  clearRowDragArtifacts();
}

// The ONE write-back callback the per-step TipTap editors are mounted with. Named (not an inline
// arrow at the enterEditMode call site) so the ORIGINAL mount and every re-mount wire up identically.
function onStepInput(i, text) { view.draft.steps[i].text = text; markDirty(); }

// ---- C2: step drag-reorder --------------------------------------------------------------------
// Everything structural is inherited from C1: C0's height-agnostic arithmetic, the shared drop bar and
// its read-back, the pill drag image, the rAF-deferred .ghost-origin, grip-only draggability,
// headings moving freely, mouse-only. What is NOT shared is the drop: it MUST go through
// rerenderEditSteps.
//
// ⚠️ THE ISLAND INVARIANT (step-editor.js:8-12) IS THE WHOLE RISK HERE. Each step's TipTap editor
// captured its index in its onUpdate closure at mount. A drop splices draft.steps, so every editor
// from the lower of the two indices onward is now bound to the WRONG step — and nothing errors: the
// next keystroke silently writes into a neighbour. rerenderEditSteps is the only path that fixes it,
// because it destroys every editor, re-renders with fresh data-i, and re-mounts. A bare innerHTML swap
// (which is all the ingredient side needs) would orphan them instead.
let stepDragFrom = null;

// Indexed by li.step-edit, not by li. #steps-list's children ARE 1:1 with draft.steps today — heading
// and normal steps both emit exactly one li and nothing else emits any — but the drop bar is itself an
// <li> inserted mid-drag, so a bare li index would be off by one from the moment the bar appears.
// Same class covers both row shapes: li.step.step-edit and li.group.step-edit.
function editStepRowEls(list) { return [...list.querySelectorAll("li.step-edit")]; }

// A step is a paragraph, not a name, so the pill carries an identifying PREFIX rather than the row.
// 42 chars is about 280px of the 14px sans face — a quarter of the row's width, enough to tell two
// steps apart at a glance and small enough to stay clear of the bar. Cut back to a word boundary only
// when that keeps most of the budget (past char 24), so a long first word truncates mid-word rather
// than collapsing the label to nothing.
function stepPillLabel(x) {
  if (!x) return "step";
  const t = String(x.text || "").replace(/\s+/g, " ").trim();
  if (x.is_heading) return t || "heading";
  if (!t) return "step";
  if (t.length <= 42) return t;
  const cut = t.slice(0, 42), sp = cut.lastIndexOf(" ");
  return (sp > 24 ? cut.slice(0, sp) : cut).trimEnd() + "…";
}

function stepDragStart(e) {
  const row = e.target.closest("#steps-list li.step-edit");
  if (!row || !view || !view.editMode || !view.draft) return;
  const at = editStepRowEls(row.closest("#steps-list")).indexOf(row);
  if (at < 0) return;
  stepDragFrom = at;
  try { e.dataTransfer.setData("text/plain", String(at)); e.dataTransfer.effectAllowed = "move"; } catch (_) {}
  setDragPill(e, stepPillLabel((view.draft.steps || [])[at]));
  requestAnimationFrame(() => row.classList.add("ghost-origin"));   // deferred for C1's reason
}

// Paint only. Re-rendering here would be doubly wrong: it destroys the element the drag is over (as on
// the ingredient side) AND tears down every TipTap editor on every pointer move.
function stepDragOver(e) {
  if (stepDragFrom == null) return;
  const list = e.target.closest("#steps-list");
  if (!list) return;
  e.preventDefault();                                   // required, or no drop event fires
  const rows = editStepRowEls(list);
  paintDropBar(list, rows, dropBeforeIndex(rows.map((r) => r.getBoundingClientRect()), e.clientY, stepDragFrom));
}

function stepDrop(e) {
  if (stepDragFrom == null) return;
  const list = e.target.closest("#steps-list");
  if (!list) return;
  e.preventDefault();
  const rows = editStepRowEls(list);
  let before = beforeIndexFromBar(list, rows);
  if (before === undefined) {                           // dropped with no dragover having painted one
    before = dropBeforeIndex(rows.map((r) => r.getBoundingClientRect()), e.clientY, stepDragFrom);
  }
  const next = applyRowDrop(view.draft.steps, stepDragFrom, before);
  stepDragFrom = null;
  if (next) { view.draft.steps = next; markDirty(); }
  rerenderEditSteps();                                  // the full destroy -> re-render -> re-mount cycle
}

function stepDragEnd() {
  stepDragFrom = null;
  clearRowDragArtifacts();
}

// ---- the Edit-mode note list's reorder ----------------------------------------------------------
// Everything structural is inherited from C1 and C2: the shared drop bar and its read-back, C0's
// height-agnostic arithmetic, the pill drag image, the rAF-deferred .ghost-origin, grip-only
// draggability, mouse-only. Three things are its own.
//
// ⚠️ 1. THE LEGAL TARGETS ARE A GROUP, NOT A LIST. The Notes section is several groups and STEP
// NOTES is itself ordered by step number, so a note may only move among the notes that share its
// group key. The rule is draftReorder's; what lives here is only which ROWS on screen that is.
// ⚠️ 2. A DROP OUTSIDE THAT SET IS NOT PREVENTED, which is how it snaps back with nothing changed:
// without preventDefault on dragover no drop event fires at all, so there is no "refuse" branch to
// get wrong.
// ⚠️ 3. THE ROWS ARE KEYED BY NOTE ID, not by DOM index. A note's id survives a repaint and a
// position does not, and repaintNotes rewrites the whole host on every held write.
let noteDragFrom = null;                                  // the dragged note's id, as a string

// The rows a note may be dropped among: every Edit-mode note row whose group key matches its own.
function noteDropRowEls(id) {
  const by = new Map(noteRows().map((n) => [String(n.id), n]));
  const me = by.get(String(id));
  if (!me) return [];
  // noteRows() resolved these already, so noteGroupKey is being handed the rows the page drew.
  const key = noteGroupKey(me, NOTE_KINDS.kinds);
  return [...document.querySelectorAll(".ie-note-block .ie-noterow")]
    .filter((el) => {
      const n = by.get(String(el.dataset.noteRow));
      return n && noteGroupKey(n, NOTE_KINDS.kinds) === key;
    });
}

function clearNoteDropBar() {
  document.querySelectorAll(".ie-note-block .drop-bar").forEach((el) => el.remove());
}

function noteDragStart(e) {
  const row = e.target.closest(".ie-note-block .ie-noterow");
  if (!row || !noteHeld()) return;
  noteDragFrom = row.dataset.noteRow;
  try { e.dataTransfer.setData("text/plain", String(noteDragFrom)); e.dataTransfer.effectAllowed = "move"; } catch (_) {}
  const n = noteRows().find((x) => String(x.id) === String(noteDragFrom));
  // The SAME label rule a step's pill uses, because a note is a paragraph too — it carries an
  // identifying prefix rather than a name. Fed the DISPLAY text, so a stripped label is not shown.
  setDragPill(e, stepPillLabel({ text: n ? displayText(n, NOTE_KINDS.kinds) : "" }));
  requestAnimationFrame(() => row.classList.add("ghost-origin"));   // deferred for C1's reason
}

// Paint only — never re-render here, for the reason the other two lists give.
function noteDragOver(e) {
  if (noteDragFrom == null) return;
  const row = e.target.closest(".ie-note-block .ie-noterow");
  const rows = noteDropRowEls(noteDragFrom);
  const at = row ? rows.indexOf(row) : -1;
  if (at < 0) { clearNoteDropBar(); return; }              // another group: no bar, and no drop
  e.preventDefault();                                      // required, or no drop event fires
  const from = rows.findIndex((r) => r.dataset.noteRow === String(noteDragFrom));
  paintDropBar(row.parentElement, rows,
               dropBeforeIndex(rows.map((r) => r.getBoundingClientRect()), e.clientY, from),
               { tag: "div", afterLast: true });
}

function noteDrop(e) {
  if (noteDragFrom == null) return;
  const rows = noteDropRowEls(noteDragFrom);
  const id = noteDragFrom;
  noteDragFrom = null;
  if (!rows.length) return;
  e.preventDefault();
  const before = beforeIndexFromBar(rows[0].parentElement, rows);
  clearRowDragArtifacts();
  if (before === undefined) return;                        // no bar was painted: nothing to apply
  // ⚠️ THE DRAFT'S RAW ROWS AND THE STEPS THEY ARE READ AGAINST, which is what draftReorder needs
  //    to work out the same groups the page just drew. Handing it view.draft.notes alone made it
  //    read a stale step_no: a note added this session was refused a drop the page offered, and a
  //    note relinked this session could be dropped into a group the page said was closed.
  const next = draftReorder(view.draft.notes, currentSteps(), NOTE_KINDS.kinds, id,
                            before == null ? null : rows[before].dataset.noteRow);
  if (next) holdNotes(next); else repaintNotes();          // refused: put the ghost row back
}

function noteDragEnd() {
  noteDragFrom = null;
  clearRowDragArtifacts();
}

// The steps' equivalent of rerenderEditIngredients — but it must also honour the island invariant
// (step-editor.js:8-12): each step editor's onUpdate closure CAPTURED its index at mount, so after any
// structural change to draft.steps the surviving editors would write to the WRONG index. Hence the
// full cycle, in this order: destroy -> re-render #steps-list with FRESH data-i -> re-mount. Scoped to
// #steps-list so the ingredient editors are never disturbed. Cost: caret + per-step undo history are
// lost (text is already flushed to the draft by onUpdate on every keystroke, so nothing typed is).
function rerenderEditSteps() {
  const el = document.getElementById("steps-list");
  if (!el || !view || !view.editMode) return;
  try { destroyStepEditors(); } catch (e) { console.error("destroyStepEditors failed", e); }
  el.innerHTML = view.draft.steps.map(renderStepEditHost).join("");
  try { mountStepEditors(view.draft, onStepInput); } catch (e) { console.error("mountStepEditors failed", e); }
}
// Mirrors removeIngredient (splice -> markDirty -> re-render), then places the caret in the step that
// took the deleted one's place — a heading (or an emptied list) simply gets no focus.
function removeStep(i) {
  const arr = view.draft.steps;
  if (!arr || !arr[i]) return;
  arr.splice(i, 1);
  markDirty(); rerenderEditSteps();
  const f = focusIndexAfterRemove(i, arr.length);
  if (f != null) focusStepEditor(f);
}
// The step mirror of addIngredient (insert -> markDirty -> re-render -> focus the new row). Two things
// differ, both forced by the island invariant: the re-render MUST be the full destroy/re-mount cycle
// (a bare innerHTML swap orphans every editor), and the caret is placed with focusStepEditor because a
// ProseMirror instance can't be focused via DOM .focus(). The inserted row carries exactly the fields
// the three readers use — renderStepEditHost, mountStepEditors, stepToPayload all read is_heading + text.
// A new step is empty by definition, so saving without typing drops it again (nonEmptySteps): the same
// contract as clearing an existing step's text, and it leaves the saved content byte-identical.
// B generalised this the same way as addIngredient: `at` omitted means the end, so the adder below the
// list is unchanged. ⚠️ A MID-LIST insert is exactly the case the island invariant exists for — every
// editor at or after `at` shifts index, and their onUpdate closures captured the OLD one at mount, so
// without the full rerenderEditSteps cycle typing into a surviving step would silently write its text
// into a DIFFERENT step. Never replace this with a bare splice + innerHTML.
function addStep(at, isHeading) {
  const arr = view.draft.steps;
  const at_ = at == null ? arr.length : at;
  arr.splice(at_, 0, { id: null, is_heading: isHeading ? 1 : 0, text: "" });   // id: null — never saved yet
  markDirty(); rerenderEditSteps();
  // A heading row is a plain <input>, not a TipTap island, so focusStepEditor can't reach it — it looks
  // for a .step-editor-host that a heading never renders. `at` stays FIRST in the signature so both
  // existing call sites (the end-of-list adder's addStep(), the menu's addStep(at)) are untouched.
  if (isHeading) focusStepHeadingField(at_); else focusStepEditor(at_);
}
// The step mirror of focusIngField, for the one step row type that is an ordinary form field.
function focusStepHeadingField(i) {
  const el = document.querySelector(`[data-inline-edit-step="heading"][data-i="${i}"]`);
  if (el) { el.focus(); if (el.select) el.select(); }
}
// The step twin of toggleIngredientHeading, and it goes through the full rerenderEditSteps cycle
// for the reason addStep's note gives: a step row is a TipTap island, so changing what a row IS
// without destroying and re-mounting would leave the editor of the old shape attached to the new one
// and the next keystroke would write into a row that no longer exists.
function toggleStepHeading(i) {
  toggleStepType(view.draft.steps[i]);
  markDirty(); rerenderEditSteps();
  if (view.draft.steps[i].is_heading) focusStepHeadingField(i); else focusStepEditor(i);
}
// One item, not two: a heading is a section or a subheading and nothing else, so the menu names the
// state it would move to, exactly as Convert to heading / Convert to ingredient does.
function toggleStepHeadingLevel(i) {
  const row = view.draft.steps[i];
  setStepLevel(row, stepLevel(row) === 2 ? 1 : 2);
  markDirty(); rerenderEditSteps();
  focusStepHeadingField(i);
}
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
    <span class="inline-editing-label">${view.importUnconfirmed ? "Imported" : "Editing"}</span>
    ${view.importUnconfirmed
      ? `<span class="inline-note">Fix anything the import got wrong — corrections now aren't tracked as changes. Edits after you save are.</span>`
      : ""}
    <span class="inline-dirty"${view.dirty ? "" : " hidden"}>• Unsaved changes</span>
    <span class="inline-error" hidden></span>
    <button class="btn sm" data-inline-edit-save>Save changes</button>
    <button class="btn ghost sm" data-inline-edit-cancel>Cancel</button>
  </div>`;
}

function enterEditMode() {
  // BOTH gates, mirroring update_recipe: the tier must permit editing AND you must own it. The Edit
  // button is already is_mine-gated, so this is the belt-and-braces path (keyboard/programmatic entry).
  if (!view || !view.data.is_editable || !view.data.is_mine || view.editMode) return;
  // ⚠️ THE CLONE WAITS FOR ANY NOTE WRITE THE SAME CLICK FIRED. See noteApi. Without this the draft
  //    is a copy of the list as it was BEFORE the save that is still in the air, and "Save changes"
  //    writes that stale list back over it.
  if (noteWriteInFlight()) { noteSettled.then(enterEditMode); return; }
  // ⚠️ AND THE NOTE STATE DOES NOT CROSS THE BOUNDARY. An open editor, a draft, a filter and above
  //    all the six-second "Saved · Undo" and "Deleted · Undo" offers belong to the view they were
  //    made in: the undo toast is drawn by Edit mode's block too, and its two shapes are not
  //    interchangeable, so a reading-view delete undone inside Edit mode restored a blank row while
  //    the real one was already gone from the database.
  closeNoteEditors();
  noteState.undo = null;
  noteState.savedId = null;
  noteState.savedBefore = null;
  noteState.savedNew = false;
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
    mountStepEditors(view.draft, onStepInput);
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
  view.importUnconfirmed = false;   // leaving the editor ends the pre-confirm window
  paintRecipe();
}

// First buffer mutation flips the "unsaved" indicator — WITHOUT re-rendering (keeps input focus/caret).
function markDirty() {
  if (!view || !view.editMode || view.dirty) return;
  view.dirty = true;
  const ind = document.querySelector(".inline-dirty");
  if (ind) ind.hidden = false;
}

// Convert the draft (DB row shape) back into the PUT payload shape write_recipe_rows expects.
// Both builders now live in ./save-payload.js so the round-trip fixture can be captured from the
// real thing rather than from a hand-written copy. The wire format is unchanged.
function draftPayload() {
  const r = view.draft.recipe;
  const t = (v) => (v == null ? "" : String(v).trim());
  const oneLine = (v) => t(v).replace(/[\r\n]+/g, " ");   // .ie-line fields wrap visually but stay one logical line
  return {
    name: oneLine(r.name), author: oneLine(r.author), source_url: t(r.source_url), category: t(r.category),
    servings: t(r.servings), prep_time: t(r.prep_time), cook_time: t(r.cook_time), total_time: t(r.total_time),
    // ⚠️ `notes` IS A LIST OF ROWS NOW, BUILT BELOW, AND IT IS NOT A HEADER FIELD. recipes.notes is a
    //    derived copy the server rebuilds from those rows, so sending the old string as well would
    //    fight write_notes for the same column.
    image: t(r.image), descr: t(r.descr),
    ingredients: nonEmptyRows(view.draft.ingredients).map(ingToPayload),   // drop blank rows the user left WIP
    steps: nonEmptySteps(view.draft.steps).map(stepToPayload),             // ditto — CLEARING a step's text deletes it
    // A row whose text box is empty is one the user left WIP, exactly like a blank ingredient.
    waits: (view.draft.waits || []).filter((w) => t(w.label)).map((w) => ({
      kind: t(w.kind) || "other", label: t(w.label), ext_label: t(w.ext_label) || null,
      when_kind: t(w.when_kind) || "always", when_label: t(w.when_label) || null,
      // ⚠️ ROUND-TRIPPED VERBATIM. The server keeps a check it is given and only reads a fresh one
      //    when this is null, which the step picker below is the only thing that does.
      step_id: w.step_id == null ? null : +w.step_id,
      alongside_step_id: w.alongside_step_id == null ? null : +w.alongside_step_id,
      ext_step_id: w.ext_step_id == null ? null : +w.ext_step_id })),
    storage: (view.draft.storage || []).filter((x) => t(x.label)).map((x) => ({
      where_kept: t(x.where_kept) || "fridge", applies_to: t(x.applies_to) || null, label: t(x.label) })),
    // ⚠️ `notes` IS SENT AGAIN, AND IT IS THE DRAFT'S LIST RATHER THAN THE DATABASE'S. Edit mode
    //    holds note changes until Save changes, so Cancel discards them like every other field on
    //    that screen. The race this key was removed to avoid is gone with it: nothing in Edit mode
    //    writes a note through its own endpoint any more, so there is no second writer to collide
    //    with. On the recipe page notes still save as you type, and that path never builds a
    //    draftPayload.
    //    ⚠️ write_notes MATCHES AND UPDATES IN PLACE, by wording first and then by order, so a
    //    save that changed no note writes the same rows back with the same ids. An explicit []
    //    still clears the list, which is how the editor empties it.
    notes: notesPayload(view.draft.notes),
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
  // NB: no toggle-ing branch — A stage 2 moved the heading toggle into the row ⋯ menu, which
  // dispatches through handleRowMenuAction. toggleIngredientHeading() itself is unchanged.
  const unl = e.target.closest("[data-inline-edit-unlink]");
  if (unl) { unlinkIngredient(Number(unl.dataset.i)); return true; }
  const ani = e.target.closest("[data-inline-edit-addnote]");
  if (ani) { addNote(Number(ani.dataset.i)); return true; }
  // Editor parity — step structural actions (re-render + re-mount via rerenderEditSteps)
  if (e.target.closest("[data-inline-edit-add-step]")) { addStep(); return true; }
  // NB: no rm-step branch — A stage 2 moved step delete into the row ⋯ menu (a .danger item), which
  // dispatches through handleRowMenuAction. removeStep() itself is unchanged.
  return false;
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

// U5 — import a URL. Mirrors doCopy exactly: POST, then navigate to the id the server hands back.
// The ONE addition is importOpening, which asks renderRecipe to land in EDIT mode rather than reading:
// an import arrives with parse errors to fix, so the editor IS the destination, not a place to go next.
let importOpening = null;    // slug to open straight into edit mode (consumed by renderRecipe)

async function doImport(url) {
  const res = await sendJSON("POST", "/api/import/commit", { url });
  if (!res.ok || !res.data || !res.data.id) {
    // The server's own wording is shown, never replaced: every refusal carries a reason written for a
    // person — "the site refused the request (HTTP 403)", "the URL returned application/pdf, not a web
    // page", and U2's composed reader text "json-ld: found Article and ImageObject, not Recipe". That
    // composition exists so the user learns WHICH layer declined and what it saw; paraphrasing it here
    // would throw away the only part that tells them whether to retry, try another link, or type it in.
    //
    // The generic string is a LAST RESORT and now carries the status, because it can only be reached
    // when the response was not our JSON at all — sendJSON sets data=null on any body it can't parse.
    // In practice that means an HTML error page from the stack rather than a refusal from this route:
    // a 404 (the app server is running older code than the browser — restart it), a 500 (an unhandled
    // exception), or a proxy/network failure. Naming the status is what separates those from "the site
    // said no", which is exactly the distinction that was missing when a stale server read as a bad URL.
    // Mirrors onSaveForm's "Couldn't save (HTTP nnn)." rather than inventing a second convention.
    alert((res.data && res.data.error) || `Couldn't import that URL (HTTP ${res.status}).`);
    return;
  }
  if (res.data.duplicate) {
    // A WARNING, never a block: the import already happened. Naming the twin is what makes it useful.
    alert(`Heads up — you already have “${res.data.duplicate.name}” from this address. `
          + `This is a second copy; delete it with Cancel if you didn't mean to.`);
  }
  importOpening = res.data.id;
  location.hash = "#/recipe/" + encodeURIComponent(res.data.id);
}

// The entry point: ask for a URL, then import it. prompt() rather than a bespoke modal — the app
// already uses the native confirm() for the dirty-nav guard and alert() for copy/import failures, so
// this matches what is here instead of introducing a dialog system for one field.
function promptImport() {
  const url = (prompt("Paste a recipe URL to import:") || "").trim();
  if (url) doImport(url);
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

// ⚠️ THIS FORM SHOWS THE STORED TEXT, MARKUP AND ALL, AND THAT IS THE RIGHT ANSWER HERE. It is the
// source-editing form (#/new and #/edit/<slug>), whose step textarea already shows [[garlic]] and
// whose placeholder tells you to write it. It also reads EVERY field's value on submit, so a
// display-only heading value would be written straight back and the link would be gone. The inline
// editor is the one that renders a heading as a heading, and that is where showLinksAsWords belongs.
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
  if (x.is_heading) return ingRow({ type: "heading", heading: headingText(x) });
  if (x.ingredient_id) return ingRow({ type: "line", qty: x.qty, link: x.ingredient_id, text: x.label || x.raw_text, note: x.note });
  return ingRow({ type: "line", qty: x.qty, text: x.label || x.raw_text });
}
function stepToRow(x) {
  if (x.is_heading) return stepRow({ type: "heading", heading: x.text, level: stepLevel(x) });
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
    // The OTHER refusal, kept separate from the tier one above so the reason is honest: this recipe is
    // editable in principle, it just isn't yours. Copy is the way to get your own version of it.
    if (!data.is_mine) {
      app.innerHTML = `
        <a class="back" href="#/recipe/${encodeURIComponent(slug)}">← Back to recipe</a>
        <div class="notice">
          <h2>This recipe isn't yours</h2>
          <p>“${esc(data.recipe.name)}” belongs to someone else, so it can't be edited here. <strong>Copy</strong> it from the recipe page to get your own version to change.</p>
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
        ${mode === "create" ? `<label class="field span2"><span>Note (optional)</span><textarea id="f-notes" rows="2"></textarea></label>` : ""}
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

// ⚠️ THIS FORM MAY NOT SPEAK ABOUT NOTES WHEN IT IS EDITING, AND THAT IS A DATA-LOSS RULE RATHER
//    than a tidy-up. On the PUT, an ABSENT notes key means keep and an EMPTY STRING means replace
//    the list with nothing. The textarea used to pre-fill from recipe.notes, the derived copy, so
//    the save round-tripped. Migration 063 dropped that column, `pre.notes` became undefined, and
//    this form then sent notes:"" on every save: measured on a fixture, a recipe with two note
//    rows answered 200 and came back with zero. There is no note editor on this form, so the only
//    safe thing it can say about a recipe's notes is nothing. Edit mode is the real editor.
//    The field stays for CREATE, where a bare string is still the documented way to start a recipe
//    off with a note and there is nothing to destroy.
function gatherPayload(mode) {
  const val = (id) => (document.getElementById(id)?.value || "").trim();
  const payload = {
    name: val("f-name"), author: val("f-author"), category: val("f-category"),
    servings: val("f-servings"), prep_time: val("f-prep"), cook_time: val("f-cook"),
    total_time: val("f-total"), image: val("f-image"), descr: val("f-descr"),
    ingredients: [], steps: [],
    is_test: !!document.getElementById("f-test")?.checked,   // create-only; PUT ignores it
  };
  if (mode === "create") payload.notes = val("f-notes");

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
  const payload = gatherPayload(mode);
  if (!payload.name) { showFormError("Please give the recipe a name."); return; }
  const res = mode === "create"
    ? await sendJSON("POST", "/api/recipes", payload)
    : await sendJSON("PUT", "/api/recipes/" + encodeURIComponent(slug), payload);
  if (res.ok) location.hash = "#/recipe/" + encodeURIComponent(res.data.id);
  else showFormError((res.data && res.data.error) || ("Couldn't save (HTTP " + res.status + ")."));
}

/* ---------- error state ---------- */
function showError(err) {
  if (err && err.message === "__auth__") return;   // 401 already dropped us to the login view — no error card
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
  // Empty is the caller's problem now: openPanel hides the whole block rather than printing a
  // sentence under a heading. See static/panel-blocks.js for why the year-round line went.
  if (!months || !months.length) return "";
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
  panel.querySelector(".used-list").innerHTML = used
    .map((u) => `<li><button data-recipe="${esc(u.id)}">${esc(u.name)}</button></li>`)
    .join("");

  // No data, no block — the rule used-block always followed, now applied to all four. A promoted
  // ingredient has none of season/regions/pairs, so its drawer is a name and its recipes.
  const show = panelBlocks(item);
  for (const [key, sel] of [["season", ".season-block"], ["regions", ".regions-block"],
                            ["pairs", ".pairs-block"], ["used", ".used-block"]]) {
    panel.querySelector(sel).style.display = show[key] ? "" : "none";
  }

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
let bdRating = null;          // the half-step verdict held while the log-cook box is open
let bdCal = null;             // the live calendar controller
let bdStaged = [];            // 3b-ii: [{file, url}] photos staged client-side (object-URL previews) before submit
let bdSubmitter = null;       // 3b-ii: the pure log-once-then-attach orchestrator (holds the cook id across retries)
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
    // Pad trailing empties so the grid is ALWAYS 6 week-rows (42 day-cells) — every month occupies the same
    // height, so changing months never resizes the calendar/modal (the "Log this cook" button stays put).
    for (let i = startDow + daysInMonth; i < 42; i++) cells += `<button class="bd-day empty" tabindex="-1" disabled></button>`;
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

// 3b-ii staging: render the backdate modal's add-a-photo box from bdStaged — the REST invite when empty,
// else the thumbnail grid (each with a × client-only remove) + a ＋ add-more tile. Object-URL previews.
function renderBdPhoto() {
  const box = backdateModal.querySelector("[data-bd-photo]");
  if (!box) return;
  if (!bdStaged.length) {
    box.className = "bd-photo zone";
    box.innerHTML = '<span class="bd-photo-ico">&oplus;</span><span class="bd-photo-lbl">add a photo</span><span class="bd-photo-cap">drag or click · optional</span>';
    return;
  }
  box.className = "bd-photo has-thumbs";
  const thumbs = bdStaged.map((s, i) =>
    `<span class="bd-thumb"><img src="${s.url}" alt="" onerror="this.style.opacity=.3"><button class="x" data-bd-remove="${i}" type="button" aria-label="Remove photo">&times;</button></span>`
  ).join("");
  const n = bdStaged.length;
  box.innerHTML = `<div class="bd-thumbs">${thumbs}<button class="bd-thumb-add" data-bd-add type="button" aria-label="Add more photos">＋</button></div>` +
    `<span class="bd-photo-cap">${n} photo${n > 1 ? "s" : ""} · drag or click to add</span>`;
}

// Stage picked/dropped files client-side (NO upload — the cook doesn't exist yet). Each VALID image gets an
// object-URL preview; a non-image is REJECTED at staging (isStageableImage mirrors the server allowlist) so
// it never becomes a broken thumbnail or a doomed upload — a brief nudge explains. The !file case (Photos
// hands a reference) is a graceful no-op.
function bdStageFiles(files) {
  const list = Array.from(files || []).filter(Boolean);
  let added = 0, rejected = 0;
  for (const f of list) {
    if (!isStageableImage(f)) { rejected++; continue; }
    bdStaged.push({ file: f, url: URL.createObjectURL(f) });
    added++;
  }
  if (added) renderBdPhoto();
  const errEl = backdateModal.querySelector("[data-bd-error]");
  if (errEl) {
    if (rejected) errEl.textContent = rejected === 1
      ? "That's not an image — JPEG, PNG, WebP, or HEIC only."
      : `${rejected} files skipped — images only (JPEG, PNG, WebP, HEIC).`;
    else if (added) errEl.textContent = "";   // a clean stage clears any prior nudge
  }
}

// Wire the add-a-photo box's pick/drop/remove ONCE (the box is a persistent DOM node; renderBdPhoto only
// swaps its innerHTML, so delegated listeners on the box survive). Picking stages; it never uploads here.
function wireBdPhoto() {
  const box = backdateModal.querySelector("[data-bd-photo]");
  const input = backdateModal.querySelector(".bd-photo-input");
  if (!box || !input) return;
  box.addEventListener("click", (e) => {
    const rm = e.target.closest("[data-bd-remove]");
    if (rm) {                                   // × : client-only unstage (drop the file, free its preview) — NOT a server delete
      const i = Number(rm.dataset.bdRemove), s = bdStaged[i];
      if (s) { URL.revokeObjectURL(s.url); bdStaged.splice(i, 1); renderBdPhoto(); }
      return;
    }
    if (e.target.closest("[data-bd-add]") || e.target.closest(".bd-photo.zone")) input.click();
  });
  box.addEventListener("keydown", (e) => {      // the rest invite is a role=button; Enter/Space opens the picker
    if ((e.key === "Enter" || e.key === " ") && !bdStaged.length) { e.preventDefault(); input.click(); }
  });
  input.addEventListener("change", () => { bdStageFiles(input.files); input.value = ""; });   // clear -> re-pick same files re-fires
  ["dragenter", "dragover"].forEach((ev) => box.addEventListener(ev, (e) => { e.preventDefault(); box.classList.add("dragover"); }));
  ["dragleave", "dragend"].forEach((ev) => box.addEventListener(ev, (e) => { if (!box.contains(e.relatedTarget)) box.classList.remove("dragover"); }));
  box.addEventListener("drop", (e) => { e.preventDefault(); box.classList.remove("dragover"); bdStageFiles(e.dataTransfer && e.dataTransfer.files); });
}

// Discard every staged file + free its object URL, and reset the box to the rest invite (called on open + close).
function bdClearStaged() {
  bdStaged.forEach((s) => URL.revokeObjectURL(s.url));
  bdStaged = [];
  renderBdPhoto();
}

// The log-cook -> attach-staged-photos orchestrator (pure core in backdate-submit.js; the DOM/network live
// in these injected callbacks). logCook creates the cook ONCE (and patches stats in place, as the flow does
// today); attachPhotos POSTs each staged photo to the album endpoint WITH the held cook_log_id (so they're
// DATED), best-effort via Promise.allSettled, returning the subset that failed (kept staged for retry).
function bdGetSubmitter() {
  if (bdSubmitter) return bdSubmitter;
  bdSubmitter = makeBackdateSubmit({
    logCook: async () => {
      const iso = bdCal ? bdCal.getSelected() : null;
      // Items 11 + 12: the verdict and the note are part of THIS cooking, so they go in the same
      // write rather than a follow-up PATCH that could half-succeed.
      const capEl = backdateModal.querySelector("[data-bd-caption]");
      const body = { date: iso, rating: bdRating, caption: capEl ? capEl.value : null };
      const { ok, data } = await sendJSON("POST", `/api/recipes/${backdateRid}/cooked`, body);
      if (!ok) return { ok: false, error: (data && data.error) || "Could not log that date." };
      if (view) view.undoneCook = null;                    // a fresh log ends any redo window
      if (view && view.data) view.data.stats = data;
      if (backdateStats) { backdateStats.innerHTML = statsInner(data); setCookCount(app, data.cook_count); }   // patch stats now (cook IS logged)
      return { ok: true, cookId: data.cook_log_id };       // READ the id 2b returns (the client used to discard it)
    },
    attachPhotos: async (cookId, staged) => {
      const post = (s) => {
        const fd = new FormData();
        fd.append("image", s.file);
        fd.append("cook_log_id", String(cookId));          // DATED -> attach to the just-logged cook
        return fetch(`/api/recipes/${encodeURIComponent(backdateRid)}/photos`,
                     { method: "POST", credentials: "same-origin", body: fd }).then((r) => r.status);
      };
      const results = await Promise.allSettled(staged.map(post));   // best-effort batch (3b-i)
      if (results.some((r) => r.status === "fulfilled" && r.value === 401)) { showAuth(); throw new Error("__auth__"); }
      const failed = [];
      results.forEach((r, i) => {
        const st = r.status === "fulfilled" ? r.value : 0;
        if (st >= 200 && st < 300) URL.revokeObjectURL(staged[i].url);   // succeeded -> free its preview
        else failed.push(staged[i]);                       // failed -> keep staged (with its preview) for retry
      });
      return failed;
    },
  });
  return bdSubmitter;
}

// Repaint the log-cook box's stars from bdRating, and show "clear" only once there is one to clear.
function bdPaintRating() {
  const holder = backdateModal.querySelector("[data-bd-stars]");
  if (!holder) return;
  holder.innerHTML = starsInputHTML(bdRating);
  const clear = backdateModal.querySelector("[data-bd-rate-clear]");
  if (clear) clear.toggleAttribute("hidden", bdRating == null);
}

function openBackdate(rid, statsEl, trigger) {
  backdateRid = rid;
  backdateStats = statsEl;
  backdateTrigger = trigger || null;
  bdClearStaged();                              // fresh add-a-photo area (rest invite)
  bdRating = null;                              // a fresh box starts unrated, never the last cook's value
  bdPaintRating();
  const capBox = backdateModal.querySelector("[data-bd-caption]");
  if (capBox) capBox.value = "";
  if (bdSubmitter) bdSubmitter.reset();         // fresh cook next submit — no held id from a prior open
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
  bdClearStaged();                              // discard any un-logged staged previews (free their URLs)
  if (bdSubmitter) bdSubmitter.reset();         // next open logs a fresh cook (drop any held id)
  if (backdateTrigger && document.contains(backdateTrigger)) backdateTrigger.focus();
}

// 3b-ii: single-button submit — log the cook, then attach the staged photos to it (dated), holding the
// modal open until BOTH succeed. The retry-holds-the-id guard lives in the orchestrator (backdate-submit.js):
// once the cook is logged its id is held, so a retry re-attaches to the SAME cook and never re-logs it.
// Photoless path is unchanged (log + close). Full success repaints so the album shows the new dated photos.
async function submitBackdate() {
  const errEl = backdateModal.querySelector("[data-bd-error]");
  const logBtn = backdateModal.querySelector("[data-backdate-log]");
  const iso = bdCal ? bdCal.getSelected() : null;
  if (!iso) { errEl.textContent = "Pick or type a date first."; return; }
  errEl.textContent = "";
  logBtn.disabled = true;                        // guard the async window against a double-submit
  let res;
  try {
    res = await bdGetSubmitter().run(bdStaged);
  } catch (_) {                                  // auth bail (showAuth already fired) -> stop quietly
    return;
  } finally {
    logBtn.disabled = false;
  }
  if (res.status === "cook-failed") { errEl.textContent = res.error; return; }
  if (res.status === "photos-failed") {          // cook logged (id HELD); keep the failed ones staged for retry
    bdStaged = res.failed;
    renderBdPhoto();
    const n = res.failed.length;
    errEl.textContent = `Cook logged — ${n} photo${n > 1 ? "s" : ""} didn't upload. Try again.`;
    return;                                       // HOLD the modal open; retry reuses the held cook id (no re-log)
  }
  // res.status === "done": cook logged + all staged photos attached (or none were staged)
  const hadPhotos = bdStaged.length > 0;
  bdStaged = [];                                  // succeeded photos' URLs were freed in attachPhotos
  const statsEl = backdateStats, rid = backdateRid;
  closeBackdate();
  if (hadPhotos) renderRecipe(rid);              // full repaint AFTER attach -> the album shows the new dated photos
  else statsEl?.querySelector("[data-backdate-open]")?.focus();   // photoless: stats already patched -> just restore focus
}

/* ---------- the step note popover ---------- */
// ⚠️ ONE CONTROL, FOUR WAYS IN, AND THEY ARE THE SAME CONTROL. The marker is a real <button>, so it
// is in the tab order with no tabindex and a screen reader announces it as a button. Hover and
// focus open it, which means a keyboard user gets what a mouse user gets without a second code
// path. Tap opens it on a phone, where hover does not exist. Escape closes it and puts focus back.
// ⚠️ aria-expanded IS THE STATE AND `hidden` IS THE RENDERING, and both are set together. Setting
// only the attribute leaves a screen reader announcing a collapsed popover whose text is still in
// the accessibility tree.
//
// ⚠️ IT OPENS FROM JS NOW, NOT FROM A CSS :has(:hover), AND THAT IS THE WHOLE FIX. The shipped rule
// was `.step-body:has(.step-note-marker:hover) .step-note-pop { display: block }`, so the popover
// existed only while the pointer was on the TAG: move toward it and it was gone before you arrived,
// which made everything inside it unreachable. The tag and the popover are one hover region here,
// with a delay on the way out, and a click pins it until a click elsewhere or Escape.
// ⚠️ AND OPENING ONE DOES NOT REPAINT THE PAGE. A repaint replaces the element the pointer is
// standing on, so the browser fires pointerout at a node that no longer exists and the popover
// flickers shut on its way open. Measured while building the :8003 preview. Only a change to a NOTE
// repaints; opening, closing and pinning move attributes on the DOM that is already there.
// ⚠️ ONE HOLD FOR THE WHOLE STEP, NOT ONE PER CONTROL. The step's words, its "+ note", its tag and
// its popover are one area as far as the pointer is concerned, and the gaps between them are where
// the controls actually live: "+ note" hangs past the end of the last line and the popover sits
// under the step. Leaving any one of them used to hide the very thing the cook was reaching for.
// The timing rule is hover-hold.js, which is pure and tested at exact milliseconds.
const hold = makeHold(HOLD_MS);
let popOpen = null;        // the step id whose popover is showing
let popPinned = null;      // ...and whether a click is holding it there
let popTimer = null;
// ⚠️ ESCAPE PUTS FOCUS BACK ON THE TAG, AND FOCUS OPENS THE POPOVER. Without this the two rules
// fought: Escape closed it, focus() fired synchronously, the focusin handler opened it again, and a
// keyboard user could never shut it at all. Measured on :8002 — the popover was still on screen
// after Escape, every time the page had real focus.
let popIgnoreFocus = false;

function popFor(stepId) { return document.getElementById(`note-pop-${stepId}`); }

// The step id an element belongs to, by any of the routes into the area: the step row itself, its
// popover, or the new-note box that opens under it.
function stepAreaOf(el) {
  if (!el || !el.closest) return null;
  const li = el.closest("li.step");
  if (li) {
    const probe = li.querySelector("[data-step-tap], .step-note-marker, [data-add-note]");
    if (!probe) return null;
    return probe.dataset.stepTap || probe.dataset.stepNote || probe.dataset.addNote || null;
  }
  const pop = el.closest(".step-note-pop");
  if (pop) return pop.id.replace("note-pop-", "");
  // ⚠️ THE NEW-NOTE PANEL IS READ OFF ITS PLACE, NOT OFF ITS OWN ATTRIBUTE. It is the ordinary
  //    editor now and carries data-note-place="new:<where>"; the [data-new-note] the bare box used
  //    to carry is gone. Reaching here at all means the panel is not inside an li.step, which the
  //    Notes section's own adder is not.
  const box = el.closest('[data-note-place^="new:"]');
  if (box) {
    const where = String(box.dataset.notePlace).slice("new:".length);
    return where === "general" ? null : where;
  }
  return null;
}

// ⚠️ SHOWING AND HIDING MOVE CLASSES, THEY NEVER REPAINT. A repaint replaces the element the pointer
// is standing on, so the browser fires pointerout at a node that no longer exists and the control
// flickers shut on its way open. Measured while building the :8003 preview.
function syncStepNotes() {
  // ⚠️ A POPOVER CAN GO AWAY UNDER AN OPEN ONE. Deleting a step's last note takes the tag and the
  //    popover with it, and a popOpen left pointing at a node that no longer exists would refuse
  //    every later hover on the grounds that it was already open.
  if (popOpen != null && !popFor(popOpen)) { popOpen = null; popPinned = null; }
  const area = hold.held();
  document.querySelectorAll("li.step").forEach((li) => {
    const sid = stepAreaOf(li);
    li.classList.toggle("hover-hold", sid != null && String(area) === String(sid));
  });
  document.querySelectorAll(".step-note-pop").forEach((pop) => {
    const sid = pop.id.replace("note-pop-", "");
    const open = String(popOpen) === sid;
    pop.hidden = !open;
    pop.classList.toggle("is-pinned", open && String(popPinned) === sid);
    const btn = document.querySelector(`[aria-controls="${pop.id}"]`);
    if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
  });
}

// The hold decides WHEN; this arms the clock that asks it.
function armHold() {
  clearTimeout(popTimer);
  const due = hold.dueAt();
  if (due == null) return;
  popTimer = setTimeout(() => {
    // ⚠️ A CONTROL BEING TYPED IN NEVER GOES AWAY ON A TIMER. The cook's pointer leaves the box the
    //    moment they look at the keyboard.
    if (noteState.newOn != null) { armHold(); return; }
    if (noteState.editingId != null && String(noteState.editingPlace).startsWith("pop:")) {
      armHold(); return;
    }
    hold.settle(Date.now());
    if (hold.held() == null && popPinned == null) popOpen = null;
    syncStepNotes();
  }, Math.max(0, due - Date.now()) + 10);
}

function openStepNote(stepId) {
  clearTimeout(popTimer);
  hold.enter(stepId, Date.now());
  popOpen = stepId;
  syncStepNotes();
}

function closeStepNotes({ force = false } = {}) {
  clearTimeout(popTimer);
  if (!force && popPinned != null) return;
  popOpen = null;
  popPinned = null;
  hold.clear();
  syncStepNotes();
}

document.addEventListener("pointerover", (e) => {
  const area = stepAreaOf(e.target);
  if (area == null) return;
  clearTimeout(popTimer);
  const was = hold.held();
  hold.enter(area, Date.now());
  // ⚠️ THE TAG OPENS THE POPOVER, THE STEP DOES NOT. A popover that opened on every step the pointer
  //    crossed would be a page that rearranges itself as you read it. Hovering the step reveals
  //    "+ note" and nothing more.
  const btn = e.target.closest && e.target.closest(".step-note-marker");
  if (btn) popOpen = btn.dataset.stepNote;
  else if (popOpen != null && String(popOpen) !== String(area) && popPinned == null) popOpen = null;
  if (was !== hold.held() || btn) syncStepNotes();
});

document.addEventListener("pointerout", (e) => {
  const from = stepAreaOf(e.target);
  if (from == null) return;
  // ⚠️ THE GAP IS NOT A DEPARTURE. relatedTarget is where the pointer is GOING, so a move from the
  //    step's last word to its own "+ note", or down into its popover, is not a leave at all. This
  //    is the whole bug: the control lives in the few pixels that belong to neither element.
  if (stepAreaOf(e.relatedTarget) === from) return;
  hold.leave(Date.now());
  armHold();
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || popOpen == null) return;
  if (noteState.editingId != null) return;     // the note editor's own Escape has the first word
  const btn = document.querySelector(`[data-step-note="${popOpen}"]`);
  closeStepNotes({ force: true });
  popIgnoreFocus = true;
  if (btn) btn.focus();        // Escape returns focus to where it came from, never to the document
  popIgnoreFocus = false;      // focus() fires its events synchronously, so the window is this line
});

// Focus opens it, which is the keyboard half of hover.
document.addEventListener("focusin", (e) => {
  const btn = e.target.closest && e.target.closest(".step-note-marker");
  if (btn) { if (!popIgnoreFocus) openStepNote(btn.dataset.stepNote); return; }
  // ⚠️ NOT WHEN FOCUS LANDS INSIDE THE POPOVER. It holds a "step N" link and the editor's own
  //    controls, all focusable the moment it is shown, so tabbing off the marker closed the very
  //    thing focus had just entered.
  if (stepAreaOf(e.target) == null) closeStepNotes();
});

/* ---------- the note component's behaviour ---------- */
// ⚠️ ONE SET OF HANDLERS FOR BOTH VIEWS. Reading view and Edit mode render the same component, so
// they get the same behaviour from the same code. The only thing that differs is how the page is
// repainted afterwards, and repaintNotes below is the one place that knows the difference.

// ⚠️ A REPAINT IN EDIT MODE MUST NOT CALL paintRecipe. The per-step TipTap editors are mounted once
// when Edit mode opens and a full repaint would orphan them (see the step-editor island invariant),
// so Edit mode rewrites only its own notes host. Reading view has no such constraint and repaints
// properly, which is what redraws a step's ⓘ when a note is added to it.
function repaintNotes() {
  if (view && view.editMode) {
    const host = document.querySelector(".ie-notes");
    if (host) host.innerHTML = ieNotesHTML(view.draft);
  } else {
    paintRecipe();
  }
  syncPickTargets();
  // ⚠️ THE POPOVER'S OPEN STATE LIVES IN JS AND THE PAGE WAS JUST REBUILT. Without this, editing a
  //    note inside a popover closed the popover on the first keystroke that repainted it.
  syncStepNotes();
  restoreNoteFocus();
}

// ⚠️ THE BOX GROWS TO THE NOTE, OR THE NOTE IS SIMPLY NOT THERE. A fixed three-line textarea with
// resize off clipped the corpus's long notes dead: all-butter-pie-crust's "Form a Pie Shell" is 447
// characters and the editor showed two and a half lines of it, with the rest reachable only by
// scrolling inside a box that gave no sign it could scroll. 23 of live's 177 notes are over 300
// characters. The height is set from the content on every repaint and on every keystroke.
function growNoteInput(el) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}

// ⚠️ THE CARET COMES BACK, OR EVERY SAVE WOULD FEEL LIKE A DISMISSAL. A repaint replaces the
// textarea, so the open editor is re-focused with the caret at the end of what was typed.
function restoreNoteFocus() {
  let el = null;
  // ⚠️ THE FILTER BOX FIRST, BECAUSE IT IS THE ONE HOLDING THE CARET. Every keystroke in it
  //    repaints the list, and restoring the note's textarea instead would move the caret out of
  //    the field on the first letter typed.
  if (noteState.stepMenuFor != null) {
    const find = document.querySelector(`[data-note-pick-find="${noteState.stepMenuFor}"]`);
    if (find) {
      find.focus();
      find.selectionStart = find.selectionEnd = find.value.length;
      const at = document.querySelector(`[data-note-pick-find="${noteState.stepMenuFor}"]`)
        .closest(".note-step-menu").querySelector(".pk-row.at");
      if (at) at.scrollIntoView({ block: "nearest" });
      return;
    }
  }
  if (noteState.editingId != null) {
    const row = document.querySelector(
      `.note-edit[data-note="${noteState.editingId}"][data-note-place="${noteState.editingPlace}"]`);
    // ⚠️ WHICHEVER FIELD HAD THE CARET, NOT ALWAYS THE TEXTAREA. This asked only for
    //    [data-note-input], and a repaint is reachable while the Title box has focus: flashSaved's
    //    six-second toast timeout calls repaintNotes() unconditionally and closeNoteEditors does
    //    not clear savedId. So saving note A, opening note B inside those six seconds and typing in
    //    B's Title box moved the caret to the end of B's TEXT at expiry, and the characters after
    //    that landed in the text draft, which the next save then wrote.
    //    noteState.focusField records which one was last touched, so the question is answered from
    //    what happened rather than from a default.
    //    ⚠️ AND THE NEW-NOTE PANEL NEEDS NO SECOND BRANCH. It is an open editor with
    //    editingId = NEW_NOTE_ID and place "new:<where>", so the selector above finds it. The
    //    branch that used to live here asked for [data-new-note-input], an attribute the bare box
    //    carried and the panel does not.
    const want = noteState.focusField === "title" ? "[data-note-title]" : "[data-note-input]";
    el = row && (row.querySelector(want) || row.querySelector("[data-note-input]"));
  }
  if (!el) return;
  growNoteInput(el);
  el.focus();
  el.selectionStart = el.selectionEnd = el.value.length;
}

const NOTE_TOAST_MS = 6000;

// ⚠️ 560px IS THE STYLESHEET'S PHONE BREAKPOINT AND IT IS READ, NOT RESTATED. .step-num-tap, the
// bottom sheet and this all turn at the same width, so a second number here would be a third
// opinion about what a phone is. matchMedia reads the same query the CSS does.
const PHONE_Q = "(max-width: 560px)";
function isPhone() {
  return typeof matchMedia === "function" && matchMedia(PHONE_Q).matches;
}

// ⚠️ THE STEP ROWS ARE MARKED BY WALKING THE DOM, NOT BY RE-RENDERING THEM. Edit mode mounts a
// TipTap editor into every step and paintRecipe cannot run without orphaning all of them, so
// "Pick on the page" would have worked in reading view only if it needed a repaint. #steps-list
// li.step is 1:1 with the ordinary steps in order, which is the mapping jumpToStep already relies
// on, so the id comes from the data rather than from an attribute the markup does not carry.
function syncPickTargets() {
  const on = noteState.pickingFor != null;
  document.body.classList.toggle("note-picking", on);
  const rows = document.querySelectorAll("#steps-list li.step");
  const ids = currentSteps().filter((x) => !x.is_heading).map((x) => x.id);
  rows.forEach((li, i) => {
    if (on && ids[i] != null) li.dataset.notePickStep = ids[i];
    else delete li.dataset.notePickStep;
  });
  let bar = document.querySelector(".note-pick-bar");
  if (!on) { if (bar) bar.remove(); return; }
  const html = pickBarHTML(noteState.pickingFor, esc, { phone: isPhone() });
  if (bar) bar.outerHTML = html;
  else document.body.insertAdjacentHTML("beforeend", html);
}

// Escape, or Cancel. On a pointer it goes back to the list, which is where the cook came from. On a
// phone the sheet was closed to make room for the method, so it goes all the way out.
function cancelPickOnPage(id) {
  noteState.pickingFor = null;
  noteState.stepMenuFor = isPhone() ? null : id;
  repaintNotes();
}

// ⚠️ EVERY NOTE ENDPOINT CALL IS TRACKED, BECAUSE ENTERING EDIT MODE CLONES THE LIST. The
//    dispatcher runs handleNoteAction before handleInlineEdit, and its click-away branch fires a
//    write and returns false, so one click on "✎ Edit" saved a note and then cloned view.data
//    synchronously, before the answer could land. The draft held the note's OLD words and the next
//    "Save changes" wrote them back over the new ones, with a 200 and no sign anything was wrong.
//    A note added that way was worse: the draft never gained it, so the save deleted its row.
//    Measured as a certainty rather than a race, because nothing awaits anything in that path.
let noteWrites = 0;
let noteSettled = Promise.resolve();

function noteApi(path, opts) {
  const call = fetch(`/api/recipes/${encodeURIComponent(view.slug)}${path}`, {
    method: opts.method, credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  }).then(async (r) => {
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  });
  noteWrites += 1;
  // ⚠️ THE CHAIN SWALLOWS THE FAILURE AND THE CALLER STILL SEES IT. noteSettled exists only to say
  //    "nothing is in flight"; every caller keeps its own .catch, and a rejection here would
  //    otherwise become an unhandled rejection as well as blocking the gate below for good.
  noteSettled = noteSettled
    .then(() => call.catch(() => {}))
    .then(() => { noteWrites -= 1; });
  return call;
}

// Whether a note write is still in the air. Edit mode may not clone the list while one is.
function noteWriteInFlight() { return noteWrites > 0; }

// ⚠️ THE SERVER'S LIST WINS. Every note route answers with the recipe's whole notes list, because a
// create or a move renumbers the others, and taking the server's answer rather than patching the
// local copy is what keeps the page agreeing with the database after a collision.
function adoptNotes(data) {
  if (data && data.notes) view.data.notes = data.notes;
  // ⚠️ IT DOES NOT REACH INTO THE DRAFT ANY MORE. It used to copy the server's list over
  //    view.draft.notes, which is now the cook's unsaved work. Nothing in Edit mode calls a note
  //    endpoint, so this only ever ran in reading view, and the line was a loaded gun pointed at
  //    the thing Cancel exists to protect.
}

function noteError(msg) {
  const bar = document.querySelector(".inline-error");
  if (bar) { bar.textContent = msg; bar.hidden = false; }
  else console.error("note:", msg);     // reading view has no error bar; the console is the fallback
}

function closeNoteEditors() {
  noteState.editingId = null;
  noteState.editingPlace = null;
  noteState.newOn = null;
  // ⚠️ THE UNSAVED ROW GOES WITH THE DRAFTS. It holds the type and the step link the cook
  //    picked, and leaving it behind would reopen the next "+ note" with the last one's answers.
  noteState.newRow = null;
  noteState.kindMenuFor = null;
  noteState.stepMenuFor = null;
  noteState.drafts.clear();
  noteState.titleDrafts.clear();
  noteState.focusField = "text";
  closePicker();
}

// ⚠️ CLOSING THE PICKER CHANGES NOTHING ABOUT THE NOTE, which is the whole of what Escape
// promises. The query and the cursor are view state and the link is only written by a click or by
// Enter, so there is nothing here to undo.
function closePicker() {
  noteState.pickQuery = "";
  noteState.pickCursor = null;
  noteState.pickingFor = null;
}

// ⚠️ THE SAVE IS UNDOABLE, SO THE TOAST HAS TO CARRY WHAT IT WOULD PUT BACK. `before` is the patch
// that restores the note, taken from the row as it stood BEFORE the write.
// ⚠️ AND UNDOING A CREATE IS A DELETE, NOT A PATCH. A new note has no `before`, so the toast drawn
// after one offered an Undo that did NOTHING: undoNote returned early on a null `before` and the
// offer simply disappeared. Pre-existing, and it became the obvious half of Andy's "same save rules
// as editing" once "+ note" started going through the shared save. `created` is the one thing the
// row cannot say for itself, since the server hands back an ordinary note either way.
function flashSaved(id, before, { created = false } = {}) {
  noteState.savedId = id;
  noteState.savedBefore = before || null;
  noteState.savedNew = !!created;
  setTimeout(() => {
    if (noteState.savedId === id) {
      noteState.savedId = null; noteState.savedBefore = null; noteState.savedNew = false;
      repaintNotes();
    }
  }, NOTE_TOAST_MS);
}

// ⚠️ THE NEW NOTE IS NOT IN noteRows() AND NEVER WILL BE until it is saved, so every path that
// looks a note up by id asks here instead. Three of them did their own `.find`, and a new note put
// in front of them is exactly the row that find cannot return.
function noteRowFor(id) {
  if (noteState.newRow && String(id) === String(NEW_NOTE_ID)) {
    return resolveNoteSteps([noteState.newRow], currentSteps())[0];
  }
  return noteRows().find((n) => String(n.id) === String(id));
}

function saveOpenNote() {
  const id = noteState.editingId;
  if (id == null) return Promise.resolve();
  // ⚠️ A NOTE WITH NO ROW BEHIND IT IS CREATED, NOT PATCHED, and that is the one difference
  //    between the two. Everything above this line is shared, which is what "one panel" means.
  if (String(id) === String(NEW_NOTE_ID)) return saveNewNote();
  const note = noteRows().find((n) => String(n.id) === String(id));
  const draft = noteState.drafts.get(id);
  const titleDraft = noteState.titleDrafts.get(id);
  // ⚠️ AN UNCHANGED SAVE SENDS NOTHING. Click-away fires on every blur, so a PATCH per blur would be
  //    a write per glance.
  // ⚠️ AND THE TITLE IS ASKED THE SAME QUESTION AS THE TEXT. Opening a note and closing it has to
  //    leave the row byte-identical, which is what keeps the recipe in the byte-equal set, so
  //    neither field alone decides and neither is ignored.
  // ⚠️ THE ROW IS CHECKED BEFORE EITHER FIELD IS ASKED ABOUT, because both questions read it.
  //    noteTextChanged runs the display rule over note.text, which throws on a missing row.
  if (!note) { closeNoteEditors(); repaintNotes(); return Promise.resolve(); }
  const textMoved = draft != null && noteTextChanged(note, draft, NOTE_KINDS.kinds);
  const titleMoved = titleDraft != null && noteTitleChanged(note, titleDraft);
  if (!textMoved && !titleMoved) {
    closeNoteEditors(); repaintNotes(); return Promise.resolve();
  }
  // Clearing a note's text and clicking away is not a delete. Deleting is the Delete button, which
  // offers an Undo; a silent delete from an empty box has nothing to undo.
  // ⚠️ IT READS THE DRAFT WHERE THERE IS ONE AND THE ROW WHERE THERE IS NOT, because a save may now
  //    be carrying a title change with the text untouched, and `draft` is null in that case.
  const nextText = draft != null ? String(draft) : String(note.text || "");
  if (!nextText.trim()) {
    closeNoteEditors(); repaintNotes(); return Promise.resolve();
  }
  // ⚠️ THE UNDO PUTS BACK THE STORED ROW, NOT THE SHOWN TEXT. A save rewrites the row to what was
  //    on screen (no label, the current number), so the only honest undo is the author's words as
  //    they were a moment ago. The title goes in it for the same reason: an Undo that restored the
  //    words and left a title the cook had just cleared would put the row back half way.
  const before = { text: note.text, title: note.title == null ? null : note.title };
  closeNoteEditors();
  // ⚠️ IN EDIT MODE THIS IS A LIST CHANGE AND NOT A WRITE, so there is no "Saved" toast and no
  //    Undo offer: the note is not saved yet, and saying so would be a lie. The page's own Cancel
  //    is the way back, which is the whole reason notes rejoined the draft.
  if (noteHeld()) {
    let next = view.draft.notes;
    if (textMoved) next = draftSetText(next, id, nextText.trim());
    if (titleMoved) next = draftSetTitle(next, id, titleDraft);
    return holdNotes(next);
  }
  const body = {};
  if (textMoved) body.text = nextText;
  if (titleMoved) body.title = titleDraft;
  return noteApi(`/notes/${id}`, { method: "PATCH", body: notePatchBody(body) })
    .then((data) => { adoptNotes(data); flashSaved(id, before); repaintNotes(); })
    .catch((e) => { noteError(e.message); repaintNotes(); });
}

// ⚠️ IT READS THE PANEL, NOT A TEXT FIELD. The box carries a Title, a type and a step link now,
// so the four answers travel together in one create rather than as a POST followed by three
// PATCHes that a cook can see happening.
// ⚠️ AN EMPTY NEW NOTE IS STILL DROPPED, which is what "+ note" has always done, and the title
// does not change that: a title with no words under it is a heading over nothing, and the column's
// own CHECK refuses a blank text anyway.
// ⚠️ THE STEP LINK COMES OFF THE ROW, NOT OFF `where`. They start equal, because "+ note" on a
// step opens linked to it, and they stop being equal the moment the cook uses the picker.
function saveNewNote() {
  const where = noteState.newOn;
  const row = noteState.newRow;
  if (where == null || !row) return Promise.resolve();
  const text = String(noteDraft(NEW_NOTE_ID) || "").trim();
  if (!text) { closeNoteEditors(); repaintNotes(); return Promise.resolve(); }
  const title = String(noteTitleDraft(NEW_NOTE_ID) || "").trim();
  const stepId = row.step_id == null ? null : +row.step_id;
  const body = { text };
  if (title) body.title = title;
  if (row.kind) body.kind = row.kind;
  if (stepId != null) body.step_id = stepId;
  closeNoteEditors();
  if (noteHeld()) {
    return holdNotes(draftAdd(view.draft.notes,
      { text, title: title || null, kind: row.kind, stepId }));
  }
  return noteApi("/notes", { method: "POST", body: notePatchBody(body) })
    .then((data) => {
      adoptNotes(data);
      if (data.note) flashSaved(data.note.id, null, { created: true });
      repaintNotes();
    })
    .catch((e) => { noteError(e.message); repaintNotes(); });
}

// A note added from another note's ⋯ menu. Edit mode only, which is where the menu is.
// ⚠️ IT OPENS READY FOR TYPING, WHICH IS WHAT addStep DOES. The new row is empty, so a save that
//    follows without a word typed drops it again (notesPayload filters a blank), exactly the
//    contract an empty added step already has.
// ⚠️ THE ID IS COMPUTED FROM THE SAME LIST draftAddBeside READS, so the two agree by construction.
//    Reading it back off the result would mean trusting the order instead.
function addNoteBeside(id, pos) {
  if (!noteHeld()) return Promise.resolve();
  saveOpenNote();
  const next = draftAddBeside(view.draft.notes, currentSteps(), NOTE_KINDS.kinds, id, pos);
  if (!next) return Promise.resolve();
  const newId = nextDraftId(view.draft.notes);
  noteState.editingId = newId;
  noteState.editingPlace = "ie";
  noteState.drafts.set(newId, "");
  return holdNotes(next);
}

function deleteNote(id) {
  if (noteHeld()) {
    // ⚠️ THE UNDO IS A LIST OPERATION TOO, so Cancel still throws the whole session away. The row
    //    itself is kept rather than a patch that would re-create it, because nothing has been
    //    written and there is nothing to re-create it from.
    const row = draftNote(id);
    const at = (view.draft.notes || []).findIndex((n) => String(n.id) === String(id));
    if (!row) return Promise.resolve();
    noteState.undo = { token: `d${id}`, what: "Deleted", row, at };
    setTimeout(() => {
      if (noteState.undo && noteState.undo.token === `d${id}`) {
        noteState.undo = null; repaintNotes();
      }
    }, NOTE_TOAST_MS);
    return holdNotes(draftDelete(view.draft.notes, id));
  }
  return noteApi(`/notes/${id}`, { method: "DELETE" })
    .then((data) => {
      adoptNotes(data);
      // ⚠️ THE UNDO HOLDS WHAT THE SERVER HANDED BACK, not what the client thought the note said.
      //    restore carries the words, the kind, the place and the step link, so Undo is a re-create
      //    that lands in the same position.
      noteState.undo = { token: `d${id}`, what: "Deleted", body: data.restore };
      repaintNotes();
      setTimeout(() => {
        if (noteState.undo && noteState.undo.token === `d${id}`) {
          noteState.undo = null; repaintNotes();
        }
      }, NOTE_TOAST_MS);
    })
    .catch((e) => noteError(e.message));
}

function undoNote(token) {
  // A saved note is still there, so its undo is a PATCH back to what it said. A deleted one is gone,
  // so its undo is a re-create from what the server handed back.
  if (String(token).startsWith("s")) {
    const id = +String(token).slice(1);
    const before = noteState.savedBefore;
    const created = noteState.savedNew;
    noteState.savedId = null; noteState.savedBefore = null; noteState.savedNew = false;
    // ⚠️ UNDOING A CREATE IS A DELETE. There is no earlier version of a note that did not exist a
    //    moment ago, so a PATCH has nothing to write and this used to return having done nothing.
    //    It goes through deleteNote, which offers its own "Deleted · Undo" and so leaves a way
    //    back from the way back.
    if (created) { repaintNotes(); return deleteNote(id); }
    if (!before) { repaintNotes(); return Promise.resolve(); }
    // ⚠️ THE ONE WRITE PATH THAT HAD NO HELD BRANCH, and the offer can be on screen in Edit mode
    //    because enterEditMode used not to clear it. A PATCH from inside a held session writes
    //    straight past Save and Cancel, which is the one thing Edit mode promises it cannot do.
    if (noteHeld()) {
      // ⚠️ BOTH FIELDS, because a save can now carry either or both. An Undo that restored the
      //    words and left a title the cook had just cleared would put the row back half way.
      return holdNotes(draftSetTitle(
        draftSetText(view.draft.notes, id, String(before.text || "")), id, before.title));
    }
    return noteApi(`/notes/${id}`, { method: "PATCH", body: notePatchBody(before) })
      .then((data) => { adoptNotes(data); repaintNotes(); })
      .catch((e) => { noteError(e.message); repaintNotes(); });
  }
  const u = noteState.undo;
  if (!u || u.token !== token) return Promise.resolve();
  noteState.undo = null;
  // ⚠️ AND A HELD RESTORE NEEDS A HELD DELETE'S SHAPE. The two deletes record different things
  //    (a reading-view one keeps the server's `restore` body, a held one keeps the row itself), so
  //    an offer made in one view and taken in the other restored a `{...undefined}` ghost that the
  //    save then dropped. enterEditMode clears the offer now; this refuses rather than guessing.
  if (noteHeld()) {
    if (!u.row) { repaintNotes(); return Promise.resolve(); }
    return holdNotes(draftRestore(view.draft.notes, u.row, u.at));
  }
  if (!u.body) { repaintNotes(); return Promise.resolve(); }
  return noteApi("/notes", { method: "POST", body: u.body })
    .then((data) => { adoptNotes(data); repaintNotes(); })
    .catch((e) => noteError(e.message));
}

function setNoteKind(id, kind) {
  noteState.kindMenuFor = null;
  // ⚠️ ON THE NEW NOTE IT IS A LOCAL CHANGE, NOT A WRITE. There is no row to patch, and
  //    creating one here so the type could be stored would make "+ note" write the moment it was
  //    opened, which is the one thing an empty new note must not do.
  if (String(id) === String(NEW_NOTE_ID) && noteState.newRow) {
    noteState.newRow = { ...noteState.newRow, kind: String(kind) };
    repaintNotes();
    return Promise.resolve();
  }
  const was = noteRowFor(id);
  const before = was ? { kind: was.kind } : null;
  if (noteHeld()) return holdNotes(draftSetKind(view.draft.notes, id, kind));
  return noteApi(`/notes/${id}`, { method: "PATCH", body: notePatchBody({ kind }) })
    .then((data) => { adoptNotes(data); flashSaved(id, before); repaintNotes(); })
    .catch((e) => { noteError(e.message); repaintNotes(); });
}

// The note's own step link, which is a different question from a "step N" written in its words.
// ⚠️ null CLEARS IT, AND THAT IS WHY notePatchBody TESTS FOR THE KEY RATHER THAN THE VALUE. An
// omitted step_id means "leave the link alone" and a null one means "take it off".
function setNoteStep(id, stepId) {
  noteState.stepMenuFor = null;
  if (String(id) === String(NEW_NOTE_ID) && noteState.newRow) {
    noteState.newRow = { ...noteState.newRow, step_id: stepId == null ? null : +stepId };
    closePicker();
    repaintNotes();
    return Promise.resolve();
  }
  const was = noteRowFor(id);
  // Picking the step it is already on is not a change, so it is not a write. The picker opens with
  // the current link under the cursor, which makes this the easiest key to press.
  if (was && !noteStepChanged(was, stepId)) { closePicker(); repaintNotes(); return Promise.resolve(); }
  const before = was ? { step_id: was.step_id == null ? null : was.step_id } : null;
  if (noteHeld()) { closePicker(); return holdNotes(draftSetStep(view.draft.notes, id, stepId)); }
  return noteApi(`/notes/${id}`, { method: "PATCH", body: notePatchBody({ step_id: stepId }) })
    .then((data) => { adoptNotes(data); flashSaved(id, before); repaintNotes(); })
    .catch((e) => { noteError(e.message); repaintNotes(); });
}

// ⚠️ unlinkNoteRef WAS HERE AND NOTHING CALLED IT. It was the client half of
//    PATCH /notes/<id>/refs/<i>, which unlinks ONE "step N" mention in a note's words. The page
//    has no affordance that reaches it: the × beside a note's step link is data-note-unlink-step,
//    which clears the note's own step_id through setNoteStep, a different thing. The endpoint stays
//    (see app.py::update_note_ref) because it is the only way a stored null ref is made, and
//    "a stored null is a decision" is what lets an unlink survive a later text edit.

// The click dispatcher, in the same shape handleInlineEdit and handleRowMenuAction already have:
// probe the attributes this concern owns, return true when one of them answered.
function handleNoteAction(e) {
  const t = e.target;
  if (!t || !t.closest) return false;

  // ⚠️ FIRST, BECAUSE A STEP ROW IS NOT INSIDE THE EDITOR. While "Pick on the page" is waiting,
  //    a click on a step is the answer to a question, and every later branch here would read it as
  //    a click-away and commit the open note instead.
  if (noteState.pickingFor != null) {
    const target = t.closest("[data-note-pick-step]");
    if (target) {
      e.preventDefault();
      const id = noteState.pickingFor;
      noteState.pickingFor = null;
      setNoteStep(id, +target.dataset.notePickStep);
      return true;
    }
  }

  const add = t.closest("[data-add-note]");
  if (add) {
    e.preventDefault();
    const where = add.dataset.addNote;
    saveOpenNote();
    // ⚠️ IT OPENS AS AN EDITOR, which is what makes the Title box, the type menu and the step
    //    picker work with no second set of handlers. The place is "new:<where>" so the box the
    //    cook is looking at is the one the caret comes back to, exactly as (note, place) does for
    //    a stored note drawn in two places at once.
    noteState.newOn = where;
    noteState.newRow = newNoteRow(where, NOTE_KINDS.kinds);
    noteState.editingId = NEW_NOTE_ID;
    noteState.editingPlace = `new:${where}`;
    noteState.drafts.set(NEW_NOTE_ID, "");
    noteState.titleDrafts.set(NEW_NOTE_ID, "");
    noteState.focusField = "text";
    noteState.kindMenuFor = null;
    noteState.stepMenuFor = null;
    repaintNotes();
    return true;
  }
  const undo = t.closest("[data-note-undo]");
  if (undo) { e.preventDefault(); undoNote(undo.dataset.noteUndo); return true; }

  const del = t.closest("[data-note-del]");
  if (del) { e.preventDefault(); deleteNote(+del.dataset.noteDel); return true; }

  const setKind = t.closest("[data-note-set-kind]");
  if (setKind) {
    e.preventDefault();
    setNoteKind(+setKind.dataset.noteSetKind, setKind.dataset.kind);
    return true;
  }
  const kindBtn = t.closest("[data-note-kind]");
  if (kindBtn) {
    e.preventDefault();
    const id = +kindBtn.dataset.noteKind;
    noteState.kindMenuFor = noteState.kindMenuFor === id ? null : id;
    noteState.stepMenuFor = null;
    repaintNotes();
    return true;
  }
  const linkMenu = t.closest("[data-note-link-menu]");
  if (linkMenu) {
    e.preventDefault();
    const id = +linkMenu.dataset.noteLinkMenu;
    noteState.stepMenuFor = noteState.stepMenuFor === id ? null : id;
    noteState.kindMenuFor = null;
    closePicker();                       // a fresh open starts with an empty filter
    repaintNotes();
    return true;
  }
  // "Pick on the page": the list goes, the method becomes the picker, and the note stays open
  // underneath so the click lands on the right one.
  const pickPage = t.closest("[data-note-pick-page]");
  if (pickPage) {
    e.preventDefault();
    noteState.pickingFor = +pickPage.dataset.notePickPage;
    noteState.stepMenuFor = null;
    noteState.pickQuery = "";
    noteState.pickCursor = null;
    repaintNotes();
    return true;
  }
  // ⚠️ CANCEL GOES BACK TO THE LIST ON A POINTER, AND ALL THE WAY OUT ON A PHONE. The sheet was
  //    closed to make room for the method there, so reopening it on cancel would put the cook back
  //    in front of the thing they just left.
  const pickCancel = t.closest("[data-note-pick-cancel]");
  if (pickCancel) {
    e.preventDefault();
    cancelPickOnPage(+pickCancel.dataset.notePickCancel);
    return true;
  }
  const linkStep = t.closest("[data-note-link-step]");
  if (linkStep) {
    e.preventDefault();
    setNoteStep(+linkStep.dataset.noteLinkStep, +linkStep.dataset.stepId);
    return true;
  }
  const unlinkStep = t.closest("[data-note-unlink-step]");
  if (unlinkStep) {
    e.preventDefault();
    setNoteStep(+unlinkStep.dataset.noteUnlinkStep, null);
    return true;
  }
  // The phone's way in: the step's number reveals that step's "+ note". A second tap on the same
  // number puts it away again.
  const tap = t.closest("[data-step-tap]");
  if (tap) {
    e.preventDefault();
    const id = tap.dataset.stepTap;
    noteState.tapStep = String(noteState.tapStep) === String(id) ? null : id;
    repaintNotes();
    return true;
  }
  // A click INSIDE an open editor is not a click-away.
  if (t.closest(".note-edit")) return false;

  const edit = t.closest("[data-note-edit]");
  if (edit) {
    e.preventDefault();
    const id = +edit.dataset.noteEdit;
    // ⚠️ THE PLACE IS READ FROM THE ATTRIBUTE THAT CARRIES IT, NEVER FROM A CLASS. This asked for
    //    `.note-row`, which is the INGREDIENT editor's own row class (styles.css:635, a two-column
    //    grid with a rule under it) — a name round 1 had collided with. Clicking a note inside a
    //    step's popover found no `.note-row`, fell back to "section", and opened the editor in the
    //    Notes section instead of in the popover the cook was looking at.
    const row = edit.closest("[data-note-place]");
    const place = (row && row.dataset.notePlace) || "section";
    if (noteState.editingId === id && noteState.editingPlace === place) return true;
    saveOpenNote();
    noteState.editingId = id;
    noteState.editingPlace = place;
    const note = noteRows().find((n) => String(n.id) === String(id));
    // ⚠️ THE DRAFT IS SEEDED FROM WHAT THE PAGE SHOWS, NOT FROM THE ROW. Seeding it from note.text
    //    put the stripped label and the author's old step number straight back into the box, which
    //    is the disagreement this round exists to end. noteEditText is the one rule both sides read.
    noteState.drafts.set(id, note ? noteEditText(note, NOTE_KINDS.kinds) : "");
    // ⚠️ THE TITLE IS SEEDED FROM THE ROW, NOT THROUGH noteEditText. It is stored verbatim and the
    //    page prints it verbatim, so there is no display rule between the two to go through.
    noteState.titleDrafts.set(id, note && note.title ? String(note.title) : "");
    noteState.focusField = "text";      // a newly opened note puts the caret in its words
    repaintNotes();
    return true;
  }
  // ⚠️ CLICK-AWAY SAVES, which is the other half of "Enter saves". A click anywhere that is not the
  //    open editor and not one of the controls above commits what was typed.
  // ⚠️ ONE BRANCH. A new note sets editingId, so the line below commits it exactly as it
  //    commits a stored one, and saveOpenNote decides which of the two it is.
  if (noteState.editingId != null) { saveOpenNote(); return false; }
  if (noteState.tapStep != null && !t.closest(".step-add-note")) {
    noteState.tapStep = null;
    repaintNotes();
  }
  return false;
}

// ⚠️ THE MENUS ARE IN THE MARKUP NOW, NOT INSERTED NEXT TO THEIR BUTTON. The type tag used to live
// on every note at rest and its menu was injected beside it, which meant a repaint could leave one
// behind. Both menus belong to the open editor and are drawn with it, so closing the editor closes
// them by construction.

// The picker's keyboard, which runs BEFORE the note's own because the caret is in the filter box and
// the box sits inside the note editor. Up and down move the cursor, Enter links what it is on, and
// Escape closes the list and changes nothing.
// ⚠️ ESCAPE HERE IS NOT THE NOTE'S ESCAPE. The note's cancels the edit and throws the draft
// away. The picker's closes one control and leaves the note exactly as it was, which is why it
// stops the event rather than falling through.
document.addEventListener("keydown", (e) => {
  const find = e.target && e.target.closest && e.target.closest("[data-note-pick-find]");
  if (!find) return;
  const id = +find.dataset.notePickFind;
  // ⚠️ noteRowFor, NOT noteRows().find. The picker opens on a NEW note too, and a row the
  //    server has never seen is not in that list, so the arrows and Enter did nothing at all
  //    inside the one panel where picking the step matters most.
  const note = noteRowFor(id);
  if (!note) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const { rows, cursor } = pickState(note);
    noteState.pickCursor = moveCursor(rows, cursor, e.key === "ArrowDown" ? 1 : -1);
    repaintNotes();
    return;
  }
  if (e.key === "Enter") {
    e.preventDefault();
    e.stopPropagation();                   // never also save the note underneath
    const { cursor } = pickState(note);
    if (cursor != null) { noteState.stepMenuFor = null; setNoteStep(id, +cursor); }
    return;
  }
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    noteState.stepMenuFor = null;
    closePicker();
    repaintNotes();
  }
}, true);

// Escape while the method IS the picker. It belongs on the document because nothing inside the
// picker holds the focus then: the panel has stepped aside and the page is the control.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || noteState.pickingFor == null) return;
  e.preventDefault();
  e.stopPropagation();
  cancelPickOnPage(noteState.pickingFor);
}, true);

// Enter saves, Shift+Enter makes a line, Escape cancels. One handler for the open note and for the
// new-note box, because they are the same keystrokes.
document.addEventListener("keydown", (e) => {
  // ⚠️ THE TITLE BOX IS THE SAME EDITOR, SO IT TAKES THE SAME KEYSTROKES. Enter in a one-line
  //    field otherwise submits nothing and Escape otherwise closes the popover the panel sits in,
  //    which would lose the typed title with no way back.
  // ⚠️ ONE PROBE, BECAUSE THERE IS ONE PANEL. The new-note box used to carry its own
  //    [data-new-note-input] and its own save call on this line. It is the editor now, so Enter
  //    goes through saveOpenNote, which is where "a note with no row behind it is created" lives.
  const open = e.target && e.target.closest
    && e.target.closest("[data-note-input], [data-note-title]");
  if (!open) return;
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    saveOpenNote();
    return;
  }
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();          // never also close the step popover this box may sit in
    closeNoteEditors();
    repaintNotes();
  }
});

// Keystrokes go into the draft and NOT through a repaint, or the caret would jump on every letter.
document.addEventListener("input", (e) => {
  const open = e.target && e.target.closest && e.target.closest("[data-note-input]");
  if (open) {
    noteState.focusField = "text";
    noteState.drafts.set(+open.dataset.noteInput, open.value);
    growNoteInput(open);
    return;
  }
  // The Title box, which is a single line and so never grows.
  const title = e.target && e.target.closest && e.target.closest("[data-note-title]");
  if (title) {
    noteState.focusField = "title";
    noteState.titleDrafts.set(+title.dataset.noteTitle, title.value);
    return;
  }
  // ⚠️ THE FILTER IS THE ONE FIELD THAT DOES REPAINT ON EVERY LETTER, because the list IS its
  //    output. restoreNoteFocus puts the caret back in it, which is why that function asks about
  //    the picker before it asks about the note.
  const find = e.target && e.target.closest && e.target.closest("[data-note-pick-find]");
  if (find) { noteState.pickQuery = find.value; noteState.pickCursor = null; repaintNotes(); }
});

/* ---------- events ---------- */
// One click listener for the whole page (instead of attaching one to every button,
// which is impossible here since the buttons are rebuilt constantly). When any click
// happens, we look at what was clicked — e.target.closest("X") finds the nearest
// matching element at or above the click — and act on the first kind we recognize.
document.addEventListener("click", (e) => {
  // 3c: a click anywhere outside an open ⋮ menu (and not on the ⋮ itself) closes it — no return, other handlers still run.
  if (!e.target.closest(".photo-menu") && !e.target.closest("[data-photo-menu]")) closePhotoMenu();
  // A stage 1: the same rule for the editor's row-actions ⋯ menus. A SEPARATE pre-branch rather than
  // extra terms on the line above, because the two exemption tests are not interchangeable — see the
  // note on closeRowMenu(). Also no return: this is a pre-branch, every handler below still runs.
  if (!e.target.closest(".row-menu") && !e.target.closest("[data-row-menu]")) closeRowMenu();
  // A plan-ahead step link: scroll to that step and mark it briefly. Reading mode only — in the
  // editor the same number is a picker, not a link.
  const wstep = e.target.closest("[data-wait-step]");
  if (wstep) { e.preventDefault(); jumpToStep(+wstep.dataset.waitStep); return; }
  const nstep = e.target.closest("[data-note-step]");
  if (nstep) { e.preventDefault(); jumpToStep(+nstep.dataset.noteStep); return; }
  // The tag at the end of a step. A click PINS the popover open until a click elsewhere or Escape,
  // which is what makes it usable on a phone, where there is no hover to hold it.
  const nmark = e.target.closest(".step-note-marker");
  if (nmark) {
    e.preventDefault();
    const sid = nmark.dataset.stepNote;
    if (String(popPinned) === String(sid)) closeStepNotes({ force: true });
    else { popPinned = sid; openStepNote(sid); syncStepNotes(); }
    return;
  }
  // A click anywhere else closes an open one, the way the photo and row menus already behave.
  if (!e.target.closest(".step-note-pop")) closeStepNotes({ force: true });
  if (view && view.editMode && handlePlanAheadAction(e.target)) { markDirty(); return; }

  // The note component: add, edit, delete, undo, type. BEFORE handleInlineEdit, because the
  // component is live in BOTH views and its attributes are disjoint from the editor's.
  if (handleNoteAction(e)) return;
  // Inline recipe editor: enter / save / cancel (namespaced data-inline-edit-*). Handled first.
  if (handleInlineEdit(e)) return;
  // A stage 1: the editor's per-row ⋯ menu. After handleInlineEdit, not before — the ⋯ carries its own
  // data-row-menu namespace, so the two dispatchers probe disjoint attributes and cannot race.
  if (handleRowMenuAction(e)) return;

  // 3b-iii: the "Cooked it" follow-on photo chip (offer -> pick -> attach). Handled before the .stats
  // block since the chip lives inside the cook block but its buttons are its own.
  if (e.target.closest("[data-cf-add]")) { openCookChipPick(); return; }
  if (e.target.closest("[data-cf-x]") || e.target.closest("[data-cc-cancel]")) { clearCookChip(); return; }
  if (e.target.closest("[data-cc-add]")) { if (cookChip) cookChip.el.querySelector(".cc-input").click(); return; }
  const ccRemove = e.target.closest("[data-cc-remove]");
  if (ccRemove) { cookChipRemove(Number(ccRemove.dataset.ccRemove)); return; }
  const ccAttach = e.target.closest("[data-cc-attach]");
  if (ccAttach) { cookChipAttach(ccAttach); return; }

  // 3c: per-photo album ⋮ menu + make-hero / edit-caption / delete (acts on data-photo-id, refresh via renderRecipe)
  // The hero Polaroid and its "Photos" pill both open the album overlay (item 6). One hook, so the
  // picture and the label cannot drift apart.
  const albumOpen = e.target.closest("[data-album-open]");
  if (albumOpen) { openAlbumOverlay(albumOpen); return; }
  if (handleAlbumPhotoAction(e)) return;

  // 3d-iii: album reorder mode — enter / Done (commit via 3d-ii) / Cancel (discard)
  if (e.target.closest("[data-album-reorder]"))        { enterAlbumReorder();  return; }
  if (e.target.closest("[data-album-reorder-done]"))   { commitAlbumReorder(); return; }
  if (e.target.closest("[data-album-reorder-cancel]")) { cancelAlbumReorder(); return; }

  // Bulk-delete all test recipes (home header) — inline two-step confirm, like the recipe delete.
  const bulk = document.getElementById("test-bulk");
  if (e.target.closest("[data-delete-test]")) {
    // ⚠️ "YOUR N", BECAUSE THE SERVER DELETES ONLY YOURS. The confirm said "all test recipes" and
    // the button "Delete all", which described the endpoint before it was owner-scoped. The count
    // comes from the same is_mine filter the button's own label uses.
    bulk.innerHTML = `<span class="delete-confirm">Delete your ${bulk.dataset.count} test recipe${
      bulk.dataset.count === "1" ? "" : "s"}?
      <button class="btn ghost sm danger" data-delete-test-confirm>Delete</button>
      <button class="btn ghost sm" data-delete-test-cancel>Cancel</button></span>`;
    return;
  }
  if (e.target.closest("[data-import-url]")) { promptImport(); return; }
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
    // A star click rates ONE COOKING, and the stars only take a click when there IS exactly one.
    // The read-only average carries no [data-rate] target at all.
    const rate = e.target.closest("[data-cook-stars] [data-rate]");
    if (rate) {
      const holder = rate.closest("[data-cook-stars]");
      // Clicking the step a cook already sits on CLEARS it, the only way back to unrated.
      patchCook(holder, { rating: nextRating(holder.dataset.rating, rate.dataset.rate) });
      return;
    }
    if (e.target.closest("[data-cook]")) {   // one-click log stays instant; then offer the photo chip (3b-iii)
      updateStats(stats, `/api/recipes/${rid}/cooked`, {}).then((s) => {
        if (s && s.cook_log_id != null) offerCookPhotoChip(stats, stats.dataset.rid, s.cook_log_id);
      });
      return;
    }
    if (e.target.closest("[data-uncook]")) {
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

  // Album "See all N photos" <-> "See less" — desktop inline expand (CSS .collapsed hides beyond four).
  // Mobile keeps the same inline expand for now; a dedicated mobile album view is a deferred follow-up.
  const albumToggle = e.target.closest("[data-album-toggle]");
  if (albumToggle) {
    const sec = app.querySelector("#album-section");
    const grid = sec && sec.querySelector(".album-grid.masonry");
    if (sec && grid) {
      const collapsed = sec.classList.toggle("collapsed");
      const total = (grid._items || []).filter((el) => !el.classList.contains("album-add")).length;
      layoutAlbum(grid);   // re-distribute: collapsed -> first ALBUM_CAP, expanded -> all (masonry, order preserved)
      albumToggle.innerHTML = collapsed
        ? `See all ${total} photos <span class="chev">&#8595;</span>`
        : `See less <span class="chev">&#8593;</span>`;
    }
    return;
  }

  // recipe-detail interactions: app-recipe delete / copy / scale
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
      if (oa) oa.innerHTML = ownerActionsHTML(view.data.recipe, view.data.is_mine);
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
  else if (albumOverlay && !albumOverlay.hidden) closeAlbumOverlay();
});

// ---- the album overlay + lightbox, wired once (both containers persist in the markup) ----------
if (albumOverlay) {
  albumOverlay.querySelector("[data-album-close]").addEventListener("click", closeAlbumOverlay);
  const aoInput = albumOverlay.querySelector(".ao-input");
  albumOverlay.querySelector("[data-ao-add]").addEventListener("click", () => aoInput.click());
  aoInput.addEventListener("change", () => { albumOverlayUpload(aoInput.files); aoInput.value = ""; });
}
if (lightbox) {
  lightbox.querySelector("[data-lb-close]").addEventListener("click", closeLightbox);
  lightbox.querySelector("[data-lb-prev]").addEventListener("click", () => showLightbox(lbIndex - 1));
  lightbox.querySelector("[data-lb-next]").addEventListener("click", () => showLightbox(lbIndex + 1));
  lightbox.querySelector("[data-lb-hero]").addEventListener("click", (e) => {
    const id = e.currentTarget.dataset.photoId;
    if (id) promotePhoto(id, view && view.slug);   // reuses the existing promote route
  });
  // Clicking the dark surround closes, the photo itself does not — the commonest way to dismiss a
  // lightbox, and clicking the picture you just opened should not throw it away.
  lightbox.addEventListener("click", (e) => {
    if (e.target === lightbox || e.target.classList.contains("lb-figure")) closeLightbox();
  });
}
backdateModal.querySelector("[data-backdate-close]").addEventListener("click", closeBackdate);
backdateModal.querySelector("[data-backdate-log]").addEventListener("click", submitBackdate);
// The log-cook box's stars. Clicking the step it already sits on clears it, the same gesture the
// cook-log rows use, so there is one way to mean "actually, no opinion".
backdateModal.addEventListener("click", (e) => {
  const hit = e.target.closest("[data-bd-stars] [data-rate]");
  if (hit) {
    bdRating = nextRating(bdRating, hit.dataset.rate);
    bdPaintRating();
    return;
  }
  if (e.target.closest("[data-bd-rate-clear]")) { bdRating = null; bdPaintRating(); }
});
wireBdPhoto();   // 3b-ii: wire the add-a-photo pick/drop/remove ONCE (the box persists; renderBdPhoto swaps innerHTML)
// 3b-iii: the cook-chip's file input is recreated on each staging render; `change` bubbles, so one
// delegated listener stages whatever it picks (isStageableImage filtering happens in cookChipStage).
document.addEventListener("change", (e) => {
  if (e.target && e.target.classList && e.target.classList.contains("cc-input")) {
    cookChipStage(e.target.files);
    e.target.value = "";   // clear so re-picking the same files re-fires
  }
});
document.addEventListener("keydown", (e) => {
  // ⚠️ THE LIGHTBOX IS CHECKED FIRST because it sits ON TOP of the album overlay. Escape must peel
  // one layer, not both, or dismissing a photo also throws away the grid behind it.
  // The hero image is role="button" tabindex="0", so it answers the keyboard like the pill does.
  if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("img[data-album-open]")) {
    e.preventDefault();
    openAlbumOverlay(e.target);
    return;
  }
  if (e.key === "Escape" && lightbox && !lightbox.hidden) { closeLightbox(); return; }
  if (lightbox && !lightbox.hidden && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
    showLightbox(lbIndex + (e.key === "ArrowRight" ? 1 : -1));
    return;
  }
  if (e.key === "Escape" && albumOverlay && !albumOverlay.hidden) { closeAlbumOverlay(); return; }
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
  // Editor parity — the step-heading twin of the ingredient Enter/Escape handling above. Shares the
  // same focus-time snapshot (iePreEdit covers both namespaces) since only one field is ever focused.
  // writeStepField tolerates a missing row, so no guard is needed on the draft lookup.
  if (view && view.editMode && e.target.dataset && e.target.dataset.inlineEditStep) {
    if (e.key === "Enter") { e.preventDefault(); e.target.blur(); return; }
    if (e.key === "Escape") {
      e.preventDefault();
      const el = e.target;
      el.value = iePreEdit;
      writeStepField(view.draft && view.draft.steps[Number(el.dataset.i)], el.dataset.inlineEditStep, iePreEdit);
      el.blur();
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
// 3d-iii: the album reorder drag (native HTML5 DnD), delegated at the document level — the #reorder-strip
// is re-created each time reorder mode is entered, so scoping the handlers by closest("#reorder-strip") keeps
// them valid across repaints without rebinding.
document.addEventListener("dragstart", reorderDragStart);
document.addEventListener("dragover", reorderDragOver);
document.addEventListener("drop", reorderDrop);
document.addEventListener("dragend", reorderDragEnd);
// C1: the ingredient-list reorder drag, wired the same way and for the same reason — #ing-section is
// re-rendered on every structural edit, so scoping by closest(".ingredient-list.edit") survives every
// repaint without rebinding. The two sets are disjoint: each returns early unless the event started
// inside its own container.
document.addEventListener("dragstart", ingDragStart);
document.addEventListener("dragover", ingDragOver);
document.addEventListener("drop", ingDrop);
document.addEventListener("dragend", ingDragEnd);
// C2: the step list, same delegation for the same reason — rerenderEditSteps replaces #steps-list's
// contents wholesale on every structural edit, so scoping by closest("#steps-list") survives it.
document.addEventListener("dragstart", stepDragStart);
document.addEventListener("dragover", stepDragOver);
document.addEventListener("drop", stepDrop);
document.addEventListener("dragend", stepDragEnd);
// The Edit-mode note list, same delegation for the same reason — repaintNotes replaces the whole
// .ie-notes host on every held write, so scoping by closest(".ie-note-block .ie-noterow") survives
// it. Disjoint from the other three: each returns early unless the drag started in its own rows.
document.addEventListener("dragstart", noteDragStart);
document.addEventListener("dragover", noteDragOver);
document.addEventListener("drop", noteDrop);
document.addEventListener("dragend", noteDragEnd);

document.addEventListener("change", (e) => {
  if (view && view.editMode && view.draft && handlePlanAheadInput(e.target)) markDirty();
});

document.addEventListener("input", (e) => {
  // 3c: live N/60 count for the album caption edit (maxlength already hard-stops at 60; this only recolors the count)
  const capIn = e.target.closest("[data-cap-input]");
  if (capIn) {
    const foot = capIn.parentElement.querySelector("[data-cap-count]");
    const n = capIn.value.length;
    if (foot) { foot.textContent = `${n} / ${ALBUM_CAPTION_MAX}`;
      foot.className = "cap-count" + (n >= ALBUM_CAPTION_MAX ? " at" : n >= 50 ? " near" : ""); }
    return;
  }
  const el = e.target.closest(".scale-custom");
  if (el) { el.value = el.value.replace(/[^\d.]/g, ""); return; }   // digits + decimal point only while editing
  // Inline editor: buffer the scalar field into the draft ONLY — never re-render here, or the input
  // would lose focus/caret mid-typing. Re-render happens solely on mode/save/cancel.
  // Plan-ahead + storage boxes buffer into the draft the same way, and for the same reason: no
  // re-render here or the caret jumps. add/remove repaint, typing never does.
  if (view && view.editMode && view.draft && handlePlanAheadInput(e.target)) { markDirty(); return; }
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
  // Editor parity — buffer a step HEADING into its draft row. Same no-re-render discipline as the
  // ingredient branch (re-rendering here would destroy focus and caret mid-keystroke), and the flush
  // MUST be on `input`, never on blur: rerenderEditSteps() destroys and rebuilds #steps-list from
  // view.draft on every add/delete, so any text that hasn't reached the draft yet is re-rendered away
  // — silently, since the rebuild happily paints the stale value instead of erroring.
  const sh = e.target.closest("[data-inline-edit-step]");
  if (sh && view && view.editMode && view.draft) {
    const row = view.draft.steps[Number(sh.dataset.i)];
    if (!row) return;
    writeStepField(row, sh.dataset.inlineEditStep, sh.value);
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
// on the unit combobox too — not just the overlay textareas — and (editor parity) the step-heading
// field. ONE shared snapshot is correct for both namespaces: only one field can be focused at a time.
let iePreEdit = "";
document.addEventListener("focusin", (e) => {
  const ta = e.target.closest("[data-inline-edit-ing], [data-inline-edit-step]");
  if (ta && view && view.editMode) iePreEdit = ta.value;
});
// Click-to-focus is the BROWSER'S, not ours. There used to be a mousedown handler here that
// preventDefault()ed on .ie-disp, read a caret offset via caretPositionFromPoint and focused the
// textarea by hand, because "a naive fall-through hit-tests the wrong, reflowed layout" (the field
// wraps and grows on focus: measured 27px/nowrap at rest -> 57px/normal focused). That handler is
// gone: the overlay is now pointer-events:none (see styles.css .ie-disp), so a press lands on the
// textarea directly and .closest(".ie-disp") could never match again. It also cost drag-selection —
// preventDefault on mousedown kills the gesture, and the press never reached the field at all.
// The stated reflow concern did NOT reproduce: native fall-through places the caret as accurately as
// the handler did, including on a truncated value (measured at x+20/80/160/240 -> 2/12/23/32 vs the
// handler's 2/12/22/33, expected ~2/11/22/32).

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

// Hover-preview the rating: fill to EXACTLY the half step under the cursor, restore the committed
// value on leave. Pure visual, and it carries real weight here — half a star is about 13px wide, so
// seeing the value fill before the click is what makes a small target safe to aim at. Touch devices
// have no hover and commit on tap.
const previewFill = (holder, value) => {
  const on = holder.querySelector(".starfill-on");
  if (on) on.style.width = ratingPct(value);
};
document.addEventListener("mouseover", (e) => {
  const hit = e.target.closest(".rating-input [data-rate]");
  if (!hit) return;
  const holder = hit.closest(".rating-input");
  holder.classList.add("previewing");
  previewFill(holder, Number(hit.dataset.rate));
});
document.addEventListener("mouseout", (e) => {
  const holder = e.target.closest(".rating-input");
  if (!holder || holder.contains(e.relatedTarget)) return;   // ignore star->star moves; clear on a real leave
  holder.classList.remove("previewing");
  // restore the committed value: the single-cook stars carry it, the log-cook box holds it in state
  previewFill(holder, holder.dataset.cookId ? Number(holder.dataset.rating || 0) : bdRating || 0);
});

// Dirty-state navigation guard: route() rebuilds `view` from a fresh fetch on any hash change (the
// ← All recipes link, browser back, any #/ nav), which would silently discard an unsaved edit buffer.
// Prompt first; if kept, restore the hash and leave the edit session intact.
let inlineNavSuppress = false;
function onHashChange() {
  if (!authGate.hidden) return;                                   // logged out (login view up) — don't route
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

// Sign out (auth-4): delegated so it survives home re-renders. Ends the session, returns to login.
document.addEventListener("click", async (e) => {
  if (!e.target.closest("[data-logout]")) return;
  await authRequest("POST", "/api/logout");
  showAuth();
});

boot();   // auth-4: gate on GET /api/me before the app renders (was: route())


/* ===================================================================================================
   SOCIAL FEED (sub-stage 2b) — the composed "Cooking" page, wired to the existing feed/share/comment
   endpoints. THIN CLIENT: render what the server returns; the server enforces friends-only visibility
   and who-may-delete (the unshare / comment-delete controls are UX shown from is_mine / can_delete,
   never the security boundary). Every user-supplied string goes through esc(). NO counts anywhere; the
   feed is server-bounded and simply ENDS. Function declarations are hoisted, so route()'s #/feed branch
   resolves this even though the block is appended below.
   =================================================================================================== */
const FEED_CAPTION_MAX = 150;    // client cap (server allows 280) — the locked spec caps the client at 150
const FEED_COMMENT_MAX = 300;    // matches the server COMMENT_MAX

// Placeholder chef-hat avatar — a simple clean mark (the characterful hand-drawn hat is a deferred
// design task). currentColor so CSS owns the ink; decorative — the name carries identity.
const HAT_SVG = '<svg viewBox="0 0 40 36" class="hat" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"><path d="M9 23 C3.5 23 4 14 9.5 13 C8.5 6 17.5 4.5 20 9.5 C22.5 4.5 31.5 6 30.5 13 C36 14 36.5 23 31 23 Z"/><path d="M12 23 h16 v5 a2 2 0 0 1 -2 2 h-12 a2 2 0 0 1 -2 -2 Z"/></g></svg>';
function feedAvatar() { return `<span class="cook-av">${HAT_SVG}</span>`; }

// A photo only when the recipe actually has one — otherwise nothing (no placeholder box), per spec.
function feedPhoto(rec) {
  if (!rec || !rec.image) return "";
  return `<div class="fp-photo"><img src="/${esc(rec.image)}" alt="${esc(rec.name || "")}" loading="lazy"
     onerror="this.closest('.fp-photo').remove()"></div>`;
}

function feedComment(c) {
  const name = (c.author && c.author.display_name) || (c.is_mine ? "You" : "Someone");
  const del = c.can_delete
    ? `<button class="fc-del" data-comment-delete="${c.id}" aria-label="Delete comment">&times;</button>` : "";
  return `<div class="fc" data-comment="${c.id}">${feedAvatar()}
    <div class="fc-main"><div class="fc-top"><span class="fc-name">${esc(name)}</span>
      <span class="fc-time">${esc(feedRelTime(c.created_at))}</span>${del}</div>
      <div class="fc-body">${esc(c.body)}</div></div></div>`;
}

function feedPost(p) {
  const kind = p.post_type === "cook" ? "cook" : "recipe";
  const chip = kind === "cook" ? "Cooked" : "Shared";
  const who = esc((p.sharer && p.sharer.display_name) || (p.is_mine ? "You" : "A friend"));   // display_name only — never the email
  const rec = p.recipe;
  const when = esc(feedRelTime(p.created_at));
  const you = p.is_mine ? `<span class="fp-you">you</span>` : "";
  const unshare = p.is_mine ? `<button class="fp-unshare" data-unshare="${p.id}">Remove</button>` : "";
  const cookedOn = (kind === "cook" && p.cooked_on)
    ? `<span class="fp-cooked">cooked ${esc(feedDateShort(p.cooked_on))}</span>` : "";
  const cap = p.caption ? `<p class="fp-cap">${esc(p.caption)}</p>` : "";
  const nameEl = rec
    ? `<a class="fp-recipe" href="#/recipe/${encodeURIComponent(rec.id)}">${esc(rec.name)}</a>`
    : `<span class="fp-recipe">a recipe</span>`;
  const thread = (p.comments || []).map(feedComment).join("");
  return `<article class="fp ${kind}${p.is_mine ? " mine" : ""}" data-post="${p.id}">
    <div class="fp-head">${feedAvatar()}
      <span class="fp-meta"><span class="fp-chip ${kind}">${chip}</span>${you}
        <span class="fp-who">${who}</span><span class="fp-when">${when}</span></span>${unshare}</div>
    ${feedPhoto(rec)}
    ${nameEl}
    ${cookedOn}
    ${cap}
    <div class="fp-thread">${thread}</div>
    <form class="fp-reply" data-comment-form="${p.id}">${feedAvatar()}
      <input type="text" name="body" maxlength="${FEED_COMMENT_MAX}" placeholder="Say something" autocomplete="off"></form>
  </article>`;
}

function feedNav() {
  return `<nav class="feed-nav">
    <a class="fn-item" href="#/">Recipes</a>
    <span class="fn-item active">Cooking<span class="fn-sub">what friends made</span></span>
    <span class="fn-item inert">Friends</span>
    <span class="fn-item inert">Profile<span class="fn-sub">your chef-page<span class="fn-soon">soon</span></span></span>
  </nav>`;
}

function surroundCard(cls, title, body, soon) {
  const tag = soon ? `<span class="fs-soon">soon</span>` : "";
  return `<section class="fs-card ${cls}"><h3 class="fs-h">${title}${tag}</h3><div class="fs-body">${body}</div></section>`;
}

function feedSurround(friends, season) {
  const fr = (friends && friends.friends) || [];
  const friendsBody = fr.length
    ? `<ul class="fs-friends">${fr.map((f) =>
        `<li>${feedAvatar()}<span>${esc(f.display_name || "A cook")}</span></li>`).join("")}</ul>`
    : `<p class="fs-empty">No friends yet — add someone to share a kitchen with.</p>`;
  const ings = (season && season.ingredients) || [];
  const seasonBody = ings.length
    ? `<ul class="fs-season">${ings.map((i) => `<li>${esc(i.name)}</li>`).join("")}</ul>`
    : `<p class="fs-empty">Nothing flagged for this month yet.</p>`;
  return `<aside class="feed-surround">
    ${surroundCard("green", "Your friends", friendsBody, false)}
    ${surroundCard("terra", "Want to make", `<p class="fs-empty">A place for what you mean to cook — coming soon.</p>`, true)}
    ${surroundCard("green", "In season now", seasonBody, false)}
    ${surroundCard("terra", "Cook it again", `<p class="fs-empty">Your favourites, back around — coming soon.</p>`, true)}
  </aside>`;
}

function feedEmpty() {
  return `<div class="feed-empty"><span class="fe-orn"></span>
    <h3>Nothing shared yet.</h3>
    <p>When you or a friend shares a cook, it lands here. Start the fire — share something you&rsquo;ve made.</p>
    <button class="share-btn" data-compose-open>Share a cook or recipe</button></div>`;
}

function feedMasthead() {
  // Masthead 3 "green chrome" (ported from preview/feed-masthead.html). Title only (subtitle removed),
  // top-right = Sign out ONLY (Box + name pills removed). The data-logout button stays functional.
  const signout = CURRENT_USER
    ? `<button type="button" class="pill out" data-logout>Sign out</button>` : "";
  return `<header class="feed-mast">
    <div><h1 class="site-title">Chef&rsquo;s Choice</h1></div>
    <div class="nav-actions">${signout}</div></header>`;
}

async function renderFeed() {
  view = null;
  app.className = "page feed-view";
  let posts;
  try {
    posts = await api("/api/feed");
  } catch (e) {
    if (e.message === "__auth__") return;   // 401 already dropped us to the login view
    throw e;                                // other failures bubble to route()'s catch -> showError
  }
  // Surround data: fetch in parallel, fail SOFT — a slow/failed side-card must never break the feed.
  const [friends, season] = await Promise.all([
    api("/api/friends").catch(() => ({ friends: [] })),
    api("/api/in-season").catch(() => ({ ingredients: [] })),
  ]);
  const center = posts.length
    ? `<div class="feed-list">${posts.map(feedPost).join("")}<div class="feed-end"><span class="fe-orn"></span></div></div>`
    : feedEmpty();
  app.innerHTML = `${feedMasthead()}
    <div class="feed-board">${feedNav()}
      <main class="feed-col"><div class="feed-col-head"><h2 class="feed-title">What&rsquo;s cooking?</h2>
        <button class="share-btn" data-compose-open>Share a cook or recipe</button></div>
        ${center}</main>
      ${feedSurround(friends, season)}</div>`;
}

/* ---- share compose (one modal, both types; cook-share primary) ---- */
let composeState = null;

async function openCompose() {
  closeCompose();
  const overlay = document.createElement("div");
  overlay.className = "compose-overlay";
  overlay.innerHTML = `<div class="compose-card" role="dialog" aria-modal="true" aria-label="Share a cook or recipe">
    <button class="compose-x" data-compose-close aria-label="Close">&times;</button>
    <h2 class="compose-title">Share a cook or recipe</h2>
    <div class="compose-tabs">
      <button class="ct-tab active" data-compose-tab="cook">A cook</button>
      <button class="ct-tab" data-compose-tab="recipe">A recipe</button></div>
    <div class="compose-pick" data-compose-pick><p class="fs-empty">Loading…</p></div>
    <label class="compose-caplabel">Add a note <span class="ct-count" data-cap-count>0/${FEED_CAPTION_MAX}</span></label>
    <textarea class="compose-cap" data-compose-caption maxlength="${FEED_CAPTION_MAX}" rows="2"
      placeholder="say a little about it (optional)"></textarea>
    <div class="compose-actions"><span class="compose-err" data-compose-err aria-live="polite"></span>
      <button class="share-btn" data-compose-submit disabled>Share</button></div></div>`;
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("open"));
  await loadComposePick("cook");   // cook picker is the primary/default path
}

function closeCompose() {
  const o = document.querySelector(".compose-overlay");
  if (o) o.remove();
  composeState = null;
}

async function loadComposePick(type) {
  composeState = { type, cook_log_id: null, recipe_id: null };
  const pick = document.querySelector("[data-compose-pick]");
  const submit = document.querySelector("[data-compose-submit]");
  if (submit) submit.disabled = true;
  document.querySelectorAll(".ct-tab").forEach((t) => t.classList.toggle("active", t.dataset.composeTab === type));
  if (!pick) return;
  pick.innerHTML = `<p class="fs-empty">Loading…</p>`;
  try {
    if (type === "cook") {
      const cooks = await api("/api/cooks");   // newest-first from the server
      pick.innerHTML = cooks.length
        ? `<ul class="ct-list">${cooks.map((c) => `<li><button class="ct-opt" data-pick-cook="${c.cook_log_id}">
            ${c.image ? `<img class="ct-thumb" src="/${esc(c.image)}" alt="" onerror="this.remove()">` : `<span class="ct-thumb none"></span>`}
            <span class="ct-opt-main"><span class="ct-opt-name">${esc(c.recipe_name)}</span>
            <span class="ct-opt-sub">cooked ${esc(feedDateShort(c.cooked_on))}</span></span></button></li>`).join("")}</ul>`
        : `<p class="fs-empty">No cooks logged yet — cook something and log it, then share it here.</p>`;
    } else {
      const recipes = await api("/api/recipes");
      const mine = recipes.filter((r) => r.is_mine === true && r.source !== "test");   // only shareable: owned + non-test
      pick.innerHTML = mine.length
        ? `<ul class="ct-list">${mine.map((r) => `<li><button class="ct-opt" data-pick-recipe="${esc(r.id)}">
            ${r.image ? `<img class="ct-thumb" src="/${esc(r.image)}" alt="" onerror="this.remove()">` : `<span class="ct-thumb none"></span>`}
            <span class="ct-opt-main"><span class="ct-opt-name">${esc(r.name)}</span></span></button></li>`).join("")}</ul>`
        : `<p class="fs-empty">No recipes of your own yet to share.</p>`;
    }
  } catch (e) {
    if (e.message !== "__auth__") pick.innerHTML = `<p class="fs-empty">Couldn&rsquo;t load — try again.</p>`;
  }
}

function selectPick(type, rawId, el) {
  composeState = {
    type,
    cook_log_id: type === "cook" ? Number(rawId) : null,
    recipe_id: type === "recipe" ? rawId : null,
  };
  document.querySelectorAll(".ct-opt").forEach((o) => o.classList.remove("selected"));
  el.classList.add("selected");
  const submit = document.querySelector("[data-compose-submit]");
  if (submit) submit.disabled = false;
}

async function submitCompose() {
  const submit = document.querySelector("[data-compose-submit]");
  const errEl = document.querySelector("[data-compose-err]");
  const capEl = document.querySelector("[data-compose-caption]");
  const caption = ((capEl && capEl.value) || "").trim();
  const body = {};
  if (composeState && composeState.type === "cook" && composeState.cook_log_id != null) body.cook_log_id = composeState.cook_log_id;
  else if (composeState && composeState.type === "recipe" && composeState.recipe_id != null) body.recipe_id = composeState.recipe_id;
  else { if (errEl) errEl.textContent = "Pick something to share first."; return; }   // exactly-one guard (client)
  if (caption) body.caption = caption;
  if (submit) submit.disabled = true;
  const res = await sendJSON("POST", "/api/shares", body);
  if (res.ok) { closeCompose(); await renderFeed(); return; }   // returns {id} only -> refetch, don't reconstruct
  if (errEl) errEl.textContent = (res.data && res.data.error) || "Couldn't share — try again.";
  if (submit) submit.disabled = false;
}

/* ---- comment add / delete + unshare (thin client; the server authorizes each) ---- */
async function submitComment(form) {
  const postId = form.dataset.commentForm;
  const input = form.querySelector("input[name=body]");
  const body = (input.value || "").trim();
  if (!body || body.length > FEED_COMMENT_MAX) return;
  input.disabled = true;
  const res = await sendJSON("POST", `/api/posts/${postId}/comments`, { body });
  input.disabled = false;
  if (res.ok && res.data) {
    const thread = form.closest(".fp").querySelector(".fp-thread");
    thread.insertAdjacentHTML("beforeend", feedComment(res.data));   // append the returned comment, no refetch
    input.value = "";
    input.focus();
  }
}

async function deleteComment(id, el) {
  const res = await sendJSON("DELETE", `/api/comments/${id}`);
  if (res.ok) { const row = el.closest(".fc"); if (row) row.remove(); }
}

async function unshare(id, el) {
  const res = await sendJSON("DELETE", `/api/shares/${id}`);
  if (res.ok) { const card = el.closest(".fp"); if (card) card.remove(); }
}

// Delegated handlers — attached ONCE at module load; they survive the feed view's innerHTML re-renders.
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-compose-open]")) { openCompose(); return; }
  if (e.target.closest("[data-compose-close]") || (e.target.classList && e.target.classList.contains("compose-overlay"))) { closeCompose(); return; }
  const tab = e.target.closest("[data-compose-tab]");
  if (tab) { loadComposePick(tab.dataset.composeTab); return; }
  const pc = e.target.closest("[data-pick-cook]");
  if (pc) { selectPick("cook", pc.dataset.pickCook, pc); return; }
  const pr = e.target.closest("[data-pick-recipe]");
  if (pr) { selectPick("recipe", pr.dataset.pickRecipe, pr); return; }
  if (e.target.closest("[data-compose-submit]")) { submitCompose(); return; }
  const un = e.target.closest("[data-unshare]");
  if (un) { unshare(un.dataset.unshare, un); return; }
  const cd = e.target.closest("[data-comment-delete]");
  if (cd) { deleteComment(cd.dataset.commentDelete, cd); return; }
});
document.addEventListener("submit", (e) => {
  const form = e.target.closest("[data-comment-form]");
  if (form) { e.preventDefault(); submitComment(form); }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && document.querySelector(".compose-overlay")) closeCompose();
});
document.addEventListener("input", (e) => {
  const cap = e.target.closest("[data-compose-caption]");
  if (cap) { const n = document.querySelector("[data-cap-count]"); if (n) n.textContent = `${cap.value.length}/${FEED_CAPTION_MAX}`; }
});
