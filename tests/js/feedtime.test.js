"use strict";
// JS unit tests for the pure feed date/relative-time helpers (static/feedtime.js). Run with
// `node --test tests/js`. `now` is injected so the relative buckets are deterministic.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as ft from "../../static/feedtime.js";

const NOW = Date.UTC(2026, 6, 26, 12, 0, 0);   // 2026-07-26 12:00:00 UTC
const ago = (ms) => new Date(NOW - ms).toISOString().slice(0, 19).replace("T", " ");   // "%Y-%m-%d %H:%M:%S" UTC

test("feedRelTime: just-now / minutes / hours / days buckets", () => {
  assert.equal(ft.feedRelTime(ago(30 * 1000), NOW), "just now");
  assert.equal(ft.feedRelTime(ago(5 * 60 * 1000), NOW), "5m");
  assert.equal(ft.feedRelTime(ago(3 * 3600 * 1000), NOW), "3h");
  assert.equal(ft.feedRelTime(ago(2 * 86400 * 1000), NOW), "2d");
});

test("feedRelTime: >=7 days falls back to a short date, year only when not current", () => {
  assert.equal(ft.feedRelTime("2026-07-03 09:00:00", NOW), "Jul 3");
  assert.equal(ft.feedRelTime("2020-01-15 09:00:00", NOW), "Jan 15, 2020");
});

test("feedRelTime: unparseable input returns the raw string (never crashes); non-string -> ''", () => {
  assert.equal(ft.feedRelTime("not a date", NOW), "not a date");
  assert.equal(ft.feedRelTime(null, NOW), "");
});

test("feedDateShort: YYYY-MM-DD -> humane; unknown -> raw; non-string -> ''", () => {
  assert.equal(ft.feedDateShort("2021-07-03"), "Jul 3, 2021");
  assert.equal(ft.feedDateShort("last week"), "last week");
  assert.equal(ft.feedDateShort(null), "");
});
