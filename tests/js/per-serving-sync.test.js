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
test("the JS PER_SERVING words equal the Python PER_SERVING_WORDS, in the same order", () => {
  const py = fs.readFileSync(path.join(here, "../../import_cleanup.py"), "utf8");
  const m = py.match(/PER_SERVING_WORDS = \(([\s\S]*?)\)\n/);
  assert.ok(m, "PER_SERVING_WORDS not found in import_cleanup.py");
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
