"use strict";
// The time block's second column exists only when something is in it.
//
// ⚠️ WHY THIS IS A BEHAVIOUR TEST AND NOT A CSS ONE. The grid is CSS, and WHETHER a recipe gets two
// columns is a decision app.js makes while it builds the markup. A stylesheet assertion would pass
// just as happily if every recipe carried .two-col and half of them drew an empty half.
//
// ⚠️ AND IT RUNS THE REAL FUNCTION. app.js cannot be imported here (it pulls TipTap through a bare
// specifier), so scaleMetaBlock is cut out of the file by brace balance and run with the handful of
// globals it reads. Nothing is retyped: a change to the function changes what this test executes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { CSS, renderTimeBlock as render } from "./time-block-harness.js";

const WAIT = { kind: "chilling", label_text: "4 hr", label_text_raw: "4 hr", step_no: 5,
               when_kind: "always", in_total: true };
const KEEP = { where_kept: "fridge", applies_to: null, label: "up to 3 days" };

test("no waits means one column, with no empty half", () => {
  const html = render({ total: { label: "30 min" } });
  assert.ok(!html.includes("two-col"), "a recipe with no waits took the two-column layout");
  assert.ok(!html.includes("tb-right"), "a recipe with no waits drew a right column");
  assert.ok(html.includes("Prep") && html.includes("Total"), html);
});

test("waits mean two columns, and the waits are in the right one", () => {
  const html = render({ waits: [WAIT], total: { label: "4 hr 30 min" } });
  assert.ok(html.includes("two-col"), "a recipe with waits stayed in one column");
  const right = html.split('class="meta-stack tb-col tb-right"')[1];
  assert.ok(right, "no right column was drawn");
  assert.ok(right.includes("Plan"), "Plan ahead is not in the right column");
  const left = html.split('class="meta-stack tb-col"')[1].split("tb-right")[0];
  assert.ok(left.includes("Prep") && left.includes("Total"), "the times left the left column");
  assert.ok(!left.includes("Plan ahead"), "Plan ahead is in the left column too");
});

test("Keeps on its own stays in the left column", () => {
  const html = render({ storage: [KEEP], total: { label: "30 min" } });
  assert.ok(!html.includes("two-col"), "Keeps alone bought a second column");
  assert.ok(html.includes("Keeps"), "the Keeps line is missing");
  assert.ok(html.indexOf("Keeps") > html.indexOf("Total"), "Keeps must read under the times");
});

test("Keeps moves to the right column when there are waits", () => {
  const html = render({ waits: [WAIT], storage: [KEEP] });
  const right = html.split('class="meta-stack tb-col tb-right"')[1];
  assert.ok(right.includes("Keeps"), "Keeps stayed on the left beside Plan ahead");
});

test("the phone is one column, and the stylesheet is what says so", () => {
  const block = CSS.match(/@media \(max-width: 680px\) \{[^}]*\.time-block\.two-col[^}]*\}/s);
  assert.ok(block, "no 680px rule turns the two columns back into one");
  assert.ok(/grid-template-columns:\s*1fr/.test(block[0]), block && block[0]);
});

test("the Plan ahead label shows even when no wait counts toward a figure", () => {
  const optional = { ...WAIT, when_kind: "optional", in_total: false };
  const html = render({ waits: [optional], total: { label: "30 min" } });
  assert.ok(html.includes("Plan ahead"), "the label vanished when nothing counted");
  assert.ok(html.includes("(optional)"), "the qualifier is missing");
});

test("a wait line leads with the action and names its step", () => {
  const html = render({ waits: [WAIT] });
  const line = html.split('<li class="meta-bullet">')[1].split("</li>")[0];
  assert.ok(line.startsWith('<span class="meta-do">Chill</span>'), line);
  assert.ok(line.includes(">step 5<"), line);
  assert.ok(line.indexOf("Chill") < line.indexOf("step 5"), "the step link came before the verb");
});

test("one wait does not print the summed figure twice", () => {
  // ⚠️ THE FIGURE CARRIES A NON-BREAKING SPACE, because bindUnits holds a number to its unit. An
  //    assertion written with an ordinary space passes whatever the code does.
  const FIGURE = "8\u00a0hr+";
  const one = render({ waits: [WAIT] });
  assert.ok(!one.includes(FIGURE), "the plan-ahead total repeated a single wait's own words");
  const two = render({ waits: [WAIT, { ...WAIT, step_no: 7 }] });
  assert.ok(two.includes(FIGURE), "two waits should print the summed figure");
});

test("the scaler sits below the block, inside .above-ing and after it", () => {
  const html = render({ waits: [WAIT] });
  assert.ok(html.indexOf("scaler-host") > html.indexOf("time-block"), html.slice(0, 200));
  const rule = CSS.match(/\.above-ing \{[^}]*\}/);
  assert.ok(/flex-direction:\s*column/.test(rule[0]), rule[0]);
});
