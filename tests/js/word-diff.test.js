"use strict";
// Pins the word-level annotation diff. The bug this guards: whitespace tokens bind trailing punctuation
// to the preceding word, so appending a tail to an ingredient name struck the noun and re-inked it
// verbatim — "cauliflower" -> "cauliflower, cut into small florets" rendered as
// ~~cauliflower~~ [cauliflower, cut into small florets], which tells the reader nothing about what
// changed. Observed on all 18 note->name moves across aloo-gobhi / bulgogi-bowls / gai-yang / mussakhan.
// The second half of the guard is the reverse failure: a fix that matches on "word minus its trailing
// punctuation" makes punctuation-ONLY edits vanish entirely, so those cases are pinned too.
// Pure module, so this runs under bare `node --test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { wordDiffParts } from "../../static/word-diff.js";

// Render parts the way app.js does (concatenate, each part preceded by its own gap), with the two mark
// types made visible: ~~struck original~~ and [inked correction].
function vis(fromStr, toStr) {
  return wordDiffParts(fromStr, toStr).map((p) => {
    if (p.t === "del") return `${p.gap}~~${p.text}~~`;
    if (p.t === "ins") return `${p.gap}[${p.text}]`;
    return p.gap + p.text;
  }).join("");
}

// ---- the SPACING contract ------------------------------------------------------------------------
// `gap` is the only signal a caller has that a run binds tight to the text before it, and app.js turns
// gap=="" into the `is-tight` class that zeroes .iname .fix's 5px margin-left. The 11 tests below pin the
// rendered STRING, which collapses gap into the concatenation and so passed while the page still showed
// "garlic , finely grated" — the space was the CSS margin, not the markup. These assert the field itself.

test("a run opening with punctuation reports gap == '' (this is what kills the 5px ink margin)", () => {
  assert.deepEqual(wordDiffParts("garlic", "garlic, finely grated"),
                   [{ t: "eq", text: "garlic", gap: "" },
                    { t: "ins", text: ", finely grated", gap: "" }]);
  assert.deepEqual(wordDiffParts("extra-virgin olive oil, plus more to serve", "extra-virgin olive oil"),
                   [{ t: "eq", text: "extra-virgin olive oil", gap: "" },
                    { t: "del", text: ", plus more to serve", gap: "" }]);
});

test("a run opening with a WORD still reports gap == ' ' (the ink nudge must survive)", () => {
  assert.deepEqual(wordDiffParts("1 cup sugar", "1 cup honey"),
                   [{ t: "eq", text: "1 cup", gap: "" },
                    { t: "del", text: "sugar", gap: " " },
                    { t: "ins", text: "honey", gap: " " }]);
});

// Mirrors app.js's wordDiffHTML markup rule so the class itself is pinned — app.js can't be imported
// (it pulls a .jpg through Vite), so this is a copy, deliberately: if the gap semantics above change,
// both this and the real renderer change together and the assertions below catch it.
const markup = (f, t) => wordDiffParts(f, t).map((p, i) => {
  const tight = i > 0 && !p.gap;
  if (p.t === "del") return `${p.gap}<span class="was">${p.text}</span>`;
  if (p.t === "ins") return `${p.gap}<span class="fix${tight ? " is-tight" : ""}">${p.text}</span>`;
  return p.gap + p.text;
}).join("");

test("is-tight is set exactly when the ink run needs to bind to the preceding word", () => {
  assert.equal(markup("garlic", "garlic, finely grated"),
               'garlic<span class="fix is-tight">, finely grated</span>');
  assert.equal(markup("Asian pear", "Asian pear, finely grated"),
               'Asian pear<span class="fix is-tight">, finely grated</span>');
  // a word-initial ink run keeps the plain class, and therefore the 5px nudge
  assert.equal(markup("1 cup sugar", "1 cup honey"),
               '1 cup <span class="was">sugar</span> <span class="fix">honey</span>');
});

test("a NAME-INITIAL ink run keeps its 5px nudge — gap=='' there means 'nothing precedes'", () => {
  // The first part's gap is always "", so keying is-tight on gap alone stripped the nudge here.
  assert.equal(markup("olive oil", "extra-virgin olive oil"),
               '<span class="fix">extra-virgin</span> olive oil');
  assert.equal(markup("sugar", "eggs"),
               '<span class="was">sugar</span> <span class="fix">eggs</span>');
});

