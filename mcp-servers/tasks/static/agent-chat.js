/* The small amount of client the panel needs.
   Everything else is server-rendered, on purpose: there is then no browser-side
   model of the conversation that can drift from the server's. */
(function () {
  "use strict";

  // Auth: HTMX requests carry the Open WebUI login token as a bearer header.
  // The SSE stream cannot, because EventSource cannot set headers, so that one
  // relies on the same-origin cookie instead.
  document.body.addEventListener("htmx:configRequest", function (e) {
    if (e.detail.path && e.detail.path.indexOf("/tasks/agents/chat") !== 0) return;
    var token = localStorage.getItem("token");
    if (token) { e.detail.headers["Authorization"] = "Bearer " + token; }
  });

  function thread() { return document.getElementById("agent-thread"); }

  function toBottom() {
    var el = thread();
    if (el) { el.scrollTop = el.scrollHeight; }
  }

  document.body.addEventListener("htmx:afterSwap", toBottom);
  document.body.addEventListener("htmx:sseMessage", toBottom);

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
    toBottom();
  });
})();
