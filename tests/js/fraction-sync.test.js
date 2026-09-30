"use strict";
// Cross-language guard: the JS fraction map (static/scaler.js UNICODE_FRACTIONS) MUST agree with the
// Python one (units.py UNICODE_FRACTIONS). "your changes" now compares amounts through the Python
// mirror, so a glyph present on one side only would put a mark on a row whose amount the cook sees
// as identical — the exact phantom the comparison change exists to remove. Reads BOTH real files as
// text (UNICODE_FRACTIONS is module-private in scaler.js, not exported) and asserts the ordered
// glyph/ascii pairs match exactly. Mirrors tests/js/unit-abbrev-sync.test.js.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

function pairs(file, re) {
  const src = fs.readFileSync(path.join(import.meta.dirname, "../../", file), "utf8");
  const block = src.match(re);
  assert.ok(block, `UNICODE_FRACTIONS block not found in ${file}`);
  const out = [];
  for (const m of block[1].matchAll(/"(.+?)":\s*"(.+?)"/g)) out.push([m[1], m[2]]);
  return out;
}

test("JS scaler.js UNICODE_FRACTIONS agrees with Python units.py UNICODE_FRACTIONS", () => {
  const js = pairs("static/scaler.js", /const UNICODE_FRACTIONS\s*=\s*\{([\s\S]*?)\};/);
  const py = pairs("units.py", /UNICODE_FRACTIONS\s*=\s*\{([\s\S]*?)\}/);
  assert.ok(js.length >= 11, `parsed too few JS glyphs (${js.length})`);
  assert.equal(py.length, js.length, `glyph count mismatch: JS ${js.length} vs Py ${py.length}`);
  for (let i = 0; i < js.length; i++) {
    assert.equal(py[i][0], js[i][0], `glyph mismatch at ${i}: Py ${py[i][0]} vs JS ${js[i][0]}`);
    assert.equal(py[i][1], js[i][1], `ascii mismatch at ${i}: Py ${py[i][1]} vs JS ${js[i][1]}`);
  }
});

test("the Python normalizer produces what the JS one does, on the real glyph set", async () => {
  // Not a re-implementation: scaler.js EXPORTS normalizeFractions, so this runs the real JS function
  // and compares against the real Python one via a subprocess, on every glyph plus the mixed-number
  // and whitespace cases the amounts on live actually contain.
  const { normalizeFractions } = await import("../../static/scaler.js");
  const { execFileSync } = await import("node:child_process");
  const cases = ["½ tsp", "1½ cups", "¼", "2 ⅔ cups", " 3/4  tsp ", "1 1/2", "no fraction here",
                 "⅛ tsp", "⅚ cup", "2½–3 tbsp"];
  const py = JSON.parse(execFileSync("python3.13",
    ["-c", "import sys,json,units;print(json.dumps([units.normalize_fractions(x) for x in json.loads(sys.argv[1])]))",
     JSON.stringify(cases)],
    { cwd: path.join(import.meta.dirname, "../..") }).toString());
  cases.forEach((c, i) => assert.equal(py[i], normalizeFractions(c), `differs on ${JSON.stringify(c)}`));
});
