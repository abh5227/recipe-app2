"use strict";
// The plan-ahead editor's two pure decisions: what a wait or storage row's menu offers, and what an
// item does to the list.
//
// ⚠️ WHY THESE ARE A TEST AND NOT A CLICK-THROUGH. The reorder and the insert are array surgery on
// the rows a recipe is made of, and while they sat inside a DOM handler nothing could state them.
// A swap that writes the wrong index puts one wait's reviewed minutes onto another wait's words,
// and brioche-bread's extension carries a figure a REVIEWER read rather than one read_duration
// produced, so there is wording in this corpus whose minutes cannot be re-derived.
import { test } from "node:test";
import assert from "node:assert/strict";
import { planAheadMenuItems, planAheadRowAction, blankWait, blankStorage, PLAN_AHEAD_KINDS }
  from "../../static/plan-ahead-rows.js";

const labels = (kind, i, n) => planAheadMenuItems(kind, i, n)
  .filter((x) => !x.sep)
  .map((x) => x.label + (x.disabled ? " [disabled]" : ""));

// --- the menu -------------------------------------------------------------------------------------

test("a wait and a storage row each name what they add", () => {
  assert.deepEqual(labels("wait", 1, 3), ["Add wait", "Move up", "Move down", "Delete"]);
  assert.deepEqual(labels("store", 1, 3),
                   ["Add storage row", "Move up", "Move down", "Delete"]);
});

test("the ends disable a move rather than hiding it", () => {
  // ⚠️ DISABLED, NOT ABSENT, so the menu does not change shape as a row travels through the list.
  assert.deepEqual(labels("wait", 0, 3),
                   ["Add wait", "Move up [disabled]", "Move down", "Delete"]);
  assert.deepEqual(labels("wait", 2, 3),
                   ["Add wait", "Move up", "Move down [disabled]", "Delete"]);
  assert.deepEqual(labels("wait", 0, 1),
                   ["Add wait", "Move up [disabled]", "Move down [disabled]", "Delete"]);
});

test("the menu offers no heading and no conversion, because the rows have neither", () => {
  for (const kind of PLAN_AHEAD_KINDS) {
    const acts = planAheadMenuItems(kind, 0, 2).filter((x) => !x.sep).map((x) => x.act);
    assert.deepEqual(acts, ["add-row", "up", "down", "delete"]);
  }
});

test("delete is the only dangerous item", () => {
  const danger = planAheadMenuItems("wait", 0, 2).filter((x) => x.danger).map((x) => x.act);
  assert.deepEqual(danger, ["delete"]);
});

// --- what an item does ----------------------------------------------------------------------------

const rows = () => [{ label: "a" }, { label: "b" }, { label: "c" }];
const names = (r) => (r || []).map((x) => x.label);

test("add puts the new row directly below the one whose menu was used", () => {
  assert.deepEqual(names(planAheadRowAction(rows(), 0, "add-row", { label: "NEW" })),
                   ["a", "NEW", "b", "c"]);
  assert.deepEqual(names(planAheadRowAction(rows(), 2, "add-row", { label: "NEW" })),
                   ["a", "b", "c", "NEW"]);
});

test("delete takes only that row", () => {
  assert.deepEqual(names(planAheadRowAction(rows(), 1, "delete")), ["a", "c"]);
});

test("a move swaps the row OBJECTS, so everything they carry travels with them", () => {
  // ⚠️ NOT THEIR TEXT. A wait carries its minutes, its three step links and its condition beside its
  //    words, and moving the words alone leaves all of that behind.
  const a = { label: "rise", min_minutes: 90, step_id: 41, when_kind: "only_if" };
  const b = { label: "chill", min_minutes: 480, step_id: 77, when_kind: "always" };
  const out = planAheadRowAction([a, b], 1, "up");
  assert.deepEqual(out, [b, a]);
  assert.equal(out[0].min_minutes, 480, "the minutes moved with the words");
  assert.equal(out[0].step_id, 77);
  assert.equal(out[1].when_kind, "only_if");
});

test("a move down is the mirror of a move up", () => {
  assert.deepEqual(names(planAheadRowAction(rows(), 0, "down")), ["b", "a", "c"]);
  assert.deepEqual(names(planAheadRowAction(rows(), 1, "up")), ["b", "a", "c"]);
});

test("a move off either end is refused, and refusing returns null", () => {
  // null is "nothing happened", which is how the caller knows not to repaint or mark the draft dirty.
  assert.equal(planAheadRowAction(rows(), 0, "up"), null);
  assert.equal(planAheadRowAction(rows(), 2, "down"), null);
});

test("the list it is given is never touched, so a refused action leaves nothing half-edited", () => {
  const original = rows();
  const copy = original.slice();
  planAheadRowAction(original, 1, "delete");
  planAheadRowAction(original, 0, "up");
  planAheadRowAction(original, 1, "add-row", { label: "x" });
  assert.deepEqual(original, copy, "planAheadRowAction mutated its argument");
});

test("an index naming no row does nothing rather than guessing a position", () => {
  // A menu can outlive the row it belonged to. The two big lists state this rule in row-insert.js.
  for (const i of [-1, 3, 99, null, undefined, 1.5, "1"]) {
    assert.equal(planAheadRowAction(rows(), i, "delete"), null, `index ${i} should be refused`);
    assert.equal(planAheadRowAction(rows(), i, "up"), null);
  }
});

test("adding to an EMPTY list still works, which is the one index-less case that must", () => {
  assert.deepEqual(names(planAheadRowAction([], 0, "add-row", { label: "first" })), ["first"]);
  assert.deepEqual(names(planAheadRowAction(undefined, 0, "add-row", { label: "first" })), ["first"]);
});

test("an unknown action does nothing", () => {
  assert.equal(planAheadRowAction(rows(), 1, "toggle"), null);
  assert.equal(planAheadRowAction(rows(), 1, "level"), null);
});

// --- the blank rows -------------------------------------------------------------------------------

test("a blank wait carries every field the save path reads, including all THREE step links", () => {
  // ⚠️ THE "+ add a wait" BUTTON'S OWN LITERAL WAS SHORT: it had no ext_step_id, so a wait added
  //    that way could not carry the alternative's step link until the row had been saved and
  //    re-read. One definition, two doors.
  assert.deepEqual(Object.keys(blankWait()).sort(),
    ["alongside_step_id", "ext_label", "ext_step_id", "kind", "label", "step_id",
     "when_kind", "when_label"]);
  assert.equal(blankWait().when_kind, "always", "a new wait counts toward the Total by default");
  assert.equal(blankWait().kind, "other");
  for (const k of ["step_id", "alongside_step_id", "ext_step_id"]) {
    assert.equal(blankWait()[k], null, `${k} starts as a null pointer, never 0 or ""`);
  }
});

test("a blank storage row says where, because that is the one thing storage is for", () => {
  assert.deepEqual(Object.keys(blankStorage()).sort(), ["applies_to", "label", "where_kept"]);
  assert.equal(blankStorage().where_kept, "fridge");
});

test("each blank is a FRESH object, so two added rows are not the same row twice", () => {
  const a = blankWait();
  const b = blankWait();
  a.label = "changed";
  assert.equal(b.label, "", "the blanks share state");
  assert.notEqual(blankStorage(), blankStorage());
});
