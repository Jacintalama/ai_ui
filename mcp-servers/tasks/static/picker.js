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
  if (!TARGET || TARGET === window) return;

  const OVERLAY_ID = "__io_picker_overlay";
  const LABEL_ID = "__io_picker_label";
  const Z_TOP = 2147483647;

  let state = "inert";
  let $overlay = null;
  let $label = null;
  let lastTarget = null;
  let altDown = false;         // updated by onKey (keydown/keyup) and by mouse
                                // events' native altKey field. Mouse-driven
                                // updates self-heal if a keyup is missed.
  let prevBodyTabIndex = null;  // restored on deactivate
  let prevActive = null;       // restored on deactivate

  // Hardened post() from Task 2 — DO NOT regress this.
  function post(msg) {
    try {
      TARGET.postMessage(msg, "*");
    } catch (e) {
      try { console.warn("[io.picker] postMessage failed:", e, msg); } catch (_) {}
    }
  }

  function ensureOverlay() {
    if ($overlay) return;
    $overlay = document.createElement("div");
    $overlay.id = OVERLAY_ID;
    Object.assign($overlay.style, {
      position: "fixed",
      pointerEvents: "none",
      outline: "2px solid #4f8df0",
      outlineOffset: "0",
      borderRadius: "4px",
      zIndex: String(Z_TOP),
      display: "none",
      left: "0px", top: "0px", width: "0px", height: "0px",
    });
    document.body.appendChild($overlay);

    $label = document.createElement("div");
    $label.id = LABEL_ID;
    Object.assign($label.style, {
      position: "fixed",
      pointerEvents: "none",
      zIndex: String(Z_TOP),
      background: "#4f8df0",
      color: "#fff",
      font: "11px ui-monospace, Menlo, monospace",
      padding: "2px 6px",
      borderRadius: "4px",
      display: "none",
    });
    document.body.appendChild($label);
  }

  function teardownOverlay() {
    if ($overlay) { $overlay.remove(); $overlay = null; }
    if ($label) { $label.remove(); $label = null; }
    lastTarget = null;
  }

  function pickableTarget(el) {
    if (!el) return null;
    if (altDown && el.parentElement && el.parentElement !== document.documentElement && el.parentElement !== document.body) {
      el = el.parentElement;
    }
    if (el === document.documentElement || el === document.body) return null;
    if (el.id === OVERLAY_ID || el.id === LABEL_ID) return null;
    return el;
  }

  function buildSelector(el) {
    // Stable-enough selector for chip labels and prompt context. v1 ships
    // this instead of vendoring @medv/finder.
    if (!el) return "";
    const parts = [];
    let cur = el;
    while (cur && cur !== document.body && parts.length < 4) {
      const tag = cur.tagName.toLowerCase();
      const id = cur.id ? "#" + cur.id : "";
      const classStr = typeof cur.className === "string"
        ? cur.className
        : (cur.className && cur.className.baseVal) || "";
      const trimmed = classStr.trim();
      const cls = trimmed
        ? "." + trimmed.split(/\s+/).slice(0, 2).join(".")
        : "";
      let nth = "";
      if (!id && cur.parentElement) {
        const siblings = Array.from(cur.parentElement.children)
          .filter((c) => c.tagName === cur.tagName);
        if (siblings.length > 1) nth = `:nth-of-type(${siblings.indexOf(cur) + 1})`;
      }
      parts.unshift(tag + id + cls + nth);
      if (id) break;
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  }

  function onMouseMove(e) {
    if (state !== "listening") return;
    // Mouse events expose altKey natively, which is more reliable than tracking
    // keydown/keyup state (esp. when Playwright's click(modifiers=["Alt"]) only
    // synthesizes the modifier on the mouse event without a real keydown).
    if (typeof e.altKey === "boolean") altDown = e.altKey;
    const el = pickableTarget(document.elementFromPoint(e.clientX, e.clientY));
    if (!el) {
      $overlay.style.display = "none";
      $label.style.display = "none";
      lastTarget = null;
      return;
    }
    if (el === lastTarget) return;
    lastTarget = el;
    const r = el.getBoundingClientRect();
    Object.assign($overlay.style, {
      display: "block",
      left: r.left + "px",
      top: r.top + "px",
      width: r.width + "px",
      height: r.height + "px",
    });
    $label.textContent = buildSelector(el);
    $label.style.display = "block";
    $label.style.left = r.left + "px";
    $label.style.top = Math.max(0, r.top - 18) + "px";
  }

  const STYLE_KEYS = [
    "color", "backgroundColor", "padding", "margin",
    "fontSize", "fontFamily", "display", "borderRadius",
    "width", "height",
  ];

  function pickStyles(el) {
    const cs = window.getComputedStyle(el);
    const out = {};
    for (const k of STYLE_KEYS) out[k] = cs[k];
    return out;
  }

  function truncate(s, n) {
    return s.length <= n ? s : s.slice(0, n);
  }

  function buildPayload(el) {
    const r = el.getBoundingClientRect();
    const attrs = {};
    if (el.id) attrs.id = el.id;
    if (el.className && typeof el.className === "string") attrs.class = el.className;
    const selector = buildSelector(el);
    return {
      type: "io.picker.selected",
      selector: truncate(selector || "", 400),
      tag: el.tagName,
      attrs,
      outerHtml: truncate(el.outerHTML || "", 2048),
      styles: pickStyles(el),
      rect: { x: r.x, y: r.y, w: r.width, h: r.height },
      url: location.href,
      pickedAt: Date.now(),
    };
  }

  function suppress(e) {
    if (state !== "listening") return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }

  function onClick(e) {
    if (state !== "listening") return;
    e.preventDefault();
    e.stopImmediatePropagation();
    // Honor Alt held at click time (synthesized modifier on the click event
    // works even when no separate keydown fires).
    if (typeof e.altKey === "boolean") altDown = e.altKey;
    const el = pickableTarget(document.elementFromPoint(e.clientX, e.clientY));
    if (!el) return;
    post(buildPayload(el));
    deactivate();
  }

  function onKey(e) {
    if (state !== "listening") return;
    if (e.type === "keydown" && e.key === "Escape") {
      e.preventDefault();
      e.stopImmediatePropagation();
      post({ type: "io.picker.cancelled" });
      deactivate();
      return;
    }
    if (e.key === "Alt") {
      altDown = e.type === "keydown";
      // Repaint hover so outline jumps to parent immediately.
      if (lastTarget) {
        const r = lastTarget.getBoundingClientRect();
        const synth = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
        onMouseMove(synth);
      }
    }
  }

  function activate() {
    if (state === "listening") return;
    state = "listening";
    ensureOverlay();
    document.addEventListener("mousemove", onMouseMove, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("mousedown", suppress, true);
    document.addEventListener("mouseup", suppress, true);
    document.addEventListener("submit", suppress, true);
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("keyup", onKey, true);
    document.body.style.cursor = "crosshair";
    // Make body focusable so it can receive keyboard events even when no
    // input/button has focus. Restored on deactivate.
    prevBodyTabIndex = document.body.hasAttribute("tabindex")
      ? document.body.getAttribute("tabindex")
      : null;
    document.body.setAttribute("tabindex", "-1");
    try { prevActive = document.activeElement; } catch (_) { prevActive = null; }
    try { document.body.focus({ preventScroll: true }); } catch (_) {}
  }

  function deactivate() {
    if (state === "inert") return;
    state = "inert";
    altDown = false;  // reset so a stuck Alt doesn't carry across activations
    document.removeEventListener("mousemove", onMouseMove, true);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("mousedown", suppress, true);
    document.removeEventListener("mouseup", suppress, true);
    document.removeEventListener("submit", suppress, true);
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("keyup", onKey, true);
    document.body.style.cursor = "";
    if (prevBodyTabIndex === null) {
      document.body.removeAttribute("tabindex");
    } else {
      document.body.setAttribute("tabindex", prevBodyTabIndex);
    }
    prevBodyTabIndex = null;
    // Restore the previously focused element (e.g., the input the user was
    // typing in before activating the picker). Guard against the element
    // having been removed from the DOM during the picking session.
    try {
      if (prevActive && typeof prevActive.focus === "function" && document.contains(prevActive)) {
        prevActive.focus({ preventScroll: true });
      }
    } catch (_) {}
    prevActive = null;
    teardownOverlay();
  }

  window.addEventListener("message", (e) => {
    const m = e.data || {};
    if (m.type === "io.picker.activate") activate();
    else if (m.type === "io.picker.deactivate") deactivate();
  });

  post({ type: "io.picker.ready" });
})();
