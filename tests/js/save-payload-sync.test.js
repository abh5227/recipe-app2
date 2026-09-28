"use strict";
// Cross-language guard: tests/fixtures/save-roundtrip.json is CAPTURED from static/save-payload.js
// and the Python suite PUTs those exact payloads. If the client's builders change and the fixture
// is not regenerated, this goes red before the Python side can silently drift from the real editor.
//
// That drift is the gap previews/save-path-scoping.md found: 20-plus PUT tests in the Python suite,
// every payload a hand-written literal, not one of them the shape the editor actually sends. The
// save could destroy a column on every real row and stay green.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { ingToPayload, stepToPayload } from "../../static/save-payload.js";

const FIX = JSON.parse(
  fs.readFileSync(path.join(import.meta.dirname, "../fixtures/save-roundtrip.json"), "utf8"));

test("the fixture covers every row shape the save has to survive", () => {
  const shapes = FIX.rows.map((r) => r.shape).join(" | ");
  for (const needed of ["heading", "NULL label", "linked", "note row", "duplicate name AND qty",
                        "canonicalizes"]) {
    assert.ok(shapes.includes(needed), `no fixture row covers "${needed}"`);
  }
  assert.ok(FIX.rows.length >= 11, `expected the full shape set, got ${FIX.rows.length}`);
});

test("ingToPayload still produces exactly what the fixture records", () => {
  for (const { shape, row, payload } of FIX.rows) {
    assert.deepEqual(ingToPayload(row), payload, `ingToPayload drifted for: ${shape}`);
  }
});

test("stepToPayload still produces exactly what the fixture records", () => {
  for (const { row, payload } of FIX.steps) {
    assert.deepEqual(stepToPayload(row), payload);
  }
});

test("the client canonicalizes the unit on the way out, which the server key must expect", () => {
  const row = FIX.rows.find((r) => r.shape.includes("canonicalizes"));
  assert.equal(row.row.unit, "teaspoon");
  assert.equal(row.payload.unit, "tsp");
});

test("a step's line breaks survive the payload builder", () => {
  const s = FIX.steps.find((x) => (x.payload.text || "").includes("AIR FRYER"));
  assert.ok(s.payload.text.includes("\n\n"), "the blank line was folded away");
});

// --------------------------------------------------------------------------------------------- //
// Option C commit 1: the row id goes back
// --------------------------------------------------------------------------------------------- //
test("every ingredient payload carries its row id", () => {
  for (const { shape, row, payload } of FIX.rows) {
    assert.equal(payload.id, row.id, `no id went back for: ${shape}`);
  }
});

test("every step payload carries its row id, heading or not", () => {
  for (const { row, payload } of FIX.steps) {
    assert.equal(payload.id, row.id);
  }
});

test("a row the user just added sends id: null rather than omitting the key", () => {
  // The templates addIngredient / addStep splice in, minus the fields the builders do not read.
  const fresh = { id: null, is_heading: 0, quantity: "1", unit: "pinch", label: "saffron", note: "" };
  assert.equal("id" in ingToPayload(fresh), true);
  assert.equal(ingToPayload(fresh).id, null);
  assert.equal(stepToPayload({ id: null, is_heading: 0, text: "Rest." }).id, null);
  assert.equal(stepToPayload({ id: null, is_heading: 1, text: "MAKE IT" }).id, null);
});

test("a row with no id at all still sends id: null", () => {
  // An older draft, or any row built before the template carried the key. undefined would serialize
  // the key away entirely and the server would have to tell "absent" from "new".
  assert.equal(ingToPayload({ is_heading: 0, quantity: "", unit: "", label: "salt" }).id, null);
  assert.equal(ingToPayload({ is_heading: 1, heading: "FOR THE DOUGH" }).id, null);
  assert.equal(stepToPayload({ is_heading: 0, text: "Rest." }).id, null);
});

test("a non-heading step goes back as an object, not a bare string", () => {
  // The shape change the server's _step_parts exists to absorb. A string has nowhere to put an id.
  const out = stepToPayload({ id: 12, is_heading: 0, text: "Whisk it." });
  assert.equal(typeof out, "object");
  assert.deepEqual(out, { id: 12, text: "Whisk it." });
});

// --------------------------------------------------------------------------------------------- //
// Migration 052: a heading row may carry a dormant name, so the title must be read, not guessed
// --------------------------------------------------------------------------------------------- //
test("a heading sends its TITLE even when the row still holds a dormant name", () => {
  // ⚠️ THE TRAP THIS REPLACED. ingToPayload read `x.heading || x.label || x.raw_text`. Once a
  // heading keeps the line's label, that middle arm wins whenever `heading` is unset and sends the
  // INGREDIENT NAME back as the section title, renaming the heading on the next save.
  const converted = { id: 7, is_heading: 1, heading: "FOR THE BRINE", label: "kosher salt",
                      raw_text: "1 teaspoon kosher salt", qty: "1 teaspoon" };
  assert.deepEqual(ingToPayload(converted), { id: 7, heading: "FOR THE BRINE" });
});

test("a heading with no title column falls back to raw_text, never to the label", () => {
  // The 223 pre-052 heading rows: heading NULL, title in raw_text, label NULL. And the shape that
  // would have gone wrong: heading NULL with a label present.
  assert.equal(ingToPayload({ id: 8, is_heading: 1, heading: null,
                              raw_text: "FOR THE SAUCE:" }).heading, "FOR THE SAUCE:");
  assert.equal(ingToPayload({ id: 9, is_heading: 1, heading: null, label: "kosher salt",
                              raw_text: "FOR THE SAUCE:" }).heading, "FOR THE SAUCE:");
});

test("a heading payload carries the title and nothing else", () => {
  // The hidden columns are the SERVER's business: it keeps them from the stored row it is updating.
  // The client cannot carry raw_text anyway, and 87% of live lines have one richer than their name.
  const out = ingToPayload({ id: 7, is_heading: 1, heading: "FOR THE BRINE", label: "salt",
                             qty: "1 tsp", quantity: "1", unit: "tsp", note: "flaky" });
  assert.deepEqual(Object.keys(out).sort(), ["heading", "id"]);
});
