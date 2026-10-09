"use strict";
// ledger-row.js — the HTML of one ingredient row's amount column and its note, at a factor.
//
// ⚠️ THIS IS WHAT THE PAGE INSERTS, AND IT IS IN A MODULE SO A TEST CAN READ IT. Round B revision 1
//    said the per-serving rule's callers were fixed and the tests passed, and Andy's click-through
//    still showed "about ½ cup per person" doubling at 2x. The tests had checked amountText, which
//    is one step short of what renders. tests/js/ledger-render.test.js renders these functions over
//    real stored rows at ½x, 1x and 2x and reads the text a cook would see.
//    (What Andy's page was actually running is in ledgerCellsAt's comment below.)
//
// Pure: no DOM, no `view`. app.js passes view.scale in, the way it passes it to the scaler.

import { esc } from "./esc.js";
import { amountText, weightText, secondAmountParts } from "./scaler.js";
import { noteSpanTexts, editedAmountParts } from "./annotation-amount.js";
import { lcsWalk } from "./word-diff.js";

// One ledger figure cell — the amount or the weight, mono + tabular. A leading "~" (an estimated
// weight, or a humane-rounded amount) earns the shared "approx" treatment. (inlineStyle is unused
// now that the per-person coloured overlay is gone — R6; kept as an optional arg.)
export function figCell(cls, text, inlineStyle) {
  const approx = text.charAt(0) === "~" ? " approx" : "";
  const style = inlineStyle ? ` style="${inlineStyle}"` : "";
  return `<span class="${cls}${approx}"${style}>${esc(text)}</span>`;
}

// The sub-lines under a ledger amount: the AUTHOR'S second amount where there is one, each on its
// own line, and otherwise the computed gram estimate.
//
// ⚠️ THE AUTHOR'S FIGURE BEATS THE COMPUTED ONE, AND 90 LIVE ROWS HAVE BOTH. The estimate is
//    weightText: the chart's grams-per-millilitre for this food times the authored volume, shown
//    only above 2 tablespoons and only where the chart knows the food, with a "~" saying so. It is
//    a good estimate and it is still an estimate: on those 90 rows the author weighed the
//    ingredient and wrote the figure down, so "250g" replaces "~240 g" rather than sitting beside
//    it. A row with no second amount keeps the estimate exactly as before.
//
// ⚠️ AND TWO BACKUPS GO ON TWO LINES. secondAmountParts splits the slot on " / ", which is how
//    import_cleanup stores a line that states its amount three ways. An "or" line is one of them
//    (round B revision 2): "1 lb / 4 medium / or 2 long" is three lines under "500 g".
export function amountSubLinesAt(row, factor, inlineStyle) {
  const parts = secondAmountParts(row.secondary_measure, factor);
  if (parts.length) return parts.map((t) => figCell("qty2", t, inlineStyle)).join("");
  const weight = weightText(row.qty, row.grams_per_ml, factor);
  return weight ? figCell("weight", weight, inlineStyle) : "";
}

// One ledger amount-cell for a line: the amount, with the author's second amount or the gram
// estimate stacked as a muted sub-line beneath it — nothing emitted otherwise, so rows with
// neither reserve no column and names stay aligned (Option B2).
// R2 hook: this .amount-cell (and its addressable .qty) is the reserved strike target — Round 2
// will strike the printed amount and set the edited value beside it in the hand color. No R1 treatment.
// ⚠️ ANDY'S "about ½ cup per person" DOUBLING WAS A STALE TAB, AND THE GUARD MOVED DOWN ANYWAY.
//    The :8002 log shows his browser never fetched revision 1's bundle: it kept running the one
//    a8ba985 served before the restart, and a8ba985 has no per-serving rule at all. What this
//    module's test holds is that the CURRENT render cannot do it, at any factor.
export function ledgerCellsAt(row, factor, inlineStyle) {
  return `<span class="amount-cell">` +
         figCell("qty", amountText(row.qty, factor), inlineStyle) +
         amountSubLinesAt(row, factor, inlineStyle) +
         `</span>`;
}

