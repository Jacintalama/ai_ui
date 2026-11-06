/**
 * AIUI sidebar entries and panes, injected into Open WebUI via Custom JS.
 *
 * Adds App Builder, Video Generation and Cron Jobs under Workspace, and
 * opens each one INSIDE the shell rather than navigating away, so the
 * sidebar and the open chat survive. Also rescues a direct URL to one of
 * those pages, which SvelteKit's router has never heard of.
 *
 * The filename is historical. Until 2026-11-06 this also drew a Pending
 * Tasks panel for meeting action items; that was removed and the rest of
 * the file, which never had anything to do with it, stayed.
 */
(function () {
  "use strict";

  if (window.__aiuiTaskPanelLoaded) return;
  window.__aiuiTaskPanelLoaded = true;

  // ===== Feature URLs =====
  //
  // The pane pages (App Builder, Cron Jobs, Video Generation, Channels) each
  // own a short URL. Open WebUI's client-side router has never heard of them,
  // so ARRIVING at one directly — pasted link, bookmark, reload — renders
  // SvelteKit's bare "404: Not Found" with no sidebar and no app. The server
  // is fine and answers 200 with the app shell; the router throws it away
  // after hydration. Clicking the sidebar was always fine, which is why this
  // hid for as long as it did: /channel had the same hole since it shipped.
  //
  // So the URL is rescued to "/", where the router is happy, and the code
  // below reopens the pane and puts the feature URL back. The PRIMARY rescue
  // is not in this file: an inline script in the <head> of
  // openwebui-overrides/index.html runs before SvelteKit, writes the same
  // pending record and rewrites the URL with history.replaceState. Nothing
  // reloads, and by the time this file runs the pathname is already "/", so
  // the bounce below does not fire.
  //
  // The bounce is only the FALLBACK, for an index.html without that head
  // script, because it signs people out. This file loads at the end of body,
  // after SvelteKit has started, and by then Open WebUI's root layout has
  // often sent GET /api/v1/auths/. location.replace() aborts that request,
  // Open WebUI reads the network error as a dead session and removes the
  // token, and the page that loads at "/" goes to /auth. With the bounce as
  // the only rescue, a reload at /ai-agents or /app-builder ended signed out
  // in 12 of 20 browser runs against production's files; a reload at "/" in
  // 0 of 10. Both path lists are kept equal to NAV_ENTRIES by
  // tests/test_feature_pages_embed.py.
  const AIUI_URL_PATHS = ["/app-builder", "/cronjobs", "/video-generation",
                          "/channel", "/ai-agents", "/ai-agents/office",
                          "/graph"];
  const AIUI_PENDING_KEY = "__aiuiOpenPath";

  // Set the moment we decide to bounce. location.replace() does NOT stop this
  // document: script keeps running and the sidebar observer keeps firing until
  // the new page commits. A scan on the doomed document would consume the
  // pending key and open a pane that is about to be discarded, leaving the real
  // load with nothing to reopen — a bare "/" instead of the feature. It is a
  // pure race, so it looked intermittent: it lost on the second load of a run,
  // where the cached script ran early enough to beat the navigation.
  let aiuiLeavingForRescue = false;

  (function rescueDirectFeatureUrl() {
    try {
      if (AIUI_URL_PATHS.indexOf(location.pathname) < 0) return;
      // Recorded before we leave, because the bounce discards the URL. A
      // signed-out visitor lands on /auth instead of "/", so this has to
      // survive the sign-in too — sessionStorage does, a variable would not.
      sessionStorage.setItem(AIUI_PENDING_KEY, JSON.stringify(
        { path: location.pathname, at: Date.now() }));
      aiuiLeavingForRescue = true;
      // replace(), not assign(): the 404 must not become a back-button stop.
      location.replace("/");
    } catch (e) { /* storage blocked -> land on the 404, same as before */ }
  })();

  // What the pane should reopen on this load, if anything. Read once; the key
  // is cleared only when the pane actually opens, so a detour through the
  // sign-in page does not lose it. Stale entries expire so a pane cannot
  // surprise someone by opening an hour later in the same tab.
  function aiuiPendingPath() {
    // This document is on its way out; whatever it reads here would be lost.
    if (aiuiLeavingForRescue) return null;
    try {
      const raw = sessionStorage.getItem(AIUI_PENDING_KEY);
      if (!raw) return null;
      const rec = JSON.parse(raw);
      if (!rec || !rec.path || Date.now() - rec.at > 5 * 60 * 1000) {
        sessionStorage.removeItem(AIUI_PENDING_KEY);
        return null;
      }
      return rec.path;
    } catch (e) { return null; }
  }

  // The action-item panel was removed on 2026-11-06.
  //
  // It tracked action items pulled out of meeting transcripts (RESEARCH,
  // ASK_USER, INTEGRATE, OUTREACH). There were 11 such rows in the whole
  // database, the newest from 13 May, several of them dead test rows.
  //
  // What is LEFT in this file is the other half, which shares nothing with
  // it but the filename: the sidebar entries for App Builder, Video
  // Generation and Cron Jobs, and the pane machinery that opens them
  // inside the shell. That is why the file was edited rather than deleted.
  //
  // The auth gate below stays because the sidebar entries use it: App
  // Builder is admin-only, and `onAuthRoute` keeps every injection off the
  // sign-in page.

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

  // Inject extra entries into the left sidebar, right below the "Workspace"
  // item. We clone the Workspace nav row (so the new entries inherit Open
  // WebUI's exact Tailwind classes + layout), relabel them, swap the icon
  // glyph, and drive navigation from a capture-phase click handler.
  //
  // Three entries are injected, in this order under Workspace:
  //   1. App Builder       -> /app-builder
  //   2. Video Generation  -> /video-generation
  //   3. Cron Jobs         -> /cronjobs
  //
  // All of them open INSIDE the shell (cfg.embed), like Channels and Graph.
  // They used to navigate away, which threw the whole Open WebUI app out and
  // rebooted it: the sidebar disappeared, the open chat was lost, and coming
  // back cost a second full boot. `href` is the page the pane loads;
  // `urlPath` is what the address bar shows, so the feature can still be
  // linked to and survives a reload.
  //
  // Each entry is guarded by its own unique data-attribute so SPA re-renders
  // never double-inject it. The App Builder entry keeps its original marker
  // (data-aiui-build-website), title, label, "</>" glyph and target so its
  // behavior is preserved exactly.
  function injectSidebarBuildWebsiteEntry() {
    // Config for each injected nav entry, in display order under "Workspace".
    const NAV_ENTRIES = [
      {
        attr: "data-aiui-build-website",
        // Visible to ALL signed-in users, not just admins. The build APIs
        // already authorize with current_user (owner-scoped), so any logged-in
        // user may create and manage their own apps.
        allUsers: true,
        label: "App Builder",
        title: "App Builder — create and manage AI-built apps",
        // The real page. /Aiuibuilder was an alias that 308'd here, so going
        // straight to it drops a redirect off the open path.
        href: "/tasks/app-builder",
        urlPath: "/app-builder",
        embed: true,
        // code-bracket "</>" glyph (unchanged from the original App Builder)
        setIcon: (svg) => {
          svg.setAttribute("viewBox", "0 0 24 24");
          svg.setAttribute("fill", "none");
          svg.setAttribute("stroke", "currentColor");
          svg.setAttribute("stroke-width", "2");
          svg.setAttribute("stroke-linecap", "round");
          svg.setAttribute("stroke-linejoin", "round");
          svg.innerHTML = '<polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline>';
        },
      },
      {
        attr: "data-aiui-video-gen",
        // Visible to ALL signed-in users, not just admins.
        allUsers: true,
        label: "Video Generation",
        title: "Video Generation: turn screenshots into a narrated video",
        // The page itself. /video-generator stays a working standalone URL —
        // the scheduler posts it into Discord — but the sidebar no longer
        // needs to leave the shell to reach it.
        href: "/tasks/static/video.html",
        urlPath: "/video-generation",
        embed: true,
        // film / clapperboard glyph (the 🎬 equivalent)
        setIcon: (svg) => {
          svg.setAttribute("viewBox", "0 0 24 24");
          svg.setAttribute("fill", "none");
          svg.setAttribute("stroke", "currentColor");
          svg.setAttribute("stroke-width", "2");
          svg.setAttribute("stroke-linecap", "round");
          svg.setAttribute("stroke-linejoin", "round");
          svg.innerHTML = '<rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line>';
        },
      },
      {
        attr: "data-aiui-cron-jobs",
        // Visible to ALL signed-in users. The schedules API is owner-scoped
        // (X-User-Email) and now caps regular users at 10 schedules with a
        // 15-minute floor, so an unbounded agent-run loop is not reachable.
        allUsers: true,
        label: "Cron Jobs",
        title: "Cron Jobs: schedule recurring AI tasks",
        // /cron-jobs stays a working standalone URL (the knowledge graph
        // links it); this is the same page, loaded into the pane.
        href: "/tasks/static/cron.html",
        urlPath: "/cronjobs",
        embed: true,
        // clock glyph (the ⏰ equivalent)
        setIcon: (svg) => {
          svg.setAttribute("viewBox", "0 0 24 24");
          svg.setAttribute("fill", "none");
          svg.setAttribute("stroke", "currentColor");
          svg.setAttribute("stroke-width", "2");
          svg.setAttribute("stroke-linecap", "round");
          svg.setAttribute("stroke-linejoin", "round");
          svg.innerHTML = '<circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline>';
        },
      },
      {
        attr: "data-aiui-channels",
        // Visible to ALL signed-in users. Everything behind it is scoped to the
        // caller: the page lists only their own links and can only unlink their
        // own. There is nothing here an admin sees that a user does not.
        allUsers: true,
        label: "Channels",
        title: "Channels: talk to IO from Telegram, a terminal and more",
        // What the iframe loads. Under the gateway router's own prefix,
        // which is what the api-gateway routes to the tasks service.
        href: "/tasks/gateway/channels",
        // What the ADDRESS BAR shows while this is open, so the page can be
        // linked to and survives a reload. Deliberately different from href
        // and deliberately short: this is the URL a person copies. See
        // openAiuiEmbed.
        urlPath: "/channel",
        // Open inside the OWUI shell: the left sidebar stays and only the
        // right-hand content area is swapped, rather than navigating away.
        embed: true,
        // speech bubble glyph
        setIcon: (svg) => {
          svg.setAttribute("viewBox", "0 0 24 24");
          svg.setAttribute("fill", "none");
          svg.setAttribute("stroke", "currentColor");
          svg.setAttribute("stroke-width", "2");
          svg.setAttribute("stroke-linecap", "round");
          svg.setAttribute("stroke-linejoin", "round");
          svg.innerHTML = '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>';
        },
      },
      {
        attr: "data-aiui-graph",
        // Visible to ALL signed-in users; the graph is owner-scoped per user.
        allUsers: true,
        label: "Graph",
        title: "Graph: your personal knowledge graph, built from your chats",
        href: "/tasks/graph",
        // The last embedded feature with no address. Opening it left the bar
        // describing whatever page you came from, so the graph could not be
        // linked to or reloaded. Caddy must not answer this path: a reload
        // has to reach the SPA so the pane can reopen.
        urlPath: "/graph",
        // Open inside the OWUI shell (keep the sidebar, swap only the
        // right-hand content area) instead of a full-window navigation.
        embed: true,
        // network / share glyph (connected nodes)
        setIcon: (svg) => {
          svg.setAttribute("viewBox", "0 0 24 24");
          svg.setAttribute("fill", "none");
          svg.setAttribute("stroke", "currentColor");
          svg.setAttribute("stroke-width", "2");
          svg.setAttribute("stroke-linecap", "round");
          svg.setAttribute("stroke-linejoin", "round");
          svg.innerHTML = '<circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line>';
        },
      },
      {
        attr: "data-aiui-agents",
        // Every signed-in user: an agent is owner-scoped, like the Graph.
        allUsers: true,
        label: "AI Agents",
        title: "AI Agents: build an assistant with your own instructions",
        href: "/tasks/agents",
        // What the ADDRESS BAR shows while this is open. Plural, matching the
        // sidebar label, and hyphenated like the page it names. Caddy must
        // NOT answer it: a reload has to reach the SPA so the pane can
        // reopen, which is what test_caddy_does_not_answer_the_feature_url_
        // itself pins.
        urlPath: "/ai-agents",
        embed: true,
        // robot glyph: a head with two eyes and an antenna
        setIcon: (svg) => {
          svg.setAttribute("viewBox", "0 0 24 24");
          svg.setAttribute("fill", "none");
          svg.setAttribute("stroke", "currentColor");
          svg.setAttribute("stroke-width", "2");
          svg.setAttribute("stroke-linecap", "round");
          svg.setAttribute("stroke-linejoin", "round");
          svg.innerHTML = '<rect x="4" y="8" width="16" height="12" rx="3"></rect>'
            + '<path d="M12 8V4"></path><circle cx="12" cy="3" r="1"></circle>'
            + '<circle cx="9" cy="14" r="1.2"></circle>'
            + '<circle cx="15" cy="14" r="1.2"></circle>'
            + '<path d="M2 13v3"></path><path d="M22 13v3"></path>';
        },
      },
      {
        attr: "data-aiui-office",
        // Every signed-in user, like AI Agents: an agent is owner-scoped and
        // so is everything this page says about one.
        allUsers: true,
        label: "Agent Office",
        title: "Agent Office: what each of your agents has been doing",
        href: "/tasks/office",
        // Nested under the agents path because that is what it is about, and
        // because the owner asked for it there. The rescue compares the whole
        // pathname, so a second segment costs it nothing.
        urlPath: "/ai-agents/office",
        embed: true,
        // an office floor: a building outline with lit windows
        setIcon: (svg) => {
          svg.setAttribute("viewBox", "0 0 24 24");
          svg.setAttribute("fill", "none");
          svg.setAttribute("stroke", "currentColor");
          svg.setAttribute("stroke-width", "2");
          svg.setAttribute("stroke-linecap", "round");
          svg.setAttribute("stroke-linejoin", "round");
          svg.innerHTML = '<path d="M3 21h18"></path>'
            + '<path d="M5 21V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v16"></path>'
            + '<path d="M16 9h3a2 2 0 0 1 2 2v10"></path>'
            + '<circle cx="9" cy="8" r="1"></circle>'
            + '<circle cx="12.5" cy="8" r="1"></circle>'
            + '<circle cx="9" cy="13" r="1"></circle>'
            + '<circle cx="12.5" cy="13" r="1"></circle>';
        },
      },
    ];

    // Build a sidebar nav entry by deep-cloning the Workspace row wrapper.
    // --- Embedded page overlay -------------------------------------------
    // Renders a page (e.g. the Graph) inside the OWUI shell: the left sidebar
    // stays put and only the right-hand content area is swapped, matching the
    // OWUI dark background. Used by nav entries flagged cfg.embed = true.

    // Measure the left sidebar so the overlay starts exactly at its right edge
    // (and re-measures when the sidebar collapses / the window resizes).
    //
    // Open WebUI 0.11 puts id="sidebar" on whichever sidebar is showing: the
    // 42px icon rail when collapsed, the 245px panel when open. They are two
    // different nodes and only one carries the id at a time (recorded frame
    // by frame on the live site, 2026-10-05). The walk below accepts only a
    // column 120px or wider, so it never found the rail and the pane fell
    // back to 260px, leaving an empty strip about 218px wide beside it.
    function aiuiSidebarRightEdge() {
      // Phones. Under 768px Open WebUI has no rail: its sidebar is a drawer
      // that slides over the page (measured live 2026-10-05: at 767px there
      // is no #sidebar and the hamburger, #sidebar-toggle-button, sits in a
      // 47px top bar; at 768px the 42px rail is back). Nothing holds the left
      // edge, so the pane takes the full width. It starts under that top bar
      // so the hamburger stays reachable: a phone has no Escape key, and
      // every link that would close the pane is underneath it.
      if (window.innerWidth < 768) {
        const btn = document.getElementById("sidebar-toggle-button");
        const bar = btn && (btn.closest("nav") || btn);
        const top = bar ? Math.max(0, Math.round(bar.getBoundingClientRect().bottom)) : 0;
        return { edge: 0, top: top, el: null };
      }
      const sb = document.getElementById("sidebar");
      if (sb) {
        const r = sb.getBoundingClientRect();
        if (r.left <= 8 && r.width >= 30 && r.width <= 520 && r.height > 200) {
          return { edge: Math.max(0, Math.round(r.right)), top: 0, el: sb };
        }
      }
      // Layouts without a usable #sidebar: walk up from one of our entries.
      const seed = document.querySelector("[data-aiui-graph]") ||
                   document.querySelector('a[href="/workspace"]');
      let best = null, el = seed;
      while (el && el !== document.body) {
        const r = el.getBoundingClientRect();
        // The sidebar is anchored to the left, tall, and a few hundred px wide.
        if (r.left <= 8 && r.width >= 120 && r.width <= 520 && r.height > 200) best = el;
        el = el.parentElement;
      }
      if (best) return { edge: Math.round(best.getBoundingClientRect().right), top: 0, el: best };
      return { edge: 260, top: 0, el: null };
    }

    // The pane, built once and kept. Reopening a feature must not rebuild it:
    // These have to open "with no loading", and a fresh iframe per
    // open means a blank pane and a full page boot every single time. So the
    // shell is HIDDEN rather than removed on close, and each page's frame is
    // cached here by href and merely unhidden when it comes back.
    const AIUI_FRAMES = Object.create(null);

    // Clicking any OTHER sidebar item (a chat, New Chat) returns to the app.
    // Clicking one of OUR entries must not, or switching from Cron Jobs to App
    // Builder would tear the pane down and reload the page being opened. This
    // used to name the Graph entry alone, which was right only while Graph was
    // the single embedded entry.
    const NAV_EMBED_SELECTOR =
      NAV_ENTRIES.map((c) => "[" + c.attr + "]").join(",");

    // Same-origin advisory: a cached page that is no longer on screen should
    // stop polling. App Builder refreshes every 8s, so without this a user who
    // opened it once would keep hitting the server from a hidden frame for as
    // long as the tab lived. Fails open — a page that ignores the message just
    // behaves exactly as it did before.
    function aiuiFrameVisible(frame, visible) {
      try {
        frame.contentWindow.postMessage(
          { aiuiFrameVisible: !!visible }, location.origin);
      } catch (e) { /* not loaded yet; the load handler re-sends */ }
    }

    function closeAiuiEmbed() {
      const wrap = document.querySelector("[data-aiui-embed]");
      if (wrap) {
        // Hidden, NOT removed. Removing it would throw away every cached frame
        // and put the loading back on the very next open.
        wrap.style.display = "none";
        wrap.removeAttribute("data-open");
        Object.keys(AIUI_FRAMES).forEach(
          (k) => aiuiFrameVisible(AIUI_FRAMES[k], false));
      }
      if (window.__aiuiEmbedCleanup) { window.__aiuiEmbedCleanup(); window.__aiuiEmbedCleanup = null; }
      // Put the address bar back where it was. Only when WE changed it, so a
      // close never rewrites a URL somebody else owns.
      if (window.__aiuiEmbedPrevUrl != null) {
        const back = window.__aiuiEmbedPrevUrl;
        window.__aiuiEmbedPrevUrl = null;
        try { history.pushState({}, "", back); } catch (e) {}
      }
    }

    // Build the pane once. Its listeners are registered once too, and every one
    // of them no-ops while the pane is closed.
    function aiuiEmbedShell() {
      let wrap = document.querySelector("[data-aiui-embed]");
      if (wrap) return wrap;

      const meas = aiuiSidebarRightEdge();
      wrap = document.createElement("div");
      wrap.setAttribute("data-aiui-embed", "");
      wrap.style.cssText =
        "position:fixed;top:" + meas.top + "px;right:0;bottom:0;left:" + meas.edge + "px;" +
        "z-index:35;background:#0b0b0b;overflow:hidden;display:none;";

      // No close button. It sat over the top right corner of every feature
      // page, which is where those pages put their own controls, and it was
      // covering them. The pane is a place you are, not a dialog you dismiss:
      // Escape leaves it, and so does clicking any link, including every
      // other entry in the sidebar. Both are wired below.
      document.body.appendChild(wrap);

      const isOpen = () => wrap.hasAttribute("data-open");

      // Keep the pane glued to the sidebar edge on resize / collapse.
      //
      // Collapsing does not resize one sidebar: Open WebUI swaps the rail and
      // the panel as whole nodes and moves the id between them. scanSidebar
      // catches the swap (it re-places an open pane on every DOM change), but
      // that can land while the panel is still sliding open (live: 124 of
      // 245px), so this observer follows whichever node is the sidebar now
      // and reports the rest of the slide. One fixed on the node measured at
      // first open went blind after the first toggle.
      let watched = null;
      const ro = "ResizeObserver" in window
        ? new ResizeObserver(() => reposition()) : null;
      const reposition = () => {
        if (!isOpen()) return;
        const m = aiuiSidebarRightEdge();
        wrap.style.left = m.edge + "px";
        wrap.style.top = m.top + "px";
        const sb = m.el || document.getElementById("sidebar");
        if (ro && sb !== watched) {
          if (watched) ro.unobserve(watched);
          if (sb) ro.observe(sb);
          watched = sb;
        }
      };
      window.addEventListener("resize", reposition);
      wrap.__aiuiReposition = reposition;

      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && isOpen()) closeAiuiEmbed();
      });

      document.addEventListener("click", (e) => {
        if (!isOpen()) return;
        const t = e.target;
        if (!t || wrap.contains(t)) return;
        // Our own nav entries SWAP the pane; they must not close it first.
        if (t.closest && t.closest(NAV_EMBED_SELECTOR)) return;
        // Close only when the click actually NAVIGATES.
        //
        // This used to close on any outside click, which meant collapsing the
        // sidebar while working in App Builder threw away a running preview
        // and whatever was typed in the build box, and dropped the user on a
        // blank chat. Reported with a screenshot on 2026-08-20 and reproduced
        // in a browser.
        //
        // A link leaves the page, so the pane should not cover where it went.
        // A button is chrome — sidebar collapse, theme toggle — and pressing
        // one is not a request to abandon the work surface. Escape and any real
        // navigation remain the deliberate ways out; there is no close
        // button any more.
        if (!t.closest || !t.closest('a[href]')) return;
        closeAiuiEmbed();
      }, true);

      return wrap;
    }

    function openAiuiEmbed(cfg) {
      const wrap = aiuiEmbedShell();
      // Same page already showing -> treat the click as a no-op toggle.
      if (wrap.getAttribute("data-open") === cfg.href) return;

      // Give the open page a URL. The pane lives inside the shell, so without
      // this the address bar keeps saying whatever it said before and the page
      // cannot be linked to at all. The previous URL is remembered only once,
      // so closing returns to the chat the user actually came from rather than
      // to whichever feature they happened to look at just before.
      if (cfg.urlPath && location.pathname !== cfg.urlPath) {
        if (window.__aiuiEmbedPrevUrl == null) {
          window.__aiuiEmbedPrevUrl = location.pathname + location.search;
        }
        try { history.pushState({ aiuiEmbed: cfg.attr }, "", cfg.urlPath); } catch (e) {}
      }

      wrap.setAttribute("data-open", cfg.href);
      wrap.style.display = "block";
      wrap.__aiuiReposition();

      Object.keys(AIUI_FRAMES).forEach((k) => {
        const shown = k === cfg.href;
        AIUI_FRAMES[k].style.display = shown ? "block" : "none";
        aiuiFrameVisible(AIUI_FRAMES[k], shown);
      });

      let frame = AIUI_FRAMES[cfg.href];
      if (!frame) {
        frame = document.createElement("iframe");
        // Cache-bust the FIRST load only. This exists to beat the PWA service
        // worker's stale HTML; doing it on every open is what made reopening
        // cost a full fetch and a blank pane.
        frame.src = cfg.href + (cfg.href.indexOf("?") < 0 ? "?v=" : "&v=") + Date.now();
        frame.setAttribute("title", cfg.title || cfg.label || "AIUI");
        frame.style.cssText =
          "width:100%;height:100%;border:0;display:block;background:#0b0b0b;";
        frame.addEventListener("load", () => {
          frame.__aiuiLoaded = true;
          aiuiFrameVisible(frame, wrap.getAttribute("data-open") === cfg.href);
        });
        AIUI_FRAMES[cfg.href] = frame;
        wrap.appendChild(frame);
      }

      // Poll briefly to catch the sidebar collapse/expand animation.
      const iv = setInterval(wrap.__aiuiReposition, 250);
      setTimeout(() => clearInterval(iv), 3000);
      window.__aiuiEmbedCleanup = () => clearInterval(iv);
    }

    // --- aiui:open-pane --------------------------------------------------
    // A page inside a pane asks the shell to open another pane, exactly as a
    // click on that sidebar entry would: the agents page opening the Graph,
    // the office opening AI Agents with a question. Without this they could
    // only send the whole window to a bare page outside Open WebUI.
    //
    // Accepted only from this origin AND straight from one of our own pane
    // frames. Open WebUI renders chat artifacts in frames, and App Builder
    // shows app previews in frames inside its pane (projects.html loads
    // /api/template-preview/ from this same origin); neither may drive the
    // shell. The path must be the urlPath of a known entry. Anything else is
    // ignored.
    //
    // An `ask` goes only to the AI Agents page, only once its frame has
    // loaded, and only PREFILLS its composer. Nothing is ever sent for the
    // person: a turn costs money and can run tools.
    //
    // The ask is handed over as the office wrote it, not trimmed: docked in
    // the agents page the office's "everyone answer: " keeps its trailing
    // space, so the person types straight after it, and this way it does
    // here too. Blank or over 2000 characters, it is dropped.
    //
    // With the ask may come the `agent` the office asked and its `name`, so
    // a robot's Chat pill opens that agent's own conversation here exactly
    // as it does in the docked office. Only an id shaped like one goes on
    // (the agents page still checks it is one of the viewer's own), and the
    // name only with it.
    const AIUI_ASK_MAX = 2000;
    const AIUI_AGENT_ID = /^[A-Za-z0-9_-]{1,100}$/;
    const AIUI_NAME_MAX = 40;

    function aiuiIsPaneFrame(source) {
      return !!source && Object.keys(AIUI_FRAMES).some(
        (k) => AIUI_FRAMES[k].contentWindow === source);
    }

    function aiuiHandAskToAgents(cfg, msg) {
      const frame = AIUI_FRAMES[cfg.href];
      if (!frame) return;
      const hand = () => {
        try {
          frame.contentWindow.postMessage(msg, location.origin);
        } catch (e) { /* frame gone: the question is dropped, never sent */ }
      };
      if (frame.__aiuiLoaded) hand();
      else frame.addEventListener("load", hand, { once: true });
    }

    window.addEventListener("message", async (ev) => {
      if (ev.origin !== location.origin) return;
      const d = ev.data;
      if (!d || d.type !== "aiui:open-pane" || typeof d.path !== "string") return;
      if (!aiuiIsPaneFrame(ev.source)) return;
      const cfg = NAV_ENTRIES.find((c) => c.embed && c.urlPath === d.path);
      if (!cfg) return;
      if (!cfg.allUsers && !(await isAdmin())) return;
      openAiuiEmbed(cfg);
      if (d.path === "/ai-agents" && typeof d.ask === "string" &&
          d.ask.trim() && d.ask.length <= AIUI_ASK_MAX) {
        const msg = { type: "aiui-agents-ask", ask: d.ask };
        if (typeof d.agent === "string" && AIUI_AGENT_ID.test(d.agent)) {
          msg.agent = d.agent;
          if (typeof d.name === "string" && d.name.length <= AIUI_NAME_MAX) {
            msg.name = d.name;
          }
        }
        aiuiHandAskToAgents(cfg, msg);
      }
    });

    // Mirrors the original App Builder cloning logic exactly, parameterized
    // by `cfg` (label / title / target href / icon).
    function buildEntry(rowWrapper, cfg) {
      // Clone deep so we inherit icon + Tailwind classes pixel-perfect.
      const entry = rowWrapper.cloneNode(true);
      entry.setAttribute(cfg.attr, "1");
      // Force the clone to take its own row even if Tailwind classes
      // (flex-1, grow, basis-*) would otherwise let it share width.
      entry.style.width = "100%";
      entry.style.flexBasis = "100%";
      entry.style.minWidth = "0";
      // Strip href/data-sveltekit-preload on the clone and any nested
      // anchors so our click handler drives the navigation. Also strip
      // tooltip-triggering attributes (Open WebUI uses tippy and the cloned
      // row inherits a "mouseover" tooltip we don't want).
      function _stripTooltipAttrs(el) {
        ["title", "data-tippy-content", "data-tooltip", "aria-label",
         "aria-labelledby", "aria-describedby"].forEach((a) => el.removeAttribute(a));
      }
      entry.removeAttribute("href");
      // The whole row is clickable, so it has to LOOK clickable. The browser
      // gives a hand cursor to <a href>, not to <a>, and every one of these
      // entries has its href stripped just below so ctrl-click cannot bypass
      // the pane — which quietly took the hand cursor away with it. cursor is
      // an inherited property, but it is set on the nested anchors too because
      // a Tailwind cursor-* class on the cloned row would otherwise win.
      entry.style.cursor = "pointer";
      _stripTooltipAttrs(entry);
      entry.querySelectorAll("*").forEach((el) => {
        el.style.cursor = "pointer";
        _stripTooltipAttrs(el);
        if (el.tagName.toLowerCase() === "a") {
          el.removeAttribute("data-sveltekit-preload-data");
          el.removeAttribute("data-sveltekit-preload-code");
          // The clone inherits the SOURCE row's href, so entries cloned from
          // the Notes anchor pointed every link at /notes. The capture-phase
          // click handler below hid this for a plain click, but hover,
          // middle-click and ctrl-click all followed the stale URL. Embed
          // entries have no page to open, so they lose the href entirely.
          if (cfg.embed) el.removeAttribute("href");
          else el.setAttribute("href", cfg.href);
        }
      });
      // Add an explicit clean tooltip in its place.
      entry.setAttribute("title", cfg.title);
      // Replace the cloned row's visible label.
      //
      // This used to match the single literal "Workspace". Which source row
      // gets cloned depends on which anchor exists — Workspace for admins,
      // Notes for everyone else — so for a non-admin nothing matched and all
      // four entries rendered as "Notes", four identical-looking links. The
      // static tests passed and the injector's own console log said
      // "injected"; only rendering it in a browser showed it.
      //
      // Rewriting the FIRST non-empty text node rather than a known word
      // keeps this working whatever the anchor row happens to say.
      const ANCHOR_LABELS = ["Workspace", "Notes", "Calendar"];
      const labelNodes = [];
      (function collectText(node) {
        for (const child of node.childNodes) {
          if (child.nodeType === 3) {
            if (child.nodeValue && child.nodeValue.trim()) labelNodes.push(child);
          } else if (child.nodeType === 1) {
            collectText(child);
          }
        }
      })(entry);
      if (labelNodes.length) {
        const first = labelNodes[0];
        const hit = ANCHOR_LABELS.find((l) => first.nodeValue.includes(l));
        first.nodeValue = hit
          ? first.nodeValue.replace(hit, cfg.label)
          : cfg.label;
      }
      // Swap the inherited Workspace icon for a distinct glyph so each entry
      // is visually distinguishable — including in the collapsed sidebar
      // where only icons render.
      const svg = entry.querySelector("svg");
      if (svg && typeof cfg.setIcon === "function") cfg.setIcon(svg);
      // Capture-phase click so we beat Svelte's own handlers.
      entry.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (cfg.embed) { openAiuiEmbed(cfg); }
        else { window.location.href = cfg.href; }
      }, true);
      return entry;
    }

    let pending = false;
    const scanSidebar = () => {
      // Don't decorate a document that is being replaced (see aiuiPendingPath).
      if (aiuiLeavingForRescue || pending) return;
      pending = true;
      requestAnimationFrame(async () => {
        pending = false;
        // An open pane follows the sidebar through Open WebUI's re-renders.
        // Collapsing and expanding swap the rail and the panel as whole
        // nodes, which no resize event reports, and this runs on every DOM
        // change.
        const shown = document.querySelector("[data-aiui-embed][data-open]");
        if (shown && shown.__aiuiReposition) shown.__aiuiReposition();
        // Don't early-return for non-admins: entries flagged allUsers must
        // still inject. Admin-only entries are gated individually below.
        // Fail-soft: if admin can't be determined isAdmin() is false, so
        // allUsers entries still show and admin-only entries stay hidden.
        const admin = await isAdmin();
        const visibleEntries = NAV_ENTRIES.filter((cfg) => cfg.allUsers || admin);
        if (!visibleEntries.length) return;

        // Landing on /channel, /app-builder, /cronjobs or /video-generation
        // directly — by reload, bookmark or a link somebody shared — opens the
        // page rather than a blank shell. The server hands the SPA back for any
        // unknown path, so without this the address bar names a feature and
        // nothing is on screen.
        //
        // The pane now survives a close (hidden, so its loaded pages are kept),
        // so "is one open" has to ask whether it is SHOWING. A bare
        // [data-aiui-embed] lookup answers yes forever after the first open.
        // Either we are already sitting on the feature URL (the pane pushed it
        // and the app never navigated away), or a rescue recorded one: the
        // head script in index.html earlier on this same load, or the bounce
        // on the load before it. The record reads the same either way.
        // NOT named `pending`: that is the re-entrancy guard in the enclosing
        // scope, and shadowing it here put it in the temporal dead zone, so
        // `pending = false` at the top of this callback threw and killed the
        // entire injector — no sidebar entries at all.
        const pendingPath = aiuiPendingPath();
        const wanted = visibleEntries.find(
          (cfg) => cfg.urlPath &&
                   (cfg.urlPath === location.pathname || cfg.urlPath === pendingPath));
        // Only open once the real app is on screen. A signed-out visitor who
        // pastes a feature URL is rescued to "/" and lands on the SIGN-IN page,
        // where opening a pane would both cover the login form and burn the
        // request, so after signing in they would land on a plain chat. The
        // sidebar is the honest signal that the app rendered and the user is
        // in; until then the key just waits.
        //
        // Phones render no sidebar links at all (390px: one 47px top bar), so
        // on a phone /ai-agents never opened. The app's own
        // <main id="main-content"> is the phone signal: it appears once a
        // signed-in user's app has rendered, and never on /auth, not even
        // while a signed-out "/" or a dead token is being sent there (all
        // checked live, 2026-10-05). The skip link that points at it,
        // a[href="#main-content"], IS on /auth: match the element, not the
        // link.
        const appIsUp = !onAuthRoute() && !!document.querySelector(
          'a[href="/"], a[href="/notes"], a[href="/calendar"], a[href="/workspace"], ' +
          'main#main-content');
        if (wanted && appIsUp &&
            !document.querySelector("[data-aiui-embed][data-open]")) {
          // Cleared only now, on the load that actually opens it, so a detour
          // through /auth keeps the request alive across the sign-in.
          try { sessionStorage.removeItem(AIUI_PENDING_KEY); } catch (e) {}
          openAiuiEmbed(wanted);
        }
        // Skip the expensive DOM work once every visible entry is present.
        if (visibleEntries.every((cfg) => document.querySelector("[" + cfg.attr + "]"))) return;

        // Anchor chain, first match wins.
        //
        // This used to look ONLY for a[href="/workspace"], which is why
        // regular users saw none of these entries: Open WebUI renders that
        // link only for admins or users holding at least one workspace
        // permission (upstream Sidebar.svelte -> isMenuItemVisible), and this
        // deployment sets all five workspace permissions to false. No anchor
        // meant nothing was injected at all, even for entries flagged
        // allUsers. Admins are unaffected — /workspace is still tried first,
        // so their entries stay exactly where they were.
        const ANCHOR_SELECTORS = [
          'a[href="/workspace"]',
          'a[href="/notes"]',
          'a[href="/calendar"]',
        ];
        let workspaceRow = null;
        for (const selector of ANCHOR_SELECTORS) {
          workspaceRow = document.querySelector(selector);
          if (workspaceRow) break;
        }
        if (!workspaceRow) {
          // Older Open WebUI versions, or a renamed route: fall back to
          // scanning for the row's label text. If neither label is present
          // we inject nothing — there is no anchor we could trust.
          const candidates = document.querySelectorAll("a, button, [role='link']");
          for (const el of candidates) {
            const txt = (el.textContent || "").trim();
            if (txt !== "Workspace" && txt !== "Notes") continue;
            workspaceRow = el;
            break;
          }
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

        // Insert each missing entry in order, each one right after the
        // previous (Workspace -> App Builder -> Video Generation -> Cron
        // Jobs). `anchor` advances to whichever configured entry currently
        // sits last, so partially-injected states still produce the right
        // order without duplicating anything.
        let anchor = rowWrapper;
        for (const cfg of NAV_ENTRIES) {
          const existing = document.querySelector("[" + cfg.attr + "]");
          if (existing) { anchor = existing; continue; }
          // Inject only entries this user may see (allUsers, or admin).
          if (!(cfg.allUsers || admin)) continue;
          const entry = buildEntry(rowWrapper, cfg);
          anchor.parentElement.insertBefore(entry, anchor.nextSibling);
          anchor = entry;
          console.log("[AIUI tasks] sidebar entry injected: " + cfg.label + " (wrapper=" + rowWrapper.tagName + ")");
        }
      });
    };
    new MutationObserver(scanSidebar).observe(
      document.body, { childList: true, subtree: true });
    // Run once up front. This was observer-only, so it depended entirely on the
    // page mutating AFTER this script attached; loader.js fetches this file
    // with a cache-busting query, so it can arrive after the render settles.
    //
    // Belt-and-braces, and honestly so: no test here fails when this line
    // is removed, because something always mutates the DOM soon enough.
    // It matters MORE since 2026-11-06: the thing that used to be relied
    // on to mutate the DOM was the task panel's own init, and that is
    // gone. Kept because it costs one guarded, idempotent call.
    scanSidebar();
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
      // Nothing to re-initialise here any more: the sidebar entries are
      // injected by their own MutationObserver, which keeps working across
      // SPA routes. This stays because the pane URL rescue above reads
      // location, and because a route change is still how we notice
      // somebody has left the sign-in page.
      if (onAuthRoute()) return;
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

  // The app-ready waiter that used to live here existed only to time the
  // panel's init() so it did not render before Svelte had settled. The
  // sidebar entries do not need it: each one is injected by its own
  // MutationObserver, which fires whenever Open WebUI renders the nav.
})();
