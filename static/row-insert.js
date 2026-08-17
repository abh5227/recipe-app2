"use strict";
// Where a per-row insert lands. Pure (no DOM, no `view`), so it's unit-testable under bare
// `node --test`. It lives in its OWN module rather than in ingredient-row.js or step-row.js because
// it is the one piece of B that is genuinely list-agnostic: ingredients and steps are different row
// shapes with different re-render rules, but "above row i" means the same thing in both, and having
// one definition is the point — two copies would be two chances to disagree by one.

// THE RULE, stated plainly so nobody re-derives it from the call site:
//   "Add above row i" inserts AT i        -> the new row takes i's place, i shifts down.
//   "Add below row i" inserts AT i + 1    -> the new row sits directly after i.
// Both are indices into the array BEFORE the splice, which is what Array.prototype.splice wants.
//
// HEADINGS are not a special case here, and that is deliberate. A heading owns the rows that follow
// it until the next heading — sections are implicit in POSITION, not a container — so the arithmetic
// is identical and the section membership falls out of where the row lands:
//   "Add below" on a heading   -> i + 1, the first row INSIDE that section.
//   "Add above" on a heading   -> i, which is OUTSIDE it: the row becomes the last row of the
//                                 PRECEDING section, or the new first row of the list. That is the
//                                 honest consequence of positional sections, not a bug to patch — the
//                                 row you clicked is the section's own header, so "above" it is
//                                 genuinely before the section starts.
// The inserted row is always a NORMAL row; callers never pass the heading shape here. Making a
// heading is a separate action (the To heading item), so inserting never has to guess.
//
// Returns null — meaning "do nothing" — for any index that isn't a real row of a list of `len`.
// Refusing rather than clamping is the safe direction because inserting is a CONTENT MUTATION, and
// every plausible bad input has a silently-wrong clamp: splice(-1) inserts before the LAST element
// rather than at the top, splice(NaN) inserts at 0, and splice(999) appends. A stale data-i between
// a splice and its re-render is a real thing on these delegated handlers (see writeStepField's note),
// so the wrong answer here would be a mis-placed row with no error anywhere.
// An EMPTY list therefore always returns null. That is unreachable in the UI by construction — the
// menu hangs off a row's own ⋯ trigger, so no rows means no menu — and the end-of-list adders are how
// you start an empty list. It's pinned by a test so the reasoning survives a refactor.
function insertIndexFor(pos, i, len) {
  if (!Number.isInteger(len) || len < 0) return null;
  if (!Number.isInteger(i) || i < 0 || i >= len) return null;
  return pos === "below" ? i + 1 : i;
}

export { insertIndexFor };