// The sub-lines of a row whose SECOND amount the cook edited, each original line set against each
// new one AS PRINTED at the factor. A line that prints the same before and after stays print, and
// only what changed is struck and inked, the way a name edit marks only the words it changed.
//
// ⚠️ COMPARED AS PRINTED, NOT AS STORED. The server compares the second amount as text, so a retype
//    that prints the same figure ("8 ounces" to "8 oz", "1/2 cup" to "½ cup") is an entry. The same
//    retype of the FIRST amount is not one, because that comparison canonicalizes the unit. Drawing
//    it would strike "8 oz" and ink "8 oz" beside it. Live holds 0 such entries.
// ⚠️ THE STRUCK LINE IS THE STRUCK FIRST AMOUNT, ONE SIZE DOWN. It carries .qty2 for the sub-line's
//    face and size and .was for the strike, and .was's opacity wins over .qty2's dimming, so the rule
//    through it is as strong as the one through an edited amount. The ink is never inside .qty2.
// Both sides render at the factor, for the reason editedAmountParts gives. A second amount cleared
// to nothing keeps its struck lines, and the row then gets the gram estimate an unedited row with
// no second amount gets. Returns null when nothing prints differently, which is no mark at all.
function secondLinesAt(second, row, factor, inlineStyle) {
  const was = secondAmountParts(second.from, factor);
  const now = secondAmountParts(second.to, factor);
  const walk = lcsWalk(was, now);
  if (!walk.some((x) => x.t !== "eq")) return null;
  const html = walk.map((x) => {
    if (x.t === "eq") return figCell("qty2", x.w, inlineStyle);
    if (x.t === "del") return `<span class="qty2 was">${esc(x.w)}</span>`;
    return `<span class="fix">${esc(x.w)}</span>`;
  }).join("");
  const rest = now.length ? "" : amountSubLinesAt({ ...row, secondary_measure: null }, factor, inlineStyle);
  return html + rest;
}

// One ingredient row's amount cell with the "your changes" marks its annotation slot carries
// (annotation-index.js), and whether the row is an amount edit. app.js's plainRow inserts exactly
// this, so tests/js/ledger-render.test.js reads the page's own decision rather than a copy of it.
//
// `edited` is the li's "edited" class, and it stays an AMOUNT edit only. That class stacks the first
// amount's struck figure over its ink, and on a row where only the second amount moved it would
// tighten an unedited first amount against the line below it.
// With only an amount edit, the markup is what the amount mark has always been, byte for byte.
export function amountCellAt(row, slot, factor, inlineStyle) {
  const amt = slot && slot.amount;
  const subs = slot && slot.second_amount ? secondLinesAt(slot.second_amount, row, factor, inlineStyle) : null;
  if (!amt && subs == null) return { edited: false, html: ledgerCellsAt(row, factor, inlineStyle) };
  let top;
  if (amt) {
    const p = editedAmountParts(amt.from, amt.to, row.grams_per_ml, factor);
    top = `<span class="qty"><span class="was">${esc(p.was)}</span><span class="fix">${esc(p.fix)}</span></span>`;
  } else {
    top = figCell("qty", amountText(row.qty, factor), inlineStyle);
  }
  // The author's second amount is a fact about the line, and a hand edit to the AMOUNT does not
  // change it, so without a second-amount edit the sub-line is whatever an unedited row would get.
  const lines = subs == null ? amountSubLinesAt(row, factor, inlineStyle) : subs;
  return { edited: !!amt, html: `<span class="amount-cell">${top}${lines}</span>` };
}

// A note rendered as a distinct secondary annotation on its OWN line below the ingredient (muted,
// italic, smaller — see .inote). Applies to every reading-mode line, linked or plain.
// ⚠️ A SUBSTITUTION NOTE'S AMOUNTS SCALE, ON DISPLAY ONLY (round B revision 2). The server tags a
//    note that opens "or <amount>" with the method text's own grammar (stepscale.note_spans) and
//    sends the spans beside the raw note; every other note has none and prints as stored. Edit
//    mode and "your changes" read row.note, which never changes.
export function readNoteAt(row, factor) {
  if (!(row.note && row.note.trim())) return "";
  const text = row.note_spans && row.note_spans.length
    ? noteSpanTexts(row.note_spans, factor).map((s) => s.text).join("")
    : row.note;
  return `<span class="inote">${esc(text)}</span>`;
}
