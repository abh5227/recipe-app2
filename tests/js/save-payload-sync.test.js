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
  const s = FIX.steps.find((x) => String(x.payload).includes("AIR FRYER"));
  assert.ok(String(s.payload).includes("\n\n"), "the blank line was folded away");
});
