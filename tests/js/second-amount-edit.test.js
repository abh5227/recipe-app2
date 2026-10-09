"use strict";
// Edit mode's second amount, drawn as C1 (Andy, 9 Oct, decisions-4): a small arrow beside the
// amount; closed, nothing else shows; open, the second-amount field(s) sit under the amount; the
// arrow looks filled in when a second amount exists. And the condition on all of it, from the round
// B click-through: "Save, Undo and the 'your changes' mark behave exactly as they do now".
//
// That condition is provable in three parts:
//   1. the arrow still SAYS whether the row holds a second amount, so nothing is hidden in silence;
//   2. the draft-only `_secondOpen` flag cannot reach the wire, and an untouched slot goes back
//      byte for byte, so a save sends what it sent before, which is what keeps the diff (and so the
//      "your changes" mark) unchanged;
//   3. opening or closing the arrow does not mark the draft dirty, so the Save bar and Cancel are
//      untouched until the cook actually types.
//
// 1 and 2 run the real functions. 3 reads the SOURCE of app.js, which is not node-importable (it
// touches document at module scope) — the same approach tests/js/note-title-wiring.test.js takes,
// and a weaker test than running it, which is why 1 and 2 carry the weight.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { secondToggle, secondLines, joinSecondLines, secondForSave, writeIngField }
  from "../../static/ingredient-row.js";
import { secondAmountParts } from "../../static/scaler.js";
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

test("the arrow knows whether the row holds a second amount", () => {
  assert.deepEqual(secondToggle({ secondary_measure: "2 sticks" }),
                   { open: false, value: "2 sticks", has: true });
  for (const row of [{}, { secondary_measure: "" }, { secondary_measure: "   " }, null]) {
    assert.deepEqual(secondToggle(row), { open: false, value: "", has: false });
  }
});

test("filled when there is a second amount, an outline when there is none, both ways open", () => {
  const src = body("secondCaret");
  assert.match(src, /open \? \(has \? "&#9662;" : "&#9663;"\) : \(has \? "&#9656;" : "&#9657;"\)/);
  const zone = body("amountZoneHTML");
  assert.match(zone, /second-arrow\$\{t\.has \? " has" : ""\}/);
  assert.match(zone, /secondCaret\(t\.has, t\.open\)/);
  // closed, nothing else shows: the fields are built only when the row is open
  assert.match(zone, /const fields = t\.open\s*\?/);
});

test("closed, the arrow's title and label carry the value, and it reports open or closed", () => {
  const zone = body("amountZoneHTML");
  assert.match(zone, /aria-expanded="\$\{t\.open\}"/);
  assert.match(zone, /title="\$\{t\.has \? "Second amount: " \+ esc\(t\.value\) : "Add a second amount"\}"/);
});

test("a row with several second-amount lines opens them all", () => {
  const row = { secondary_measure: "1 lb / 4 medium / or 2 long" };
  assert.deepEqual(secondLines(row), ["1 lb", "4 medium", "or 2 long"]);
  // the same lines the reading view stacks under the amount, at 1x
  assert.deepEqual(secondLines(row), secondAmountParts(row.secondary_measure, 1));
  const zone = body("amountZoneHTML");
  assert.match(zone, /secondLines\(x\)/);
  assert.match(zone, /lines\.map\(\(v, k\) => secondCell\(i, v, k, lines\.length\)\)/);
});

test("a row with no second amount opens one empty field", () => {
  for (const row of [{}, { secondary_measure: "" }, { secondary_measure: null }, null]) {
    assert.deepEqual(secondLines(row), [""]);
  }
});

test("the open fields join back to exactly the slot they were split from", () => {
  for (const v of ["2 sticks", "8 tablespoons / 113 grams", "1 lb / 4 medium / or 2 long",
                   "½ cup/113 grams", "about 1 bunch"]) {
    assert.equal(joinSecondLines(secondLines({ secondary_measure: v })), v);
  }
});

// ⚠️ THIS IS THE ONE THAT KEEPS "your changes" HONEST. The mark is diff(baseline, current rows),
// so it moves only if a SAVE sends something different. ingToPayload names every key it sends, so
// a draft-only flag cannot ride along — and this asserts it rather than trusting the shape.
test("ingToPayload is identical with the arrow open and closed", () => {
  for (const second of ["2 sticks", "1 lb / 4 medium / or 2 long", "", null]) {
    const closed = { id: 7, quantity: "1", unit: "cup", secondary_measure: second,
                     label: "butter", note: "" };
    const open = { ...closed, _secondOpen: true, _noteOpen: true };
    assert.deepEqual(ingToPayload(open), ingToPayload(closed));
    assert.equal("_secondOpen" in ingToPayload(open), false);
  }
});

test("an untouched slot goes back byte for byte, so a save that changed nothing sends nothing new", () => {
  for (const v of ["2 sticks", "8 tablespoons / 113 grams", "1 lb / 4 medium / or 2 long",
                   "½ cup/113 grams", ""]) {
    assert.equal(secondForSave(v), v);
  }
  assert.equal(secondForSave(null), "");
});

test("a line the cook cleared is left out on the way to the server", () => {
  assert.equal(secondForSave("1 lb /  / or 2 long"), "1 lb / or 2 long");
  assert.equal(secondForSave("1 lb / "), "1 lb");
  assert.equal(secondForSave(" / "), "");
  const row = { id: 7, quantity: "500", unit: "g", secondary_measure: "1 lb /  / or 2 long", label: "x" };
  assert.equal(ingToPayload(row).secondary_measure, "1 lb / or 2 long");
});

test("clearing the field still sends the empty string, which is what stores NULL", () => {
  const row = { id: 7, quantity: "1", unit: "cup", secondary_measure: "", label: "butter" };
  assert.equal(ingToPayload(row).secondary_measure, "");
  assert.equal("secondary_measure" in ingToPayload(row), true);
});

test("opening or closing the arrow does NOT mark the draft dirty", () => {
  const src = body("toggleIngSecond");
  assert.match(src, /row\._secondOpen = !row\._secondOpen/);
  assert.match(src, /rerenderEditIngredients\(\)/);
  assert.match(src, /focusIngField\(i,\s*"second"\)/);
  assert.equal(/markDirty/.test(src), false,
               "toggleIngSecond must not markDirty. Save and Cancel stay untouched until a keystroke");
});

test("the click dispatcher reaches toggleIngSecond", () => {
  assert.match(APP, /\[data-inline-edit-second\][\s\S]{0,120}toggleIngSecond\(/);
});

test("typing into one line writes the whole slot from every open line, in order", () => {
  const src = body("secondFieldsValue");
  assert.match(src, /\.closest\("\.second-fields"\)/);
  assert.match(src, /joinSecondLines\(/);
  assert.match(APP, /ing\.dataset\.inlineEditIng === "second" \? secondFieldsValue\(ing\) : ing\.value/);
  const row = {};
  writeIngField(row, "second", joinSecondLines(["1 lb", "5 medium"]));
  assert.equal(row.secondary_measure, "1 lb / 5 medium");
});
