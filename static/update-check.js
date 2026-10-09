"use strict";
// The reload bar (Andy, 9 Oct, decisions-4: variant 1 of :8003/reload-prompt/). Pure, so
// tests/js/update-check.test.js runs it in node. app.js owns the DOM half.
//
// ⚠️ WHY IT EXISTS. An open tab keeps the bundle it loaded. A restart reaches the server and not the
//    page already open, which is how revision 1's click-through ran a8ba985's client against a newer
//    server and newer data. The server now names its commit on every API answer (X-App-Commit), and
//    the page knows the commit that served it (the app-commit meta app.py writes into index.html).
//    When the two differ, a quiet bar at the top says the page has been updated.
// ⚠️ THE PAGE'S COMMIT IS THE SERVER'S AT THE MOMENT IT SERVED THE PAGE, NOT ONE BAKED INTO THE
//    BUNDLE. A bundle stamped at build time disagrees forever with a server restarted on a later
//    commit without a rebuild, and the bar would then come back after every reload.
// ⚠️ AND IT NEVER THROWS AWAY UNSAVED EDIT MODE CHANGES. With a change unsaved, the bar says to save
//    or cancel first and its Reload button is disabled, as the preview showed. The beforeunload
//    guard stands behind it either way.

export const COMMIT_HEADER = "X-App-Commit";
export const UPDATE_WORDS = "This page has been updated";
export const UPDATE_WAIT = "Reload after you save or cancel";

// The commit that served this page, or "" when nothing says (the Vite dev server writes no meta).
export function pageCommit(doc) {
  const m = doc && doc.querySelector ? doc.querySelector('meta[name="app-commit"]') : null;
  return m ? String(m.getAttribute("content") || "").trim() : "";
}

// One API answer heard. The state is { page, updated }, and a new object comes back only when
// something changed, so the caller can repaint on identity. A page that knows no commit of its own
// takes the first one it hears, so the check still works from the second answer on. An answer that
// names no commit (a server older than this feature, or one git could not read) changes nothing.
export function heardCommit(state, server) {
  const s = String(server || "").trim();
  if (!s) return state;
  if (!state.page) return { page: s, updated: false };
  const updated = s !== state.page;
  return updated === state.updated ? state : { page: state.page, updated };
}

// The bar, variant 1 as previewed. `waiting` is "Edit mode is open with a change unsaved".
export function updateBarHTML(waiting) {
  return `<div class="update-bar${waiting ? " is-waiting" : ""}" role="status">` +
    `<span class="update-bar-text">${UPDATE_WORDS}</span>` +
    (waiting ? `<span class="update-wait">${UPDATE_WAIT}</span>` : "") +
    `<button type="button" class="btn sm" data-update-reload${waiting ? " disabled" : ""}>Reload</button>` +
    `</div>`;
}

// A fetch that hears every answer and hands back the response untouched. The check is never allowed
// to break a request, so a throw inside `onCommit` is swallowed.
export function hearingFetch(realFetch, onCommit) {
  return async (...args) => {
    const res = await realFetch(...args);
    try {
      onCommit(res && res.headers ? res.headers.get(COMMIT_HEADER) : null);
    } catch (e) { /* the bar is a convenience and a request is not */ }
    return res;
  };
}
