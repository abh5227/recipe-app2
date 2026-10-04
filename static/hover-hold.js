"use strict";
// Pure hover-hold timing (no DOM, no timers of its own): the rule that decides when a hovered
// step's controls go away.
//
// ⚠️ IT EXISTS BECAUSE THE GAP IS WHERE THE CONTROL LIVES. "+ note" hangs off a zero-width anchor
// past the end of the step's last line and the note popover sits under the step, so reaching either
// one means crossing a few pixels that belong to neither. CSS :hover ends the moment the pointer
// leaves the element, so the control the cook was reaching for vanished on the way. The hold keeps
// the area shown for a short while after the pointer leaves it, and re-entering cancels the hide.
//
// ⚠️ THE CLOCK IS AN ARGUMENT, WHICH IS THE WHOLE REASON THIS IS ITS OWN FILE. Timing stated through
// setTimeout can only be tested by waiting, which makes a test slow and flaky. Every method takes
// `now`, so tests/js/hover-hold.test.js drives the rule at exact milliseconds with no timers at all.

export const HOLD_MS = 300;

export function makeHold(delay = HOLD_MS) {
  let shown = null;        // the area being shown, or null
  let leftAt = null;       // when the pointer left it, or null while the pointer is inside

  return {
    delay,

    // The pointer is inside `key`. Entering ALWAYS cancels a pending hide, including a hide pending
    // on a different area: moving straight from one step to the next switches immediately rather
    // than showing both for 300ms.
    enter(key, now) {
      if (key == null) return shown;
      shown = key;
      leftAt = null;
      return shown;
    },

    // The pointer has left the whole area. Nothing is hidden yet.
    leave(now) {
      if (shown !== null && leftAt === null) leftAt = now;
      return shown;
    },

    // Called on a timer or on the next event. Hides only when the pointer has left AND the delay
    // has passed. A caller that never calls this keeps the area shown, which is the safe direction.
    settle(now) {
      if (shown !== null && leftAt !== null && now - leftAt >= delay) {
        shown = null;
        leftAt = null;
      }
      return shown;
    },

    // What should be on screen right now, without advancing the clock.
    held() { return shown; },

    // True while a hide is pending, which is what tells a caller to arm a timer.
    leaving() { return leftAt !== null; },

    // When the hide is due, or null while the pointer is inside.
    dueAt() { return leftAt === null ? null : leftAt + delay; },

    // Hide at once, for Escape and for a click elsewhere.
    clear() { shown = null; leftAt = null; return shown; },
  };
}
