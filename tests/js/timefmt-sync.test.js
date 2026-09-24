"use strict";
// Cross-language guard: static/timefmt.js normalizeTime MUST agree with
// import_cleanup.normalize_time. Both are asserted against the SAME case table,
// tests/fixtures/time-cases.json, generated from every one of the 63 distinct time spellings live
// data holds plus the edge cases neither corpus happens to contain. The Python side asserts the
// same file in tests/test_import_cleanup.py, so a change on one side alone turns the other red.
// Same arrangement as factor-sync.test.js holds scaler.js to weights.py.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { normalizeTime } from "../../static/timefmt.js";

const CASES = JSON.parse(
  fs.readFileSync(path.join(import.meta.dirname, "../fixtures/time-cases.json"), "utf8"));

test("the shared case table is the real corpus, not a handful of invented strings", () => {
  assert.ok(CASES.length >= 63, `expected the 63 live spellings, got ${CASES.length}`);
});

test("JS normalizeTime agrees with Python normalize_time on every case", () => {
  for (const { in: input, out } of CASES) {
    assert.equal(normalizeTime(input), out, `normalizeTime(${JSON.stringify(input)})`);
  }
});

test("a range keeps both ends", () => {
  assert.equal(normalizeTime("15-20 minutes"), "15–20 min");
});

test("a trailing note is kept and its own durations are normalized", () => {
  assert.equal(normalizeTime("30 mins, plus 1 hour soaking"), "30 min · plus 1 hr soaking");
  assert.equal(normalizeTime("20 minutes additional time"), "20 min · additional time");
});

test("an unreadable value comes back exactly as stored", () => {
  for (const junk of ["1 cup", "to taste", "whenever", "--"]) {
    assert.equal(normalizeTime(junk), junk);
  }
});

test("null and undefined are empty, never the string 'null'", () => {
  assert.equal(normalizeTime(null), "");
  assert.equal(normalizeTime(undefined), "");
});
