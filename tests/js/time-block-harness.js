"use strict";
// Run app.js's REAL time-block renderer in a test.
//
// ⚠️ app.js CANNOT BE IMPORTED HERE. It pulls TipTap through a bare specifier, and the JS suite is
// deliberately zero-dependency: it runs on the source with no node_modules. So scaleMetaBlock is cut
// out of the file by brace balance and run with the handful of globals it reads. Nothing is
// retyped, so a change to the renderer changes what the tests execute.
//
// ⚠️ ONE COPY, TWO TEST FILES. The column rule and the second Total both need the markup, and a
// harness written out twice is the drift this repository has a standing rule against.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "../..");
export const APP = fs.readFileSync(path.join(ROOT, "static/app.js"), "utf8");
export const CSS = fs.readFileSync(path.join(ROOT, "static/styles.css"), "utf8");

/** A top-level function's source, from `function <name>(` to the `}` in column 1. */
export function sliceFunction(name, source = APP) {
  const lines = source.split("\n");
  const start = lines.findIndex((l) => l.startsWith(`function ${name}(`));
  assert.ok(start >= 0, `${name} is not a top-level function in app.js any more`);
  // ⚠️ BOUNDED, BECAUSE PAST THE END lines[end] IS undefined AND NEVER EQUALS "}". The start anchor
  //    was asserted and the end was not, so a function whose closing brace stopped being in column 1
  //    span the suite forever with no output instead of failing. A hang is the worst failure a test
  //    can have: it reports nothing at all.
  let end = start;
  while (end < lines.length && lines[end] !== "}") end += 1;
  assert.ok(end < lines.length, `${name} has no closing } in column 1, so it cannot be sliced`);
  return lines.slice(start, end + 1).join("\n");
}

const DEPS = ["view", "esc", "timeParts", "bindUnits", "formatAmount", "servingsBase",
              "scaleControl", "WAIT_VERBS", "STORE_PLACE",
              "META_CLOCK", "META_HOURGLASS", "META_JAR", "META_FIG"];

const build = new Function(...DEPS, `${sliceFunction("scaleMetaBlock")}; return scaleMetaBlock;`);

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// the real one, from the module app.js imports it from
const { bindUnits } = await import(path.join(ROOT, "static/timefmt.js"));
const WAIT_VERBS = { marinating: "Marinate", chilling: "Chill", rising: "Rise", soaking: "Soak",
                     resting: "Rest", freezing: "Freeze", brining: "Brine", other: "Wait" };
const STORE_PLACE = { fridge: "fridge", freezer: "freezer", "room temp": "room temperature",
                      other: "" };

/** The block's markup for one made-up recipe. */
export function renderTimeBlock({ waits = [], storage = [], total = {}, conds = [],
                                  servings = "4", prep = "10 min", cook = "20 min",
                                  waitTotal = null, authorTotal = null } = {}) {
  const recipe = { prep_time: prep, cook_time: cook, servings };
  const view = {
    scale: 1, waits, storage,
    waitTotal: waitTotal || { label: waits.length ? "8 hr+" : "" },
    data: { recipe, total, conditional_totals: conds, author_total: authorTotal },
  };
  const fn = build(view, esc, (raw) => ({ value: raw, note: "" }), bindUnits,
                   (n) => String(n), () => (servings ? 4 : null),
                   () => "<div class='scale'></div>", WAIT_VERBS, STORE_PLACE,
                   "<svg id=clock>", "<svg id=hg>", "<svg id=jar>", "<svg id=fig>");
  return fn(recipe);
}

/** The groups the block renders, in DOM order. ⚠️ DOM ORDER IS READING ORDER IN BOTH LAYOUTS: the
 *  phone collapses the grid to one column in source order, and the two desktop columns are a FOLD
 *  in that same order rather than a different one. So one assertion covers both. */
export function groupsOf(html) {
  // ⚠️ THE SEPARATOR IS WRITTEN BOTH WAYS IN THE SAME BLOCK, so it is matched both ways.
  //    "Prep" is held to its figure with a non-breaking space (a0) and "Serves" is not (20).
  //    A helper that assumed one of them silently reported the other group as absent, which is
  //    the direction that makes an order assertion pass over a shorter list than it thinks.
  const SP = "[ \\u00a0]";
  const MARKS = [[`>Prep${SP}`, "Prep"], [`>Cook${SP}`, "Cook"], [`>Total${SP}`, "Total"],
                 ["tb-author", "Author"],
                 ["meta-conditional(?![\"' ]*tb-author)", "2nd"],
                 [`>Serves${SP}`, "Serves"], ["Plan\\u00a0ahead", "Plan ahead"],
                 [">Keeps<", "Keeps"]];
  const found = [];
  for (const [src, name] of MARKS) {
    const g = new RegExp(src, "g");
    let m;
    while ((m = g.exec(html)) !== null) found.push([m.index, name]);
  }
  return found.sort((a, b) => a[0] - b[0]).map(([, name]) => name);
}
