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
// ⚠️ KEEP IN STEP WITH import_cleanup._NOTE_LEAD. tests/js/note-kinds-sync.test.js pins the kinds
// and tests/fixtures/note-lead-cases.json pins this pattern itself, label and body, case by case.
// ⚠️ A LETTER IS A LETTER IN ANY SCRIPT, AND [A-Za-z] SAID OTHERWISE. "Café: use a dark roast" could
// not be read as a label at all, because the é fails the inner class and the match stops there.
// ⚠️ AND THE SET IS \p{L}\p{Nl}\p{No}, NOT THE OBVIOUS \p{L}. Python spells this class [^\W\d_],
// which is every character \w admits bar a digit and the underscore: the letters, plus the Nl and No
// numerals (Ⅷ, ²), and NOT the combining marks. Writing \p{L} here would make the two sides
// disagree on Ⅷ and ², which Python admits and \p{L} does not. A DECOMPOSED "Café" is refused
// by both, since neither class takes a combining mark, and the fixture pins that agreement too.
const LEAD = /^\s*([\p{L}\p{Nl}\p{No}][\p{L}\p{Nl}\p{No} '’/-]{0,28}?)\s*[:.–—-]\s+(\S[\s\S]*)$/u;

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

// A row with its kind settled and its display text worked out, which is what every renderer wants
// and none of them should compute for itself.
// ⚠️ ONE DECORATOR, SO A NOTE IN THE STEP NOTES GROUP AND THE SAME NOTE IN A TYPE GROUP CANNOT
// READ DIFFERENTLY. noteBlocks did this inline and noteSections would have been a second copy.
function decorate(row, table) {
  const headers = new Map(table.map((k) => [k.kind, k.header]));
  const kind = headers.has(row.kind) ? row.kind : table[0].kind;
  const d = displayParts({ ...row, kind }, table);
  return { ...row, kind, display: d.text, displayStripped: d.stripped };
}

// Note ROWS -> [{kind, header, notes: [row]}], in order of a kind's first appearance.
// ⚠️ A KIND IS ONE BLOCK EVEN WHEN ITS ROWS ARE NOT ADJACENT. beans writes Note, Note, Tip and reads
// as two blocks; a recipe that alternates would otherwise print the same header twice.
export function noteBlocks(rows, table) {
  const headers = new Map(table.map((k) => [k.kind, k.header]));
  const order = [];
  const byKind = new Map();
  for (const row of rows || []) {
    const d = decorate(row, table);
    if (!byKind.has(d.kind)) {
      byKind.set(d.kind, { kind: d.kind, header: headers.get(d.kind), notes: [] });
      order.push(d.kind);
    }
    byKind.get(d.kind).notes.push(d);
  }
  return order.map((k) => byKind.get(k)).filter((b) => b.notes.length);
}

// ⚠️ ONE DEFINITION OF "LINKED", AND EVERY CALLER ASKS IT RATHER THAN DECIDING FOR ITSELF. A note
// reaches a step by its own link (step_id, chosen in the editor) or by naming one in its words
// (a stored reference), and both are the same thing to a reader standing on that step. It is the
// rule the step note tag already follows (stepNoteIndex), stated once for the section too.
// ⚠️ IT READS THE NUMBER, NOT THE ID, WHICH IS WHAT MAKES A HEADING FALL OUT. The server resolves
// step_no to null for a link whose step has become a heading or gone, and a note the page cannot
// print a number for does not belong in a group ordered by number. Such a note keeps its stored
// link and reads in its type group, which is the rule a wait already follows: a wrong number is
// worse than no link.
// ⚠️ AND AN OWN LINK IS ASKED FIRST AND ALONE. A note carrying step_id is where its author put
// it, so a reference in its words is not consulted to overrule that, and a note whose own link
// resolves to nothing is not quietly re-filed under a step it merely mentions.
export function linkedStepNo(note) {
  if (note.step_id) return note.step_no || null;
  const ref = (note.refs || []).find((r) => r.step_no);
  return ref ? ref.step_no : null;
}

// The SAME question, answered with the step's id instead of its number. A note added beside a
// linked one has to reach the same step, and the only way to say that in a row is step_id.
// ⚠️ IT MIRRORS linkedStepNo BRANCH FOR BRANCH, deliberately: an own link is asked first and alone,
// and a link whose number does not resolve does not count. Two functions reading the same rule
// differently is how a note added under Step 4 lands under Notes instead.
export function linkedStepId(note) {
  if (note.step_id) return note.step_no ? note.step_id : null;
  const ref = (note.refs || []).find((r) => r.step_no);
  return ref ? ref.step_id : null;
}

// Note ROWS -> {steps: [row], blocks: [{kind, header, notes}]}, which is the whole Notes section in
// one answer: what belongs to a step, in step order, then everything else grouped by type.
// ⚠️ A LINKED NOTE IS IN EXACTLY ONE OF THE TWO. It used to appear under its type with a
// trailing "(step N)", and showing it in both places would say the same thing twice on one screen.
// ⚠️ ORDERED BY THE STEP NUMBER, THEN BY THE NOTE'S OWN POSITION. Two notes on one step keep the
// order the cook put them in, which a sort on the number alone does not promise.
// ⚠️ ONE FUNCTION, THREE RENDERERS: the recipe page, Edit mode's block and the tests. The
// section looked one way in reading view and another in Edit mode for exactly as long as each
// built its own arrangement.
export function noteSections(rows, table) {
  const linked = [], rest = [];
  for (const row of rows || []) {
    (linkedStepNo(row) != null ? linked : rest).push(row);
  }
  const steps = linked
    .map((row, i) => ({ row, no: linkedStepNo(row), i }))
    .sort((a, b) => (a.no - b.no) || (a.i - b.i))
    .map(({ row, no }) => ({ ...decorate(row, table), stepLinkNo: no }));
  return { steps, blocks: noteBlocks(rest, table) };
}

// The STEP NOTES group's heading. A plain string, uppercased by the same CSS rule that uppercases a
// step section heading, so it is not shouted here as well.
export const STEP_NOTES_HEADER = "Step notes";

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

export { noteParagraphs, classifyNote, normLabel, displayText, displayParts, decorate, LEAD };
