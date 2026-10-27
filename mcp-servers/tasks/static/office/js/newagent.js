// Making an agent without leaving the office (2026-10-16, "how can the
// user able to create or add agents in the office tab").
//
// The agents page has the whole form: tools, skills, every model. In the
// shell its header is hidden, and "+ New agent" with it, so there was no way
// to make one from the floor at all. This is the short form: a name, what
// they do, their instructions, a model and how much they may do. It writes
// the SAME ModelForm the agents page writes (agents.html buildAgentBody), to
// the same endpoint, so an agent made here is an ordinary agent that the
// agents page can open and edit. Everything it leaves out keeps the agents
// page's own default for a new agent: every tool this account has
// (toolIds server:mcp-proxy), no skills.
import { authHeaders, getJson } from "./util.js";

var API = "/api/v1/models";
//: agents.html AGENT_NAME_RE, MAX_INSTRUCTIONS, MAX_AGENTS: the same rules,
//: because the server does not check them and the agents page does.
var NAME_RE = /^[A-Za-z][A-Za-z0-9]{1,23}$/;
var MAX_INSTRUCTIONS = 4000;
var MAX_AGENTS = 25;
//: Pipes that hand the question back to your agents: an agent set to one
//: answers itself for ever (agents.html CALLBACK_MODELS).
var CALLBACK_MODELS = ["auto_router.auto", "io.io"];
//: Every agent's base model is the IO pipe, so that @mentioning it in the
//: main chat runs our loop; the language model is meta.llm (agents.html
//: AGENT_BASE and llmOf, agent_llm.py).
var AGENT_BASE = "io.io";
export function llmOf(m) {
  var base = (m && m.base_model_id) || "";
  if (CALLBACK_MODELS.indexOf(base) === -1) return base;
  var llm = m && m.meta && m.meta.llm;
  return typeof llm === "string" ? llm : "";
}
//: Models that cannot answer a chat turn at all (agents.html
//: NON_CHAT_MODELS, by prefix here rather than the whole list: every id on
//: that list starts with one of these, and a new image or audio model is
//: more likely to as well).
var NON_CHAT_PREFIXES = ["webhook_", "gpt-image", "chatgpt-image", "sora-",
                         "gpt-transcribe", "gpt-live-transcribe", "gpt-4o-transcribe",
                         "gpt-4o-mini-transcribe", "gpt-realtime", "gpt-audio",
                         "omni-moderation", "text-moderation", "text-embedding",
                         "tts-", "gpt-4o-mini-tts", "whisper", "dall-e",
                         "computer-use", "davinci", "babbage"];

function isAgent(m) { return /^agent-/.test(String(m && m.id || "")); }
function chattable(m) {
  var id = String(m && m.id || "");
  if (!id || isAgent(m) || CALLBACK_MODELS.indexOf(id) !== -1) return false;
  for (var i = 0; i < NON_CHAT_PREFIXES.length; i++) {
    if (id.indexOf(NON_CHAT_PREFIXES[i]) === 0) return false;
  }
  return true;
}

function slug(name) {
  return String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 40) || "agent";
}
export function newAgentId(name) {
  var hex = "0123456789abcdef", suffix = "";
  for (var i = 0; i < 4; i++) suffix += hex[Math.floor(Math.random() * 16)];
  return "agent-" + slug(name) + "-" + suffix;
}

//: The exact body the agents page posts for a new agent, less what this
//: form does not ask about. meta is written whole, so a key is only there
//: when it has a value: an agent with no role has no role key.
export function buildBody(f) {
  var meta = { description: f.instructions.slice(0, 120),
               toolIds: ["server:mcp-proxy"],
               agent_instructions: f.instructions,
               llm: f.baseModel };
  if (f.role) meta.role = f.role;
  if (f.access) meta.access = f.access;
  return { id: f.id, name: f.name, base_model_id: AGENT_BASE, meta: meta,
           params: { system: f.instructions }, access_grants: [], is_active: true };
}

//: What is wrong with the form, or nothing (agents.html save()).
export function problemWith(f, mine) {
  if (!f.name) return "Give the agent a name.";
  if (/\s/.test(f.name)) {
    return "Use one word, so you can say the name in a sentence. 'Jack' works, 'Research Agent' does not.";
  }
  if (!NAME_RE.test(f.name)) {
    return "A name is 2 to 24 characters, starts with a letter, and uses only letters and numbers.";
  }
  if (!f.instructions) return "Tell the agent what to do.";
  if (f.instructions.length > MAX_INSTRUCTIONS) {
    return "Instructions are " + f.instructions.length + " characters. The limit is 4000.";
  }
  if (mine >= MAX_AGENTS) {
    return "You have " + MAX_AGENTS + " agents, which is the limit. Delete one to make another.";
  }
  if (!f.baseModel) return "Pick a model for this agent.";
  return "";
}

