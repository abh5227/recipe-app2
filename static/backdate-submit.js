"use strict";
// Pure, DOM-free orchestrator for the backdate modal's "log the cook -> attach its staged photos" submit
// (Stage 4 build 3b-ii). Standalone (like upload-status.js) so the sequencing — and especially the
// correctness crux — is unit-testable without the DOM. app.js injects the real logCook / attachPhotos
// (network + DOM side effects live there); this only holds the id and sequences the two steps.
//
// THE CRUX (retry-holds-the-id): once the cook is logged, its id is HELD. A retry after a photo failure
// re-attaches to the SAME cook and NEVER re-logs it — a re-log would create a DUPLICATE cook. `run` skips
// the cook-create whenever an id is already held; `reset` (called when the modal reopens) clears it so the
// next submit logs a fresh cook.
// Client-side staging gate for the backdate add-a-photo picker (3b-ii). Mirrors the server allowlist
// (images.ALLOWED_INPUT_FORMATS = JPEG/PNG/WEBP/HEIF) so a wrong-type file is rejected BEFORE it stages —
// no broken thumbnail, no doomed upload. A KNOWN mime type must be on the allowlist; an EMPTY/unknown type
// (macOS hands HEIC as "" in many contexts) falls back to the extension, so valid HEIC — which browsers
// can't decode, ruling out a decode check — still stages. The rare mislabeled file that slips through is
// caught by the upload's hold-until-both guard (belt-and-suspenders). Kept in sync with images.py by
// tests/js/backdate-submit.test.js.
const STAGE_OK_MIME = new Set([
  "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
  "image/heic-sequence", "image/heif-sequence",
]);
const STAGE_OK_EXT = /\.(jpe?g|png|webp|heic|heif)$/i;
export function isStageableImage(file) {
  const t = ((file && file.type) || "").toLowerCase();
  if (t === "") return STAGE_OK_EXT.test((file && file.name) || "");   // unknown type -> trust the extension (HEIC)
  return STAGE_OK_MIME.has(t);                                         // known type -> must be on the allowlist
}

export function makeBackdateSubmit({ logCook, attachPhotos }) {
  let cookId = null;                               // held across retries — the anti-duplicate guard
  return {
    cookId: () => cookId,
    reset() { cookId = null; },                    // modal (re)opened -> a fresh cook next submit

    // staged: the items to attach (opaque to this module — app.js knows their shape). Returns one of:
    //   { status: "cook-failed", error }               — the cook couldn't be logged (nothing held; retry re-logs)
    //   { status: "photos-failed", cookId, failed }    — cook logged (id held); `failed` should stay staged for retry
    //   { status: "done", cookId }                     — cook logged + all photos attached (or none were staged)
    async run(staged) {
      if (cookId == null) {                        // FIRST attempt only: create the cook exactly once
        const r = await logCook();                 // -> { ok, cookId?, error? }
        if (!r.ok) return { status: "cook-failed", error: r.error };
        cookId = r.cookId;                         // HOLD it — every retry reuses this, never re-logs
      }
      if (!staged || !staged.length) return { status: "done", cookId };
      const failed = await attachPhotos(cookId, staged);   // -> the subset that failed (empty/undefined if all ok)
      if (failed && failed.length) return { status: "photos-failed", cookId, failed };
      return { status: "done", cookId };
    },
  };
}
