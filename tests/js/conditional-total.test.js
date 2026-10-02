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

const ROOT = path.join(import.meta.dirname, "../..");
const APP = fs.readFileSync(path.join(ROOT, "static/app.js"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "static/styles.css"), "utf8");
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
  // the source is the contract: a loop over view.data.conditional_totals pushing a meta item each
  assert.ok(/view\.data\.conditional_totals/.test(APP),
    "app.js does not read conditional_totals");
  const block = APP.slice(APP.indexOf("const conds ="), APP.indexOf("const conds =") + 700);
  assert.ok(/for \(const c of conds\)/.test(block), "the lines are not rendered one per entry");
  assert.ok(/meta-conditional/.test(block), "the line carries no class of its own");
  assert.ok(/esc\(bindUnits\(c\.label\)\)/.test(block), "the figure is not escaped");
  assert.ok(/esc\(c\.when\)/.test(block), "the condition is not escaped");
  assert.ok(/if \(!c \|\| !c\.label\) continue;/.test(block),
    "an entry with no figure is not skipped");
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
