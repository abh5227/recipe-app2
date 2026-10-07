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
// The wait half of scaleMetaBlock: the verb, the step link, the qualifier, the lines and the
// figure. ⚠️ THE ANCHORS ARE THE READS THEMSELVES, not a layout comment. The first anchor was
// `const waits = (view.waits || [])`, whose parentheses went when the block was rebuilt in two
// columns, and the slice then started at -1 and asserted over the whole file.
const WAITS = APP.slice(APP.indexOf("const waits = view.waits"),
                        APP.indexOf("const twoCol ="));
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

test("the client prints the server's figure and counts nothing itself", () => {
  // ⚠️ THIS ASSERTED A FILTER, AND THE FILTER IS GONE. The client used to split the waits into
  //    counted and not, because a single counted wait printed inline and everything else printed a
  //    summed figure with a breakdown under it. Round 3's block gives every wait its own line, so
  //    the only figure is the one the server computed (view.waitTotal.label) and there is nothing
  //    left for the client to count. That is the same rule arrived at from the other side: the
  //    strongest version of "the client must not decide which waits count" is a client that cannot.
  assert.match(WAITS, /view\.waitTotal\.label/, "the client no longer prints the server's figure");
  assert.doesNotMatch(CODE, /filter\([^)]*in_total/,
    "the client is filtering on in_total again instead of printing what it was handed");
});

test("the client does not decide for itself which waits count", () => {
  // qual() still reads when_kind to choose a QUALIFIER, which is a different question, so the
  // assertion is scoped to anything that looks like a counted set.
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
