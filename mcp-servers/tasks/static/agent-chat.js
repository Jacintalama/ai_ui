/* The small amount of client the panel needs.
   Everything else is server-rendered, on purpose: there is then no browser-side
   model of the conversation that can drift from the server's. */
(function () {
  "use strict";

  var PANEL = "/tasks/agents/chat";

  // Auth: HTMX requests carry the Open WebUI login token as a bearer header.
  // The SSE stream cannot, because EventSource cannot set headers, so that one
  // relies on the same-origin cookie instead.
  // An empty box is not a message. Caught ahead of htmx (capture, on the
  // document) so nothing is posted and nothing is refused: Send or Enter
  // on an empty box used to post "message=" and draw "That did not go
  // through" (seen on the live office, 2026-10-26).
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || !form.classList || !form.classList.contains("ap-composer")) return;
    var input = form.querySelector('input[name="message"]');
    if (!input || input.value.trim()) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    try { input.focus(); } catch (x) { /* fine */ }
  }, true);

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
        r.setAttribute("data-heard", "1");
      });
    }
    sayNewAnswers(el);
    typeNewAnswers(el);
    toBottom(el);
  }
  // --- Talking to the agents (2026-10-28) ------------------------------
  //: Talk, and the agents answer out loud. The words come from the
  //: browser's own speech recognition: Open WebUI's is Whisper inside its
  //: container, which already sits at 615 MB of its 1 GB, and loading a
  //: model there per message risked the whole site. A browser without it
  //: (Firefox) gets no Talk button rather than one that fails. The answers
  //: are read by the same ElevenLabs voice as Read Aloud in the main chat,
  //: through Open WebUI's /api/v1/audio/speech, so the key never reaches
  //: the page. Only answers to a message that was SPOKEN are read; typing
  //: again turns it off, so nobody is talked at who did not ask.
  var Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  //: About 600 ElevenLabs credits at most per answer (0.5 a character on
  //: eleven_flash_v2_5); a longer answer is read up to a sentence end.
  var SPEAK_MAX_CHARS = 1200;
  var LISTENING = null;        // { form, rec, said } while the mic is open
  var VOICE_SEND = null;       // the form being sent by voice right now
  var SAYING = [];             // answers still to read, in order
  var PLAYING = null;          // the Audio being read now
  var VOICE_ID = null;         // a promise of the site's read-aloud voice
  var MIC_SVG = '<svg class="ap-mic-icon" viewBox="0 0 24 24" width="14" height="14" ' +
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true" focusable="false">' +
    '<rect x="9" y="3" width="6" height="11" rx="3"/>' +
    '<path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/></svg>';

  function authHeaders() {
    var h = { "Content-Type": "application/json" };
    var token = null;
    try { token = localStorage.getItem("token"); } catch (e) { /* none */ }
    if (token) h["Authorization"] = "Bearer " + token;
    return h;
  }

  //: The voice Read Aloud uses, from the site's own config. Open WebUI's
  //: speech endpoint needs it named; its own page sends it the same way.
  function voiceId() {
    if (!VOICE_ID) {
      VOICE_ID = fetch("/api/config", { headers: authHeaders() })
        .then(function (r) { return r.ok ? r.json() : {}; })
        .then(function (c) {
          return (c && c.audio && c.audio.tts && c.audio.tts.voice) || "";
        })
        .catch(function () { return ""; });
    }
    return VOICE_ID;
  }

  function threadOf(form) {
    var sel = form && form.getAttribute("hx-target"), el = null;
    if (sel) { try { el = document.querySelector(sel); } catch (x) { el = null; } }
    if (!el && form) {
      var box = form.closest(".cw, .agent-panel, aside, section");
      el = box ? box.querySelector(".ap-thread") : null;
    }
    return el || thread();
  }

  function micOf(form) { return form ? form.querySelector(".ap-mic") : null; }

  function showMic(form) {
    var b = micOf(form);
    if (!b) return;
    var listening = !!(LISTENING && LISTENING.form === form);
    var talking = !listening && !!(PLAYING || SAYING.length) &&
      threadOf(form) && threadOf(form).getAttribute("data-voice") === "1";
    // Short labels: the office's chat window is 300px wide, and "Done
    // talking" squeezed the message box to a third of it. The full
    // meaning is in the accessible name.
    // While an answer is being read, Talk still talks: it cuts the reading
    // off and listens, the way you interrupt somebody. A press that only
    // silenced it left the next sentence unheard (live, 2026-10-28).
    var label = b.querySelector(".ap-mic-label");
    if (label) label.textContent = listening ? "Done" : "Talk";
    b.setAttribute("aria-label", listening ? "Stop listening and send"
      : talking ? "Stop the reading and talk" : "Talk instead of typing");
    b.setAttribute("aria-pressed", listening ? "true" : "false");
    b.classList.toggle("on", listening);
  }
  function showMics() {
    document.querySelectorAll("form.ap-composer").forEach(showMic);
  }

  function addMic(form) {
    if (!Recognition || !form || micOf(form)) return;
    var b = document.createElement("button");
    b.type = "button";
    // ghost: the office's plain .btn is filled cyan, which made Talk look
    // like a second Send.
    b.className = "btn ghost ap-mic";
    // A microphone in front of the word, so it reads as voice at a glance
    // (asked for 2026-10-28). Drawn inline, in the button's own colour.
    b.innerHTML = MIC_SVG + '<span class="ap-mic-label">Talk</span>';
    b.setAttribute("aria-label", "Talk instead of typing");
    b.setAttribute("aria-pressed", "false");
    b.title = "Say it instead of typing. The answers are read out loud.";
    // After Send, so Send stays the composer's first button and the one
    // Enter presses.
    form.appendChild(b);
  }
  function addMics(root) {
    (root || document).querySelectorAll("form.ap-composer").forEach(addMic);
  }

  function stopReading() {
    SAYING = [];
    if (PLAYING) {
      try { PLAYING.pause(); } catch (e) { /* gone */ }
      PLAYING = null;
    }
    showMics();
  }

  function note(el, words) {
    if (!el) return;
    el.insertAdjacentHTML("beforeend", '<div class="am note"></div>');
    el.lastElementChild.textContent = words;
    toBottom(el);
  }

  function listen(form) {
    var input = form.querySelector('input[name="message"]');
    if (!input) return;
    stopReading();
    var rec;
    try { rec = new Recognition(); } catch (e) { return; }
    rec.lang = navigator.language || "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    LISTENING = { form: form, rec: rec, said: "" };
    rec.onresult = function (ev) {
      var words = "";
      for (var i = 0; i < ev.results.length; i++) {
        words += ev.results[i][0].transcript;
      }
      if (LISTENING && LISTENING.rec === rec) LISTENING.said = words.trim();
      input.value = words.trim();
    };
    rec.onerror = function (ev) {
      var why = ev && ev.error;
      if (why === "not-allowed" || why === "service-not-allowed") {
        note(threadOf(form), "The microphone is blocked. Allow it for this " +
          "site in the browser's settings, then press Talk again.");
      } else if (why && why !== "no-speech" && why !== "aborted") {
        note(threadOf(form), "Could not hear that (" + why + "). Try again, " +
          "or type it.");
      }
    };
    rec.onend = function () {
      var was = LISTENING && LISTENING.rec === rec ? LISTENING : null;
      if (was) LISTENING = null;
      showMic(form);
      var said = was ? was.said : "";
      if (!said) return;
      input.value = said;
      VOICE_SEND = form;
      try {
        if (typeof form.requestSubmit === "function") form.requestSubmit();
        else form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
      } finally { VOICE_SEND = null; }
    };
    try { rec.start(); } catch (e) { LISTENING = null; }
    showMic(form);
    try { input.focus(); } catch (e) { /* fine */ }
  }

  document.addEventListener("click", function (e) {
    var b = e.target && e.target.closest ? e.target.closest(".ap-mic") : null;
    if (!b) return;
    e.preventDefault();
    var form = b.closest("form");
    if (LISTENING && LISTENING.form === form) {
      try { LISTENING.rec.stop(); } catch (x) { /* ended already */ }
      return;
    }
    if (LISTENING) { try { LISTENING.rec.abort(); } catch (x) { /* fine */ } }
    listen(form);
  });

  //: A spoken message turns reading on for its thread; a typed one turns
  //: it off. Capture, so it is decided before htmx sends anything.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || !form.classList || !form.classList.contains("ap-composer")) return;
    var el = threadOf(form);
    if (!el) return;
    if (VOICE_SEND === form) el.setAttribute("data-voice", "1");
    else { el.removeAttribute("data-voice"); stopReading(); }
  }, true);

  function sayable(row) {
    var text = row.querySelector(".atext");
    if (!text) return "";
    var words = (text.textContent || "").replace(/\s+/g, " ").trim();
    if (words.length > SPEAK_MAX_CHARS) {
      var cut = words.slice(0, SPEAK_MAX_CHARS);
      var end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("? "),
                         cut.lastIndexOf("! "));
      words = end > SPEAK_MAX_CHARS / 2 ? cut.slice(0, end + 1) : cut;
    }
    return words;
  }

  function fetchSpeech(text) {
    return voiceId().then(function (voice) {
      return fetch("/api/v1/audio/speech", {
        method: "POST", headers: authHeaders(),
        body: JSON.stringify({ input: text, voice: voice })
      });
    }).then(function (r) {
      if (!r.ok) throw new Error("speech " + r.status);
      return r.blob();
    }).then(function (blob) { return URL.createObjectURL(blob); });
  }

  function playNext() {
    if (PLAYING || !SAYING.length) { showMics(); return; }
    var next = SAYING.shift();
    PLAYING = { pause: function () { next.cancelled = true; } };
    showMics();
    next.audio.then(function (url) {
      if (next.cancelled) return;
      var a = new Audio(url);
      PLAYING = a;
      function done() {
        try { URL.revokeObjectURL(url); } catch (e) { /* fine */ }
        if (PLAYING === a) PLAYING = null;
        playNext();
      }
      a.onended = done;
      a.onerror = done;
      var p = a.play();
      if (p && p.catch) p.catch(done);
    }).catch(function (err) {
      try { console.warn("[agent-chat] could not read the answer out", err); } catch (x) { /* fine */ }
      if (!next.cancelled) { PLAYING = null; playNext(); }
    });
  }

  //: Every answer that landed since the last look, read out in order when
  //: the thread was spoken to. Fetched as they land, played one by one.
  function sayNewAnswers(el) {
    if (!el) return;
    var rows = el.querySelectorAll(".am.agent:not([data-heard])");
    if (!rows.length) return;
    var on = el.getAttribute("data-voice") === "1";
    var speakers = {};
    el.querySelectorAll(".am.agent[data-agent]").forEach(function (r) {
      speakers[r.getAttribute("data-agent")] = 1;
    });
    var room = Object.keys(speakers).length > 1;
    rows.forEach(function (row) {
      row.setAttribute("data-heard", "1");
      if (!on || row.classList.contains("ajob")) return;
      var words = sayable(row);
      if (!words) return;
      var who = row.getAttribute("data-agent");
      if (room && who) words = who + ". " + words;
      SAYING.push({ audio: fetchSpeech(words) });
    });
    playNext();
  }

  // --- Attach (2026-10-28) ---------------------------------------------------
  // A file or a picture goes with the message. The server turns it into text
  // the agents read (agent_attach.py); here it is chosen, shown as a chip that
  // can be taken off again, and a picture is shrunk first, so a phone photo is
  // not five megabytes of upload and of vision tokens. The row sits above the
  // message box rather than beside Send and Talk: in the office's chat window
  // a third button left the box too narrow to type in.
  var ATTACH_MAX = 3;
  var ATTACH_BYTES = 5 * 1024 * 1024;
  var PIC_EDGE = 1600;
  var THUMB_EDGE = 160;
  //: The same list as agent_attach.ACCEPT (a test keeps them equal).
  var ATTACH_ACCEPT = "image/png,image/jpeg,image/webp,image/gif,.pdf,.c,.cfg,.cpp,.cs,.css,.csv,.env.example,.go,.h,.htm,.html,.ini,.java,.js,.json,.jsx,.kt,.log,.markdown,.md,.php,.py,.rb,.rs,.sh,.sql,.svelte,.swift,.toml,.ts,.tsv,.tsx,.txt,.vue,.xml,.yaml,.yml";
  var CHOSEN = typeof WeakMap === "function" ? new WeakMap() : null;

  function chosen(form) {
    if (!CHOSEN) return [];
    if (!CHOSEN.has(form)) CHOSEN.set(form, []);
    return CHOSEN.get(form);
  }

  function shrink(file, edge) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        var w = img.naturalWidth, h = img.naturalHeight;
        var k = Math.min(1, edge / Math.max(w, h, 1));
        var c = document.createElement("canvas");
        c.width = Math.max(1, Math.round(w * k));
        c.height = Math.max(1, Math.round(h * k));
        var g = c.getContext("2d");
        g.fillStyle = "#fff";
        g.fillRect(0, 0, c.width, c.height);
        g.drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        resolve(c);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolve(null); };
      img.src = url;
    });
  }

  //: A picture as it is sent: at most PIC_EDGE on its long side, as a JPEG,
  //: with a small preview for the chip and the bubble.
  function asPicture(file) {
    return shrink(file, PIC_EDGE).then(function (big) {
      if (!big) return { file: file, thumb: "" };
      return new Promise(function (resolve) {
        big.toBlob(function (blob) {
          var name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
          var out = blob ? new File([blob], name, { type: "image/jpeg" }) : file;
          shrink(out, THUMB_EDGE).then(function (small) {
            resolve({ file: out, thumb: small ? small.toDataURL("image/jpeg", 0.7) : "" });
          });
        }, "image/jpeg", 0.85);
      });
    });
  }

  //: The file input carries exactly the chips, so htmx posts what is shown.
  function syncFiles(form) {
    var input = form.querySelector("input.ap-files");
    var thumbs = form.querySelector('input[name="thumbs"]');
    var list = chosen(form), map = {};
    try {
      var dt = new DataTransfer();
      list.forEach(function (c) { dt.items.add(c.file); if (c.thumb) map[c.file.name] = c.thumb; });
      if (input) input.files = dt.files;
    } catch (e) { /* an old browser keeps whatever it picked itself */ }
    if (thumbs) thumbs.value = list.length ? JSON.stringify(map) : "";
    // Multipart only while there is a file to carry; a plain message still
    // posts the way it always has.
    if (list.length) form.setAttribute("hx-encoding", "multipart/form-data");
    else form.removeAttribute("hx-encoding");
    var chips = form.querySelector(".ap-chips");
    if (!chips) return;
    chips.innerHTML = "";
    list.forEach(function (c, i) {
      var chip = document.createElement("span");
      chip.className = "ap-chip";
      if (c.thumb) {
        var img = document.createElement("img");
        img.src = c.thumb;
        img.alt = "";
        chip.appendChild(img);
      }
      var name = document.createElement("span");
      name.className = "ap-chip-name";
      name.textContent = c.file.name;
      chip.appendChild(name);
      var x = document.createElement("button");
      x.type = "button";
      x.className = "ap-chip-x";
      x.setAttribute("data-i", String(i));
      x.setAttribute("aria-label", "Remove " + c.file.name);
      x.title = "Remove";
      x.innerHTML = "&times;";
      chip.appendChild(x);
      chips.appendChild(chip);
    });
  }

  function addFiles(form, files) {
    var list = chosen(form);
    var waits = [];
    Array.prototype.forEach.call(files || [], function (f) {
      if (list.length + waits.length >= ATTACH_MAX) {
        note(threadOf(form), "At most " + ATTACH_MAX + " files on one message.");
        return;
      }
      if (/^image\//.test(f.type)) {
        waits.push(asPicture(f));
      } else if (f.size > ATTACH_BYTES) {
        note(threadOf(form), f.name + " is larger than 5 MB.");
      } else {
        waits.push(Promise.resolve({ file: f, thumb: "" }));
      }
    });
    return Promise.all(waits).then(function (got) {
      got.forEach(function (c) { if (c && c.file) list.push(c); });
      syncFiles(form);
    });
  }

  function addAttach(form) {
    if (!form || form.querySelector(".ap-attach")) return;
    var tray = document.createElement("div");
    tray.className = "ap-tray";
    tray.innerHTML =
      '<button type="button" class="btn ghost ap-attach">Attach</button>' +
      '<span class="ap-chips"></span>' +
      '<span class="ap-tray-status" aria-live="polite"></span>' +
      '<input type="file" class="ap-files" name="files" multiple hidden>' +
      '<input type="hidden" name="thumbs" value="">';
    tray.querySelector(".ap-files").setAttribute("accept", ATTACH_ACCEPT);
    var b = tray.querySelector(".ap-attach");
    b.setAttribute("aria-label", "Attach a file or a picture");
    b.title = "Attach a picture, a PDF or a text file";
    form.insertBefore(tray, form.firstChild);
  }
  function addAttaches(root) {
    (root || document).querySelectorAll("form.ap-composer").forEach(addAttach);
  }

  document.addEventListener("click", function (e) {
    var t = e.target;
    var pick = t && t.closest ? t.closest(".ap-attach") : null;
    if (pick) {
      e.preventDefault();
      var input = pick.closest("form").querySelector("input.ap-files");
      // The chips already hold what was chosen before, so the picker starts
      // empty and what it adds joins them (change, below).
      if (input) { input.value = ""; input.click(); }
      return;
    }
    var x = t && t.closest ? t.closest(".ap-chip-x") : null;
    if (x) {
      e.preventDefault();
      var form = x.closest("form");
      chosen(form).splice(parseInt(x.getAttribute("data-i"), 10), 1);
      syncFiles(form);
    }
  });
  document.addEventListener("change", function (e) {
    var input = e.target;
    if (!input || !input.classList || !input.classList.contains("ap-files")) return;
    addFiles(input.closest("form"), Array.prototype.slice.call(input.files || []));
  });
  // A picture pasted into the message box, or a file dropped on the composer.
  function composerOf(e) {
    return e.target && e.target.closest ? e.target.closest("form.ap-composer") : null;
  }
  document.addEventListener("paste", function (e) {
    var form = composerOf(e);
    var files = e.clipboardData && e.clipboardData.files;
    if (!form || !files || !files.length) return;
    e.preventDefault();
    addFiles(form, files);
  });
  document.addEventListener("dragover", function (e) {
    if (composerOf(e)) e.preventDefault();
  });
  document.addEventListener("drop", function (e) {
    var form = composerOf(e);
    if (!form || !e.dataTransfer || !e.dataTransfer.files.length) return;
    e.preventDefault();
    addFiles(form, e.dataTransfer.files);
  });
  // A picture is looked at by a model before the message is posted, which
  // takes a few seconds; say so, rather than a Send that seems to do nothing.
  document.body.addEventListener("htmx:beforeRequest", function (e) {
    var form = e.detail && e.detail.elt;
    if (!form || !form.classList || !form.classList.contains("ap-composer")) return;
    var status = form.querySelector(".ap-tray-status");
    if (status && chosen(form).length) status.textContent = "Reading the attachment...";
  });
  document.body.addEventListener("htmx:afterRequest", function (e) {
    var form = e.detail && e.detail.elt;
    if (!form || !form.classList || !form.classList.contains("ap-composer")) return;
    var status = form.querySelector(".ap-tray-status");
    if (status) status.textContent = "";
    // Sent: the files went with it. Refused: reset() emptied the input, and
    // the chips put the files back for another try.
    if (e.detail.successful) chosen(form).length = 0;
    syncFiles(form);
  });

  addMics(document);
  addAttaches(document);
  if (window.MutationObserver) {
    // The office opens a chat window per conversation (office/js/dock.js),
    // each with its own composer, long after this ran.
    new MutationObserver(function (changes) {
      for (var i = 0; i < changes.length; i++) {
        if (changes[i].addedNodes && changes[i].addedNodes.length) { addMics(document); addAttaches(document); return; }
      }
    }).observe(document.body, { childList: true, subtree: true });
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
    // The server's own reason when it gave one ({"detail": "..."}), and the
    // status always: "did not go through" alone could not be told apart
    // from a refused message, a backend that is down or a dropped
    // connection (reported from the live office, 2026-10-26).
    var why = "";
    try {
      var body = JSON.parse(detail.xhr && detail.xhr.responseText || "");
      if (body && typeof body.detail === "string") why = body.detail;
    } catch (x) { /* not JSON */ }
    try { console.warn("[agent-chat] request failed", status, path, detail.xhr && detail.xhr.responseText); } catch (x) { /* fine */ }
    var said = (status === 401 || status === 403)
      ? "Your sign-in has expired. Reload the page and sign in again."
      : "That did not go through" + (status ? " (" + status + (why ? ": " + why : "") + ")" : " (no reply from the server)") + ". Try again in a moment.";
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
