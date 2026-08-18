"use strict";

import {
  formatAmount, group, scaleQty, abbrevUnits, canonicalizeUnit, amountText, weightText, toUnicodeFractions,
} from "./scaler.js";
import { headingText, toggleRowType, nonEmptyRows, writeIngField } from "./ingredient-row.js";
import { nonEmptySteps, focusIndexAfterRemove, writeStepField } from "./step-row.js";
import { insertIndexFor } from "./row-insert.js";
import { removedInsertIndex } from "./annotation-place.js";
import { feedRelTime, feedDateShort } from "./feedtime.js";
import { isToMake } from "./tomake.js";
import { uploadErrorHTML } from "./upload-status.js";
import { makeBackdateSubmit, isStageableImage } from "./backdate-submit.js";
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
      // Derived "to make" mark (client-only): an owned, never-cooked recipe fills the otherwise-empty
      // .rc-stats slot with a quiet "Uncooked" whisper. Gated on is_mine via isToMake() — NOT on count
      // alone — so another user's uncooked recipe gets no mark. Never both a stats line and the mark
      // (it fills only the empty slot); never a category tag (see static/tomake.js).
      const uncooked = (!statsLine && isToMake(r)) ? `<span class="rc-uncooked">Uncooked</span>` : "";
      const isTest = r.source === "test";
      return `<a class="recipe-card${isTest ? " is-test" : ""}" href="#/recipe/${encodeURIComponent(r.id)}">
                ${photo(r, "thumb")}
                <div class="rc-body">
                  <p class="rc-name">${esc(r.name)}${isTest ? ` <span class="test-badge">Test</span>` : ""}</p>
                  <p class="rc-meta">${bits}</p>
                  ${statsLine}${uncooked}
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
      <div class="site-head-actions">${bulkTest}<a class="btn ghost" href="#/feed">Cooking</a><a class="btn new-recipe" href="#/new">+ New recipe</a>${
        CURRENT_USER ? `<span class="site-user">${esc(CURRENT_USER.display_name || CURRENT_USER.email)}<button type="button" data-logout>Sign out</button></span>` : ""
      }</div>
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

// O-c-1: index the current-vs-original annotations (view.data.annotations) by heading-EXCLUDED new_pos,
// per kind, for the PRESENT-position cases the reading view renders (amount/name modified, added). A
// removed entry has no current row to attach to (new_pos=null), so it is collected SEPARATELY and placed
// by `section` (stage 3, see insertRemovedRows); heading entries aren't rendered here. A single new_pos may
// carry BOTH an amount and a name edit; they're grouped into one slot so a row shows both.
function annotationIndex(anns) {
  const ing = new Map();
  const step = new Map();
  const removedIng = [];
  const removedStep = [];
  for (const a of (anns || [])) {
    if (a.type === "removed") {
      // no new_pos to key on — kept as a flat list, placed at its original section's bottom. Ordered by
      // old_pos so several removals out of one section keep their original relative order. (kind
      // "heading" falls through both branches: a removed HEADING is not rendered in the ledger.)
      if (a.kind === "ingredient") removedIng.push(a);
      else if (a.kind === "step") removedStep.push(a);
      continue;
    }
    if (a.new_pos == null) continue;
    if (a.kind === "ingredient") {
      const slot = ing.get(a.new_pos) || {};
      if (a.type === "added") slot.added = a;
      else if (a.type === "modified" && (a.field === "amount" || a.field === "name")) slot[a.field] = a;
      ing.set(a.new_pos, slot);
    } else if (a.kind === "step") {
      const slot = step.get(a.new_pos) || {};
      if (a.type === "added") slot.added = a;
      else if (a.type === "modified") slot.mod = a;
      step.set(a.new_pos, slot);
    }
    // kind === "heading": not rendered in the reading ledger — ignored.
  }
  const byOldPos = (x, y) => (x.old_pos == null ? 0 : x.old_pos) - (y.old_pos == null ? 0 : y.old_pos);
  removedIng.sort(byOldPos);
  removedStep.sort(byOldPos);
  return { ing, step, removedIng, removedStep };
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
// there is nothing to map over). `text` is the RAW combined "qty label" line and `label` is the name, so
// the qty is what precedes the label; it renders through amountText(_, 1) to match the abbreviated
// ledger display (the entry's text is unabbreviated). Same .amount-cell/.qty + .iname structure as a
// live row, so it sits in the ledger grid; .was gives it the shared 1px strike.
function removedIngredientRow(e) {
  const text = String(e.text || "");
  const label = String(e.label || "");
  const qty = (label && text.endsWith(label)) ? text.slice(0, text.length - label.length).trim() : "";
  const shown = qty ? amountText(qty, 1) : "";
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
// words, leave shared words as plain print. Token LCS on whitespace-split words. Order follows the walk:
// a divergence emits the struck old word(s) then the inked new word(s), shared runs stay plain. Falls back
// to a whole-field strike+ink when the two share NO words (LCS empty) — cleaner than striking every token.
// Every token is esc()'d before it reaches the DOM (no raw HTML from names). Kept inline (not a module).
function _wordLcsWalk(a, b) {
  const n = a.length, m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ t: "eq", w: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: "del", w: a[i] }); i++; }
    else { out.push({ t: "ins", w: b[j] }); j++; }
  }
  while (i < n) out.push({ t: "del", w: a[i++] });
  while (j < m) out.push({ t: "ins", w: b[j++] });
  return out;
}
function wordDiffHTML(fromStr, toStr) {
  const a = String(fromStr || "").split(/\s+/).filter(Boolean);
  const b = String(toStr || "").split(/\s+/).filter(Boolean);
  const walk = _wordLcsWalk(a, b);
  if (!walk.some((x) => x.t === "eq")) {                 // no shared word -> whole-field strike+ink
    return `<span class="was">${esc(fromStr || "")}</span> <span class="fix">${esc(toStr || "")}</span>`;
  }
  const parts = [];                                      // coalesce consecutive same-type tokens
  for (const x of walk) {
    const last = parts[parts.length - 1];
    if (last && last.t === x.t) last.w.push(x.w);
    else parts.push({ t: x.t, w: [x.w] });
  }
  return parts.map((p) => {
    const text = esc(p.w.join(" "));
    if (p.t === "del") return `<span class="was">${text}</span>`;
    if (p.t === "ins") return `<span class="fix">${text}</span>`;
    return text;
  }).join(" ");
}

function plainRow(row, ann) {
  // Guard (belt-and-suspenders): never render an empty row as a bare divider line, even if one somehow
  // reaches the reading view — a heading with no text, or a line with no name, is skipped entirely.
  if (row.is_heading) return (row.raw_text || "").trim() ? `<li class="group">${esc(row.raw_text)}</li>` : "";
  if (!(row.label || row.raw_text || "").trim()) return "";
  // Added ingredient: the whole current line in the hand ink, "+"-prefixed (see li.added CSS).
  if (ann && ann.added) return `<li class="added">${ledgerCells(row.qty, row.grams_per_ml)}<span class="iname">${lineBodyHTML(row)}</span></li>`;
  const amt = ann && ann.amount, nm = ann && ann.name;
  // Amount edit stacks the struck ABBREVIATED original over the Kalam ink value INSIDE the 5rem cell
  // (li.edited); amountText(_, 1) abbreviates the authored amounts exactly like the ledger.
  const amountCell = amt
    ? `<span class="amount-cell"><span class="qty"><span class="was">${esc(amountText(amt.from, 1))}</span><span class="fix">${esc(amountText(amt.to, 1))}</span></span></span>`
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
  const { ing, removedIng } = annotationIndex(view.data.annotations);   // O-c-1: edits keyed by new_pos + removals
  let i = 0;                                                 // heading-EXCLUDED index == snapshot_diff new_pos
  // Headings are tracked alongside each row so a removed entry can find its section (exact-string match on
  // the heading's raw_text). The counter advances ONLY on real non-heading rows — synthesized removed rows
  // are spliced in afterwards and never touch it, so every other anchor stays aligned.
  const items = view.data.ingredients.map((row) => ({
    isHeading: !!row.is_heading,
    headingText: row.is_heading ? (row.raw_text || "") : null,
    html: row.is_heading ? plainRow(row) : plainRow(row, ing.get(i++)),
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

// Render a step. Non-heading steps arrive as tagged spans (Phase 1d): "scale" spans are
// rescaled live with the 1a scaler (so they format identically to the ingredient list);
// "plain" spans are linkified (and may contain [[ingredient]] links). Falls back to raw
// text if a payload has no spans.
function renderStepRow(row, ann) {
  if (row.is_heading) return `<li class="group">${esc(row.text)}</li>`;
  // O-c-1: an added step -> the whole line in the hand ink (NO "+" marker — a full paragraph of ink
  // against printed prose announces itself; see the .step-add note in styles.css); a reworded step ->
  // the struck original + the Kalam correction. Both are plain prose (no scaling/abbreviation — that's
  // amount-only).
  if (ann && ann.added) return `<li class="step"><div class="step-body"><span class="step-add">${esc(row.text)}</span></div></li>`;
  if (ann && ann.mod) return `<li class="step"><div class="step-body">${wordDiffHTML(ann.mod.from, ann.mod.to)}</div></li>`;
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

// O-c-1: render the step list with its annotation layer. Own 0-based li.step counter (heading-EXCLUDED,
// a SEPARATE index space from ingredients) == snapshot_diff step new_pos. Empty annotations -> byte-identical.
function renderStepsList(steps) {
  const { step, removedStep } = annotationIndex(view.data.annotations);
  let i = 0;   // heading-EXCLUDED step index (its OWN sequence); synthesized removals never advance it
  const items = steps.map((row) => ({
    isHeading: !!row.is_heading,
    headingText: row.is_heading ? (row.text || "") : null,
    html: row.is_heading ? renderStepRow(row) : renderStepRow(row, step.get(i++)),
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
// The grip is LIVE as of C2: the whole row is draggable and the grip is its visual handle (the drag
// listeners are delegated, so the grip itself still carries no handler). It stays aria-hidden because
// the drag is mouse-only — there is no keyboard path for it to announce. See ROADMAP, "Known
// limitations & tech debt".
function editStepRowTools(i) {
  return `<span class="rtools">
    <span class="rbtn grip" title="Drag to reorder" aria-hidden="true">${ING_GRIP}</span>
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
  // C2: draggable on the whole row, as on the ingredient side. Measured with trusted CDP input: a
  // draggable ancestor does not hijack text selection inside a ProseMirror host, and dragstart fires
  // from the grip but not from the prose — so the editor keeps its own selection and drag behaviour.
  if (row.is_heading) return `<li class="group step-edit" draggable="true">${editStepHeadingField(i, row.text)}${tools}</li>`;
  return `<li class="step step-edit" draggable="true"><div class="step-editor-host" data-i="${i}"></div>${tools}</li>`;
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
  return `<input type="text" class="ie e-step-heading" data-inline-edit-step="heading" data-i="${i}" value="${esc(text || "")}" placeholder="Section heading" aria-label="Section heading" spellcheck="false">`;
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
    const updatePill = editable ? `<button class="update-photo" type="button" aria-label="Update photo">Update photo</button>` : "";
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
      <img class="photo" src="/${esc(r.image)}" alt="${esc(r.name)}" loading="lazy"${brokenCollapse}>
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
  const canAdd = !!(data && data.is_editable);   // owner-only add-zone — same gate as the hero uploader (dishPhoto)
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
async function promotePhoto(id, rid) { const { ok } = await sendJSON("POST", `/api/photos/${id}/promote`, {}); if (ok) renderRecipe(rid); }
async function deletePhoto(id, rid)  { const { ok } = await sendJSON("DELETE", `/api/photos/${id}`, null);     if (ok) renderRecipe(rid); }
async function saveCaption(fig, rid) {
  const ta = fig.querySelector("[data-cap-input]");
  const { ok } = await sendJSON("PATCH", `/api/photos/${fig.dataset.photoId}`, { caption: ta ? ta.value.trim() : "" });
  if (ok) renderRecipe(rid);                               // blank clears it (server allows blank)
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
function closeRowMenu() {
  const m = app.querySelector(".row-menu");
  if (!m) return;
  const row = m.closest(".erow, li.step-edit");
  if (row) {
    row.classList.remove("menu-open");
    const trig = row.querySelector("[data-row-menu]");
    if (trig) trig.setAttribute("aria-expanded", "false");
  }
  m.remove();
}
// A stage 2: the real items. Stage 3 adds Add above / Add below above the separator.
// Labels are SHORT on purpose and must stay that way: .photo-menu's min-width is 140px (tuned for the
// album's "Make hero" / "Edit caption"), and the natural long forms overflow it — "Make an ingredient"
// wraps to two lines (46px vs 30px) and pushes the menu to 157px, undoing the point of a compact menu.
// "To heading" / "To ingredient" fit on one line in both directions. Text-only, no .mi glyph: the
// album's items all carry one, but no real icon exists for stage 3's add-above/add-below and inventing
// one is exactly what the fidelity rule forbids — a half-populated icon column is worse than none.
// The heading state is read from the DRAFT rather than passed in, so the label can never disagree with
// the row it belongs to (the menu is rendered at open time, after any re-render).
// B puts the two inserts FIRST, separated from the row's own actions by the same .sep the album menu
// uses before its destructive item: the top group acts on the LIST (add a neighbour), the bottom group
// acts on THIS row (retype it, delete it). Both labels fit on one line at min-width: 140px.
function rowMenuItemsHTML(kind, i) {
  const inserts = `<button type="button" data-rm-act="add-above">Add above</button>
    <button type="button" data-rm-act="add-below">Add below</button>
    <div class="sep"></div>`;
  if (kind === "step") {
    return `${inserts}<button type="button" class="danger" data-rm-act="delete">Delete</button>`;
  }
  const row = view.draft.ingredients[i];
  const toHeading = !(row && row.is_heading);
  return `${inserts}<button type="button" data-rm-act="toggle">${toHeading ? "To heading" : "To ingredient"}</button>`;
}
function openRowMenu(trigger, i, kind) {
  closePhotoMenu();                                        // single-open ACROSS both families
  closeRowMenu();
  const row = trigger.closest(".erow, li.step-edit");
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
  const row = e.target.closest(".erow, li.step-edit");
  if (!row) return false;
  const host = e.target.closest("[data-row-menu], .row-menu");
  if (!host) return false;
  const i = Number(host.dataset.i);
  const kind = host.dataset.rowMenu || host.dataset.rowKind;
  const trigger = e.target.closest("[data-row-menu]");
  if (trigger) { row.querySelector(".row-menu") ? closeRowMenu() : openRowMenu(trigger, i, kind); return true; }
  const item = e.target.closest("[data-rm-act]");
  if (!item) return false;
  const act = item.dataset.rmAct;
  closeRowMenu();
  // B: both lists share the index arithmetic (insertIndexFor) and differ only in which array is
  // measured and which adder runs. A null index means the row this menu claimed to belong to is not a
  // real row any more — do nothing rather than guess a position; see row-insert.js.
  if (act === "add-above" || act === "add-below") {
    const arr = kind === "step" ? view.draft.steps : view.draft.ingredients;
    const at = insertIndexFor(act === "add-below" ? "below" : "above", i, arr.length);
    if (at == null) return true;
    if (kind === "step") addStep(at); else addIngredient(false, at);   // always a NORMAL row
    return true;
  }
  if (kind === "ing"  && act === "toggle") { toggleIngredientHeading(i); return true; }
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
function ownerActionsHTML(r) {
  return `<button class="btn ghost sm" data-inline-edit-enter>✎ Edit</button>
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
  clearCookChip();   // 3b-iii: any pending "add photos?" offer is stale once we refetch/repaint
  albumReorder = null;   // 3d-iii: leaving reorder mode on any repaint (defensive; commit/cancel already clear it)
  const data = await api("/api/recipes/" + encodeURIComponent(rid));
  view = { slug: rid, data, scale: 1,
           pendingRating: null, undoneCook: null, editMode: false, draft: null, dirty: false };
  app.className = "page recipe-view";
  setCookCount(app, data.stats.cook_count);   // reserved R2 wear signal on the recipe root

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
  const photoSlot = dishPhoto(r, data.is_editable, data.photos);   // data.photos carries the is_hero caption (SHARED)
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
            ${editing ? ieNoteHTML(r) : (r.notes ? `<div class="notes"><strong>Note.</strong> ${esc(r.notes)}</div>` : "")}
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
// accumulation. No-ops when there's no editable Polaroid (dishPhoto only tags it when data.is_editable).
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

  // Trigger + "Try again" — SHARED. Trigger is the empty zone or the filled "Update photo" pill; err-retry
  // returns to rest without opening the picker (filled: removes the error overlay -> the photo shows again).
  wrap.addEventListener("click", (e) => {
    if (e.target.closest(".err-retry")) { rest(); return; }
    if (e.target.closest(filled ? ".update-photo" : ".upload-zone")) input.click();
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
// This is the FINAL shape of the ingredient cluster; C1 made the grip live.
function editIngRowTools(i) {
  return `<span class="divider" aria-hidden="true"></span><span class="rtools">
    <span class="rbtn grip" title="Drag to reorder" aria-hidden="true">${ING_GRIP}</span>
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
    return `<li class="erow group-row" draggable="true">
      ${ieCell("heading", i, headingText(x), "e-heading", "Section heading")}
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
  // C1: draggable on the WHOLE ROW, not the grip — measured with trusted CDP input, a draggable
  // ancestor does not hijack text selection inside a textarea, and the drag image is then the row
  // the user grabbed rather than a 24px handle. The below-note row is deliberately NOT draggable and
  // NOT a target: it belongs to the row above it and travels with it (the draft holds one object per
  // ingredient, note included), which is also why the drag indexes by li.erow and not by li.
  const main = `<li class="erow${noteOpen ? " has-note" : ""}" draggable="true">
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
  arr.splice(at_, 0, isHeading ? { is_heading: 1, heading: "", qty: "", quantity: "", unit: "", label: "", note: "", ingredient_id: null, raw_text: "" }
                               : { is_heading: 0, qty: "", quantity: "", unit: "", label: "", note: "", ingredient_id: null, raw_text: "" });
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
function paintDropBar(list, rows, before) {
  let bar = list.querySelector(".drop-bar");
  if (!bar) { bar = document.createElement("li"); bar.className = "drop-bar"; bar.setAttribute("aria-hidden", "true"); }
  if (before == null) list.appendChild(bar); else list.insertBefore(bar, rows[before]);
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
  document.querySelectorAll(".ingredient-list.edit .ghost-origin, #steps-list .ghost-origin")
    .forEach((el) => el.classList.remove("ghost-origin"));
  document.querySelectorAll(".ingredient-list.edit .drop-bar, #steps-list .drop-bar")
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
// its read-back, the pill drag image, the rAF-deferred .ghost-origin, draggable on the whole row,
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
function addStep(at) {
  const arr = view.draft.steps;
  const at_ = at == null ? arr.length : at;
  arr.splice(at_, 0, { is_heading: 0, text: "" });
  markDirty(); rerenderEditSteps();
  focusStepEditor(at_);
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
    steps: nonEmptySteps(view.draft.steps).map(stepToPayload),             // ditto — CLEARING a step's text deletes it
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
      const { ok, data } = await sendJSON("POST", `/api/recipes/${backdateRid}/cooked`, { date: iso });
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

function openBackdate(rid, statsEl, trigger) {
  backdateRid = rid;
  backdateStats = statsEl;
  backdateTrigger = trigger || null;
  bdClearStaged();                              // fresh add-a-photo area (rest invite)
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
  if (handleAlbumPhotoAction(e)) return;

  // 3d-iii: album reorder mode — enter / Done (commit via 3d-ii) / Cancel (discard)
  if (e.target.closest("[data-album-reorder]"))        { enterAlbumReorder();  return; }
  if (e.target.closest("[data-album-reorder-done]"))   { commitAlbumReorder(); return; }
  if (e.target.closest("[data-album-reorder-cancel]")) { cancelAlbumReorder(); return; }

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
    if (e.target.closest("[data-cook]")) {   // one-click log stays instant; then offer the photo chip (3b-iii)
      if (view) view.pendingRating = null;
      updateStats(stats, `/api/recipes/${rid}/cooked`, {}).then((s) => {
        if (s && s.cook_log_id != null) offerCookPhotoChip(stats, stats.dataset.rid, s.cook_log_id);
      });
      return;
    }
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
