"use strict";
// Cross-language guard: the JS conversion factors (static/scaler.js UNIT_TO_ML) MUST agree
// with the Python ones (weights.py VOLUME_TO_ML). This reads BOTH real files, so it catches
// the one genuine drift class — a factor changed on one side only. Lives in the JS suite so
// the Python pytest count stays unchanged.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { UNIT_TO_ML } from "../../static/scaler.js";

test("JS UNIT_TO_ML agrees with Python weights.VOLUME_TO_ML", () => {
  const py = fs.readFileSync(path.join(import.meta.dirname, "../../weights.py"), "utf8");
  const block = py.match(/VOLUME_TO_ML\s*=\s*\{([\s\S]*?)\}/);
  assert.ok(block, "VOLUME_TO_ML block not found in weights.py");

  const pyFactors = {};
  for (const m of block[1].matchAll(/"([a-z ]+)"\s*:\s*([\d.]+)/g)) {
    pyFactors[m[1]] = parseFloat(m[2]);
  }
  assert.ok(Object.keys(pyFactors).length >= 3, "parsed too few Python factors");

  // every unit Python defines must exist in the JS table with the identical value
  for (const [unit, ml] of Object.entries(pyFactors)) {
    assert.ok(unit in UNIT_TO_ML, `JS UNIT_TO_ML is missing "${unit}"`);
    assert.equal(UNIT_TO_ML[unit], ml, `factor mismatch for "${unit}" (JS ${UNIT_TO_ML[unit]} vs Py ${ml})`);
  }
  // and the shared core must be present on the Python side
  for (const u of ["tsp", "tbsp", "cup"]) {
    assert.ok(u in pyFactors, `weights.py VOLUME_TO_ML is missing "${u}"`);
  }
});
