"use strict";
// Cross-language guard for round B's R3: an amount marked per person does not move with the
// servings. The rule lives on BOTH sides — import_cleanup.py decides which rows carry such an
// amount, and static/scaler.js refuses to scale one — and a word on one list only is the drift
// that makes a shared rule a comment claiming to be a rule. A figure the pass stores and the
// client then multiplies would be worse than leaving the clause in the name.
//
// Same shape as tests/js/unit-abbrev-sync.test.js: read both real files as text and compare the
// pattern SOURCE byte for byte.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { PER_SERVING, amountText } from "../../static/scaler.js";

const here = import.meta.dirname;

// ⚠️ THE WORD LIST IS WHAT IS COMPARED, NOT THE PATTERN TEXT. import_cleanup.py builds
// PER_SERVING_SRC by joining PER_SERVING_WORDS, so reading its source line back gives the
// concatenation expression rather than the pattern. The list is the thing that can drift anyway:
// the pattern around it is four characters either side.
// ⚠️ THE LIST LIVES IN units.py, AND IT USED TO LIVE IN import_cleanup.py WHERE ONLY ONE OF THE
// THREE CALLERS COULD SEE IT. stepscale.py has to lock the same figure in the METHOD text, and it
// did not: at 2x the ledger read "about ½ cup per person" while the step beside it read "1 cup rice
// per person". A fresh review found that.
test("the JS PER_SERVING words equal the Python PER_SERVING_WORDS, in the same order", () => {
  const py = fs.readFileSync(path.join(here, "../../units.py"), "utf8");
  const m = py.match(/PER_SERVING_WORDS = \(([\s\S]*?)\)\n/);
  assert.ok(m, "PER_SERVING_WORDS not found in units.py");
  const words = [...m[1].matchAll(/"([a-z]+)"/g)].map((x) => x[1]);
  assert.ok(words.length >= 5, `parsed too few Python words (${words.length})`);
  assert.equal(PER_SERVING.source, `\\bper\\s+(?:${words.join("|")})\\b`);
  assert.equal(PER_SERVING.flags, "i");
});

test("a per-person amount is printed as written at every factor", () => {
  for (const f of [0.5, 1, 2, 3.5]) {
    assert.equal(amountText("about 1/2 cup per person", f), "about ½ cup per person");
    assert.equal(amountText("3 leaves per serving", f), "3 leaves per serving");
    assert.equal(amountText("about 1/4 per person", f), "about ¼ per person");
  }
});

test("'per side' is not 'per serving', so an ordinary amount still scales", () => {
  assert.equal(PER_SERVING.test("4 to 5 minutes per side"), false);
  assert.equal(amountText("1 cup", 2), "2 cups");
});

// ⚠️ "head" IS OFF THE LIST ON PURPOSE. import_cleanup's _COUNT_NOUNS holds "head"/"heads" as a
// UNIT the parse writes into the unit column, and units.UNIT_PLURALS holds it too, so "1 pound per
// head" read as a per-diner figure and the scaler then refused to scale a head of cabbage. "per
// head" does mean per person in British English; the collision is the problem, and the losing
// reading was silent.
test("'head' is not a per-serving word, because it is a counting noun", () => {
  assert.equal(PER_SERVING.test("1 pound per head"), false);
  assert.equal(amountText("1 pound per head", 2), "2 lb per head");
});

// ⚠️ REFUSING TO SCALE IS NOT A REASON TO SKIP THE FACTOR-INDEPENDENT FIXES, and the first draft
// skipped both. The old path applied them at factor 1.
test("the per-serving branch still agrees plurals and collapses a degenerate range", () => {
  assert.equal(amountText("1 cups per person", 1), "1 cup per person");
  assert.equal(amountText("2 cup per person", 1), "2 cups per person");
  assert.equal(amountText("1 to 1 tbsp per person", 1), "1 tbsp per person");
});

// ⚠️ AND THE GRAM ESTIMATE UNDER IT HOLDS TOO. The figure above held at "about ½ cup per person"
// while the sub-line beneath it went 63 g, 125 g, 251 g.
test("the gram estimate under a per-person amount does not scale", async () => {
  const { weightText } = await import("../../static/scaler.js");
  for (const f of [1, 2, 4]) {
    assert.equal(weightText("about 1/2 cup per person", 0.53, f), "~63 g");
  }
  // an ordinary amount still scales
  assert.notEqual(weightText("1 cup", 0.53, 2), weightText("1 cup", 0.53, 1));
});
