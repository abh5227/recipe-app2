"use strict";
// The reload bar (decisions-4, variant 1 of :8003/reload-prompt/). The pure half runs here. The
// wiring in app.js is read from its source, the approach second-amount-edit.test.js takes, because
// app.js touches document at module scope and cannot be imported in node.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pageCommit, heardCommit, updateBarHTML, hearingFetch, COMMIT_HEADER, UPDATE_WAIT }
  from "../../static/update-check.js";

const APP = fs.readFileSync(path.join(import.meta.dirname, "../../static/app.js"), "utf8");
const A = "a".repeat(40), B = "b".repeat(40);

test("equal commits, no bar", () => {
  const s = { page: A, updated: false };
  assert.equal(heardCommit(s, A), s);
  assert.equal(heardCommit(s, A).updated, false);
});

test("a different commit on an answer shows the bar", () => {
  assert.deepEqual(heardCommit({ page: A, updated: false }, B), { page: A, updated: true });
});

test("an answer that names no commit changes nothing", () => {
  const s = { page: A, updated: false };
  for (const v of [null, undefined, "", "   "]) assert.equal(heardCommit(s, v), s);
});

test("a page served with no commit takes the first one it hears, then compares", () => {
  const first = heardCommit({ page: "", updated: false }, A);
  assert.deepEqual(first, { page: A, updated: false });
  assert.equal(heardCommit(first, B).updated, true);
});

test("the server going back to the page's own commit takes the bar away again", () => {
  assert.deepEqual(heardCommit({ page: A, updated: true }, A), { page: A, updated: false });
});

test("the page reads its commit from the meta app.py writes", () => {
  const doc = { querySelector: (q) => (q === 'meta[name="app-commit"]'
    ? { getAttribute: () => ` ${A} ` } : null) };
  assert.equal(pageCommit(doc), A);
  assert.equal(pageCommit({ querySelector: () => null }), "");
  assert.equal(pageCommit(null), "");
});

test("with a change unsaved, the bar says so and its Reload is disabled", () => {
  const waiting = updateBarHTML(true);
  assert.match(waiting, /data-update-reload disabled/);
  assert.ok(waiting.includes(UPDATE_WAIT));
  const free = updateBarHTML(false);
  assert.equal(/disabled/.test(free), false);
  assert.equal(free.includes(UPDATE_WAIT), false);
  assert.match(free, /This page has been updated/);
});

test("every answer is heard and handed back untouched, and the check cannot break a request", async () => {
  const heard = [];
  const res = { headers: { get: (h) => (h === COMMIT_HEADER ? B : null) }, ok: true };
  const f = hearingFetch(async () => res, (c) => heard.push(c));
  assert.equal(await f("/api/recipes"), res);
  assert.deepEqual(heard, [B]);
  const angry = hearingFetch(async () => res, () => { throw new Error("no"); });
  assert.equal(await angry("/api/recipes"), res);
});

// ---- the wiring in app.js ---------------------------------------------------------------------
test("every fetch in app.js goes through the hearing fetch", () => {
  assert.match(APP, /const fetch = hearingFetch\(window\.fetch\.bind\(window\)/);
  // declared before anything calls it, so module start-up cannot reach the bare global
  const decl = APP.indexOf("const fetch = hearingFetch(");
  const firstCall = APP.search(/\bfetch\(/);
  assert.ok(decl !== -1 && decl < APP.indexOf("async function api("), "declared above api()");
  assert.ok(firstCall >= decl, "a fetch( call sits above the declaration");
});

test("Reload never runs while Edit mode holds a change, and the bar follows the dirty flag", () => {
  const click = APP.slice(APP.indexOf('if (!e.target.closest("[data-update-reload]")) return;'));
  const body = click.slice(0, click.indexOf("});"));
  assert.match(body, /if \(updateWaiting\(\)\) return;/);
  // a note the same click saved is waited for, and an editor still open after it stops the reload
  assert.match(body, /if \(noteWriteInFlight\(\)\) await noteSettled;/);
  assert.match(body, /if \(!updateWaiting\(\) && noteState\.editingId == null\) location\.reload\(\);/);
  assert.match(APP, /function updateWaiting\(\) \{\s*return !!\(view && view\.editMode && view\.dirty\);/);
  const markDirty = APP.slice(APP.indexOf("function markDirty("), APP.indexOf("function markDirty(") + 900);
  assert.match(markDirty, /paintUpdateBar\(\)/);
  // ⚠️ not only on the first change: the plan-ahead handlers set view.dirty and then call markDirty
  assert.match(markDirty, /if \(!view \|\| !view\.editMode\) return;/);
  assert.equal(/view\.dirty\) return/.test(markDirty.slice(0, markDirty.indexOf("view.dirty = true"))), false);
  const paint = APP.slice(APP.indexOf("function paintRecipe("));
  assert.match(paint.slice(0, paint.indexOf("\n}\n")), /paintUpdateBar\(\)/);
});

test("no other module fetches, so nothing can go around the hearing fetch", () => {
  const dir = path.join(import.meta.dirname, "../../static");
  const others = fs.readdirSync(dir).filter((f) => f.endsWith(".js") && f !== "app.js" && f !== "update-check.js")
    .filter((f) => /\bfetch\(/.test(fs.readFileSync(path.join(dir, f), "utf8")));
  assert.deepEqual(others, [], "these modules call fetch( directly and the reload bar never hears them");
});

test("the slot is the live region and the sticky element, made once, and sits under every modal", () => {
  assert.equal(/role=/.test(updateBarHTML(false)), false, "the bar carries no role; the slot is the live region");
  assert.match(APP, /slot\.setAttribute\("role", "status"\)/);
  assert.match(APP, /\nupdateSlot\(\);/, "the slot is made at start, empty");
  assert.match(APP, /if \(html === paintedBar\) return;/, "painted only when it would change");
  const CSS = fs.readFileSync(path.join(import.meta.dirname, "../../static/styles.css"), "utf8");
  const slot = CSS.match(/\.update-bar-slot \{([^}]*)\}/);
  assert.ok(slot, "no .update-bar-slot rule");
  assert.match(slot[1], /position: sticky; top: 0;/);
  const z = Number(slot[1].match(/z-index: (\d+)/)[1]);
  assert.ok(z < 40, `the slot's z-index ${z} must sit under the scrim's 40`);
  assert.equal(/position: sticky/.test(CSS.match(/\.update-bar \{([^}]*)\}/)[1]), false);
});
