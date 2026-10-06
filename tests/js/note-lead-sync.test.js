// The pattern that decides what a note's LEADING LABEL is, held to one answer in two languages.
//
// ⚠️ note-kinds-sync.test.js CANNOT CATCH THIS CLASS, which is why this file exists beside it. That
// test compares the KIND each side returns, and a label the table does not list answers "no kind"
// on both sides whether the pattern matched it or not. So the whole accented, Greek and Cyrillic
// question was invisible to it: both halves read ASCII only, "Café: use a dark roast" matched
// nothing in either language, and every test passed.
//
// The fixture records the label and the body Python's _NOTE_LEAD produces for each case, or null
// where it must not match. Regenerate it with scripts/gen_note_lead_cases.py.
import { test } from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";
import { LEAD } from "../../static/note-blocks.js";

const CASES = JSON.parse(readFileSync(new URL("../fixtures/note-lead-cases.json", import.meta.url))).cases;

test("LEAD reads the same label and body as import_cleanup._NOTE_LEAD on every case", () => {
  const wrong = [];
  for (const c of CASES) {
    const m = LEAD.exec(c.text);
    const label = m ? m[1] : null;
    const body = m ? m[2] : null;
    if (label !== c.label || body !== c.body) {
      wrong.push({ text: c.text.slice(0, 48), want: c.label, got: label });
    }
  }
  assert.deepEqual(wrong, [], `${wrong.length} of ${CASES.length} disagree`);
});

test("the fixture still carries the characters the ASCII class could not read", () => {
  // A fixture regenerated from the corpus alone would quietly drop these: no note in the 177
  // carries an accented, Greek or Cyrillic label, which is exactly why the gap survived.
  for (const label of ["Café", "Crème fraîche", "Jalapeño", "Ρίγανη", "Борщ"]) {
    assert.ok(CASES.some((c) => c.label === label), `no case produces the label ${label}`);
  }
  // and the shapes that must stay refused
  assert.ok(CASES.some((c) => c.label === null && /^500g/.test(c.text)), "no refused digit case");
  assert.ok(CASES.some((c) => c.label === null && /^_private/.test(c.text)), "no refused _ case");
});
