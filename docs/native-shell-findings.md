# Native shell findings — does a WebView wrapper preserve this app?

The plan on the table is: keep building the web app, and later wrap it in a native shell that adds a
real browser (fixing import 403s and client-side-rendered sites), the camera, and offline. That
ordering is only safe if the wrapper **preserves** the existing web UI rather than forcing a native
rewrite. This file records what a probe measured, so the question doesn't get re-argued from
first principles when the shell actually comes up.

**Headline:** the wrapper preserves the UI on desktop — measured, not reasoned. The one thing it does
*not* fix is touch, and that gap is in the web app, not the shell.

## How this was measured (2026-08-21)

A throwaway WKWebView driver (Swift, `activationPolicy = .accessory`, offscreen window,
`WKSnapshotConfiguration` for PNGs) loaded the **real app** from a Flask instance whose `app.DB` was
rebound to a scratch copy of `recipes.db` (the `make_kitchen` pattern), logged in as a scratch user,
and drove the actual UI. Everything built for it lived outside the repo and was deleted; the tree
ended byte-identical at `4f07fe9`.

Environment: macOS 26.5.1, Swift 6.2.4 via Command Line Tools. **No Xcode.app and no iOS simulator**,
which bounds what could be tested — see *What was NOT measured*.

## 1. What works in a WKWebView

The app renders **completely**. The snapshot shows a working recipe editor: the ingredient ledger with
its amount/unit/name columns and dashed rules, paperclip and note icons, "+ add ingredient" /
"+ section heading", the METHOD list with numbered circles, and the floating
"● Editing · Unsaved changes · Save changes / Cancel" bar. Nothing unstyled, nothing degraded.

