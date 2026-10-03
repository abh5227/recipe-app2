"use strict";
// Bracketed text, quieter. A DISPLAY rule: nothing stored changes, and the words inside the brackets
// are the same words. Pure, no DOM, so tests/js/brackets.test.js can state it.
//
// ⚠️ MEASURED ON LIVE BEFORE IT WAS WRITTEN (2026-10-03). 388 brackets over 317 of 2,223 step rows,
// 547 over 529 of 3,344 ingredient labels, and 31 in notes, which this rule does not touch. Of the
// step brackets 80 hold a time, a temperature or an amount, 71 hold a bare number that is NOT one
// ("photo 1", "photo 2") and 237 hold words.
//
// ⚠️ ONLY AN UNMATCHED OPEN STARTS A RANGE, AND THAT IS WHAT THE CORPUS TAUGHT. 10 step rows, 4
// ingredient labels and 3 notes are unbalanced, and the common shape is a stray CLOSE rather than a
// stray open: country-ham-croquettes writes "1) one with the flour, 2) one with the panko, 3) ...",
// raspberry-chocolate-chunk-cookies ends "288 grams)", and three notes end in the emoticon ": )".
// A close paren with no open is not a bracket, so it opens nothing and styles nothing. Reading it as
// one would have greyed most of a step on three recipes and every smiley in the notes.
//
// ⚠️ AND AN UNMATCHED OPEN STOPS AT THE END OF ITS CLAUSE. "whole mackerel (about" is the whole of
// what it reaches; a sentence that opens a bracket and never closes it must not drag the paragraphs
// after it into the quiet style. A comma does NOT end the clause, because bracketed asides are full
// of commas ("(American, Cheddar, Jack, or a combination)").

const CLAUSE_END = /[.!?;]/;

// A time, a temperature or an amount. Variant B keeps these at full strength: they are the figures a
// cook is reading FOR, so dimming them makes the one thing worth finding the hardest to find.
const NUMERAL = /[0-9¼-¾⅐-⅞]/;          // digits and vulgar fractions
const UNIT = new RegExp(
  "\\b(?:min|mins|minute|minutes|hour|hours|hr|hrs|sec|secs|second|seconds|day|days|week|weeks|" +
  "cup|cups|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|g|gram|grams|kg|" +
  "oz|ounce|ounces|lb|lbs|pound|pounds|ml|l|liter|liters|litre|litres|inch|inches|cm|mm|" +
  "degrees|degree|f|c)\\b|[°\"″]", "i");

export function holdsAFigure(inner) {
  const s = String(inner || "");
  return NUMERAL.test(s) && UNIT.test(s);
}

// text -> [{text, bracket, inner, figure}] in order, covering every character exactly once.
// `bracket` is true for the parts to style, INCLUDING the parentheses themselves: a bracket read in
// a quieter weight should have quieter brackets, or the punctuation ends up louder than the aside.
export function bracketParts(text) {
  const s = String(text == null ? "" : text);
  const parts = [];
  let plain = "";
  let i = 0;
  const flush = () => { if (plain) { parts.push({ text: plain, bracket: false }); plain = ""; } };
  while (i < s.length) {
    const ch = s[i];
    if (ch !== "(") { plain += ch; i += 1; continue; }
    const close = s.indexOf(")", i + 1);
    // ⚠️ THE NEXT OPEN DECIDES WHETHER THIS CLOSE IS OURS. "(a (b) c)" is not in the corpus and a
    //    nested pair would otherwise let the inner close end the outer bracket.
    const nextOpen = s.indexOf("(", i + 1);
    const closed = close !== -1 && (nextOpen === -1 || close < nextOpen);
    let end;
    if (closed) {
      end = close + 1;
    } else {
      // Unmatched: run to the end of the clause, never past it.
      const rest = s.slice(i + 1);
      const stop = rest.search(CLAUSE_END);
      end = stop === -1 ? s.length : i + 1 + stop;
    }
    const chunk = s.slice(i, end);
    const inner = closed ? s.slice(i + 1, close) : s.slice(i + 1, end);
    flush();
    parts.push({ text: chunk, bracket: true, inner, figure: holdsAFigure(inner), closed });
    i = end;
  }
  flush();
  return parts;
}

// The HTML. `render` turns a plain substring into safe HTML (escaping, and linkifying where the
// caller wants it), so this function never escapes anything itself and never sees markup.
//
// ⚠️ IT SPLITS THE RAW TEXT AND RENDERS EACH PIECE, rather than wrapping spans around already-built
// HTML. Running a bracket matcher over escaped, linkified output would find the parentheses inside
// an <a href> or a data attribute and cut the tag in half.
//
// variant "A": every bracket is quieter. "B": a bracket holding a time, a temperature or an amount
// stays at full strength.
export function bracketedHTML(text, render, { variant = "A" } = {}) {
  const parts = bracketParts(text);
  if (!parts.some((p) => p.bracket)) return render(String(text == null ? "" : text));
  return parts.map((p) => {
    const body = render(p.text);
    if (!p.bracket) return body;
    if (variant === "B" && p.figure) return body;
    return `<span class="brk">${body}</span>`;
  }).join("");
}
