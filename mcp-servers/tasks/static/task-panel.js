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
    .aiui-tp { position: fixed; bottom: 80px; right: 24px; width: 520px; max-height: 78vh;
      background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 14px;
      overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.04);
      display: flex; flex-direction: column; z-index: 9999;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: #fff; animation: aiui-tp-in 0.25s ease-out; }
    @keyframes aiui-tp-in { from { opacity: 0; transform: translateY(12px) scale(0.98); } to { opacity: 1; transform: translateY(0) scale(1); } }
    .aiui-tp.hidden { display: none; }
    .aiui-tp-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid #2a2a2a; background: #111; user-select: none; }
    .aiui-tp-head .title { display: flex; align-items: center; gap: 8px; }
    .aiui-tp-head .dot { width: 8px; height: 8px; border-radius: 50%; background: #ef4444; }
    .aiui-tp-head strong { font-size: 13px; }
    .aiui-tp-head .badge { background: #ef4444; color: #fff; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 10px; margin-left: 6px; display: none; }
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
    .aiui-tp-live:empty::before { content: "Waiting for the AIUI Agent to start…"; color: #666; font-style: italic; }
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
    /* ===== FAB launcher ===== */
    .aiui-tp-fab {
      /* position must establish a containing block for the absolute badge below. */
      position: fixed; bottom: 24px; right: 24px; z-index: 9998;
      width: 44px; height: 44px; border-radius: 50%;
      background: #1a1a1a; border: 1px solid #2a2a2a;
      color: #fff; cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      box-shadow: 0 6px 20px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.04);
      transition: transform 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .aiui-tp-fab:hover { background: #232323; transform: translateY(-1px); }
    .aiui-tp-fab:active { transform: translateY(0); }
    .aiui-tp-fab:focus-visible { outline: 2px solid #3b82f6; outline-offset: 2px; }
    .aiui-tp-fab.hidden { display: none; }
    .aiui-tp-fab svg { width: 20px; height: 20px; stroke: currentColor; fill: none; stroke-width: 2; }
    .aiui-tp-fab .aiui-tp-fab-badge {
      position: absolute; top: -4px; right: -4px;
      min-width: 18px; height: 18px; padding: 0 5px;
      border-radius: 9px; background: #ef4444; color: #fff;
      font-size: 11px; font-weight: 700; line-height: 18px;
      text-align: center; border: 2px solid #0b0b0b;
      box-sizing: content-box;
    }
    .aiui-tp-fab .aiui-tp-fab-badge.zero { display: none; }
    .aiui-tp-fab.pulse { animation: aiui-tp-fab-pulse 1.6s ease-out 2; }
    @keyframes aiui-tp-fab-pulse {
      0%   { box-shadow: 0 6px 20px rgba(0,0,0,0.55), 0 0 0 0 rgba(239,68,68,0.55); }
      70%  { box-shadow: 0 6px 20px rgba(0,0,0,0.55), 0 0 0 14px rgba(239,68,68,0); }
      100% { box-shadow: 0 6px 20px rgba(0,0,0,0.55), 0 0 0 0 rgba(239,68,68,0); }
    }
    @media (max-width: 640px) {
      .aiui-tp-fab { width: 48px; height: 48px; bottom: 16px; right: 16px; }
    }
    @media (max-width: 640px) {
      .aiui-tp {
        left: 0; right: 0; bottom: 0; top: auto;
        width: 100%; max-height: 85vh;
        border-radius: 16px 16px 0 0;
        border-left: 0; border-right: 0; border-bottom: 0;
      }
      .aiui-tp::before {
        content: "";
        display: block;
        width: 36px; height: 4px;
        background: #2a2a2a;
        border-radius: 2px;
        margin: 8px auto 0;
      }
      .aiui-tp-head { padding: 10px 16px 12px; }
      .aiui-tp-body { padding: 12px; }
    }
  `;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  // ===== State =====
  const state = { activeTab: "pending", tasks: { pending: [], progress: [], done: [] }, sse: {}, lastPendingCount: 0 };

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

  // ===== Build FAB launcher =====
  const fab = document.createElement("button");
  fab.type = "button";
  fab.className = "aiui-tp-fab hidden";
  fab.setAttribute("aria-label", "Open tasks panel");
  fab.title = "Tasks";
  fab.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 4h6a2 2 0 0 1 2 2v0H7v0a2 2 0 0 1 2-2z"/>
      <rect x="5" y="6" width="14" height="14" rx="2"/>
      <path d="M9 11l2 2 4-4"/>
    </svg>
    <span class="aiui-tp-fab-badge zero" data-role="fab-badge">0</span>
  `;
  document.body.appendChild(fab);

  fab.addEventListener("click", () => {
    setOpen(true);
  });

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
    const fabBadge = fab.querySelector('[data-role="fab-badge"]');
    if (fabBadge) {
      fabBadge.textContent = total;
      fabBadge.classList.toggle("zero", total === 0);
    }
    if (total > state.lastPendingCount && fab.classList.contains("hidden") === false) {
      fab.classList.remove("pulse");
      // Force reflow so the animation restarts when re-added
      void fab.offsetWidth;
      fab.classList.add("pulse");
    }
    state.lastPendingCount = total;

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
      let loopBtns = "";
      if (t.max_attempts > 1) {
          if (!t.plan || t.plan_status !== "approved") {
              loopBtns = `<button class="aiui-tp-btn-ai" data-task-action="clarify" data-task-id="${t.id}" style="background:#7c3aed;">💬 Clarify</button>
                          <button class="aiui-tp-btn-ai" data-task-action="plan" data-task-id="${t.id}" style="background:#4f46e5;">📋 Plan</button>`;
          }
      }
      actions = `${loopBtns}
                 <button class="aiui-tp-btn-ai" data-task-action="ai" data-task-id="${t.id}">⚡ AI</button>
                 <button class="aiui-tp-btn-manual" data-task-action="manual" data-task-id="${t.id}">✋ Manual</button>
                 <button class="aiui-tp-btn-manual" data-task-action="delete" data-task-id="${t.id}" title="Delete this task" style="flex:0 0 auto;padding:8px 10px;">🗑</button>`;
    } else {
      actions = `<button class="aiui-tp-btn-manual" data-task-action="manual" data-task-id="${t.id}">✋ Manual</button>
                 <button class="aiui-tp-btn-manual" data-task-action="delete" data-task-id="${t.id}" title="Delete this task" style="flex:0 0 auto;padding:8px 10px;">🗑</button>`;
    }
    const historyHtml = (t.conversation_history || []).length > 0
      ? `<div style="max-height:120px;overflow-y:auto;margin-bottom:6px;">${
          (t.conversation_history || []).map(h =>
              `<div style="font-size:11px;padding:4px 6px;margin:2px 0;border-radius:3px;background:${
                  h.role === 'ai' ? '#1a1208' : '#0a1a14'};color:${
                  h.role === 'ai' ? '#fcd34d' : '#86efac'};">
                  <strong>${h.role === 'ai' ? 'AI' : 'You'}:</strong> ${escapeHtml(h.content)}
              </div>`
          ).join("")
      }</div>`
      : "";
    const askInputUI = t.status === "awaiting_input"
      ? `<div style="background:#1a1208;border:1px solid #78350f;border-radius:4px;padding:8px;font-size:11px;color:#fcd34d;margin-bottom:8px;"><strong>AI says:</strong><br/>${escapeHtml(t.result || "")}</div>
         ${historyHtml}
         <textarea class="aiui-tp-textarea" data-textarea-id="${t.id}" placeholder="Reply to the AI…"></textarea>
         <div class="aiui-tp-actions"><button class="aiui-tp-btn-answer" data-task-action="answer-resume" data-task-id="${t.id}">↩ Reply</button></div>`
      : `<div class="aiui-tp-actions">${actions}</div>`;
    const planReviewUI = t.status === "awaiting_plan_review" && t.plan
      ? `<div style="background:#0a1a1a;border:1px solid #065f46;border-radius:4px;padding:8px;font-size:11px;color:#6ee7b7;margin-bottom:8px;max-height:200px;overflow-y:auto;white-space:pre-wrap;"><strong>AI Plan:</strong><br/>${escapeHtml(t.plan)}</div>
         <div class="aiui-tp-actions">
           <button class="aiui-tp-btn-ai" data-task-action="approve-plan" data-task-id="${t.id}">✓ Approve Plan</button>
           <button class="aiui-tp-btn-manual" data-task-action="reject-plan" data-task-id="${t.id}">✗ Reject</button>
         </div>`
      : "";
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
          ${t.max_attempts > 1 ? `<span class="aiui-tp-badge" style="background:#312e81;color:#c4b5fd;">🔄 Loop ${t.attempt_count}/${t.max_attempts}</span>` : ''}
          ${t.status === "awaiting_input" ? '<span class="aiui-tp-badge" style="background:#7c2d12;color:#fed7aa;">⚠️ NEEDS INPUT</span>' : ''}
        </div>
        <div class="aiui-tp-desc">${escapeHtml(t.description)}</div>
        <div class="aiui-tp-meta"><span class="aiui-tp-assignee">${escapeHtml(t.assignee_name)}</span></div>
        ${priorFailHint}
        ${askInputUI}${planReviewUI}
      </div>`;
  }

  function renderProgress(t) {
    return `
      <div class="aiui-tp-task running" data-task-card-id="${t.id}">
        <div class="aiui-tp-badges">
          <span class="aiui-tp-badge ${t.action_type}">${TYPE_LABELS[t.action_type] || TYPE_LABELS.UNKNOWN}</span>
          <span class="aiui-tp-badge priority">${PRI_LABELS[t.priority] || t.priority}</span>
          ${t.max_attempts > 1 ? `<span class="aiui-tp-badge" style="background:#312e81;color:#c4b5fd;">🔄 Loop ${t.attempt_count}/${t.max_attempts}</span>` : ''}
          ${t.status === "running" ? '<span class="aiui-tp-badge live">⚡ AI RUNNING</span>' : '<span class="aiui-tp-badge" style="background:#374151;color:#d1d5db;">✋ MANUAL</span>'}
        </div>
        <div class="aiui-tp-desc">${escapeHtml(t.description)}</div>
        <div class="aiui-tp-meta"><span class="aiui-tp-assignee">${escapeHtml(t.assignee_name)}</span></div>
        ${t.status === "running"
          ? `<div class="aiui-tp-live" data-live-id="${t.id}"><span style="color:#888;">◦ Spawning AIUI Agent (takes ~10s)…</span></div>
             <div class="aiui-tp-actions"><button class="aiui-tp-btn-stop" data-task-action="cancel" data-task-id="${t.id}">⏹ Stop</button></div>`
          : `<div class="aiui-tp-actions"><button class="aiui-tp-btn-ai" data-task-action="complete-prompt" data-task-id="${t.id}">✓ Mark Done</button></div>`}
      </div>`;
  }

  function renderDone(t) {
    const isFailed = t.status === "failed";
    const takeOverBtn = isFailed
      ? `<button class="aiui-tp-btn-manual" data-task-action="take-over" data-task-id="${t.id}">✋ Take over manually</button>`
      : "";
    const previewBtn = (t.action_type === "BUILD" && t.built_app_slug)
      ? `<a href="/tasks/static/preview.html?task=${t.id}" target="_blank"
           class="aiui-tp-btn-ai" style="text-decoration:none;text-align:center;display:inline-block;">
           🔍 Preview App</a>`
      : "";
    const resultBlock = t.result
      ? `<div style="background:${isFailed ? '#1a0a0a' : '#0a1a14'};border:1px solid ${isFailed ? '#7f1d1d' : '#065f46'};border-radius:6px;padding:8px 10px;font-size:12px;color:${isFailed ? '#fca5a5' : '#86efac'};margin-top:8px;line-height:1.5;white-space:pre-wrap;">${escapeHtml(t.result)}</div>`
      : "";
    const previewBtnBig = (t.action_type === "BUILD" && t.built_app_slug)
      ? `<a href="/tasks/static/preview.html?task=${t.id}" target="_blank"
           style="display:block;background:#3b82f6;color:#fff;border:0;padding:10px 14px;border-radius:6px;font-size:13px;font-weight:700;text-decoration:none;text-align:center;margin-top:10px;">
           🔍 Preview App →</a>`
      : "";
    return `
      <div class="aiui-tp-task aiui-tp-done" data-task-card="${t.id}">
        <div class="aiui-tp-done-header" data-task-action="toggle-done" data-task-id="${t.id}" style="cursor:pointer;display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
          <div style="flex:1;min-width:0;">
            <div class="aiui-tp-badges">
              <span class="aiui-tp-badge ${t.action_type}">${TYPE_LABELS[t.action_type] || TYPE_LABELS.UNKNOWN}</span>
              <span class="aiui-tp-badge priority">${PRI_LABELS[t.priority] || t.priority}</span>
              ${t.max_attempts > 1 ? `<span class="aiui-tp-badge" style="background:#312e81;color:#c4b5fd;">🔄 Loop ${t.attempt_count}/${t.max_attempts}</span>` : ''}
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
        ${previewBtnBig}
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
      else if (action === "clarify") {
        await api("POST", `/${id}/clarify`);
        await refreshAll();
        switchTab("progress");
        openStream(id);
      }
      else if (action === "plan") {
        await api("POST", `/${id}/plan`);
        await refreshAll();
        switchTab("progress");
        openStream(id);
      }
      else if (action === "approve-plan") {
        await api("POST", `/${id}/review-plan`, { approved: true });
        await refreshAll();
      }
      else if (action === "reject-plan") {
        showTextModal({
          title: "Reject Plan — Feedback (optional)",
          placeholder: "What should be different?",
          saveLabel: "Reject",
          allowEmpty: true,
          onSave: async (fb) => { await api("POST", `/${id}/review-plan`, { approved: false, feedback: fb }); await refreshAll(); },
        });
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

  // Convert one line of the agent's stream-json into a readable status
  function prettifyStreamLine(line) {
    line = line.trim();
    if (!line || !line.startsWith("{")) return null;
    let obj;
    try { obj = JSON.parse(line); } catch (_) { return null; }
    if (obj.type === "system" && obj.subtype === "init") {
      return `<span style="color:#60a5fa;">◦ AIUI Agent session started</span>`;
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
            ${(t.action_type === "BUILD" && t.built_app_slug) ? `<a href="/tasks/static/preview.html?task=${t.id}" target="_blank" style="background:#3b82f6;color:#fff;border:0;padding:6px 10px;border-radius:6px;font-size:11px;font-weight:600;text-decoration:none;">🔍 Preview App</a>` : ''}
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

      <label style="display:flex;align-items:center;gap:8px;margin-top:8px;font-size:12px;color:#aaa;">
          <input type="checkbox" data-loop-toggle style="accent-color:#4f46e5;"/>
          Loop mode (clarify → plan → TDD build → verify → retry)
      </label>

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
      const loopToggle = modal.querySelector("[data-loop-toggle]");
      const maxAttempts = loopToggle && loopToggle.checked ? 3 : 1;
      const body = {
        description: desc,
        action_type: modal.querySelector("[data-type]").value,
        priority: modal.querySelector("[data-prio]").value,
        assignee: modal.querySelector("[data-assignee]").value,
        max_attempts: maxAttempts,
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

  function setOpen(open) {
    if (open) {
      panel.classList.remove("hidden");
      fab.classList.add("hidden");
    } else {
      panel.classList.add("hidden");
      fab.classList.remove("hidden");
    }
  }

  // ===== Header controls =====
  panel.addEventListener("click", e => {
    const act = e.target.dataset && e.target.dataset.act;
    const tab = e.target.dataset && e.target.dataset.tab;
    if (act === "new-task") showCreateTaskModal();
    else if (act === "refresh") refreshAll();
    else if (act === "close") {
      setOpen(false);
    }
    else if (act === "history") showHistoryModal();
    else if (tab) switchTab(tab);
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

      // Show the FAB launcher; the panel itself stays collapsed until the
      // user clicks the FAB (or the + menu entry).
      fab.classList.remove("hidden");
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

          entry.appendChild(leftSide);
          menu.insertBefore(entry, row);
          console.log("[AIUI tasks] + menu entry injected (with toggle)");
          return;
        }
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  injectIntegrationsMenuEntry();

  // Inject a "Build Website" entry into the left sidebar, right below
  // the "Workspace" item. Clicking it opens /tasks/static/projects.html
  // which lists all of the user's AI-built apps.
  function injectSidebarBuildWebsiteEntry() {
    let pending = false;
    const observer = new MutationObserver(() => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(async () => {
        pending = false;
        if (!(await isAdmin())) return;
        if (document.querySelector("[data-aiui-build-website]")) return;

        // Find the <a>/<button> row whose label text is exactly "Workspace".
        let workspaceRow = null;
        const candidates = document.querySelectorAll("a, button, [role='link']");
        for (const el of candidates) {
          const txt = (el.textContent || "").trim();
          if (txt !== "Workspace") continue;
          workspaceRow = el;
          break;
        }
        if (!workspaceRow || !workspaceRow.parentElement) return;

        // The <a> found may sit inside a row wrapper (e.g. an <li> or
        // <div>) whose other siblings are sibling nav rows. If its parent
        // only contains workspaceRow, we need to clone at the parent level
        // so our new entry becomes a peer of other row wrappers — not a
        // second child inside Workspace's own row (which would split the
        // flex-row layout and squeeze both items into one line).
        let rowWrapper = workspaceRow;
        while (
          rowWrapper.parentElement &&
          rowWrapper.parentElement.children.length === 1 &&
          rowWrapper.parentElement.tagName.toLowerCase() !== "nav" &&
          rowWrapper.parentElement.tagName.toLowerCase() !== "aside"
        ) {
          rowWrapper = rowWrapper.parentElement;
        }

        // Clone deep so we inherit icon + Tailwind classes pixel-perfect.
        const entry = rowWrapper.cloneNode(true);
        entry.dataset.aiuiBuildWebsite = "1";
        // Force the clone to take its own row even if Tailwind classes
        // (flex-1, grow, basis-*) would otherwise let it share width.
        entry.style.width = "100%";
        entry.style.flexBasis = "100%";
        entry.style.minWidth = "0";
        // Strip href/data-sveltekit-preload on the clone and any nested
        // anchors so our click handler drives the navigation.
        // Also strip tooltip-triggering attributes (Open WebUI uses tippy
        // and the cloned row inherits a "mouseover" tooltip we don't want).
        function _stripTooltipAttrs(el) {
          ["title", "data-tippy-content", "data-tooltip", "aria-label",
           "aria-labelledby", "aria-describedby"].forEach((a) => el.removeAttribute(a));
        }
        entry.removeAttribute("href");
        _stripTooltipAttrs(entry);
        entry.querySelectorAll("*").forEach((el) => {
          _stripTooltipAttrs(el);
          if (el.tagName.toLowerCase() === "a") {
            el.removeAttribute("data-sveltekit-preload-data");
            el.removeAttribute("data-sveltekit-preload-code");
          }
        });
        // Add an explicit clean tooltip in its place.
        entry.setAttribute("title", "App Builder — create and manage AI-built apps");
        // Replace the cloned Workspace SVG with the AIUI "OI" wordmark.
        const cloneIcon = entry.querySelector("svg");
        if (cloneIcon) {
          const ns = "http://www.w3.org/2000/svg";
          const newIcon = document.createElementNS(ns, "svg");
          newIcon.setAttribute("width",  cloneIcon.getAttribute("width")  || "20");
          newIcon.setAttribute("height", cloneIcon.getAttribute("height") || "20");
          newIcon.setAttribute("viewBox", "0 0 32 32");
          if (cloneIcon.getAttribute("class")) newIcon.setAttribute("class", cloneIcon.getAttribute("class"));
          // "OI" wordmark — matches the AIUI brand on the App Builder page.
          const txt = document.createElementNS(ns, "text");
          txt.setAttribute("x", "16");
          txt.setAttribute("y", "22");
          txt.setAttribute("text-anchor", "middle");
          txt.setAttribute("font-family", "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif");
          txt.setAttribute("font-size", "17");
          txt.setAttribute("font-weight", "700");
          txt.setAttribute("fill", "currentColor");
          txt.setAttribute("letter-spacing", "-0.5");
          txt.textContent = "OI";
          newIcon.appendChild(txt);
          cloneIcon.replaceWith(newIcon);
        }
        // Replace the "Workspace" text label with "Build Website" wherever
        // it appears inside the cloned subtree.
        (function rewriteLabel(node) {
          for (const child of Array.from(node.childNodes)) {
            if (child.nodeType === 3) {
              const t = child.nodeValue;
              if (t && t.includes("Workspace")) {
                child.nodeValue = t.replace("Workspace", "App Builder");
              }
            } else if (child.nodeType === 1) {
              rewriteLabel(child);
            }
          }
        })(entry);
        // Capture-phase click so we beat Svelte's own handlers.
        entry.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          window.location.href = "/tasks/app-builder";
        }, true);
        // Insert right after the Workspace row wrapper.
        rowWrapper.parentElement.insertBefore(entry, rowWrapper.nextSibling);
        console.log("[AIUI tasks] sidebar 'Build Website' entry injected (wrapper=" + rowWrapper.tagName + ")");
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }
  injectSidebarBuildWebsiteEntry();

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
        fab.classList.add("hidden");
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
    open: () => setOpen(true),
    close: () => setOpen(false),
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
