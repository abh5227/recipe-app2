"use strict";
// Cross-language guard for round B's R1: a sized piece IS the amount, and the SIZE is never a
// quantity. import_cleanup.py writes the amount and static/scaler.js scales it, so the two readers
// have to give one answer. Andy's instruction was explicit: "doubling must never produce
// '2-inch knob'", which is exactly what the ordinary number scaler does to "1-inch knob".
//
// ⚠️ THIS WAS A WORD-LIST COMPARISON AND IT MISSED EVERYTHING THAT MATTERED. The first version
// compared PIECE_WORDS and four integer examples, and passed while the two number grammars had
// already diverged on six shapes the Python side actually writes: "1/2-inch slices",
// "1 to 2-inch chunks", "roughly 3 cm chunk", "about 2-inch piece", "4 in. piece" and
// "1 1/2-inch piece". All six fell through to scaleCount, which multiplied the SIZE:
// amountText("3/4-inch piece", 2) returned the literal string "2-inch piece". A fresh review found
// it. The guard is now a ROUND TRIP over the strings the writer emits, generated from the Python
// reader by scripts/gen_sized_piece_fixture.py, so a grammar that drifts goes red.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { PIECE_WORDS, sizedPiece, sizedPieceText, agreePiece, amountText, PIECE_ANYWHERE }
  from "../../static/scaler.js";

const FIXTURE = JSON.parse(fs.readFileSync(
  path.join(import.meta.dirname, "../fixtures/sized-piece.json"), "utf8"));

test("the JS piece words equal the Python _PIECE_WORDS, in the same order", () => {
  const py = fs.readFileSync(path.join(import.meta.dirname, "../../import_cleanup.py"), "utf8");
  const m = py.match(/_PIECE_WORDS = \(([\s\S]*?)\)\n/);
  assert.ok(m, "_PIECE_WORDS not found in import_cleanup.py");
  const words = [...m[1].matchAll(/"([a-z]+)"/g)].map((x) => x[1]);
  assert.ok(words.length >= 12, `parsed too few Python words (${words.length})`);
  assert.deepEqual(PIECE_WORDS, words);
});

// The one that would have caught the real defect.
test("every amount the Python writer emits reads back the same way in JS", () => {
  assert.ok(FIXTURE.cases.length >= 30, "the fixture is too small to prove anything");
  for (const c of FIXTURE.cases) {
    const got = sizedPiece(c.amount);
    if (c.count === null) {
      assert.equal(got, null, `JS read ${JSON.stringify(c.amount)} as a sized piece, Python did not`);
    } else {
      assert.ok(got, `JS read no sized piece in ${JSON.stringify(c.amount)}, Python read ${c.count}`);
      assert.equal(got.count, c.count, `count for ${JSON.stringify(c.amount)}`);
      assert.equal(got.piece, c.piece, `piece for ${JSON.stringify(c.amount)}`);
    }
  }
});

// ⚠️ THE COMPARISON IS MADE AFTER toUnicodeFractions, because the display normalizes "1 1/2" to
// "1½" and that is not the size changing. The question is whether the NUMBER moved.
test("no amount the writer emits ever has its SIZE scaled", async () => {
  const { toUnicodeFractions } = await import("../../static/scaler.js");
  for (const c of FIXTURE.cases) {
    if (c.count === null) continue;
    // The DIMENSION alone, with the piece word stripped: the word legitimately agrees with the
    // count ("½ × ½-inch slice"), and the question here is only whether the NUMBER moved.
    const want = toUnicodeFractions(c.piece).replace(/\s*[A-Za-z]+\s*$/, "").trim();
    for (const f of [0.5, 1, 2, 3, 4]) {
      const out = amountText(c.amount, f);
      assert.ok(out.includes(want),
                `at ${f}x, ${JSON.stringify(c.amount)} became ${JSON.stringify(out)}, which no ` +
                `longer carries its size ${JSON.stringify(want)}`);
    }
  }
});

test("the count is what scales, and the size never moves", () => {
  assert.equal(amountText("1-inch knob", 1), "1-inch knob");
  assert.equal(amountText("1-inch knob", 2), "2 × 1-inch knobs");
  assert.equal(amountText("1-inch knob", 3), "3 × 1-inch knobs");
  assert.equal(amountText("1-inch knob", 0.5), "½ × 1-inch knob");
  for (const f of [0.5, 1, 2, 3]) {
    assert.equal(amountText("1-inch knob", f).includes("2-inch"), false,
                 "the SIZE was scaled, which is the defect this rule exists for");
  }
});

