"use strict";
// Pins the LOSSLESS ingredient<->heading toggle (Option A1). This is silent-regression-prone toggle
// logic, so it's unit-tested directly against the pure transform in static/ingredient-row.js.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { toggleRowType, headingText, nonEmptyRows, writeIngField } = require("../../static/ingredient-row.js");

test("ingredient -> heading -> ingredient is lossless (qty/name/note/link restored)", () => {
  const row = { is_heading: 0, qty: "2", label: "garlic cloves", note: "minced", ingredient_id: "garlic", raw_text: "2 garlic cloves" };

  toggleRowType(row);                              // -> heading
  assert.equal(row.is_heading, 1);
  assert.equal(headingText(row), "garlic cloves"); // heading seeded from the name
  assert.equal(row.qty, "2");                      // ingredient fields kept dormant, not deleted
  assert.equal(row.note, "minced");
  assert.equal(row.ingredient_id, "garlic");

  toggleRowType(row);                              // -> ingredient
  assert.equal(row.is_heading, 0);
  assert.equal(row.qty, "2");
  assert.equal(row.label, "garlic cloves");
  assert.equal(row.note, "minced");
  assert.equal(row.ingredient_id, "garlic");
});

test("null-label row (name in raw_text) survives a round-trip without clobbering the name", () => {
  const row = { is_heading: 0, qty: "1 tbsp", label: "", note: "", ingredient_id: null, raw_text: "olive oil" };
  const displayedName = (r) => r.label || r.raw_text;
  assert.equal(displayedName(row), "olive oil");

  toggleRowType(row);                              // -> heading
  assert.equal(headingText(row), "olive oil");
  toggleRowType(row);                              // -> ingredient
  assert.equal(row.is_heading, 0);
  assert.equal(row.qty, "1 tbsp");                 // qty preserved
  assert.equal(displayedName(row), "olive oil");   // name text intact (not clobbered)
});

test("heading -> ingredient -> heading preserves the heading text (back-compat raw_text heading)", () => {
  const row = { is_heading: 1, raw_text: "SAUCE" };   // a loaded heading with no dedicated `heading` field yet
  assert.equal(headingText(row), "SAUCE");            // back-compat display

  toggleRowType(row);                                 // -> ingredient
  assert.equal(row.is_heading, 0);
  assert.equal(row.label, "SAUCE");                   // born heading carries its text into the name
  toggleRowType(row);                                 // -> heading
  assert.equal(row.is_heading, 1);
  assert.equal(headingText(row), "SAUCE");
});

test("editing a heading then converting to ingredient keeps the dormant name (lossless), not the edited heading", () => {
  const row = { is_heading: 0, qty: "2", label: "garlic", note: "", ingredient_id: null, raw_text: "" };
  toggleRowType(row);              // -> heading (heading seeded 'garlic')
  row.heading = "SAUCE";           // user edits the heading text
  toggleRowType(row);              // -> ingredient
  assert.equal(row.label, "garlic");   // dormant name preserved, NOT overwritten by 'SAUCE'
  assert.equal(row.qty, "2");
});

test("nonEmptyRows drops blank ingredient + blank heading rows, keeps rows with content", () => {
  const rows = [
    { is_heading: 1, heading: "SAUCE" },                                  // keep (has heading text)
    { is_heading: 0, qty: "2", label: "garlic", note: "", ingredient_id: null },  // keep (has name)
    { is_heading: 0, qty: "", label: "", note: "", ingredient_id: null, raw_text: "" },  // drop (blank)
    { is_heading: 0, qty: "5", label: "   ", note: "", ingredient_id: null },     // drop (stray qty, no name)
    { is_heading: 1, heading: "   " },                                    // drop (blank heading)
    { is_heading: 1, raw_text: "TO SERVE" },                              // keep (back-compat heading text)
    { is_heading: 0, label: "", raw_text: "water" },                      // keep (name in raw_text)
  ];
  const kept = nonEmptyRows(rows);
  assert.deepEqual(kept.map((r) => (r.is_heading ? headingText(r) : (r.label || r.raw_text))),
    ["SAUCE", "garlic", "TO SERVE", "water"]);
});

test("writeIngField routes each key to the right field (name -> label); used by input buffering AND Esc-revert", () => {
  const row = { is_heading: 0, qty: "", label: "", note: "", heading: "", ingredient_id: null };
  writeIngField(row, "qty", "2 tbsp");
  writeIngField(row, "name", "olive oil");     // 'name' writes to label (the ingToPayload convention)
  writeIngField(row, "note", "extra virgin");
  writeIngField(row, "heading", "SAUCE");
  assert.equal(row.qty, "2 tbsp");
  assert.equal(row.label, "olive oil");
  assert.equal(row.note, "extra virgin");
  assert.equal(row.heading, "SAUCE");
  // Esc-revert semantics: writing the focus-time snapshot back restores the field exactly.
  writeIngField(row, "name", "olive oil, cold-pressed");   // simulate an edit
  writeIngField(row, "name", "olive oil");                 // revert to snapshot
  assert.equal(row.label, "olive oil");
});
