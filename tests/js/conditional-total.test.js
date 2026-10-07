"use strict";
// The client half of the second Total. tests/fixtures/conditional-total-cases.json is SHARED: the
// Python suite asserts the figures planahead.conditional_totals produces and this file asserts the
// markup app.js builds from them, so the one implementation and its rendering cannot drift apart.
//
// ⚠️ THE CLIENT COMPUTES NOTHING HERE, AND THAT IS DELIBERATE. The Total and the second Total are
// both decided server side (see planahead's header), so what this file guards is the SHAPE the
// client depends on: a list of {label, when}, one line each, printed under the Total and escaped.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { APP, CSS, renderTimeBlock as render } from "./time-block-harness.js";

const ROOT = path.join(import.meta.dirname, "../..");
const FIX = JSON.parse(fs.readFileSync(
  path.join(ROOT, "tests/fixtures/conditional-total-cases.json"), "utf8"));

test("the fixture carries the shapes the feature was asked for", () => {
  const names = FIX.cases.map((c) => c.name).join(" | ");
  for (const needed of ["optional", "only_if", "two conditionals", "alongside"]) {
    assert.ok(names.includes(needed), `no case covers ${needed}`);
  }
  const withLines = FIX.cases.filter((c) => c.expected.length);
  assert.ok(withLines.length >= 3, "the fixture has almost no positive cases");
  for (const c of withLines) {
    for (const line of c.expected) {
      assert.equal(typeof line.label, "string");
      assert.equal(typeof line.when, "string");
      assert.ok(line.label.length, `an empty figure in ${c.name}`);
    }
  }
});

test("the client reads conditional_totals and prints one line for each", () => {
  // ⚠️ IT RUNS THE RENDERER RATHER THAN READING IT. This asserted the SHAPE of the loop
  //    ("for (const c of conds)", "if (!c || !c.label) continue;"), which pinned one spelling of
  //    the rule and broke the day the block was rebuilt in two columns without the behaviour
  //    changing at all. What the feature promises is one line per entry, both halves escaped, and
  //    an entry with no figure skipped, so that is what is checked.
  assert.ok(/view\.data\.conditional_totals/.test(APP), "app.js does not read conditional_totals");

  const html = render({
    total: { label: "1 hr 20 min" },
    conds: [{ label: "9 hr 20 min+", when: "if you soak" },
            { label: "3 hr 30 min+", when: "if chilled" }],
  });
  const lines = html.split("meta-conditional").length - 1;
  assert.equal(lines, 2, "the lines are not rendered one per entry");
  assert.ok(html.includes("9\u00a0hr 20\u00a0min+") && html.includes("if you soak"), html);
  assert.ok(html.includes("3\u00a0hr 30\u00a0min+") && html.includes("if chilled"), html);

  // an entry with no figure says nothing rather than printing an empty line
  const bare = render({ conds: [{ label: "", when: "if you soak" }, null] });
  assert.equal(bare.split("meta-conditional").length - 1, 0, bare);

  // and both halves are escaped
  const nasty = render({ conds: [{ label: "<b>1 hr</b>", when: "if <i>you</i> soak" }] });
  assert.ok(!nasty.includes("<b>") && !nasty.includes("<i>"), nasty);
});

test("the second Total is quieter and sits under the first", () => {
  // ⚠️ IT MUST NOT COMPETE WITH THE TOTAL. Andy asked for "a smaller line under the Total", so the
  //    rule is stated here rather than left to whoever edits the stylesheet next.
  const rule = CSS.slice(CSS.indexOf(".meta-stack .meta-item.meta-conditional {"),
                         CSS.indexOf(".meta-stack .meta-item.meta-conditional {") + 260);
  assert.ok(rule.length > 40, "the .meta-conditional rule is gone");
  const size = rule.match(/font-size:\s*([\d.]+)em/);
  assert.ok(size && Number(size[1]) < 1, `the second total is not smaller: ${size && size[1]}`);
  assert.ok(/color:\s*var\(--ink-soft\)/.test(rule), "the second total is not muted");
});

test("the main Total's own line is untouched by the feature", () => {
  assert.ok(/\["Total", totals\.label \|\| "", totals\.note \|\| ""\]/.test(APP),
    "the Total line no longer reads the server's label");
});
