"use strict";
// The capital under a title, which is the stripped-label rule and not a second one.
//
// ⚠️ THE FOUR NOTES BELOW ARE THE REAL ROWS, copied out of the rehearsal copy after the titles pass
// ran. The pass lifts a label into the `title` column and takes it off the front of the text, so
// each of these now stores a sentence that starts in the middle. 24 of the 28 titled notes already
// open with a capital and must come back byte-identical.
//
// ⚠️ ONE FUNCTION ANSWERS BOTH ARMS. note-text.js::capFirst asks "did something that used to carry
// this sentence's first letter stop being part of it?", and a stripped kind label and a lifted
// title are two ways for that to be true. A second rule here is how the step popover and the Notes
// block end up capitalizing differently.
import { test } from "node:test";
import assert from "node:assert/strict";
import { noteTextPlain, noteTextParts } from "../../static/note-text.js";

const plain = (note) => noteTextPlain(note);

// notes 39, 83, 84 and 103 as the pass leaves them
const LOWER = [
  { id: 39, title: "Mirin",
    text: "substitute Chinese cooking wine or cooking sake plus ½ tsp brown sugar.",
    want: "Substitute Chinese cooking wine or cooking sake plus ½ tsp brown sugar." },
  { id: 83, title: "Cannellini",
    text: "also known as White Italian Beans, white kidney beans.",
    want: "Also known as White Italian Beans, white kidney beans." },
  { id: 84, title: "Borlotti",
    text: "also known as Cranberry bean, Roman bean",
    want: "Also known as Cranberry bean, Roman bean" },
  { id: 103, title: "Tomato Bouillon",
    text: "granules or cubes, found in the Mexican aisle or online.",
    want: "Granules or cubes, found in the Mexican aisle or online." },
];

for (const n of LOWER) {
  test(`note ${n.id} shows a capital under its title`, () => {
    assert.equal(plain({ ...n, refs: [] }), n.want);
  });
}

test("the stored text is not what changed", () => {
  // The transform is read-only on its input, which is what "display only" has to mean in code.
  for (const n of LOWER) {
    const row = { ...n, refs: [] };
    plain(row);
    assert.equal(row.text, n.text);
  }
});

test("a note with no title and no stripped label keeps its own opening", () => {
  assert.equal(plain({ id: 1, title: null, text: "about 200g of flour works.", refs: [] }),
    "about 200g of flour works.");
  assert.equal(plain({ id: 1, title: "   ", text: "about 200g of flour works.", refs: [] }),
    "about 200g of flour works.");
});

test("only a lowercase letter moves", () => {
  // ⚠️ A NUMBER, A BRACKET AND AN UNCASED SCRIPT ARE LEFT ALONE. \p{Ll} is the whole test, which is
  //    why this is a regex and not charAt(0).toUpperCase().
  const cases = [
    ["200g is the flour, the rest is read against it.", "200g is the flour, the rest is read against it."],
    ["(or use the dried kind).", "(or use the dried kind)."],
    ["½ tsp is plenty.", "½ tsp is plenty."],
    ["сметана on the side.", "Сметана on the side."],
    ["漢 is not a cased letter.", "漢 is not a cased letter."],
  ];
  for (const [text, want] of cases) {
    assert.equal(plain({ id: 1, title: "Note", text, refs: [] }), want, text);
  }
});

test("a title capitalizes the leading whitespace's first letter, not the whitespace", () => {
  assert.equal(plain({ id: 1, title: "Mirin", text: "  substitute the wine.", refs: [] }),
    "  Substitute the wine.");
});

test("the title itself is untouched by the rule", () => {
  // The title is stored verbatim and printed verbatim. Only the BODY is asked this question.
  const parts = noteTextParts({ id: 1, title: "mirin", text: "substitute the wine.", refs: [] });
  assert.equal(parts[0].v, "Substitute the wine.");
});

test("a stripped label still capitalizes, with no title in sight", () => {
  assert.equal(plain({ id: 1, title: null, displayStripped: true,
                       display: "increase water to 354 grams.", text: "x", refs: [] }),
    "Increase water to 354 grams.");
});
