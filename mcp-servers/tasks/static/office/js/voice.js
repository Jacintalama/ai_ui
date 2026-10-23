// Talking with an agent (2026-10-23, "in the chat how the ai agent talk to
// user ... have mic enable and disable for user").
//
// Two halves, both free and both offline from this service's point of view.
// HEARING is the browser's own speech recognition (Chrome, Edge, Safari;
// Firefox keeps it behind a flag): the mic at the left of a window's
// composer turns it on, the words it hears go into the box, grey while
// still being heard and solid once a phrase is final, and a pause of
// SILENCE_MS after a final phrase sends the box through the composer's own
// form, so approvals, Needs you and who answers all work exactly as for a
// typed message. SPEAKING is Piper on the server (/agents/voice/say): when
// the server says an answer has landed (speaking_started, through office.js
// voiceSaid), the answer's row is read sentence by sentence in that agent's
// voice, and the robot's mouth moves for as long as the sound plays
// (S.VOICING, read by office.js speaking()).
//
// The rules: the speaker button on a window mutes every voice, remembered
// per browser; auto listen reopens the mic after an answer, but only when
// the question was spoken, so a typed chat never starts listening on its
// own; the mic pressed while a robot talks cuts it off and listens; a
// browser without speech recognition shows no mic and no auto listen, and
// still hears the agents. Nothing here may break the chat: every failure
// leaves the text exactly as it was.
import { S, nameOf } from "./state.js";
import { authHeaders, getJson, esc } from "./util.js";

var SAY = "/api/tasks/agents/voice/say";
var VOICES_URL = "/api/tasks/agents/voice/voices";
var SPEAKER_KEY = "aiui.voice.speaker";   // "0" = muted
var AUTO_KEY = "aiui.voice.auto";         // "0" = off
var VOICE_OF = "aiui.voice.of.";          // + agent id -> voice id
export var SILENCE_MS = 1200;

//: The voices Piper carries here, in case the listing cannot be read. The
//: ids match video_voices.py.
var FALLBACK_VOICES = [
  { id: "amy", label: "Amy", accent: "US", gender: "Female" },
  { id: "ryan", label: "Ryan", accent: "US", gender: "Male" },
  { id: "lessac", label: "Lessac", accent: "US", gender: "Female" },
  { id: "joe", label: "Joe", accent: "US", gender: "Male" },
  { id: "alan", label: "Alan", accent: "UK", gender: "Male" },
  { id: "alba", label: "Alba", accent: "UK", gender: "Female" }
];
var VOICES = FALLBACK_VOICES.slice();

var opts = {};
function changed() { if (opts.onChange) opts.onChange(); }
function store(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* no storage */ } }
function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

// --- what the browser can do -------------------------------------------------

function Recognizer() { return window.SpeechRecognition || window.webkitSpeechRecognition || null; }
export function canListen() { return !!Recognizer(); }
export function speakerOn() { return read(SPEAKER_KEY) !== "0"; }
export function autoOn() { return canListen() && read(AUTO_KEY) !== "0"; }

// --- whose voice -------------------------------------------------------------

//: Every agent gets a voice of its own from its id alone, so a meeting
//: sounds like different people before anybody picks anything.
export function defaultVoice(agentId) {
  var h = 0, s = String(agentId || "");
  for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return VOICES[h % VOICES.length].id;
}
export function voiceOf(agentId) {
  var v = read(VOICE_OF + agentId);
  return v && VOICES.some(function (x) { return x.id === v; }) ? v : defaultVoice(agentId);
}
export function setVoiceOf(agentId, voiceId) {
  store(VOICE_OF + agentId, voiceId && voiceId !== defaultVoice(agentId) ? voiceId : null);
}
export function voices() { return VOICES.slice(); }
export async function loadVoices() {
  try {
    var got = await getJson(VOICES_URL);
    if (got && Array.isArray(got.voices) && got.voices.length) VOICES = got.voices;
  } catch (e) { /* the built-in list stands */ }
}
//: The card's Voice row: a pick and a sample.
export function voiceRowHtml(agent) {
  var picked = voiceOf(agent.id), dflt = defaultVoice(agent.id);
  return '<div class="voice-row">' +
    '<select class="voice-pick" data-id="' + esc(agent.id) + '" aria-label="Voice of ' + esc(agent.name || agent.id) + '">' +
      VOICES.map(function (v) {
        var words = v.label + " (" + v.accent + ", " + String(v.gender || "").toLowerCase() + ")" + (v.id === dflt ? ", its own" : "");
        return '<option value="' + esc(v.id) + '"' + (v.id === picked ? " selected" : "") + '>' + esc(words) + '</option>';
      }).join("") +
    '</select>' +
    '<button type="button" class="voice-hear" data-id="' + esc(agent.id) + '" title="Hear this voice">&#9654; Hear</button>' +
  '</div>';
}
var sample = null;
export function hearSample(agentId) {
  try {
    if (sample) { sample.pause(); sample = null; }
    sample = new Audio("/tasks/static/voices/" + encodeURIComponent(voiceOf(agentId)) + ".mp3");
    sample.play().catch(function () {});
  } catch (e) { /* no audio */ }
}

