// step-adapter.js — PURE [[key|label]] step-text <-> ProseMirror JSON adapter (Stage 1b-1).
//
// Deliberately DEPENDENCY-FREE: no TipTap, no DOM, no imports of any kind. That's what keeps the
// JS test suite zero-dep (node --test, no npm install in CI) — the round-trip test imports THIS
// module directly, not the TipTap-coupled step-editor.js. step-editor.js imports these when it wires
// the live editor in 1b-2 (chips serialize through docToStepText; getText would drop chip nodes).
//
// Reuses linkify's regex (app.js). Fidelity rule (proven byte-identical on all real linked steps):
// emit |label IFF label != null; a no-label [[key]] records label:null and serializes back WITHOUT a
// spurious |label (never collapse label==key either); text/Unicode runs pass through verbatim.

// text -> ProseMirror JSON doc. A step is one paragraph; an internal "\n" splits into separate
// paragraphs so a multi-line step round-trips. Empty/whitespace lines reproduce the original line.
export function stepTextToDoc(text) {
  // Fresh regex per call (linkify's pattern) so the /g lastIndex is never shared across calls.
  const re = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g;
  const content = String(text).split("\n").map((line) => {
    const inline = [];
    let i = 0, m;
    re.lastIndex = 0;
    while ((m = re.exec(line)) !== null) {
      if (m.index > i) inline.push({ type: "text", text: line.slice(i, m.index) });   // non-empty run only
      inline.push({ type: "ingredientLink", attrs: { id: m[1], label: m[2] !== undefined ? m[2] : null } });
      i = m.index + m[0].length;
    }
    if (i < line.length) inline.push({ type: "text", text: line.slice(i) });           // trailing run
    // Empty line -> a paragraph with no content (ProseMirror rejects zero-length text nodes).
    return inline.length ? { type: "paragraph", content: inline } : { type: "paragraph" };
  });
  return { type: "doc", content: content.length ? content : [{ type: "paragraph" }] };
}

// ProseMirror JSON doc -> text (PURE). Paragraphs join with "\n"; each ingredientLink node ->
// [[id|label]] when label != null, else [[id]]. Byte-identical to the stored text for a faithful doc.
export function docToStepText(docJson) {
  const paras = (docJson && docJson.content) || [];
  return paras.map((para) => {
    const inline = (para && para.content) || [];
    return inline.map((node) => {
      if (node.type === "ingredientLink") {
        const { id, label } = node.attrs || {};
        return label != null ? `[[${id}|${label}]]` : `[[${id}]]`;
      }
      return node.text || "";
    }).join("");
  }).join("\n");
}
