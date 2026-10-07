"use strict";
// The legacy #/edit form may not clear a recipe's notes.
//
// ⚠️ THE RULE IT BREAKS IS THE PUT's, NOT THIS FORM's. `_kept` makes an ABSENT key mean keep; an
// EMPTY STRING means "replace the list with nothing", which is the documented old-client path. The
// textarea used to pre-fill from recipe.notes, the derived copy. Migration 063 dropped that column,
// so `pre.notes` became undefined and the field was always empty, and every save from this form
// then sent notes:"" over whatever the recipe actually had. Measured on a fixture by an independent
// review: a recipe with two note rows answered 200 and came back with zero.
//
// ⚠️ RUN, NOT READ. gatherPayload is cut out of app.js and executed against a stub document, so a
// future edit that reintroduces the key fails here rather than passing a source-shape assertion.
import { test } from "node:test";
import assert from "node:assert/strict";
import { APP, sliceFunction } from "./time-block-harness.js";

function run(mode, values = {}) {
  const doc = {
    getElementById: (id) => (id in values ? { value: values[id], checked: false } : null),
    querySelectorAll: () => [],
  };
  const fn = new Function("document", `${sliceFunction("gatherPayload")}; return gatherPayload;`)(doc);
  return fn(mode);
}

test("editing says nothing about notes, so the PUT keeps them", () => {
  const payload = run("edit", { "f-name": "Brioche", "f-notes": "" });
  assert.ok(!("notes" in payload),
            `an edit sent notes=${JSON.stringify(payload.notes)}, which clears every note row`);
  assert.equal(payload.name, "Brioche", "the rest of the form stopped working");
});

test("creating still carries the note the form offers", () => {
  const payload = run("create", { "f-name": "New", "f-notes": "Tip: salt late." });
  assert.equal(payload.notes, "Tip: salt late.");
});

test("the textarea is only drawn where it can do no harm", () => {
  // ⚠️ A SOURCE ASSERTION, AND IT KNOWS IT. The two tests above are the behavioural half and are
  //    what actually protects the data. This one is about what the cook SEES: on a recipe that
  //    already has notes, an always-empty box labelled "Note" says the recipe has none.
  const i = APP.indexOf('id="f-notes"');
  assert.ok(i > 0, "the notes field is gone entirely, so this test has nothing to say");
  const line = APP.slice(APP.lastIndexOf("\n", i) + 1, APP.indexOf("\n", i));
  assert.match(line, /mode === "create" \?/,
               `the notes textarea is drawn while editing, where it can only destroy:\n  ${line}`);
});
