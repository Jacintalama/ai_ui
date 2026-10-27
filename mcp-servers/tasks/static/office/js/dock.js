// The chat dock: conversations as windows along the bottom of the office,
// the way a messenger draws them (2026-10-16, "a chat inside the office
// which is like facebook messenger style that you can chat with the team
// and private chat with the agents... open multiple chat like 3 agents then
// it will minimize the other chat like a circle").
//
// One window per conversation: the team (the room, where every agent hears
// you) and one per agent (a private word with them). At most OPEN_MAX are
// open at once; opening another puts the oldest away as a circle in the
// bottom left corner, which shows how much was said while it was away and
// opens again when clicked. Which windows are open and which are away is
// remembered per browser, so a reload puts them back.
//
// Each window's thread is the same server-rendered conversation the agents
// page shows (/tasks/agents/chat/thread, ?agent= for a private one) and its
// composer is the same send route, so nothing about a conversation lives in
// this file: it only decides which ones are on screen. agent-chat.js, which
// renders, groups, types and scrolls, works per .ap-thread, so every window
// is a thread of its own.
import { esc } from "./util.js";

var OPEN_MAX = 3;
var STORE_KEY = "aiuiOfficeDock";
//: The room's key. A window's key is the agent's id, or this.
export var TEAM = "";

var S = null, opts = null;
//: Which windows exist, in the order they were opened: { key, min }.
var WINDOWS = [];
var UNREAD = {};

function remember() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(WINDOWS.map(function (w) {
      return { key: w.key, min: !!w.min };
    })));
  } catch (e) { /* a dock that cannot be remembered still works now */ }
}
function recall() {
  try {
    var got = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
    if (Array.isArray(got)) {
      return got.filter(function (w) { return w && typeof w.key === "string"; })
        .map(function (w) { return { key: w.key, min: !!w.min }; });
    }
  } catch (e) { /* unreadable: the default below */ }
  return null;
}

function safe(key) { return String(key).replace(/[^A-Za-z0-9_-]/g, "_"); }
export function threadId(key) { return key === TEAM ? "agent-thread" : "agent-thread-" + safe(key); }
function windowId(key) { return "cw-" + (key === TEAM ? "team" : safe(key)); }
function headId(key) { return "chead-" + (key === TEAM ? "team" : safe(key)); }

function agentOf(key) {
  return (S.AGENTS || []).filter(function (m) { return m.id === key; })[0] || null;
}
function nameOf(key) {
  if (key === TEAM) return "Team";
  var m = agentOf(key);
  return m ? (m.name || m.id) : key;
}
function initialOf(key) {
  return key === TEAM ? "T" : (nameOf(key).charAt(0) || "?").toUpperCase();
}

function find(key) {
  return WINDOWS.filter(function (w) { return w.key === key; })[0] || null;
}
function openOnes() { return WINDOWS.filter(function (w) { return !w.min; }); }

//: The window's own markup. The team thread keeps the id #agent-thread
//: (the server's queued-message fragment and the needs-you tray look for
//: it) and the team composer's hidden field keeps #ap-agent (the approval
//: buttons include it).
function windowHtml(key) {
  var tid = threadId(key), team = key === TEAM, name = nameOf(key);
  var where = team ? "" : "?agent=" + encodeURIComponent(key);
  return (
    '<section class="cw" id="' + windowId(key) + '" data-chat="' + esc(key) + '"' +
      ' aria-label="' + (team ? "Team chat" : "Chat with " + esc(name)) + '">' +
      '<header class="cw-head">' +
        '<span class="cw-av" aria-hidden="true">' + esc(initialOf(key)) + '</span>' +
        '<span class="cw-who"><b class="cw-name">' + esc(name) + '</b>' +
          '<small class="cw-state"><i class="dot idle"></i><span></span></small></span>' +
        (team ? '<button class="cw-meet" type="button" title="Every agent answers, and none may pass">Meeting</button>' : "") +
        '<button class="cw-min" type="button" aria-label="Minimise" title="Minimise">&#8211;</button>' +
        '<button class="cw-close" type="button" aria-label="Close" title="Close">&times;</button>' +
      '</header>' +
      '<div class="ap-thread" id="' + tid + '" data-thread="' + esc(key) + '"' +
        ' hx-get="/tasks/agents/chat/thread' + where + '" hx-trigger="load" hx-swap="innerHTML">' +
        '<div class="aempty">' + (team
          ? "Ask anything. Every agent hears it, and the ones with something to say answer."
          : "A private word with " + esc(name) + ". Nobody else reads it.") + '</div>' +
      '</div>' +
      '<form class="ap-composer" hx-post="/tasks/agents/chat/send"' +
        ' hx-target="#' + tid + '" hx-swap="beforeend" hx-on::after-request="this.reset()">' +
        '<input type="hidden" name="agent"' + (team ? ' id="ap-agent"' : "") + ' value="' + esc(key) + '">' +
        '<input type="text" name="message" autocomplete="off"' +
          ' placeholder="' + (team ? "Message everyone" : "Message " + esc(name)) + '"' +
          ' aria-label="' + (team ? "Message everyone" : "Message " + esc(name)) + '">' +
        '<button class="btn primary" type="submit">Send</button>' +
      '</form>' +
    '</section>');
}

