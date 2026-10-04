"use strict";
// Pure note-text transform (no DOM, no `view`): a note's words with each stored step reference
// turned into a link. The notes sibling of note-blocks.js, and extracted for the same reason
// step-row.js was — two bugs lived in the few lines below and neither was reachable from a test
// while they sat inside app.js.
//
// `esc` is INJECTED rather than imported, exactly as note-blocks.js takes the kind table: this
// module stays dependency-free for the zero-dep JS suite, and the app keeps one escaping function
// rather than a second copy of it. displayText comes from note-blocks.js, which is dependency-free
// too, so the step popover and the Notes block strip a label by one rule and not two.
import { displayText, displayParts } from "./note-blocks.js";

// ⚠️ A MIRROR OF notes.py::STEP_MENTION, AND NOT THE OBVIOUS SPELLING OF IT. Python's \b, \s and
// \d are Unicode-aware on a str and JavaScript's are ASCII-only, so /\bsteps?\s+(\d+)\b/ and the
// Python pattern disagree on real text: "éstep 3" matched here and not there, "step 3٠" read as
// step 3 here and as step 30 there. The server decides WHICH mention each stored reference belongs
// to by its ordinal, so one side seeing a match the other does not shifts every later link onto the
// wrong words. tests/js/step-mention-sync.test.js holds the two together over a shared fixture.
const STEP_MENTION = /(?<![\p{L}\p{N}_])steps?[\s\u0085\u001c-\u001f]+(\p{Nd}+)(?![\p{L}\p{N}_])/giu;

// A note's words, with each stored step reference turned into a link that always reads the step's
// CURRENT number.
// ⚠️ THE NUMBER ON SCREEN IS NOT THE NUMBER IN THE TEXT. The author wrote "step 9" against their own
// numbering, and the steps have moved since. What is stored is the step's id, so the sentence keeps
// meaning the same step and the figure is resolved every time the page draws.
// ⚠️ A REFERENCE WHOSE STEP BECAME A HEADING, OR WENT, RENDERS AS PLAIN TEXT. step_no comes back
// null and the words stay exactly as written, which is the rule waits already follow: a wrong
// number is worse than no link.
// ⚠️ ONE SCAN, TWO RENDERERS. The page draws a reference as a link and the editor has to show the
// same words in a plain field, and writing the walk twice is how the two drift. noteTextParts is the
// walk; noteTextHTML and noteTextPlain only decide what a piece looks like.
export function noteTextParts(note) {
  const refs = note.refs || [];
  const text = String(note.display != null ? note.display : (note.text || ""));
  // ⚠️ THE DISPLAY TEXT CAN BE SHORTER THAN THE STORED TEXT, so the ordinals have to be lined up.
  //    A label the kind table knows is stripped for display, the server counted its mentions
  //    against the WHOLE stored text, and a mention inside that label would put every later
  //    reference one place out. The strip is always a prefix, so counting what it removed is
  //    enough.
  const stored = String(note.text || "");
  const cut = (note.display != null && stored && stored !== text) ? stored.indexOf(text) : 0;
  const offset = cut > 0 ? (stored.slice(0, cut).match(STEP_MENTION) || []).length : 0;
  const parts = [];
  let last = 0, i = 0;
  STEP_MENTION.lastIndex = 0;
  for (let m = STEP_MENTION.exec(text); m; m = STEP_MENTION.exec(text)) {
    // ⚠️ BY ref_index, NEVER BY POSITION IN THE ARRAY. A reference the author left flagged, or one
    //    a recorded decision wrote on its own, makes the set SPARSE: refs = [{ref_index: 1}] on a
    //    note with two mentions paired that link to mention 0 and printed "Skip step 3" as
    //    "Skip step 9". The flagged_references list in a decision file exists to produce exactly
    //    that shape.
    const ref = refs.find((r) => r.ref_index === i + offset);
    i++;
    if (m.index > last) parts.push({ t: "text", v: text.slice(last, m.index) });
    parts.push({ t: "step", v: m[0], step_no: (ref && ref.step_no) ? ref.step_no : null,
                 ref_index: i - 1 + offset });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ t: "text", v: text.slice(last) });
  return capFirst(parts, note);
}

