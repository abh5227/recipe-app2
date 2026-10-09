"use strict";
// esc.js — the one HTML escape. Every piece of data the page inserts goes through it.
//
// ⚠️ IT LIVES IN A MODULE OF ITS OWN SO THE RENDER CAN BE TESTED WHERE IT IS WRITTEN. app.js held
//    it as a local function, and a renderer that needs it could only be exercised by loading the
//    whole page. ledger-row.js imports it, and so does app.js, so there is one escape and not two.
export function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
}