async function isDuplicateId(r) {
  if (r.ok) return false;
  try {
    var d = await r.clone().json();
    return !!d && typeof d.detail === "string" && /already registered/i.test(d.detail);
  } catch (e) { return false; }
}

//: The models on offer, the platform's default first. Read once, the
//: first time the form opens: the roster does not change under a page.
var MODELS = null;
async function loadModels() {
  if (MODELS) return MODELS;
  var offered = [], preferred = "";
  try {
    var body = await getJson("/api/models");
    offered = (body.data || (Array.isArray(body) ? body : [])).filter(chattable);
  } catch (e) { console.warn("[office] could not list models", e); }
  try {
    var tb = await getJson("/api/tasks/agents/tools");
    if (tb && typeof tb.default_model === "string") preferred = tb.default_model;
  } catch (e) { /* no default known: the first on offer is as good */ }
  MODELS = { offered: offered, preferred: preferred };
  return MODELS;
}

export function initNewAgent(opts) {
  var back = document.getElementById("newagent");
  if (!back) return;
  var form = back.querySelector("form");
  var err = document.getElementById("na-error");
  var model = document.getElementById("na-model");
  var save = document.getElementById("na-save");
  var lastFocus = null;

  function say(msg) { err.textContent = msg || ""; err.hidden = !msg; }

  async function fillModels(agents) {
    var got = await loadModels();
    if (model.options.length) return;
    // Recommended is data, not taste: the platform default, then whatever
    // your own agents already run on.
    var ids = got.offered.map(function (m) { return m.id; });
    var rec = [];
    function recommend(id) {
      if (id && ids.indexOf(id) !== -1 && rec.indexOf(id) === -1) rec.push(id);
    }
    recommend(got.preferred);
    (agents || []).forEach(function (a) { recommend(llmOf(a)); });
    function group(label, list) {
      if (!list.length) return;
      var g = document.createElement("optgroup");
      g.label = label;
      list.forEach(function (m) {
        var o = document.createElement("option");
        o.value = m.id; o.textContent = m.name || m.id;
        g.appendChild(o);
      });
      model.appendChild(g);
    }
    group("Recommended", rec.map(function (id) { return got.offered[ids.indexOf(id)]; }));
    group("All models", got.offered.filter(function (m) { return rec.indexOf(m.id) === -1; }));
    if (rec.length) model.value = rec[0];
  }

  function open() {
    lastFocus = document.activeElement;
    back.hidden = false;
    say("");
    fillModels(opts.agents ? opts.agents() : []);
    var name = document.getElementById("na-name");
    if (name) name.focus();
  }
  function close() {
    back.hidden = true;
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) {} }
  }

  document.addEventListener("click", function (ev) {
    if (ev.target.closest(".new-agent-open")) { ev.preventDefault(); open(); }
  });
  back.addEventListener("click", function (ev) {
    if (ev.target === back || ev.target.closest(".na-cancel")) close();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !back.hidden) close();
  });

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var picked = form.querySelector('input[name="na-access"]:checked');
    var f = { name: document.getElementById("na-name").value.trim(),
              role: document.getElementById("na-role").value.trim(),
              instructions: document.getElementById("na-instructions").value.trim(),
              baseModel: model.value, access: picked ? picked.value : "" };
    var mine = opts.agents ? opts.agents().length : 0;
    var problem = problemWith(f, mine);
    if (problem) { say(problem); return; }
    f.id = newAgentId(f.name);
    var body = buildBody(f);
    save.disabled = true;
    try {
      var r = await fetch(API + "/create", { method: "POST", headers: authHeaders(),
                                             credentials: "include", body: JSON.stringify(body) });
      if (await isDuplicateId(r)) {
        body.id = newAgentId(f.name);
        r = await fetch(API + "/create", { method: "POST", headers: authHeaders(),
                                           credentials: "include", body: JSON.stringify(body) });
      }
      if (r.status === 401) throw new Error("Agents are not switched on for your account yet.");
      if (!r.ok) throw new Error("Could not save that agent.");
      // Rebuilds the server's model cache, without which a freshly made
      // agent answers "Model not found" in chat (agents.html, measured on
      // production). Fire and forget: the agent exists either way.
      getJson("/api/models").catch(function () {});
      form.reset();
      close();
      if (opts.onCreated) opts.onCreated(body.id, f.name);
    } catch (e) {
      // Never clear the form on failure: the person typed that.
      say(e.message || "Could not save that agent.");
    } finally {
      save.disabled = false;
    }
  });
}
