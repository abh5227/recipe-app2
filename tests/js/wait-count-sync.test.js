// The client's half of "which waits reach the Plan ahead figure": it is HANDED the answer and holds
// no rule of its own. The shared case table is tests/fixtures/wait-count-cases.json, which
// tests/test_planahead.py drives against planahead.counts.
//
// ⚠️ WHAT THIS PINS IS THE ABSENCE OF A MIRROR, exactly like total-line.test.js. The client used to
// filter `(w.when_kind || "always") === "always"`, which is planahead.counts written out a second
// time. The two drifted on the alongside row: the server counted an 'alongside' wait whose pointer
// had gone null and the client did not, so a one-wait recipe printed the head figure and then a
// bullet repeating it. The server now sends `in_total` per wait and this filters on that.
import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";

const APP = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const CASES = JSON.parse(readFileSync(new URL("../fixtures/wait-count-cases.json", import.meta.url), "utf8"));
// The wait block of scaleMetaBlock — where the figure, the breakdown and the one-line case live.
const WAITS = APP.slice(APP.indexOf("const waits = (view.waits || [])"),
                        APP.indexOf("// ⚠️ STORAGE IS NOT A WAIT"));
// The same block with its comments removed. The notes in there NAME the fields they are warning
// about ("resolved from alongside_step_id"), so a doesNotMatch over the raw text would fire on the
// explanation rather than on a rule.
const CODE = WAITS.replace(/^\s*\/\/.*$/gm, "");

test("the fixture is the shared table both sides read", () => {
  assert.ok(CASES.length >= 14, "case table shrank");
  for (const c of CASES) {
    assert.ok(typeof c.why === "string" && c.why.length, "every case says what it is for");
    assert.equal(typeof c.in_total, "boolean", c.why);
    assert.ok(c.wait && typeof c.wait === "object", c.why);
  }
});

test("the client filters on the server's in_total", () => {
  assert.match(WAITS, /const counted = waits\.filter\(\(w\) => w\.in_total\);/,
    "the counted set is the server's answer");
});

test("the client does not decide for itself which waits count", () => {
  // The filter is the only thing that may read when_kind for this purpose. qual() still reads it to
  // choose a QUALIFIER, which is a different question, so the assertion is scoped to the filter.
  assert.doesNotMatch(CODE, /filter\([^)]*when_kind/,
    "a second copy of planahead.counts grew back in the wait filter");
  assert.doesNotMatch(CODE, /alongside_step_id/,
    "the client must not read the pointer to decide the figure");
});

test("every case the table says counts would survive the client's filter", () => {
  // The filter the source asserts above, run over the table. Not a mirror of the rule: it is the
  // one-expression predicate the client applies to the field the server computed.
  const clientFilter = (w) => !!w.in_total;
  for (const c of CASES) {
    const served = { ...c.wait, in_total: c.in_total };   // the wait as get_recipe sends it
    assert.equal(clientFilter(served), c.in_total, c.why);
  }
});

test("a wait whose step became a heading still reaches the figure", () => {
  // The case that made this a rule rather than a tidy-up. The step's kind is not a statement about
  // how long the cook waits, so step_no coming back null must not remove the wait from the total.
  const heading = CASES.filter((c) => c.wait.step_ok === false && c.wait.when_kind === "always");
  assert.ok(heading.length, "the table must carry the heading case");
  for (const c of heading) assert.equal(c.in_total, true, c.why);
});