// --- speaking ----------------------------------------------------------------

//: Sentences, the unit the server is asked for: the first is heard while
//: the rest are still being made. Short fragments ride with the next.
export function sentences(text) {
  var parts = String(text || "").replace(/\s+/g, " ").trim().split(/(?<=[.!?])\s+/), out = [], cur = "";
  parts.forEach(function (p) {
    cur = cur ? cur + " " + p : p;
    if (cur.length >= 24) { out.push(cur); cur = ""; }
  });
  if (cur) { if (out.length && cur.length < 12) out[out.length - 1] += " " + cur; else out.push(cur); }
  return out.filter(Boolean);
}

var QUEUE = [], PLAYING = null, player = null, lastSpokenWin = null, fetching = 0;

function voicing(agentId, on) {
  if (on) S.VOICING[agentId] = true; else delete S.VOICING[agentId];
  document.querySelectorAll('.am.agent[data-voicing="1"]').forEach(function (r) {
    if (!on || r.getAttribute("data-agent") !== nameOf(agentId)) r.removeAttribute("data-voicing");
  });
  document.querySelectorAll(".cw").forEach(function (w) { w.classList.toggle("voicing", !!Object.keys(S.VOICING).length); });
  changed();
}

async function fetchClip(item) {
  if (item.blob !== undefined || item.failed) return;
  fetching++;
  try {
    var r = await fetch(SAY, { method: "POST", headers: authHeaders(), credentials: "include",
                               body: JSON.stringify({ text: item.text, voice: item.voice }) });
    if (!r.ok) throw new Error("say " + r.status);
    item.blob = await r.blob();
  } catch (e) {
    // The answer stays text. A 503 (no Piper) or a 429 (too many) is not
    // the person's problem to see.
    item.failed = true;
  } finally {
    fetching--;
  }
  if (item.waiting) { var w = item.waiting; item.waiting = null; w(); }
}
function prefetch() {
  // The one playing plus the next two, at most, so a long meeting does not
  // ask the server for everything at once.
  QUEUE.slice(0, 2).forEach(function (it) { if (it.blob === undefined && !it.failed && !it.loading) { it.loading = true; fetchClip(it); } });
}
function playNext() {
  if (PLAYING) return;
  var item = QUEUE.shift();
  if (!item) { drained(); return; }
  PLAYING = item;
  function go() {
    if (PLAYING !== item) return;
    if (item.failed || !item.blob) { finished(item); return; }
    var url;
    try {
      url = URL.createObjectURL(item.blob);
      player = new Audio(url);
    } catch (e) { finished(item); return; }
    var ended = false;
    function end() {
      if (ended) return; ended = true;
      try { URL.revokeObjectURL(url); } catch (e) { /* fine */ }
      finished(item);
    }
    player.addEventListener("ended", end);
    player.addEventListener("error", end);
    if (item.row) item.row.setAttribute("data-voicing", "1");
    voicing(item.agentId, true);
    var p = player.play();
    if (p && p.catch) p.catch(end);
  }
  // This clip first, then the ones after it, so the server makes them in
  // the order they are heard.
  if (item.blob !== undefined || item.failed) go();
  else if (item.loading) item.waiting = go;
  else { item.loading = true; item.waiting = go; fetchClip(item); }
  prefetch();
}
function finished(item) {
  if (PLAYING !== item) return;
  PLAYING = null; player = null;
  var more = QUEUE.some(function (q) { return q.agentId === item.agentId; });
  if (!more) voicing(item.agentId, false);
  if (item.row && !more) item.row.removeAttribute("data-voicing");
  playNext();
}
function drained() {
  // Said and done: if the question was spoken, listen for the next one.
  var win = lastSpokenWin;
  lastSpokenWin = null;
  if (win && autoOn() && document.body.contains(win) && !LISTENING) listen(win);
}
export function stopSpeaking() {
  QUEUE = [];
  var was = PLAYING;
  PLAYING = null;
  if (player) { try { player.pause(); } catch (e) { /* fine */ } player = null; }
  if (was) { if (was.row) was.row.removeAttribute("data-voicing"); voicing(was.agentId, false); }
  document.querySelectorAll('.am.agent[data-voicing="1"]').forEach(function (r) { r.removeAttribute("data-voicing"); });
  Object.keys(S.VOICING).forEach(function (k) { delete S.VOICING[k]; });
  document.querySelectorAll(".cw.voicing").forEach(function (w) { w.classList.remove("voicing"); });
  changed();
}
export function isSpeaking() { return !!PLAYING || QUEUE.length > 0; }

