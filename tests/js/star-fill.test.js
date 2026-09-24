// The rating stars' arithmetic (static/star-fill.js). Zero-dep, runs on the source.
//
// The reason this module exists: a recipe's number is an AVERAGE of half-step verdicts, so it is
// usually not itself a half step, and the renderer has to draw a fraction the old ★-repeat path
// could not express.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { RATING_MAX, RATING_STEPS, ratingPct, ratingText, nextRating } from "../../static/star-fill.js";

test("the fill is continuous, not snapped to a half", () => {
  // three cooks rated 5, 4 and 4 -> 4.333…, which is 86.67% of the way across and NOT 4.5
  assert.equal(ratingPct((5 + 4 + 4) / 3), "86.67%");
  assert.equal(ratingPct(4.5), "90%");
  assert.equal(ratingPct(4), "80%");
  assert.equal(ratingPct(0.5), "10%");
});

test("the percentage is rounded, so the DOM gets a number and not float noise", () => {
  assert.equal(ratingPct(4.3333333333), "86.67%");     // not 86.66666599999999%
  assert.ok(!ratingPct(1 / 3).includes("99999"));
});

test("out-of-range values clamp instead of overflowing the stars", () => {
  assert.equal(ratingPct(9), "100%");
  assert.equal(ratingPct(-1), "0%");
});

test("⚠️ null is not zero — an unrated cook has no fill and no figure", () => {
  // Number(null) === 0, so a guard written with Number.isFinite alone would print "0" for unrated.
  for (const empty of [null, undefined, "", true, false, "x", NaN]) {
    assert.equal(ratingPct(empty), "0%", `pct of ${String(empty)}`);
    assert.equal(ratingText(empty), "", `text of ${String(empty)}`);
  }
});

test("the printed figure keeps one decimal and drops a bare .0", () => {
  assert.equal(ratingText(4.3333333), "4.3");
  assert.equal(ratingText(4), "4");            // not "4.0" — the precision would say nothing
  assert.equal(ratingText(4.5), "4.5");
  assert.equal(ratingText(4.96), "5");         // one decimal, rounded
  assert.equal(ratingText("4.5"), "4.5");      // a JSON string coerces
});

test("clicking the step a cook already sits on clears it", () => {
  assert.equal(nextRating(3, 3), null);        // the only route back to unrated
  assert.equal(nextRating(3, 4), 4);
  assert.equal(nextRating(null, 0.5), 0.5);
  assert.equal(nextRating("4.5", "4.5"), null);   // dataset values arrive as strings
  assert.equal(nextRating("", "1"), 1);
});

test("the half steps match the server and the DB CHECK", () => {
  assert.deepEqual(RATING_STEPS, [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]);
  assert.equal(RATING_MAX, 5);
  assert.ok(RATING_STEPS.every((v) => v > 0 && v <= RATING_MAX));   // no zero-star rating exists
});
// Cross-language guard, the factor-sync.test.js idiom. The half steps are written in FOUR places:
// this module, app.RATING_STEPS, import_write._RATING_STEPS and the CHECK in migration 048. Reading
// the real files is what catches the one drift that matters — a step added on one side only, which
// would let the client offer a rating the database then refuses.
const repoFile = (rel) => fs.readFileSync(path.join(import.meta.dirname, "../../", rel), "utf8");
const parseSteps = (src, re, what) => {
  const block = src.match(re);
  assert.ok(block, `${what} was not found`);
  return block[1].split(",").map((s) => Number(s.trim())).filter((n) => !Number.isNaN(n));
};

test("the half steps agree across JS, app.py and import_write.py", () => {
  assert.deepEqual(
    parseSteps(repoFile("app.py"), /\bRATING_STEPS\s*=\s*\(([^)]*)\)/, "app.RATING_STEPS"),
    RATING_STEPS);
  assert.deepEqual(
    parseSteps(repoFile("import_write.py"), /_RATING_STEPS\s*=\s*\(([^)]*)\)/, "import_write._RATING_STEPS"),
    RATING_STEPS);
});

test("the half steps agree with the CHECK constraint in migration 048", () => {
  const sql = repoFile("migrations/048_ratings_cluster.sql");
  const inList = sql.match(/rating IN \(([^)]*)\)/);
  assert.ok(inList, "the rating IN-list was not found in migration 048");
  assert.deepEqual(inList[1].split(",").map((s) => Number(s.trim())), RATING_STEPS);
});
