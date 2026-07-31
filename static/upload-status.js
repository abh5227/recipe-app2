"use strict";
// Pure status -> in-frame error markup for the photo uploader (Stage 3). Standalone (like tomake.js /
// feedtime.js) so the status→message mapping is unit-testable without the DOM; app.js injects the
// returned HTML into the empty Polaroid's photo cell on an upload failure. Maps the shipped endpoint's
// real responses: 413 (MAX_CONTENT_LENGTH), 400 (image validation), anything else -> generic recoverable.
export function uploadErrorHTML(status) {
  if (status === 413) return '<span class="err-msg">Too large — max 10&nbsp;MB.</span><button class="err-retry">Try again</button>';
  if (status === 400) return '<span class="err-msg">Not an image file.</span><span class="err-sub">JPEG, PNG, WebP, or HEIC</span><button class="err-retry">Try again</button>';
  return '<span class="err-msg">Upload failed — try again.</span><button class="err-retry">Try again</button>';
}
