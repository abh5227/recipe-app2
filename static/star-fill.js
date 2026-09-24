// star-fill.js — the pure arithmetic behind the rating stars. Split out for the same reason
// scaler.js and tomake.js are: it is the part with edge cases, and a module is testable without a DOM.
//
// ⚠️ TWO MODES, BECAUSE A RECIPE'S NUMBER AND A COOK'S VERDICT ARE DIFFERENT KINDS OF THING.
// A cook's verdict is on a half step. A recipe's number is the AVERAGE of its rated cooks, which is
// usually not: three cooks rated 5, 4 and 4 average 4.333…. Rounding that to a half before drawing it
// is a claim the data does not support, so the read-only renderer fills CONTINUOUSLY and prints the
// figure beside the stars.
export const RATING_MAX = 5;

// The half steps a single cooking may be rated. Mirrors app.RATING_STEPS and the DB CHECK on
// cook_log.rating — ⚠️ change one and change all three, the scaler.js/weights.py arrangement.
export const RATING_STEPS = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5];

// ⚠️ null IS NOT ZERO HERE. An unrated cook is null and a zero-star rating does not exist (the DB
// floor is 0.5), so Number(null) === 0 must not be allowed to read as a real value. Both functions
// reject it explicitly rather than leaning on Number.isFinite, which accepts null, "" and false.
const asRating = (value) =>
  (value === null || value === undefined || value === "" || typeof value === "boolean")
    ? null
    : (Number.isFinite(Number(value)) ? Number(value) : null);

// value -> the width of the gold overlay, clamped. A malformed or missing value reads as empty
// rather than throwing, because this runs inside a render that must not take the page down.
// Rounded to 2 decimals: 4.3333… would otherwise write 86.66666599999999% into the DOM, which is
// noise at any screen width.
export function ratingPct(value) {
  const n = asRating(value);
  if (n === null) return "0%";
  return `${Math.round(Math.max(0, Math.min(1, n / RATING_MAX)) * 10000) / 100}%`;
}

// The figure printed beside the stars. One decimal, with a trailing ".0" trimmed so a clean 4 reads
// as "4" and not "4.0" — the precision should say something, and on a whole number it does not.
export function ratingText(value) {
  const n = asRating(value);
  if (n === null) return "";
  return String(n.toFixed(1)).replace(/\.0$/, "");
}

// Clicking the step a cook already sits on CLEARS it. That gesture is the only route back to
// unrated, so it lives here rather than being written twice in the two places stars are clickable.
export function nextRating(current, clicked) {
  return Number(current) === Number(clicked) ? null : Number(clicked);
}
