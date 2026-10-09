"use strict";
// Cross-language guard for round B's R1: a sized piece IS the amount, and the SIZE is never a
// quantity. import_cleanup.py writes the amount and static/scaler.js scales it, so the list of
// piece words has to be one list. Andy's instruction was explicit: "doubling must never produce
// '2-inch knob'", and that is exactly what the ordinary number scaler does to "1-inch knob".
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { PIECE_WORDS, sizedPiece, amountText } from "../../static/scaler.js";

test("the JS piece words equal the Python _PIECE_WORDS, in the same order", () => {
  const py = fs.readFileSync(path.join(import.meta.dirname, "../../import_cleanup.py"), "utf8");
  const m = py.match(/_PIECE_WORDS = \(([\s\S]*?)\)\n/);
  assert.ok(m, "_PIECE_WORDS not found in import_cleanup.py");
  const words = [...m[1].matchAll(/"([a-z]+)"/g)].map((x) => x[1]);
  assert.ok(words.length >= 12, `parsed too few Python words (${words.length})`);
  assert.deepEqual(PIECE_WORDS, words);
});

test("the count is what scales, and the size never moves", () => {
  assert.equal(amountText("1-inch knob", 1), "1-inch knob");
  assert.equal(amountText("1-inch knob", 2), "2 × 1-inch knob");
  assert.equal(amountText("1-inch knob", 3), "3 × 1-inch knob");
  assert.equal(amountText("1-inch knob", 0.5), "½ × 1-inch knob");
  for (const f of [0.5, 1, 2, 3]) {
    assert.equal(amountText("1-inch knob", f).includes("2-inch"), false,
                 "the SIZE was scaled, which is the defect this rule exists for");
  }
});

test("every sized piece the corpus carries reads back", () => {
  for (const [q, piece] of [["2-inch piece", "2-inch piece"], ["1½-inch piece", "1½-inch piece"],
                            ["3-inch section", "3-inch section"], ["1-inch knob", "1-inch knob"]]) {
    assert.equal(sizedPiece(q).piece, piece);
    assert.equal(sizedPiece(q).count, "1");
    assert.equal(amountText(q, 2), `2 × ${piece}`);
  }
});

test("an already-scaled amount round-trips rather than compounding", () => {
  assert.deepEqual(sizedPiece("2 × 1-inch knob"), { count: "2", piece: "1-inch knob" });
  assert.equal(amountText("2 × 1-inch knob", 2), "4 × 1-inch knob");
  assert.equal(amountText("2 × 1-inch knob", 0.5), "1-inch knob");
});

test("a cut instruction is not a sized piece", () => {
  for (const q of ["1 cup", "2 cups", "½", "1 pound", "", "1-inch cubes", "2 tbsp"]) {
    assert.equal(sizedPiece(q), null, `${q} read as a sized piece`);
  }
});