// ---- the shape that prompted this ---------------------------------------------------------------

test("appending a tail marks ONLY the tail — the noun is not struck and rewritten", () => {
  assert.equal(vis("cauliflower", "cauliflower, cut into small florets"),
               "cauliflower[, cut into small florets]");
  assert.equal(vis("red onions", "red onions, finely sliced into half-moons"),
               "red onions[, finely sliced into half-moons]");
  assert.equal(vis("palm sugar", "palm sugar, finely chopped"),
               "palm sugar[, finely chopped]");
});

test("removing a tail strikes ONLY the tail", () => {
  assert.equal(vis("extra-virgin olive oil, plus more to serve", "extra-virgin olive oil"),
               "extra-virgin olive oil~~, plus more to serve~~");
});

test("a mid-string reword marks only the changed words", () => {
  assert.equal(vis("Slash the flesh of each piece of chicken diagonally.",
                   "Slash the flesh of each thigh diagonally."),
               "Slash the flesh of each ~~piece of chicken~~ [thigh] diagonally.");
});

// ---- the reverse failure: a punctuation-only edit must NOT become invisible ------------------------

test("punctuation-only edits still produce a mark", () => {
  assert.equal(vis("salt, pepper", "salt; pepper"), "salt~~,~~[;] pepper");
  assert.equal(vis("Preheat the oven", "Preheat the oven."), "Preheat the oven[.]");
  assert.equal(vis("flour, sifted", "flour sifted"), "flour~~,~~ sifted");
});

test("a case-only edit still produces a mark (the match is exact, not normalized)", () => {
  assert.equal(vis("Sugar", "sugar"), "~~Sugar~~ [sugar]");
  assert.equal(vis("add the Salt now", "add the salt now"), "add the ~~Salt~~ [salt] now");
});

// ---- unchanged behaviour ---------------------------------------------------------------------------

test("plain word edits are unaffected by tokenising punctuation", () => {
  assert.equal(vis("1 cup sugar", "1 cup honey"), "1 cup ~~sugar~~ [honey]");
  assert.equal(vis("olive oil", "extra-virgin olive oil"), "[extra-virgin] olive oil");
  assert.equal(vis("extra-virgin olive oil", "olive oil"), "~~extra-virgin~~ olive oil");
});

test("hyphens, decimals and fractions are never split", () => {
  assert.equal(vis("28.35 g extra-virgin oil", "28.35 g extra-virgin olive oil"),
               "28.35 g extra-virgin [olive] oil");
  assert.equal(vis("1 1/2 cups flour", "1 1/2 cups bread flour"), "1 1/2 cups [bread] flour");
});

test("parentheses attach without stray spaces", () => {
  assert.equal(vis("soy sauce", "soy sauce (light)"), "soy sauce [(light)]");
  assert.equal(vis("soy sauce (light)", "soy sauce"), "soy sauce ~~(light)~~");
  assert.equal(vis("soy sauce (light)", "soy sauce (dark)"), "soy sauce (~~light~~ [dark])");
});

// ---- the whole-field fallback ----------------------------------------------------------------------

test("no shared word -> one whole-field strike + one whole-field ink", () => {
  assert.deepEqual(wordDiffParts("sugar", "eggs"),
                   [{ t: "del", text: "sugar", gap: "" }, { t: "ins", text: "eggs", gap: " " }]);
  assert.equal(vis("1 cup sugar", "3 large eggs"), "~~1 cup sugar~~ [3 large eggs]");
});

test("a SHARED COMMA does not defeat the fallback — it tests for a shared WORD", () => {
  // Both sides tokenise to a "," but have no word in common; without the PUNCT_ONLY guard this
  // fragmented into ~~sugar~~ [eggs], ~~divided~~ [beaten].
  assert.equal(vis("sugar, divided", "eggs, beaten"), "~~sugar, divided~~ [eggs, beaten]");
  assert.equal(vis("sugar (white)", "eggs (large)"), "~~sugar (white)~~ [eggs (large)]");
});

test("empty sides fall back rather than throwing", () => {
  assert.equal(vis("", "cauliflower, chopped"), "~~~~ [cauliflower, chopped]");
  assert.equal(vis("cauliflower, chopped", ""), "~~cauliflower, chopped~~ []");
  assert.equal(vis(null, undefined), "~~~~ []");
});
