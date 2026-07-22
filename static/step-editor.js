// step-editor.js — Stage 1a: per-step TipTap editors for the method, PLAIN TEXT ONLY.
//
// Scope (1a): one minimal TipTap Editor per NON-heading step, plain schema (document/paragraph/
// text/history). NO link chips, NO [[key|label]] parsing, NO {{...}} handling, NO autocomplete —
// those are 1b/1c/1d. Raw markup shows as LITERAL text here (expected); it round-trips byte-faithful
// because a plain schema neither interprets nor rewrites it.
//
// ISLAND INVARIANT: these instances live inside the DOM that app.js's paintRecipe() replaces via
// `app.innerHTML = …`. paintRecipe fires ONLY at initial load / enterEditMode / exitEditMode — never
// mid edit-session — so a mount-on-enter / destroy-on-exit lifecycle is sufficient (no re-mount per
// paint, no teaching paint to skip a node). If a future feature repaints the recipe MID-SESSION, it
// MUST destroyStepEditors() then mountStepEditors() again, or the instances are orphaned.
//
// Self-contained + removable: app.js calls mountStepEditors()/destroyStepEditors() at the edit-mode
// enter/exit/save/nav hooks; view/state ownership stays in app.js (passed in, written back via cb).

import { Editor, Node } from "@tiptap/core";
import { Document } from "@tiptap/extension-document";
import { Paragraph } from "@tiptap/extension-paragraph";
import { Text } from "@tiptap/extension-text";
import { History } from "@tiptap/extension-history";
import { stepTextToDoc, docToStepText } from "./step-adapter.js";

// The [[key|label]] chip: an inline atom node. atom:true (no editable content) + contenteditable=false
// on the DOM make the caret treat it as a single unit — arrows skip it, backspace deletes it whole,
// you can't type inside. id/label are rendered:false (they live in the node/JSON, not as HTML attrs)
// so renderHTML can emit the SAME markup reading-mode linkify does (<button class="ingredient" …>) —
// reusing the existing .ingredient CSS, no new styling. Attrs survive editor.getJSON() -> the proven
// docToStepText serializer turns them back into [[id|label]].
const IngredientLink = Node.create({
  name: "ingredientLink",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return { id: { default: null, rendered: false }, label: { default: null, rendered: false } };
  },
  renderHTML({ node }) {
    const { id, label } = node.attrs;
    const shown = label != null ? label : id;
    return ["button", { class: "ingredient", "data-item": id, contenteditable: "false", type: "button" }, shown];
  },
});

// Live instances, parallel to the currently-mounted .step-editor-host nodes. Cleared on destroy.
let editors = [];

// Mount one editor per non-heading step host present in the (edit-mode) DOM.
//   draft       = view.draft (its .steps[i].text seeds each editor)
//   onStepInput = (i, text) => app.js writes view.draft.steps[i].text = text and marks dirty
// Idempotent: destroys any prior instances first, so it can never double-mount.
export function mountStepEditors(draft, onStepInput) {
  destroyStepEditors();
  if (!draft || !Array.isArray(draft.steps)) return;
  document.querySelectorAll(".step-editor-host").forEach((host) => {
    const i = Number(host.dataset.i);
    const step = draft.steps[i];
    if (!step || step.is_heading) return;            // headings keep their plain rendering (not TipTap in 1a)
    const editor = new Editor({
      element: host,
      extensions: [Document, Paragraph, Text, History, IngredientLink],
      content: stepTextToDoc(step.text || ""),        // [[key|label]] -> chip nodes; other text verbatim
      onUpdate: ({ editor }) => onStepInput(i, docToStepText(editor.getJSON())),
    });
    editors.push(editor);
  });
}

// Destroy every live instance and clear the list. Safe (no-op) when nothing is mounted. This is the
// required teardown discipline — orphaned ProseMirror instances leak listeners/DOM otherwise.
export function destroyStepEditors() {
  for (const ed of editors) { try { ed.destroy(); } catch (_) { /* already torn down */ } }
  editors = [];
}

// How many editors are currently mounted — used to VERIFY teardown (0 after every exit path).
export function mountedStepEditorCount() { return editors.length; }