// ⚠️ THE CAPITAL IS DISPLAY ONLY, AND ONLY AFTER A STRIPPED LABEL. "SAME DAY VERSION: increase
// water…" is a sentence whose first letter was carried by the label, so removing the label leaves
// it lowercase. A note whose label was NOT stripped is the author's own opening and is left alone.
// Nothing here is written back: the stored row keeps the author's words until the cook edits it.
function capFirst(parts, note) {
  if (!note.displayStripped || !parts.length || parts[0].t !== "text") return parts;
  const v = parts[0].v.replace(/^(\s*)(\p{Ll})/u, (_, sp, ch) => sp + ch.toUpperCase());
  return v === parts[0].v ? parts : [{ ...parts[0], v }, ...parts.slice(1)];
}

// A note's words, with each stored step reference turned into a link that always reads the step's
// CURRENT number.
// ⚠️ THE NUMBER ON SCREEN IS NOT THE NUMBER IN THE TEXT. The author wrote "step 9" against their own
// numbering, and the steps have moved since. What is stored is the step's id, so the sentence keeps
// meaning the same step and the figure is resolved every time the page draws.
// ⚠️ A REFERENCE WHOSE STEP BECAME A HEADING, OR WENT, RENDERS AS PLAIN TEXT. step_no comes back
// null and the words stay exactly as written, which is the rule waits already follow: a wrong
// number is worse than no link.
export function noteTextHTML(note, esc) {
  return noteTextParts(note).map((p) => (p.t === "step" && p.step_no)
    ? `<a class="note-stepref" href="#" data-note-step="${p.step_no}">step ${p.step_no}</a>`
    : esc(p.v)).join("");
}

// The same words as a plain string, which is what the editor is seeded with: the label gone, the
// first letter capitalized, and every resolved reference reading the number the page prints.
// ⚠️ THIS IS WHAT A SAVE WRITES. "What you see is what is stored" only holds if the thing the cook
// was shown is the thing the field contained.
export function noteTextPlain(note) {
  return noteTextParts(note).map((p) => (p.t === "step" && p.step_no)
    ? `step ${p.step_no}` : p.v).join("");
}

export { STEP_MENTION };


// ⚠️ A NOTE IS CONNECTED TO A STEP BY EITHER ROUTE, AND BOTH SHOW THE MARKER. An attached link
// (step_id, chosen in the editor) and a "step N" written in the note's own words are two ways of
// saying the same thing, and a reader on the step wants the note either way. This counted only the
// attached link, so the bagel's "proceed with step 9" note showed on the page as a link in the Notes
// block and left step 8 with no marker at all.
// ⚠️ AND A NOTE CONNECTED BOTH WAYS APPEARS ONCE. Two markers on one sentence reads as two
// different kinds of thing, which is the same reason two notes on one step share a marker.
export function stepNoteIndex(rows, table) {
  const by = new Map();
  const add = (sid, n) => {
    if (!sid) return;
    if (!by.has(sid)) by.set(sid, []);
    const seen = by.get(sid);
    // ⚠️ KEYED ON THE ID WHERE THERE IS ONE, AND ON THE WORDS WHERE THERE IS NOT. The id test alone
    //    let a row with a null id through twice, so a note with two references to the same step was
    //    listed twice in that step's popover. Server rows always carry an id, so this is the
    //    defensive direction rather than a repair.
    const key = n.id != null ? `#${n.id}` : `t:${n.text || ""}`;
    if (seen.some((x) => (x.id != null ? `#${x.id}` : `t:${x.text || ""}`) === key)) return;
    // ⚠️ THE SAME DISPLAY TEXT THE NOTES SECTION SHOWS. These are the raw rows, so without this the
    //    popover printed the label ("Variation: ...") that the section strips, and one note read
    //    two different ways on one page.
    const d = displayParts(n, table);
    seen.push({ ...n, display: d.text, displayStripped: d.stripped });
  };
  for (const n of rows || []) {
    add(n.step_id, n);
    for (const r of (n.refs || [])) add(r.step_id, n);
  }
  return by;
}