//: Read this row aloud in this agent's voice.
export function say(agentId, row, text) {
  if (!speakerOn()) return;
  var voice = voiceOf(agentId);
  sentences(text).forEach(function (s) { QUEUE.push({ agentId: agentId, row: row, text: s, voice: voice }); });
  if (!PLAYING) playNext(); else prefetch();
}

//: The server says this agent's answer has landed (speaking_started). Its
//: row is the newest of that agent's in any window that is not yet read.
//: The row may land a moment after the event, on the chat's own stream, so
//: this looks a few times before giving up.
export function voiceSaid(agentId) {
  if (!speakerOn()) return;
  var name = nameOf(agentId), tries = 0;
  if (!name) return;
  (function look() {
    var rows = document.querySelectorAll('#chatdock .ap-thread .am.agent:not([data-voiced]):not(.awaiting):not(.ajob)');
    var row = null;
    for (var i = rows.length - 1; i >= 0; i--) {
      if (rows[i].getAttribute("data-agent") === name) { row = rows[i]; break; }
    }
    if (!row) { if (++tries < 20) setTimeout(look, 150); return; }
    row.setAttribute("data-voiced", "1");
    var text = row.querySelector(".atext");
    say(agentId, row, text ? text.textContent : "");
  })();
}

// --- listening ---------------------------------------------------------------

var LISTENING = null;   // { win, rec, finals, timer }

function micOf(win) { return win.querySelector(".ap-mic"); }
function inputOf(win) { return win.querySelector('.ap-composer input[name="message"]'); }
function showListening(win, on) {
  win.classList.toggle("listening", on);
  var mic = micOf(win);
  if (mic) {
    mic.setAttribute("aria-pressed", on ? "true" : "false");
    mic.setAttribute("aria-label", on ? "Stop listening" : "Talk");
    mic.title = on ? "Stop listening" : "Talk";
  }
  var input = inputOf(win);
  if (input && !on) input.removeAttribute("data-interim");
}
function sendSpoken(win) {
  var input = inputOf(win), form = win.querySelector(".ap-composer");
  stopListening();
  if (!input || !form || !input.value.trim()) return;
  input.removeAttribute("data-interim");
  lastSpokenWin = win;
  // The composer's own send, so htmx opens the round exactly as for typing.
  if (typeof form.requestSubmit === "function") form.requestSubmit();
  else form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}