function headHtml(key) {
  return (
    '<button class="chead" id="' + headId(key) + '" type="button" data-chat="' + esc(key) + '"' +
      ' title="' + esc(nameOf(key)) + '" aria-label="Open the chat with ' + esc(nameOf(key)) + '">' +
      '<span class="chead-av" aria-hidden="true">' + esc(initialOf(key)) + '</span>' +
      '<span class="chead-n" hidden></span>' +
      '<i class="dot idle"></i>' +
    '</button>');
}

//: Something said in a window that is away: counted on its circle.
function watchUnread(key, el) {
  if (!window.MutationObserver) return;
  var thread = el.querySelector(".ap-thread");
  new MutationObserver(function (muts) {
    var w = find(key);
    if (!w || !w.min) return;
    var said = 0;
    muts.forEach(function (m) {
      Array.prototype.forEach.call(m.addedNodes, function (n) {
        if (n.nodeType !== 1) return;
        if (n.matches && n.matches(".am.agent")) said++;
        else if (n.querySelectorAll) said += n.querySelectorAll(".am.agent").length;
      });
    });
    if (!said) return;
    UNREAD[key] = (UNREAD[key] || 0) + said;
    drawHeads();
  }).observe(thread, { childList: true, subtree: true });
}

function ensureWindow(key) {
  var box = document.getElementById("chatdock-open");
  if (!box) return null;
  var el = document.getElementById(windowId(key));
  if (el) return el;
  box.insertAdjacentHTML("beforeend", windowHtml(key));
  el = document.getElementById(windowId(key));
  if (window.htmx && typeof window.htmx.process === "function") window.htmx.process(el);
  watchUnread(key, el);
  return el;
}

function drawHeads() {
  var box = document.getElementById("chatdock-min");
  if (!box) return;
  var seen = {};
  WINDOWS.forEach(function (w) {
    if (!w.min) return;
    seen[w.key] = 1;
    var el = document.getElementById(headId(w.key));
    if (!el) { box.insertAdjacentHTML("beforeend", headHtml(w.key)); el = document.getElementById(headId(w.key)); }
    var n = UNREAD[w.key] || 0, badge = el.querySelector(".chead-n");
    badge.hidden = !n;
    badge.textContent = n > 9 ? "9+" : String(n);
    el.classList.toggle("unread", n > 0);
  });
  Array.prototype.slice.call(box.children).forEach(function (el) {
    if (!seen[el.getAttribute("data-chat")]) el.remove();
  });
  document.documentElement.classList.toggle("has-heads", box.children.length > 0);
}

