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

// A heading's WORDS: [[key|label]] -> the label, [[key]] -> the key, everything else verbatim.
//
// ⚠️ THIS IS A DISPLAY TRANSFORM AND THE STORED TEXT KEEPS ITS MARKUP. A heading is escaped and
// never linkified (a clickable button inside an uppercase section label is not a thing this app
// draws), so a converted step carrying [[garlic]] printed its brackets on the page. The importer and
// the corpus pass avoid that by MOVING the link out when they lift a lead-in label, which is right
// for a label whose referent is in the step below it. The step row menu has no such move available:
// it converts a whole step, markup and all, and the cook can convert it straight back. Rewriting the
// text on conversion would spend the link to buy the brackets, and nothing would bring it back.
//
// So the text is stored verbatim and every heading renderer runs it through here. Converting back to
// a step restores the link, because the link was never removed.
//
// It lives beside the two round-trip functions because they own this grammar — the regex is the same
// one stepTextToDoc and app.js's linkify use, and a third spelling of it is how the two readers of a
// shared rule drift apart.
export function showLinksAsWords(text) {
  return String(text == null ? "" : text)
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, key, label) => (label || key).trim());
}
