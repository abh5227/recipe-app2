"use strict";
// Andy's call on the round B click-through: Edit mode shows the FIRST amount only, with the second
// behind an expand, and "Save, Undo and the 'your changes' mark behave exactly as they do now".
//
// That last clause is the thing worth proving, and it is provable in three parts:
//   1. the collapsed toggle still SAYS what the row holds, so nothing is hidden in silence;
//   2. the draft-only `_secondOpen` flag cannot reach the wire, so a save sends what it sent
//      before, which is what makes the diff (and so the "your changes" mark) unchanged;
//   3. opening the field does not mark the draft dirty, so the Save bar and Undo are untouched
//      until the cook actually types.
//
// 1 and 2 run the real functions. 3 reads the SOURCE of app.js, which is not node-importable (it
// touches document at module scope) — the same approach tests/js/note-title-wiring.test.js takes,
// and a weaker test than running it, which is why 1 and 2 carry the weight.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { secondToggle } from "../../static/ingredient-row.js";
import { ingToPayload } from "../../static/save-payload.js";

const APP = fs.readFileSync(path.join(import.meta.dirname, "../../static/app.js"), "utf8");

function body(name) {
  const at = APP.indexOf(`function ${name}(`);
  assert.ok(at !== -1, `${name} not found in app.js`);
  const open = APP.indexOf("{", APP.indexOf(")", at));
  let depth = 0;
  for (let i = open; i < APP.length; i++) {
    if (APP[i] === "{") depth++;
    else if (APP[i] === "}" && --depth === 0) return APP.slice(open, i + 1);
  }
  throw new Error(`unbalanced braces in ${name}`);
}

test("collapsed, the toggle says what the row holds", () => {
  assert.deepEqual(secondToggle({ secondary_measure: "2 sticks" }),
                   { open: false, value: "2 sticks", has: true, label: "+ 2 sticks" });
});

test("with no second amount it offers to add one", () => {
  for (const row of [{}, { secondary_measure: "" }, { secondary_measure: "   " }, null]) {
    const t = secondToggle(row);
    assert.equal(t.label, "+ second amount");
    assert.equal(t.has, false);
    assert.equal(t.open, false);
  }
});

test("two backups in one slot are both named on the toggle", () => {
  assert.equal(secondToggle({ secondary_measure: "8 tablespoons / 113 grams" }).label,
               "+ 8 tablespoons / 113 grams");
});

test("_secondOpen is the only thing the toggle changes, and it opens the field", () => {
  const row = { secondary_measure: "2 sticks", _secondOpen: true };
  assert.equal(secondToggle(row).open, true);
  assert.equal(secondToggle(row).label, "+ 2 sticks");   // the value is unchanged by opening it
});

// ⚠️ THIS IS THE ONE THAT KEEPS "your changes" HONEST. The mark is diff(baseline, current rows),
// so it moves only if a SAVE sends something different. ingToPayload names every key it sends, so
// a draft-only flag cannot ride along — and this asserts it rather than trusting the shape.
test("a draft-only flag never reaches the wire, so a save is byte-identical", () => {
  const plain = { id: 7, quantity: "1", unit: "cup", secondary_measure: "2 sticks",
                  label: "butter", note: "" };
  const open = { ...plain, _secondOpen: true, _noteOpen: true };
  assert.deepEqual(ingToPayload(open), ingToPayload(plain));
  assert.equal("_secondOpen" in ingToPayload(open), false);
  assert.equal(ingToPayload(open).secondary_measure, "2 sticks");
});

test("clearing the field still sends the empty string, which is what stores NULL", () => {
  const row = { id: 7, quantity: "1", unit: "cup", secondary_measure: "", label: "butter" };
  assert.equal(ingToPayload(row).secondary_measure, "");
  assert.equal("secondary_measure" in ingToPayload(row), true);
});

test("opening the field does NOT mark the draft dirty", () => {
  const src = body("openIngSecond");
  assert.match(src, /_secondOpen\s*=\s*true/);
  assert.match(src, /rerenderEditIngredients\(\)/);
  assert.match(src, /focusIngField\(i,\s*"second"\)/);
  assert.equal(/markDirty/.test(src), false,
               "openIngSecond must not markDirty — Save and Undo stay untouched until a keystroke");
});

test("the row renders the toggle when closed and the field when open", () => {
  const src = body("amountZoneHTML");
  assert.match(src, /secondToggle\(x\)/);
  assert.match(src, /data-inline-edit-second/);
  assert.match(src, /secondCell\(i,\s*x\.secondary_measure\)/);
});

test("the click dispatcher reaches openIngSecond", () => {
  assert.match(APP, /\[data-inline-edit-second\][\s\S]{0,120}openIngSecond\(/);
});

// The field itself still writes to the same draft key it always did, so the save path below it is
// the one already covered by tests/js/save-payload-sync.test.js.
test("the field writes to secondary_measure", async () => {
  const { writeIngField } = await import("../../static/ingredient-row.js");
  const row = {};
  writeIngField(row, "second", "1 block");
  assert.equal(row.secondary_measure, "1 block");
});
