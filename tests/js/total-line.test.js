// The client's half of the Total contract: it PRINTS the label the server computed and never
// recomputes it. The shared case table is tests/fixtures/total-cases.json, which
// tests/test_planahead.py drives against planahead.recipe_total.
//
// ⚠️ WHAT THIS PINS IS THE ABSENCE OF A MIRROR. A second implementation in JS is exactly what
// planahead's header argues against, and the way that would creep in is the client deciding to add
// the waits itself when total_time is empty. These assert the client reads view.data.total.
import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";

const APP = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const CASES = JSON.parse(readFileSync(new URL("../fixtures/total-cases.json", import.meta.url), "utf8"));

test("the fixture is the shared table both sides read", () => {
  assert.ok(CASES.length >= 14, "case table shrank");
  for (const c of CASES) {
    assert.ok(typeof c.why === "string" && c.why.length, "every case says what it is for");
    assert.ok("label" in c && "note" in c, c.why);
  }
});

test("the Total segment reads the server's computed label, not r.total_time", () => {
  const block = APP.slice(APP.indexOf("function scaleMetaBlock"), APP.indexOf("function scaleMetaBlock") + 4000);
  assert.match(block, /view\.data\.total/, "the client must read the server's total");
  assert.match(block, /\["Total", totals\.label/, "the Total segment is the server's label");
  assert.doesNotMatch(block, /\["Total", r\.total_time\]/, "r.total_time is the EDITOR's value");
});

test("the client does not sum waits into a total of its own", () => {
  const block = APP.slice(APP.indexOf("function scaleMetaBlock"), APP.indexOf("function scaleMetaBlock") + 4000);
  assert.doesNotMatch(block, /prep_time\s*\+\s*/, "no arithmetic on the times here");
  assert.doesNotMatch(block, /incl\. plan ahead/, "the note is the server's words, not a JS literal");
});

test("every case's label is already in the app's own duration spelling", () => {
  // fmt_minutes writes "1 hr 15 min" / "30 min" / "2 days", plus a "+" for open-ended and an en dash
  // for a range. Anything else would mean the client had to reformat, which is the mirror again.
  const ok = /^(\d+ (min|hr|days?)( \d+ min)?)(\+| – \d+ (min|hr|days?)( \d+ min)?)?$|^\d+ hr \d+ min\+$/;
  for (const c of CASES) {
    if (c.label == null) continue;
    if (c.recipe.total_time && c.note == null) continue;   // an author's own words, passed through
    assert.match(c.label, ok, `${c.why}: ${c.label}`);
  }
});
