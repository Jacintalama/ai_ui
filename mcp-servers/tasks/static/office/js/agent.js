import { nameOf } from "./state.js";

// What an agent looks like: its colour, and the robot drawn in it.
//
// The figure is GENERATED, not a file per agent. Agents are created by the
// person using this, in any number and with a colour they pick, so six fixed
// SVGs would mean six fixed agents. paletteOf falls back to a hue derived
// from the name, so a new agent has a colour before anybody chooses one.

// The palettes from the owner's own reference, assets/AI Agent Robots.html:
// a body, a darker body2 for the gradient, and an accent for eyes, hands and
// antenna. Named so a person can pick one by sight rather than by hex.
export var PALETTES = [
  { hue: "violet", accent: "#8b6bff", body: "#6c53d8", body2: "#4a3699" },
  { hue: "green",  accent: "#3fd08f", body: "#1fa872", body2: "#127653" },
  { hue: "blue",   accent: "#4d9bee", body: "#2d76c9", body2: "#1c5296" },
  { hue: "pink",   accent: "#ef6fc9", body: "#c94ea3", body2: "#973b7c" },
  { hue: "orange", accent: "#f0a24d", body: "#cc7f2b", body2: "#96591b" },
  { hue: "cyan",   accent: "#3fc7d1", body: "#2597a1", body2: "#186e76" },
];

var COLOUR_KEY = "aiuiOfficeColours";

//: What the person picked, by agent id. Read once at load; a private
//: window throws on localStorage and the office still draws.
var CHOSEN = {};
try { CHOSEN = JSON.parse(localStorage.getItem(COLOUR_KEY) || "{}") || {}; }
catch (e) { CHOSEN = {}; }

