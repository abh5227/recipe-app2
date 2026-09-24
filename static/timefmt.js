// timefmt.js — the reading view's half of the time normalizer. The other half is
// import_cleanup.normalize_time, which runs on the way IN. This one runs on the way OUT, so the
// 218 already-stored times read the same as a fresh import without a single stored row being
// rewritten.
//
// ⚠️ MIRRORS import_cleanup.normalize_time AND IS HELD TO IT. tests/js/timefmt-sync.test.js and
// tests/test_import_cleanup.py assert both implementations against the SAME case table,
// tests/fixtures/time-cases.json, which was generated from every one of the 63 distinct spellings
// live data actually holds. Change one side and the other goes red. Same arrangement as
// scaler.js / weights.py.
//
// ⚠️ IT IS NOT USED IN THE EDITOR. An editable field shows the RAW stored value, so saving can
// never normalize behind the cook's back. Display only.

// Measured over the 218 stored times: min 102, mins 56, minutes 44, hr 16, hour 7, hours 3, hrs 1.
const TIME_UNITS = {
  min: "min", mins: "min", minute: "min", minutes: "min", m: "min",
  hr: "hr", hrs: "hr", hour: "hr", hours: "hr", h: "hr",
};

// One "N unit" segment with an optional range. The unit is captured LOOSELY as any word, so a
// non-time word ("1 cup" in a time column) is read and then REFUSED rather than skipped past.
const SEG = /(\d+(?:\.\d+)?)(?:\s*(?:to|[-–—])\s*(\d+(?:\.\d+)?))?\s*([A-Za-z]+)\.?/iy;
const SEG_G = /(\d+(?:\.\d+)?)(?:\s*(?:to|[-–—])\s*(\d+(?:\.\d+)?))?\s*([A-Za-z]+)\.?/gi;
const JOIN = /[\s,]*(?:and\s+)?/iy;
const NOTE_LEAD = /^[\s,;:—–-]+/;

const seg = (lo, hi, unit) => (hi ? `${lo}–${hi} ${unit}` : `${lo} ${unit}`);

// Normalize any duration INSIDE a trailing note, leaving every other word alone.
function timeInNote(note) {
  return note.replace(SEG_G, (whole, lo, hi, word) => {
    const unit = TIME_UNITS[String(word).toLowerCase()];
    return unit ? seg(lo, hi, unit) : whole;
  });
}

// "10 mins" -> "10 min". "1 hr, 30 min" -> "1 hr 30 min". "15-20 minutes" -> "15–20 min".
// "30 mins, plus 1 hour soaking" -> "30 min · plus 1 hr soaking".
// Anything unreadable comes back EXACTLY as given. Never blanked, never guessed at.
export function normalizeTime(raw) {
  const s = String(raw == null ? "" : raw).trim();
  if (!s) return s;
  const parts = [];
  let pos = 0;
  while (pos < s.length) {
    let probe = pos;
    if (parts.length) { JOIN.lastIndex = pos; probe = JOIN.exec(s) ? JOIN.lastIndex : pos; }
    SEG.lastIndex = probe;
    const m = SEG.exec(s);
    if (!m) break;
    const unit = TIME_UNITS[String(m[3]).toLowerCase()];
    if (!unit) break;
    parts.push(seg(m[1], m[2], unit));
    pos = SEG.lastIndex;
  }
  if (!parts.length) return s;
  let note = s.slice(pos).trim().replace(NOTE_LEAD, "");
  if (note.startsWith("(") && note.endsWith(")")) note = note.slice(1, -1).trim();
  const duration = parts.join(" ");
  return note ? `${duration} · ${timeInNote(note)}` : duration;
}
