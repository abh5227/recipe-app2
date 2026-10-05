"use strict";
// The "link a step" picker's PURE half: what rows the list shows, what a typed filter keeps, and
// where the arrow keys land. No DOM, no `view`, no fetch — note-ui.js draws it and app.js wires it.
//
// ⚠️ EXTRACTED FOR THE REASON note-blocks.js AND hover-hold.js WERE. The old picker was five lines
// inside stepMenuHTML that nothing could reach from a test, and it shipped with a filter that
// matched step 2 on the query "12" because step 2's own words say "10 to 12 minutes". A rule with a
// counter-example deserves a file.
//
// ⚠️ THE TEXT CLEANER IS INJECTED, exactly as note-blocks.js takes the kind table and note-text.js
// takes esc. A step's stored words carry [[key|label]] ingredient markup and a heading carries a
// trailing colon, and the two functions that strip those live in step-adapter.js and app.js. This
// module stays dependency-free for the zero-dep JS suite, so the caller hands it a cleaner.

// ⚠️ SEVEN ROWS, AND THE LIST SCROLLS RATHER THAN SHRINKING THEM. The previous menu was a column
// flex box with a 240px cap and no minimum on its items, so the bagel's 15 steps were squeezed to
// 15px rows with their tops cut off. A number here and `flex: 0 0 auto` on the row is what makes
// "about 6 to 8 rows, then scroll" true rather than hoped for.
export const PICKER_ROWS = 7;

// How many of a step's own words stand in for it in a row. Enough to recognize the step by, short
// enough that 7 rows fit without wrapping.
export const PICKER_WORDS = 7;

// The method -> the rows the list draws, in the recipe's own order.
// ⚠️ THE RECIPE'S OWN SECTION HEADINGS ARE THE GROUPING, because it is the only grouping a cook
// already has in their head. They are rows the list prints and never rows it can select: a note
// attached to a heading resolves no number and would print without a link.
export function pickerRows(steps, clean) {
  const text = clean || ((s) => String(s == null ? "" : s));
  const out = [];
  let no = 0;
  for (const s of steps || []) {
    if (s.is_heading) {
      const label = text(s.text || "", true).trim();
      if (label) out.push({ t: "sect", text: label });
      continue;
    }
    no += 1;
    const words = text(s.text || "", false).trim().split(/\s+/).filter(Boolean);
    out.push({
      t: "step", id: s.id, no,
      words: words.slice(0, PICKER_WORDS).join(" "),
      more: words.length > PICKER_WORDS,
      hay: text(s.text || "", false).toLowerCase(),
    });
  }
  return out;
}

// ⚠️ DIGITS MEAN A NUMBER, NOT A WORD, AND THAT IS A MEASURED RULE RATHER THAN A PREFERENCE. Typing
// "12" matched the bagel's step 2 as well as its step 12, because step 2's own words read "10 to 12
// minutes". A cook typing a number means a step number, so a digits-only query is answered by the
// number alone and never by the words.
// ⚠️ AND IT MATCHES BY PREFIX, so "1" offers 1, 10, 11 rather than only 1. A list of one is not
// worth the keystroke.
export function matchesStep(row, query) {
  const q = String(query == null ? "" : query).trim().toLowerCase();
  if (!q) return true;
  if (/^\d+$/.test(q)) return String(row.no).startsWith(q);
  return row.hay.includes(q);
}

// The rows a typed filter leaves. A section heading survives only while a step under it does, so a
// filter never leaves a heading standing over nothing.
export function filterRows(rows, query) {
  const kept = [];
  let pending = null;
  for (const r of rows || []) {
    if (r.t === "sect") { pending = r; continue; }
    if (!matchesStep(r, query)) continue;
    if (pending) { kept.push(pending); pending = null; }
    kept.push(r);
  }
  return kept;
}

export function stepRowsOf(rows) {
  return (rows || []).filter((r) => r.t === "step");
}

// Where the cursor starts: the step this note is already linked to when that step is still in the
// list, else the first row. A filter that hides the current link must not leave the cursor on it.
export function startCursor(rows, linkedId) {
  const steps = stepRowsOf(rows);
  if (!steps.length) return null;
  const on = steps.find((r) => String(r.id) === String(linkedId));
  return on ? on.id : steps[0].id;
}

// ⚠️ THE ARROWS CLAMP, THEY DO NOT WRAP. A list of 15 steps that jumps from the last to the first
// hides the fact that the cook has reached the end, and the end is the thing they are looking for.
export function moveCursor(rows, cursorId, delta) {
  const steps = stepRowsOf(rows);
  if (!steps.length) return null;
  const at = steps.findIndex((r) => String(r.id) === String(cursorId));
  if (at < 0) return steps[delta < 0 ? steps.length - 1 : 0].id;
  const next = Math.min(steps.length - 1, Math.max(0, at + delta));
  return steps[next].id;
}