export function listen(win) {
  var R = Recognizer();
  if (!R || !win) return;
  if (LISTENING) stopListening();
  // The mic is also the way to cut a talking robot off.
  if (isSpeaking()) stopSpeaking();
  var rec, input = inputOf(win);
  try { rec = new R(); } catch (e) { return; }
  rec.continuous = true;
  rec.interimResults = true;
  try { rec.lang = navigator.language || "en-US"; } catch (e) { /* fine */ }
  var st = { win: win, rec: rec, timer: null, typed: input ? input.value : "" };
  LISTENING = st;
  rec.onresult = function (ev) {
    if (LISTENING !== st) return;
    var finals = "", interim = "";
    for (var i = 0; i < ev.results.length; i++) {
      var r = ev.results[i], t = r[0] ? r[0].transcript : "";
      if (r.isFinal) finals += t; else interim += t;
    }
    var lead = st.typed ? st.typed.replace(/\s+$/, "") + " " : "";
    if (input) {
      input.value = (lead + finals + interim).replace(/\s+/g, " ").replace(/^\s/, "");
      if (interim) input.setAttribute("data-interim", "1"); else input.removeAttribute("data-interim");
    }
    clearTimeout(st.timer);
    if (finals.trim() && !interim) st.timer = setTimeout(function () { if (LISTENING === st) sendSpoken(win); }, SILENCE_MS);
  };
  rec.onerror = function (ev) {
    if (LISTENING !== st) return;
    var why = ev && ev.error;
    if (why === "not-allowed" || why === "service-not-allowed") {
      if (input) input.placeholder = "Microphone blocked. Allow it in the address bar.";
    }
    stopListening();
  };
  rec.onend = function () {
    // The browser stops on its own after a while of quiet. Anything final
    // and unsent goes now rather than sitting in the box.
    if (LISTENING !== st) return;
    if (input && input.value.trim() && !input.getAttribute("data-interim") && input.value !== st.typed) sendSpoken(win);
    else stopListening();
  };
  showListening(win, true);
  try { rec.start(); } catch (e) { stopListening(); }
}
export function stopListening() {
  var st = LISTENING;
  if (!st) return;
  LISTENING = null;
  clearTimeout(st.timer);
  try { st.rec.onend = null; st.rec.onresult = null; st.rec.onerror = null; st.rec.stop(); } catch (e) { /* fine */ }
  showListening(st.win, false);
}
export function isListening() { return !!LISTENING; }

// --- the windows -------------------------------------------------------------

//: The buttons a window carries (dock.js draws them), brought up to date:
//: the mic only where the browser can hear, the speaker and auto-listen
//: as remembered.
export function decorate(root) {
  (root || document).querySelectorAll(".cw").forEach(function (win) {
    var mic = micOf(win), auto = win.querySelector(".cw-auto"), spk = win.querySelector(".cw-voice");
    var can = canListen();
    if (mic) mic.hidden = !can;
    if (auto) { auto.hidden = !can; auto.setAttribute("aria-pressed", autoOn() ? "true" : "false"); }
    if (spk) spk.setAttribute("aria-pressed", speakerOn() ? "true" : "false");
  });
}

export function initVoice(options) {
  opts = options || {};
  var dock = document.getElementById("chatdock");
  if (!dock) return;
  // The list is only read when a card is drawn, and the built-in one is
  // the same six, so nothing is redrawn for it: a draw() during the
  // floor's first load re-bore every robot (seen 2026-10-23).
  loadVoices();
  decorate(dock);
  if (window.MutationObserver) {
    new MutationObserver(function () { decorate(dock); }).observe(dock, { childList: true, subtree: false });
    var open = document.getElementById("chatdock-open");
    if (open) new MutationObserver(function () { decorate(dock); }).observe(open, { childList: true });
  }
  dock.addEventListener("click", function (ev) {
    var win = ev.target.closest(".cw");
    if (!win) return;
    if (ev.target.closest(".ap-mic")) {
      ev.preventDefault();
      if (LISTENING && LISTENING.win === win) {
        // Pressed again: send what is there, or just stop.
        var input = inputOf(win);
        if (input && input.value.trim() && input.value !== LISTENING.typed) sendSpoken(win); else stopListening();
      } else {
        listen(win);
      }
      return;
    }
    if (ev.target.closest(".cw-voice")) {
      var on = !speakerOn();
      store(SPEAKER_KEY, on ? null : "0");
      if (!on) stopSpeaking();
      decorate(dock);
      return;
    }
    if (ev.target.closest(".cw-auto")) {
      store(AUTO_KEY, autoOn() ? "0" : null);
      decorate(dock);
    }
  });
  // Typing in a listening box is the person taking over.
  dock.addEventListener("keydown", function (ev) {
    if (LISTENING && ev.target === inputOf(LISTENING.win) && ev.key.length === 1) stopListening();
  });
}