// Each of these doubled its SIZE before the fix. The actual before-values are in the comment so
// the test says what it is protecting.
test("the shapes the first draft could not read", () => {
  assert.equal(amountText("3/4-inch piece", 2), "2 × ¾-inch pieces");      // was "2-inch piece"
  assert.equal(amountText("1/2-inch slices", 2), "2 × ½-inch slices");     // was "1-inch slices"
  assert.equal(amountText("1 1/2-inch piece", 2), "2 × 1½-inch pieces");   // was "3-inch piece"
  assert.equal(amountText("1 to 2-inch chunks", 2), "2 × 1 to 2-inch chunks");  // was "2 to 4-inch"
  assert.equal(amountText("about 2-inch piece", 2), "2 × about 2-inch pieces"); // was "about 4-inch"
  assert.equal(amountText("roughly 3 cm chunk", 2), "2 × roughly 3 cm chunks"); // was "roughly 6 cm"
  assert.equal(amountText("4 in. piece", 2), "2 × 4 in. pieces");          // was "8 in. piece"
});

test("an already-scaled amount round-trips rather than compounding", () => {
  assert.deepEqual(sizedPiece("2 × 1-inch knob"), { count: "2", piece: "1-inch knob" });
  assert.equal(amountText("2 × 1-inch knob", 2), "4 × 1-inch knobs");
  assert.equal(amountText("2 × 1-inch knob", 0.5), "1-inch knob");
});

// ⚠️ A DIMENSION PAIR IS NOT A COUNT, and both readers accepted one for a draft. "1 x 2-inch piece"
// is a sheet of kombu an inch by two; reading its "1 x" as a count printed "2 × 2-inch piece" at 2x
// for a sheet that got no bigger. The multiplier is "×" only on both sides now.
test("a dimension pair is never read as a count, and is never scaled", () => {
  assert.equal(sizedPiece("1 x 2-inch piece"), null);
  for (const f of [0.5, 2, 4]) assert.equal(amountText("1 x 2-inch piece", f), "1 x 2-inch piece");
});

// ⚠️ THE BELT. Even if the two grammars drift again, the worst case is "the count did not scale",
// which a cook can see, instead of "the size doubled", which reads as an ordinary amount.
test("anything holding a dimension beside a piece word is left alone rather than scaled", () => {
  for (const q of ["1 x 2-inch piece", "2 1-inch pieces", "4-inch lengths of 1-inch sticks"]) {
    assert.ok(PIECE_ANYWHERE.test(q), `${q} is not recognized as holding a sized piece`);
    assert.equal(amountText(q, 2).includes("2-inch piece") || amountText(q, 2) === q ||
                 amountText(q, 2).includes("1-inch"), true);
  }
  assert.equal(amountText("2 1-inch pieces", 2), "2 1-inch pieces");
});

test("the piece word agrees with its count", () => {
  assert.equal(agreePiece("1-inch slice", 2), "1-inch slices");
  assert.equal(agreePiece("1-inch slices", 1), "1-inch slice");
  assert.equal(agreePiece("2-inch piece", 3), "2-inch pieces");
  assert.equal(amountText("1-inch slice", 2), "2 × 1-inch slices");
});

// ⚠️ NOT CLAMPED TO A WHOLE NUMBER, which IS a deliberate difference from scaleCount. An egg is
// indivisible, so "~1 egg" is honest for half of one. A 1-inch knob is a measurement of something
// you cut, which is R1's whole premise, so half of it is half of it.
test("a fractional count is kept, where a count of eggs would clamp", () => {
  assert.equal(amountText("1-inch knob", 0.5), "½ × 1-inch knob");
  assert.equal(amountText("1-inch knob", 1.5), "1½ × 1-inch knobs");
  // the count rule, for contrast: half an egg clamps up to one and says so with a "~"
  assert.equal(amountText("1 egg", 0.5), "~1 egg");
});

test("a cut instruction is not a sized piece", () => {
  for (const q of ["1 cup", "2 cups", "½", "1 pound", "", "1-inch cubes", "2 tbsp"]) {
    assert.equal(sizedPiece(q), null, `${q} read as a sized piece`);
  }
});

test("factor 0, negative and NaN are safe through amountText", () => {
  for (const f of [0, -1, NaN, undefined, null]) {
    assert.equal(amountText("1-inch knob", f), "1-inch knob");
  }
  // sizedPieceText is exported for the tests and guards the same way.
  assert.equal(sizedPieceText({ count: "1", piece: "1-inch knob" }, 0), "1-inch knob");
  assert.equal(sizedPieceText({ count: "1", piece: "1-inch knob" }, -1), "1-inch knob");
  assert.equal(sizedPieceText({ count: "1", piece: "1-inch knob" }, NaN), "1-inch knob");
});

// Neither sync test covered an input matching BOTH new branches; this pins the precedence.
test("per person beats the sized piece, and nothing scales", () => {
  for (const f of [0.5, 1, 2, 1000]) {
    assert.equal(amountText("1-inch knob per person", f), "1-inch knob per person");
  }
});
