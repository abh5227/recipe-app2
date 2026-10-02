"use strict";
// Cross-language guard: notes.py::STEP_MENTION and static/note-text.js::STEP_MENTION find the same
// "step N" mentions in the same places, over tests/fixtures/step-mention-cases.json. The Python side
// asserts the same file, so neither pattern can move without the other.
//
// ⚠️ WHY THIS IS NOT A STYLE TEST. The server stores one reference row per mention and identifies it
// by its ORDINAL in the text. The client re-scans the same words to decide which mention each
// reference belongs to. A pattern that finds one match the other does not therefore shifts every
// later reference onto the wrong words, and the page then prints the REFERENCED step's current
// number over them. Measured at HEAD with the obvious spelling /\bsteps?\s+(\d+)\b/gi: 5 of the 38
// cases disagreed, because Python's \b, \s and \d are Unicode-aware on a str and JavaScript's are
// ASCII-only. "éstep 3" matched in the browser and not on the server; "step 3٠" read as step 3 in
// the browser and step 30 on the server.
//
// Same arrangement as the seven other mirrors (factor-sync, fraction-sync, timefmt-sync,
// unit-abbrev-sync, step-ping-sync, save-payload-sync, note-kinds-sync).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { STEP_MENTION, noteTextHTML, stepNoteIndex } from "../../static/note-text.js";

const FIX = JSON.parse(readFileSync(new URL("../fixtures/step-mention-cases.json", import.meta.url)));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ⚠️ THE WORDS AND THE OFFSET, WHICH IS THE WHOLE CONTRACT. What has to agree is WHICH mentions
// exist and WHERE, because that is what decides each reference's ordinal. The NUMBER is the
// server's business: it resolves the author's figure against the author's list, and this file never
// reads the capture group (the figure on screen comes from the referenced step's current position).
// They genuinely differ on one shape and it does not matter: Python's int() accepts Unicode digits,
// so int("3٠") is 30, while Number("3٠") is NaN. The number is compared below wherever it is an
// ordinary numeral, which is every case a recipe has ever contained.
function found(text) {
  STEP_MENTION.lastIndex = 0;
  const out = [];
  for (let m = STEP_MENTION.exec(text); m; m = STEP_MENTION.exec(text)) {
    out.push({ match_text: m[0], start: m.index, digits: m[1] });
  }
  return out;
}

test("the fixture still carries the real corpus cases and the adversarial set", () => {
  assert.ok(FIX.cases.length >= 38, `only ${FIX.cases.length} cases`);
  const texts = FIX.cases.map((c) => c.text);
  assert.ok(texts.some((t) => t.includes("grated cheddar")), "the parathas case is gone");
  assert.ok(texts.some((t) => t.includes("SAME DAY VERSION")), "the bagel case is gone");
  for (const hard of ["éstep 3", "step 3٠", "step 3½", "step\u00853"]) {
    assert.ok(texts.includes(hard), `the fixture no longer covers ${JSON.stringify(hard)}`);
  }
});

test("the client pattern finds exactly what notes.scan_step_mentions found", () => {
  for (const c of FIX.cases) {
    const got = found(c.text);
    assert.deepEqual(got.map((m) => ({ match_text: m.match_text, start: m.start })),
      c.mentions.map((m) => ({ match_text: m.match_text, start: m.start })),
      `the two patterns disagree on ${JSON.stringify(c.text)}`);
    got.forEach((m, i) => {
      if (/^[0-9]+$/.test(m.digits)) {
        assert.equal(Number(m.digits), c.mentions[i].number,
          `the two read a different number out of ${JSON.stringify(c.text)}`);
      }
    });
  }
});

test("a sparse reference set links the mention it names, not the first one", () => {
  // ⚠️ THE SHAPE A RECORDED DECISION PRODUCES. apply_note_decisions writes one reference row at the
  //    ref_index it was recorded for, and a decision file's flagged_references list exists to leave
  //    a mention deliberately unwritten. Paired by array position, "Skip step 3" printed as
  //    "Skip step 9".
  const html = noteTextHTML(
    { text: "Skip step 3 if you like, then proceed with step 9.",
      refs: [{ ref_index: 1, match_text: "step 9", step_no: 9 }] }, esc);
  assert.ok(html.startsWith("Skip step 3 if you like"), `the first mention was rewritten: ${html}`);
  assert.ok(html.includes('data-note-step="9">step 9</a>'), `the second was not linked: ${html}`);
});

