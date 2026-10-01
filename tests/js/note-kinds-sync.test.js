// The note-kind classifier exists twice, once in Python and once here, and this is what holds them
// together.
//
// ⚠️ THE TABLE IS SHARED AND THE REGEXES WERE NOT. static/note-kinds.json is read by both sides, and
// tests already assert that. The LEAD pattern that reads a label off the front of a paragraph was
// hand-duplicated, with no test, in a project that keeps six other cross-language mirrors in step
// exactly this way (factor-sync, fraction-sync, timefmt-sync, unit-abbrev-sync, step-ping-sync,
// save-payload-sync). The two had already drifted from _NOTE_STEP on the separator set: a "Tip - ..."
// step moved into the notes with its dash and neither side could read the label back, so two real
// corpus paragraphs printed under the wrong header.
//
// tests/fixtures/note-kind-cases.json carries every label in the table in five separator forms and
// two casings, the shapes that must NOT classify, and every real notes paragraph in the corpus. The
// Python side asserts the same file.
import { test } from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";
import { classifyNote } from "../../static/note-blocks.js";

const CASES = JSON.parse(readFileSync(new URL("../fixtures/note-kind-cases.json", import.meta.url))).cases;
const TABLE = JSON.parse(readFileSync(new URL("../../static/note-kinds.json", import.meta.url))).kinds;

test("the fixture is the real table, not a stale copy of it", () => {
  assert.ok(CASES.length > 400, `only ${CASES.length} cases`);
  // every label in the live table appears in the fixture, so adding a kind without regenerating fails
  for (const k of TABLE) {
    for (const lab of k.labels) {
      assert.ok(CASES.some((c) => c.text.toLowerCase().startsWith(lab.toLowerCase())),
        `no case covers the label ${lab!= null ? lab : ""}`);
    }
  }
});

test("classifyNote agrees with import_cleanup.note_kind on every case", () => {
  // classifyNote ALWAYS returns a kind, falling back to table[0] for an unlabelled paragraph, and
  // the signal that a label actually matched is that the text came back STRIPPED. note_kind returns
  // null for the same case, so that is the mapping between the two.
  const wrong = [];
  for (const c of CASES) {
    const got = classifyNote(c.text, TABLE);
    const js = got.text === c.text ? null : got.kind;
    if (js !== (c.kind || null)) wrong.push({ text: c.text.slice(0, 60), py: c.kind, js });
  }
  assert.deepEqual(wrong, [], `${wrong.length} of ${CASES.length} disagree`);
});
