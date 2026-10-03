"use strict";
// Bracketed asides, quieter. A DISPLAY rule, so every case here is about what the page shows and
// none of them is about stored text.
//
// ⚠️ THE CASES ARE THE CORPUS'S OWN SHAPES, measured on live 2026-10-03: 388 brackets over 317 of
// 2,223 step rows, 547 over 529 of 3,344 ingredient labels, and 10 step rows plus 4 ingredient
// labels plus 3 notes where the parentheses do not balance. The unbalanced ones are what drove the
// rule, and the common shape there is a stray CLOSE, not a stray open.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bracketParts, bracketedHTML, holdsAFigure } from "../../static/brackets.js";

const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const shape = (t) => bracketParts(t).map((p) => (p.bracket ? `[${p.text}]` : p.text)).join("|");

test("a closed bracket is the part that steps back, parentheses included", () => {
  assert.equal(shape("Use a pan (or cast iron pan) over heat"),
               "Use a pan |[(or cast iron pan)]| over heat");
});

test("two brackets in one step are two parts", () => {
  assert.equal(shape("Beat the butter (softened) and the sugar (caster)"),
               "Beat the butter |[(softened)]| and the sugar |[(caster)]");
});

test("every character is covered exactly once, whatever the text", () => {
  for (const t of ["plain words", "(all of it)", "a (b) c (d)", "((", "))", "", "a(b", ")a("]) {
    assert.equal(bracketParts(t).map((p) => p.text).join(""), t, `lost or duplicated text in ${t}`);
  }
});

// --- the unbalanced cases, which is where the rule earns its keep -------------------------------

test("a numbered list written with close parens styles nothing", () => {
  // country-ham-croquettes-with-parsley-salad, verbatim in shape
  const t = "Set up three bowls: 1) one with the flour, 2) one with the panko, and 3) one with the egg";
  assert.equal(shape(t), t, "a close paren with no open is not a bracket");
});

test("an emoticon in a note styles nothing", () => {
  // acqua-pazza, key-lime-pie and pumpkin-scones all end a note this way
  for (const t of ["Made for Marshall and Maeve : )", "Made for Sophia and Vedant's coffee party :)"]) {
    assert.equal(shape(t), t);
  }
});

test("a stray close paren at the end of an ingredient line styles nothing", () => {
  // raspberry-chocolate-chunk-cookies
  const t = "2 1/4 cups spooned and leveled all-purpose flour 288 grams)";
  assert.equal(shape(t), t);
});

test("an unclosed bracket stops at the end of its clause, never the rest of the step", () => {
  const t = "Combine the oil (neutral coconut oil, avocado oil. Then whisk the eggs.";
  assert.equal(shape(t),
    "Combine the oil |[(neutral coconut oil, avocado oil]|. Then whisk the eggs.");
});

test("a comma does NOT end the clause, because asides are full of commas", () => {
  const parts = bracketParts("Add the cheese (American, Cheddar, Jack, or a combination)");
  assert.equal(parts.filter((p) => p.bracket).length, 1);
  assert.match(parts.find((p) => p.bracket).inner, /^American, Cheddar, Jack, or a combination$/);
});

test("an unclosed bracket at the very end reaches only what is there", () => {
  // tseke-com-peix-frito...
  assert.equal(shape("whole mackerel (about"), "whole mackerel |[(about]");
});

test("each of ! ? ; and . closes an unclosed bracket", () => {
  for (const mark of [".", "!", "?", ";"]) {
    assert.equal(shape(`Stir it (gently${mark} Then wait`), `Stir it |[(gently]|${mark} Then wait`);
  }
});

test("a nested pair is ONE bracket, read to the end of the clause", () => {
  // Not in the corpus (0 of the 388 step brackets nest). Stated so introducing one is a decision
  // rather than a surprise. The inner close is not treated as the outer one's, so the whole aside
  // steps back together instead of half of it going quiet and "if you can" staying loud.
  const parts = bracketParts("Chill it (overnight (or longer) if you can)");
  assert.equal(parts.filter((p) => p.bracket).length, 1);
  assert.equal(parts.find((p) => p.bracket).text, "(overnight (or longer) if you can)");
  assert.equal(parts.map((x) => x.text).join(""), "Chill it (overnight (or longer) if you can)");
});

// --- variant B: a figure keeps its weight -------------------------------------------------------

test("a time, a temperature or an amount is a figure", () => {
  for (const s of ["20 minutes", "about 1 - 1 1/2 minutes each side", "350 degrees",
                   "180°C", "150 grams", "15-ounce can", "9\"", "½ inch slices",
                   "drained for 20 minutes"]) {
    assert.equal(holdsAFigure(s), true, `${s} should read as a figure`);
  }
});

test("words and a bare number without a unit are not figures", () => {
  // The corpus writes 71 bracketed bare numbers in steps and none of them is an amount.
  for (const s of ["optional", "Greek or Turkish", "like Vidalia", "or cast iron pan",
                   "photo 1", "photo 2", "American, Cheddar, Jack"]) {
    assert.equal(holdsAFigure(s), false, `${s} should NOT read as a figure`);
  }
});

test("variant A dims every bracket and variant B spares the figures", () => {
  const t = "Bake (20 minutes) in a pan (or cast iron)";
  const a = bracketedHTML(t, esc, { variant: "A" });
  const b = bracketedHTML(t, esc, { variant: "B" });
  assert.equal((a.match(/class="brk"/g) || []).length, 2);
  assert.equal((b.match(/class="brk"/g) || []).length, 1);
  assert.match(b, /Bake \(20 minutes\)/, "the figure keeps its weight in B");
  assert.match(b, /<span class="brk">\(or cast iron\)<\/span>/);
});

// --- it never builds markup itself --------------------------------------------------------------

test("the caller escapes, and markup in a bracket cannot escape the span", () => {
  const html = bracketedHTML('Mix (<script>alert(1)</script>)', esc, {});
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("a text with no bracket is handed to render untouched, in one piece", () => {
  const calls = [];
  const spy = (s) => { calls.push(s); return s; };
  bracketedHTML("no brackets at all", spy, {});
  assert.deepEqual(calls, ["no brackets at all"], "an unbracketed line must not be split");
});

test("the parentheses themselves are inside the quiet span", () => {
  // A bracket read in a quieter weight with louder punctuation reads as a rendering fault.
  const html = bracketedHTML("a (b) c", esc, {});
  assert.match(html, /<span class="brk">\(b\)<\/span>/);
});

test("a link's own markup is never cut in half, because the split is on the raw text", () => {
  // The caller's render is what produces the <button>; the splitter only ever sees plain substrings.
  const linkify = (t) => esc(t).replace(/\[\[([^\]]+)\]\]/g,
    (_, k) => `<button class="ingredient" data-item="${esc(k)}">${esc(k)}</button>`);
  const html = bracketedHTML("Wilt the [[spinach]] (about 2 minutes)", linkify, { variant: "A" });
  assert.match(html, /<button class="ingredient" data-item="spinach">spinach<\/button>/);
  assert.match(html, /<span class="brk">\(about 2 minutes\)<\/span>/);
});
