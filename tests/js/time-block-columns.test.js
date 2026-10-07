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
import { CSS, groupsOf, renderTimeBlock as render } from "./time-block-harness.js";

const WAIT = { kind: "chilling", label_text: "4 hr", label_text_raw: "4 hr", step_no: 5,
               when_kind: "always", in_total: true };
const KEEP = { where_kept: "fridge", applies_to: null, label: "up to 3 days" };
// ⚠️ WRITTEN AS AN ESCAPE, NEVER AS THE CHARACTER. The label holds a non-breaking space so "Plan
// ahead" cannot break across two lines, and an assertion typed with an ordinary space is simply
// false however the code behaves. Three of the tests below were written that way and failed with
// the string plainly visible in the output, which is the kinder direction. The same mistake inside
// a `!includes` would have passed forever.
const LABEL = "Plan\u00a0ahead";

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
  assert.ok(!left.includes("Plan\u00a0ahead"), "Plan ahead is in the left column too");
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
  assert.ok(html.includes(LABEL), "the label vanished when nothing counted");
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


// ---- what the column rule looked at, and what it did not --------------------------------------
// ⚠️ THE DEFAULTS HID BOTH OF THESE. renderTimeBlock supplies prep, cook and servings unless a test
// says otherwise, so every case above builds a non-empty LEFT column and a non-empty block. The two
// recipes shapes that broke are the ones with nothing on the left, which no test could reach.

test("a recipe with nothing to say still gets the scaler", () => {
  // 78 of live's 300 state no prep, no cook, no total and no serving count. An early `return ""`
  // took #scaler-host with the block, so a quarter of the corpus lost the ½×/1×/2× control, and
  // rerenderScaler null-checks the host so nothing threw.
  const html = render({ prep: "", cook: "", servings: "", total: {} });
  assert.ok(html.includes('id="scaler-host"'), "the scaler is gone from a recipe with no times");
  assert.ok(html.includes("above-ing"), "the block's container is gone too");
  assert.ok(!html.includes("time-block"), "an empty block was drawn rather than omitted");
});

test("a wait with nothing on the left is one column, not an empty half", () => {
  // 27 of the 300: a wait, and no prep, cook, total or serving count. Asking only about the waits
  // drew the grid with a blank left cell and .tb-right's dividing rule hanging in it.
  const html = render({ waits: [WAIT], prep: "", cook: "", servings: "", total: {} });
  assert.ok(!html.includes("two-col"), "a recipe with nothing on the left took the two-column grid");
  assert.ok(!html.includes("tb-right"), "the dividing rule was drawn against an empty left column");
  assert.ok(html.includes(LABEL), "the waits fell out of the single column");
});

test("Keeps and the waits both survive the single column", () => {
  const html = render({ waits: [WAIT], storage: [KEEP], prep: "", cook: "", servings: "",
                        total: {} });
  assert.ok(!html.includes("two-col"), html.slice(0, 160));
  assert.ok(html.includes(LABEL) && html.includes("Keeps"), "a group was dropped");
  assert.ok(html.indexOf(LABEL) < html.indexOf("Keeps"), "Keeps came before the waits");
});

test("the alternative does not run into the qualifier before it", () => {
  // ⚠️ ASSERTED ON THE TEXT, NOT THE MARKUP. The spans are block elements, so on screen the missing
  //    space is invisible and a COPY of the line shows "(optional)or a 90 minute quick soak".
  const html = render({ waits: [{ ...WAIT, when_kind: "optional",
                                  ext_label: "or a 90 minute quick soak" }] });
  const text = html.replace(/<[^>]*>/g, "");
  assert.ok(text.includes(") or a 90\u00a0minute quick soak"),
            `the alternative ran into the line before it: ${JSON.stringify(text)}`);
});


// ---- one fixed order, every case ---------------------------------------------------------------
// ⚠️ ANDY'S RULE: times, Serves, Plan ahead, Keeps, and the same sentence read down one column or
// across two. It had Keeps ABOVE Serves on a recipe with no waits and BELOW it on one with waits,
// which is two orders for the same two lines decided by a third thing.
//
// ⚠️ DOM ORDER IS READING ORDER IN BOTH LAYOUTS, which is why one assertion covers the phone and
// the desktop. The 680px rule collapses the grid in source order, and the two desktop columns are
// a FOLD in that one order rather than a different one.

const ORDER = ["Prep", "Cook", "Total", "Author", "2nd", "Serves", "Plan ahead", "Keeps"];
const AUTHOR = "Author's total: 1 hr, before the waits";
const COND = { label: "6 hr", when: "if you soak" };

const CASES = {
  "times + waits": [{ waits: [WAIT], total: { label: "4 hr 30 min" } },
                    ["Prep", "Cook", "Total", "Serves", "Plan ahead"]],
  "times only": [{ total: { label: "30 min" } },
                 ["Prep", "Cook", "Total", "Serves"]],
  "waits only": [{ waits: [WAIT], prep: "", cook: "", servings: "", total: {} },
                 ["Plan ahead"]],
  "waits + Keeps, no times": [{ waits: [WAIT], storage: [KEEP], prep: "", cook: "", servings: "",
                                total: {} },
                              ["Plan ahead", "Keeps"]],
  "Keeps only": [{ storage: [KEEP], prep: "", cook: "", servings: "", total: {} },
                 ["Keeps"]],
  "Serves only": [{ prep: "", cook: "", total: {} },
                  ["Serves"]],
  "times + Keeps, no waits": [{ storage: [KEEP], total: { label: "30 min" } },
                              ["Prep", "Cook", "Total", "Serves", "Keeps"]],
  "everything": [{ waits: [WAIT], storage: [KEEP], total: { label: "4 hr 30 min" },
                   conds: [COND], authorTotal: AUTHOR },
                 ["Prep", "Cook", "Total", "Author", "2nd", "Serves", "Plan ahead", "Keeps"]],
};

