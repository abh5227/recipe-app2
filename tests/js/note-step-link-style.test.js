"use strict";
// The step link and the × that removes it, held apart by a rule rather than by a number.
//
// ⚠️ THE DEFECT THIS FILE EXISTS FOR. `.note-unlink` read `margin-left: -10px`, which is an OVERLAP
// and not a gap. Measured in the browser on the real panel: the link button's box ends exactly where
// its last glyph ends, the × is 8px wide, and a -10px pull put the × on top of the link's last 10px
// at EVERY step number. At one digit it covered a narrow "1" and read as a tight pairing, which is
// why it shipped. At two digits it covered the second one, so a note linked to step 13 printed
// "step 1✕". Andy found it clicking through the rehearsal on 2026-10-06.
//
// The rule underneath: a control that has to sit BESIDE text is placed by the container's `gap`, so
// it cannot land on the text whatever the text measures. A pull of any fixed size can.
//
// ⚠️ AND THE OTHER FOUR PLACES A STEP LINK APPEARS WERE MEASURED AND ARE CLEAN. The picker row's
// number (.pk-n) is `flex: 0 0 auto` inside a `gap: 8px` row, the STEP NOTES lead and the popover's
// "(step N)" are inline text with no width of their own, and Edit mode draws the same panel this
// rule governs. So the sweep below is stated over the footer rather than over one selector.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const CSS = fs.readFileSync(path.join(import.meta.dirname, "../../static/styles.css"), "utf8");

/** Every rule whose selector list contains `sel`, as {selectors, body}. */
function rulesFor(sel) {
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(CSS)) !== null) {
    const selectors = m[1].replace(/\/\*[\s\S]*?\*\//g, "")
      .split(",").map((s) => s.trim()).filter(Boolean);
    if (selectors.includes(sel)) out.push({ selectors, body: m[2] });
  }
  return out;
}

test("the × is placed by the anchor's gap, not by a pull", () => {
  const anchor = rulesFor(".note-anchor");
  assert.ok(anchor.length > 0, ".note-anchor has no rule");
  const flex = anchor.find((r) => /display\s*:\s*inline-flex/.test(r.body));
  assert.ok(flex, ".note-anchor is no longer the inline-flex wrapper the pair sits in");
  const gap = /(?:^|;|\{|\s)gap\s*:\s*([^;]+)/.exec(flex.body);
  assert.ok(gap, `.note-anchor sets no gap, so the two buttons sit flush: ${flex.body}`);
  // a POSITIVE length. A gap cannot overlap; that is the whole point of using it.
  const n = parseFloat(gap[1]);
  assert.ok(Number.isFinite(n) && n > 0, `the gap has to be positive: ${gap[1]}`);
});

test("no control in the note footer is positioned by a negative margin", () => {
  // Stated over the footer's own selectors rather than over .note-unlink alone, so the next
  // control added there is covered before anyone remembers it.
  const re = /([^{}]+)\{([^{}]*)\}/g;
  const bad = [];
  let m;
  while ((m = re.exec(CSS)) !== null) {
    const selectors = m[1].replace(/\/\*[\s\S]*?\*\//g, "").split(",").map((s) => s.trim());
    if (!selectors.some((s) => /\.note-(foot|tool|anchor|unlink|caret|x|hint)\b/.test(s))) continue;
    const neg = /margin(?:-left|-right|-inline[a-z-]*)?\s*:\s*[^;]*-\d/.exec(m[2]);
    if (neg) bad.push(`${selectors.join(", ")} {${neg[0]}}`);
  }
  assert.deepEqual(bad, [], `a negative margin in the note footer: ${bad.join(" | ")}`);
});

test("the spacing beside the × has exactly one source", () => {
  // ⚠️ WITHOUT THE RESET the generic `.note-caret, .note-x` margin would add its own .25em on top
  //    of the anchor's gap, so the pair would read with two different gaps depending on which
  //    control it was.
  assert.match(CSS, /\.note-unlink \.note-x \{[^}]*margin-left:\s*0/,
    ".note-x keeps no reset inside .note-unlink, so the gap is applied twice");
});

test("the link sizes to its number, in every place a step link is drawn", () => {
  // No fixed width and no absolute positioning on anything that holds a step number. A two-digit
  // number has to be able to make its own box wider.
  for (const sel of [".note-tool", ".note-unlink", ".pk-n", ".note-lead", "a.note-lead-step",
                     "a.meta-step.note-step"]) {
    for (const r of rulesFor(sel)) {
      assert.ok(!/(?:^|;|\s)width\s*:\s*\d/.test(r.body),
        `${sel} pins a width, so a longer number cannot fit: ${r.body}`);
      assert.ok(!/position\s*:\s*absolute/.test(r.body),
        `${sel} is taken out of flow, so it cannot sit beside anything: ${r.body}`);
    }
  }
});
