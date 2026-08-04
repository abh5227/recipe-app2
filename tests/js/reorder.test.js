// reorder.js — the pure album-reorder op (3d-iii): move an id to sit before another (or to the end).
// The drop handler's whole state change funnels through this, so pin the index math for the cases a drag
// produces: move forward, move backward, to front, to end, no-op, and the defensive branches.
import { test } from "node:test";
import assert from "node:assert/strict";
import { reorderBefore } from "../../static/reorder.js";

test("move backward — before an earlier photo", () => {
  assert.deepEqual(reorderBefore([1, 2, 3, 4], 4, 2), [1, 4, 2, 3]);   // 4 lands before 2
});

test("move forward — before a later photo (removal shifts indices correctly)", () => {
  assert.deepEqual(reorderBefore([1, 2, 3, 4], 1, 3), [2, 1, 3, 4]);   // 1 lands before 3
});

test("move to front — before the first photo", () => {
  assert.deepEqual(reorderBefore([1, 2, 3], 3, 1), [3, 1, 2]);
});

test("move to end — beforeId null (dropped past the last)", () => {
  assert.deepEqual(reorderBefore([1, 2, 3], 1, null), [2, 3, 1]);
});

test("no-op — dropped onto itself (beforeId === id)", () => {
  assert.deepEqual(reorderBefore([1, 2, 3], 2, 2), [1, 2, 3]);
});

test("unknown beforeId -> append (defensive, never corrupts)", () => {
  assert.deepEqual(reorderBefore([1, 2, 3], 2, 99), [1, 3, 2]);
});

test("does not mutate the input", () => {
  const src = [1, 2, 3];
  reorderBefore(src, 3, 1);
  assert.deepEqual(src, [1, 2, 3]);
});
