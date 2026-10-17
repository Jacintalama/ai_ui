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

  //: Every conversation on the page. The agents page has one, #agent-thread;
  //: the office has a window per conversation (office/js/dock.js), each an
  //: .ap-thread of its own, so everything here works per thread and an
  //: answer landing in one window never scrolls or retypes another.
  function threads() { return document.querySelectorAll(".ap-thread"); }
  function thread() { return document.getElementById("agent-thread") || threads()[0] || null; }

  //: Has a thread been drawn once? A replayed conversation jumps to its
  //: end; everything after that glides, the way a messenger follows a new
  //: message in, unless the person has asked for less motion. Kept on the
  //: element, since each window settles on its own.
  function settled(el) { return !!(el && el.getAttribute("data-settled")); }
  function toBottom(el) {
    el = el || thread();
    if (!el) return;
    var reduce = false;
    try { reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
    catch (e) { /* no media queries: jump */ }
    if (settled(el) && !reduce && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    } else {
      el.scrollTop = el.scrollHeight;
    }
    el.setAttribute("data-settled", "1");
  }

  //: A run of messages from one agent shares one avatar and one name, the
  //: way a messenger draws several messages from one person in a row.
  //: Decided here, from data-agent on each row, because the server emits
  //: each answer on its own as it lands and cannot know what will follow
  //: it. A card (an approval, a job plan) ends a run: it has its own box.
  function groupBubbles(el) {
    if (!el) return;
    function plain(n) {
      return !!n && n.classList.contains("am") && n.classList.contains("agent") &&
        !n.classList.contains("awaiting") && !n.classList.contains("ajob");
    }
    // Siblings, wherever the row sits: a replayed answer is a child of its
    // turn, a live one lands in the turn's .aturn-body, and either way the
    // run is the rows next to each other.
    el.querySelectorAll(".am.agent").forEach(function (row) {
      row.classList.remove("g-first", "g-mid", "g-last");
      if (!plain(row)) return;
      var who = row.getAttribute("data-agent");
      var prev = row.previousElementSibling, next = row.nextElementSibling;
      var up = plain(prev) && prev.getAttribute("data-agent") === who;
      var down = plain(next) && next.getAttribute("data-agent") === who;
      if (up && down) row.classList.add("g-mid");
      else if (down) row.classList.add("g-first");
      else if (up) row.classList.add("g-last");
    });
  }

  // The page ships with the invitation already in the thread, and messages are
  // appended after it, so without this "Pick who is in the room, then ask."
  // sits above a conversation that has plainly already started. New chat puts
  // it back by replacing the whole thread, which is the one time it belongs.
  function dropInvitation(el) {
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

  function renderAll(el) {
    if (!el) return;
    var texts = el.querySelectorAll(".atext.md");
    for (var i = 0; i < texts.length; i++) { renderMarkdown(texts[i]); }
  }

  //: When a message was said, in the reader's own clock. The server stores
  //: the instant (data-at, agent_chat_render._when); the browser puts a
  //: <time> beside the bubble that shows on hover, the way a messenger
  //: does, and rewrites each day line as Today, Yesterday or the weekday.
  function sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() &&
      a.getDate() === b.getDate();
  }
  function clock(d) {
    try { return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
    catch (e) { return d.getHours() + ":" + ("0" + d.getMinutes()).slice(-2); }
  }
  function dayWords(d) {
    var now = new Date(), yesterday = new Date(now.getTime() - 86400000);
    if (sameDay(d, now)) return "Today";
    if (sameDay(d, yesterday)) return "Yesterday";
    try {
      return d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
    } catch (e) { return d.toDateString(); }
  }
  function stampTimes(el) {
    if (!el) return;
    el.querySelectorAll(".am[data-at]:not([data-stamped])").forEach(function (row) {
      var d = new Date(row.getAttribute("data-at"));
      row.setAttribute("data-stamped", "1");
      if (isNaN(d.getTime())) return;
      var t = document.createElement("time");
      t.className = "awhen";
      t.setAttribute("datetime", row.getAttribute("data-at"));
      t.textContent = (sameDay(d, new Date()) ? "" : dayWords(d) + " ") + clock(d);
      // Beside the bubble, on the side the row has room: before a message
      // of yours (it sits on the right), after an agent's (on the left).
      if (row.classList.contains("user")) row.insertBefore(t, row.firstChild);
      else row.appendChild(t);
    });
    el.querySelectorAll(".aday time:not([data-stamped])").forEach(function (t) {
      t.setAttribute("data-stamped", "1");
      var parts = (t.getAttribute("datetime") || "").split("-");
      if (parts.length !== 3) return;
      var d = new Date(+parts[0], +parts[1] - 1, +parts[2]);
      if (!isNaN(d.getTime())) t.textContent = dayWords(d);
    });
  }

  //: An answer arrives whole (the round is not streamed), so it used to
  //: pop into the thread in one piece while the robot on the floor beside
  //: it moved its mouth for seconds. Now a LIVE answer is typed in: its
  //: text is revealed word by word over the same time the floor gives the
  //: mouth, max(1500, min(5000, chars * 40)) ms (office.js speaking), so
  //: the bubble and the robot speak together and one agent's answer is
  //: visibly finishing before the next agent's dots appear. A replayed
  //: conversation shows at once, and so does a reader who asked for less
  //: motion. Markdown is rendered first and the reveal walks its text
  //: nodes, so emphasis, lists and links come up in place.
  function speakMs(chars) { return Math.max(1500, Math.min(5000, chars * 40)); }
  //: One answer at a time. A meeting's answers can land faster than they
  //: are read out (the next agent's turn starts the moment the last one's
  //: lands), and typing them all at once had three bubbles growing
  //: together. Each waits, out of sight, for the one before it to finish.
  var TYPING_QUEUE = [], TYPING_NOW = false, TYPING_WATCH = null;
  //: The reveal in flight, so it can be finished from outside: when the
  //: tab is hidden (rAF stops there, and an answer stuck at its first
  //: word with a caret was what the person came back to), or when
  //: anything goes wrong mid-reveal. Nothing may wedge the queue: a stuck
  //: TYPING_NOW hid every later answer for good (seen 2026-10-17).
  var REVEALING = null;
  function finishReveal() {
    var r = REVEALING;
    if (!r) return;
    REVEALING = null;
    try { r.finish(); } catch (e) { /* the words are shown below either way */ }
  }
  function typeNext() {
    if (TYPING_NOW) return;
    var text = TYPING_QUEUE.shift();
    if (!text) return;
    var row = text.closest(".am");
    if (row) row.hidden = false;
    TYPING_NOW = true;
    clearTimeout(TYPING_WATCH);
    // The watchdog: however the reveal ends, the queue moves on.
    TYPING_WATCH = setTimeout(function () { finishReveal(); }, 5000 + 2000);
    function done() {
      clearTimeout(TYPING_WATCH);
      REVEALING = null;
      TYPING_NOW = false;
      typeNext();
    }
    try { typeIn(text, done); }
    catch (e) { showAll(text); done(); }
  }
  //: Every word of an answer, at once.
  function showAll(el) {
    el.querySelectorAll(".aw-wait").forEach(function (w) { w.classList.remove("aw-wait"); });
    el.classList.remove("typing");
  }
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) finishReveal();
  });
  //: A caret in a window nobody can see types for nobody: an answer that
  //: lands in a hidden window (the office's dock, minimised) is shown
  //: whole, so it is there the moment the window opens.
  function unseen(el) {
    return !el || !el.isConnected || el.offsetParent === null;
  }
  function typeIn(el, done) {
    // Every word in its own span, shown in order. The words are all in the
    // document from the first frame, so what the eye sees arriving is
    // already there for anything reading the thread. The ones still to come
    // take no room: fading them in left a bubble at its full height, blank,
    // with a caret at the bottom, which read as an answer stuck mid-typing
    // after it had already landed (screenshot, 2026-10-16). The bubble
    // grows as the words land, the way a typed message does.
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    var texts = [], n;
    while ((n = walker.nextNode())) texts.push(n);
    var words = [], chars = 0;
    texts.forEach(function (node) {
      var parts = node.nodeValue.split(/(\s+)/), frag = document.createDocumentFragment();
      parts.forEach(function (part) {
        if (!part) return;
        if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
        var w = document.createElement("span");
        w.className = "aw aw-wait"; w.textContent = part;
        frag.appendChild(w); words.push(w); chars += part.length;
      });
      node.parentNode.replaceChild(frag, node);
    });
    if (!words.length) { el.classList.remove("typing"); if (done) done(); return; }
    var ms = speakMs(chars), start = performance.now(), shown = 0, over = false;
    var box = el.closest(".ap-thread");
    function end() {
      if (over) return;
      over = true;
      clearInterval(ticker);
      el.classList.remove("typing");
      if (done) done();
    }
    function frame(now) {
      if (over) return;
      var gone = (now || performance.now()) - start;
      var want = (gone >= ms || unseen(box) || document.hidden) ? words.length
               : Math.floor(words.length * gone / ms);
      while (shown < want) { words[shown].classList.remove("aw-wait"); shown++; }
      toBottom(box);
      if (shown < words.length) requestAnimationFrame(frame);
      else end();
    }
    // A clock that does not stop with the tab: rAF pauses in a background
    // tab, and this keeps the reveal moving (slowly) and ends it on time.
    var ticker = setInterval(function () { frame(); }, 250);
    REVEALING = { finish: function () {
      while (shown < words.length) { words[shown].classList.remove("aw-wait"); shown++; }
      end();
    } };
    el.classList.add("typing");
    requestAnimationFrame(frame);
  }
  function typeNewAnswers(el) {
    if (!el || !settled(el)) return;
    var reduce = false;
    try { reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
    catch (e) { /* no media queries */ }
    el.querySelectorAll(".am.agent:not([data-typed]) .atext").forEach(function (text) {
      var row = text.closest(".am");
      row.setAttribute("data-typed", "1");
      if (reduce || unseen(el) || row.classList.contains("awaiting") || row.classList.contains("ajob")) return;
      // Its turn comes when the answer before it has been said.
      if (TYPING_NOW || TYPING_QUEUE.length) row.hidden = true;
      TYPING_QUEUE.push(text);
    });
    typeNext();
  }

  function settleOne(el) {
    dropInvitation(el);
    renderAll(el);
    groupBubbles(el);
    stampTimes(el);
    // Everything on screen at the first draw is history, not arriving.
    if (!settled(el)) {
      el.querySelectorAll(".am.agent").forEach(function (r) {
        r.setAttribute("data-typed", "1");
      });
    }
    typeNewAnswers(el);
    toBottom(el);
  }
  //: Settle the thread an event landed in, or every thread when the event
  //: cannot say (an out-of-band swap names its own target, not the thread).
  function settle(ev) {
    var target = ev && ev.detail && (ev.detail.target || ev.detail.elt);
    var one = target && target.closest ? target.closest(".ap-thread") : null;
    if (one && !(ev && ev.detail && ev.detail.xhr && ev.detail.xhr.responseText &&
                 ev.detail.xhr.responseText.indexOf("hx-swap-oob") !== -1)) {
      settleOne(one);
      return;
    }
    threads().forEach(settleOne);
  }
  window.aiuiSettleChat = function (el) { if (el) settleOne(el); else threads().forEach(settleOne); };

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
    // The thread the failed send was aimed at, where the person is looking.
    var el = null, elt = detail.elt;
    var form = elt && elt.closest ? elt.closest("form") : null;
    var sel = form && form.getAttribute("hx-target");
    if (sel) { try { el = document.querySelector(sel); } catch (x) { el = null; } }
    if (!el && elt && elt.closest) el = elt.closest(".ap-thread");
    if (!el) el = thread();
    if (!el) return;
    el.insertAdjacentHTML("beforeend",
      '<div class="am note">' + said + "</div>");
    settleOne(el);
  });

  // When the round closes, stop the element listening. The SSE extension leaves
  // sse-connect in place after closing, and a live attribute is an invitation
  // for a later pass to reconnect and re-run a round we have already paid for.
  document.body.addEventListener("htmx:sseClose", function () {
    var open = document.querySelectorAll(".astream[sse-connect]");
    for (var i = 0; i < open.length; i++) {
      open[i].removeAttribute("sse-connect");
    }
    // The status line lives in the turn's own .aturn-status row now (see
    // into_turn/turn_status in agent_chat_render.py), not in .awork: .awork
    // is a sink that out-of-band content is swapped OUT OF before it ever
    // lands there, so it is always empty and clearing it clears nothing.
    // The server clears .aturn-status itself with an empty "working" event
    // at the end of every round, but that event never fires when the
    // connection closes before one: a drop and reconnect lands on the
    // stream route with the tail no longer "user", which closes right away
    // with no round and no clearing event, and "X is working..." would
    // otherwise stay pinned on that turn until the page is reloaded.
    document.querySelectorAll("#agent-thread .aturn-status, .ap-thread .aturn-status")
      .forEach(function (el) { el.innerHTML = ""; });
    threads().forEach(settleOne);
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
  // No Escape handler here. agents.html has the page's one Escape handler,
  // which closes only the top-most layer, and for this dialog it presses
  // Cancel, so focus comes back to Clear through showClear above.

  // Drag the divider to trade width between the conversation and the agents.
  // The width belongs to the person, not the session, so it is remembered
  // per browser. localStorage can throw outright in a private window, hence
  // the guards: a panel that will not open because a preference could not be
  // read would be a poor trade for remembering a width.
  var WIDTH_KEY = "aiui-agents-width";
  // 2026-10-08: the ceiling came down from 640 to 420, which also RESCUES a
  // width already saved above it. restoreWidth puts the stored value through
  // applyWidth, and applyWidth clamps, so a column dragged out to 620 in an
  // earlier session comes back to 420 on the next load without anybody
  // having to clear their storage. The office was reported as cramped for
  // exactly that reason.
  var MIN_AGENTS = 240;
  var MAX_AGENTS = 420;
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
