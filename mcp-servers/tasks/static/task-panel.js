/**
 * AIUI Admin Task Panel — injected into Open WebUI via Custom JS.
 *
 * Shows pending action items from meeting transcripts to the 4 admins,
 * lets them approve AI execution or claim manual handling, with live SSE
 * status updates during AI runs.
 */
(function () {
  "use strict";

  if (window.__aiuiTaskPanelLoaded) return;
  window.__aiuiTaskPanelLoaded = true;

  // ===== Config =====
  const API_BASE = "/api/tasks";
  const HISTORY_URL = "/tasks/static/task-history.html";
  const DISMISS_KEY = "aiui-tasks-dismissed-at";
  const DISMISS_TTL_MS = 4 * 60 * 60 * 1000; // 4 hours

  const TYPE_LABELS = {
    BUILD: "🔨 BUILD",
    RESEARCH: "🔍 RESEARCH",
    INTEGRATE: "🔗 INTEGRATE",
    ASK_USER: "❓ ASK",
    UNKNOWN: "• TASK",
  };
  const PRI_LABELS = { CRITICAL: "CRITICAL", IMPORTANT: "IMPORTANT", NICE_TO_HAVE: "NICE" };

  // ===== Styles =====
  const css = `
    .aiui-tp { position: fixed; top: 24px; right: 24px; width: 520px; max-height: 78vh;
      background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 14px;
      overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.04);
      display: flex; flex-direction: column; z-index: 9999;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: #fff; animation: aiui-tp-in 0.25s ease-out; }
    @keyframes aiui-tp-in { from { opacity: 0; transform: translateY(-10px) scale(0.98); } to { opacity: 1; transform: translateY(0) scale(1); } }
    .aiui-tp.minimized { width: auto; max-height: none; }
    .aiui-tp.minimized .aiui-tp-tabs, .aiui-tp.minimized .aiui-tp-body, .aiui-tp.minimized .aiui-tp-foot { display: none; }
    .aiui-tp.hidden { display: none; }
    .aiui-tp-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid #2a2a2a; background: #111; user-select: none; }
    .aiui-tp-head .title { display: flex; align-items: center; gap: 8px; }
    .aiui-tp-head .dot { width: 8px; height: 8px; border-radius: 50%; background: #ef4444; }
    .aiui-tp-head strong { font-size: 13px; }
    .aiui-tp-head .badge { background: #ef4444; color: #fff; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 10px; margin-left: 6px; display: none; }
    .aiui-tp.minimized .aiui-tp-head .badge { display: inline-block; }
    .aiui-tp-head .ctrls { display: flex; gap: 4px; }
    .aiui-tp-head .ctrls button { background: transparent; border: 0; color: #888; padding: 2px 8px; cursor: pointer; font-size: 14px; border-radius: 4px; }
    .aiui-tp-head .ctrls button:hover { background: #2a2a2a; color: #fff; }
    .aiui-tp-tabs { display: flex; border-bottom: 1px solid #2a2a2a; background: #0f0f0f; }
    .aiui-tp-tab { flex: 1; padding: 10px 12px; background: transparent; border: 0; color: #888; font-size: 12px; font-weight: 600; cursor: pointer; border-bottom: 2px solid transparent; text-transform: uppercase; letter-spacing: 0.5px; }
    .aiui-tp-tab:hover { color: #ccc; }
    .aiui-tp-tab.active { color: #fff; border-bottom-color: #3b82f6; }
    .aiui-tp-tab .count { display: inline-block; background: #2a2a2a; color: #ccc; font-size: 10px; padding: 1px 6px; border-radius: 8px; margin-left: 4px; }
    .aiui-tp-tab.active .count { background: #3b82f6; color: #fff; }
    .aiui-tp-body { padding: 14px; overflow-y: auto; flex: 1; }
    .aiui-tp-body::-webkit-scrollbar { width: 6px; }
    .aiui-tp-body::-webkit-scrollbar-thumb { background: #2a2a2a; border-radius: 3px; }
    .aiui-tp-empty { text-align: center; padding: 32px 16px; color: #666; font-size: 13px; }
    .aiui-tp-task { background: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; transition: border-color 0.15s; }
    .aiui-tp-task:hover { border-color: #3a3a3a; }
    .aiui-tp-task.running { border-color: #3b82f6; }
    .aiui-tp-badges { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
    .aiui-tp-badge { font-size: 10.5px; padding: 3px 8px; border-radius: 4px; font-weight: 600; letter-spacing: 0.3px; }
    .aiui-tp-badge.BUILD { background: #7f1d1d; color: #fee2e2; }
    .aiui-tp-badge.RESEARCH { background: #1e3a8a; color: #dbeafe; }
    .aiui-tp-badge.INTEGRATE { background: #365314; color: #bef264; }
    .aiui-tp-badge.ASK_USER { background: #7c2d12; color: #fed7aa; }
    .aiui-tp-badge.UNKNOWN { background: #374151; color: #d1d5db; }
    .aiui-tp-badge.priority { background: #1f2937; color: #9ca3af; }
    .aiui-tp-badge.live { background: #1e3a8a; color: #dbeafe; }
    .aiui-tp-desc { color: #fff; font-size: 14px; margin-bottom: 6px; line-height: 1.5; }
    .aiui-tp-meta { color: #666; font-size: 11.5px; margin-bottom: 10px; }
    .aiui-tp-assignee { color: #60a5fa; font-weight: 500; }
    .aiui-tp-actions { display: flex; gap: 8px; }
    .aiui-tp-actions button { flex: 1; border: 0; padding: 8px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; font-weight: 600; transition: background 0.15s; }
    .aiui-tp-btn-ai { background: #3b82f6; color: white; }
    .aiui-tp-btn-ai:hover { background: #2563eb; }
    .aiui-tp-btn-manual { background: #374151; color: #ddd; }
    .aiui-tp-btn-manual:hover { background: #4b5563; }
    .aiui-tp-btn-answer { background: #f59e0b; color: #000; }
    .aiui-tp-btn-answer:hover { background: #d97706; }
    .aiui-tp-btn-stop { background: #7f1d1d; color: #fff; }
    .aiui-tp-live { background: #000; border-radius: 4px; padding: 8px; font-family: monospace; font-size: 11px; color: #3b82f6; margin: 6px 0; max-height: 80px; overflow-y: auto; white-space: pre-wrap; }
    .aiui-tp-foot { border-top: 1px solid #2a2a2a; padding: 10px 14px; background: #0f0f0f; text-align: center; }
    .aiui-tp-foot a { color: #60a5fa; font-size: 12px; text-decoration: none; cursor: pointer; }
    .aiui-tp-foot a:hover { text-decoration: underline; }
    .aiui-tp-textarea { width: 100%; background: #000; color: #fff; border: 1px solid #2a2a2a; border-radius: 4px; padding: 6px; font-size: 12px; height: 50px; box-sizing: border-box; margin-bottom: 6px; resize: vertical; }
    .aiui-tp-done { opacity: 0.85; }
    .aiui-tp-done .aiui-tp-actions { display: none; }
    .aiui-tp-done-meta { display: flex; gap: 8px; align-items: center; font-size: 11px; color: #888; margin-top: 6px; }
    .aiui-tp-done-mode { padding: 2px 6px; border-radius: 3px; font-weight: 600; }
    .aiui-tp-done-mode.ai { background: #1e3a8a; color: #dbeafe; }
    .aiui-tp-done-mode.manual { background: #374151; color: #d1d5db; }
    .aiui-tp-check { color: #22c55e; font-weight: 700; }
  `;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  // ===== State =====
  const state = { activeTab: "pending", tasks: { pending: [], progress: [], done: [] }, sse: {} };

  // ===== Build DOM =====
  const panel = document.createElement("div");
  panel.className = "aiui-tp hidden";
  panel.innerHTML = `
    <div class="aiui-tp-head">
      <div class="title">
        <div class="dot"></div>
        <strong class="aiui-tp-title">Pending Tasks</strong>
        <span class="badge" data-role="badge">0</span>
      </div>
      <div class="ctrls">
        <button data-act="refresh" title="Refresh">⟳</button>
        <button data-act="min" title="Minimize">─</button>
        <button data-act="close" title="Close">✕</button>
      </div>
    </div>
    <div class="aiui-tp-tabs">
      <button class="aiui-tp-tab active" data-tab="pending">Pending <span class="count" data-count="pending">0</span></button>
      <button class="aiui-tp-tab" data-tab="progress">In Progress <span class="count" data-count="progress">0</span></button>
      <button class="aiui-tp-tab" data-tab="done">Done <span class="count" data-count="done">0</span></button>
    </div>
    <div class="aiui-tp-body" data-role="body"><div class="aiui-tp-empty">Loading…</div></div>
    <div class="aiui-tp-foot"><a data-act="history">See full history →</a></div>
  `;
  document.body.appendChild(panel);

  // ===== Helpers =====
  function $(sel, root = panel) { return root.querySelector(sel); }
  function $$(sel, root = panel) { return Array.from(root.querySelectorAll(sel)); }
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

  async function api(method, path, body) {
    const opts = { method, credentials: "include", headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(API_BASE + path, opts);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.status === 204 ? null : r.json();
  }

  async function refreshAll() {
    try {
      const [pending, progress, done] = await Promise.all([
        fetch(`${API_BASE}?status=pending`, { credentials: "include" }).then(r => r.ok ? r.json() : []),
        fetch(`${API_BASE}?status=progress`, { credentials: "include" }).then(r => r.ok ? r.json() : []),
        fetch(`${API_BASE}?status=done`,    { credentials: "include" }).then(r => r.ok ? r.json() : []),
      ]);
      state.tasks = { pending, progress, done };
    } catch (e) {
      console.error("[AIUI tasks] fetch failed:", e);
      state.tasks = { pending: [], progress: [], done: [] };
    }
    render();
  }

  function render() {
    const t = state.tasks;
    $('[data-count="pending"]').textContent  = t.pending.length;
    $('[data-count="progress"]').textContent = t.progress.length;
    $('[data-count="done"]').textContent     = t.done.length;
    const total = t.pending.length;
    $(".aiui-tp-title").textContent = total ? `${total} Pending Task${total === 1 ? "" : "s"}` : "No Pending Tasks";
    $('[data-role="badge"]').textContent = total;

    const body = $('[data-role="body"]');
    const list = t[state.activeTab];
    if (!list.length) {
      const msg = { pending: "No pending tasks.", progress: "Nothing running right now.", done: "No completed tasks yet." }[state.activeTab];
      body.innerHTML = `<div class="aiui-tp-empty">${msg}</div>`;
      return;
    }
    if (state.activeTab === "pending")  body.innerHTML = list.map(renderPending).join("");
    if (state.activeTab === "progress") body.innerHTML = list.map(renderProgress).join("");
    if (state.activeTab === "done")     body.innerHTML = list.map(renderDone).join("");

    // Wire buttons
    $$("[data-task-action]", body).forEach(btn => {
      btn.addEventListener("click", () => onAction(btn.dataset.taskId, btn.dataset.taskAction));
    });

    // Resume SSE for progress items
    if (state.activeTab === "progress") {
      list.forEach(t => { if (t.status === "running") openStream(t.id); });
    }
  }

  function renderPending(t) {
    const isAsk = t.action_type === "ASK_USER";
    const actions = isAsk
      ? `<button class="aiui-tp-btn-answer" data-task-action="answer-ui" data-task-id="${t.id}">💬 Answer</button>`
      : `<button class="aiui-tp-btn-ai" data-task-action="ai" data-task-id="${t.id}">⚡ AI</button>
         <button class="aiui-tp-btn-manual" data-task-action="manual" data-task-id="${t.id}">✋ Manual</button>`;
    const askInputUI = t.status === "awaiting_input"
      ? `<div style="background:#1a1208;border:1px solid #78350f;border-radius:4px;padding:8px;font-size:11px;color:#fcd34d;margin-bottom:8px;"><strong>AI says:</strong><br/>${escapeHtml(t.result || "")}</div>
         <textarea class="aiui-tp-textarea" data-textarea-id="${t.id}" placeholder="Reply to the AI…"></textarea>
         <div class="aiui-tp-actions"><button class="aiui-tp-btn-answer" data-task-action="answer-resume" data-task-id="${t.id}">↩ Reply</button></div>`
      : `<div class="aiui-tp-actions">${actions}</div>`;
    return `
      <div class="aiui-tp-task">
        <div class="aiui-tp-badges">
          <span class="aiui-tp-badge ${t.action_type}">${TYPE_LABELS[t.action_type] || TYPE_LABELS.UNKNOWN}</span>
          <span class="aiui-tp-badge priority">${PRI_LABELS[t.priority] || t.priority}</span>
          ${t.status === "awaiting_input" ? '<span class="aiui-tp-badge" style="background:#7c2d12;color:#fed7aa;">⚠️ NEEDS INPUT</span>' : ''}
        </div>
        <div class="aiui-tp-desc">${escapeHtml(t.description)}</div>
        <div class="aiui-tp-meta"><span class="aiui-tp-assignee">${escapeHtml(t.assignee_name)}</span></div>
        ${askInputUI}
      </div>`;
  }

  function renderProgress(t) {
    return `
      <div class="aiui-tp-task running" data-task-card-id="${t.id}">
        <div class="aiui-tp-badges">
          <span class="aiui-tp-badge ${t.action_type}">${TYPE_LABELS[t.action_type] || TYPE_LABELS.UNKNOWN}</span>
          <span class="aiui-tp-badge priority">${PRI_LABELS[t.priority] || t.priority}</span>
          ${t.status === "running" ? '<span class="aiui-tp-badge live">⚡ AI RUNNING</span>' : '<span class="aiui-tp-badge" style="background:#374151;color:#d1d5db;">✋ MANUAL</span>'}
        </div>
        <div class="aiui-tp-desc">${escapeHtml(t.description)}</div>
        <div class="aiui-tp-meta"><span class="aiui-tp-assignee">${escapeHtml(t.assignee_name)}</span></div>
        ${t.status === "running"
          ? `<div class="aiui-tp-live" data-live-id="${t.id}">Connecting…</div>
             <div class="aiui-tp-actions"><button class="aiui-tp-btn-stop" data-task-action="cancel" data-task-id="${t.id}">⏹ Stop</button></div>`
          : `<div class="aiui-tp-actions"><button class="aiui-tp-btn-ai" data-task-action="complete-prompt" data-task-id="${t.id}">✓ Mark Done</button></div>`}
      </div>`;
  }

  function renderDone(t) {
    return `
      <div class="aiui-tp-task aiui-tp-done">
        <div class="aiui-tp-badges">
          <span class="aiui-tp-badge ${t.action_type}">${TYPE_LABELS[t.action_type] || TYPE_LABELS.UNKNOWN}</span>
          <span class="aiui-tp-badge priority">${PRI_LABELS[t.priority] || t.priority}</span>
        </div>
        <div class="aiui-tp-desc">${escapeHtml(t.description)}</div>
        <div class="aiui-tp-done-meta">
          <span class="aiui-tp-check">${t.status === "completed" ? "✓ Done" : "✗ Failed"}</span>
          ${t.mode ? `<span class="aiui-tp-done-mode ${t.mode}">${t.mode === "ai" ? "⚡ AI" : "✋ Manual"}</span>` : ""}
          ${t.completed_at ? `<span>${new Date(t.completed_at).toLocaleString()}</span>` : ""}
        </div>
        <div class="aiui-tp-meta" style="margin-top:6px;margin-bottom:0;"><span class="aiui-tp-assignee">${escapeHtml(t.assignee_name)}</span></div>
      </div>`;
  }

  // ===== Actions =====
  async function onAction(id, action) {
    try {
      if (action === "ai") { await api("POST", `/${id}/execute`); openStream(id); switchTab("progress"); }
      else if (action === "manual") { await api("POST", `/${id}/manual`); refreshAll(); }
      else if (action === "cancel") { await api("POST", `/${id}/cancel`); refreshAll(); }
      else if (action === "answer-ui") {
        const ans = prompt("Your answer:");
        if (ans !== null) { await api("POST", `/${id}/answer`, { answer: ans }); refreshAll(); }
      }
      else if (action === "answer-resume") {
        const ta = panel.querySelector(`[data-textarea-id="${id}"]`);
        const ans = ta && ta.value.trim();
        if (!ans) { alert("Type a reply first."); return; }
        await api("POST", `/${id}/answer`, { answer: ans });
        refreshAll();
      }
      else if (action === "complete-prompt") {
        const note = prompt("Add a note about what you did:") || "";
        await api("POST", `/${id}/complete`, { result: note });
        refreshAll();
      }
    } catch (e) {
      alert(`Action failed: ${e.message}`);
    }
  }

  function openStream(id) {
    if (state.sse[id]) return;
    const ev = new EventSource(`${API_BASE}/${id}/stream`, { withCredentials: true });
    state.sse[id] = ev;
    const live = panel.querySelector(`[data-live-id="${id}"]`);
    if (live) live.textContent = "";
    ev.addEventListener("log", e => {
      const liveEl = panel.querySelector(`[data-live-id="${id}"]`);
      if (liveEl) { liveEl.textContent += e.data; liveEl.scrollTop = liveEl.scrollHeight; }
    });
    ev.addEventListener("done", () => { ev.close(); delete state.sse[id]; refreshAll(); });
    ev.addEventListener("error", () => { ev.close(); delete state.sse[id]; });
  }

  function switchTab(tab) {
    state.activeTab = tab;
    $$(".aiui-tp-tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
    render();
  }

  // ===== Header controls =====
  panel.addEventListener("click", e => {
    const act = e.target.dataset && e.target.dataset.act;
    const tab = e.target.dataset && e.target.dataset.tab;
    if (act === "refresh") refreshAll();
    else if (act === "min") panel.classList.toggle("minimized");
    else if (act === "close") {
      panel.classList.add("hidden");
      try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (_) {}
    }
    else if (act === "history") window.open(HISTORY_URL, "_blank");
    else if (tab) switchTab(tab);
    else if (panel.classList.contains("minimized") && !e.target.closest("button")) {
      panel.classList.remove("minimized");
    }
  });

  // ===== Bootstrap =====
  async function init() {
    await refreshAll();
    const dismissedAt = parseInt(localStorage.getItem(DISMISS_KEY) || "0", 10);
    const fresh = Date.now() - dismissedAt > DISMISS_TTL_MS;
    if (state.tasks.pending.length > 0 && fresh) {
      panel.classList.remove("hidden");
    } else {
      // Even when dismissed/empty, expose a global to reopen manually:
      console.log("[AIUI tasks] panel hidden — call window.aiuiTaskPanel.open() to show");
    }
  }

  window.aiuiTaskPanel = {
    open: () => panel.classList.remove("hidden"),
    refresh: refreshAll,
    state,
  };

  // Wait for page to be ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(init, 500));
  } else {
    setTimeout(init, 500);
  }
})();
