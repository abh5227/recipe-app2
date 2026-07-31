"use strict";
// Pins the upload status -> in-frame message mapping (static/upload-status.js). The browser pass covers
// the drag/drop interaction; this guards the pure mapping (correct message per real endpoint response).
import { test } from "node:test";
import assert from "node:assert/strict";
import { uploadErrorHTML } from "../../static/upload-status.js";

test("413 -> too-large message with a Try again button", () => {
  const html = uploadErrorHTML(413);
  assert.match(html, /Too large — max 10/);
  assert.match(html, /err-retry/);
  assert.doesNotMatch(html, /Not an image/);
});

test("400 -> not-an-image message names the accepted formats", () => {
  const html = uploadErrorHTML(400);
  assert.match(html, /Not an image file/);
  assert.match(html, /JPEG, PNG, WebP, or HEIC/);   // user-facing copy says HEIC (the extension iPhone users see); the allowlist matches "HEIF"
  assert.match(html, /err-retry/);
});

test("any other status -> a generic recoverable failure", () => {
  for (const s of [0, 403, 500]) {
    const html = uploadErrorHTML(s);
    assert.match(html, /Upload failed/);
    assert.match(html, /err-retry/);
  }
});
