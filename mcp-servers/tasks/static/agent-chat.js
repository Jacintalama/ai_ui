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

  // Earlier conversations open from the header rather than living under the
  // composer, so the input keeps the bottom of the panel. Opening one closes
  // the list again: you asked for that conversation, not for the list.
  var historyToggle = document.getElementById("ap-history-toggle");
  var historyPanel = document.getElementById("ap-history");

  function showHistory(open) {
    if (!historyPanel || !historyToggle) return;
    historyPanel.hidden = !open;
    historyToggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  if (historyToggle) {
    historyToggle.addEventListener("click", function () {
      showHistory(historyPanel.hidden);
    });
  }

  document.body.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest(".achatopen")) { showHistory(false); }
  });
})();
