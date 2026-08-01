"use strict";
// Stage 4 build 3b-ii — the backdate submit orchestrator. The load-bearing test is RETRY-HOLDS-THE-ID:
// after a photo failure, a retry must re-attach to the SAME cook and NOT re-log it (a re-log = duplicate
// cook). The DOM/network wiring lives in app.js (browser-tested); this covers the pure sequencing.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { makeBackdateSubmit, isStageableImage } from "../../static/backdate-submit.js";

test("retry after a photo failure does NOT re-log the cook (the id is held)", async () => {
  let cookCalls = 0, attachAttempts = 0;
  const s = makeBackdateSubmit({
    logCook: async () => { cookCalls++; return { ok: true, cookId: 42 }; },
    attachPhotos: async (cookId, staged) => {
      attachAttempts++;
      assert.equal(cookId, 42, "always attaches to the same held cook");
      return attachAttempts === 1 ? staged.slice() : [];   // 1st attempt: all fail; retry: all succeed
    },
  });
  const staged = [{ id: "a" }, { id: "b" }];

  const r1 = await s.run(staged);
  assert.equal(r1.status, "photos-failed");
  assert.deepEqual(r1.failed, staged);

  const r2 = await s.run(r1.failed);                        // RETRY with the failed subset
  assert.equal(r2.status, "done");
  assert.equal(cookCalls, 1, "the cook was logged EXACTLY once across the retry");
  assert.equal(attachAttempts, 2);
});

test("a cook-create failure holds no id, so the next run retries the cook", async () => {
  let cookCalls = 0;
  const s = makeBackdateSubmit({
    logCook: async () => { cookCalls++; return cookCalls === 1 ? { ok: false, error: "nope" } : { ok: true, cookId: 7 }; },
    attachPhotos: async () => [],
  });
  const r1 = await s.run([{ id: "a" }]);
  assert.equal(r1.status, "cook-failed");
  assert.equal(r1.error, "nope");

  const r2 = await s.run([{ id: "a" }]);                    // cook wasn't held -> this run re-logs it
  assert.equal(r2.status, "done");
  assert.equal(cookCalls, 2);
});

test("no staged photos -> done after logging the cook once (photoless path never attaches)", async () => {
  let cookCalls = 0;
  const s = makeBackdateSubmit({
    logCook: async () => { cookCalls++; return { ok: true, cookId: 1 }; },
    attachPhotos: async () => { throw new Error("attach must not be called with no staged photos"); },
  });
  const r = await s.run([]);
  assert.equal(r.status, "done");
  assert.equal(cookCalls, 1);
});

test("reset() clears the held id so the next submit logs a fresh cook", async () => {
  let cookCalls = 0;
  const s = makeBackdateSubmit({
    logCook: async () => { cookCalls++; return { ok: true, cookId: cookCalls }; },
    attachPhotos: async () => [],
  });
  await s.run([]);
  assert.equal(s.cookId(), 1);
  s.reset();
  assert.equal(s.cookId(), null);
  await s.run([]);
  assert.equal(cookCalls, 2, "after reset the next run logs a new cook");
});

// --- staging gate (3b-ii add): reject non-images BEFORE they stage, matching the server allowlist ---

test("isStageableImage accepts the allowlisted image types (incl. HEIC by type and by extension)", () => {
  for (const [type, name] of [
    ["image/jpeg", "a.jpg"], ["image/png", "a.png"], ["image/webp", "a.webp"],
    ["image/heic", "a.heic"], ["image/heif", "a.heif"],
  ]) assert.ok(isStageableImage({ type, name }), `${type} should stage`);
  // macOS often hands HEIC with an EMPTY type -> the extension carries it
  assert.ok(isStageableImage({ type: "", name: "IMG_0421.HEIC" }), "empty-type HEIC by extension");
  assert.ok(isStageableImage({ type: "", name: "snap.jpeg" }), "empty-type JPEG by extension");
});

test("isStageableImage rejects non-images and non-allowlisted image types", () => {
  for (const [type, name] of [
    ["application/pdf", "a.pdf"], ["text/plain", "a.txt"], ["video/mp4", "a.mp4"],
    ["image/gif", "a.gif"], ["image/bmp", "a.bmp"], ["image/svg+xml", "a.svg"], ["image/avif", "a.avif"],
  ]) assert.ok(!isStageableImage({ type, name }), `${type} should NOT stage`);
  assert.ok(!isStageableImage({ type: "", name: "notes.pdf" }), "empty type + wrong extension -> reject");
  assert.ok(!isStageableImage({}), "no type, no name -> reject");
});

test("the client staging gate stays in sync with images.ALLOWED_INPUT_FORMATS", () => {
  const py = fs.readFileSync(path.join(import.meta.dirname, "../../images.py"), "utf8");
  const m = py.match(/ALLOWED_INPUT_FORMATS\s*=\s*frozenset\(\{([^}]*)\}\)/);
  assert.ok(m, "ALLOWED_INPUT_FORMATS block not found in images.py");
  const formats = new Set([...m[1].matchAll(/"([A-Z]+)"/g)].map((x) => x[1]));
  assert.deepEqual(formats, new Set(["JPEG", "PNG", "WEBP", "HEIF"]),
    "server allowlist changed — update isStageableImage's MIME/ext sets (and this test) to match");
});
