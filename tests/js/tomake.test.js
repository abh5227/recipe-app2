"use strict";
// Pins the derived "to make" truth table (static/tomake.js). Silent-regression-prone: the
// not-mine cases are the ones that would quietly leak a mark onto other users' recipes, so
// they're asserted explicitly. Pure — runs under bare `node --test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { isToMake } from "../../static/tomake.js";

test("isToMake: mark ONLY my own never-cooked recipes", () => {
  assert.equal(isToMake({ is_mine: true,  cook_count: 0 }), true,  "mine + uncooked -> to make");
  assert.equal(isToMake({ is_mine: true,  cook_count: 3 }), false, "mine + cooked -> not");
  assert.equal(isToMake({ is_mine: false, cook_count: 0 }), false, "NOT mine + uncooked -> not (silent-regression guard)");
  assert.equal(isToMake({ is_mine: false, cook_count: 2 }), false, "not mine + cooked -> not");
});

test("isToMake: defensive on missing/odd fields", () => {
  assert.equal(isToMake({ is_mine: true }), true,              "absent cook_count -> treated as 0");
  assert.equal(isToMake({ cook_count: 0 }), false,             "absent is_mine -> not mine -> no mark");
  assert.equal(isToMake({ is_mine: 1, cook_count: 0 }), false, "is_mine must be strictly true, not truthy");
  assert.equal(isToMake(null), false,                          "null row never throws / never marks");
});