for (const [name, [opts, expected]] of Object.entries(CASES)) {
  test(`the order holds: ${name}`, () => {
    assert.deepEqual(groupsOf(render(opts)), expected);
  });
}

test("every combination reads in the one order, with nothing out of place", () => {
  // ⚠️ STATED OVER THE COMBINATIONS, NOT OVER THE EIGHT ABOVE. The named cases are the ones worth
  //    reading; this is the one that cannot be satisfied by getting eight examples right.
  const bits = [[WAIT], []].flatMap((waits) =>
    [[KEEP], []].flatMap((storage) =>
      ["4", ""].flatMap((servings) =>
        [{ label: "30 min" }, {}].flatMap((total) =>
          [[COND], []].flatMap((conds) =>
            [AUTHOR, null].map((authorTotal) =>
              ({ waits, storage, servings, total, conds, authorTotal,
                 prep: total.label ? "10 min" : "", cook: total.label ? "20 min" : "" })))))));
  assert.equal(bits.length, 64);
  let seen = 0;
  const perGroup = Object.fromEntries(ORDER.map((g) => [g, 0]));
  for (const opts of bits) {
    const got = groupsOf(render(opts));
    seen += got.length;
    let at = 0;
    for (const g of got) {
      assert.ok(ORDER.includes(g), `${g} is not one of the groups this order is stated over`);
      perGroup[g] += 1;
      // ⚠️ NOT STRICTLY INCREASING, AND THE DIFFERENCE IS A REAL RENDERING. Two conditional
      //    totals are two "2nd" rows in a row, which the project supports and has a fixture case
      //    for ("two conditionals, one line each (no-knead-bread's shape)"). `indexOf(g, at + 1)`
      //    with `i > at` rejected that, so the day a second line appears this test fails on a
      //    correct page. 0 of the 300 render two today, because no-knead-bread's second wait has a
      //    floor of 0 and is skipped, which is the only reason it never fired.
      const i = ORDER.indexOf(g, at);
      assert.ok(i >= at,
                `${JSON.stringify(got)} is not in the one order, for ${JSON.stringify(opts)}`);
      at = i;
    }
  }
  // ⚠️ ANTI-VACUITY, PER GROUP. A groupsOf that matched nothing would make every sequence above
  //    trivially ordered, which is how the non-breaking space nearly made this test meaningless.
  //    A total floor cannot catch that: measured, the 64 combinations render exactly 32 of each of
  //    the 8 groups, so `seen > 150` tolerated THREE of the eight marks going dead, and
  //    re-introducing the NBSP bug left seen at 224 with this assertion still green. The per-group
  //    count is what actually fails, and the exact total catches anything else that stops matching.
  for (const g of ORDER) {
    assert.equal(perGroup[g], 32,
                 `${g} was found ${perGroup[g]} times over the 64 combinations, expected 32. `
                 + `A mark that stops matching makes every order assertion above vacuous.`);
  }
  assert.equal(seen, 256, `the combinations rendered ${seen} groups in total, expected 256`);
});

test("two conditional totals are two rows in a row, and that is in order", () => {
  // ⚠️ THE CASE THE ORDER CHECK USED TO REJECT. tests/fixtures/conditional-total-cases.json has
  //    "two conditionals, one line each (no-knead-bread's shape)", so the page supports it, and
  //    the combination test's `indexOf(g, at + 1)` made two "2nd" rows a failure. 0 of the 300
  //    render two today: no-knead-bread's second wait has a floor of 0 and is skipped, which is
  //    the only reason a correct page was never declared out of order.
  const second = { label: "9 hr 45 min", when: "if you soak the beans" };
  const html = render({ prep: "10 min", cook: "20 min", total: { label: "30 min" },
                        conds: [COND, second], servings: "4", waits: [WAIT] });
  const groups = groupsOf(html);
  assert.deepEqual(groups,
                   ["Prep", "Cook", "Total", "2nd", "2nd", "Serves", "Plan ahead"],
                   groups.join(" > "));
  let at = 0;
  for (const g of groups) {
    const i = ORDER.indexOf(g, at);
    assert.ok(i >= at, `${groups.join(" > ")} is not in the one order`);
    at = i;
  }
});


test("the author's own total sits directly under the Total it replaced", () => {
  const html = render({ waits: [WAIT], total: { label: "2 hr 30 min+", note: "incl. plan ahead" },
                        authorTotal: AUTHOR });
  const groups = groupsOf(html);
  assert.equal(groups[groups.indexOf("Total") + 1], "Author", groups.join(" > "));
  assert.ok(html.includes("incl. plan ahead"), "the Total lost its note");
  assert.ok(html.replace(/<[^>]*>/g, "").includes("Author's total: 1\u00a0hr, before the waits"),
            "the author's figure is not on the page");
});

test("no author line is drawn when the server does not send one", () => {
  const html = render({ waits: [WAIT], total: { label: "4 hr 30 min" } });
  assert.ok(!html.includes("tb-author"), "an empty author line was drawn");
});
