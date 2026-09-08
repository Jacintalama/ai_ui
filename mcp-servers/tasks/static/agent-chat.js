/* The small amount of client the panel needs.
   Everything else is server-rendered, on purpose: there is then no browser-side
   model of the conversation that can drift from the server's. */
(function () {
  "use strict";

  var PANEL = "/tasks/agents/chat";

  // Auth: HTMX requests carry the Open WebUI login token as a bearer header.
  // The SSE stream cannot, because EventSource cannot set headers, so that one
  // relies on the same-origin cookie instead.
  document.body.addEventListener("htmx:configRequest", function (e) {
    if (e.detail.path && e.detail.path.indexOf(PANEL) !== 0) return;
    var token = localStorage.getItem("token");
    if (token) { e.detail.headers["Authorization"] = "Bearer " + token; }
  });

  function thread() { return document.getElementById("agent-thread"); }

  function toBottom() {
    var el = thread();
    if (el) { el.scrollTop = el.scrollHeight; }
  }

  // The page ships with the invitation already in the thread, and messages are
  // appended after it, so without this "Pick who is in the room, then ask."
  // sits above a conversation that has plainly already started. New chat puts
  // it back by replacing the whole thread, which is the one time it belongs.
  function dropInvitation() {
    var el = thread();
    if (!el) return;
    var invitations = el.querySelectorAll(".aempty");
    if (!invitations.length) return;
    if (el.children.length <= invitations.length) return;
    for (var i = 0; i < invitations.length; i++) {
      invitations[i].remove();
    }
  }

  // Answers are markdown. Without this a person reads the asterisks and the
  // hashes instead of the emphasis and the headings. marked does not sanitize
  // and this is model output, so DOMPurify runs on the result before it is
  // ever assigned. Bubbles arrive whole here, unlike the Fusion page where
  // tokens stream into one element, so each is rendered as it lands.
  function renderMarkdown(el) {
    if (!el || el.classList.contains("done")) return;
    if (typeof marked === "undefined" || typeof DOMPurify === "undefined") return;
    el.innerHTML = DOMPurify.sanitize(marked.parse(el.textContent));
    el.classList.add("done");
  }

  function renderAll() {
    var el = thread();
    if (!el) return;
    var texts = el.querySelectorAll(".atext.md");
    for (var i = 0; i < texts.length; i++) { renderMarkdown(texts[i]); }
  }

  function settle() {
    dropInvitation();
    renderAll();
    toBottom();
  }

  document.body.addEventListener("htmx:afterSwap", settle);
  document.body.addEventListener("htmx:sseMessage", settle);

  // A request that fails swaps nothing, and the composer clears itself either
  // way, so without this the message vanishes and the screen does not change:
  // an expired token, a refusal or a backend that is down all look exactly
  // like nothing happening.
  document.body.addEventListener("htmx:responseError", function (e) {
    var detail = e.detail || {};
    var path = (detail.requestConfig && detail.requestConfig.path)
      || (detail.pathInfo && detail.pathInfo.requestPath) || "";
    if (path.indexOf(PANEL) !== 0) return;
    var status = detail.xhr ? detail.xhr.status : 0;
    var said = (status === 401 || status === 403)
      ? "Your sign-in has expired. Reload the page and sign in again."
      : "That did not go through. Try again in a moment.";
    var el = thread();
    if (!el) return;
    el.insertAdjacentHTML("beforeend",
      '<div class="am note">' + said + "</div>");
    settle();
  });

  // When the round closes, stop the element listening. The SSE extension leaves
  // sse-connect in place after closing, and a live attribute is an invitation
  // for a later pass to reconnect and re-run a round we have already paid for.
  document.body.addEventListener("htmx:sseClose", function () {
    var open = document.querySelectorAll(".astream[sse-connect]");
    for (var i = 0; i < open.length; i++) {
      open[i].removeAttribute("sse-connect");
    }
    var work = document.querySelector(".awork");
    if (work) { work.innerHTML = ""; }
    settle();
  });

  // Clearing is the only destructive thing in the panel, so it is the only
  // thing that asks first. The page's own overlay, not the browser's confirm
  // box: that dialog cannot be styled and looks like a warning from 2005.
  var clearBtn = document.getElementById("ap-clear");
  var overlay = document.getElementById("ap-clear-overlay");
  var cancelBtn = document.getElementById("ap-clear-cancel");
  var confirmBtn = document.getElementById("ap-clear-confirm");

  function showClear(open) {
    if (!overlay) return;
    overlay.hidden = !open;
    if (open && cancelBtn) { cancelBtn.focus(); }
    else if (clearBtn) { clearBtn.focus(); }
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", function () { showClear(true); });
  }
  if (cancelBtn) {
    cancelBtn.addEventListener("click", function () { showClear(false); });
  }
  if (overlay) {
    // Clicking the backdrop cancels. Clicking the dialog itself must not.
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) { showClear(false); }
    });
  }
  if (confirmBtn) {
    // htmx does the post; this only takes the dialog away once it lands, so
    // a failed clear leaves the dialog up rather than pretending it worked.
    confirmBtn.addEventListener("htmx:afterRequest", function (e) {
      if (e.detail && e.detail.successful) { showClear(false); }
    });
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && overlay && !overlay.hidden) { showClear(false); }
  });

  // Drag the divider to trade width between the conversation and the agents.
  // The width belongs to the person, not the session, so it is remembered
  // per browser. localStorage can throw outright in a private window, hence
  // the guards: a panel that will not open because a preference could not be
  // read would be a poor trade for remembering a width.
  var WIDTH_KEY = "aiui-agents-width";
  var MIN_AGENTS = 260;
  var MAX_AGENTS = 640;
  var layout = document.querySelector(".agents-layout");
  var grip = document.getElementById("ap-resize");

  function clampWidth(px) {
    return Math.max(MIN_AGENTS, Math.min(MAX_AGENTS, Math.round(px)));
  }

  function applyWidth(px, remember) {
    if (!layout) return;
    var width = clampWidth(px);
    layout.style.setProperty("--agents-width", width + "px");
    if (grip) { grip.setAttribute("aria-valuenow", String(width)); }
    if (!remember) return;
    try { localStorage.setItem(WIDTH_KEY, String(width)); } catch (e) {}
  }

  (function restoreWidth() {
    var saved = null;
    try { saved = localStorage.getItem(WIDTH_KEY); } catch (e) {}
    var px = parseInt(saved, 10);
    if (px > 0) { applyWidth(px, false); }
  })();

  if (grip && layout) {
    grip.addEventListener("pointerdown", function (e) {
      e.preventDefault();
      // Pointer capture, so the drag survives the cursor leaving the handle
      // and crossing the iframe's own edges.
      grip.setPointerCapture(e.pointerId);
      layout.classList.add("ap-dragging");
    });

    grip.addEventListener("pointermove", function (e) {
      if (!layout.classList.contains("ap-dragging")) return;
      // The agents column is the right one, so its width is whatever is left
      // between the pointer and the layout's right edge.
      applyWidth(layout.getBoundingClientRect().right - e.clientX, false);
    });

    function stop(e) {
      if (!layout.classList.contains("ap-dragging")) return;
      layout.classList.remove("ap-dragging");
      try { grip.releasePointerCapture(e.pointerId); } catch (err) {}
      // Written once, at the end, rather than on every pointermove.
      applyWidth(layout.getBoundingClientRect().right - e.clientX, true);
    }
    grip.addEventListener("pointerup", stop);
    grip.addEventListener("pointercancel", stop);

    // A drag handle nobody can reach without a mouse is not a control.
    grip.addEventListener("keydown", function (e) {
      var step = e.shiftKey ? 48 : 16;
      var current = grip.getBoundingClientRect().right;
      var now = layout.getBoundingClientRect().right - current;
      if (e.key === "ArrowLeft") { applyWidth(now + step, true); }
      else if (e.key === "ArrowRight") { applyWidth(now - step, true); }
      else { return; }
      e.preventDefault();
    });

    // Double click resets, because a dragged panel is easy to lose.
    grip.addEventListener("dblclick", function () { applyWidth(340, true); });
  }
})();