- **HTML5 drag-and-drop works end to end.** Step 1 moved to position 3 through the full chain —
  `dragstart` → `dataTransfer` (the app's own `setData` payload read back as `"0"`) → `dragover`
  (handler called `preventDefault`) → drop-bar paint → `drop` → `applyRowDrop` → re-render.
  `order_changed: true`. Capability surface all present: `draggable` attribute, `ondragstart` on
  window, `DataTransfer`, `DragEvent`, `setDragImage`.
- **TipTap / ProseMirror mounts and accepts typing.** Five editors on a five-step recipe,
  five `contenteditable` nodes, `insertText` landed and read back out of the ProseMirror node.
- **`/images/<path>` serves.** A hero loaded at its true 650×834.
- **Auth works within a session.** The `HttpOnly` cookie is invisible to JS (`document.cookie` is
  `""`) and authenticated `fetch` calls succeed.
- **`FormData` is available** and the three `<input type="file" accept="image/*">` elements construct
  correctly.

## 2. ⚠️ THE TOUCH FINDING — the load-bearing one

**Three distinct claims, recorded separately because collapsing them would overstate the evidence:**

1. **Measured working on macOS.** The reorder drag executed fully in WKWebView, as above.
2. **Structurally impossible on touch.** The app has **zero** touch or pointer handling — a sweep for
   `touchstart` / `touchmove` / `pointerdown` / `PointerEvent` / `touch-action` across `static/*.js`
   and `styles.css` returns nothing. Reorder is HTML5 drag-and-drop *exclusively*, and HTML5 DnD does
   not fire from touch input on iOS or Android WebView.
3. **UNMEASURED on device.** No Xcode, no iOS simulator, no Android emulator on this machine. Claim 2
   is a structural consequence of the code plus documented platform behaviour — it is **not** a test
   result, and should not be cited as one.

**What follows from this:** a phone needs a touch reorder path **regardless** of whether the shell is
a WebView wrapper or a native client. No shell can supply it, because the missing piece is the web
app's event handling. That is **app work, not shell work**, and it is independent of the wrapper
decision — which means it neither blocks the wrapper nor is fixed by going native.

If the target is desktop, nothing here blocks the planned ordering. If the target is a phone, the
reorder needs pointer events before a shell is worth building.

## 3. The bridge seam — one function wide

For a shell to fix fetching, the web app has to call something native instead of the server. That
seam is unusually clean:

`url_fetch.fetch(url)` returns either a `Refused` or an object carrying `(url, html)`. **Everything
downstream consumes only those two strings** — `url_cascade.read(final_url, html)`, then the JSON-LD
layer, then `import_cleanup`, then `import_write`. Nothing below the fetch knows or cares how the
bytes arrived.

- **Server side:** a shell that loads pages in a real browser (executing JS, carrying real cookies and
  a real UA) replaces **one function's output**. The parser, the cleanup stage, the writer and the UI
  are untouched.
- **Client side:** `{url}` becomes `{url, html}` on **two routes** (`/api/import/preview` and
  `/api/import/commit`). One request shape, two call sites.
- Call sites of the fetcher today: exactly two (`import_preview` has its own copy alongside
  `read_url_or_refusal` — the duplication already recorded in `072bd6f`).

**Implication:** server-side fetching is the one area not worth further investment. Its known
weaknesses — 403s from Cloudflare-fronted sites, client-side-rendered pages — are precisely what the
shell fixes, at a seam that costs almost nothing to move.

## 4. Wrapper vs. native — the cost split

| | Lines | Fate under a native rewrite |
|---|---|---|
| `static/` (client) | **6,698** | Rebuilt |
| `*.py` (server) | **7,423** | Reused unchanged |

**Reused as-is:** the entire JSON API, the ORM layer, the import pipeline
(`paprika_native_reader` → `import_cleanup` → `import_write`), the URL cascade, `weights.py`,
`stepscale.py`, the snapshot modules, auth, the social layer. A native client speaks the same HTTP.

**Rebuilt:** all of `static/`. Concretely — the ingredient ledger with its scaling and unit
abbreviation, the annotation overlay (`annotation-place.js` plus the CSS that paints strikes and
margin marks), the drag reorder, the photo album, the feed, the compose modal, and `styles.css`
entire. **TipTap has no native equivalent** — rich-text on native is a from-scratch problem, not a
port. The annotation overlay and `styles.css` *are* the design system; they are the parts with the
most design investment behind them.

**Portable in logic but not in form:** the dependency-free pure modules — `scaler.js`,
`drop-index.js`, `reorder.js`, `feedtime.js`, `annotation-place.js`, `step-adapter.js`,
`row-insert.js`, `tomake.js` — each unit-tested under `tests/js/`. The algorithms transfer; the
implementations do not.

## 5. Three fixable things the probe surfaced

All three live in the web app, not the shell, and all three are invisible today because a browser tab
is long-lived and usually online.

- **A shell lands on the login screen every cold launch.** Measured: a fresh process against the same
  persistent `WKWebsiteDataStore` reported `{"user": null}`. The wire shows why — `Set-Cookie` carries
  `HttpOnly; Path=/; SameSite=Lax` and **no `Expires`, no `Max-Age`**, i.e. a pure browser-session
  cookie discarded when the WebView process ends. Cause: `login_user(user)` in `auth.py` is called
  without `remember=True`, and nothing sets `session.permanent`.
- **Spectral is the only font NOT self-hosted.** Inter, Caveat and Kalam are bundled woff2 in
  `static/fonts/`; Spectral comes from `fonts.googleapis.com`, and that link survives the Vite build
  into `dist/index.html`. Offline, the primary serif falls back to Georgia.
  ⚠️ **Scope correction:** `design-decisions.md` states in two places that offline "only the *title*
  serif" falls back. That understates it — `index.html`'s own comment calls Spectral *"the single text
  serif … title, body, names, and the ledger's tabular figures + labels"*, and `--font-serif` has 25
  uses in `styles.css` against `--font-title`'s 3 (and `--font-title` is itself an alias of
  `--font-serif`). The whole content voice falls back, not the title alone.
  ⚠️ **The offline fallback was NOT cleanly measured.** Two attempts failed and were discarded: a
  `WKContentRuleList` with `unless-domain` did not match IP literals, and rewriting it to `if-domain`
  on the font hosts still did not intercept (an in-page check reported the CDN reachable, so the first
  "offline" run was invalid). Removing the stylesheet in-page was also inconclusive — WebKit keeps an
  already-loaded face warm. The fallback is a structural certainty (one remote source, not installed
  locally), not a measurement.
- **The camera `capture` attribute is unsupported in macOS WKWebView** (`"capture" in input` → false)
  and **untested on device**. Expected — it is a mobile attribute — but it is the mechanism the shell
  is supposed to provide, so it is worth knowing it was not exercised here.

## 6. What this concludes

- **The server data model and the web UI work are durable.** 7,423 lines of Python survive any client
  decision untouched, and the web UI was measured working intact inside a real WKWebView.
- **The shell is additive and cheap when it arrives.** It replaces one function's output server-side
  and one request shape client-side.
- **Server-side fetching is the one area not worth further investment** — the shell fixes it at a seam
  that barely moves.
- **The single caveat to the plan's premise:** the wrapper preserves the UI, but it does not make the
  app usable by touch. That is app work, decoupled from the shell decision, and it can be done at any
  point.

## What was NOT measured

Recorded so none of it is later mistaken for a tested result:

- iOS and Android WebView behaviour of any kind — no Xcode, no simulator, no emulator available.
- The offline font fallback (see the scope note above) — structural, not measured.
- Camera capture on a device.
- Any upload path. The probe deliberately performed **no writes** to images or recipes, to keep the
  repo byte-identical.