test("a reference whose step became a heading renders as plain words", () => {
  const html = noteTextHTML(
    { text: "See step 4.", refs: [{ ref_index: 0, match_text: "step 4", step_no: null }] }, esc);
  assert.equal(html, "See step 4.");
});

test("the number on screen is the step's current one, not the words the author wrote", () => {
  const html = noteTextHTML(
    { text: "proceed with step 9.", refs: [{ ref_index: 0, match_text: "step 9", step_no: 8 }] },
    esc);
  assert.equal(html, 'proceed with <a class="note-stepref" href="#" data-note-step="8">step 8</a>.');
});

test("a stripped label does not shift the ordinals", () => {
  // The display text is the stored text with a known label taken off the front. The server counted
  // the mentions over the WHOLE stored text, so a mention inside the label has to be accounted for.
  const html = noteTextHTML(
    { text: "Step 2: then do step 7.", display: "then do step 7.",
      refs: [{ ref_index: 1, match_text: "step 7", step_no: 7 }] }, esc);
  assert.ok(html.includes('data-note-step="7">step 7</a>'), html);
});

test("a note with no references is escaped and otherwise untouched", () => {
  assert.equal(noteTextHTML({ text: "Use <b>good</b> butter & salt." }, esc),
               "Use &lt;b&gt;good&lt;/b&gt; butter &amp; salt.");
});

// ---- the marker works both ways (Andy's recheck) -----------------------------------------------
// ⚠️ ANDY SAW NO ⓘ ON THE BAGEL, AND HALF OF THAT WAS THIS. A note is connected to a step by an
// attached link OR by a "step N" written in its own words, and only the attached link produced a
// marker. The bagel's "proceed with step 9" note therefore printed a link in the Notes block and
// left step 8 with nothing on it, which is the one place a reader standing on that step would look.
const TABLE = [{ kind: "notes", header: "Notes", labels: ["Note"] },
               { kind: "tips", header: "Tips", labels: ["Tip"] }];

test("a note attached to a step shows on that step", () => {
  const by = stepNoteIndex([{ id: 1, text: "Use fresh yeast.", step_id: 10, refs: [] }], TABLE);
  assert.deepEqual([...by.keys()], [10]);
  assert.equal(by.get(10).length, 1);
});

test("a note that only NAMES a step in its words shows on that step too", () => {
  const by = stepNoteIndex(
    [{ id: 2, text: "Then proceed with step 9.", step_id: null,
       refs: [{ ref_index: 0, match_text: "step 9", step_id: 42, step_no: 8 }] }], TABLE);
  assert.deepEqual([...by.keys()], [42], "a step reference produced no marker");
  assert.equal(by.get(42)[0].id, 2);
});

test("a note connected both ways appears once on that step", () => {
  const by = stepNoteIndex(
    [{ id: 3, text: "See step 2.", step_id: 7,
       refs: [{ ref_index: 0, match_text: "step 2", step_id: 7, step_no: 2 }] }], TABLE);
  assert.equal(by.get(7).length, 1, "the same note was counted twice on one step");
});

test("one note can show on two different steps", () => {
  const by = stepNoteIndex(
    [{ id: 4, text: "Do this at step 5.", step_id: 11,
       refs: [{ ref_index: 0, match_text: "step 5", step_id: 22, step_no: 5 }] }], TABLE);
  assert.deepEqual([...by.keys()].sort((a, b) => a - b), [11, 22]);
});

test("a reference whose step is gone makes no marker", () => {
  const by = stepNoteIndex(
    [{ id: 5, text: "See step 4.", step_id: null,
       refs: [{ ref_index: 0, match_text: "step 4", step_id: null, step_no: null }] }], TABLE);
  assert.equal(by.size, 0);
});

test("two notes on one step share one entry, and the popover shows both", () => {
  const by = stepNoteIndex([{ id: 6, text: "First.", step_id: 9, refs: [] },
                            { id: 7, text: "Second.", step_id: 9, refs: [] }], TABLE);
  assert.equal(by.get(9).length, 2);
});

test("the popover text has its label stripped, like the Notes block", () => {
  const by = stepNoteIndex([{ id: 8, kind: "tips", text: "Tip: chill it first.", step_id: 3,
                             refs: [] }], TABLE);
  assert.equal(by.get(3)[0].display, "chill it first.");
});
