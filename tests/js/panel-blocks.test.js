"use strict";
// Pins the drawer's one visibility rule (static/panel-blocks.js): no data, no block. Silent-
// regression-prone in both directions — a block that shows when empty renders a heading over
// nothing, and a block that hides when full silently loses curated content — so the populated
// cases are asserted as hard as the empty ones. Pure, runs under bare `node --test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { panelBlocks } from "../../static/panel-blocks.js";

const CURATED = {                        // what one of the 36 looks like
  name: "Lemon", descr: "A winter citrus.", pairs: "Garlic, olive oil, and herbs.",
  season: [12, 1, 2, 3, 4], regions: ["California", "Sicily"], used_in: [{ id: "r", name: "R" }],
};
const PROMOTED = {                       // what the save gate creates
  name: "penne", descr: null, pairs: null, season: [], regions: [], used_in: [],
};

test("a fully curated row shows every block", () => {
  assert.deepEqual(panelBlocks(CURATED), { season: true, regions: true, pairs: true, used: true });
});

test("a fully thin promoted row shows none of them", () => {
  assert.deepEqual(panelBlocks(PROMOTED),
                   { season: false, regions: false, pairs: false, used: false });
});

test("an empty season hides its block, and the tier makes no difference", () => {
  // ⚠️ THE 22-ROW CHANGE, MADE ON PURPOSE. soy_sauce and 21 other CURATED rows carry no
  // ingredient_seasons rows and used to render "A pantry staple, available year-round". One rule
  // for every row means the seed row and the app row now behave identically.
  const soy = { ...CURATED, name: "Soy Sauce", season: [], source: "seed" };
  const app = { ...CURATED, name: "penne", season: [], source: "app" };
  assert.equal(panelBlocks(soy).season, false);
  assert.equal(panelBlocks(app).season, false);
  assert.equal(panelBlocks(soy).regions, true, "its other blocks are untouched");
  assert.equal(panelBlocks(soy).pairs, true);
});

test("empty regions and empty pairs each hide only themselves", () => {
  assert.deepEqual(panelBlocks({ ...CURATED, regions: [] }),
                   { season: true, regions: false, pairs: true, used: true });
  assert.deepEqual(panelBlocks({ ...CURATED, pairs: "" }),
                   { season: true, regions: true, pairs: false, used: true });
});

test("pairs counts whitespace as empty, and null as empty", () => {
  assert.equal(panelBlocks({ ...CURATED, pairs: "   " }).pairs, false);
  assert.equal(panelBlocks({ ...CURATED, pairs: null }).pairs, false);
  assert.equal(panelBlocks({ ...CURATED, pairs: "Lime." }).pairs, true);
});

test("missing keys and a missing item do not throw", () => {
  assert.deepEqual(panelBlocks({}), { season: false, regions: false, pairs: false, used: false });
  assert.deepEqual(panelBlocks(null), { season: false, regions: false, pairs: false, used: false });
  assert.deepEqual(panelBlocks(undefined),
                   { season: false, regions: false, pairs: false, used: false });
});

test("used_in still drives used-block exactly as it always did", () => {
  assert.equal(panelBlocks({ ...CURATED, used_in: [] }).used, false);
  assert.equal(panelBlocks({ ...CURATED, used_in: [{ id: "a", name: "A" }] }).used, true);
});
