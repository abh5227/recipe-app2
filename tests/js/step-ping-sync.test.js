"use strict";
// Cross-file guard: the step highlight's duration is written in TWO places — the CSS animation that
// draws it and the setTimeout that takes the class off again — and they have to agree. Too short a
// timeout cuts the highlight off mid-fade; too long and a second tap on the same step cannot
// restart it. Same arrangement as timefmt-sync holds the two time formatters together.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "../..");
const APP = fs.readFileSync(path.join(ROOT, "static/app.js"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "static/styles.css"), "utf8");

const jsMs = Number((APP.match(/const STEP_PING_MS = (\d+);/) || [])[1]);
const cssSec = Number((CSS.match(/\.steps li\.step\.step-ping \{ animation: step-ping ([\d.]+)s/) || [])[1]);

test("the JS timeout and the CSS animation name the same duration", () => {
  assert.ok(Number.isFinite(jsMs), "STEP_PING_MS not found in app.js");
  assert.ok(Number.isFinite(cssSec), "the step-ping animation duration not found in styles.css");
  assert.equal(jsMs, cssSec * 1000);
});

test("the highlight holds before it fades", () => {
  // The hold is what the change was for: the smooth scroll has to finish carrying the step into
  // view while the amber is still at full strength.
  const kf = CSS.match(/@keyframes step-ping \{([\s\S]*?)\n\}/);
  assert.ok(kf, "the step-ping keyframes are gone");
  const holdTo = Number((kf[1].match(/0%,\s*(\d+)%/) || [])[1]);
  assert.ok(holdTo > 0, "no hold segment — the highlight starts fading immediately");
  const holdMs = (holdTo / 100) * jsMs;
  assert.ok(holdMs >= 1800 && holdMs <= 2300,
    `the hold is ${holdMs}ms, which is not the ~2s that was asked for`);
});

test("reduced motion keeps the highlight and drops the fade", () => {
  // ⚠️ IT USED TO SET animation-duration: 1ms, which removed the highlight altogether. Someone who
  // asks for less motion still has to be able to find the step they just tapped.
  const block = CSS.match(/@media \(prefers-reduced-motion: reduce\) \{\s*\.steps li\.step\.step-ping \{([^}]*)\}/);
  assert.ok(block, "no reduced-motion rule for the step highlight");
  assert.doesNotMatch(block[1], /duration:\s*1ms/, "1ms removes the affordance instead of the motion");
  assert.match(block[1], /steps\(1,\s*end\)/, "the colour should cut rather than ramp");
});
