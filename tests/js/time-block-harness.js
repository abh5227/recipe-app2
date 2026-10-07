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
  let end = start;
  while (lines[end] !== "}") end += 1;
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
                                  waitTotal = null } = {}) {
  const recipe = { prep_time: prep, cook_time: cook, servings };
  const view = {
    scale: 1, waits, storage,
    waitTotal: waitTotal || { label: waits.length ? "8 hr+" : "" },
    data: { recipe, total, conditional_totals: conds },
  };
  const fn = build(view, esc, (raw) => ({ value: raw, note: "" }), bindUnits,
                   (n) => String(n), () => (servings ? 4 : null),
                   () => "<div class='scale'></div>", WAIT_VERBS, STORE_PLACE,
                   "<svg id=clock>", "<svg id=hg>", "<svg id=jar>", "<svg id=fig>");
  return fn(recipe);
}
