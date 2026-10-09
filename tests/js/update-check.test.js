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
  assert.match(APP, /\[data-update-reload\][\s\S]{0,160}if \(!updateWaiting\(\)\) location\.reload\(\)/);
  assert.match(APP, /function updateWaiting\(\) \{\s*return !!\(view && view\.editMode && view\.dirty\);/);
  const markDirty = APP.slice(APP.indexOf("function markDirty("), APP.indexOf("function markDirty(") + 400);
  assert.match(markDirty, /paintUpdateBar\(\)/);
  const paint = APP.slice(APP.indexOf("function paintRecipe("));
  assert.match(paint.slice(0, paint.indexOf("\n}\n")), /paintUpdateBar\(\)/);
});
