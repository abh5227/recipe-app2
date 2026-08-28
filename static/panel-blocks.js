// Which field-guide drawer blocks have something to show. Pure, so it's unit-tested directly
// (tests/js/panel-blocks.test.js) rather than through the DOM.
//
// ONE RULE FOR ALL FOUR BLOCKS: no data, no block. `used-block` already worked this way, hiding
// itself when a row is in no recipes; season, regions and pairs each rendered a heading over
// nothing instead, and season went further and rendered a CLAIM over nothing ("A pantry staple,
// available year-round") for any row with no month data.
//
// ⚠️ THAT LINE IS GONE ON PURPOSE, AND IT WAS SHOWING ON 22 OF THE 36 CURATED ROWS, not only on
// the promoted ones. soy_sauce, cumin, sesame_oil and 19 more carry no ingredient_seasons rows, so
// the drawer told you they were year-round staples. Dropping it is a deliberate call: a panel
// should show the sections that have content and stay quiet about the rest, and one honest rule
// beats a message that has to guess which kind of emptiness it is looking at.
export function panelBlocks(item) {
  const it = item || {};
  return {
    season: (it.season || []).length > 0,
    regions: (it.regions || []).length > 0,
    pairs: typeof it.pairs === "string" && it.pairs.trim() !== "",
    used: (it.used_in || []).length > 0,
  };
}
