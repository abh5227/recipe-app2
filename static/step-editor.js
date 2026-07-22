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

import { Editor } from "@tiptap/core";
import { Document } from "@tiptap/extension-document";
import { Paragraph } from "@tiptap/extension-paragraph";
import { Text } from "@tiptap/extension-text";
import { History } from "@tiptap/extension-history";

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
      extensions: [Document, Paragraph, Text, History],
      content: textToDoc(step.text || ""),           // plain text -> paragraph(s); raw markup stays literal
      onUpdate: ({ editor }) => onStepInput(i, docToText(editor)),
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

// ---- plain-text <-> doc (1a: no markup interpretation) ----------------------------------------
// A method step is one logical line, modelled as a single paragraph. Internal newlines (rare) map to
// separate paragraphs and rejoin with "\n" on serialize, so text -> doc -> text is faithful.
function textToDoc(text) {
  const paras = String(text).split("\n").map((line) =>
    line
      ? { type: "paragraph", content: [{ type: "text", text: line }] }
      : { type: "paragraph" });
  return { type: "doc", content: paras.length ? paras : [{ type: "paragraph" }] };
}

function docToText(editor) {
  // Default getText joins blocks with "\n\n"; a step is one line, so join blocks with a single "\n".
  return editor.getText({ blockSeparator: "\n" });
}
