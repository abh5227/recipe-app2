// feedtime.js — pure date / relative-time formatting for the social feed. ES module like scaler.js:
// app.js imports these names in the browser and the tests under tests/js/ import them the same way.
// No DOM, no globals, `now` injectable — so it's deterministic and unit-testable.

// Parse the server's "%Y-%m-%d %H:%M:%S" (UTC) into ms since epoch. NaN if it doesn't match (be
// defensive: the client never assumes a shape it can't verify).
function parseUtc(s) {
  if (typeof s !== "string") return NaN;
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if (!m) return NaN;
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
}

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Humane relative share-time: "just now" / "5m" / "3h" / "2d" under 7 days, else a short date
// ("Jul 3", plus the year when it isn't the current one). Unparseable → the raw string (never crash),
// or "" for non-strings.
function feedRelTime(s, now = Date.now()) {
  const t = parseUtc(s);
  if (Number.isNaN(t)) return typeof s === "string" ? s : "";
  const diff = Math.max(0, now - t);
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return min + "m";
  const hr = Math.floor(min / 60);
  if (hr < 24) return hr + "h";
  const day = Math.floor(hr / 24);
  if (day < 7) return day + "d";
  const d = new Date(t);
  const base = `${MON[d.getUTCMonth()]} ${d.getUTCDate()}`;
  return d.getUTCFullYear() === new Date(now).getUTCFullYear() ? base : `${base}, ${d.getUTCFullYear()}`;
}

// Defensive display of a cook date. Usually "YYYY-MM-DD" — but the client does NOT assume that: a
// clean match becomes "Jul 3, 2021"; anything else is returned as-is (or "" for a non-string).
function feedDateShort(s) {
  if (typeof s !== "string") return "";
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return s;
  const mon = MON[(+m[2]) - 1];
  return mon ? `${mon} ${+m[3]}, ${m[1]}` : s;
}

export { feedRelTime, feedDateShort, parseUtc };
