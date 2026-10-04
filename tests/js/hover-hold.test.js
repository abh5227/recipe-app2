"use strict";
// The hold that keeps a step's controls on screen while the pointer crosses the gap to reach them.
// Driven at exact milliseconds with no timers, which is the reason the clock is an argument.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeHold, HOLD_MS } from "../../static/hover-hold.js";

test("the shipped delay is 300ms", () => {
  assert.equal(HOLD_MS, 300);
  assert.equal(makeHold().delay, 300);
});

test("entering shows the area, leaving does not hide it on its own", () => {
  const h = makeHold(300);
  assert.equal(h.held(), null);
  h.enter("s1", 0);
  assert.equal(h.held(), "s1");
  h.leave(100);
  assert.equal(h.held(), "s1", "the pointer has left, the control is still reachable");
  assert.equal(h.leaving(), true);
  assert.equal(h.dueAt(), 400);
});

test("it hides only once the delay has passed", () => {
  const h = makeHold(300);
  h.enter("s1", 0);
  h.leave(100);
  assert.equal(h.settle(399), "s1", "one millisecond early is still shown");
  assert.equal(h.settle(400), null, "and at the delay it goes");
  assert.equal(h.leaving(), false);
});

test("re-entering cancels the hide, which is the whole point", () => {
  // ⚠️ THE CASE THE GAP CREATES. The pointer leaves the step, crosses two pixels of nothing, and
  //    lands on "+ note". Without this the control disappeared under the cursor on the way.
  const h = makeHold(300);
  h.enter("s1", 0);
  h.leave(100);
  h.enter("s1", 180);          // reached the control
  assert.equal(h.leaving(), false);
  assert.equal(h.settle(10000), "s1", "no hide is pending, so time passing changes nothing");
});

test("a second leave after a re-entry starts the clock again", () => {
  const h = makeHold(300);
  h.enter("s1", 0);
  h.leave(100);
  h.enter("s1", 180);
  h.leave(200);
  assert.equal(h.dueAt(), 500);
  assert.equal(h.settle(499), "s1");
  assert.equal(h.settle(500), null);
});

test("moving to another step switches at once, with no overlap", () => {
  // Two steps showing their controls at the same time would be two invitations to one click.
  const h = makeHold(300);
  h.enter("s1", 0);
  h.leave(100);
  h.enter("s2", 120);
  assert.equal(h.held(), "s2");
  assert.equal(h.leaving(), false);
  assert.equal(h.settle(1000), "s2", "s1 is not resurrected by the pending hide it left behind");
});

test("leave is idempotent: the clock starts when the pointer FIRST left", () => {
  // pointerout fires more than once while a pointer crosses nested elements on its way out.
  const h = makeHold(300);
  h.enter("s1", 0);
  h.leave(100);
  h.leave(250);
  h.leave(299);
  assert.equal(h.dueAt(), 400, "still measured from the first leave");
  assert.equal(h.settle(400), null);
});

test("settle does nothing while the pointer is inside", () => {
  const h = makeHold(300);
  h.enter("s1", 0);
  assert.equal(h.settle(99999), "s1");
});

test("clear hides at once, for Escape and for a click elsewhere", () => {
  const h = makeHold(300);
  h.enter("s1", 0);
  assert.equal(h.clear(), null);
  assert.equal(h.held(), null);
  assert.equal(h.leaving(), false);
});

test("entering nothing is not a command to hide", () => {
  // The pointer moving over the page background sends no key; that must not clear a held area.
  const h = makeHold(300);
  h.enter("s1", 0);
  h.enter(null, 50);
  assert.equal(h.held(), "s1");
});

test("a zero delay still needs a settle, so a caller cannot hide by accident", () => {
  const h = makeHold(0);
  h.enter("s1", 0);
  h.leave(10);
  assert.equal(h.held(), "s1");
  assert.equal(h.settle(10), null);
});
