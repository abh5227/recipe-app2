"use strict";
// Pure Notes-grouping transform (no DOM, no `view`), the display half of the note-kinds rule.
// app.js imports it in the browser and tests/js/note-blocks.test.js imports it the same way —
// the same arrangement panel-blocks.js and step-row.js use.
//
// ⚠️ GROUPING IS DISPLAY-ONLY. The stored text keeps the author's own labels, exactly as written.
// This decides what the page SHOWS, and nothing here is ever written back.
//
// ⚠️ THE KIND TABLE IS A SHARED FIXTURE, not a literal in this file. import_cleanup reads the same
// static/note-kinds.json for the data rule, so the two cannot disagree about what "Storing."
// means. The table is injected rather than imported because this module must stay dependency-free
// for the zero-dep JS suite; app.js passes the baked copy and the test passes the fixture.

// A leading label: a short capitalized-ish phrase, then a colon or a period, then the note itself.
// The period form is real and common ("Flour. This recipe works best with..." on brioche-bread).
const LEAD = /^\s*([A-Za-z][A-Za-z '’/-]{0,28}?)\s*[:.–—-]\s+(\S[\s\S]*)$/;

// A paragraph that is ONLY a label, with nothing under it.

function normLabel(s) {
  return String(s || "").replace(/’/g, "'").trim().replace(/\s+/g, " ").toLowerCase();
}

// Split stored notes into paragraphs. A blank line separates them, which is the convention the
// corpus already keeps (78 of its 79 newline runs are exactly one blank line).
function noteParagraphs(text) {
  return String(text == null ? "" : text).split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
}

// One paragraph -> {kind, header, text}. `table` is the shared kind list.
// ⚠️ AN UNLISTED LABEL KEEPS ITS TEXT WHOLE AND SITS UNDER "Notes". Stripping a label the table does
// not know would silently delete the only thing naming what the note is about ("Blind Bake:",
// "Tomato Bouillon:"). 17 of the corpus's labelled paragraphs are in that shape, so this is the
// common case, not the edge one.
function classifyNote(para, table) {
  const m = LEAD.exec(para);
  if (m) {
    const want = normLabel(m[1]);
    for (const k of table) {
      if (k.labels.some((l) => normLabel(l) === want)) {
        return { kind: k.kind, header: k.header, text: m[2].trim() };   // label stripped
      }
    }
  }
  const first = table[0];
  return { kind: first.kind, header: first.header, text: para };        // unchanged
}

// Stored notes -> [{kind, header, paras: [text]}], in order of a kind's first appearance.
// ⚠️ A KIND IS ONE BLOCK EVEN WHEN ITS PARAGRAPHS ARE NOT ADJACENT. beans writes Note, Note, Tip and
// reads as two blocks; a recipe that alternates would otherwise print the same header twice.
export function noteBlocks(text, table) {
  const order = [];
  const byKind = new Map();
  for (const para of noteParagraphs(text)) {
    const c = classifyNote(para, table);
    if (!byKind.has(c.kind)) { byKind.set(c.kind, { kind: c.kind, header: c.header, paras: [] }); order.push(c.kind); }
    byKind.get(c.kind).paras.push(c.text);
  }
  return order.map((k) => byKind.get(k)).filter((b) => b.paras.length);
}

export { noteParagraphs, classifyNote, normLabel, LEAD };
