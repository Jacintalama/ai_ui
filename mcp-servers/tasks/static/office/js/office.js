// The Agent Office.
//
// Moved out of office.html on 2026-10-08, unchanged, as the first step of
// splitting it: a module is deferred and strict where an inline script was
// neither, so doing that on its own makes any breakage obviously about module
// semantics rather than tangled up with restructuring.
//
// The outer closure is kept for now. It stops meaning anything once this file
// is broken into the modules beside it, and goes then.

import { S, nameOf } from "./state.js";
import { initNewAgent } from "./newagent.js";
import { initDock, drawDock, openChat, pruneDock, TEAM } from "./dock.js";
import { initVoice, voiceSaid, voiceRowHtml, setVoiceOf, hearSample } from "./voice.js";
import { getJson, esc, ago, saying, authHeaders } from "./util.js";
import { PALETTES, ownPalette, paletteOf, colourOf, pickColour, robot, face }
  from "./agent.js";

(function () {
  "use strict";

  //: Which tab is showing. Page state, not shared state: no other
  //: module has any business knowing which tab you are on.
  var TAB = "office";

  //: Handoffs between this person's agents in the last few minutes, straight
  //: from tasks.agent_step. The floor draws a collaboration from these and
  //: from nothing else: an empty list means nobody is drawn talking, however
  //: busy the office looks.
  //: Where each robot ended up on the floor this draw, as percentages, so a
  //: line can be run between two of them. Rebuilt by drawRooms.
  //: Which tool each agent is running right now, from the live feed only.





















  function roleOf(m) { return (m.meta && m.meta.role) || ""; }
  function toolsOf(m) {
    var t = (m.meta && m.meta.toolIds) || [];
    return Array.isArray(t) ? t : [];
  }
  function descOf(m) {
    var meta = m.meta || {}, params = m.params || {};
    return meta.description || params.system || meta.agent_instructions || "";
  }

  // agent_activity._shape returns last_run_at and last_status. Reading
  // started_at and status gave undefined for both, so an agent with 761 runs
  // said "No runs recorded yet" and every live card said "never".
  function stateOf(id) {
    var a = S.ACTIVITY[id];
    if (!a) return { key: "idle", label: "No runs yet" };
    if (a.state === "working") {
      // _since is set from the browser's own clock both times it is set,
      // so the timer runs between reads and server clock skew cannot make
      // it negative.
      var secs = a._since != null
        ? Math.max(0, Math.round((Date.now() - a._since) / 1000))
        : a.running_for_seconds;
      // A build is the agent working on an app, for minutes: said as what
      // it is, so "Building 4m" beside Rex is the job the to-do lists.
      var verb = a.source === "build" ? "Building" : "Working";
      return { key: "working", label: verb + (secs != null ? " " + secs + "s" : "") };
    }
    if (a.state === "waiting") return { key: "waiting", label: "Waiting on you" };
    if (a.state === "failed") return { key: "failed", label: "Last run failed" };
    if (asleep(a)) return { key: "asleep", label: "Asleep, last run " + ago(a.last_run_at) };
    return { key: "ready", label: "Ready" };
  }

  //: How long a desk is quiet before the robot at it dozes off (2026-10-21,
  //: "robots idle sleeping like you know human working"). Nothing is
  //: invented: asleep is "finished, and nothing since", drawn so a floor of
  //: twenty agents reads at a glance as who is actually doing something.
  //: A sleeping robot also costs the browser nothing: no blink, no halo, one
  //: slow breath (agent.css). It wakes the moment a run starts.
  var SLEEP_AFTER_MS = 30 * 60 * 1000;
  function asleep(a) {
    if (!a || a.state !== "ready") return false;
    // Quiet since the later of: when the last run began (the server's
    // word) and when this page saw it finish (its own clock). A run that
    // ended a moment ago is not a quiet desk, whatever its start stamp.
    var at = Math.max(Date.parse(a.last_run_at || "") || 0, a._finished || 0);
    return !at || Date.now() - at > SLEEP_AFTER_MS;
  }
  //: Who is asleep right now, as one string, so a timer can tell when
  //: somebody has just dozed off and redraw only then.
  function sleepers() {
    return S.AGENTS.filter(function (m) { return asleep(S.ACTIVITY[m.id]); })
      .map(function (m) { return m.id; }).join(",");
  }

  // Which part of the office an agent belongs to, decided by the tools it
  // actually holds, so this is a picture of how they were set up rather than
  // a seating plan somebody typed. First match wins, so an agent holding both
  // code and schedules sits in Development.
  // Six rooms on a plan, laid out as in the owner's mockup: three across the
  // top, three across the bottom, with the middle left open.
  //: No furniture. The rooms wore little drawn desks, screens, shelves
  //: and plants from 2026-10-08 to 2026-10-12, and the owner circled every
  //: one of them: "remove this that kinda messy please fix make it clean".
  //: A room is its name, its numbers and the people in it; each agent
  //: still has a desk of its own (.desk, agent.css) under its feet.
  var ZONES = [
    { key: "research",   label: "Research",       tools: ["server:mcp-proxy", "fusion"],
      glow: "#22D3EE" },
    { key: "dev",        label: "Development",    tools: ["code"],
      glow: "#60a5fa" },
    { key: "comms",      label: "Communication",  tools: ["gmail"],
      glow: "#f472b6" },
    { key: "meeting",    label: "Meeting room",   tools: ["calendar"],
      glow: "#34d399" },
    { key: "knowledge",  label: "Knowledge base", tools: ["gdrive", "documents"],
      glow: "#a78bfa" },
    { key: "automation", label: "Automation",     tools: ["schedules", "excel_creator", "executive_dashboard"],
      glow: "#fbbf24" },
  ];
  // An agent whose owner picked no tools reaches everything, so it has no one
  // room. It gets a room of its own rather than being hidden.
  var LOUNGE = { key: "lounge", label: "Open floor", tools: [], glow: "#8296b5" };

  //: --- the floor's measurements -------------------------------------------
  //: Rooms used to be fixed percentages of a fixed 1040x680 canvas, which
  //: meant a room could hold fewer agents than were standing in it. Three
  //: agents in Development put the third one's name and Chat pill below the
  //: room's own wall, which is how the project manager went missing.
  //:
  //: Everything below is in canvas pixels and runs the other way round: an
  //: agent needs a slot, a room is however big its slots make it, and the
  //: canvas is however big its rooms make it. A room cannot be too small for
  //: its people because its people are what set its size.
  var SLOT_W = 140;        // one agent's column; the name label is the widest part
  var BOT_W = 62, BOT_H = 84;
  var SLOT_H = 132;        // robot + name + Chat, stacked
  var SLOT_GAP_X = 12, SLOT_GAP_Y = 14;
  var ROOM_HEAD = 46;      // the room's own title strip, up to two lines
  //: No room is narrower than the name written across it. A room holding one
  //: person would otherwise be sized by that one slot and print its own
  //: department as "COMMUNICAT...".
  //: Wide enough for the header to fit on one line: a lit dot, the longest
  //: department name at 11px with wide letter-spacing, and the clean badge
  //: beside it. At 172 "COMMUNICATION" was ellipsised down to "COMMUN...",
  //: which names nothing.
  var ROOM_MIN_W = 252;
  var ROOM_PAD = 14, ROOM_GAP = 18, BAND_PAD = 18;
  //: The strip along a room's bottom edge carrying its runs and its cost.
  //: Reserved, or the lowest agent in a room stands on top of it.
  var ROOM_FOOT = 24;
  //: The strip the meeting table takes along the bottom of the meeting
  //: room while a meeting is on. Reserved only then, and only there: the
  //: table used to be laid across the Chat pills of whoever stood in the
  //: bottom row (screenshot, 2026-10-12, five agents in a meeting).
  var TABLE_SPACE = 36;
  var FLOOR_BAR = 52;      // the strip along the bottom, which is not a room
  //: Clear canvas above the rooms for the live activity card, which on the
  //: whole page is laid over the floor in the top right corner. Reserved
  //: rather than left to overlap: a card sitting on a room hides the agent
  //: it is reporting on, which is the opposite of what it is for. Zero in
  //: the dock, where the card is under the floor and not over it.
  //: 70, down from 120 (2026-10-16): the card rests folded to one line
  //: now (embed.css), so the band only has to clear that line.
  var TOP_RESERVE = 70;
  //: The room a meeting happens in. A FIXTURE on the floor from 2026-10-08:
  //: drawn whether or not anybody is in it, because a room people are called
  //: to has to be somewhere they can already see. Every other room still
  //: appears only when somebody works in it.
  var MEETING_KEY = "meeting";
  //: Your own desk, a fixture like the meeting room (2026-10-16, "add a
  //: desk of the user so he or she can approve"). An agent whose run has
  //: stopped to wait on you walks here and stands at your desk until you
  //: answer, from the tray in the column or in the thread, or until you
  //: set it to Auto, after which it never has to ask again. Drawn from the
  //: same recorded state as the robot's wide-eyed face.
  var YOU_KEY = "you";
  var YOU = { key: YOU_KEY, label: "Your desk", tools: [], glow: "#fbbf24", fixture: true };
  function atYourDesk(id) { return stateOf(id).key === "waiting"; }

  function topReserve() {
    try {
      if (document.documentElement.classList.contains("embed")) return 0;
      // Just the live activity card's corner now. The band used to grow to
      // stand a whole meeting in, because the table floated above the rooms;
      // the meeting happens in a room on the plan since 2026-10-08, so the
      // floor no longer reshapes itself when one is called.
      return TOP_RESERVE;
    } catch (e) { return 0; }
  }
  //: The canvas used to be a fixed 1040px, so the bottom strip always had
  //: room for its sentence and its two buttons on one line. It is sized by
  //: the rooms now, and two rooms come to under 400px: the strip wrapped
  //: onto three lines, grew upward from the bottom edge it is pinned to, and
  //: covered the agents standing above it, which swallowed their Chat pills.
  var CANVAS_MIN_W = 780;
  //: The stacking depths worth trying. Past three rows a room is a tower and
  //: the canvas is taller than any dock, so there is nothing to gain by
  //: offering more.
  var ROW_CAPS = [1, 2, 3];

  //: The shape that shows the floor largest in the room it has. Ties and a
  //: missing box both fall back to the first candidate, so this can never
  //: return nothing.
  //: Is this the small card on the agents page, or the office itself? The
  //: two want opposite things from the same floor: a dock is a few hundred
  //: pixels tall, so it scales the plan down and lets you zoom and drag
  //: around it, while the full page has room to show the whole thing and
  //: should simply show it.
  function embedded() {
    try { return document.documentElement.classList.contains("embed"); }
    catch (e) { return false; }
  }

  //: Stretch the chosen plan until it is the shape of the box it will be
  //: drawn in, so no strip of floor is left empty down one side and there is
  //: nothing off-screen to go and look for. bestLayout still CHOOSES on the
  //: unstretched plans, which is the right order: pick the arrangement that
  //: fits best, then let it fill.
  //:
  //: Full page only. In the dock the plan is deliberately smaller than the
  //: card, which is what the zoom and the drag are for.
  function spreadSlots(r, left, w) {
    // The agents keep their spacing and stay centred in the room they are
    // standing in, so widening a room does not strand them against a wall.
    var d = (left + w / 2) - (r.left + r.w / 2);
    r.slots.forEach(function (s) { s.left = Math.round(s.left + d); });
  }

  function fillTheBox(plan) {
    var box = fitBox();
    if (embedded() || !box || !plan || !plan.rooms || !plan.rooms.length) return plan;

    var rows = {}, order = [];
    plan.rooms.forEach(function (r) {
      if (!rows[r.top]) { rows[r.top] = []; order.push(r.top); }
      rows[r.top].push(r);
    });
    order.sort(function (a, b) { return a - b; });

    var aspect = box.w / box.h;
    var W = Math.max(plan.w, plan.h * aspect);
    var H = Math.max(plan.h, plan.w / aspect);

    // Across: every row spans the whole band, each room taking the share of
    // the extra that its own width already earned, so a room holding three
    // people stays wider than one holding one.
    order.forEach(function (key) {
      var row = rows[key].sort(function (a, b) { return a.left - b.left; });
      var avail = W - BAND_PAD * 2 - ROOM_GAP * (row.length - 1);
      var sum = row.reduce(function (a, r) { return a + r.w; }, 0);
      var f = sum > 0 ? avail / sum : 1;
      var x = BAND_PAD;
      row.forEach(function (r) {
        var w = Math.round(r.w * f);
        spreadSlots(r, x, w);
        r.left = x; r.w = w;
        x += w + ROOM_GAP;
      });
    });

    // Down: the rows share what is left evenly, and each room's agents are
    // re-centred in the taller room rather than left clinging to its ceiling.
    var extra = H - plan.h;
    if (extra > 0) {
      var per = extra / order.length, dy = 0;
      order.forEach(function (key) {
        rows[key].forEach(function (r) {
          var lift = Math.round(per / 2);
          r.top = Math.round(r.top + dy);
          r.h = Math.round(r.h + per);
          r.slots.forEach(function (s) { s.top = Math.round(s.top + dy + lift); });
        });
        dy += per;
      });
    }
    plan.w = Math.round(W);
    plan.h = Math.round(H);
    return plan;
  }

  function bestLayout(rooms) {
    var box = fitBox(), best = null, bestK = -1;
    // Both the shape of a room and the shape of the PLAN are tried: how many
    // people stack inside a room, and how many rooms stand side by side
    // before the next row. One band of equal columns reads as a chart rather
    // than a floor, and on a wide page it is also the worst use of the
    // height, so the grid has to be a candidate and not an afterthought.
    for (var c = 1; c <= rooms.length; c++) {
      for (var i = 0; i < ROW_CAPS.length; i++) {
        var plan = layoutFloor(rooms, ROW_CAPS[i], c);
        if (!box) return plan;
        var k = Math.min(box.w / plan.w, box.h / plan.h);
        // A tie goes to the arrangement already chosen, so the floor does
        // not flip between two equally good shapes as the window wobbles.
        if (k > bestK + 0.001) { bestK = k; best = plan; }
      }
    }
    return fillTheBox(best);
  }

  //: One room, sized to the agents in it, and where each of them stands.
  function roomBox(n, rowCap, extra) {
    var cols = Math.max(1, Math.ceil(n / Math.max(1, rowCap)));
    var rows = Math.max(1, Math.ceil(n / cols));
    return {
      cols: cols, rows: rows,
      w: Math.max(ROOM_MIN_W,
                  ROOM_PAD * 2 + cols * SLOT_W + (cols - 1) * SLOT_GAP_X),
      h: ROOM_HEAD + rows * SLOT_H + (rows - 1) * SLOT_GAP_Y
         + ROOM_PAD + ROOM_FOOT + (extra || 0),
    };
  }

  //: Lay the occupied rooms out in one band and report the canvas they need.
  //: Rooms are centred on the band rather than stretched to it, so a room
  //: holding one person is not a tall empty strip beside a room holding three.
  //:
  //: `rowCap` is how many people a room may stack before it grows sideways
  //: instead. It is not a constant because the right answer depends on the
  //: dock: stacking makes the canvas tall and short, spreading makes it wide
  //: and flat, and only one of those matches the box on any given day.
  //: layoutFloor is called once per candidate and the caller keeps the one
  //: that fits largest, so the floor uses the width it has rather than
  //: leaving 400px of it empty beside a floor that shrank to fit the height.
  function layoutFloor(rooms, rowCap, cols) {
    var boxes = rooms.map(function (r) {
      // The meeting room holds its table, and your desk its desk, under
      // the people standing in it.
      var table = (r.z.key === MEETING_KEY || r.z.key === YOU_KEY) && r.of.length
        ? TABLE_SPACE : 0;
      return roomBox(r.of.length, rowCap, table);
    });
    cols = Math.max(1, Math.min(cols || boxes.length, boxes.length));
    var rowCount = Math.ceil(boxes.length / cols);

    // Rooms sit in a grid, not a single band. A row of equal columns reads
    // as a chart; a plan has rooms above and below each other, which is what
    // the owner's reference looks like and what an office looks like.
    var rowsOf = [];
    for (var r0 = 0; r0 < rowCount; r0++) {
      rowsOf.push(boxes.slice(r0 * cols, (r0 + 1) * cols));
    }
    // Every room in a row shares that row's height, and every row is as wide
    // as the widest, so the plan has straight walls rather than a ragged edge.
    var rowH = rowsOf.map(function (row) {
      return row.reduce(function (a, b) { return Math.max(a, b.h); }, 0);
    });
    var rowW = rowsOf.map(function (row) {
      return ROOM_GAP * Math.max(0, row.length - 1) +
        row.reduce(function (a, b) { return a + b.w; }, 0);
    });
    var widest = rowW.reduce(function (a, b) { return Math.max(a, b); }, 0);
    var stack = rowH.reduce(function (a, b) { return a + b; }, 0) +
      ROOM_GAP * Math.max(0, rowCount - 1);

    var need = BAND_PAD * 2 + widest;
    var width = Math.max(need, CANVAS_MIN_W);
    var reserve = topReserve();
    var height = BAND_PAD * 2 + reserve + stack + FLOOR_BAR;

    var out = [];
    var y = BAND_PAD + reserve;
    rowsOf.forEach(function (row, ri) {
      // Each row centred on the plan, so a short last row is not left
      // hanging off one side.
      var x = Math.round((width - rowW[ri]) / 2);
      row.forEach(function (b, ci) {
        var idx = ri * cols + ci;
        var rm = rooms[idx];
        var top = y, left = x;
        x += b.w + ROOM_GAP;

        // Where each agent stands inside THIS room, in canvas pixels. The
        // slot is reserved by the same numbers that sized the room, so an
        // agent can no more overflow its room than a room can overflow the
        // canvas.
        var want = b.cols * SLOT_W + (b.cols - 1) * SLOT_GAP_X;
        var inner = left + Math.round((b.w - want) / 2);
        var innerTop = top + ROOM_HEAD;
        var slots = rm.of.map(function (m, k) {
          var col = k % b.cols, row2 = Math.floor(k / b.cols);
          return {
            m: m,
            left: inner + col * (SLOT_W + SLOT_GAP_X),
            top: innerTop + row2 * (SLOT_H + SLOT_GAP_Y),
          };
        });
        out.push({ z: rm.z, of: rm.of, residents: rm.residents,
                   left: left, top: top,
                   w: b.w, h: rowH[ri], slots: slots });
      });
      y += rowH[ri] + ROOM_GAP;
    });
    return { w: width, h: height, rooms: out };
  }

  function zoneFor(m) {
    var tools = toolsOf(m);
    for (var i = 0; i < ZONES.length; i++) {
      for (var j = 0; j < ZONES[i].tools.length; j++) {
        if (tools.indexOf(ZONES[i].tools[j]) >= 0) return ZONES[i];
      }
    }
    // No tools picked means it reaches everything its owner can, so it has no
    // one desk rather than being hidden.
    return LOUNGE;
  }

  function skillsOf(m) {
    var ids = (m.meta && m.meta.skillIds) || [];
    if (!Array.isArray(ids)) return [];
    return ids.map(function (id) { return S.SKILLS[id] || { name: id, description: "" }; });
  }


  //: --- the clock every movement reads --------------------------------------
  //: A robot crosses the floor at ONE pace, so the length of a journey comes
  //: from its distance: a step to the next desk is quick and a walk to the
  //: meeting room takes as long as it should. The duration is written on
  //: the slot as --d (agent.css reads it for left, top and transform), and
  //: the longest journey in a draw is written on the rooms and the floor,
  //: so a room is finished growing at the moment its last agent steps in.
  //:
  //: It used to be a fixed 2.1s in agent.css and a fixed 2300 here, which
  //: had to be kept in step by hand and made a 30px shuffle take as long as
  //: a trip across the office.
  var WALK_SPEED = 0.42;   // canvas px per ms
  var WALK_MIN = 450, WALK_MAX = 2600;
  function walkDuration(dist) {
    if (!(dist > 0.5)) return 0;
    return Math.round(Math.min(WALK_MAX, Math.max(WALK_MIN, dist / WALK_SPEED)));
  }

  //: The settle at the end of a walk, in walking.css.
  var SETTLE_MS = 500;

  //: One slot is on its way. `walking` goes on now and comes off when the
  //: transition actually ends (transitionend, below, with a timer as the
  //: net for a tab that was hidden), so a bobbing robot always means one
  //: that is moving, for exactly as long as it moves. The lean is the
  //: direction of travel, and nothing else on the slot is touched.
  function startWalk(el, dx, dur) {
    if (!dur) return;
    var until = Date.now() + dur;
    el._walkUntil = Math.max(el._walkUntil || 0, until);
    el.style.setProperty("--d", dur + "ms");
    el.style.setProperty("--lean", (dx > 8 ? 4 : dx < -8 ? -4 : 0) + "deg");
    el.classList.remove("arrived");
    el.classList.add("walking");
    clearTimeout(el._walk);
    el._walk = setTimeout(function () { arrive(el); }, dur + 120);
  }

  function arrive(el) {
    // Another journey was started on this slot since: let that one end it.
    if (Date.now() < (el._walkUntil || 0) - 50) return;
    clearTimeout(el._walk);
    if (!el.classList.contains("walking")) return;
    el.classList.remove("walking");
    el.style.setProperty("--lean", "0deg");
    el.classList.add("arrived");
    clearTimeout(el._settle);
    el._settle = setTimeout(function () { el.classList.remove("arrived"); }, SETTLE_MS);
    // An answer that landed while this robot was walking has been waiting
    // for exactly this moment (startSpeaking).
    var s = S.SPEAKING[el.getAttribute("data-id")];
    if (s && !s.until) draw();
  }

  function watchArrival(el) {
    el.addEventListener("transitionend", function (e) {
      if (e.target !== el) return;
      if (["left", "top", "transform"].indexOf(e.propertyName) < 0) return;
      arrive(el);
    });
  }

  //: Where an agent stands. Changed on its own, so the node moves rather
  //: than being rebuilt somewhere else: a replaced node starts life at the
  //: new coordinates and jumps, and no transition can animate that.
  //: Returns the length of the walk this placing started, or 0.
  function placeSlot(el, slot) {
    var nx = slot.left + "px", ny = slot.top + "px";
    if (!el.isConnected || (el.style.left === nx && el.style.top === ny)) {
      el.style.left = nx;
      el.style.top = ny;
      return 0;
    }
    var dx = slot.left - (parseFloat(el.style.left) || 0);
    var dy = slot.top - (parseFloat(el.style.top) || 0);
    var dur = walkDuration(Math.sqrt(dx * dx + dy * dy));
    startWalk(el, dx, dur);
    el.style.left = nx;
    el.style.top = ny;
    return dur;
  }

  //: How long each slot's walk will be, BEFORE anything is moved, so the
  //: rooms and the floor can be given the longest of them. Reads the slots
  //: already on the floor and changes nothing.
  function measureWalks(slots) {
    var layer = document.getElementById("agents-layer"), longest = 0;
    if (!layer) return 0;
    slots.forEach(function (slot) {
      var el = slotEl(layer, slot.m.id);
      if (!el) return;
      var dx = slot.left - (parseFloat(el.style.left) || 0);
      var dy = slot.top - (parseFloat(el.style.top) || 0);
      longest = Math.max(longest, walkDuration(Math.sqrt(dx * dx + dy * dy)));
    });
    return longest;
  }

  function slotEl(layer, id) {
    return layer.querySelector('.who-slot[data-id="' +
      (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
  }

  //: Answering somebody, as opposed to running a schedule in silence. A run
  //: started from a conversation records where it came from
  //: (agent_activity SOURCE_MEETING, SOURCE_CHANNEL, SOURCE_COLLEAGUE), and
  //: that row is the only thing the dots are drawn from. The thread beside
  //: the floor says "is working..." from the same row, so the two start and
  //: stop together. This is the THINKING.
  var SPEAKING_SOURCES = { meeting: 1, channel: 1, colleague: 1 };
  function typing(id) {
    var a = S.ACTIVITY[id];
    return !!(a && a.state === "working" && SPEAKING_SOURCES[a.source]);
  }

  //: Speaking is the BUBBLE, not the thinking. Agent turns are not
  //: streamed: the whole answer lands in the chat at once, after the run
  //: has finished, and the server says so with speaking_started. The mouth
  //: runs for a time that grows with the answer. Drawing it from the run
  //: working (as before) opened it 1.55 s before the bubble and shut it as
  //: the bubble appeared, measured 2026-10-13.
  var SPEAK_MIN_MS = 1500, SPEAK_MAX_MS = 5000, SPEAK_MS_PER_CHAR = 40;
  function speakFor(chars) {
    return Math.max(SPEAK_MIN_MS, Math.min(SPEAK_MAX_MS, (chars || 0) * SPEAK_MS_PER_CHAR));
  }
  function speaking(id) {
    // A voice being played (voice.js) keeps the mouth going for exactly as
    // long as the sound, whatever the clock below said.
    if (S.VOICING[id]) return true;
    var s = S.SPEAKING[id];
    return !!(s && s.until && s.until > Date.now());
  }

  //: Walk first, then talk. The mouth's time starts when the robot is
  //: standing still: now, or at the end of the walk it is on, which
  //: arrive() hands back here through a draw. No second clock: the walk's
  //: own end is the start. An answer that waited longer than any walk can
  //: take (the floor was on the other tab) is not played late.
  function startSpeaking(id) {
    var s = S.SPEAKING[id];
    if (!s || s.until) return;
    if (Date.now() - s.heard > 2 * WALK_MAX) { delete S.SPEAKING[id]; return; }
    s.until = Date.now() + s.ms;
    setTimeout(draw, s.ms + 30);
    // A closed meeting waits for this answer (inMeeting), so the room has
    // to be looked at again once it is said.
    if (S.MEETING && S.MEETING.ended) setTimeout(draw, s.ms + SPEECH_GRACE_MS + 30);
  }

  //: Each robot a little out of step with the next. Decoration, so it may
  //: come from nothing more than the id.
  function breathOf(id) {
    var h = 0, s = String(id || "");
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 3400;
    return "-" + h + "ms";
  }

  //: What has to be REBUILT rather than patched: the figure's colour runs
  //: through its gradient, its hands and its face, and a renamed agent is a
  //: new label. Everything else about an agent is changed in place, below,
  //: so a change of state no longer restarts its breathing or its stride.
  function slotStructure(m) {
    return [m.id, m.name || "", colourOf(m.id)].join("|");
  }

  function labelFor(m, st) {
    // The role normally, but the STATE the moment there is one worth
    // reading. A dot alone says something is happening without saying
    // what, and "Working 12s" is the whole reason to look at this floor.
    // Asleep is quiet too: the face, the "z" and the card say it, and the
    // label keeps telling one agent from another.
    return st.key === "ready" || st.key === "idle" || st.key === "asleep"
      ? (roleOf(m) || "no role") : st.label;
  }

  var DOTS = '<span class="talk-dots" aria-hidden="true"><i></i><i></i><i></i></span>';

  function slotInner(m) {
    var st = stateOf(m.id), c = colourOf(m.id);
    return '<div class="desk"></div>' +
      '<button class="who" data-id="' + esc(m.id) + '" data-state="' + st.key + '"' +
      (typing(m.id) ? ' data-typing="1"' : "") +
      (speaking(m.id) ? ' data-speaking="1"' : "") +
      (S.SELECTED === m.id ? ' aria-current="true"' : "") +
      // No background: the robot IS the avatar now. The colour stays as the
      // element's own colour so the dot and the label pick it up.
      ' style="color:' + c + '"' +
      ' title="' + esc(st.label) + '">' +
      robot(m.id, st.key) +
      '<i class="dot ' + st.key + '"></i>' +
      (typing(m.id) ? DOTS : "") +
      (st.key === "working" && S.TOOL_NOW[m.id]
        ? '<span class="tool-now">' + esc(S.TOOL_NOW[m.id]) + '</span>' : "") +
      '<span class="who-label"><span class="card-name">' + esc(m.name || m.id) +
        '</span><small>' + esc(labelFor(m, st)) + '</small></span>' +
      '</button>' +
      // Every agent carries its own, because one button on whoever happens to
      // be selected means you must pick somebody before you can talk to them.
      // Naming the agent is what makes the turn private: agent_routing's name
      // rung hands it to that one agent and nobody else answers.
      '<a class="who-chat" data-id="' + esc(m.id) + '" target="_top"' +
        ' title="Ask ' + esc(m.name || m.id) + ' on their own"' +
        ' href="/tasks/agents?ask=' +
        encodeURIComponent((m.name || m.id) + ", ") + '">Chat</a>';
  }

  //: Bring a slot that already exists up to date WITHOUT rebuilding it.
  //: Only what changed is touched: the state and its face, the light, the
  //: badge, the label. The figure itself, mid-breath or mid-stride, is left
  //: exactly where its animation has it.
  function patchSlot(el, m) {
    var who = el.querySelector(".who");
    if (!who) { el.innerHTML = slotInner(m); return; }
    var st = stateOf(m.id);
    if (who.getAttribute("data-state") !== st.key) {
      // Work ends a dance: the floor never dances over a state.
      if (!canDance(m.id)) stopDance(el, m.id);
      // Waking up: a stretch before anything else, so a run starting at a
      // quiet desk is seen to start.
      if (who.getAttribute("data-state") === "asleep") {
        var slot = who.closest(".who-slot");
        if (slot) {
          slot.classList.add("waking");
          clearTimeout(slot._wake);
          slot._wake = setTimeout(function () { slot.classList.remove("waking"); }, 900);
        }
      }
      who.setAttribute("data-state", st.key);
      who.setAttribute("title", st.label);
      var f = who.querySelector(".bot-face");
      if (f) {
        f.innerHTML = face(m.id, st.key);
        // Restarted on purpose: a face that changed is a thing that
        // happened, and the short fade in speaking.css says so.
        f.classList.remove("swap");
        void f.getBoundingClientRect();
        f.classList.add("swap");
      }
      var dot = who.querySelector(".dot");
      if (dot) dot.className = "dot " + st.key;
    }
    // The dots and the mouth are two things now, each on its own: the dots
    // while the answer is being thought about, the mouth once it has landed.
    var thinking = typing(m.id), dots = who.querySelector(".talk-dots");
    if (thinking && !dots) {
      who.setAttribute("data-typing", "1");
      who.querySelector(".dot").insertAdjacentHTML("afterend", DOTS);
    } else if (!thinking && dots) {
      who.removeAttribute("data-typing");
      dots.remove();
    }
    var talking = speaking(m.id);
    if (talking !== (who.getAttribute("data-speaking") === "1")) {
      if (talking) who.setAttribute("data-speaking", "1");
      else who.removeAttribute("data-speaking");
    }
    if ((S.SELECTED === m.id) !== (who.getAttribute("aria-current") === "true")) {
      if (S.SELECTED === m.id) who.setAttribute("aria-current", "true");
      else who.removeAttribute("aria-current");
    }
    var tool = st.key === "working" ? (S.TOOL_NOW[m.id] || "") : "";
    var badge = who.querySelector(".tool-now");
    if (tool && !badge) {
      who.querySelector(".who-label").insertAdjacentHTML("beforebegin",
        '<span class="tool-now">' + esc(tool) + '</span>');
    } else if (!tool && badge) {
      badge.remove();
    } else if (badge && badge.textContent !== tool) {
      badge.textContent = tool;
    }
    var small = who.querySelector(".who-label small"), label = labelFor(m, st);
    if (small && small.textContent !== label) small.textContent = label;
  }

  //: Who is in a meeting right now.
  //:
  //: Only from the run's own source. agent_routing calls a meeting and every
  //: agent answers at once, and the run each of them starts records
  //: `meeting` (agent_activity.SOURCE_MEETING). Guessing it instead, from
  //: several runs beginning at about the same time, would draw a meeting
  //: that nobody called.
  //: How long after the last word a meeting is still standing. A round goes
  //: round the table ONE AGENT AT A TIME: the panel asks each in turn and
  //: awaits it, so at any instant six of seven are already finished. Asking
  //: "is this agent working right now" put a single robot in the meeting
  //: room while the rest sat at their desks, and a gathering never appeared.
  var MEETING_SECONDS = 90;

  //: Is a meeting happening at all? True while anybody is mid-turn in one,
  //: and for a short while after the last of them finished, so the team
  //: arrives and leaves together instead of trickling through one at a time.
  function meetingIsOn() {
    var newest = 0;
    for (var id in S.ACTIVITY) {
      var a = S.ACTIVITY[id];
      if (!a || a.source !== "meeting") continue;
      if (a.state === "working") return true;
      var at = Date.parse(a.last_run_at || "");
      if (at > newest) newest = at;
    }
    return !!newest && (Date.now() - newest) / 1000 <= MEETING_SECONDS;
  }

  //: How long the room stays together after the round closes, so the last
  //: answer is finished where it was said before everybody walks back.
  var MEETING_LINGER_MS = 4000;
  //: And never before the last word in it is finished: the last answer and
  //: meeting_ended arrive milliseconds apart, and an answer of 100
  //: characters talks for 4 s, so a fixed linger had the last speaker walk
  //: back mid-sentence (review, 2026-10-14).
  var SPEECH_GRACE_MS = 300;

  //: Closed, lingered, and nobody in it mid-sentence: the room is free.
  function meetingOver(m) {
    return !!(m && m.ended && Date.now() - m.ended > MEETING_LINGER_MS &&
              !stillTalking(m));
  }

  //: Is anybody in this meeting still talking, or still walking in to say
  //: something they have been given? Then the room stays.
  function stillTalking(m) {
    var now = Date.now();
    for (var i = 0; i < m.ids.length; i++) {
      var s = S.SPEAKING[m.ids[i]];
      if (!s) continue;
      if (!s.until) return true;
      if (s.until + SPEECH_GRACE_MS > now) return true;
    }
    return false;
  }

  //: The round itself says who is in it: meeting_started names everybody
  //: at once, in speaking order, and meeting_ended closes it. From the first
  //: of those this page hears, that wins. The source rule below, with its
  //: MEETING_SECONDS guess, is only for a page that opened mid-meeting and
  //: has heard neither (measured 2026-10-13: driven by sources, 0 robots
  //: were in the room at the first answer, and a private chat drew 3).
  function inMeeting(id) {
    var m = S.MEETING, a = S.ACTIVITY[id];
    if (m && !meetingOver(m)) {
      if (m.ids.indexOf(id) !== -1) return true;
      // The round named everybody: nobody else is in it.
      if (m.heard) return false;
      // Opened from the runs (this page missed meeting_started): the ids are
      // only the speakers heard so far, and the source rule fills in the
      // rest, but only runs begun since the last meeting closed. An agent
      // whose meeting run was the previous round's is not in this one.
      return bySource(a) && beganAfter(a, m.after);
    }
    if (m) {
      // The last meeting this page heard is over. It still stops stale
      // sources from drawing it again, but not a NEW round: a run that
      // began after it closed is the next meeting, whose meeting_started
      // this page may not have heard (a reconnect in between, or the
      // poll's truth arriving first). Until 2026-10-16 one finished
      // meeting blocked every later one from the source rule for good.
      return !!(a && a.state === "working") && bySource(a) && beganAfter(a, m.ended);
    }
    return bySource(a);
  }
  //: Still recorded, still in the room: the source is the run's own, so
  //: this never puts an agent in a meeting it was not part of.
  function bySource(a) {
    if (!a || a.source !== "meeting") return false;
    return a.state === "working" || meetingIsOn();
  }
  function beganAfter(a, when) {
    if (!when) return true;
    return (Date.parse((a && a.last_run_at) || "") || 0) > when;
  }
  //: A meeting this page opens from the runs, not from meeting_started.
  //: `after` is when the last one closed, so its stragglers stay out.
  function meetingFromRuns(id) {
    return { ids: [id], ended: null, heard: false,
             after: (S.MEETING && S.MEETING.ended) || S.LAST_MEETING_END || 0 };
  }

  //: Bring the agents layer in line with the plan, WITHOUT rebuilding it.
  //: Nodes that already exist are moved and patched; only an agent that is
  //: new gets created, and only one whose colour or name changed is redrawn.
  function syncAgents(slots) {
    var layer = document.getElementById("agents-layer");
    if (!layer) return;
    var seen = {};
    slots.forEach(function (slot) {
      var m = slot.m, id = m.id;
      seen[id] = 1;
      var el = slotEl(layer, id);
      if (!el) {
        el = document.createElement("div");
        el.className = "who-slot";
        el.setAttribute("data-id", id);
        el.style.width = SLOT_W + "px";
        el.style.setProperty("--bot-w", BOT_W + "px");
        el.style.setProperty("--bot-h", BOT_H + "px");
        el.style.setProperty("--breath", breathOf(id));
        // Placed before it is in the document, so it does not animate in
        // from the corner the first time it is drawn.
        placeSlot(el, slot);
        startSpeaking(id);
        el.innerHTML = slotInner(m);
        el.setAttribute("data-sig", slotStructure(m));
        watchArrival(el);
        // Somebody new on a floor already drawn (an agent just made) pops
        // up at its desk; the first draw's agents were simply there.
        if (FLOOR_DRAWN) {
          el.classList.add("born");
          setTimeout(function () { el.classList.remove("born"); }, 700);
        }
        layer.appendChild(el);
        return;
      }
      placeSlot(el, slot);
      // On its way somewhere: arrive() starts the mouth when it gets there.
      if (!el.classList.contains("walking")) startSpeaking(id);
      var sig = slotStructure(m);
      if (el.getAttribute("data-sig") !== sig) {
        el.innerHTML = slotInner(m);
        el.setAttribute("data-sig", sig);
      } else {
        patchSlot(el, m);
      }
    });
    // An agent the search no longer matches, or one that was deleted.
    Array.prototype.slice.call(layer.children).forEach(function (el) {
      if (!seen[el.getAttribute("data-id")]) el.remove();
    });
  }

  //: How long a handoff keeps two robots visibly together, at most. The
  //: server only sends the last few minutes, and this is the slice of that
  //: which reads as "now" rather than "recently".
  var TALK_SECONDS = 90;

  //: A handoff is a fact about a RUN: the asker's run called a colleague
  //: and waited. It ends when that run ends, which run_finished says and
  //: the poll's state says. Until 2026-10-16 the line, the walk and the
  //: "Asking X…" bubble lived the whole 90 s whatever the asker was doing,
  //: and nothing redrew when the 90 s ran out, so two robots stood together
  //: for up to two minutes after the chat was over ("if they done talking
  //: they didnt stop collaborating").
  function _fresh(h) {
    var at = Date.parse(h && h.at || "");
    if (!at) return false;
    if ((Date.now() - at) / 1000 > TALK_SECONDS) return false;
    var a = S.ACTIVITY[h.from];
    return !a || a.state === "working";
  }

  //: Redraw the moment the oldest live handoff runs out, so a line never
  //: outlives its window waiting for the next event or poll.
  var TALK_TIMER = null;
  function redrawWhenTalkEnds(handoffs) {
    var soonest = 0;
    handoffs.forEach(function (h) {
      var until = Date.parse(h && h.at || "") + TALK_SECONDS * 1000;
      if (until > Date.now() && (!soonest || until < soonest)) soonest = until;
    });
    if (TALK_TIMER) { clearTimeout(TALK_TIMER); TALK_TIMER = null; }
    if (soonest) TALK_TIMER = setTimeout(function () { TALK_TIMER = null; draw(); },
                                         soonest - Date.now() + 30);
  }

  //: How far along the line an asking robot walks. Changed 2026-10-08 from a
  //: FRACTION of the journey to a fixed GAP at the far end, because a
  //: fraction cannot be right for both lengths: 0.28 of a long walk stopped
  //: in open floor, and the 0.82 that fixed that landed the walker on top of
  //: a colleague at the next desk, name chips and all.
  //:
  //: The gap is measured from the FIGURE and not from the slot. A slot is
  //: 140px of mostly padding, so leaving a whole one meant a short trip
  //: ended before the walker had even left its own room, which is what the
  //: owner saw and reported as "they are not moving or going to each other".
  //:
  //: The gap depends on the DIRECTION of approach (2026-10-12). A slot is
  //: a column, a robot with its name and its Chat pill under it, so a
  //: walker arriving from above with a side-by-side gap stood on the
  //: colleague's head, name chip across their face. Beside a colleague the
  //: gap is the figure's width; above or below it is the slot's height.
  function walkFraction(a, b) {
    var px = (b.x - a.x) * CANVAS_W / 100;
    var py = (b.y - a.y) * CANVAS_H / 100;
    var len = Math.sqrt(px * px + py * py);
    if (!len) return 0;
    var ux = px / len, uy = py / len;
    var gap = Math.sqrt(Math.pow(ux * (BOT_W + 34), 2) +
                        Math.pow(uy * (SLOT_H + 4), 2));
    return Math.max(0, len - gap) / len;
  }

  //: Every collaboration the floor may draw right now, worked out ONCE per
  //: draw and shared by the walk, the line and the bubble, so the three
  //: cannot disagree about where anybody is going or how long it takes.
  //: Drawn ONLY from HANDOFFS, which is ONLY tasks.agent_step rows. Nothing
  //: here may be invented: a line between the wrong pair states a
  //: collaboration that did not happen, which is worse than drawing none.
  //:
  //:   lines   one per pair, from the asker's desk to the colleague
  //:   nudges  one per asker (the latest), how far it walks along that line
  function planTalk() {
    var lines = [], nudges = {}, seen = {}, live = [];
    S.HANDOFFS.forEach(function (h) {
      if (!h || !h.from || !h.to || h.from === h.to || !_fresh(h)) return;
      live.push(h);
      var a = S.AT[h.from], b = S.AT[h.to];
      // One of them is filtered out of the search, or in a room nobody is
      // drawing. A line to nowhere is worse than no line.
      if (!a || !b) return;
      var key = h.from + ">" + h.to;
      var refused = h.status === "refused" || h.status === "failed";
      // Percentages are of different axes, so the angle is computed in the
      // floor's own pixel space and the line is placed back in percentages.
      var px = (b.x - a.x) * CANVAS_W / 100;
      var py = (b.y - a.y) * CANVAS_H / 100;
      var len = Math.sqrt(px * px + py * py);
      var f = walkFraction(a, b);
      var nudge = { from: h.from, to: h.to, key: key, refused: refused,
                    dx: Math.round(px * f), dy: Math.round(py * f),
                    dist: len * f };
      nudges[h.from] = nudge;
      if (seen[key]) return;
      seen[key] = 1;
      lines.push({ key: key, from: h.from, to: h.to, refused: refused,
                   x: a.x, y: a.y, len: Math.round(len),
                   rot: (Math.atan2(py, px) * 180 / Math.PI).toFixed(2),
                   dur: walkDuration(nudge.dist) });
    });
    redrawWhenTalkEnds(live);
    return { lines: lines, nudges: nudges };
  }

  //: The longest journey the nudges will start THIS draw. A nudge already
  //: standing is not a journey.
  function measureNudges(nudges) {
    var layer = document.getElementById("agents-layer"), longest = 0;
    if (!layer) return 0;
    Array.prototype.forEach.call(layer.children, function (el) {
      var id = el.getAttribute("data-id"), n = nudges[id];
      var want = n ? "translate(" + n.dx + "px," + n.dy + "px)" : "";
      if (el.style.transform === want) return;
      var dist = n ? n.dist : (el._nudge ? el._nudge.dist : 0);
      longest = Math.max(longest, walkDuration(dist));
    });
    return longest;
  }

  //: Move each asking robot toward the colleague it is actually waiting on,
  //: and walk it home the moment the handoff falls out of the data: a robot
  //: left standing beside a colleague long after the fact is the staleness
  //: lie this floor is supposed to avoid.
  //:
  //: Only a CHANGE starts a walk. The transform is compared with what the
  //: slot already has, so a redraw mid-journey (an event, the poll) leaves
  //: the journey alone instead of restarting its stride.
  function applyNudges(nudges) {
    var layer = document.getElementById("agents-layer");
    if (!layer) return;
    Array.prototype.forEach.call(layer.children, function (el) {
      var id = el.getAttribute("data-id"), n = nudges[id];
      var want = n ? "translate(" + n.dx + "px," + n.dy + "px)" : "";
      if (el.style.transform === want) return;
      if (n) {
        startWalk(el, n.dx, walkDuration(n.dist));
        el._nudge = n;
      } else if (el._nudge) {
        startWalk(el, -el._nudge.dx, walkDuration(el._nudge.dist));
        el._nudge = null;
      }
      // The whole slot walks, so the robot keeps its own name and its own
      // Chat pill with it. Left behind, that pill would offer a conversation
      // with whoever is standing there now, which is nobody.
      el.style.transform = want;
    });
  }

  //: The lines between robots, kept across redraws like everything else on
  //: this floor: a new one is DRAWN, at the pace the asking robot walks it,
  //: and one whose handoff has gone stale fades rather than vanishing.
  function syncLines(lines) {
    var layer = document.getElementById("floor-lines");
    if (!layer) return;
    var seen = {};
    lines.forEach(function (ln) {
      seen[ln.key] = 1;
      var el = layer.querySelector('.talk-line[data-key="' +
        (window.CSS && CSS.escape ? CSS.escape(ln.key) : ln.key) + '"]');
      if (!el) {
        el = document.createElement("div");
        el.className = "talk-line drawing";
        el.setAttribute("data-key", ln.key);
        el.setAttribute("data-from", ln.from);
        el.setAttribute("data-to", ln.to);
        el.style.setProperty("--d", ln.dur + "ms");
        el.addEventListener("animationend", function (e) {
          if (e.animationName === "line-draw") el.classList.remove("drawing");
          if (e.animationName === "line-fade") el.remove();
        });
        layer.appendChild(el);
      }
      el.classList.remove("fading");
      el.classList.toggle("refused", ln.refused);
      el.style.left = ln.x + "%";
      el.style.top = ln.y + "%";
      el.style.width = ln.len + "px";
      el.style.setProperty("--rot", ln.rot + "deg");
    });
    Array.prototype.slice.call(layer.children).forEach(function (el) {
      if (seen[el.getAttribute("data-key")]) return;
      if (el.classList.contains("fading")) return;
      el.classList.add("fading");
      // The net, for a tab whose animations are paused.
      setTimeout(function () { el.remove(); }, 700);
    });
  }

  //: What the asking robot is saying, over its own head. The bubble is a
  //: child of the robot's slot, so it goes where the robot goes: it used to
  //: be pinned where the robot WOULD be and hung in empty air for the
  //: length of the walk, which read as somebody else talking.
  function syncSays(nudges) {
    var layer = document.getElementById("agents-layer");
    if (!layer) return;
    Array.prototype.forEach.call(layer.children, function (el) {
      var id = el.getAttribute("data-id"), n = nudges[id];
      var say = el.querySelector(".say");
      if (!n) {
        if (say && !say.classList.contains("going")) {
          say.classList.add("going");
          setTimeout(function () { say.remove(); }, 650);
        }
        return;
      }
      var to = nameOf(n.to) || "a colleague";
      var text = n.refused ? "Could not reach " + to : "Asking " + to + "…";
      if (!say || say.classList.contains("going")) {
        if (say) say.remove();
        say = document.createElement("div");
        say.className = "say";
        el.appendChild(say);
      }
      say.classList.toggle("refused", n.refused);
      if (say.textContent !== text) say.textContent = text;
    });
  }

  //: Where a talk line finds the two robots it joins: the middle of the
  //: figure, in percentages of the canvas, so the line survives a zoom
  //: without being recomputed.
  function markAt(slot) {
    S.AT[slot.m.id] = {
      x: (slot.left + SLOT_W / 2) / CANVAS_W * 100,
      y: (slot.top + BOT_H / 2) / CANVAS_H * 100,
    };
  }

  //: The room's header and footer, as in the owner's reference: a lit dot
  //: and the name on the left, how cleanly this room's runs finished on the
  //: right, and the totals along the bottom edge. CLEAN is this room's runs
  //: weighted by their own success rate, not an average of percentages, so
  //: a room with eight hundred runs is not outvoted by one with three.
  function roomNumbers(residents) {
    var runs = 0, done = 0, spent = 0, working = 0;
    residents.forEach(function (m) {
      var st = S.STATS[m.id] || {};
      runs += st.runs || 0;
      if (st.runs && st.success_pct != null) done += st.runs * st.success_pct / 100;
      spent += st.cost_usd || 0;
      if (stateOf(m.id).key === "working") working++;
    });
    return { runs: runs, spent: spent, working: working,
             pct: runs ? Math.round(100 * done / runs) : null };
  }

  function headHtml(z, n) {
    return '<span class="zone-name"><i class="zone-dot"></i>' + esc(z.label) + '</span>' +
      (n.pct == null ? "" : '<span class="zone-badge">' + n.pct + '% CLEAN</span>');
  }
  function footHtml(n) {
    return '<span>RUNS: ' + n.runs + '</span>' +
      '<span>COST: $' + n.spent.toFixed(2) + '</span>';
  }

  //: The rooms, kept across draws the way the agents are. A room that is
  //: already on the floor is MOVED to its new place and size, on the same
  //: clock as the people walking into it (--d), and only the words on it
  //: that changed are rewritten. Rebuilding the rooms by innerHTML, which
  //: this did until 2026-10-12, snapped every wall to its new place while
  //: the robots were still halfway across the floor.
  //:
  //: `longest` is the longest walk this draw started, so the meeting table
  //: in a room is laid when the last agent arrives and not before.
  function syncRooms(plan, met, longest) {
    var layer = document.getElementById("floor-rooms");
    if (!layer) return;
    var seen = {}, live = met.length > 0;
    plan.rooms.forEach(function (r) {
      var z = r.z, key = z.key;
      seen[key] = 1;
      var n = roomNumbers(r.residents || r.of);
      var el = layer.querySelector('.zone[data-room="' + esc(key) + '"]');
      if (!el) {
        el = document.createElement("section");
        el.className = "zone arriving";
        el.setAttribute("data-room", key);
        el.style.setProperty("--glow", z.glow);
        el.innerHTML =
          '<div class="zone-head">' + headHtml(z, n) + '</div>' +
          '<div class="zone-foot">' + footHtml(n) + '</div>';
        el.addEventListener("animationend", function (e) {
          if (e.animationName === "room-in") el.classList.remove("arriving");
          if (e.animationName === "room-out") el.remove();
        });
        // Placed before it is in the document, so it appears where it
        // belongs rather than sliding in from the corner.
        el.style.left = r.left + "px"; el.style.top = r.top + "px";
        el.style.width = r.w + "px"; el.style.height = r.h + "px";
        layer.appendChild(el);
      } else {
        el.classList.remove("leaving");
        clearTimeout(el._leave);
        el.style.setProperty("--d", longest + "ms");
        el.style.left = r.left + "px"; el.style.top = r.top + "px";
        el.style.width = r.w + "px"; el.style.height = r.h + "px";
        var head = el.querySelector(".zone-head"), hh = headHtml(z, n);
        if (head && head.innerHTML !== hh) head.innerHTML = hh;
        var foot = el.querySelector(".zone-foot"), fh = footHtml(n);
        if (foot && foot.innerHTML !== fh) foot.innerHTML = fh;
      }
      // The lights: on while somebody who desks here is working. From the
      // same recorded state as the robot's face, so the two cannot disagree.
      el.setAttribute("data-busy", n.working ? "1" : "0");

      if (key === YOU_KEY) {
        // Your desk, and whether anybody is standing at it.
        if (!el.querySelector(".you-desk")) {
          el.insertAdjacentHTML("beforeend",
            '<div class="you-desk" aria-hidden="true">' +
              '<svg viewBox="0 0 120 70"><rect x="10" y="38" width="100" height="10" rx="3"/>' +
              '<rect x="18" y="48" width="6" height="18" rx="2"/><rect x="96" y="48" width="6" height="18" rx="2"/>' +
              '<rect x="44" y="16" width="32" height="20" rx="3" class="you-screen"/>' +
              '<circle cx="60" cy="58" r="7" class="you-head"/><rect x="50" y="64" width="20" height="6" rx="3" class="you-body"/></svg>' +
              '<span class="you-label">You</span></div>');
        }
        el.setAttribute("data-live", r.of.length ? "1" : "0");
        return;
      }
      if (key !== MEETING_KEY) return;
      // Said on the room itself while a meeting is running, so the table in
      // it is never ambiguous about whether it is in use. Laid when the
      // team ARRIVES (--d is the walk), cleared when the meeting is over.
      el.setAttribute("data-live", live ? "1" : "0");
      var table = el.querySelector(".meeting-table");
      var words = met.length + (met.length === 1 ? " agent" : " agents") + " in a meeting";
      if (live) {
        if (!table || table.classList.contains("leaving")) {
          if (table) table.remove();
          table = document.createElement("div");
          table.className = "meeting-table";
          table.style.setProperty("--d", longest + "ms");
          el.insertBefore(table, el.querySelector(".zone-foot"));
        }
        if (table.textContent !== words) table.textContent = words;
      } else if (table && !table.classList.contains("leaving")) {
        table.classList.add("leaving");
        setTimeout(function () { table.remove(); }, 450);
      }
    });
    // A room whose last agent the search hid, or that emptied.
    Array.prototype.slice.call(layer.querySelectorAll(".zone")).forEach(function (el) {
      if (seen[el.getAttribute("data-room")] || el.classList.contains("leaving")) return;
      el.classList.add("leaving");
      el._leave = setTimeout(function () { el.remove(); }, 600);
    });
  }

  //: Has the floor been drawn once? Until then it has no shape worth
  //: easing from, and the first plan has to simply appear.
  var FLOOR_DRAWN = false;

  function drawRooms() {
    var q = (document.getElementById("q").value || "").trim().toLowerCase();
    var shown = S.AGENTS.filter(function (m) {
      if (!q) return true;
      return (m.name || "").toLowerCase().indexOf(q) >= 0 ||
             roleOf(m).toLowerCase().indexOf(q) >= 0 ||
             toolsOf(m).join(" ").toLowerCase().indexOf(q) >= 0;
    });

    var byZone = {};
    shown.forEach(function (m) {
      var z = zoneFor(m);
      (byZone[z.key] = byZone[z.key] || { z: z, of: [] }).of.push(m);
    });

    // Whoever is in a meeting is IN THE MEETING ROOM, not at their desk.
    // Moving them here, BEFORE the layout runs, is the whole mechanism: a
    // room is however big the agents in it make it, so the meeting room
    // grows to hold everybody, their slots are ordinary slots in it, and the
    // change of coordinates IS the walk there. No seat geometry of its own,
    // no band floating above the floor, and they arrive somewhere that is
    // really on the plan rather than hovering over it.
    var met = [], blocked = [], here = {};
    Object.keys(byZone).forEach(function (k) {
      here[k] = byZone[k].of.filter(function (m) {
        // Waiting on you outranks a meeting: a robot cannot be in two
        // rooms, and the one with a question for you stands at your desk.
        if (atYourDesk(m.id)) { blocked.push(m); return false; }
        if (!inMeeting(m.id)) return true;
        met.push(m);
        return false;
      });
    });

    // Only rooms somebody works in, plus the meeting room, which is always
    // there. A room whose people are all in the meeting stays on the plan
    // with its desks visibly empty, which is the point: you can see they
    // left. `residents` is who DESKS here and `of` is who is standing here
    // now, so a room's totals stay its own while a meeting is running.
    var occupied = ZONES.concat([LOUNGE, YOU])
      .filter(function (z) { return z.key === MEETING_KEY || z.key === YOU_KEY || byZone[z.key]; })
      .map(function (z) {
        var mine = here[z.key] || [];
        return { z: z, residents: (byZone[z.key] && byZone[z.key].of) || [],
                 of: z.key === MEETING_KEY ? mine.concat(met)
                   : z.key === YOU_KEY ? blocked : mine };
      });

    // The canvas is whatever the rooms need, and the rooms are whatever the
    // agents need. Set before anything is positioned, because AT records
    // percentages of it.
    var plan = bestLayout(occupied);
    CANVAS_W = plan.w;
    CANVAS_H = plan.h;

    // The agents are NOT part of the rooms. They live in their own layer
    // so that redrawing a room does not rebuild a robot mid-walk.
    var allSlots = [];
    plan.rooms.forEach(function (r) {
      r.slots.forEach(function (slot) { allSlots.push(slot); });
    });
    // No seats to assign: whoever is in the meeting was put in the meeting
    // room above and already has an ordinary slot there.
    allSlots.forEach(markAt);

    // How long this draw's journeys take, measured BEFORE anything moves,
    // so the rooms and the floor can be put on the same clock as the
    // longest of them. Nothing moving means nothing to ease: a resize or a
    // first draw simply takes its shape.
    var talk = planTalk();
    var longest = Math.max(measureWalks(allSlots), measureNudges(talk.nudges));

    var floor = document.getElementById("rooms");
    if (floor) {
      floor.classList.toggle("reflow", FLOOR_DRAWN && longest > 0);
      floor.style.setProperty("--d", longest + "ms");
      floor.style.width = CANVAS_W + "px";
      floor.style.height = CANVAS_H + "px";
      floor.setAttribute("data-meeting", met.length ? String(met.length) : "");
    }

    syncRooms(plan, met, longest);
    syncAgents(allSlots);
    applyNudges(talk.nudges);
    syncLines(talk.lines);
    syncSays(talk.nudges);
    FLOOR_DRAWN = true;

    var working = shown.filter(function (m) { return stateOf(m.id).key === "working"; }).length;
    var newest = recentRows()[0];

    // The bar the mockup puts along the bottom. "Call a meeting" is real: it
    // hands the chat the words the routing ladder matches as a meeting, so
    // every agent answers and none may pass. There is deliberately no
    // "simulate collaboration": agents cannot address each other, and a
    // button that pretends otherwise is the one thing this page must not do.
    var bar = '<span class="now tick"><i class="dot ' + (working ? "working" : "ready") + '"></i> ' +
        (working ? '<b>' + working + '</b> working now'
                 : (newest ? '<b>' + esc(newest.name) + '</b> ' +
                    esc(newest.a.state === "working" ? "is working"
                        : (newest.a.last_status || "finished")) + ' ' +
                    esc(ago(newest.a.last_run_at))
                  : "nothing has run yet")) + '</span>' +
      // Only in the dock on the agents page, where the chat is the page
      // around this floor and the floor's own dock is not drawn. Elsewhere
      // the buttons stand beside The Brain (#brain-actions), out from under
      // the chat windows.
      (document.documentElement.classList.contains("embed")
        ? '<span class="right">' +
          '<a class="btn" target="_top" href="/tasks/agents?ask=' +
            encodeURIComponent("everyone answer: ") + '">Call a team meeting</a>' +
          '</span>'
        : "");
    var rooms = document.getElementById("floor-rooms");
    var barEl = rooms && rooms.querySelector(".floor-bar");
    if (rooms && !barEl) {
      barEl = document.createElement("div");
      barEl.className = "floor-bar";
      rooms.appendChild(barEl);
    }
    if (barEl && barEl.innerHTML !== bar) barEl.innerHTML = bar;

    // The canvas just changed shape, so whatever scale was on it is stale.
    drawZoom();

    document.getElementById("sub").innerHTML =
      '<i class="dot ' + (working ? "working" : "ready") + '"></i>' +
      S.AGENTS.length + (S.AGENTS.length === 1 ? " agent" : " agents") +
      (working ? " &middot; " + working + " working now" : " &middot; none working right now");
  }

  // 67 skills ship with the image and an agent is given some of them, but the
  // only place one was ever visible is a section of the edit form collapsed by
  // default. Each becomes a message rather than a button that fires: a turn
  // costs money, so the composer is handed the wording and the person sends it.
  function canDo(m) {
    var mine = skillsOf(m);
    if (!mine.length) {
      return '<p class="section-title" style="margin-top:18px">What to ask for</p>' +
        '<p class="empty">This agent has no ready-made skills yet. You can still ' +
        'ask it anything, or give it some when you edit it.</p>';
    }
    var name = m.name || "this agent";
    return '<p class="section-title" style="margin-top:18px">What you can ask ' +
      esc(name) + ' for</p><div class="tags">' +
      mine.map(function (s) {
        var msg = name + ", " + saying(s.name);
        // The agent's id rides along, so the page around a hosted floor can
        // open this agent's own conversation instead of asking the room.
        return '<a class="tag skill" target="_top" data-id="' + esc(m.id) +
          '" href="/tasks/agents?ask=' +
          encodeURIComponent(msg) + '" title="' + esc(s.description) + '">' +
          esc(saying(s.name)) + '</a>';
      }).join("") + '</div>';
  }

  //: Whether the agent card is folded to its header row. Per browser, and
  //: guarded like every other localStorage read here.
  var FOLD_KEY = "aiuiOfficeCardFolded";
  function sideFolded() {
    try { return localStorage.getItem(FOLD_KEY) === "1"; } catch (e) { return false; }
  }
  function setSideFolded(folded) {
    try {
      if (folded) localStorage.setItem(FOLD_KEY, "1");
      else localStorage.removeItem(FOLD_KEY);
    } catch (e) { /* obeyed now, forgotten next time */ }
  }

  function drawSide() {
    // The CARD, not the whole column. The to-do above it and the
    // conversation below it are not redrawn, and must not be: rebuilding the
    // thread would throw away the round in flight.
    var side = document.getElementById("side-agent");
    if (!side) return;
    var m = S.AGENTS.filter(function (a) { return a.id === S.SELECTED; })[0];
    // In the card the details are an overlay, not a column: standing empty it
    // was taking 340px of the width the floor needed, which is most of why
    // the office looked cramped in there.
    var wrap = document.querySelector(".wrap");
    if (wrap) wrap.classList.toggle("picked", !!m);
    if (!m) {
      side.innerHTML = '<p class="empty">Pick an agent to see what it has been doing.</p>';
      return;
    }
    var s = S.STATS[m.id] || {}, st = stateOf(m.id), a = S.ACTIVITY[m.id];
    var success = (s.success_pct == null) ? "&mdash;" : s.success_pct + "%";
    var avg = s.avg_seconds ? s.avg_seconds + "s" : "&mdash;";
    var cost = s.cost_usd ? "$" + s.cost_usd.toFixed(3) : "$0";

    var recent = a && a.last_run_at
      ? '<ul class="rows"><li><span>' +
          esc(a.state === "working" ? "Running now"
              : "Last run " + (a.last_status ? a.last_status : "finished")) +
          '</span><span class="when">' + esc(ago(a.last_run_at)) + '</span></li>' +
        (a.last_duration_seconds != null
          ? '<li><span>Took ' + a.last_duration_seconds + 's</span></li>' : "") +
        (a.source ? '<li><span>Started from ' + esc(a.source) + '</span></li>' : "") +
        '</ul>'
      : '<p class="empty">No runs recorded yet.</p>';

    side.classList.toggle("folded", sideFolded());
    side.innerHTML =
      '<button class="side-shut" type="button" id="side-shut" ' +
        'aria-label="Close the details">&times;</button>' +
      '<div class="side-head">' +
        '<div class="side-bot">' + robot(m.id, st.key, "p") + '</div>' +
        '<div class="side-who"><h2>' + esc(m.name || m.id) + '</h2>' +
        '<div class="st"><i class="dot ' + st.key + '"></i>' + esc(st.label) + '</div></div>' +
        // The card folds to this row, so the conversation under it gets the
        // column. Remembered per browser, like the conversation's own bar.
        '<button class="side-fold" type="button" id="side-fold" ' +
          'aria-expanded="' + (sideFolded() ? "false" : "true") + '" ' +
          'aria-controls="side-agent" title="' +
          (sideFolded() ? "Show the details" : "Fold the details away") + '">' +
          '<span class="deskchat-caret" aria-hidden="true"></span></button>' +
      '</div>' +
      '<p class="role" style="margin:9px 0 0;color:var(--muted)">' +
        esc(roleOf(m) || "No role set") + '</p>' +
      '<p class="empty" style="margin:6px 0 0">' + esc(descOf(m) || "No description.") + '</p>' +
      '<div class="stats">' +
        '<div class="stat"><div class="k">Total runs</div><div class="v">' + (s.runs != null ? s.runs : 0) + '</div></div>' +
        '<div class="stat"><div class="k">Average run</div><div class="v">' + avg + '</div></div>' +
        '<div class="stat"><div class="k">Finished cleanly</div><div class="v">' + success + '</div></div>' +
        '<div class="stat"><div class="k">Spent</div><div class="v">' + cost + '</div></div>' +
      '</div>' +
      '<p class="section-title" style="margin-top:18px">Colour</p>' +
      '<div class="tags swatches">' +
        // The agent's own colour first, the one it wears on its card.
        [ownPalette(m.id)].concat(PALETTES).map(function (pal) {
          var own = pal.hue === "own";
          return '<button class="swatch" type="button" data-hue="' + pal.hue +
            '" title="' + (own ? "Its own colour, as on its card" : pal.hue) +
            '" aria-label="' + (own
              ? "Give " + esc(m.name || m.id) + " its own colour"
              : "Make " + esc(m.name || m.id) + " " + pal.hue) +
            '" style="background:' + pal.body +
            ';border-color:' + pal.accent + '"' +
            (paletteOf(m.id).hue === pal.hue ? ' aria-current="true"' : "") +
            '></button>';
        }).join("") +
      '</div>' +
      '<p class="section-title" style="margin-top:18px">Voice</p>' +
      // How it sounds when its answers are read aloud (voice.js). Kept per
      // browser; every agent has one of its own from its id until picked.
      voiceRowHtml(m) +
      canDo(m) +
      '<p class="section-title" style="margin-top:18px">Recent activity</p>' + recent +
      '<p class="section-title" style="margin-top:18px">Tools it can reach</p>' +
      '<div class="tags">' +
        (toolsOf(m).length
          ? toolsOf(m).map(function (t) { return '<span class="tag">' + esc(t) + '</span>'; }).join("")
          : '<span class="empty">Everything this account can reach.</span>') +
      '</div>' +
      // Aimed at this agent, not the room: naming it is what the routing
      // ladder matches on, and a named agent answers and may not pass.
      '<a class="btn chat-with" target="_top" data-id="' + esc(m.id) +
        '" href="/tasks/agents?ask=' +
        encodeURIComponent((m.name || "") + ", ") + '">Chat with ' +
        esc(m.name || "this agent") + '</a>' +
      '<a class="btn ghost edit-agent" target="_top" data-id="' + esc(m.id) + '" href="/tasks/agents">Edit agent</a>' +
      '<p class="note">Which tool a run actually used is not recorded, so this ' +
        'is what it may reach, not what it is using. Only the most recent run ' +
        'is kept per agent.</p>';
  }

  function recentRows() {
    return S.AGENTS.map(function (m) {
      var a = S.ACTIVITY[m.id];
      return a ? { name: m.name || m.id, id: m.id, a: a } : null;
    }).filter(Boolean).sort(function (x, y) {
      return new Date(y.a.last_run_at || 0) - new Date(x.a.last_run_at || 0);
    });
  }

  //: --- the activity log ----------------------------------------------------
  //: The live activity card used to be the most recent run of EACH AGENT,
  //: redrawn from the poll: a job vanished from it the moment the next one
  //: started, a tool call never appeared at all, and nothing in it said
  //: what happened in what order. It is a log now ("add logs activity",
  //: 2026-10-12): seeded once from what the server knows, then every event
  //: the stream delivers is written to it as it arrives, newest first, so
  //: what the card says and what the floor is doing are the same events at
  //: the same moment. Each line is still a recorded row and nothing else.
  var LOG = [], LOG_MAX = 40;

  function logLine(id, key, text, at) {
    LOG.unshift({ id: id, name: nameOf(id) || id, key: key, text: text,
                  at: at ? Date.parse(at) || Date.now() : Date.now() });
    if (LOG.length > LOG_MAX) LOG.length = LOG_MAX;
  }

  //: Is this already in the log? The same agent, the same state, at or
  //: after the same moment. The stream and the poll describe the same run
  //: twice (an event lands, then the re-read finds the row it wrote), and
  //: the log must say it once.
  function logged(id, key, at) {
    for (var i = 0; i < LOG.length; i++) {
      var l = LOG[i];
      if (l.id === id && l.key === key && l.at >= at - 2000) return true;
    }
    return false;
  }

  //: What the server's own rows say, each agent's latest run: the whole
  //: log at load, and the fallback's only source when there is no stream
  //: (no EventSource, a 401, a gap the heartbeat missed). A row whose state
  //: the log has not seen yet becomes a line; one it has is left alone.
  //: Each handoff is said once from the asker's side.
  function logFromEvents() {
    var added = false;
    (S.EVENTS || []).forEach(function (e) {
      if (!e || !e.agent_id || !nameOf(e.agent_id)) return;
      var at = Date.parse(e.at || "") || 0;
      if (!at || logged(e.agent_id, e.key, at)) return;
      var text = e.text;
      if (e.target_agent_id) text += " " + (nameOf(e.target_agent_id) || "a colleague");
      logLine(e.agent_id, e.key, text, e.at);
      added = true;
    });
    return added;
  }

  function logFromActivity() {
    var added = logFromEvents();
    recentRows().forEach(function (r) {
      var key = stateOf(r.id).key;
      var at = Date.parse(r.a.last_run_at || "") || 0;
      if (!at || logged(r.id, key, at)) return;
      logLine(r.id, key,
        (r.a.state === "working" ? "is working" : (r.a.last_status || "finished")) +
        (r.a.source ? " from " + r.a.source : ""), r.a.last_run_at);
      added = true;
    });
    // Newest first. The sort is stable, so a finish found by the same read
    // as its start, at the same recorded moment, stays above it.
    if (added) LOG.sort(function (x, y) { return y.at - x.at; });
  }

  //: One stream event, in the log's words. A tool that finished cleanly is
  //: left out: "is using X" already said it, and a card of "finished X"
  //: lines would bury the runs between them.
  function logEvent(e) {
    if (!e || !e.agent_id || !nameOf(e.agent_id)) return;
    var id = e.agent_id;
    if (e.event === "run_started") logLine(id, "working", "started working", e.at);
    else if (e.event === "tool_started") logLine(id, "working", "is using " + (e.tool || "a tool"), e.at);
    else if (e.event === "tool_finished") {
      if (e.status && e.status !== "ok") logLine(id, "failed", (e.tool || "a tool") + " failed", e.at);
    } else if (e.event === "handoff") {
      var to = nameOf(e.target_agent_id) || "a colleague";
      var refused = e.status === "refused" || e.status === "failed";
      logLine(id, refused ? "failed" : "working",
              refused ? "could not reach " + to : "asked " + to, e.at);
    } else if (e.event === "run_finished") {
      logLine(id, e.status === "failed" ? "failed" : e.status === "waiting" ? "waiting" : "ready",
              e.status === "failed" ? "failed" : e.status === "waiting" ? "is waiting on you" : "finished",
              e.at);
    }
  }

  function drawLive() {
    logFromActivity();
    var live = document.getElementById("live");
    // Marked so the overlay on the whole page can take itself away entirely
    // when there is nothing to report, rather than sit over a room header
    // saying so. The bar along the bottom of the floor already says nothing
    // has run.
    var strip = document.getElementById("strip");
    if (strip) strip.setAttribute("data-empty", LOG.length ? "0" : "1");
    if (!LOG.length) {
      live.innerHTML = '<li><span class="empty">Nothing has run yet.</span></li>';
      return;
    }
    live.innerHTML = LOG.map(function (l) {
      return '<li><i class="dot ' + l.key + '"></i><span><b>' + esc(l.name) + '</b> ' +
        esc(l.text) + '</span>' +
        '<span class="when">' + esc(ago(new Date(l.at).toISOString())) + '</span></li>';
    }).join("");
  }

  //: A week of runs, read when the tab is first opened and on every draw
  //: of it after that. Empty (no route, no rows, an error) falls back to
  //: the one-line-per-agent view the tab always had.
  var HIST = { runs: [], spend: [] }, HIST_LOADED = false;
  async function loadHistory() {
    try {
      var got = await getJson("/api/tasks/agents/history");
      HIST = { runs: Array.isArray(got.runs) ? got.runs : [],
               spend: Array.isArray(got.spend) ? got.spend : [] };
    } catch (e) { console.warn("[office] history unavailable", e); }
    HIST_LOADED = true;
  }

  function histFilter() {
    var f = {};
    ["agent", "status", "source"].forEach(function (k) {
      var sel = document.getElementById("hist-" + k);
      f[k] = sel ? sel.value : "";
    });
    return f;
  }

  //: The selects offer what the week actually holds, and keep what was
  //: picked across redraws.
  function fillHistFilters(runs) {
    var agentSel = document.getElementById("hist-agent");
    var sourceSel = document.getElementById("hist-source");
    if (!agentSel || !sourceSel) return;
    var keepA = agentSel.value, keepS = sourceSel.value;
    var ids = {}, sources = {};
    runs.forEach(function (r) { ids[r.agent_id] = 1; if (r.source) sources[r.source] = 1; });
    agentSel.innerHTML = '<option value="">Every agent</option>' +
      Object.keys(ids).filter(function (id) { return nameOf(id); })
        .sort(function (a, b) { return nameOf(a).localeCompare(nameOf(b)); })
        .map(function (id) { return '<option value="' + esc(id) + '">' + esc(nameOf(id)) + '</option>'; }).join("");
    sourceSel.innerHTML = '<option value="">Started anywhere</option>' +
      Object.keys(sources).sort().map(function (s) {
        return '<option value="' + esc(s) + '">' + esc("From " + s) + '</option>'; }).join("");
    agentSel.value = keepA; sourceSel.value = keepS;
  }

  function drawSpend(spend, runs) {
    var el = document.getElementById("spend");
    if (!el) return;
    var total = 0;
    runs.forEach(function (r) { total += r.cost_usd || 0; });
    var most = spend.reduce(function (a, d) { return Math.max(a, d.cost_usd || 0); }, 0);
    el.hidden = false;
    el.innerHTML = '<span>This week <b>$' + total.toFixed(2) + '</b> over ' +
        runs.length + (runs.length === 1 ? ' run' : ' runs') + '</span>' +
      '<span class="spend-days">' + spend.map(function (d) {
        var h = most ? Math.max(2, Math.round(22 * (d.cost_usd || 0) / most)) : 2;
        return '<span class="spend-day" title="' + esc(d.day) + ': $' + (d.cost_usd || 0).toFixed(2) + '">' +
          '<i style="height:' + h + 'px"></i>' + esc(d.day.slice(5)) + '</span>';
      }).join("") + '</span>';
  }

  function drawActivity() {
    var feed = document.getElementById("activity-feed");
    var title = document.getElementById("hist-title");
    var filters = document.getElementById("hist-filters");
    if (HIST.runs.length) {
      if (title) title.textContent = "Every run in the last week";
      if (filters) filters.hidden = false;
      fillHistFilters(HIST.runs);
      drawSpend(HIST.spend, HIST.runs);
      var f = histFilter();
      var shown = HIST.runs.filter(function (r) {
        return nameOf(r.agent_id) &&
          (!f.agent || r.agent_id === f.agent) &&
          (!f.status || r.status === f.status) &&
          (!f.source || r.source === f.source);
      });
      feed.innerHTML = shown.length ? shown.map(function (r) {
        var key = r.status === "waiting" ? "waiting" : r.status === "failed" ? "failed"
                : r.status === "running" ? "working" : "ready";
        return '<li><i class="dot ' + key + '"></i><span>' + esc(nameOf(r.agent_id)) +
          ' &middot; ' + esc(r.status === "waiting" ? "waiting on you" : r.status) +
          (r.source ? ' <span class="hist-meta">from ' + esc(r.source) + '</span>' : "") +
          (r.seconds != null ? ' <span class="hist-meta">' + r.seconds + 's</span>' : "") +
          '</span>' +
          (r.cost_usd != null ? '<span class="hist-cost">$' + r.cost_usd.toFixed(3) + '</span>' : "") +
          '<span class="when">' + esc(ago(r.started_at)) + '</span></li>';
      }).join("") : '<li><span class="empty">No runs match.</span></li>';
      return;
    }
    if (title) title.textContent = "Most recent run of each agent";
    if (filters) filters.hidden = true;
    var spend = document.getElementById("spend");
    if (spend) spend.hidden = true;
    var rows = recentRows();
    if (!rows.length) {
      feed.innerHTML = '<li><span class="empty">Nothing has run yet.</span></li>';
      return;
    }
    feed.innerHTML = rows.map(function (r) {
      var st = stateOf(r.id);
      return '<li><i class="dot ' + st.key + '"></i><span>' + esc(r.name) + ' &middot; ' +
        esc(r.a.state === "working" ? "working now" : (r.a.last_status || "finished")) +
        (r.a.source ? " from " + esc(r.a.source) : "") + '</span>' +
        '<span class="when">' + esc(ago(r.a.last_run_at)) + '</span></li>';
    }).join("");
  }

  //: Re-read the floor now rather than at the next poll. The live feed
  //: (connectLive) normally drives the floor, with a 30 second poll as the
  //: fallback; the hook exists so a test can prove what the floor does with
  //: a given set of rows instead of waiting.
  window.aiuiRefreshOffice = async function () {
    // Everything the floor shows that can change, not just the activity.
    // The to-do was left out at first and simply never refreshed: it is a
    // list of work in flight, so a stale one is worse than none.
    await Promise.all([loadActivity(), loadTodo()]);
    draw();
  };

  function draw() {
    // The floor is always drawn: the log is a drawer over it, not a page
    // instead of it, so what happens while you read still happens here.
    document.getElementById("panel-activity").hidden = TAB !== "activity";
    drawRooms(); drawLive();
    if (TAB === "activity") drawActivity();
    drawDock();
    drawSide();
    drawNeeds();
    drawTodo();
    // The side panel opening or closing changes how wide the floor's column
    // is, and a hidden tab measures as zero, so the fit is recomputed after
    // every draw rather than only on resize.
    if (typeof drawZoom === "function") drawZoom();
  }

  async function loadAgents() {
    // /list pages at 30, one-indexed. Page 1 alone silently hides every agent
    // past the thirtieth, which the cron page learned the hard way.
    var items = [], total = 0, page = 1, guard = 0;
    while (guard++ < 25) {
      var body = await getJson("/api/v1/models/list?page=" + page);
      var batch = Array.isArray(body.items) ? body.items : [];
      total = typeof body.total === "number" ? body.total : batch.length;
      items = items.concat(batch);
      if (!batch.length || items.length >= total) break;
      page++;
    }
    S.AGENTS = items.filter(function (m) { return String(m.id || "").indexOf("agent-") === 0; });
  }
  async function loadActivity() {
    try {
      var got = await getJson("/api/tasks/agents/activity");
      S.ACTIVITY = got.activity || {};
      S.HANDOFFS = got.handoffs || [];
      // The last day of recorded runs and handoffs, as log lines, so the
      // live card does not start empty on every reload.
      S.EVENTS = got.events || [];
      var now = Date.now();
      Object.keys(S.ACTIVITY).forEach(function (id) {
        var a = S.ACTIVITY[id];
        if (a && a.state === "working") a._since = now - (a.running_for_seconds || 0) * 1000;
      });
    } catch (e) { console.warn("[office] activity unavailable", e); }
  }

  //: One event from /agents/stream, applied to what the floor holds. Each is
  //: a row the server just wrote (tool_started: a call it just began), so
  //: this is the poll's truth, sooner. Safe to apply twice: resync re-applies
  //: events that arrived while it was reading.
  function applyEvent(e) {
    if (!e || !e.agent_id) return;
    logEvent(e);
    var a = S.ACTIVITY[e.agent_id] || {};
    if (e.event === "run_started") {
      var since = a.state === "working" && a._since != null ? a._since : Date.now();
      // The run's own source when the event carries it. Keeping the one
      // the last poll saw drew a private chat as "3 agents in a meeting".
      S.ACTIVITY[e.agent_id] = Object.assign({}, a, { state: "working",
        running_for_seconds: 0, _since: since, last_run_at: e.at },
        e.source ? { source: e.source } : {});
      // A meeting run with no open meeting on this page: its meeting_started
      // was missed (the page connected mid-round, or the stream dropped
      // between the two). Open one from the runs themselves, speaker by
      // speaker, and let a meeting_started that does arrive replace it.
      if (e.source === "meeting") {
        if (!S.MEETING || meetingOver(S.MEETING)) {
          S.MEETING = meetingFromRuns(e.agent_id);
        } else if (!S.MEETING.ended && !S.MEETING.heard &&
                   S.MEETING.ids.indexOf(e.agent_id) === -1) {
          S.MEETING.ids.push(e.agent_id);
        }
      }
    } else if (e.event === "tool_started") {
      S.TOOL_NOW[e.agent_id] = e.tool;
    } else if (e.event === "tool_finished") {
      if (S.TOOL_NOW[e.agent_id] === e.tool) delete S.TOOL_NOW[e.agent_id];
    } else if (e.event === "handoff") {
      if (e.target_agent_id && e.target_agent_id !== e.agent_id) {
        S.HANDOFFS = S.HANDOFFS.filter(function (h) {
          return !(h && h.from === e.agent_id && h.to === e.target_agent_id);
        }).concat([{ from: e.agent_id, to: e.target_agent_id,
                     status: e.status, at: e.at }]);
      }
    } else if (e.event === "run_finished") {
      delete S.TOOL_NOW[e.agent_id];
      // Whoever this run asked, it has stopped asking: the walk home, the
      // line's fade and the bubble's going all start from here.
      S.HANDOFFS = S.HANDOFFS.filter(function (h) { return !(h && h.from === e.agent_id); });
      var next = Object.assign({}, a, { last_status: e.status, _finished: Date.now(),
        state: e.status === "waiting" ? "waiting"
             : e.status === "failed" ? "failed" : "ready" });
      delete next.running_for_seconds;
      delete next._since;
      S.ACTIVITY[e.agent_id] = next;
    } else if (e.event === "speaking_started") {
      // Only a length (`chars`), never the words. The clock starts in
      // startSpeaking, once the robot is standing still.
      S.SPEAKING[e.agent_id] = { ms: speakFor(e.chars), heard: Date.now(), until: 0 };
      // And read aloud, if the speaker is on and the answer is in a window.
      voiceSaid(e.agent_id);
    } else if (e.event === "meeting_started") {
      S.MEETING = { ids: (e.participants || []).slice(), ended: null,
                    heard: true };
    } else if (e.event === "meeting_ended") {
      // A page that opened mid-round never heard who was in it: whoever the
      // source rule has in the room is, and they leave together too.
      if (!S.MEETING) {
        S.MEETING = { ids: S.AGENTS.map(function (m) { return m.id; })
          .filter(inMeeting), ended: null, heard: false, after: 0 };
      }
      // Events carry no meeting id. The round names its first speaker on
      // meeting_started and its last on meeting_ended, so an end whose
      // speaker is not this meeting's last is another round's (two rounds
      // at once: the office chat and the agents page) and must not close
      // the one still answering (review, 2026-10-14).
      var last = S.MEETING.ids[S.MEETING.ids.length - 1];
      if (S.MEETING.heard && last && e.agent_id !== last) return;
      if (!S.MEETING.ended) {
        S.MEETING.ended = S.LAST_MEETING_END = Date.now();
        setTimeout(draw, MEETING_LINGER_MS + 30);
      }
    }
  }

  //: One full re-read, with events that arrive meanwhile held and applied
  //: after it rather than overwritten by it. The poll goes through here too.
  var SYNCING = null, PENDING = [];
  function resync() {
    if (SYNCING) return SYNCING;
    PENDING = [];
    SYNCING = loadActivity().then(function () {
      Object.keys(S.TOOL_NOW).forEach(function (id) {
        if (!S.ACTIVITY[id] || S.ACTIVITY[id].state !== "working") delete S.TOOL_NOW[id];
      });
      var held = PENDING;
      PENDING = [];
      SYNCING = null;
      held.forEach(applyEvent);
      draw();
    });
    return SYNCING;
  }

  //: "hello" opens every connection, each automatic reconnect included, and
  //: the floor re-reads on it: the stream is a fan-out, not a log, so what
  //: happened while disconnected is only in the database. EventSource sends
  //: the token cookie, which the gateway accepts; a 401 closes it for good
  //: and the poll carries on alone.
  var LIVE_EVENTS = ["run_started", "tool_started", "tool_finished",
                     "handoff", "run_finished", "speaking_started",
                     "meeting_started", "meeting_ended"];
  function connectLive() {
    if (typeof window.EventSource !== "function") return;
    var es;
    try {
      es = new EventSource("/api/tasks/agents/stream", { withCredentials: true });
    } catch (x) { console.warn("[office] live feed unavailable", x); return; }
    es.addEventListener("hello", function () {
      // A reconnect may have swallowed this meeting's meeting_ended: the
      // stream keeps no log, and a deploy restarts the round's process
      // before its finally runs. An open meeting is forgotten here and the
      // source rule, re-read by resync, decides again; left alone, everyone
      // stood in the room until a reload (review, 2026-10-14). A closed one
      // is kept: it still stops stale sources drawing a meeting.
      if (S.MEETING && !S.MEETING.ended) S.MEETING = null;
      resync();
    });
    LIVE_EVENTS.forEach(function (name) {
      es.addEventListener(name, function (ev) {
        var e;
        try { e = JSON.parse(ev.data); } catch (x) { return; }
        if (SYNCING) { PENDING.push(e); return; }
        applyEvent(e);
        draw();
      });
    });
  }
  //: On screen: the tab is showing and no frame between this floor and the
  //: top window is display:none. Inside the agents pane the floor is two
  //: frames down (shell, agents page, office), and the shell keeps a closed
  //: pane loaded with display:none, which document.hidden never sees. The
  //: agents page's own Hide button is caught the same way.
  function onScreen() {
    if (document.hidden) return false;
    try {
      for (var w = window; w !== w.top; w = w.parent) {
        var f = w.frameElement;
        // Framed by another origin: nothing more can be known, so poll.
        if (!f) return true;
        if (!f.getClientRects().length) return false;
      }
    } catch (e) { /* an ancestor we may not read: poll as before */ }
    return true;
  }

  //: The poll is the live feed's fallback, so it runs only while somebody can
  //: see the floor. A skipped tick is made up as soon as whoever framed this
  //: page (the shell, or the agents page) says it is back on screen.
  var RESYNC_MISSED = false;
  function pollWhenOnScreen() {
    // The list rides the same 30s tick as the activity re-read. It changes
    // when a job starts or finishes, which the stream already tells us
    // about, so it does not need a clock of its own.
    if (onScreen()) { RESYNC_MISSED = false; loadTodo(); resync(); }
    else RESYNC_MISSED = true;
  }
  function catchUp() {
    if (!RESYNC_MISSED || !onScreen()) return;
    RESYNC_MISSED = false;
    resync();
  }
  document.addEventListener("visibilitychange", catchUp);
  window.addEventListener("message", function (ev) {
    if (ev.origin !== window.location.origin) return;
    if (ev.source !== window.parent) return;
    if (ev.data && ev.data.aiuiFrameVisible === true) catchUp();
  });

  async function loadStats() {
    try { S.STATS = (await getJson("/api/tasks/agents/stats")).stats || {}; }
    catch (e) { console.warn("[office] stats unavailable", e); }
  }
  async function loadSkills() {
    try {
      var got = (await getJson("/api/tasks/agents/skills")).skills || [];
      got.forEach(function (s) { S.SKILLS[s.name] = s; });
    } catch (e) { console.warn("[office] skill catalogue unavailable", e); }
  }

  async function loadTodo() {
    try { S.TODO = await getJson("/api/tasks/agents/todo"); }
    catch (e) { console.warn("[office] the to-do list is unavailable", e); }
  }

  //: What the team still has to do. Every line is a tasks.items row: the
  //: office invents nothing here, the same rule the floor follows.
  //: What needs you: every agent whose last run stopped to wait on the
  //: person. The same recorded state that gives the robot its wide-eyed
  //: face, so the tray and the floor cannot disagree. Answering goes to
  //: that agent's own conversation, which is where the question is.
  //: The question an agent is waiting on, if the thread beside the floor
  //: holds it: the approval bubble the round drew (agent_chat_render
  //: approval_bubble), with the calls it wants to run and its Yes and No.
  //: The tray's buttons press THOSE buttons, so an answer from the desk
  //: is the same answer, through the same route, as one from the thread.
  function pendingBubbleFor(name) {
    var rows = document.querySelectorAll('.ap-thread .am.awaiting');
    for (var i = rows.length - 1; i >= 0; i--) {
      if (rows[i].getAttribute("data-agent") === name) return rows[i];
    }
    return null;
  }

  function drawNeeds() {
    var el = document.getElementById("needs");
    if (!el) return;
    var waiting = S.AGENTS.filter(function (m) { return stateOf(m.id).key === "waiting"; });
    el.hidden = !waiting.length;
    if (!waiting.length) { el.innerHTML = ""; return; }
    el.innerHTML =
      '<div class="needs-head">Needs you' +
        '<span class="todo-n">' + waiting.length + '</span></div>' +
      '<ul class="needs-list">' + waiting.map(function (m) {
        var name = m.name || m.id, bubble = pendingBubbleFor(name);
        var auto = (m.meta && m.meta.access) === "all";
        var calls = bubble ? Array.prototype.map.call(
          bubble.querySelectorAll(".acalls li code"), function (c) { return c.textContent; }) : [];
        return '<li class="needs-item" data-id="' + esc(m.id) + '"' +
          (bubble ? ' data-ask="' + esc(bubble.id) + '"' : "") + '>' +
          '<div class="needs-row"><i class="dot waiting"></i>' +
          '<span class="needs-what"><b>' + esc(name) + '</b> ' +
            (bubble ? 'wants to run ' + esc(calls.join(", ") || "a tool") : 'is waiting on you') +
          '</span></div>' +
          '<div class="needs-actions">' +
          (bubble
            ? '<button class="btn primary needs-yes" type="button" data-id="' + esc(m.id) + '">Yes</button>' +
              '<button class="btn ghost needs-no" type="button" data-id="' + esc(m.id) + '">No</button>'
            : '<a class="btn needs-answer" target="_top" data-id="' + esc(m.id) + '"' +
              ' href="/tasks/agents?ask=' + encodeURIComponent(name + ", ") + '">Answer</a>') +
          // Auto: this agent never has to ask again. It is the agent's own
          // access level (meta.access, agent_access.LEVEL_ALL), written to
          // its model row exactly as the agents page writes it. The question
          // already standing is answered Yes as part of the same press.
          '<label class="needs-auto" title="Let ' + esc(name) + ' run its tools without asking">' +
            '<input type="checkbox" class="needs-auto-box" data-id="' + esc(m.id) + '"' +
            (auto ? " checked" : "") + '> Auto</label>' +
          '</div></li>';
      }).join("") + '</ul>';
  }

  //: Press the thread's own button for this agent's standing question.
  function answerPending(id, yes) {
    var m = S.AGENTS.filter(function (a) { return a.id === id; })[0];
    var bubble = m && pendingBubbleFor(m.name || m.id);
    if (!bubble) return false;
    var btn = bubble.querySelector("button[hx-vals*='\"approved\": \"" + (yes ? "yes" : "no") + "\"']");
    if (!btn) return false;
    btn.click();
    return true;
  }

  //: Give an agent all access, or take it back to asking. Reads the whole
  //: model row and writes it back with only meta.access changed: a partial
  //: body to this endpoint drops tools and instructions, which is why the
  //: office never wrote one before.
  var MODELS_API = "/api/v1/models";
  async function setAuto(id, on) {
    var r = await fetch(MODELS_API + "/model?id=" + encodeURIComponent(id),
                        { headers: authHeaders(), credentials: "include" });
    if (!r.ok) throw new Error("model " + r.status);
    var row = await r.json();
    row.meta = Object.assign({}, row.meta || {}, { access: on ? "all" : "ask" });
    var w = await fetch(MODELS_API + "/model/update?id=" + encodeURIComponent(id),
                        { method: "POST", headers: authHeaders(), credentials: "include",
                          body: JSON.stringify(row) });
    if (!w.ok) throw new Error("update " + w.status);
    var m = S.AGENTS.filter(function (a) { return a.id === id; })[0];
    if (m) m.meta = Object.assign({}, m.meta || {}, { access: on ? "all" : "ask" });
  }

  document.getElementById("needs").addEventListener("click", function (ev) {
    var yes = ev.target.closest(".needs-yes"), no = ev.target.closest(".needs-no");
    if (yes || no) { answerPending((yes || no).getAttribute("data-id"), !!yes); return; }
  });
  document.getElementById("needs").addEventListener("change", function (ev) {
    var box = ev.target.closest(".needs-auto-box");
    if (!box) return;
    var id = box.getAttribute("data-id"), on = box.checked;
    box.disabled = true;
    setAuto(id, on).then(function () {
      // The question already standing is answered as part of the same
      // press: Auto means "and go ahead".
      if (on) answerPending(id, true);
    }).catch(function (e) {
      console.warn("[office] could not change access", e);
      box.checked = !on;
    }).then(function () { box.disabled = false; drawNeeds(); });
  });

  function drawTodo() {
    var el = document.getElementById("todo");
    if (!el) return;
    var open = (S.TODO && S.TODO.open) || [];
    var done = (S.TODO && S.TODO.done) || [];
    if (!open.length && !done.length) {
      // Said plainly rather than hidden. An empty panel reads as broken;
      // "nothing outstanding" is a fact worth knowing.
      el.innerHTML = '<div class="todo-head"><h2>To do</h2></div>' +
        '<p class="todo-none">Nothing outstanding.</p>';
      return;
    }
    function line(t, isDone) {
      var who = t.who ? '<span class="todo-who">' + esc(t.who) + '</span>' : "";
      var when = isDone && t.at ? '<span class="todo-when">' + esc(ago(t.at)) + '</span>' : "";
      return '<li class="todo-item' + (isDone ? " done" : "") +
        '" data-status="' + esc(t.status) + '" data-pri="' + esc(t.priority) + '">' +
        '<i class="todo-dot" aria-hidden="true"></i>' +
        '<span class="todo-what" title="' + esc(t.what) + '">' + esc(t.what) + '</span>' +
        '<span class="todo-meta">' + who +
          (isDone ? when : '<span class="todo-state">' + esc(t.status.replace(/_/g, " ")) + '</span>') +
        '</span></li>';
    }
    el.innerHTML =
      '<div class="todo-head"><h2>To do</h2>' +
        (open.length ? '<span class="todo-n">' + open.length + ' open</span>' : "") +
      '</div>' +
      (open.length ? '<ul class="todo-list">' + open.map(function (t) { return line(t, false); }).join("") + '</ul>'
                   : '<p class="todo-none">Nothing outstanding.</p>') +
      // Finished work behind a disclosure rather than struck through under
      // the open work: a column that opened on four crossed-out lines read
      // as clutter ("revise the ui", 2026-10-16). The count says it is there.
      (done.length ? '<details class="todo-done"><summary>Recently done' +
         '<span class="todo-n">' + done.length + '</span></summary>' +
         '<ul class="todo-list todo-recent">' +
         done.map(function (t) { return line(t, true); }).join("") + '</ul></details>' : "");
  }

  //: Who is looking: the signed-in person's first name, for the robots to
  //: say hello to. Read once, and the office works without it ("Hi!").
  var MY_NAME = "";
  getJson("/api/v1/auths/").then(function (me) {
    var name = me && typeof me.name === "string" ? me.name.trim() : "";
    MY_NAME = name.split(/\s+/)[0] || "";
  }).catch(function () { /* nobody to greet by name */ });

  //: A robot clicked says hello: a wave of the arm and a word over its
  //: head (2026-10-17, "if i click the agent in the office it should hi
  //: to me like waving the hands"). The bubble is its own element, not
  //: the handoff's .say, which syncSays owns and would take away on the
  //: redraw the click causes.
  var WAVE_MS = 1800;
  function wave(id) {
    var el = slotEl(document.getElementById("agents-layer"), id);
    if (!el) return;
    clearTimeout(el._wave);
    el.classList.remove("waving");
    void el.offsetWidth;                  // restart the animation on a second click
    el.classList.add("waving");
    // A sleeping robot wakes to say hello, and dozes off again after.
    var who = el.querySelector(".who"), f = who && who.querySelector(".bot-face");
    var dozing = who && who.getAttribute("data-state") === "asleep";
    if (dozing) {
      el.classList.add("woken");
      if (f) f.innerHTML = face(id, "ready");
    }
    var old = el.querySelector(".hello");
    if (old) old.remove();
    var hi = document.createElement("div");
    hi.className = "say hello";
    hi.textContent = "Hi" + (MY_NAME ? ", " + MY_NAME : "") + "! \uD83D\uDC4B";
    el.appendChild(hi);
    offerDance(el, id);
    el._wave = setTimeout(function () {
      el.classList.remove("waving");
      hi.classList.add("going");
      setTimeout(function () { hi.remove(); }, 650);
      if (dozing) {
        el.classList.remove("woken");
        // Still asleep, as far as the floor knows: back to it, unless it
        // has been asked to dance meanwhile (the dance keeps it awake).
        if (f && who.getAttribute("data-state") === "asleep" && !el.classList.contains("dancing")) {
          f.innerHTML = face(id, "asleep");
        }
      }
    }, WAVE_MS);
  }

  //: Dancing (2026-10-22, "pop up the small icon dance ... so user can
  //: select an agent to dance"). With the hello comes a small Dance button;
  //: it opens the five moves (animations/dance.css), and the one picked
  //: runs on this robot for DANCE_MS. A dance is for you and is never a
  //: state: not offered to a robot that is working, waiting on you or
  //: failed, ended at once by a run starting, and paused while it walks.
  var DANCES = [["bop", "Bop"], ["twist", "Twist"], ["robot", "The Robot"],
                ["hands", "Hands up"], ["spin", "Spin"]];
  var DANCE_MS = 8000, DANCE_OFFER_MS = 6000;
  function canDance(id) {
    var k = stateOf(id).key;
    return k === "ready" || k === "asleep" || k === "idle";
  }
  function offerDance(el, id) {
    var old = el.querySelector(".dance-btn");
    if (old) old.remove();
    var menu = el.querySelector(".dance-menu");
    if (menu) menu.remove();
    if (!canDance(id)) return;
    var b = document.createElement("button");
    b.type = "button";
    b.className = "dance-btn";
    b.setAttribute("data-id", id);
    b.textContent = el.classList.contains("dancing") ? "Stop" : "\u266A Dance";
    b.title = "Make " + (nameOf(id) || "this agent") + " dance";
    el.appendChild(b);
    clearTimeout(el._offer);
    el._offer = setTimeout(function () {
      // Gone again unless it is being used, or the robot is dancing (then
      // it is the Stop button).
      if (el.querySelector(".dance-menu") || el.classList.contains("dancing")) return;
      b.classList.add("going");
      setTimeout(function () { b.remove(); }, 300);
    }, DANCE_OFFER_MS);
  }
  function openDanceMenu(el, id) {
    var menu = el.querySelector(".dance-menu");
    if (menu) { menu.remove(); return; }
    menu = document.createElement("div");
    menu.className = "dance-menu";
    menu.setAttribute("role", "menu");
    menu.innerHTML = DANCES.map(function (d) {
      return '<button type="button" role="menuitem" data-dance="' + d[0] + '">' + esc(d[1]) + '</button>';
    }).join("");
    el.appendChild(menu);
  }
  function startDance(el, id, key) {
    var menu = el.querySelector(".dance-menu");
    if (menu) menu.remove();
    if (!canDance(id)) return;
    var who = el.querySelector(".who"), f = who && who.querySelector(".bot-face");
    el.setAttribute("data-dance", key);
    el.classList.add("dancing");
    // Awake for it, whatever the desk looked like.
    if (who && who.getAttribute("data-state") === "asleep" && f) f.innerHTML = face(id, "ready");
    var b = el.querySelector(".dance-btn");
    if (b) b.textContent = "Stop";
    clearTimeout(el._dance);
    el._dance = setTimeout(function () { stopDance(el, id); }, DANCE_MS);
  }
  function stopDance(el, id) {
    clearTimeout(el._dance);
    if (!el.classList.contains("dancing")) return;
    el.classList.remove("dancing");
    el.removeAttribute("data-dance");
    var who = el.querySelector(".who"), f = who && who.querySelector(".bot-face");
    if (who && who.getAttribute("data-state") === "asleep" && f && !el.classList.contains("woken")) {
      f.innerHTML = face(id, "asleep");
    }
    var b = el.querySelector(".dance-btn");
    if (b) { b.classList.add("going"); setTimeout(function () { b.remove(); }, 300); }
  }

  document.getElementById("rooms").addEventListener("click", function (ev) {
    var pick = ev.target.closest(".dance-menu button");
    if (pick) {
      var pslot = pick.closest(".who-slot");
      startDance(pslot, pslot.getAttribute("data-id"), pick.getAttribute("data-dance"));
      return;
    }
    var db = ev.target.closest(".dance-btn");
    if (db) {
      var dslot = db.closest(".who-slot"), did = dslot.getAttribute("data-id");
      if (dslot.classList.contains("dancing")) stopDance(dslot, did);
      else openDanceMenu(dslot, did);
      return;
    }
    var who = ev.target.closest(".who");
    if (!who) return;
    S.SELECTED = who.getAttribute("data-id");
    draw();
    wave(S.SELECTED);
  });
  // --- how big the floor is drawn -----------------------------------------
  //
  // The floor is one canvas, sized by layoutFloor to whatever its rooms need,
  // then scaled to the space it has. The canvas is not reflowed to the box:
  // a robot and its name are fixed pixels, so squeezing the canvas packs the
  // rooms into strips too small to hold one. layoutFloor instead picks a
  // canvas SHAPE that suits the box, and this scales it.
  //
  // Fit is the default and it means the WHOLE office is visible: the smaller
  // of the width and height ratios, so nothing is cut off on either axis.
  //: Set by layoutFloor on every draw. The starting values only have to be
  //: sane enough for a first fit before any agent has been placed.
  var CANVAS_W = 1240, CANVAS_H = 420;
  //: Versioned for the same reason the dock's height is: a zoom is a number
  //: about a canvas, and this canvas changed size on 2026-09-29. 95% of the
  //: old floor is not 95% of this one, and the owner's saved value read as a
  //: zoom he never chose for the floor he was looking at.
  var ZOOM_KEY = "aiuiOfficeZoom2";
  var ZOOM = null;                  // null = fit; a number = the person chose
  //: How far the floor has been dragged from its resting place. Zoom alone
  //: left the browser's scrollbars as the only way to reach the rest of a
  //: floor you had zoomed into, which is a poor way to move around a plan
  //: and does not work at all inside a card that scrolls itself.
  var PAN_X = 0, PAN_Y = 0;

  try {
    var kept = parseFloat(localStorage.getItem(ZOOM_KEY) || "");
    if (kept > 0) ZOOM = kept;
  } catch (e) { /* fit, then */ }

  //: How much room the floor actually has. Split out of fitScale because
  //: layoutFloor asks the same question BEFORE there is a canvas to scale:
  //: the shape the rooms should take depends on the shape of the box.
  //:
  //: `top` and `below` are also what tellHostOurHeight has to add back when
  //: it says how tall a card would need to be. The two used to walk the page
  //: separately and disagree: this subtracted what sits UNDER the floor and
  //: that did not add it back, so the office asked its host for a card
  //: exactly the live activity strip too short, and Fit came out at two
  //: thirds of the height it had sized itself for.
  //: The height a person can actually see of this document.
  //:
  //: Walks up through same-origin frames, intersecting each frame's box with
  //: its parent's viewport, so a pane taller than the window reports the
  //: window. Falls back to this document's own height the moment anything is
  //: unreadable, which is every case this did not use to handle.
  function visibleHeight() {
    var h = window.innerHeight || CANVAS_H;
    try {
      var w = window, top = 0, bottom = h;
      while (w !== w.top) {
        var f = w.frameElement;
        if (!f) break;                       // framed by another origin
        var r = f.getBoundingClientRect();
        var p = w.parent;
        var ph = p.innerHeight || r.height;
        // This frame's visible slice, in the parent's coordinates.
        var vTop = Math.max(r.top, 0), vBottom = Math.min(r.bottom, ph);
        var slice = vBottom - vTop;
        if (slice > 0 && slice < bottom - top) bottom = top + slice;
        w = p;
      }
      h = Math.min(h, bottom - top);
    } catch (e) { /* an ancestor we may not read: the frame's own height */ }
    return Math.max(160, h);
  }

  function fitBox() {
    var fit = document.getElementById("floor-fit");
    if (!fit) return null;
    var w = fit.clientWidth || CANVAS_W;
    // How far down the PAGE the floor starts, not where it currently appears
    // on screen. getBoundingClientRect().top moves when the page scrolls, and
    // this scale decides the wrapper's height, which decides whether the page
    // scrolls: the two chased each other and the floor never held still long
    // enough to be clicked.
    var top = 0, el = fit;
    while (el) { top += el.offsetTop; el = el.offsetParent; }
    // And what sits BELOW it. Reserving only the space above left the live
    // activity strip hanging past the bottom: measured at 860x470 with seven
    // agents the page came out 81px taller than the frame, so the card
    // scrolled and the bottom of the office was cut off.
    // Walked UP as well as along: the live activity strip is not a sibling
    // of the wrapper, it sits outside the panel the wrapper is in, so
    // looking only at the wrapper's own siblings found nothing and the fit
    // was still 81px too tall.
    //: Only what is actually UNDER the floor. A following sibling is not
    //: necessarily a lower one: on the whole page the right hand panel is a
    //: sibling of <main> and sits BESIDE the floor, and counting it reserved
    //: 827px of height against a column that costs the floor none. Available
    //: height collapsed to 160 and Fit fell to 0.57, so the floor drew 725px
    //: inside a 1295px box (measured 2026-10-07).
    //:
    //: Compared with offsetTop rather than a client rect, for the same
    //: reason the walk above uses offsetTop: a rect moves when the page
    //: scrolls, and this number decides a height that decides whether the
    //: page scrolls at all.
    var below = 0, node = fit;
    while (node && node !== document.body) {
      var bottom = node.offsetTop + node.offsetHeight;
      var sib = node.nextElementSibling;
      while (sib) {
        if (!sib.hidden && sib.offsetTop >= bottom) below += sib.offsetHeight || 0;
        sib = sib.nextElementSibling;
      }
      node = node.parentElement;
    }
    //: How tall the window is, or the visible part of it when this page is
    //: a frame inside another.
    //:
    //: In the shell the office is a pane: an iframe at height:100%, and
    //: window.innerHeight inside it is the IFRAME's height, not what anyone
    //: can see. When the shell's own page is taller than the browser window,
    //: the floor sized itself to a box whose bottom is below the fold and
    //: the bar along its bottom was sliced in half (owner's screenshot,
    //: 2026-10-08, at /ai-agents/office).
    //:
    //: Same origin, so the frames can be measured. Cross-origin throws and
    //: an ancestor that will not be read leaves the plain height, which is
    //: what this always did.
    var h = Math.max(160, visibleHeight() - top - below - 16);
    return { w: w, h: h, top: top, below: below };
  }

  function fitScale() {
    var box = fitBox();
    if (!box) return 1;
    return Math.min(box.w / CANVAS_W, box.h / CANVAS_H);
  }

  //: `instant` is a zoom, a drag or a window resize: the hand asked, so the
  //: floor answers at once. Without it the floor keeps whatever easing the
  //: last draw gave it (.reflow, room.css), which is how a plan that grew
  //: for a meeting reshapes on the same clock as the people walking in.
  function drawZoom(instant) {
    var fit = document.getElementById("floor-fit");
    var floor = document.getElementById("rooms");
    if (!fit || !floor) return;
    if (instant === true) floor.classList.remove("reflow");
    var k = ZOOM == null ? fitScale() : ZOOM;
    k = Math.min(Math.max(k, 0.25), 2);
    // Translate before scale, so a drag moves the floor by the number of
    // screen pixels the pointer moved rather than by that many scaled ones.
    if (!embedded()) { PAN_X = 0; PAN_Y = 0; }
    floor.style.transform =
      "translate(" + Math.round(PAN_X) + "px," + Math.round(PAN_Y) + "px) " +
      "scale(" + k + ")";
    // Centred when the height is what limits the fit, which it is in a short
    // dock: the floor would otherwise sit against the left edge with the
    // width it could not use left empty beside it.
    var spare = (fit.clientWidth || CANVAS_W) - CANVAS_W * k;
    floor.style.left = Math.round(Math.max(0, spare) / 2) + "px";
    // The wrapper owns the space the scaled floor actually occupies, but
    // never more than the frame can show. Zoomed in past Fit inside a short
    // dock, the full scaled height made the office's OWN page taller than
    // the card, so the whole thing scrolled and the floor went out of sight.
    // A floor bigger than its box is what panning is for, and the grab
    // cursor has promised that all along.
    var room = fitBox();
    fit.style.height = Math.round(
      room ? Math.min(CANVAS_H * k, room.h) : CANVAS_H * k) + "px";
    var label = document.getElementById("zoom-fit");
    if (label) label.textContent = ZOOM == null ? "Fit" : Math.round(k * 100) + "%";
    tellHostOurHeight(fit);
  }

  // How tall a card would have to be for the whole floor to show at this
  // width. Deliberately computed from the WIDTH alone: a suggestion that
  // depended on the height we currently have would change the height, which
  // would change the suggestion, and the two would chase each other.
  function tellHostOurHeight(fit) {
    if (window.parent === window) return;
    var box = fitBox();
    if (!box) return;
    // Everything above the floor AND everything below it. Leaving the strip
    // underneath out is what made the card too short for the floor it was
    // being asked to hold.
    var need = Math.round(
      box.top + box.below + CANVAS_H * (box.w / CANVAS_W) + 16);
    try {
      window.parent.postMessage({ type: "aiui-office-size", height: need },
                                window.location.origin);
    } catch (e) { /* the card keeps whatever height it had */ }
  }

  function setZoom(k) {
    // Back to the whole office means back to the middle of it. Leaving the
    // pan behind would make Fit show an empty corner at the right scale.
    if (k == null) { PAN_X = 0; PAN_Y = 0; }
    ZOOM = k;
    try {
      if (k == null) localStorage.removeItem(ZOOM_KEY);
      else localStorage.setItem(ZOOM_KEY, String(k));
    } catch (e) { /* it will fit again next time */ }
    drawZoom(true);
  }

  (function () {
    var out = document.getElementById("zoom-out");
    var into = document.getElementById("zoom-in");
    var fitBtn = document.getElementById("zoom-fit");
    function now() { return ZOOM == null ? fitScale() : ZOOM; }
    if (out) out.addEventListener("click", function () { setZoom(now() / 1.15); });
    if (into) into.addEventListener("click", function () { setZoom(now() * 1.15); });
    // Back to showing everything, which is the one thing a person wants often
    // enough to deserve its own button.
    if (fitBtn) fitBtn.addEventListener("click", function () { setZoom(null); });
    window.addEventListener("resize", function () { drawZoom(true); });

    // Dragging the floor. Pointer events rather than mouse, so a touch or a
    // pen moves it too, and the capture keeps the drag alive when the
    // pointer leaves the wrapper mid-move.
    var fit = document.getElementById("floor-fit");
    var from = null;
    if (fit) {
      fit.addEventListener("pointerdown", function (e) {
        // The robots are buttons and the room links are links. A drag that
        // started on one of those is that control's, not the floor's.
        if (e.target.closest("button, a, .strip")) return;
        from = { x: e.clientX, y: e.clientY, px: PAN_X, py: PAN_Y };
        fit.classList.add("panning");
        try { fit.setPointerCapture(e.pointerId); } catch (err) { /* older */ }
        e.preventDefault();
      });
      fit.addEventListener("pointermove", function (e) {
        if (!from) return;
        PAN_X = from.px + (e.clientX - from.x);
        PAN_Y = from.py + (e.clientY - from.y);
        drawZoom(true);
      });
      function released() { from = null; fit.classList.remove("panning"); }
      fit.addEventListener("pointerup", released);
      fit.addEventListener("pointercancel", released);
    }

    drawZoom(true);
  })();

  // Asking from inside the frame.
  //
  // Every link here carries target="_top" so it escapes the frame rather than
  // loading the agents page INSIDE the office, which is a bug this page has
  // already had. But the office is open the whole time now, so following one
  // would tear the floor down and rebuild it on every click.
  //
  // Being in a frame is NOT enough to swallow the click. This page is also a
  // pane in the shell, at /ai-agents/office, and there nobody is listening: a
  // preventDefault with no host would make Chat do nothing at all. So the
  // host has to say so first, and until it does the link behaves normally.
  var HOSTED = false;
  window.addEventListener("message", function (ev) {
    if (ev.origin !== window.location.origin) return;
    if (ev.source !== window.parent) return;
    if (ev.data && ev.data.type === "aiui-office-host") HOSTED = true;
  });
  // Said in both directions, because either side can be the late one: the
  // host posts when the frame fires load, and the frame announces itself in
  // case it finished first.
  if (window.parent !== window) {
    try {
      window.parent.postMessage({ type: "aiui-office-ready" },
                                window.location.origin);
    } catch (e) { /* a frame we cannot talk to is simply not a host */ }
  }

  //: Each page this office links to, by the shell's own nav path for it
  //: (task-panel.js NAV_ENTRIES urlPath). A link to anything else is left
  //: alone wherever the office is.
  var PANE_OF = { "/tasks/agents": "/ai-agents", "/tasks/graph": "/graph",
                  "/tasks/office": "/ai-agents/office" };

  //: The Open WebUI shell, not merely some page that frames this one.
  //: task-panel.js sets this flag on the top window before it does anything
  //: else. A page that frames the office without it has nobody to answer
  //: aiui:open-pane, so there a link has to be followed.
  function inShell() {
    if (window.top === window || window.parent !== window.top) return false;
    try { return window.top.__aiuiTaskPanelLoaded === true; }
    catch (e) { return false; }            // a top we cannot read is not ours
  }

  // Every link here used to load a bare page over the whole of Open WebUI,
  // except the Chat pills. Now:
  //   hosted by the agents page: a message to it, which acts in place;
  //   the Agent Office pane in the shell: aiui:open-pane to the shell, which
  //     opens that pane exactly as its sidebar entry would;
  //   anywhere else: the link is followed, target=_top as written.
  // Nothing is ever sent. An ask only fills the composer.
  //: The office has a chat of its own (the dock) everywhere but inside the
  //: agents page, which has the one conversation already.
  function hasDock() {
    return !document.documentElement.classList.contains("embed") &&
      !!document.getElementById("chatdock");
  }
  document.addEventListener("click", function (ev) {
    // A new tab or window was asked for: that is the link's job.
    if (ev.defaultPrevented || ev.button !== 0 ||
        ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    // The buttons beside The Brain: the team chat, or a meeting in it.
    var btn = ev.target.closest(".chat-open");
    if (btn) { openChat(TEAM, btn.getAttribute("data-ask") || ""); return; }
    var a = ev.target.closest("a[href]");
    if (!a) return;
    if ((a.getAttribute("href") || "").charAt(0) === "#") return;
    var path = PANE_OF[a.pathname];
    if (!path) return;
    var ask = "";
    var raw = a.href.split("ask=")[1];
    if (raw != null) {
      try { ask = decodeURIComponent(raw); }
      catch (e) { return; }                // malformed: let the link do its job
    }
    var id = a.getAttribute("data-id") || "";
    // A chat link, with the office's own dock to open it in: "Chat" on a
    // robot is a private window with them, the meeting button is the team
    // window with the meeting words filled in, and nothing leaves the
    // floor (2026-10-16, "instead of redirecting it to the ai agent tab").
    if (raw != null && hasDock()) {
      ev.preventDefault();
      openChat(id || TEAM, id ? "" : ask);
      return;
    }
    var shell = !HOSTED && inShell();
    if (!HOSTED && !shell) return;
    ev.preventDefault();
    // Same origin only, both ways. The office, the agents page and the shell
    // are served by the same host, and a wildcard would hand whatever is
    // typed to any page that framed this one.
    var origin = window.location.origin;
    // Who a Chat pill or a skill link is talking to, said the same way to
    // the agents page around us and, through the shell, to the AI Agents
    // pane: either one opens that agent's own conversation, so the same
    // click does the same thing wherever this floor is.
    var name = (ask.split(",")[0] || "").trim();
    if (shell) {
      var open = { type: "aiui:open-pane", path: path };
      if (ask) {
        open.ask = ask;
        if (id) { open.agent = id; open.name = name; }
      }
      window.top.postMessage(open, origin);
      return;
    }
    if (ask) {
      // The agent's id goes with it. The page around us opens that agent's
      // own conversation rather than putting the question to the room:
      // "Chat" on a robot means a private word with them. Without an id
      // (the meeting button) it is a question for the room.
      window.parent.postMessage({
        type: "aiui-office-ask", ask: ask, agent: id, name: name
      }, origin);
    } else if (id && a.classList.contains("edit-agent")) {
      window.parent.postMessage({ type: "aiui-office-edit", id: id }, origin);
    } else {
      window.parent.postMessage({ type: "aiui-office-open", path: path }, origin);
    }
  });

  document.getElementById("side").addEventListener("change", function (ev) {
    var pick = ev.target.closest(".voice-pick");
    if (!pick) return;
    setVoiceOf(pick.getAttribute("data-id"), pick.value);
    drawSide();
  });
  document.getElementById("side").addEventListener("click", function (ev) {
    if (ev.target.closest("#side-shut")) { S.SELECTED = null; draw(); return; }
    var hear = ev.target.closest(".voice-hear");
    if (hear) { hearSample(hear.getAttribute("data-id")); return; }
    if (ev.target.closest("#side-fold")) { setSideFolded(!sideFolded()); drawSide(); drawZoom(true); return; }
    var sw = ev.target.closest(".swatch");
    if (!sw || !S.SELECTED) return;
    // agent.js changes the colour; the page is what redraws. It used to
    // call draw() itself, which meant the module that knows about palettes
    // also had to know this page existed.
    pickColour(S.SELECTED, sw.getAttribute("data-hue"));
    draw();
  });
  document.getElementById("q").addEventListener("input", draw);
  function showTab(name) {
    TAB = name;
    document.getElementById("tab-office").setAttribute("aria-selected", String(name === "office"));
    document.getElementById("tab-activity").setAttribute("aria-selected", String(name === "activity"));
    draw();
    // The week of runs is read the first time the log opens, and the
    // drawer is drawn again when it lands.
    if (name === "activity" && !HIST_LOADED) loadHistory().then(draw);
  }
  ["office", "activity"].forEach(function (name) {
    document.getElementById("tab-" + name).addEventListener("click", function () { showTab(name); });
  });
  document.getElementById("logs-close").addEventListener("click", function () { showTab("office"); });
  // The Logs button beside The Brain, which is the only way in from the
  // shell, where the header and its Activity tab are hidden.
  document.addEventListener("click", function (ev) {
    if (ev.target.closest(".logs-open")) showTab(TAB === "activity" ? "office" : "activity");
  });
  ["agent", "status", "source"].forEach(function (k) {
    var sel = document.getElementById("hist-" + k);
    if (sel) sel.addEventListener("change", drawActivity);
  });

  // In the shell the header is hidden (embed.css html.shell), and the
  // search box in it would be hidden with it. It moves down beside The
  // Brain, where the zoom controls already are, so searching still works
  // on a floor that fills the pane.
  (function moveSearchIntoTheFloor() {
    if (!document.documentElement.classList.contains("shell")) return;
    var q = document.getElementById("q"), brain = document.querySelector(".brain");
    var zoom = brain && brain.querySelector(".zoom");
    if (q && brain) brain.insertBefore(q, zoom || null);
  })();

  initDock(S, { stateOf: function (key) {
    if (key === TEAM) {
      var n = S.AGENTS.filter(function (m) { return stateOf(m.id).key === "working"; }).length;
      return { key: n ? "working" : "ready", label: n ? n + " working" : S.AGENTS.length + " agents" };
    }
    return stateOf(key);
  } });
  // The mic and the voices in those windows; a change of who is talking
  // redraws the floor so the mouth follows the sound.
  initVoice({ onChange: draw });

  initNewAgent({
    agents: function () { return S.AGENTS; },
    onCreated: async function (id) {
      // The new agent is read back from the list, so what the floor draws
      // is what the server has, and it stands at its desk picked out.
      try { await loadAgents(); } catch (e) { console.warn("[office] could not reload agents", e); }
      S.SELECTED = id;
      draw();
    }
  });

  (async function init() {
    try {
      await loadAgents();
    } catch (e) {
      document.getElementById("sub").textContent =
        "Your agents could not be loaded. Reload the page to try again.";
      console.warn("[office] could not list agents", e);
      return;
    }
    await Promise.all([loadActivity(), loadStats(), loadSkills(), loadTodo()]);
    // A remembered window for an agent that is gone is dropped now the
    // roster is known.
    pruneDock();
    // Not in the card: a panel that opens by itself takes the width the
    // floor was moved inline to get. On its own page the column is always
    // there, so showing somebody in it beats showing an empty prompt.
    if (!S.SELECTED && S.AGENTS.length &&
        !document.documentElement.classList.contains("embed")) {
      S.SELECTED = S.AGENTS[0].id;
    }
    draw();
    // Only the live half repeats. The aggregate covers every run an agent has
    // ever had and does not move between two ticks of a clock. The live feed
    // drives the floor; the poll stays as the fallback (no EventSource, no
    // cookie, a gap the heartbeat missed), slowed from 5s to 30s.
    connectLive();
    setInterval(pollWhenOnScreen, 30000);
    // Desks go quiet without any event: once a minute, whoever has just
    // dozed off is drawn asleep.
    var SLEPT = sleepers();
    setInterval(function () {
      var now = sleepers();
      if (now !== SLEPT) { SLEPT = now; draw(); }
    }, 60000);
    // The working timer moves between events without redrawing the floor.
    setInterval(function () {
      document.querySelectorAll('.who[data-state="working"]').forEach(function (el) {
        var small = el.querySelector(".who-label small");
        if (small) small.textContent = stateOf(el.getAttribute("data-id")).label;
      });
    }, 1000);
  })();
})();
