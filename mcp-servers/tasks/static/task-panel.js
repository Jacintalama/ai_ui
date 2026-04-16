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
    .aiui-tp-live { background: #000; border-radius: 6px; padding: 10px 12px; font-family: Consolas, Menlo, monospace; font-size: 11.5px; color: #d1d5db; margin: 6px 0; max-height: 240px; min-height: 60px; overflow-y: auto; white-space: normal; line-height: 1.5; }
    .aiui-tp-live:empty::before { content: "Waiting for Claude to start…"; color: #666; font-style: italic; }
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
        <button data-act="new-task" title="Create a new task">+</button>
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
    const canAi = t.action_type === "BUILD" || t.action_type === "INTEGRATE" || t.action_type === "RESEARCH";
    let actions;
    if (isAsk) {
      actions = `<button class="aiui-tp-btn-answer" data-task-action="answer-ui" data-task-id="${t.id}">💬 Answer</button>
                 <button class="aiui-tp-btn-manual" data-task-action="delete" data-task-id="${t.id}" title="Delete this task" style="flex:0 0 auto;padding:8px 10px;">🗑</button>`;
    } else if (canAi) {
      actions = `<button class="aiui-tp-btn-ai" data-task-action="ai" data-task-id="${t.id}">⚡ AI</button>
                 <button class="aiui-tp-btn-manual" data-task-action="manual" data-task-id="${t.id}">✋ Manual</button>
                 <button class="aiui-tp-btn-manual" data-task-action="delete" data-task-id="${t.id}" title="Delete this task" style="flex:0 0 auto;padding:8px 10px;">🗑</button>`;
    } else {
      actions = `<button class="aiui-tp-btn-manual" data-task-action="manual" data-task-id="${t.id}">✋ Manual</button>
                 <button class="aiui-tp-btn-manual" data-task-action="delete" data-task-id="${t.id}" title="Delete this task" style="flex:0 0 auto;padding:8px 10px;">🗑</button>`;
    }
    const askInputUI = t.status === "awaiting_input"
      ? `<div style="background:#1a1208;border:1px solid #78350f;border-radius:4px;padding:8px;font-size:11px;color:#fcd34d;margin-bottom:8px;"><strong>AI says:</strong><br/>${escapeHtml(t.result || "")}</div>
         <textarea class="aiui-tp-textarea" data-textarea-id="${t.id}" placeholder="Reply to the AI…"></textarea>
         <div class="aiui-tp-actions"><button class="aiui-tp-btn-answer" data-task-action="answer-resume" data-task-id="${t.id}">↩ Reply</button></div>`
      : `<div class="aiui-tp-actions">${actions}</div>`;
    // If a previous AI run failed, show a small warning + the reason
    const priorFailHint = (!t.mode && t.result && !isAsk && t.status === "pending")
      ? `<div style="background:#1a0a0a;border:1px solid #7f1d1d;border-radius:4px;padding:6px 8px;font-size:11px;color:#fca5a5;margin-bottom:8px;">
           ⚠️ Previous attempt failed — <span style="color:#f87171;">${escapeHtml((t.result || "").slice(0, 140))}</span>
         </div>`
      : "";
    return `
      <div class="aiui-tp-task">
        <div class="aiui-tp-badges">
          <span class="aiui-tp-badge ${t.action_type}">${TYPE_LABELS[t.action_type] || TYPE_LABELS.UNKNOWN}</span>
          <span class="aiui-tp-badge priority">${PRI_LABELS[t.priority] || t.priority}</span>
          ${t.status === "awaiting_input" ? '<span class="aiui-tp-badge" style="background:#7c2d12;color:#fed7aa;">⚠️ NEEDS INPUT</span>' : ''}
        </div>
        <div class="aiui-tp-desc">${escapeHtml(t.description)}</div>
        <div class="aiui-tp-meta"><span class="aiui-tp-assignee">${escapeHtml(t.assignee_name)}</span></div>
        ${priorFailHint}
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
          ? `<div class="aiui-tp-live" data-live-id="${t.id}"><span style="color:#888;">◦ Spawning Claude (takes ~10s)…</span></div>
             <div class="aiui-tp-actions"><button class="aiui-tp-btn-stop" data-task-action="cancel" data-task-id="${t.id}">⏹ Stop</button></div>`
          : `<div class="aiui-tp-actions"><button class="aiui-tp-btn-ai" data-task-action="complete-prompt" data-task-id="${t.id}">✓ Mark Done</button></div>`}
      </div>`;
  }

  function renderDone(t) {
    const isFailed = t.status === "failed";
    const takeOverBtn = isFailed
      ? `<button class="aiui-tp-btn-manual" data-task-action="take-over" data-task-id="${t.id}">✋ Take over manually</button>`
      : "";
    const resultBlock = t.result
      ? `<div style="background:${isFailed ? '#1a0a0a' : '#0a1a14'};border:1px solid ${isFailed ? '#7f1d1d' : '#065f46'};border-radius:6px;padding:8px 10px;font-size:12px;color:${isFailed ? '#fca5a5' : '#86efac'};margin-top:8px;line-height:1.5;white-space:pre-wrap;">${escapeHtml(t.result)}</div>`
      : "";
    return `
      <div class="aiui-tp-task aiui-tp-done" data-task-card="${t.id}">
        <div class="aiui-tp-done-header" data-task-action="toggle-done" data-task-id="${t.id}" style="cursor:pointer;display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
          <div style="flex:1;min-width:0;">
            <div class="aiui-tp-badges">
              <span class="aiui-tp-badge ${t.action_type}">${TYPE_LABELS[t.action_type] || TYPE_LABELS.UNKNOWN}</span>
              <span class="aiui-tp-badge priority">${PRI_LABELS[t.priority] || t.priority}</span>
            </div>
            <div class="aiui-tp-desc">${escapeHtml(t.description)}</div>
            <div class="aiui-tp-done-meta">
              <span class="aiui-tp-check" style="${isFailed ? 'color:#ef4444;' : ''}">${isFailed ? "✗ Failed" : "✓ Done"}</span>
              ${t.mode ? `<span class="aiui-tp-done-mode ${t.mode}">${t.mode === "ai" ? "⚡ AI" : "✋ Manual"}</span>` : ""}
              ${t.completed_at ? `<span>${new Date(t.completed_at).toLocaleString()}</span>` : ""}
            </div>
            <div class="aiui-tp-meta" style="margin-top:6px;margin-bottom:0;"><span class="aiui-tp-assignee">${escapeHtml(t.assignee_name)}</span></div>
          </div>
          <span class="aiui-tp-chev" style="color:#888;font-size:13px;transition:transform 0.2s;user-select:none;margin-top:4px;">▾</span>
        </div>
        <div class="aiui-tp-done-details" data-task-details="${t.id}" style="display:none;">
          ${resultBlock}
          <div class="aiui-tp-actions" style="margin-top:8px;">
            <button class="aiui-tp-btn-manual" data-task-action="view-log" data-task-id="${t.id}" style="font-size:11px;padding:5px 8px;">📜 View full AI log</button>
            ${takeOverBtn}
          </div>
        </div>
      </div>`;
  }

  // ===== Actions =====
  const _inflight = new Set();
  async function onAction(id, action) {
    const key = `${id}:${action}`;
    if (_inflight.has(key)) return; // debounce double-clicks
    _inflight.add(key);
    // Disable the clicked button visually
    const btns = Array.from(panel.querySelectorAll(`[data-task-action="${action}"][data-task-id="${id}"]`));
    btns.forEach(b => { b.disabled = true; b.style.opacity = "0.5"; b.style.cursor = "wait"; });
    try {
      if (action === "ai") {
        try {
          await api("POST", `/${id}/execute`);
        } catch (e) {
          // 409 = task is already running (most common double-click cause).
          // Treat as success and just switch tabs to show progress.
          if (!String(e.message || "").includes("409")) throw e;
        }
        await refreshAll();
        switchTab("progress");
        openStream(id);
      }
      else if (action === "manual" || action === "take-over") {
        await api("POST", `/${id}/manual`);
        await refreshAll();
        if (action === "take-over") switchTab("progress");
      }
      else if (action === "cancel") {
        await api("POST", `/${id}/cancel`);
        await refreshAll();
      }
      else if (action === "answer-ui") {
        showTextModal({
          title: "Answer this ASK_USER task",
          placeholder: "Your answer…",
          saveLabel: "Send answer",
          onSave: async (ans) => { await api("POST", `/${id}/answer`, { answer: ans }); await refreshAll(); },
        });
      }
      else if (action === "delete") {
        if (!confirm("Delete this pending task? This cannot be undone.")) return;
        await api("DELETE", `/${id}`);
        await refreshAll();
      }
      else if (action === "answer-resume") {
        const ta = panel.querySelector(`[data-textarea-id="${id}"]`);
        const ans = ta && ta.value.trim();
        if (!ans) { alert("Type a reply first."); return; }
        await api("POST", `/${id}/answer`, { answer: ans });
        await refreshAll();
      }
      else if (action === "complete-prompt") {
        showTextModal({
          title: "Mark as Done",
          placeholder: "What did you do? (optional note)",
          saveLabel: "Mark Done",
          allowEmpty: true,
          onSave: async (note) => { await api("POST", `/${id}/complete`, { result: note || "" }); await refreshAll(); },
        });
      }
      else if (action === "view-log") {
        showLogModal(id);
      }
      else if (action === "toggle-done") {
        const details = panel.querySelector(`[data-task-details="${id}"]`);
        const chev = panel.querySelector(`[data-task-card="${id}"] .aiui-tp-chev`);
        if (details) {
          const open = details.style.display !== "none";
          details.style.display = open ? "none" : "block";
          if (chev) chev.style.transform = open ? "rotate(0deg)" : "rotate(180deg)";
        }
      }
    } catch (e) {
      alert(`Action failed: ${e.message}`);
    } finally {
      _inflight.delete(key);
      btns.forEach(b => { b.disabled = false; b.style.opacity = ""; b.style.cursor = ""; });
    }
  }

  function openStream(id) {
    if (state.sse[id]) return;
    const ev = new EventSource(`${API_BASE}/${id}/stream`, { withCredentials: true });
    state.sse[id] = ev;
    const live = panel.querySelector(`[data-live-id="${id}"]`);
    if (live) { live.textContent = ""; live.dataset.streamBuf = ""; }

    ev.addEventListener("log", e => {
      const liveEl = panel.querySelector(`[data-live-id="${id}"]`);
      if (!liveEl) return;
      const buf = (liveEl.dataset.streamBuf || "") + e.data;
      const parts = buf.split("\n");
      liveEl.dataset.streamBuf = parts.pop(); // last partial line
      for (const line of parts) {
        const pretty = prettifyStreamLine(line);
        if (pretty) appendLiveLine(liveEl, pretty);
      }
    });
    ev.addEventListener("done", () => { ev.close(); delete state.sse[id]; refreshAll(); });
    ev.addEventListener("error", () => { ev.close(); delete state.sse[id]; });
  }

  function appendLiveLine(el, html) {
    const line = document.createElement("div");
    line.innerHTML = html;
    line.style.cssText = "padding:2px 0;";
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
  }

  // Convert one line of Claude's stream-json into a readable status
  function prettifyStreamLine(line) {
    line = line.trim();
    if (!line || !line.startsWith("{")) return null;
    let obj;
    try { obj = JSON.parse(line); } catch (_) { return null; }
    if (obj.type === "system" && obj.subtype === "init") {
      return `<span style="color:#60a5fa;">◦ Claude session started</span>`;
    }
    if (obj.type === "assistant" && obj.message && Array.isArray(obj.message.content)) {
      const bits = [];
      for (const c of obj.message.content) {
        if (c.type === "tool_use") {
          const name = c.name || "tool";
          const inp = c.input || {};
          if (name === "Read" && inp.file_path) bits.push(`📖 Reading <span style="color:#86efac;">${escapeHtml(inp.file_path)}</span>`);
          else if ((name === "Write" || name === "Edit") && inp.file_path) bits.push(`✏️ Editing <span style="color:#fcd34d;">${escapeHtml(inp.file_path)}</span>`);
          else if (name === "Bash" && inp.command) bits.push(`▶ <span style="color:#c084fc;">${escapeHtml(String(inp.command).slice(0, 90))}</span>`);
          else if (name === "Grep" && inp.pattern) bits.push(`🔎 Grep <span style="color:#86efac;">${escapeHtml(String(inp.pattern).slice(0, 60))}</span>`);
          else if (name === "Glob" && inp.pattern) bits.push(`🔎 Glob <span style="color:#86efac;">${escapeHtml(String(inp.pattern).slice(0, 60))}</span>`);
          else if (name === "WebSearch" || name === "WebFetch") bits.push(`🌐 ${name}`);
          else bits.push(`⚙ ${escapeHtml(name)}`);
        } else if (c.type === "text" && c.text && c.text.trim()) {
          const txt = c.text.trim();
          // Skip the verbose assistant text; show only short one-liners
          if (txt.length < 140) bits.push(`<span style="color:#d1d5db;">${escapeHtml(txt)}</span>`);
        }
      }
      return bits.join("<br>");
    }
    if (obj.type === "user" && obj.message && Array.isArray(obj.message.content)) {
      for (const c of obj.message.content) {
        if (c.type === "tool_result") {
          const ok = !c.is_error;
          const note = ok ? "✓ ok" : "✗ error";
          const color = ok ? "#4ade80" : "#f87171";
          return `<span style="color:${color};font-size:11px;">  ↳ ${note}</span>`;
        }
      }
    }
    if (obj.type === "result") {
      const sub = obj.subtype || "finished";
      return `<span style="color:#4ade80;font-weight:600;">◉ ${escapeHtml(sub)}</span>`;
    }
    return null;
  }

  async function showHistoryModal() {
    try {
      const r = await fetch(`${API_BASE}/history?limit=100`, { credentials: "include" });
      if (!r.ok) { alert("Failed to fetch history: " + r.status); return; }
      const items = await r.json();

      // If already open, just bring to front
      const existing = document.querySelector("[data-aiui-hist-window]");
      if (existing) { existing.remove(); }

      // Floating, draggable window — not a backdrop modal
      const modal = document.createElement("div");
      modal.dataset.aiuiHistWindow = "1";
      const HIST_POS_KEY = "aiui-hist-panel-pos";
      let savedPos = null;
      try { savedPos = JSON.parse(localStorage.getItem(HIST_POS_KEY) || "null"); } catch (_) {}
      const top = savedPos && typeof savedPos.top === "number" ? Math.max(8, Math.min(window.innerHeight - 80, savedPos.top)) : 80;
      const left = savedPos && typeof savedPos.left === "number" ? Math.max(8, Math.min(window.innerWidth - 100, savedPos.left)) : (window.innerWidth - 920) / 2;
      modal.style.cssText = `position:fixed;top:${top}px;left:${left}px;background:#0f0f0f;border:1px solid #2a2a2a;border-radius:12px;width:min(900px, 92vw);max-height:78vh;display:flex;flex-direction:column;overflow:hidden;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;z-index:10000;box-shadow:0 20px 60px rgba(0,0,0,0.7),0 0 0 1px rgba(255,255,255,0.04);animation:aiui-tp-in 0.2s ease-out;`;
      modal.innerHTML = `
        <div id="aiui-hist-head" style="display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid #2a2a2a;background:#111;cursor:move;user-select:none;">
          <div>
            <strong style="font-size:15px;">Task History</strong>
            <div style="color:#888;font-size:12px;margin-top:2px;">${items.length} completed or failed tasks · drag to move</div>
          </div>
          <button id="aiui-hist-close" style="background:transparent;border:0;color:#888;font-size:22px;cursor:pointer;line-height:1;padding:0 6px;">×</button>
        </div>
        <div id="aiui-hist-body" style="overflow-y:auto;flex:1;padding:8px 12px;"></div>
      `;
      document.body.appendChild(modal);

      // Drag support on the header
      (function enableDrag() {
        const head = modal.querySelector("#aiui-hist-head");
        let dragging = false, offX = 0, offY = 0;
        head.addEventListener("mousedown", (e) => {
          if (e.target.closest("button")) return;
          dragging = true;
          const rect = modal.getBoundingClientRect();
          offX = e.clientX - rect.left;
          offY = e.clientY - rect.top;
          modal.style.transition = "none";
          e.preventDefault();
        });
        document.addEventListener("mousemove", (e) => {
          if (!dragging) return;
          const l = Math.max(0, Math.min(window.innerWidth - 100, e.clientX - offX));
          const t = Math.max(0, Math.min(window.innerHeight - 60, e.clientY - offY));
          modal.style.left = l + "px";
          modal.style.top = t + "px";
        });
        document.addEventListener("mouseup", () => {
          if (!dragging) return;
          dragging = false;
          modal.style.transition = "";
          const rect = modal.getBoundingClientRect();
          localStorage.setItem(HIST_POS_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
        });
      })();

      const body = modal.querySelector("#aiui-hist-body");
      if (!items.length) {
        body.innerHTML = '<div style="color:#888;text-align:center;padding:40px;">No completed tasks yet.</div>';
      } else {
        body.innerHTML = items.map(renderHistoryRow).join("");
        // Wire up expand chevrons
        body.querySelectorAll("[data-hist-toggle]").forEach(row => {
          row.addEventListener("click", (ev) => {
            if (ev.target.closest("button")) return;
            const id = row.dataset.histToggle;
            const det = body.querySelector(`[data-hist-details="${id}"]`);
            const chev = row.querySelector(".aiui-hist-chev");
            if (det) {
              const open = det.style.display !== "none";
              det.style.display = open ? "none" : "block";
              if (chev) chev.style.transform = open ? "rotate(0deg)" : "rotate(180deg)";
            }
          });
        });
        // Wire "View full AI log" buttons
        body.querySelectorAll("[data-hist-log]").forEach(btn => {
          btn.addEventListener("click", (ev) => {
            ev.stopPropagation();
            showLogModal(btn.dataset.histLog);
          });
        });
      }

      modal.querySelector("#aiui-hist-close").addEventListener("click", () => modal.remove());
    } catch (e) { alert("Failed: " + e.message); }
  }

  function renderHistoryRow(t) {
    const isFailed = t.status === "failed";
    const typeColors = { BUILD: "#7f1d1d", RESEARCH: "#1e3a8a", INTEGRATE: "#365314", ASK_USER: "#7c2d12" };
    const typeBg = typeColors[t.action_type] || "#374151";
    return `
      <div style="border:1px solid #2a2a2a;border-radius:8px;margin-bottom:8px;overflow:hidden;">
        <div data-hist-toggle="${t.id}" style="padding:12px 14px;cursor:pointer;display:flex;gap:12px;align-items:center;background:#111;">
          <div style="flex:1;min-width:0;">
            <div style="display:flex;gap:6px;margin-bottom:4px;flex-wrap:wrap;">
              <span style="font-size:10.5px;padding:3px 8px;border-radius:4px;font-weight:600;background:${typeBg};color:#fff;">${escapeHtml(t.action_type)}</span>
              <span style="font-size:10.5px;padding:3px 8px;border-radius:4px;background:${isFailed?'#7f1d1d':'#065f46'};color:#fff;font-weight:600;">${isFailed?'FAILED':'DONE'}</span>
              ${t.mode?`<span style="font-size:10.5px;padding:3px 8px;border-radius:4px;background:${t.mode==='ai'?'#1e3a8a':'#374151'};color:#fff;font-weight:600;">${t.mode==='ai'?'AI':'MANUAL'}</span>`:''}
            </div>
            <div style="font-size:13px;line-height:1.4;">${escapeHtml(t.description)}</div>
            <div style="font-size:11px;color:#666;margin-top:4px;">${t.completed_at?new Date(t.completed_at).toLocaleString():''}</div>
          </div>
          <span class="aiui-hist-chev" style="color:#888;transition:transform 0.2s;">▾</span>
        </div>
        <div data-hist-details="${t.id}" style="display:none;padding:12px 14px;background:#0a0a0a;border-top:1px solid #2a2a2a;">
          ${t.result ? `<div style="background:${isFailed?'#1a0a0a':'#0a1a14'};border:1px solid ${isFailed?'#7f1d1d':'#065f46'};border-radius:6px;padding:10px 12px;font-size:12.5px;color:${isFailed?'#fca5a5':'#86efac'};line-height:1.5;white-space:pre-wrap;">${escapeHtml(t.result)}</div>` : '<div style="color:#666;font-size:12px;">(no result recorded)</div>'}
          <div style="display:flex;gap:8px;margin-top:10px;align-items:center;">
            <button data-hist-log="${t.id}" style="background:#1e3a8a;color:#dbeafe;border:0;padding:6px 10px;border-radius:6px;font-size:11px;cursor:pointer;font-weight:600;">📜 View full AI log</button>
            <span style="color:#555;font-size:11px;">Meeting: ${escapeHtml(String(t.meeting_id).slice(0,8))}…</span>
          </div>
        </div>
      </div>
    `;
  }

  // ===== Floating draggable form modal (used for create / note / answer) =====
  function makeFloatingModal(title, bodyHtml, posKey) {
    // Remove any existing instance of the same kind
    const existing = document.querySelector(`[data-aiui-modal="${posKey}"]`);
    if (existing) existing.remove();

    const modal = document.createElement("div");
    modal.dataset.aiuiModal = posKey;
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(posKey) || "null"); } catch (_) {}
    const top  = saved && typeof saved.top === "number" ? Math.max(8, Math.min(window.innerHeight-80, saved.top)) : 100;
    const left = saved && typeof saved.left === "number" ? Math.max(8, Math.min(window.innerWidth-100, saved.left)) : Math.max(20, (window.innerWidth - 520) / 2);
    modal.style.cssText = `position:fixed;top:${top}px;left:${left}px;background:#0f0f0f;border:1px solid #2a2a2a;border-radius:12px;width:min(520px, 92vw);display:flex;flex-direction:column;overflow:hidden;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;z-index:10001;box-shadow:0 20px 60px rgba(0,0,0,0.7),0 0 0 1px rgba(255,255,255,0.04);animation:aiui-tp-in 0.2s ease-out;`;
    modal.innerHTML = `
      <div class="aiui-modal-head" style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #2a2a2a;background:#111;cursor:move;user-select:none;">
        <strong style="font-size:14px;">${escapeHtml(title)}</strong>
        <button data-modal-close style="background:transparent;border:0;color:#888;font-size:20px;cursor:pointer;line-height:1;padding:0 6px;">×</button>
      </div>
      <div style="padding:14px 16px;">${bodyHtml}</div>
    `;
    document.body.appendChild(modal);

    // Drag
    (function () {
      const head = modal.querySelector(".aiui-modal-head");
      let dragging = false, offX = 0, offY = 0;
      head.addEventListener("mousedown", (e) => {
        if (e.target.closest("button")) return;
        dragging = true;
        const r = modal.getBoundingClientRect();
        offX = e.clientX - r.left; offY = e.clientY - r.top;
        e.preventDefault();
      });
      document.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        const l = Math.max(0, Math.min(window.innerWidth - 100, e.clientX - offX));
        const t = Math.max(0, Math.min(window.innerHeight - 60, e.clientY - offY));
        modal.style.left = l + "px"; modal.style.top = t + "px";
      });
      document.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        const r = modal.getBoundingClientRect();
        localStorage.setItem(posKey, JSON.stringify({ left: r.left, top: r.top }));
      });
    })();

    modal.querySelector("[data-modal-close]").addEventListener("click", () => modal.remove());
    return modal;
  }

  // Simple single-textarea modal (reused for manual note + ASK_USER answer)
  function showTextModal({ title, placeholder, saveLabel, onSave, allowEmpty = false }) {
    const html = `
      <textarea data-ta style="width:100%;background:#000;color:#fff;border:1px solid #2a2a2a;border-radius:6px;padding:10px 12px;font-size:13px;font-family:Consolas,Menlo,monospace;height:110px;box-sizing:border-box;resize:vertical;" placeholder="${escapeHtml(placeholder || '')}"></textarea>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
        <button data-cancel style="background:#374151;color:#ddd;border:0;padding:8px 14px;border-radius:6px;cursor:pointer;font-weight:600;">Cancel</button>
        <button data-save style="background:#3b82f6;color:#fff;border:0;padding:8px 14px;border-radius:6px;cursor:pointer;font-weight:600;">${escapeHtml(saveLabel || 'Save')}</button>
      </div>
    `;
    const modal = makeFloatingModal(title, html, "aiui-text-modal");
    const ta = modal.querySelector("[data-ta]");
    setTimeout(() => ta.focus(), 50);
    modal.querySelector("[data-cancel]").addEventListener("click", () => modal.remove());
    modal.querySelector("[data-save]").addEventListener("click", async () => {
      const val = ta.value.trim();
      if (!allowEmpty && !val) { ta.focus(); return; }
      try {
        modal.querySelector("[data-save]").disabled = true;
        await onSave(val);
        modal.remove();
      } catch (e) {
        alert("Failed: " + e.message);
        modal.querySelector("[data-save]").disabled = false;
      }
    });
  }

  // Create-task form modal
  async function showCreateTaskModal() {
    const auth = await getAuthInfo();
    const currentEmail = (auth && auth.email) || "me";
    const html = `
      <label style="display:block;font-size:12px;color:#888;margin-bottom:4px;">Description</label>
      <textarea data-desc style="width:100%;background:#000;color:#fff;border:1px solid #2a2a2a;border-radius:6px;padding:10px 12px;font-size:13px;height:80px;box-sizing:border-box;resize:vertical;" placeholder="What needs doing?"></textarea>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px;">
        <div>
          <label style="display:block;font-size:12px;color:#888;margin-bottom:4px;">Type</label>
          <select data-type style="width:100%;background:#000;color:#fff;border:1px solid #2a2a2a;border-radius:6px;padding:8px;font-size:13px;">
            <option value="BUILD">BUILD</option>
            <option value="INTEGRATE">INTEGRATE</option>
            <option value="RESEARCH">RESEARCH</option>
            <option value="ASK_USER">ASK_USER</option>
          </select>
        </div>
        <div>
          <label style="display:block;font-size:12px;color:#888;margin-bottom:4px;">Priority</label>
          <select data-prio style="width:100%;background:#000;color:#fff;border:1px solid #2a2a2a;border-radius:6px;padding:8px;font-size:13px;">
            <option value="IMPORTANT">IMPORTANT</option>
            <option value="CRITICAL">CRITICAL</option>
            <option value="NICE_TO_HAVE">NICE_TO_HAVE</option>
          </select>
        </div>
      </div>

      <div style="margin-top:10px;">
        <label style="display:block;font-size:12px;color:#888;margin-bottom:4px;">Assignee</label>
        <select data-assignee style="width:100%;background:#000;color:#fff;border:1px solid #2a2a2a;border-radius:6px;padding:8px;font-size:13px;">
          <option value="self">Me (${escapeHtml(currentEmail)})</option>
          <option value="Ralph">Ralph</option>
          <option value="Clarenz">Clarenz</option>
          <option value="Lukas">Lukas</option>
          <option value="Jacint">Jacint</option>
          <option value="team">Team (visible to all admins)</option>
        </select>
      </div>

      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px;">
        <button data-cancel style="background:#374151;color:#ddd;border:0;padding:8px 14px;border-radius:6px;cursor:pointer;font-weight:600;">Cancel</button>
        <button data-save style="background:#10b981;color:#fff;border:0;padding:8px 14px;border-radius:6px;cursor:pointer;font-weight:600;">+ Create task</button>
      </div>
    `;
    const modal = makeFloatingModal("New task", html, "aiui-create-modal");
    setTimeout(() => modal.querySelector("[data-desc]").focus(), 50);
    modal.querySelector("[data-cancel]").addEventListener("click", () => modal.remove());
    modal.querySelector("[data-save]").addEventListener("click", async () => {
      const desc = modal.querySelector("[data-desc]").value.trim();
      if (!desc) { modal.querySelector("[data-desc]").focus(); return; }
      const body = {
        description: desc,
        action_type: modal.querySelector("[data-type]").value,
        priority: modal.querySelector("[data-prio]").value,
        assignee: modal.querySelector("[data-assignee]").value,
      };
      try {
        modal.querySelector("[data-save]").disabled = true;
        await api("POST", "", body);
        modal.remove();
        await refreshAll();
        switchTab("pending");
      } catch (e) {
        alert("Create failed: " + e.message);
        modal.querySelector("[data-save]").disabled = false;
      }
    });
  }

  async function showLogModal(taskId) {
    try {
      const r = await fetch(`${API_BASE}/${taskId}/executions`, { credentials: "include" });
      if (!r.ok) { alert("Failed to fetch log: " + r.status); return; }
      const execs = await r.json();
      const backdrop = document.createElement("div");
      backdrop.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:99999;display:flex;align-items:center;justify-content:center;padding:20px;";
      const modal = document.createElement("div");
      modal.style.cssText = "background:#0f0f0f;border:1px solid #2a2a2a;border-radius:12px;max-width:900px;width:100%;max-height:80vh;display:flex;flex-direction:column;overflow:hidden;";
      modal.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid #2a2a2a;">
          <strong style="color:#fff;font-size:15px;">AI Execution Log</strong>
          <button id="aiui-log-close" style="background:transparent;border:0;color:#888;font-size:22px;cursor:pointer;line-height:1;">×</button>
        </div>
        <div id="aiui-log-body" style="padding:16px 20px;overflow-y:auto;flex:1;"></div>
      `;
      backdrop.appendChild(modal);
      document.body.appendChild(backdrop);

      const body = modal.querySelector("#aiui-log-body");
      if (!execs.length) {
        body.innerHTML = '<div style="color:#888;text-align:center;padding:40px;">No AI runs for this task (was claimed manually).</div>';
      } else {
        body.innerHTML = execs.map((e, i) => `
          <div style="margin-bottom:14px;border:1px solid #2a2a2a;border-radius:8px;overflow:hidden;">
            <div style="padding:10px 14px;background:#111;display:flex;justify-content:space-between;gap:10px;align-items:center;font-size:12px;">
              <div>
                <strong style="color:${e.status === 'succeeded' ? '#22c55e' : e.status === 'failed' ? '#ef4444' : '#f59e0b'};">${escapeHtml(e.status)}</strong>
                <span style="color:#666;margin-left:8px;">Run ${execs.length - i}</span>
              </div>
              <div style="color:#666;">${e.started_at ? new Date(e.started_at).toLocaleString() : ''}</div>
            </div>
            ${e.error ? `<div style="padding:10px 14px;background:#1a0a0a;color:#fca5a5;font-size:12px;border-top:1px solid #2a2a2a;">Error: ${escapeHtml(e.error)}</div>` : ''}
            <pre style="margin:0;padding:14px;background:#000;color:#d1d5db;font-family:Consolas,Menlo,monospace;font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-word;max-height:400px;overflow:auto;">${escapeHtml(e.log || "(no output)")}</pre>
          </div>`).join("");
      }

      function close() { backdrop.remove(); }
      modal.querySelector("#aiui-log-close").addEventListener("click", close);
      backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    } catch (e) { alert("Failed: " + e.message); }
  }

  function switchTab(tab) {
    state.activeTab = tab;
    $$(".aiui-tp-tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
    render();
  }

  // ===== Drag to move =====
  const POS_KEY = "aiui-tasks-panel-pos";
  (function restorePos() {
    try {
      const pos = JSON.parse(localStorage.getItem(POS_KEY) || "null");
      if (pos && typeof pos.left === "number" && typeof pos.top === "number") {
        panel.style.left = Math.max(0, Math.min(window.innerWidth - 100, pos.left)) + "px";
        panel.style.top = Math.max(0, Math.min(window.innerHeight - 60, pos.top)) + "px";
        panel.style.right = "auto";
      }
    } catch (_) {}
  })();

  (function enableDrag() {
    const header = panel.querySelector(".aiui-tp-head");
    if (!header) return;
    header.style.cursor = "move";
    let dragging = false, offX = 0, offY = 0;

    header.addEventListener("mousedown", e => {
      // Don't start drag when clicking a button in the header
      if (e.target.closest("button")) return;
      dragging = true;
      const rect = panel.getBoundingClientRect();
      offX = e.clientX - rect.left;
      offY = e.clientY - rect.top;
      panel.style.transition = "none";
      e.preventDefault();
    });

    document.addEventListener("mousemove", e => {
      if (!dragging) return;
      let left = e.clientX - offX;
      let top = e.clientY - offY;
      // Clamp to viewport
      left = Math.max(0, Math.min(window.innerWidth - 100, left));
      top = Math.max(0, Math.min(window.innerHeight - 60, top));
      panel.style.left = left + "px";
      panel.style.top = top + "px";
      panel.style.right = "auto";
    });

    document.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      panel.style.transition = "";
      const rect = panel.getBoundingClientRect();
      localStorage.setItem(POS_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
    });
  })();

  // ===== Header controls =====
  panel.addEventListener("click", e => {
    const act = e.target.dataset && e.target.dataset.act;
    const tab = e.target.dataset && e.target.dataset.tab;
    if (act === "new-task") showCreateTaskModal();
    else if (act === "refresh") refreshAll();
    else if (act === "min") panel.classList.toggle("minimized");
    else if (act === "close") {
      panel.classList.add("hidden");
      try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (_) {}
    }
    else if (act === "history") showHistoryModal();
    else if (tab) switchTab(tab);
    else if (panel.classList.contains("minimized") && !e.target.closest("button")) {
      panel.classList.remove("minimized");
    }
  });

  // ===== Auth gate =====
  // Don't render on auth/error pages or before the user has signed in.
  function onAuthRoute() {
    const p = location.pathname || "";
    return p.startsWith("/auth") || p.startsWith("/error") || p === "/signin";
  }

  // Save the original fetch reference so demo wrappers can't trick us.
  const _origFetchOrWindow = window.fetch.bind(window);
  let _cachedAuth = null;

  async function getAuthInfo() {
    if (_cachedAuth) return _cachedAuth;
    const token = localStorage.getItem("token");
    if (!token) return null;
    try {
      const r = await _origFetchOrWindow("/api/v1/auths/", {
        credentials: "include",
        headers: { Authorization: "Bearer " + token },
      });
      if (!r.ok) return null;
      _cachedAuth = await r.json();
      console.log("[AIUI tasks] auth:", _cachedAuth.email, "role:", _cachedAuth.role);
      return _cachedAuth;
    } catch (e) {
      console.warn("[AIUI tasks] auth check failed:", e);
      return null;
    }
  }

  async function isSignedIn() {
    return !!(await getAuthInfo());
  }

  async function isAdmin() {
    const a = await getAuthInfo();
    return !!(a && a.role === "admin");
  }

  // ===== Bootstrap =====
  let _initRunning = false;
  let _initDone = false;
  let _firstLoad = true; // only auto-show on the very first page load

  async function init() {
    if (_initRunning || _initDone) return;
    if (onAuthRoute()) {
      console.log("[AIUI tasks] auth route — skipping panel");
      return;
    }
    _initRunning = true;
    try {
      if (!(await isAdmin())) {
        console.log("[AIUI tasks] not admin — skipping panel");
        return;
      }
      await refreshAll();
      _initDone = true;

      // Only auto-popup on the very first page load. SPA navigations (clicking
      // around inside OpenWebUI) MUST NOT re-open the panel; the user can use
      // the integrations menu button or Settings toggle to re-open manually.
      if (!_firstLoad) {
        console.log("[AIUI tasks] SPA init — data refreshed, not auto-showing");
        return;
      }
      _firstLoad = false;

      if (!isAutoShowEnabled()) {
        console.log("[AIUI tasks] auto-show disabled by admin");
        return;
      }
      if (state.tasks.pending.length > 0) {
        panel.classList.remove("hidden");
      } else {
        console.log("[AIUI tasks] panel hidden — no pending tasks");
      }
    } finally {
      _initRunning = false;
    }
  }

  // ===== Inject single "Tasks" entry into the OpenWebUI user dropdown =====
  // Dropdown is created on demand. Use MutationObserver but dedupe per
  // menu instance via a unique flag on the parent menu element.
  const AUTOSHOW_KEY = "aiui-tasks-autoshow";
  function isAutoShowEnabled() {
    return localStorage.getItem(AUTOSHOW_KEY) !== "false"; // default ON
  }
  function setAutoShow(enabled) {
    localStorage.setItem(AUTOSHOW_KEY, enabled ? "true" : "false");
  }

  // Settings toggle removed — toggle now lives inline in the + menu row.
  const SETTINGS_ANCHORS = [];
  // eslint-disable-next-line no-unused-vars
  function injectSettingsToggle_DISABLED() {
    let pending = false;
    const observer = new MutationObserver(() => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(async () => {
        pending = false;
        if (!(await isAdmin())) return;
        if (document.querySelector("[data-aiui-tasks-toggle]")) return;

        // Find any element whose trimmed text is EXACTLY one of our anchors.
        // Then walk up to find the row (a container <= 300 chars text,
        // with at least one sibling row).
        let targetRow = null;
        let matchedAnchor = null;
        const all = document.querySelectorAll("*");
        for (const el of all) {
          const txt = (el.textContent || "").trim();
          if (!SETTINGS_ANCHORS.includes(txt)) continue;
          // Skip elements that contain many children (too big to be a label)
          if ((el.children && el.children.length > 2)) continue;

          let cur = el.parentElement;
          for (let i = 0; i < 4 && cur; i++) {
            const siblings = cur.parentElement ? cur.parentElement.children.length : 1;
            const bodyLen = (cur.textContent || "").length;
            // STRICT: row must be short (< 80 chars ~ label + "Default"/"On")
            // and have siblings (meaning it's a list item, not a section)
            if (siblings > 1 && bodyLen < 80) {
              targetRow = cur;
              matchedAnchor = txt;
              break;
            }
            cur = cur.parentElement;
          }
          if (targetRow) break;
        }
        if (!targetRow || !targetRow.parentElement) {
          console.log("[AIUI tasks] settings toggle: no anchor match");
          return;
        }
        console.log("[AIUI tasks] settings injecting after:", matchedAnchor);

        // Clone the native row so we inherit Tailwind/Svelte classes exactly.
        // This matches alignment, colors, spacing, toggle shape pixel-perfectly.
        const myRow = targetRow.cloneNode(true);
        myRow.dataset.aiuiTasksToggle = "1";

        // Rewrite the left-hand label text. Find the first text node that has
        // the anchor text and replace it with "Tasks (admin)".
        (function rewriteLabel(node) {
          for (const child of Array.from(node.childNodes)) {
            if (child.nodeType === 3) {
              const t = child.nodeValue.trim();
              if (t && t !== "Default" && t !== "On" && t !== "Off") {
                child.nodeValue = child.nodeValue.replace(t, "Tasks (admin)");
                return true;
              }
            } else if (child.nodeType === 1) {
              if (rewriteLabel(child)) return true;
            }
          }
          return false;
        })(myRow);

        // Clone the toggle button/input and rewire its handler. We disable
        // the original click by cloning the node (clones drop listeners).
        const toggle = myRow.querySelector("button, input[type='checkbox']");
        if (toggle) {
          const fresh = toggle.cloneNode(true);
          toggle.replaceWith(fresh);
          function paint() {
            const on = isAutoShowEnabled();
            if (fresh.tagName === "INPUT") fresh.checked = on;
            fresh.setAttribute("aria-checked", on ? "true" : "false");
            // If the native toggle uses a class to indicate "on", try common ones
            if (on) fresh.classList.add("!bg-emerald-500", "!bg-green-500");
            else fresh.classList.remove("!bg-emerald-500", "!bg-green-500");
          }
          paint();
          fresh.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            setAutoShow(!isAutoShowEnabled());
            paint();
            if (isAutoShowEnabled() && window.aiuiTaskPanel) {
              window.aiuiTaskPanel.open();
              window.aiuiTaskPanel.refresh();
            }
          });
        }

        targetRow.parentElement.insertBefore(myRow, targetRow.nextSibling);
        console.log("[AIUI tasks] settings toggle injected (cloned row)");
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  // injectSettingsToggle(); // disabled — toggle is now inline in the + menu

  // Inject a "Tasks" manual-open button into the + integrations menu
  // (the menu with Upload Files / Capture / Attach Webpage / Integrations).
  function injectIntegrationsMenuEntry() {
    let pending = false;
    const observer = new MutationObserver(() => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(async () => {
        pending = false;
        if (!(await isAdmin())) return;

        const all = document.querySelectorAll("*");
        for (const el of all) {
          const txt = (el.textContent || "").trim();
          if (txt !== "Upload Files") continue;
          let row = el;
          while (row && row.parentElement) {
            const t = row.tagName.toLowerCase();
            if (t === "button" || row.getAttribute("role") === "menuitem") break;
            row = row.parentElement;
          }
          if (!row) continue;
          const menu = row.parentElement;
          if (!menu || menu.dataset.aiuiTasksIntegInjected) continue;
          menu.dataset.aiuiTasksIntegInjected = "1";

          // Outer container — cloned shallow so it inherits classes/padding
          const entry = row.cloneNode(false);
          entry.dataset.aiuiTasksIntegEntry = "1";
          entry.removeAttribute("href");
          entry.innerHTML = "";
          entry.style.cssText += ";display:flex;align-items:center;justify-content:space-between;gap:8px;cursor:pointer;";

          // Left side: click-to-open label area
          const leftSide = document.createElement("span");
          leftSide.style.cssText = "display:flex;align-items:center;gap:8px;flex:1;";
          const icon = document.createElement("span");
          icon.textContent = "✓";
          icon.style.cssText = "color:#3b82f6;font-weight:700;";
          const label = document.createElement("span");
          label.textContent = "Tasks";
          leftSide.appendChild(icon);
          leftSide.appendChild(label);
          leftSide.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            // Close the + menu first, then open the task panel
            document.body.click();
            setTimeout(() => {
              if (window.aiuiTaskPanel) {
                window.aiuiTaskPanel.open();
                window.aiuiTaskPanel.refresh();
              }
            }, 80);
          });

          // Right side: inline auto-show toggle
          const toggle = document.createElement("button");
          toggle.type = "button";
          toggle.setAttribute("role", "switch");
          toggle.title = "Auto-popup the panel on login";
          toggle.style.cssText = "position:relative;width:32px;height:18px;border:0;border-radius:10px;cursor:pointer;transition:background 0.2s;padding:0;flex-shrink:0;";
          const knob = document.createElement("span");
          knob.style.cssText = "position:absolute;top:2px;width:14px;height:14px;background:#fff;border-radius:50%;transition:left 0.2s;";
          toggle.appendChild(knob);
          function paint() {
            const on = isAutoShowEnabled();
            toggle.setAttribute("aria-checked", on ? "true" : "false");
            toggle.style.background = on ? "#10b981" : "#4b5563";
            knob.style.left = on ? "16px" : "2px";
          }
          paint();
          toggle.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            setAutoShow(!isAutoShowEnabled());
            paint();
          });

          entry.appendChild(leftSide);
          entry.appendChild(toggle);
          menu.insertBefore(entry, row);
          console.log("[AIUI tasks] + menu entry injected (with toggle)");
          return;
        }
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  injectIntegrationsMenuEntry();

  // ===== SPA navigation watcher =====
  // OpenWebUI is a SvelteKit SPA — sign-in changes URL via pushState without
  // reloading. Watch for route changes and re-attempt init when leaving /auth.
  function watchSpaNavigation() {
    let lastPath = location.pathname;
    function onChange() {
      if (location.pathname === lastPath) return;
      lastPath = location.pathname;
      console.log("[AIUI tasks] route changed to", lastPath);
      // Reset init when entering or leaving /auth
      if (onAuthRoute()) {
        panel.classList.add("hidden");
      } else {
        _initDone = false;
        init();
      }
    }
    const _push = history.pushState;
    const _replace = history.replaceState;
    history.pushState = function () { _push.apply(this, arguments); onChange(); };
    history.replaceState = function () { _replace.apply(this, arguments); onChange(); };
    window.addEventListener("popstate", onChange);
    // Belt-and-braces: poll once a second in case some app uses location.assign
    setInterval(onChange, 1000);
  }
  watchSpaNavigation();

  window.aiuiTaskPanel = {
    open: () => panel.classList.remove("hidden"),
    refresh: refreshAll,
    state,
  };

  // Wait for OpenWebUI's chat UI to actually render before auto-showing.
  // Poll for the chat input textarea (or the app shell) with a hard cap.
  function waitForAppThenInit() {
    const start = Date.now();
    const tick = () => {
      const appReady =
        document.querySelector("textarea") ||
        document.querySelector('[class*="chat"]') ||
        document.querySelector('main');
      if (appReady || Date.now() - start > 8000) {
        // Additional 600ms grace period so Svelte settles its initial render
        setTimeout(init, 600);
      } else {
        setTimeout(tick, 200);
      }
    };
    tick();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", waitForAppThenInit);
  } else {
    waitForAppThenInit();
  }
})();
