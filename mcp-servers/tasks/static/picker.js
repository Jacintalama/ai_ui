/* IO Element Picker — iframe-side script.
 *
 * Lifecycle (postMessage protocol — both directions use window.parent):
 *
 *   on load:                      iframe -> parent  io.picker.ready
 *   parent -> iframe:             io.picker.activate
 *   parent -> iframe:             io.picker.deactivate
 *   iframe -> parent (on click):  io.picker.selected   (with payload)
 *   iframe -> parent (on ESC):    io.picker.cancelled
 *
 * State: "inert" (default) -> "listening" -> "inert".
 */
(function () {
  "use strict";

  const TARGET = window.parent;
  if (!TARGET || TARGET === window) return;  // not in an iframe — no-op

  function post(msg) {
    try {
      TARGET.postMessage(msg, "*");
    } catch (e) {
      // Non-cloneable payloads or detached parents will land here. Log so
      // future Tasks 3-5 payload regressions are observable in DevTools.
      try { console.warn("[io.picker] postMessage failed:", e, msg); } catch (_) {}
    }
  }

  // Announce readiness so the parent knows it can send activate.
  post({ type: "io.picker.ready" });

  // Wire the activate/deactivate handlers in later tasks.
})();
