"use strict";
// The word-level diff behind a name/step annotation, as PURE DATA — no DOM, no esc(), no `view` — so
// it's unit-testable in node like annotation-place.js / row-insert.js. app.js imports it and does the
// escaping + span-wrapping, which keeps every "raw HTML from user text" decision in one place there.
//
// WHY THIS ISN'T JUST split(/\s+/). Whitespace tokens bind trailing punctuation to the word before it,
// so "cauliflower" and "cauliflower," are different tokens with nothing in common. Appending a tail to a
// name therefore struck the noun and re-inked it verbatim:
//     "cauliflower" -> "cauliflower, cut into small florets"
//     rendered as:  ~~cauliflower~~ [cauliflower, cut into small florets]
// The reader sees the ingredient's own name crossed out and rewritten as itself, which says nothing
// about what changed. All 18 note->name moves on the four hand-edited recipes rendered this way.
// Splitting punctuation into its OWN token makes the shared words actually match, so only the tail is
// marked: cauliflower[, cut into small florets].
//
// PUNCTUATION IS A TOKEN, NOT A SUFFIX — and that choice is load-bearing. The obvious alternative,
// "match on the word with trailing punctuation ignored", also fixes the doubling, but it makes a
// punctuation-ONLY edit invisible: "salt, pepper" -> "salt; pepper" matches on every token and renders
// with NO MARK AT ALL, silently reporting that nothing changed. Measured across 39,756 mutations of every
// real name and step in the corpus, that variant erased marks; this one erases none. A separate token
// can be struck or inked on its own, so the comma-to-semicolon edit still shows: salt~~,~~[;] pepper.
//
// The SHARED-WORD fallback guard exists for the same reason in reverse: with punctuation tokenised, two
// wholly different strings can still "share" a comma, which would defeat the whole-field strike+ink and
// fragment an unrelated replacement ("sugar, divided" -> "eggs, beaten" as ~~sugar~~ [eggs], ~~divided~~
// [beaten]). The fallback therefore tests for a shared NON-PUNCTUATION token.

// Split points: structural punctuation anywhere in a token, plus sentence-final .!? — anchored to the
// token END so decimals ("28.35"), fractions ("1/2") and hyphenated words ("extra-virgin", "half-moons")
// are never broken up.
const PUNCT = /([,;:()[\]]|[.!?](?=$))/;
const PUNCT_ONLY = /^[,;:.!?()[\]]+$/;
const NO_SPACE_BEFORE = /^[,;:.!?)\]]/;
const NO_SPACE_AFTER = /[([]$/;

function tokens(s) {
  return String(s || "").split(/\s+/).filter(Boolean)
    .flatMap((w) => w.split(PUNCT).filter(Boolean));
}

// The space between two adjacent tokens — "" where punctuation attaches, so re-joining a token run
// reproduces the original spacing ("cauliflower" + "," -> "cauliflower,", "(" + "optional" -> "(optional").
function gapBetween(prev, next) {
  return (!prev || NO_SPACE_BEFORE.test(next) || NO_SPACE_AFTER.test(prev)) ? "" : " ";
}

function joinTokens(ws) {
  return ws.reduce((acc, w, i) => acc + (i ? gapBetween(ws[i - 1], w) : "") + w, "");
}

// Token LCS. Order follows the walk: a divergence emits the struck old token(s) then the inked new
// token(s), shared runs stay plain.
function lcsWalk(a, b) {
  const n = a.length, m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ t: "eq", w: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: "del", w: a[i] }); i++; }
    else { out.push({ t: "ins", w: b[j] }); j++; }
  }
  while (i < n) out.push({ t: "del", w: a[i++] });
  while (j < m) out.push({ t: "ins", w: b[j++] });
  return out;
}

// -> [{ t: "eq"|"del"|"ins", text, gap }] in render order. `gap` is the separator that precedes the
// part (""or " "), so the caller concatenates parts with no join separator of its own. Consecutive
// same-type tokens are coalesced so one edit is one span, not one span per word.
function wordDiffParts(fromStr, toStr) {
  const a = tokens(fromStr), b = tokens(toStr);
  const walk = lcsWalk(a, b);
  if (!walk.some((x) => x.t === "eq" && !PUNCT_ONLY.test(x.w))) {
    // No shared WORD -> strike the whole old field and ink the whole new one; cleaner than marking
    // every token, and it keeps both sides readable as the sentences they are.
    return [{ t: "del", text: String(fromStr || ""), gap: "" },
            { t: "ins", text: String(toStr || ""), gap: " " }];
  }
  const parts = [];
  for (const x of walk) {
    const last = parts[parts.length - 1];
    if (last && last.t === x.t) last.w.push(x.w);
    else parts.push({ t: x.t, w: [x.w] });
  }
  return parts.map((p, i) => ({
    t: p.t,
    text: joinTokens(p.w),
    gap: i ? gapBetween(parts[i - 1].w[parts[i - 1].w.length - 1], p.w[0]) : "",
  }));
}

export { wordDiffParts };