//: The agent's own hue, from its NAME, by the hash its card uses
//: (agents.html avatarHue) and the chat thread uses
//: (agent_chat_render._hue). Keep the three identical: a robot picked by
//: a hash of the id made Ada green on her card and purple on this floor.
function nameHue(name) {
  var h = 0, str = String(name || "");
  for (var i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 360;
  return h;
}

//: A palette in that hue: the body is DESIGN.md's avatar colour,
//: hsl(hue 45% 32%), and the accent is light enough to read as eyes on
//: the dark face.
export function ownPalette(id) {
  var h = nameHue(nameOf(id));
  return { hue: "own", accent: "hsl(" + h + ", 70%, 66%)",
           body: "hsl(" + h + ", 45%, 32%)", body2: "hsl(" + h + ", 45%, 24%)" };
}

// The one this person picked, or the agent's own hue, so the same agent is
// the same colour here as on its card and in the chat without anybody
// choosing.
export function paletteOf(id) {
  var picked = CHOSEN[id];
  if (picked) {
    for (var i = 0; i < PALETTES.length; i++) {
      if (PALETTES[i].hue === picked) return PALETTES[i];
    }
  }
  return ownPalette(id);
}

export function colourOf(id) { return paletteOf(id).accent; }

export function pickColour(id, hue) {
  // "own" is the way back: no choice stored, the agent's own hue again.
  if (hue === "own") delete CHOSEN[id];
  else CHOSEN[id] = hue;
  // Per viewer, because it is how this person wants their own office to
  // look rather than a property of the agent. Making it the agent's would
  // mean writing the whole model row back through Open WebUI's update
  // endpoint, and a partial body there can drop tools or instructions.
  try { localStorage.setItem(COLOUR_KEY, JSON.stringify(CHOSEN)); }
  catch (e) { /* not worth losing the choice on screen over */ }
}

// The robot, from assets/AI Agent Robots.html. Trimmed to what survives at
// this size: head, face, body, arms and feet. The legs and the walking
// animation in the reference are for a 220px portrait and turn to mud on a
// floor tile.
//: The face, from the agent's REAL state and nothing else.
//:
//: There is no mood to set, by a button or otherwise. A robot looking
//: pleased when its last run failed would be the floor lying in the one
//: place a person reads fastest, and a face is read before any label.
//:
//:   working  eyes narrowed on the job, and the blink that already said
//:            "mid-run" carries on
//:   waiting  wide, looking straight at you, because it is waiting on YOU
//:   failed   flat and dimmed, with a down-turned mouth
//:   ready    the one that smiles
//:   idle     open and neutral: nothing has happened yet
function faceFor(state, a) {
  var w = '#fff';
  if (state === "working") {
    return '<ellipse class="bot-eye bot-think" cx="58" cy="70" rx="8" ry="9" fill="' + a.accent + '"/>' +
      '<rect class="bot-eye bot-think" x="74" y="68" width="16" height="4" rx="2" fill="' + a.accent + '"/>' +
      '<rect x="60" y="86" width="20" height="3" rx="1.5" fill="' + a.accent + '" opacity=".75"/>';
  }
  if (state === "waiting") {
    return '<ellipse class="bot-eye" cx="58" cy="70" rx="9.5" ry="10.5" fill="' + a.accent + '"/>' +
      '<ellipse class="bot-eye" cx="82" cy="70" rx="9.5" ry="10.5" fill="' + a.accent + '"/>' +
      '<circle cx="55" cy="66" r="2.8" fill="' + w + '"/><circle cx="79" cy="66" r="2.8" fill="' + w + '"/>' +
      '<ellipse cx="70" cy="87" rx="5" ry="4" fill="none" stroke="' + a.accent + '" stroke-width="2.4"/>';
  }
  if (state === "failed") {
    return '<rect class="bot-eye" x="50" y="68" width="16" height="3.4" rx="1.7" fill="#fb7185"/>' +
      '<rect class="bot-eye" x="74" y="68" width="16" height="3.4" rx="1.7" fill="#fb7185"/>' +
      '<path d="M60 90 Q70 83 80 90" stroke="#fb7185" stroke-width="2.6" fill="none" stroke-linecap="round"/>';
  }
  if (state === "ready") {
    return '<path class="bot-eye" d="M50 72 Q58 63 66 72" stroke="' + a.accent + '" stroke-width="3.2" fill="none" stroke-linecap="round"/>' +
      '<path class="bot-eye" d="M74 72 Q82 63 90 72" stroke="' + a.accent + '" stroke-width="3.2" fill="none" stroke-linecap="round"/>' +
      '<path d="M58 83 Q70 93 82 83 Z" fill="' + a.accent + '" opacity=".9"/>';
  }
  return '<ellipse class="bot-eye" cx="58" cy="70" rx="8" ry="9" fill="' + a.accent + '"/>' +
    '<ellipse class="bot-eye" cx="82" cy="70" rx="8" ry="9" fill="' + a.accent + '"/>' +
    '<circle cx="55" cy="67" r="2.4" fill="' + w + '"/><circle cx="79" cy="67" r="2.4" fill="' + w + '"/>' +
    '<rect x="62" y="86" width="16" height="3" rx="1.5" fill="' + a.accent + '" opacity=".5"/>';
}

//: `state` is one of idle/working/waiting/failed/ready. It used to be a
//: boolean for "thinking", which is why the old call sites passed one.
export function robot(id, state, ns) {
  var a = paletteOf(id), uid = (ns || "f") + id.replace(/[^a-z0-9]/gi, "");
  if (state === true) state = "working";          // the old boolean
  var eyes = faceFor(state, a);
  // Wide enough for the arms and the floor shadow. A tighter box drew them
  // only because the tile allowed overflow, which the panel portrait does not.
  return '<svg class="bot" viewBox="4 0 132 182" aria-hidden="true">' +
    '<defs><linearGradient id="g' + uid + '" x1="0" y1="0" x2="1" y2="1">' +
      '<stop offset="0%" stop-color="' + a.body + '"/>' +
      '<stop offset="100%" stop-color="' + a.body2 + '"/></linearGradient></defs>' +
    '<ellipse cx="70" cy="170" rx="38" ry="7" fill="#000" opacity=".26"/>' +
    '<rect class="bot-arm" x="16" y="102" width="15" height="48" rx="7" fill="url(#g' + uid + ')"/>' +
    '<rect class="bot-arm" x="109" y="102" width="15" height="48" rx="7" fill="url(#g' + uid + ')"/>' +
    '<circle cx="23" cy="154" r="8" fill="' + a.accent + '"/>' +
    '<circle cx="117" cy="154" r="8" fill="' + a.accent + '"/>' +
    '<rect class="bot-body" x="34" y="90" width="72" height="72" rx="18" ' +
      'fill="' + a.body + '"/>' +
    '<rect x="46" y="104" width="48" height="30" rx="10" fill="#0c1220"/>' +
    '<rect x="54" y="140" width="32" height="8" rx="4" fill="#0c1220"/>' +
    '<circle cx="70" cy="144" r="3" fill="' + a.accent + '"/>' +
    '<rect x="62" y="14" width="16" height="34" rx="8" fill="url(#g' + uid + ')"/>' +
    '<line x1="70" y1="6" x2="70" y2="16" stroke="' + a.accent + '" stroke-width="3" stroke-linecap="round"/>' +
    '<circle cx="70" cy="6" r="5" fill="' + a.accent + '"/>' +
    '<rect x="30" y="46" width="80" height="46" rx="16" fill="url(#g' + uid + ')"/>' +
    '<rect x="42" y="58" width="56" height="24" rx="8" fill="#0c1220"/>' + eyes +
    '<rect x="44" y="15" width="10" height="24" rx="5" fill="' + a.accent + '" opacity=".8"/>' +
    '<rect x="86" y="15" width="10" height="24" rx="5" fill="' + a.accent + '" opacity=".8"/>' +
    '</svg>';
}
