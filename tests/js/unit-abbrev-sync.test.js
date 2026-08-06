"use strict";
// Cross-language guard: the JS unit abbreviator (static/scaler.js UNIT_ABBREV) MUST agree with the
// Python one (units.py UNIT_ABBREV) — the change diff (snapshot_diff) canonicalizes amounts through the
// Python mirror, so a rule present on one side only would let unit-representation phantoms slip back in.
// Reads BOTH real files as text (UNIT_ABBREV is module-private in scaler.js, not exported) and asserts
// the ordered (pattern-source, replacement) pairs match exactly. Mirrors tests/js/factor-sync.test.js;
// lives in the JS suite so the Python pytest count stays unchanged.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// Pull the UNIT_ABBREV block out of scaler.js and parse each [/pattern/gi, "repl"] entry.
function jsRules() {
  const src = fs.readFileSync(path.join(import.meta.dirname, "../../static/scaler.js"), "utf8");
  const block = src.match(/const UNIT_ABBREV\s*=\s*\[([\s\S]*?)\];/);
  assert.ok(block, "UNIT_ABBREV block not found in scaler.js");
  const rules = [];
  for (const m of block[1].matchAll(/\[\/(.+?)\/gi,\s*"(.+?)"\]/g)) rules.push([m[1], m[2]]);
  return rules;
}

// Pull the UNIT_ABBREV list out of units.py and parse each (r"pattern", "repl") tuple.
function pyRules() {
  const src = fs.readFileSync(path.join(import.meta.dirname, "../../units.py"), "utf8");
  const block = src.match(/UNIT_ABBREV\s*=\s*\[([\s\S]*?)\]/);
  assert.ok(block, "UNIT_ABBREV block not found in units.py");
  const rules = [];
  for (const m of block[1].matchAll(/\(r"(.+?)",\s*"(.+?)"\)/g)) rules.push([m[1], m[2]]);
  return rules;
}

test("JS scaler.js UNIT_ABBREV agrees with Python units.py UNIT_ABBREV", () => {
  const js = jsRules();
  const py = pyRules();
  assert.ok(js.length >= 9, `parsed too few JS rules (${js.length})`);
  assert.equal(py.length, js.length, `rule count mismatch: JS ${js.length} vs Py ${py.length}`);
  // ordered, byte-for-byte: same pattern SOURCE and same replacement at each index
  for (let i = 0; i < js.length; i++) {
    assert.equal(py[i][0], js[i][0], `pattern mismatch at ${i}: Py /${py[i][0]}/ vs JS /${js[i][0]}/`);
    assert.equal(py[i][1], js[i][1], `replacement mismatch at ${i}: Py "${py[i][1]}" vs JS "${js[i][1]}"`);
  }
});
