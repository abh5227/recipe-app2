// hero-caption.js — the SHARED hero caption read: "the caption of the is_hero photo" (or null). Covers the
// three cases the hero render must handle gracefully: a captioned cook-photo hero (show it), an uncaptioned
// one (no caption area), and no is_hero match at all — a legacy/backfilled hero with no cook_photo row (no
// caption area, don't break).
import { test } from "node:test";
import assert from "node:assert/strict";
import { heroCaption } from "../../static/hero-caption.js";

test("captioned is_hero photo -> its caption (not another photo's)", () => {
  const photos = [
    { id: 1, is_hero: false, caption: "album note" },
    { id: 2, is_hero: true, caption: "nailed the sear" },
  ];
  assert.equal(heroCaption(photos), "nailed the sear");
});

test("uncaptioned is_hero photo -> null (no caption area)", () => {
  assert.equal(heroCaption([{ id: 2, is_hero: true, caption: null }]), null);
  assert.equal(heroCaption([{ id: 2, is_hero: true, caption: "" }]), null);
});

test("no is_hero match (non-cook-photo / legacy hero) -> null, no throw", () => {
  assert.equal(heroCaption([{ id: 1, is_hero: false, caption: "x" }]), null);
  assert.equal(heroCaption([]), null);
  assert.equal(heroCaption(null), null);
  assert.equal(heroCaption(undefined), null);
});
