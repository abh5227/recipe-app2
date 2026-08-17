"use strict";
// Where a struck REMOVED annotation row is spliced into a rendered list — pure (no DOM, no `view`), so
// it's unit-testable in node like ingredient-row.js / step-row.js. app.js imports it in the browser.
//
// The rule the O-c-0 engine implies but doesn't spell out: a removed item's `section` is the text of the
// nearest heading PRECEDING it in the original, or null when none preceded it. That null carries TWO
// different meanings, and conflating them is what sent a removed step past every section to the very
// bottom of the method list:
//   (a) the list has NO headings at all  -> the list bottom IS the only section's bottom. Correct.
//   (b) the item lived in the UNNAMED PREAMBLE above the first heading -> its section ends where the
//       FIRST heading begins, so it belongs immediately BEFORE that heading, not after everything.
// A named section that no longer exists (renamed/deleted) still falls to the list bottom, deliberately:
// the preamble is a REAL section, and routing genuinely unplaceable rows into it would put rows there
// that were never in it. List bottom stays the honest junk drawer.

// `items` only needs {isHeading, headingText} per entry. Returns the splice index.
function removedInsertIndex(items, section) {
  const name = section == null ? "" : String(section);
  if (!name) {                                        // null/undefined/"" -> the unnamed preamble
    const first = items.findIndex((x) => x.isHeading);
    return first === -1 ? items.length : first;       // no headings at all -> list bottom (case a)
  }
  const h = items.findIndex((x) => x.isHeading && x.headingText === name);
  if (h === -1) return items.length;                  // section since renamed/removed -> list bottom
  for (let k = h + 1; k < items.length; k++) {
    if (items[k].isHeading) return k;                 // the section ends at the next heading
  }
  return items.length;                                // last section -> list bottom
}

export { removedInsertIndex };