//: Every window and circle brought in line with WINDOWS, without touching
//: a thread that is already on screen: a window is hidden when away, never
//: rebuilt, so the round in it carries on.
export function drawDock() {
  if (!S) return;
  WINDOWS.forEach(function (w) {
    var el = ensureWindow(w.key);
    if (!el) return;
    el.hidden = !!w.min;
    var st = opts.stateOf ? opts.stateOf(w.key) : null;
    var dot = el.querySelector(".cw-state .dot"), words = el.querySelector(".cw-state span");
    if (dot && st) dot.className = "dot " + st.key;
    if (words && st) words.textContent = w.key === TEAM ? st.label : st.label;
  });
  var box = document.getElementById("chatdock-open");
  if (box) {
    Array.prototype.slice.call(box.children).forEach(function (el) {
      if (!find(el.getAttribute("data-chat"))) el.remove();
    });
  }
  drawHeads();
  // The circles' lights too.
  WINDOWS.forEach(function (w) {
    var el = document.getElementById(headId(w.key));
    var st = el && opts.stateOf ? opts.stateOf(w.key) : null;
    if (el && st) el.querySelector(".dot").className = "dot " + st.key;
  });
}

//: Open a conversation: brought back if it was away, made if it did not
//: exist. More than OPEN_MAX open puts the one opened longest ago away.
//: `ask` fills the composer and stops; nothing is ever sent for you.
export function openChat(key, ask) {
  key = key || TEAM;
  var w = find(key);
  if (!w) { w = { key: key, min: false }; WINDOWS.push(w); }
  w.min = false;
  UNREAD[key] = 0;
  // Oldest first among the open ones, this one excepted.
  var open = openOnes();
  while (open.length > OPEN_MAX) {
    var oldest = open.filter(function (o) { return o.key !== key; })[0];
    if (!oldest) break;
    oldest.min = true;
    open = openOnes();
  }
  remember();
  drawDock();
  var el = document.getElementById(windowId(key));
  var input = el && el.querySelector('input[name="message"]');
  if (input) {
    if (typeof ask === "string" && ask) input.value = ask;
    try { input.focus(); } catch (e) { /* a hidden frame cannot take focus */ }
  }
  // Back at its end, where the newest message is. Not settled here: a
  // thread still loading would be marked as drawn, and its history would
  // then type in as if it had just been said.
  var thread = el && el.querySelector(".ap-thread");
  if (thread) thread.scrollTop = thread.scrollHeight;
  return el;
}

export function minimiseChat(key) {
  var w = find(key);
  if (!w) return;
  w.min = true;
  remember();
  drawDock();
}

export function closeChat(key) {
  WINDOWS = WINDOWS.filter(function (w) { return w.key !== key; });
  delete UNREAD[key];
  remember();
  drawDock();
}

export function dockState() {
  return WINDOWS.map(function (w) { return { key: w.key, min: !!w.min }; });
}

//: Wire the dock. `stateOf(id)` is the floor's own word on an agent's
//: state, so a window's light is the same light as the robot's.
export function initDock(state, options) {
  S = state;
  opts = options || {};
  var dock = document.getElementById("chatdock");
  if (!dock) return;
  var kept = recall();
  // The first visit: the team chat is open, the way the column was.
  WINDOWS = kept || [{ key: TEAM, min: false }];
  // A remembered private window for an agent that is gone is dropped.
  dock.addEventListener("click", function (ev) {
    var head = ev.target.closest(".chead");
    if (head) { openChat(head.getAttribute("data-chat")); return; }
    var win = ev.target.closest(".cw");
    if (!win) return;
    var key = win.getAttribute("data-chat");
    if (ev.target.closest(".cw-close")) { closeChat(key); return; }
    if (ev.target.closest(".cw-min")) { minimiseChat(key); return; }
    if (ev.target.closest(".cw-meet")) {
      var input = win.querySelector('input[name="message"]');
      if (input) { input.value = "everyone answer: "; input.focus(); }
      return;
    }
    // The title bar itself folds the window away, as a messenger's does.
    if (ev.target.closest(".cw-head") && !ev.target.closest("button")) minimiseChat(key);
  });
  drawDock();
}

//: Called once the agents are known, so a remembered private window for
//: an agent that no longer exists is dropped rather than drawn empty.
export function pruneDock() {
  if (!S) return;
  var before = WINDOWS.length;
  WINDOWS = WINDOWS.filter(function (w) { return w.key === TEAM || !!agentOf(w.key); });
  if (WINDOWS.length !== before) remember();
  drawDock();
}
