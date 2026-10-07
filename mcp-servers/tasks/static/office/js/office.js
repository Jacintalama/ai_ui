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
import { getJson, esc, ago, saying } from "./util.js";
import { PALETTES, ownPalette, paletteOf, colourOf, pickColour, robot }
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
      return { key: "working", label: "Working" + (secs != null ? " " + secs + "s" : "") };
    }
    if (a.state === "waiting") return { key: "waiting", label: "Waiting on you" };
    if (a.state === "failed") return { key: "failed", label: "Last run failed" };
    return { key: "ready", label: "Ready" };
  }

  // Which part of the office an agent belongs to, decided by the tools it
  // actually holds, so this is a picture of how they were set up rather than
  // a seating plan somebody typed. First match wins, so an agent holding both
  // code and schedules sits in Development.
  // Six rooms on a plan, laid out as in the owner's mockup: three across the
  // top, three across the bottom, with the middle left open.
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
  var ROOM_MIN_W = 172;
  var ROOM_PAD = 14, ROOM_GAP = 18, BAND_PAD = 18;
  var FLOOR_BAR = 52;      // the strip along the bottom, which is not a room
  //: Clear canvas above the rooms for the live activity card, which on the
  //: whole page is laid over the floor in the top right corner. Reserved
  //: rather than left to overlap: a card sitting on a room hides the agent
  //: it is reporting on, which is the opposite of what it is for. Zero in
  //: the dock, where the card is under the floor and not over it.
  var TOP_RESERVE = 120;
  function topReserve() {
    try {
      return document.documentElement.classList.contains("embed") ? 0 : TOP_RESERVE;
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
  function bestLayout(rooms) {
    var box = fitBox(), best = null, bestK = -1;
    for (var i = 0; i < ROW_CAPS.length; i++) {
      var plan = layoutFloor(rooms, ROW_CAPS[i]);
      if (!box) return plan;
      var k = Math.min(box.w / plan.w, box.h / plan.h);
      if (k > bestK) { bestK = k; best = plan; }
    }
    return best;
  }

  //: One room, sized to the agents in it, and where each of them stands.
  function roomBox(n, rowCap) {
    var cols = Math.max(1, Math.ceil(n / Math.max(1, rowCap)));
    var rows = Math.max(1, Math.ceil(n / cols));
    return {
      cols: cols, rows: rows,
      w: Math.max(ROOM_MIN_W,
                  ROOM_PAD * 2 + cols * SLOT_W + (cols - 1) * SLOT_GAP_X),
      h: ROOM_HEAD + rows * SLOT_H + (rows - 1) * SLOT_GAP_Y + ROOM_PAD,
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
  function layoutFloor(rooms, rowCap) {
    var boxes = rooms.map(function (r) { return roomBox(r.of.length, rowCap); });
    var tallest = boxes.reduce(function (a, b) { return Math.max(a, b.h); }, 0);
    var need = BAND_PAD * 2 + ROOM_GAP * Math.max(0, boxes.length - 1) +
      boxes.reduce(function (a, b) { return a + b.w; }, 0);
    var width = Math.max(need, CANVAS_MIN_W);
    var reserve = topReserve();
    var height = BAND_PAD * 2 + reserve + tallest + FLOOR_BAR;

    // Centred when the strip below is what set the width, so a floor with
    // two rooms on it is not a pair of rooms in the corner of an empty hall.
    var x = BAND_PAD + Math.round((width - need) / 2);
    var out = rooms.map(function (r, i) {
      var b = boxes[i];
      // Every room is as tall as the tallest, rather than centred on the
      // band. Centring was right when the floor was a short wide strip and a
      // room holding one person would have been a tall empty column. Given
      // the height of the whole page it reads as five cards floating at
      // different offsets instead of rooms in a building, and it wastes the
      // space the fit just won back.
      var top = BAND_PAD + reserve;
      var left = x;
      x += b.w + ROOM_GAP;

      // Where each agent stands inside THIS room, in canvas pixels. The slot
      // is reserved by the same numbers that sized the room, so an agent can
      // no more overflow its room than a room can overflow the canvas.
      var need = b.cols * SLOT_W + (b.cols - 1) * SLOT_GAP_X;
      var inner = left + Math.round((b.w - need) / 2), innerTop = top + ROOM_HEAD;
      var slots = r.of.map(function (m, k) {
        var col = k % b.cols, row = Math.floor(k / b.cols);
        return {
          m: m,
          left: inner + col * (SLOT_W + SLOT_GAP_X),
          top: innerTop + row * (SLOT_H + SLOT_GAP_Y),
        };
      });
      return { z: r.z, of: r.of, left: left, top: top, w: b.w, h: tallest,
               slots: slots };
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


  //: One agent, in the slot the room reserved for it. Everything inside the
  //: slot is in normal flow: the robot, then the name, then the Chat pill.
  //: Nothing here is told where to put itself, which is why nothing here can
  //: land on top of anything else.
  function whoHtml(m, slot) {
    var st = stateOf(m.id), c = colourOf(m.id);
    return '<div class="who-slot" data-id="' + esc(m.id) + '"' +
      ' style="left:' + slot.left + 'px;top:' + slot.top + 'px;width:' + SLOT_W +
        'px;--bot-w:' + BOT_W + 'px;--bot-h:' + BOT_H + 'px">' +
      '<div class="desk"></div>' +
      '<button class="who" data-id="' + esc(m.id) + '" data-state="' + st.key + '"' +
      (S.SELECTED === m.id ? ' aria-current="true"' : "") +
      // No background: the robot IS the avatar now. The colour stays as the
      // element's own colour so the dot and the label pick it up.
      ' style="color:' + c + '"' +
      ' title="' + esc(st.label) + '">' +
      robot(m.id, st.key === "working") +
      '<i class="dot ' + st.key + '"></i>' +
      (st.key === "working" && S.TOOL_NOW[m.id]
        ? '<span class="tool-now">' + esc(S.TOOL_NOW[m.id]) + '</span>' : "") +
      // The role normally, but the STATE the moment there is one worth
      // reading. A dot alone says something is happening without saying
      // what, and "Working 12s" is the whole reason to look at this floor.
      '<span class="who-label"><span class="card-name">' + esc(m.name || m.id) +
        '</span><small>' + esc(st.key === "ready" || st.key === "idle"
          ? (roleOf(m) || "no role") : st.label) + '</small></span>' +
      '</button>' +
      // Every agent carries its own, because one button on whoever happens to
      // be selected means you must pick somebody before you can talk to them.
      // Naming the agent is what makes the turn private: agent_routing's name
      // rung hands it to that one agent and nobody else answers.
      '<a class="who-chat" data-id="' + esc(m.id) + '" target="_top"' +
        ' title="Ask ' + esc(m.name || m.id) + ' on their own"' +
        ' href="/tasks/agents?ask=' +
        encodeURIComponent((m.name || m.id) + ", ") + '">Chat</a>' +
      '</div>';
  }

  //: How long a handoff keeps two robots visibly together. The server only
  //: sends the last few minutes, and this is the slice of that which reads as
  //: "now" rather than "recently".
  var TALK_SECONDS = 90;

  function _fresh(h) {
    var at = Date.parse(h && h.at || "");
    if (!at) return false;
    return (Date.now() - at) / 1000 <= TALK_SECONDS;
  }


  //: How far along the line an asking robot walks. Not all the way: it has to
  //: stay in its own room to still read as who and where it is, and two
  //: robots standing on the same spot is a pile rather than a conversation.
  var WALK_FRACTION = 0.28;

  //: Move the asking robot toward the colleague it is actually waiting on.
  //: Applied after the rooms are drawn, so it rides the .who transition and
  //: reads as a walk rather than a jump. Cleared on every draw, so the moment
  //: a handoff falls out of the data the robot walks back: a robot left
  //: standing beside a colleague long after the fact is the staleness lie
  //: this floor is supposed to avoid.
  function walkThem() {
    S.HANDOFFS.forEach(function (h) {
      if (!h || !h.from || !h.to || h.from === h.to || !_fresh(h)) return;
      var a = S.AT[h.from], b = S.AT[h.to];
      if (!a || !b) return;
      var id = window.CSS && CSS.escape ? CSS.escape(h.from) : h.from;
      // The whole slot walks, so the robot keeps its own name and its own
      // Chat pill with it. Left behind, that pill would offer a conversation
      // with whoever is standing there now, which is nobody.
      var who = document.querySelector('.who-slot[data-id="' + id + '"]');
      if (!who) return;
      var dx = (b.x - a.x) * CANVAS_W / 100 * WALK_FRACTION;
      var dy = (b.y - a.y) * CANVAS_H / 100 * WALK_FRACTION;
      who.style.transform =
        "translate(" + Math.round(dx) + "px," + Math.round(dy) + "px)";
    });
  }

  //: The line between two robots, plus what the asking one is saying over its
  //: head. Drawn ONLY from HANDOFFS, which is ONLY tasks.agent_step rows.
  //: Nothing here may be invented: a line between the wrong pair states a
  //: collaboration that did not happen, which is worse than drawing none.
  function talkHtml() {
    var out = "", seen = {};
    S.HANDOFFS.forEach(function (h) {
      if (!h || !h.from || !h.to || h.from === h.to) return;
      if (!_fresh(h)) return;
      var a = S.AT[h.from], b = S.AT[h.to];
      // One of them is filtered out of the search, or in a room nobody is
      // drawing. A line to nowhere is worse than no line.
      if (!a || !b) return;
      var key = h.from + ">" + h.to;
      if (seen[key]) return;
      seen[key] = 1;

      var refused = h.status === "refused" || h.status === "failed";
      var cls = refused ? " refused" : "";
      // Percentages are of different axes, so the angle is computed in the
      // floor's own pixel space and the line is placed back in percentages.
      var dx = (b.x - a.x) * CANVAS_W / 100;
      var dy = (b.y - a.y) * CANVAS_H / 100;
      var len = Math.sqrt(dx * dx + dy * dy);
      var deg = Math.atan2(dy, dx) * 180 / Math.PI;
      out += '<div class="talk-line' + cls + '"' +
        ' data-from="' + esc(h.from) + '" data-to="' + esc(h.to) + '"' +
        ' style="left:' + a.x + '%;top:' + a.y + '%;width:' + Math.round(len) +
        'px;transform:rotate(' + deg.toFixed(2) + 'deg)"></div>';

      var to = nameOf(h.to) || "a colleague";
      // Placed where the robot WILL be, not where its desk is: walkThem
      // moves the robot the same fraction along this line, and a bubble left
      // behind at the desk reads as somebody else talking.
      var sayX = a.x + (b.x - a.x) * WALK_FRACTION;
      var sayY = a.y + (b.y - a.y) * WALK_FRACTION;
      out += '<div class="say' + cls + '" style="left:' + sayX + '%;top:' +
        sayY + '%;margin-top:-46px">' +
        esc(refused ? "Could not reach " + to : "Asking " + to + "…") +
        '</div>';
    });
    return out;
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

    // Only rooms somebody works in. An empty room is scenery, and six of them
    // is what made the earlier floor unreadable.
    var occupied = ZONES.concat([LOUNGE])
      .filter(function (z) { return byZone[z.key]; })
      .map(function (z) { return { z: z, of: byZone[z.key].of }; });

    // The canvas is whatever the rooms need, and the rooms are whatever the
    // agents need. Set before anything is positioned, because AT records
    // percentages of it.
    var plan = bestLayout(occupied);
    CANVAS_W = plan.w;
    CANVAS_H = plan.h;
    var floor = document.getElementById("rooms");
    if (floor) {
      floor.style.width = CANVAS_W + "px";
      floor.style.height = CANVAS_H + "px";
    }

    var html = plan.rooms.map(function (r) {
      var z = r.z, of = r.of;
      var runs = 0, done = 0, spent = 0, working = 0;
      of.forEach(function (m) {
        var st = S.STATS[m.id] || {};
        runs += st.runs || 0;
        // success_pct is a percentage of that agent's OWN runs, so it is
        // weighted back into runs before rooms can be compared. Averaging the
        // percentages would let an agent with three runs outvote one with
        // eight hundred.
        if (st.runs && st.success_pct != null) done += st.runs * st.success_pct / 100;
        spent += st.cost_usd || 0;
        if (stateOf(m.id).key === "working") working++;
      });
      var pct = runs ? Math.round(100 * done / runs) : null;
      return '<section class="zone" style="--glow:' + z.glow + ';left:' + r.left +
        'px;top:' + r.top + 'px;width:' + r.w + 'px;height:' + r.h + 'px">' +
        '<div class="zone-head"><span>' + esc(z.label) + '</span>' +
        '<span class="card-room"><span>RUNS <b>' + runs + '</b></span>' +
        (pct == null ? "" : '<span>CLEAN <b>' + pct + '%</b></span>') +
        (spent ? '<span>$<b>' + spent.toFixed(2) + '</b></span>' : "") +
        '</span></div></section>';
    }).join("");

    // Agents sit above the rooms, so a label is never clipped by a wall.
    html += plan.rooms.map(function (r) {
      return r.slots.map(function (slot) {
        markAt(slot);
        return whoHtml(slot.m, slot);
      }).join("");
    }).join("");

    var working = shown.filter(function (m) { return stateOf(m.id).key === "working"; }).length;
    var newest = recentRows()[0];

    // The bar the mockup puts along the bottom. "Call a meeting" is real: it
    // hands the chat the words the routing ladder matches as a meeting, so
    // every agent answers and none may pass. There is deliberately no
    // "simulate collaboration": agents cannot address each other, and a
    // button that pretends otherwise is the one thing this page must not do.
    html += '<div class="floor-bar">' +
      '<span class="now"><i class="dot ' + (working ? "working" : "ready") + '"></i> ' +
        (working ? '<b>' + working + '</b> working now'
                 : (newest ? '<b>' + esc(newest.name) + '</b> ' +
                    esc(newest.a.state === "working" ? "is working"
                        : (newest.a.last_status || "finished")) + ' ' +
                    esc(ago(newest.a.last_run_at))
                  : "nothing has run yet")) + '</span>' +
      '<span class="right">' +
        '<a class="btn" target="_top" href="/tasks/agents?ask=' +
          encodeURIComponent("everyone answer: ") + '">Call a team meeting</a>' +
        // Not in the card on the agents page: the chat it opens is the page
        // around this floor, so following it only reloaded that page.
        (document.documentElement.classList.contains("embed") ? "" :
          '<a class="btn ghost" target="_top" href="/tasks/agents">Open the chat</a>') +
      '</span></div>';

    document.getElementById("rooms").innerHTML = html + talkHtml();
    walkThem();
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

  function drawSide() {
    var side = document.getElementById("side");
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

    side.innerHTML =
      '<button class="side-shut" type="button" id="side-shut" ' +
        'aria-label="Close the details">&times;</button>' +
      '<div class="side-head">' +
        '<div class="side-bot">' + robot(m.id, st.key === "working", "p") + '</div>' +
        '<div><h2>' + esc(m.name || m.id) + '</h2>' +
        '<div class="st"><i class="dot ' + st.key + '"></i>' + esc(st.label) + '</div></div>' +
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

  function drawLive() {
    var rows = recentRows(), live = document.getElementById("live");
    // Marked so the overlay on the whole page can take itself away entirely
    // when there is nothing to report, rather than sit over a room header
    // saying so. The bar along the bottom of the floor already says nothing
    // has run.
    var strip = document.getElementById("strip");
    if (strip) strip.setAttribute("data-empty", rows.length ? "0" : "1");
    if (!rows.length) {
      live.innerHTML = '<li><span class="empty">Nothing has run yet.</span></li>';
      return;
    }
    live.innerHTML = rows.slice(0, 8).map(function (r) {
      var st = stateOf(r.id);
      return '<li><i class="dot ' + st.key + '"></i><span><b>' + esc(r.name) + '</b> ' +
        esc(r.a.state === "working" ? "is working" : (r.a.last_status || "finished")) +
        (r.a.source ? " from " + esc(r.a.source) : "") + '</span>' +
        '<span class="when">' + esc(ago(r.a.last_run_at)) + '</span></li>';
    }).join("");
  }

  function drawActivity() {
    var rows = recentRows(), feed = document.getElementById("activity-feed");
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
    await loadActivity();
    draw();
  };

  function draw() {
    document.getElementById("panel-office").hidden = TAB !== "office";
    document.getElementById("panel-activity").hidden = TAB !== "activity";
    document.getElementById("strip").hidden = TAB !== "office";
    if (TAB === "office") { drawRooms(); drawLive(); } else { drawActivity(); }
    drawSide();
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
    var a = S.ACTIVITY[e.agent_id] || {};
    if (e.event === "run_started") {
      var since = a.state === "working" && a._since != null ? a._since : Date.now();
      S.ACTIVITY[e.agent_id] = Object.assign({}, a, { state: "working",
        running_for_seconds: 0, _since: since, last_run_at: e.at });
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
      var next = Object.assign({}, a, { last_status: e.status,
        state: e.status === "waiting" ? "waiting"
             : e.status === "failed" ? "failed" : "ready" });
      delete next.running_for_seconds;
      delete next._since;
      S.ACTIVITY[e.agent_id] = next;
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
                     "handoff", "run_finished"];
  function connectLive() {
    if (typeof window.EventSource !== "function") return;
    var es;
    try {
      es = new EventSource("/api/tasks/agents/stream", { withCredentials: true });
    } catch (x) { console.warn("[office] live feed unavailable", x); return; }
    es.addEventListener("hello", function () { resync(); });
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
    if (onScreen()) { RESYNC_MISSED = false; resync(); }
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

  document.getElementById("rooms").addEventListener("click", function (ev) {
    var who = ev.target.closest(".who");
    if (!who) return;
    S.SELECTED = who.getAttribute("data-id");
    draw();
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

  function drawZoom() {
    var fit = document.getElementById("floor-fit");
    var floor = document.getElementById("rooms");
    if (!fit || !floor) return;
    var k = ZOOM == null ? fitScale() : ZOOM;
    k = Math.min(Math.max(k, 0.25), 2);
    // Translate before scale, so a drag moves the floor by the number of
    // screen pixels the pointer moved rather than by that many scaled ones.
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
    drawZoom();
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
    window.addEventListener("resize", drawZoom);

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
        drawZoom();
      });
      function released() { from = null; fit.classList.remove("panning"); }
      fit.addEventListener("pointerup", released);
      fit.addEventListener("pointercancel", released);
    }

    drawZoom();
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
  document.addEventListener("click", function (ev) {
    // A new tab or window was asked for: that is the link's job.
    if (ev.defaultPrevented || ev.button !== 0 ||
        ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    var a = ev.target.closest("a[href]");
    if (!a) return;
    if ((a.getAttribute("href") || "").charAt(0) === "#") return;
    var path = PANE_OF[a.pathname];
    if (!path) return;
    var shell = !HOSTED && inShell();
    if (!HOSTED && !shell) return;
    var ask = "";
    var raw = a.href.split("ask=")[1];
    if (raw != null) {
      try { ask = decodeURIComponent(raw); }
      catch (e) { return; }                // malformed: let the link do its job
    }
    var id = a.getAttribute("data-id") || "";
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

  document.getElementById("side").addEventListener("click", function (ev) {
    if (ev.target.closest("#side-shut")) { S.SELECTED = null; draw(); return; }
    var sw = ev.target.closest(".swatch");
    if (!sw || !S.SELECTED) return;
    // agent.js changes the colour; the page is what redraws. It used to
    // call draw() itself, which meant the module that knows about palettes
    // also had to know this page existed.
    pickColour(S.SELECTED, sw.getAttribute("data-hue"));
    draw();
  });
  document.getElementById("q").addEventListener("input", draw);
  ["office", "activity"].forEach(function (name) {
    document.getElementById("tab-" + name).addEventListener("click", function () {
      TAB = name;
      document.getElementById("tab-office").setAttribute("aria-selected", String(name === "office"));
      document.getElementById("tab-activity").setAttribute("aria-selected", String(name === "activity"));
      draw();
    });
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
    await Promise.all([loadActivity(), loadStats(), loadSkills()]);
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
    // The working timer moves between events without redrawing the floor.
    setInterval(function () {
      document.querySelectorAll('.who[data-state="working"]').forEach(function (el) {
        var small = el.querySelector(".who-label small");
        if (small) small.textContent = stateOf(el.getAttribute("data-id")).label;
      });
    }, 1000);
  })();
})();
