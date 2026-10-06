"use strict";
// ⚠️ "SHARE THE RULE, DON'T COPY VALUES" IS A CLAIM ABOUT THE STYLESHEET, so it is checked in the
// stylesheet. Andy's instruction for a note's title was that it takes the step SUBHEADING's look,
// and the way that goes wrong is not a wrong value today, it is a right value that drifts: the
// subheading's own size read 15px for a while, which is the step's size, so nothing but the weight
// separated a heading from the sentence under it. This file fails if .note-title stops being part
// of the same declaration block rather than when its numbers stop matching.
//
// The method column already learned this twice. .notes-kind carried its own 12px mono block until
// it was folded into .steps li.group, and the comment above that fold says why in as many words.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const CSS = fs.readFileSync(
  path.join(import.meta.dirname, "../../static/styles.css"), "utf8");

/** Every rule whose selector list contains `sel`, as {selectors, body}. */
function rulesFor(sel) {
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(CSS)) !== null) {
    const selectors = m[1].replace(/\/\*[\s\S]*?\*\//g, "")
      .split(",").map((s) => s.trim()).filter(Boolean);
    if (selectors.includes(sel)) out.push({ selectors, body: m[2] });
  }
  return out;
}

test("the subheading rule exists and names both the method column and a note's title", () => {
  const rules = rulesFor(".note-title");
  assert.ok(rules.length > 0, ".note-title has no rule at all");
  const shared = rules.find((r) => r.selectors.includes(".steps li.group.h2"));
  assert.ok(shared, `.note-title is not in the step subheading's own rule: ` +
    JSON.stringify(rules.map((r) => r.selectors)));
  // the four declarations that ARE the subheading's look, read off the shared block
  for (const prop of ["font-family", "font-size", "font-weight", "text-transform"]) {
    assert.ok(new RegExp(`\\b${prop}\\s*:`).test(shared.body),
      `the shared block does not set ${prop}: ${shared.body}`);
  }
  assert.ok(/var\(--fs-step-sub\)/.test(shared.body),
    "the size has to be the token, not a number");
});

test("no other rule restates the subheading's typography for a note title", () => {
  // A second rule setting font-size or font-family on .note-title is the copy this exists to stop.
  // Margins are allowed: the notes column has no 16px row gap of its own, so spacing is local.
  for (const r of rulesFor(".note-title")) {
    if (r.selectors.includes(".steps li.group.h2")) continue;
    assert.ok(!/font-family\s*:|font-size\s*:|font-weight\s*:/.test(r.body),
      `${r.selectors.join(", ")} restates the subheading's typography: ${r.body}`);
  }
});

test("a titled note's bullet is suppressed after the Edit-mode indent, or source order loses", () => {
  // ⚠️ BOTH SELECTORS CARRY FOUR CLASSES, so specificity is a tie and position decides. The
  //    Edit-mode indent is .ie-note-block .notes-group.marked .notes-para.
  const ie = CSS.indexOf(".ie-note-block .notes-group.marked .notes-para {");
  const titled = CSS.indexOf(".notes-group.marked .notes-para.titled,");
  assert.ok(ie > 0, "the Edit-mode indent rule moved or was renamed");
  assert.ok(titled > 0, "the titled override is missing");
  assert.ok(titled > ie, "the titled override has to come after the Edit-mode indent");
  assert.ok(/\.notes-group\.marked \.notes-para\.titled::before \{ content: none; \}/.test(CSS),
    "the bullet itself is not switched off");
});

test("the shared subheading rule STATES the section headings' colour", () => {
  // ⚠️ THE ONE DECLARATION THE SHARED RULE DID NOT SHARE WAS THE COLOUR, and each side then took it
  //    from its own ancestor: a step subheading got var(--green) from .steps li.group above it, a
  //    note title got var(--ink-soft) from the .notes card it sits in. Measured rgb(78,75,36)
  //    against rgb(110,88,66) on one page. Andy's call, 2026-10-06.
  const shared = rulesFor(".note-title").find((r) => r.selectors.includes(".steps li.group.h2"));
  assert.ok(shared, "the shared subheading rule is gone");
  const colour = /(?:^|;|\{|\s)color\s*:\s*([^;]+)/.exec(shared.body);
  assert.ok(colour, `the shared block sets no colour: ${shared.body}`);
  // the VARIABLE, never a copy of its value
  assert.match(colour[1].trim(), /^var\(--[a-z-]+\)$/,
    `the colour has to be a token, not a literal: ${colour[1]}`);

  // and it is the SAME token the section headings read, so the two cannot drift
  const section = rulesFor(".notes-kind").find((r) => r.selectors.includes(".steps li.group"));
  assert.ok(section, "the section heading's own shared rule is gone");
  const sectionColour = /(?:^|;|\{|\s)color\s*:\s*([^;]+)/.exec(section.body);
  assert.ok(sectionColour, "the section rule sets no colour");
  assert.equal(colour[1].trim(), sectionColour[1].trim(),
    "a subheading and a section heading have to name one variable");
});

test("only the colour joined the shared rule, the rest of the look is unchanged", () => {
  const shared = rulesFor(".note-title").find((r) => r.selectors.includes(".steps li.group.h2"));
  assert.match(shared.body, /font-size\s*:\s*var\(--fs-step-sub\)/, "the size moved");
  assert.match(shared.body, /font-weight\s*:\s*700/, "the weight moved");
  assert.match(shared.body, /text-transform\s*:\s*none/, "the case moved");
  assert.match(shared.body, /font-family\s*:\s*var\(--font-serif\)/, "the family moved");
});
