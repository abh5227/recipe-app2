"use strict";
// annotation-amount.js — the amount an ANNOTATED ledger row shows, at the same factor as the rows
// around it.
//
// ⚠️ THIS EXISTS BECAUSE THE ANNOTATION RENDER HARDCODED A FACTOR OF 1. faca870 reached for
// amountText to get the ledger's abbreviation ("½ teaspoon" -> "½ tsp") and passed 1 for "do not
// scale", so an edited row sat frozen at 1x while every unedited row beside it doubled. Measured
// before the fix: 81 amount edits over 68 recipes, each freezing TWO numbers (the struck original
// and the ink correction), plus 13 struck removed amounts over 11 recipes.
//
// Pure (scaler.js only) so the numbers are testable with no DOM. It returns TEXT, never markup:
// app.js owns the escaping and the spans.

import { amountText, weightText, scaleQty, abbrevUnits, fixPlurals, toUnicodeFractions } from "./scaler.js";

/** The two halves of an edited amount cell, plus the gram estimate the row is entitled to.
 *
 * ⚠️ THE WEIGHT IS THE CURRENT AMOUNT'S, not the struck original's. The sub-line answers "how much
 * do I weigh out", which is the corrected value. The original is there to show what it used to say.
 * Measured: of the 81 edited rows only 9 carry a density at all and none clears the 2-tbsp spoon
 * threshold at 1x, so this is one row at 2x today. It is here so an edited row stops LOSING a
 * column the row beside it keeps, not for the rows it lights up now. */
export function editedAmountParts(from, to, gramsPerMl, factor) {
  return {
    was: amountText(from, factor),
    fix: amountText(to, factor),
    weight: weightText(to, gramsPerMl, factor),
  };
}

/** The struck amount of a REMOVED row. The entry carries the raw combined "qty label" line and the
 * name separately, so the amount is whatever precedes the name. Returns "" when the line is all
 * name (a removed row with no amount reserves no figure). */
export function removedAmountText(text, label, factor) {
  const t = String(text || "");
  const l = String(label || "");
  const qty = (l && t.endsWith(l)) ? t.slice(0, t.length - l.length).trim() : "";
  return qty ? amountText(qty, factor) : "";
}

/** A step's tagged spans with the scalable ones scaled, in render order.
 *
 * ⚠️ A STEP IS NEVER SCALED BY RUNNING scaleQty OVER ITS WHOLE TEXT. The server's tagger decides
 * which numbers are quantities, and everything it leaves `plain` is left alone. Run over the raw
 * prose instead, "simmer for 4-6 minutes" becomes "8-12 minutes" at 2x, which is the corpus's one
 * reworded step and the reason that shortcut is not taken here. */
export function stepSpanTexts(spans, factor) {
  return (spans || []).map((s) => (s.t === "scale"
    // ⚠️ fixPlurals HERE TOO, OR ONE PAGE PRINTS TWO SPELLINGS. The ledger agreed its unit with
    //    the figure and the method text did not, so at 2x an ingredient read "2 cups" and the step
    //    that names it read "2 cup". Same order as amountText: scale, agree, abbreviate, glyphs.
    ? { t: "scale", text: toUnicodeFractions(abbrevUnits(fixPlurals(scaleQty(String(s.text || ""), factor)))) }
    : { t: "plain", text: String(s.text || "") }));
}

/** A substitution note's tagged spans with the scalable ones scaled, in render order.
 *
 * ⚠️ EACH AMOUNT GOES THROUGH amountText, THE LEDGER'S OWN PATH, so a note scales "exactly like the
 * line's own amounts" (Andy, decisions-3): the same count rounding, the same never-scale rule for a
 * size or a per-person figure, the same plural agreement. The one difference is { words: true },
 * which keeps "tablespoons" as the author wrote it, because a note is prose and Andy's expected 2x
 * reads "or 4 tablespoons Korean doenjang + 2 tablespoons water".
 * Which numbers are amounts is the SERVER's call (stepscale.note_spans), as it is for a step. */
export function noteSpanTexts(spans, factor) {
  return (spans || []).map((s) => (s.t === "scale"
    ? { t: "scale", text: amountText(String(s.text || ""), factor, { words: true }) }
    : { t: "plain", text: String(s.text || "") }));
}
