"use strict";
// Pure Notes-grouping transform (no DOM, no `view`), the display half of the note-kinds rule.
// app.js imports it in the browser and tests/js/note-blocks.test.js imports it the same way —
// the same arrangement panel-blocks.js and step-row.js use.
//
// ⚠️ IT TAKES ROWS NOW, NOT A STRING. Migration 060 made a note a row with its own id, kind and
// links, and recipes.notes became a derived copy kept only so the previous deploy can still serve.
// The paragraph split still exists below for that older shape and for a test fixture, but the page
// never calls it.
//
// ⚠️ GROUPING IS DISPLAY-ONLY AND THE STORED TEXT IS UNTOUCHED. The row's `kind` column decides
// which group it sits in. The LABEL is a separate question: a label the table knows is stripped for
// display, and one it does not know stays, because stripping it would delete the only thing naming
// what the note is about. 27 of the corpus's 177 paragraphs are in that shape against 23 in the
// other, so the unlisted case is the common one.
//
// ⚠️ THE KIND TABLE IS A SHARED FIXTURE, not a literal in this file. import_cleanup reads the same
// static/note-kinds.json for the data rule, so the two cannot disagree about what "Storing."
// means. The table is injected rather than imported because this module must stay dependency-free
// for the zero-dep JS suite; app.js passes the baked copy and the test passes the fixture.

// A leading label: a short capitalized-ish phrase, then a colon or a period, then the note itself.
// The period form is real and common ("Flour. This recipe works best with..." on brioche-bread).
// ⚠️ KEEP IN STEP WITH import_cleanup._NOTE_LEAD. tests/js/note-kinds-sync.test.js pins it.
const LEAD = /^\s*([A-Za-z][A-Za-z '’/-]{0,28}?)\s*[:.–—-]\s+(\S[\s\S]*)$/;

function normLabel(s) {
  return String(s || "").replace(/’/g, "'").trim().replace(/\s+/g, " ").toLowerCase();
}

// Split stored notes into paragraphs. A blank line separates them, which is the convention the
// corpus already keeps (82 of its newline runs are exactly one blank line, 19 are a single newline
// INSIDE a paragraph). Kept for the old string shape; the row path never calls it.
function noteParagraphs(text) {
  return String(text == null ? "" : text).split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
}

// One paragraph -> {kind, header, text}. `table` is the shared kind list.
// ⚠️ AN UNLISTED LABEL KEEPS ITS TEXT WHOLE AND SITS UNDER "Notes". See the header note.
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

// ⚠️ THE LABEL IS STRIPPED ONLY WHEN IT AGREES WITH THE ROW'S KIND. A cook who moves a note reading
// "Tip: ..." into Storage has changed the kind and not the words, and hiding the word "Tip" would
// quietly edit the note to match a decision they can still undo.
function displayParts(row, table) {
  const c = classifyNote(String(row.text || ""), table);
  const stripped = c.kind === row.kind && c.text !== row.text;
  return { text: stripped ? c.text : String(row.text || ""), stripped };
}

// ⚠️ ONE COPY OF THE LABEL RULE, READ BY THE PAGE AND BY THE EDITOR. The editor used to seed itself
// from the STORED text, so a note read "Increase water…" and edited "SAME DAY VERSION: increase
// water…", and the two disagreed about what the note said. Both go through displayParts now, and
// `stripped` is what tells the renderer whether the first letter needs a capital.
function displayText(row, table) { return displayParts(row, table).text; }

// Note ROWS -> [{kind, header, notes: [row]}], in order of a kind's first appearance.
// ⚠️ A KIND IS ONE BLOCK EVEN WHEN ITS ROWS ARE NOT ADJACENT. beans writes Note, Note, Tip and reads
// as two blocks; a recipe that alternates would otherwise print the same header twice.
export function noteBlocks(rows, table) {
  const headers = new Map(table.map((k) => [k.kind, k.header]));
  const order = [];
  const byKind = new Map();
  for (const row of rows || []) {
    const kind = headers.has(row.kind) ? row.kind : table[0].kind;
    if (!byKind.has(kind)) {
      byKind.set(kind, { kind, header: headers.get(kind), notes: [] });
      order.push(kind);
    }
    const d = displayParts({ ...row, kind }, table);
    byKind.get(kind).notes.push({ ...row, display: d.text, displayStripped: d.stripped });
  }
  return order.map((k) => byKind.get(k)).filter((b) => b.notes.length);
}

// The old string shape, for a payload that predates migration 060.
// ⚠️ NOTHING ON THE PAGE CALLS THIS. app.js renders rows through noteBlocks; this is reachable only
// from the tests and from a caller holding pre-060 data. It is kept because the paragraph split and
// the label classifier are stated through it in tests/js/note-blocks.test.js, and because the
// column it reads is retired rather than dropped. Delete it with the column.
export function noteBlocksFromText(text, table) {
  return noteBlocks(noteParagraphs(text).map((p, i) => {
    const c = classifyNote(p, table);
    return { id: -1 - i, kind: c.kind, text: p, step_id: null, step_no: null, refs: [] };
  }), table);
}

export { noteParagraphs, classifyNote, normLabel, displayText, displayParts, LEAD };
