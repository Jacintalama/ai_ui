// AIUI Integrations - Custom UI injection for Open WebUI
(function() {
  'use strict';

  var GDRIVE_API = window.location.hostname === 'localhost' ? 'http://localhost:8005' : '/gdrive';
  var GMAIL_API = window.location.hostname === 'localhost' ? 'http://localhost:8006' : '/gmail';
  var CALENDAR_API = window.location.hostname === 'localhost' ? 'http://localhost:8007' : '/calendar';
  var CALENDAR_ICON_SMALL = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#4285f4" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>';
  var GMAIL_ICON_SMALL = '<svg width="16" height="16" viewBox="0 0 75 75" xmlns="http://www.w3.org/2000/svg"><path d="M6.25 56.25h12.5V36.46L0 22.5v27.5c0 3.45 2.8 6.25 6.25 6.25z" fill="#4285f4"/><path d="M56.25 56.25h12.5c3.45 0 6.25-2.8 6.25-6.25V22.5l-18.75 13.96" fill="#34a853"/><path d="M56.25 25v31.25h12.5c3.45 0 6.25-2.8 6.25-6.25V22.5l-11.72 8.72" fill="#34a853"/><path d="M18.75 56.25V36.46L37.5 50l18.75-13.54V25L37.5 38.54 18.75 25" fill="#ea4335"/><path d="M0 22.5l18.75 13.96V25L6.25 18.75C2.8 18.75 0 21.55 0 22.5" fill="#c5221f"/><path d="M56.25 25v11.46L75 22.5c0-.95-2.8-3.75-6.25-3.75L56.25 25" fill="#0d652d"/><path d="M18.75 25L6.25 18.75C2.8 18.75 0 21.55 0 22.5l18.75 13.96" fill="#c5221f"/><path d="M56.25 25l12.5-6.25C65.3 18.75 62.5 21.55 62.5 22.5" fill="#0d652d"/></svg>';
  var GMAIL_ICON_BIG = '<svg width="24" height="24" viewBox="0 0 75 75" xmlns="http://www.w3.org/2000/svg"><path d="M6.25 56.25h12.5V36.46L0 22.5v27.5c0 3.45 2.8 6.25 6.25 6.25z" fill="#4285f4"/><path d="M56.25 56.25h12.5c3.45 0 6.25-2.8 6.25-6.25V22.5l-18.75 13.96" fill="#34a853"/><path d="M56.25 25v31.25h12.5c3.45 0 6.25-2.8 6.25-6.25V22.5l-11.72 8.72" fill="#34a853"/><path d="M18.75 56.25V36.46L37.5 50l18.75-13.54V25L37.5 38.54 18.75 25" fill="#ea4335"/><path d="M0 22.5l18.75 13.96V25L6.25 18.75C2.8 18.75 0 21.55 0 22.5" fill="#c5221f"/><path d="M56.25 25v11.46L75 22.5c0-.95-2.8-3.75-6.25-3.75L56.25 25" fill="#0d652d"/><path d="M18.75 25L6.25 18.75C2.8 18.75 0 21.55 0 22.5l18.75 13.96" fill="#c5221f"/><path d="M56.25 25l12.5-6.25C65.3 18.75 62.5 21.55 62.5 22.5" fill="#0d652d"/></svg>';
  var GDRIVE_ICON_SMALL = '<svg width="16" height="16" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg"><path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/><path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-20.4 35.3c-.8 1.4-1.2 2.95-1.2 4.5h27.5z" fill="#00ac47"/><path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.5l5.4 9.35z" fill="#ea4335"/><path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/><path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc"/><path d="m73.4 26.5-10.1-17.5c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 23.8h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/></svg>';
  var GDRIVE_ICON_BIG = '<svg width="24" height="24" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg"><path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/><path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-20.4 35.3c-.8 1.4-1.2 2.95-1.2 4.5h27.5z" fill="#00ac47"/><path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.5l5.4 9.35z" fill="#ea4335"/><path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/><path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc"/><path d="m73.4 26.5-10.1-17.5c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 23.8h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/></svg>';

  // Chrome repaints any autofilled input white via :-webkit-autofill, and an
  // inline style cannot beat it. The inset shadow trick is the only way to
  // keep a dark field dark if the browser fills it anyway.
  (function injectAutofillGuard() {
    if (document.getElementById('aiui-autofill-guard')) return;
    var st = document.createElement('style');
    st.id = 'aiui-autofill-guard';
    st.textContent =
      '#aiui-conn-search:-webkit-autofill, .aiui-cred-input:-webkit-autofill,' +
      '#aiui-conn-search:-webkit-autofill:focus, .aiui-cred-input:-webkit-autofill:focus {' +
      '  -webkit-text-fill-color: #eee !important;' +
      '  -webkit-box-shadow: 0 0 0 1000px #0e0e0e inset !important;' +
      '  caret-color: #eee;' +
      '  transition: background-color 9999s ease-in-out 0s;' +
      '}';
    (document.head || document.documentElement).appendChild(st);
  })();

  // When you @mention an agent, Open WebUI shows a chip above the input with
  // the agent's name and a dismiss X. It lays those out with
  // `justify-between w-full`, so on a wide input the X ends up at the far
  // right edge, a screen away from the name it belongs to, reading like a
  // control for the whole box rather than for the mention.
  //
  // Pull them together. Scoped by :has() to the one row that actually holds a
  // model profile image, so no other justify-between row on the page moves.
  (function injectMentionChipFix() {
    if (document.getElementById('aiui-mention-chip-fix')) return;
    var st = document.createElement('style');
    st.id = 'aiui-mention-chip-fix';
    st.textContent =
      'div.flex.items-center.justify-between.w-full:has(> div > img[alt="model profile"]) {' +
      '  justify-content: flex-start !important;' +
      '  gap: 0.5rem;' +
      '}';
    (document.head || document.documentElement).appendChild(st);
  })();

  // ========== Helpers ==========

  // The signed-in account's address, cached once resolved.
  //
  // Never a user id. Every per-user table on the platform is keyed by the
  // address, and Open WebUI's JWT carries an id and no address, so this used
  // to answer with the id whenever it was asked before the address had been
  // fetched (which happened a second after load, and only then). A Google
  // consent started inside that second wrote the id into gmail_tokens,
  // gdrive_tokens and calendar_tokens, and every read, which asks by address,
  // found nothing. One account was connected and unreachable at the same
  // time, in all three services, with no error anywhere.
  // See mcp-servers/gmail/account_identity.py for the server's half.
  var _cachedEmail = null;

  // Loose on purpose: this only has to tell an address from a user id.
  function _isEmail(v) {
    return typeof v === 'string' && /^[^@\s]+@[^@\s]+$/.test(v.trim());
  }

  function getEffectiveEmail() {
    if (_cachedEmail) return _cachedEmail;

    // Open WebUI keeps the signed-in user object in localStorage, so the
    // address is usually available before /api/v1/auths/ answers. The JWT is
    // deliberately not consulted: it has an id and no address.
    for (var i = 0; i < localStorage.length; i++) {
      try {
        var val = localStorage.getItem(localStorage.key(i));
        if (!val) continue;
        var obj = JSON.parse(val);
        if (obj && _isEmail(obj.email)) {
          _cachedEmail = obj.email.trim();
          return _cachedEmail;
        }
        if (obj && obj.user && _isEmail(obj.user.email)) {
          _cachedEmail = obj.user.email.trim();
          return _cachedEmail;
        }
      } catch (e) {}
    }
    // Not cached: this is a guess, and the next call should get another
    // chance at the real thing.
    return 'default@local';
  }

  // Fetch actual email from Open WebUI API and update cache
  function resolveUserEmail() {
    var token = localStorage.getItem('token');
    if (!token) return;
    fetch('/api/v1/auths/', {
      headers: { 'Authorization': 'Bearer ' + token }
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data && _isEmail(data.email)) {
        _cachedEmail = data.email.trim();
        // Sync Gmail connection state with the server so stale localStorage
        // doesn't show UI for a connection the server no longer has.
        syncGmailStateFromServer();
      }
    }).catch(function() {});
  }

  function syncGmailStateFromServer() {
    var email = getEffectiveEmail();
    if (!email) return;
    fetch(GMAIL_API + '/auth/google/status?user_email=' + encodeURIComponent(email))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var key = 'aiui-gmail-connected:' + email;
        var emailKey = 'aiui-gmail-email:' + email;
        if (data && data.connected === true) {
          localStorage.setItem(key, 'true');
        } else {
          // Server says not connected: clear stale localStorage so Gmail UI
          // (Add-from-Gmail menu item, Gmail card in Integrations) stays hidden.
          if (localStorage.getItem(key) === 'true') {
            console.log('[AIUI] Clearing stale Gmail localStorage for', email);
            localStorage.removeItem(key);
            localStorage.removeItem(emailKey);
          }
        }
      })
      .catch(function() { /* network err: leave state alone */ });
  }

  // Resolve email on load
  resolveUserEmail();
  // Kept as a retry: the first call races page setup on a cold load.
  setTimeout(resolveUserEmail, 1000);

  // Tell the platform what timezone this browser is in, so the assistant knows
  // what "tomorrow morning" means for THIS user. Intl reports the IANA zone
  // name ("Asia/Manila"), which is what gets stored: a raw UTC offset is right
  // for only half the year in any zone with daylight saving, and it fails
  // silently.
  //
  // Once a day per user, not once a page view. A zone changes when someone
  // travels, which is not something to spend a request on every navigation.
  // The server refuses to overwrite a zone the user set by hand, so this is
  // safe to fire unattended.
  function reportTimezone() {
    var tz;
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { return; }
    if (!tz) return;
    var token = localStorage.getItem('token');
    if (!token) return;
    var stamp = 'aiui-tz-sent:' + getEffectiveEmail() + ':' + tz;
    var last = 0;
    try { last = parseInt(localStorage.getItem(stamp) || '0', 10); } catch (e) {}
    if (last && (Date.now() - last) < 86400000) return;
    fetch('/api/tasks/prefs/timezone', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json',
                 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ timezone: tz, manual: false })
    }).then(function (r) {
      if (r.ok) {
        try { localStorage.setItem(stamp, String(Date.now())); } catch (e) {}
      }
    }).catch(function () {});
  }
  // After resolveUserEmail, so the localStorage key is per real account.
  setTimeout(reportTimezone, 2500);

  // Per-user localStorage keys: each user has separate connection state
  function _userKey(base) {
    var email = getEffectiveEmail();
    return base + ':' + email;
  }

  function isConnected() {
    return localStorage.getItem(_userKey('aiui-gdrive-connected')) === 'true';
  }

  function isGmailConnected() {
    return localStorage.getItem(_userKey('aiui-gmail-connected')) === 'true';
  }

  function handleDisconnected() {
    // Clear local state for current user only
    localStorage.removeItem(_userKey('aiui-gdrive-connected'));
    localStorage.removeItem(_userKey('aiui-gdrive-email'));
    // Remove "Add from Google Drive" button from menu
    var gdriveBtn = document.getElementById('aiui-gdrive-menu-btn');
    if (gdriveBtn) gdriveBtn.remove();
    // Show reconnect modal
    showReconnectPrompt();
  }

  function showReconnectPrompt() {
    var overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10001;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';

    var modal = document.createElement('div');
    modal.style.cssText = 'background:#1e1e1e;border-radius:16px;padding:32px;max-width:420px;width:90%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,0.5);';

    modal.innerHTML = '<div style="margin-bottom:16px;">' + GDRIVE_ICON_BIG + '</div>' +
      '<h3 style="color:#fff;margin:0 0 8px 0;font-size:18px;">Google Drive Disconnected</h3>' +
      '<p style="color:#999;font-size:14px;margin:0 0 24px 0;">Your Google Drive session has expired or been revoked. Please reconnect to continue.</p>' +
      '<div style="display:flex;gap:10px;justify-content:center;">' +
        '<button id="aiui-reconnect-btn" style="background:#4a9eff;border:none;border-radius:8px;color:#fff;padding:10px 24px;font-size:14px;cursor:pointer;font-weight:600;">Reconnect</button>' +
        '<button id="aiui-dismiss-btn" style="background:transparent;border:1px solid #666;border-radius:8px;color:#ccc;padding:10px 24px;font-size:14px;cursor:pointer;">Dismiss</button>' +
      '</div>';

    overlay.appendChild(modal);

    modal.querySelector('#aiui-reconnect-btn').addEventListener('click', function() {
      window.open(GDRIVE_API + '/auth/google/link', 'aiui-oauth', 'width=600,height=700');
      overlay.remove();
    });

    modal.querySelector('#aiui-dismiss-btn').addEventListener('click', function() {
      overlay.remove();
    });

    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) overlay.remove();
    });

    document.body.appendChild(overlay);
  }

  function checkResponseForAuthError(data) {
    if (data && data.error && typeof data.error === 'string') {
      if (data.error.indexOf('not connected') > -1 || data.error.indexOf('Not connected') > -1) {
        handleDisconnected();
        return true;
      }
    }
    return false;
  }

  // Listen for OAuth callback
  window.addEventListener('message', function(event) {
    if (event.data && event.data.type === 'aiui-gdrive-connected') {
      localStorage.setItem(_userKey('aiui-gdrive-email'), event.data.email);
      localStorage.setItem(_userKey('aiui-gdrive-connected'), 'true');
      if (activeIntModal) updateCardConnected(activeIntModal, 'google-drive');
    }
    if (event.data && event.data.type === 'aiui-gmail-connected') {
      localStorage.setItem(_userKey('aiui-gmail-email'), event.data.email);
      localStorage.setItem(_userKey('aiui-gmail-connected'), 'true');
      if (activeIntModal) updateCardConnected(activeIntModal, 'gmail');
    }
  });

  // ========== Attached files tracking ==========

  var attachedDriveFiles = [];

  function addDriveAttachment(file) {
    // Always allow: create unique copy with unique ID for tracking
    var fileCopy = { id: file.id, name: file.name, type: file.type, uid: file.id + '_' + Date.now() };
    attachedDriveFiles.push(fileCopy);
    renderAttachmentCards();
    uploadDriveFileToWebUI(fileCopy);
  }

  function removeDriveAttachment(fileUid) {
    attachedDriveFiles = attachedDriveFiles.filter(function(f) { return f.uid !== fileUid; });
    renderAttachmentCards();
    // Remove the context from textarea
    var textarea = document.querySelector('textarea');
    if (textarea) {
      textarea.value = textarea.value.replace(/\[Attached from Google Drive:.*?\]\n/g, '');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  function renderAttachmentCards() {
    var existing = document.getElementById('aiui-drive-cards');
    if (existing) existing.remove();

    if (attachedDriveFiles.length === 0) return;

    // Find the chat input form area - look for the textarea's parent form/container
    var textarea = document.querySelector('textarea');
    if (!textarea) return;

    // Walk up to find a good container above the textarea
    var formContainer = textarea;
    for (var p = 0; p < 8; p++) {
      if (!formContainer.parentElement) break;
      formContainer = formContainer.parentElement;
      // Stop at a container that looks like the chat input wrapper
      if (formContainer.querySelector && formContainer.querySelector('textarea') && formContainer.offsetHeight > 80) break;
    }

    var cardsContainer = document.createElement('div');
    cardsContainer.id = 'aiui-drive-cards';
    cardsContainer.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;padding:8px 16px 4px 16px;';

    attachedDriveFiles.forEach(function(file) {
      var typeLabel = (file.type || 'file').toUpperCase();
      var typeColor = '#4285f4';
      if (file.type === 'spreadsheet') typeColor = '#0f9d58';
      else if (file.type === 'presentation') typeColor = '#f4b400';
      else if (file.type === 'pdf') typeColor = '#ea4335';

      var card = document.createElement('div');
      card.style.cssText = 'position:relative;background:#2a2a2a;border:1px solid #444;border-radius:12px;padding:12px 14px;min-width:140px;max-width:200px;cursor:default;';

      var loadId = file.uid ? file.uid.replace(/[^a-zA-Z0-9]/g, '').substring(0, 16) : file.id.substring(0, 8);

      card.innerHTML = '<button class="aiui-remove-card" style="position:absolute;top:4px;right:6px;background:#444;border:none;color:#ccc;width:20px;height:20px;border-radius:50%;cursor:pointer;font-size:12px;line-height:1;display:flex;align-items:center;justify-content:center;">&times;</button>' +
        '<div style="color:#e0e0e0;font-size:13px;font-weight:500;margin-bottom:8px;padding-right:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + file.name + '">' + file.name + '</div>' +
        '<div style="display:flex;align-items:center;gap:4px;">' +
          '<span style="background:' + typeColor + ';color:#fff;font-size:10px;font-weight:700;padding:2px 6px;border-radius:3px;">' + typeLabel + '</span>' +
          '<span id="aiui-loading-' + loadId + '" style="color:#888;font-size:11px;margin-left:4px;">Loading...</span>' +
        '</div>';

      card.querySelector('.aiui-remove-card').addEventListener('click', function() {
        removeDriveAttachment(file.uid || file.id);
      });

      cardsContainer.appendChild(card);
    });

    // Insert the cards above the textarea's container
    formContainer.insertBefore(cardsContainer, formContainer.firstChild);
  }

  function getWebUIToken() {
    // Open WebUI stores JWT token in localStorage
    for (var i = 0; i < localStorage.length; i++) {
      var key = localStorage.key(i);
      var val = localStorage.getItem(key);
      if (!val) continue;
      // Look for JWT tokens
      try {
        if (val.split('.').length === 3) {
          var payload = JSON.parse(atob(val.split('.')[1]));
          if (payload.id && payload.exp) return val;
        }
      } catch (e) {}
    }
    return null;
  }

  function uploadDriveFileToWebUI(file) {
    var email = getEffectiveEmail();
    var loadId = file.uid ? file.uid.replace(/[^a-zA-Z0-9]/g, '').substring(0, 16) : file.id.substring(0, 8);
    var loadingEl = document.getElementById('aiui-loading-' + loadId);
    var isBinary = false; // Only support Google Docs/Sheets/Slides (text export)

    if (isBinary) {
      // For PDFs: server-side download from Google Drive + upload to Open WebUI
      if (loadingEl) loadingEl.textContent = 'Processing...';
      var token = getWebUIToken();

      fetch(GDRIVE_API + '/gdrive_upload_to_webui', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-Email': email },
        body: JSON.stringify({
          file_id: file.id,
          webui_url: window.location.origin,
          webui_token: token || ''
        })
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (checkResponseForAuthError(data)) return;
        if (data.error) {
          console.error('[AIUI] Server upload error:', data.error);
          if (loadingEl) { loadingEl.textContent = 'Error'; loadingEl.style.color = '#f44'; }
          return;
        }
        if (data.success) {
          file.webui_file_id = data.file_id;
          var sizeMB = (data.size / 1024 / 1024).toFixed(1);
          if (loadingEl) { loadingEl.textContent = 'Attached (' + sizeMB + ' MB)'; loadingEl.style.color = '#00ac47'; }
          // Trigger native attachment to show in chat
          file.content = 'PDF file: ' + file.name;
          file._blob = new Blob(['PDF: ' + file.name], { type: 'application/pdf' });
          triggerNativeAttachment({ filename: data.filename, id: data.file_id }, file);
        }
      })
      .catch(function(err) {
        console.error('[AIUI] Server upload error:', err);
        if (loadingEl) { loadingEl.textContent = 'Error'; loadingEl.style.color = '#f44'; }
      });
    } else {
      // For text files (Docs, Sheets, Slides): read content then upload
      if (loadingEl) loadingEl.textContent = 'Reading...';

      fetch(GDRIVE_API + '/gdrive_read_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-Email': email },
        body: JSON.stringify({ file_id: file.id })
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.error) {
          if (loadingEl) { loadingEl.textContent = 'Error'; loadingEl.style.color = '#f44'; }
          return;
        }
        var content = data.content || '';
        var fileName = data.file_name || file.name;
        file.content = content;

        // Handle empty content
        if (!content || content.trim().length === 0) {
          if (loadingEl) { loadingEl.textContent = 'Empty file'; loadingEl.style.color = '#f4b400'; }
          return;
        }

        if (loadingEl) loadingEl.textContent = 'Uploading...';

        var mimeType = 'text/plain';
        var ext = fileName.split('.').pop().toLowerCase();
        if (ext === 'csv') mimeType = 'text/csv';
        else if (ext === 'md') mimeType = 'text/markdown';
        else if (ext === 'html') mimeType = 'text/html';

        var uniqueName = fileName.replace(/(\.[^.]+)$/, '_' + Date.now() + '$1');
        var blob = new Blob([content], { type: mimeType });
        var formData = new FormData();
        formData.append('file', blob, uniqueName);

        var token = getWebUIToken();
        return fetch('/api/v1/files/', {
          method: 'POST',
          headers: token ? { 'Authorization': 'Bearer ' + token } : {},
          body: formData
        });
      })
      .then(function(r) { if (r) return r.json(); })
      .then(function(uploadResult) {
        if (!uploadResult || !uploadResult.id) {
          if (loadingEl) { loadingEl.textContent = 'Failed'; loadingEl.style.color = '#f44'; }
          return;
        }
        file.webui_file_id = uploadResult.id;
        if (loadingEl) { loadingEl.textContent = 'Attached'; loadingEl.style.color = '#00ac47'; }
        triggerNativeAttachment(uploadResult, file);
      })
      .catch(function(err) {
        console.error('[AIUI] Text upload error:', err);
        if (loadingEl) { loadingEl.textContent = 'Error'; loadingEl.style.color = '#f44'; }
      });
    }
  }

  function triggerNativeAttachment(uploadResult, file) {
    var fileName = uploadResult.filename || file.name;
    var content = file.content || 'Drive file: ' + file.name;
    var mimeType = 'text/plain';
    if (file.type === 'pdf') mimeType = 'application/pdf';
    else if (file.type === 'spreadsheet') mimeType = 'text/csv';

    // Use stored blob if available (for binary files), otherwise create from content
    var blob;
    if (file._blob) {
      blob = file._blob;
    } else {
      blob = new Blob([content], { type: mimeType });
    }
    var syntheticFile = new File([blob], fileName, { type: mimeType });

    // Try drag-drop first (works for multiple files)
    var textarea = document.querySelector('textarea');
    var dropTarget = textarea ? (textarea.closest('form') || textarea.closest('[class*="chat"]') || textarea.parentElement) : document.body;

    try {
      var dt = new DataTransfer();
      dt.items.add(syntheticFile);

      // Simulate full drag sequence
      var dragEnter = new DragEvent('dragenter', { bubbles: true, dataTransfer: dt });
      var dragOver = new DragEvent('dragover', { bubbles: true, dataTransfer: dt });
      var drop = new DragEvent('drop', { bubbles: true, dataTransfer: dt });

      dropTarget.dispatchEvent(dragEnter);
      dropTarget.dispatchEvent(dragOver);
      dropTarget.dispatchEvent(drop);
      console.log('[AIUI] Drop event dispatched for:', fileName);
    } catch (e) {
      console.log('[AIUI] Drop failed, trying file input');
    }

    // Also try file input as backup
    var fileInputs = document.querySelectorAll('input[type="file"]');
    for (var i = 0; i < fileInputs.length; i++) {
      try {
        var input = fileInputs[i];
        var dt2 = new DataTransfer();
        dt2.items.add(syntheticFile);
        input.files = dt2.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
        console.log('[AIUI] File input triggered for:', fileName);
        break;
      } catch (e2) {}
    }
  }

  // ========== File Picker ==========

  function createFilePicker() {
    var overlay = document.createElement('div');
    overlay.id = 'aiui-filepicker-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';

    var picker = document.createElement('div');
    picker.style.cssText = 'background:#1e1e1e;border-radius:16px;padding:0;max-width:500px;width:90%;max-height:70vh;box-shadow:0 25px 50px rgba(0,0,0,0.5);display:flex;flex-direction:column;overflow:hidden;';

    // Header
    picker.innerHTML = '<div style="padding:16px 20px;border-bottom:1px solid #333;display:flex;align-items:center;gap:10px;">' +
      GDRIVE_ICON_SMALL +
      '<span style="color:#fff;font-weight:600;font-size:15px;flex:1;">Add from Google Drive</span>' +
      '<button id="aiui-picker-close" style="background:none;border:none;color:#888;font-size:20px;cursor:pointer;line-height:1;">&times;</button>' +
      '</div>' +
      '<div style="padding:12px 16px;border-bottom:1px solid #333;">' +
        '<input id="aiui-picker-search" type="text" placeholder="Search documents..." style="width:100%;background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:8px 12px;color:#fff;font-size:14px;outline:none;box-sizing:border-box;" />' +
      '</div>' +
      '<div id="aiui-picker-files" style="flex:1;overflow-y:auto;padding:8px;min-height:200px;">' +
        '<div style="text-align:center;padding:40px;color:#666;">Loading files...</div>' +
      '</div>';

    overlay.appendChild(picker);

    // Close
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
    picker.querySelector('#aiui-picker-close').addEventListener('click', function() { overlay.remove(); });
    document.addEventListener('keydown', function handler(e) {
      if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', handler); }
    });

    // Search
    var searchTimeout = null;
    var searchInput = picker.querySelector('#aiui-picker-search');
    searchInput.addEventListener('input', function() {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(function() {
        var query = searchInput.value.trim();
        if (query) {
          searchDriveFiles(query, picker);
        } else {
          loadDriveFiles(picker);
        }
      }, 400);
    });

    // Load initial files
    loadDriveFiles(picker);

    return overlay;
  }

  function loadDriveFiles(picker) {
    var email = getEffectiveEmail();
    var filesList = picker.querySelector('#aiui-picker-files');
    filesList.innerHTML = '<div style="text-align:center;padding:40px;color:#666;">Loading files...</div>';

    fetch(GDRIVE_API + '/gdrive_list_files', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-User-Email': email },
      body: JSON.stringify({ page_size: 20 })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (checkResponseForAuthError(data)) {
        var overlay = picker.closest('#aiui-filepicker-overlay');
        if (overlay) overlay.remove();
        return;
      }
      if (data.error) {
        filesList.innerHTML = '<div style="text-align:center;padding:40px;color:#f44;">' + data.error.substring(0, 200) + '</div>';
        return;
      }
      renderFileList(data.files || [], filesList, picker);
    })
    .catch(function(err) {
      filesList.innerHTML = '<div style="text-align:center;padding:40px;color:#f44;">Failed to load files</div>';
    });
  }

  function searchDriveFiles(query, picker) {
    var email = getEffectiveEmail();
    var filesList = picker.querySelector('#aiui-picker-files');
    filesList.innerHTML = '<div style="text-align:center;padding:40px;color:#666;">Searching...</div>';

    fetch(GDRIVE_API + '/gdrive_search_files', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-User-Email': email },
      body: JSON.stringify({ query: query, page_size: 20 })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (checkResponseForAuthError(data)) {
        var overlay = picker.closest('#aiui-filepicker-overlay');
        if (overlay) overlay.remove();
        return;
      }
      if (data.error) {
        filesList.innerHTML = '<div style="text-align:center;padding:40px;color:#f44;">' + data.error.substring(0, 200) + '</div>';
        return;
      }
      renderFileList(data.files || [], filesList, picker);
    })
    .catch(function() {
      filesList.innerHTML = '<div style="text-align:center;padding:40px;color:#f44;">Search failed</div>';
    });
  }

  var FILE_ICONS = {
    document: '<svg width="18" height="18" viewBox="0 0 24 24" fill="#4285f4"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm-1 7V3.5L18.5 9H13zM7 13h10v2H7v-2zm0 4h7v2H7v-2z"/></svg>',
    spreadsheet: '<svg width="18" height="18" viewBox="0 0 24 24" fill="#0f9d58"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm-1 7V3.5L18.5 9H13zM7 13h3v2H7v-2zm0 4h3v2H7v-2zm7 2h-3v-2h3v2zm0-4h-3v-2h3v2z"/></svg>',
    presentation: '<svg width="18" height="18" viewBox="0 0 24 24" fill="#f4b400"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm-1 7V3.5L18.5 9H13zM8 15l2.5-3 1.5 2 2-2.5L17 15H8z"/></svg>',
    pdf: '<svg width="18" height="18" viewBox="0 0 24 24" fill="#ea4335"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm-1 7V3.5L18.5 9H13z"/></svg>',
    folder: '<svg width="18" height="18" viewBox="0 0 24 24" fill="#5f6368"><path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>',
    default: '<svg width="18" height="18" viewBox="0 0 24 24" fill="#5f6368"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm-1 7V3.5L18.5 9H13z"/></svg>'
  };

  function getFileIcon(type) {
    return FILE_ICONS[type] || FILE_ICONS['default'];
  }

  function renderFileList(files, container, picker) {
    // Only show Google Docs, Sheets, Slides (they export as text reliably)
    var supportedTypes = ['document', 'presentation', 'folder'];
    var filtered = files.filter(function(f) {
      return supportedTypes.indexOf(f.type) > -1;
    });

    if (filtered.length === 0) {
      container.innerHTML = '<div style="text-align:center;padding:40px;color:#666;">No supported files found<br><span style="font-size:12px;color:#555;">Only Google Docs, Sheets, and Slides are supported</span></div>';
      return;
    }

    container.innerHTML = '';
    filtered.forEach(function(file) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;cursor:pointer;transition:background 0.15s;';

      row.innerHTML = '<div style="flex-shrink:0;">' + getFileIcon(file.type) + '</div>' +
        '<div style="flex:1;min-width:0;">' +
          '<div style="color:#e0e0e0;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + file.name + '</div>' +
          '<div style="color:#888;font-size:12px;">' + file.type + ' &middot; ' + (file.modified || '') + '</div>' +
        '</div>';

      row.addEventListener('mouseenter', function() { row.style.background = '#333'; });
      row.addEventListener('mouseleave', function() { row.style.background = 'transparent'; });

      row.addEventListener('click', function() {
        // Add file as attachment
        addDriveAttachment({ id: file.id, name: file.name, type: file.type });
        // Close picker
        var overlay = picker.closest('#aiui-filepicker-overlay');
        if (overlay) overlay.remove();
      });

      container.appendChild(row);
    });
  }

  // ========== Integrations Modal ==========

  var activeIntModal = null;

  // The feature pages (AI Agents, Cron, Video) run in iframes in this shell.
  // The Agents page decides which tools an agent may use, so it has to know
  // the moment one is connected here, and it must not have to reload to find
  // out: reloading would throw away a half written agent.
  function notifyConnectionsChanged() {
    var frames = document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {
      try {
        frames[i].contentWindow.postMessage(
          { type: 'aiui:connections-changed' }, '*');
      } catch (e) { /* cross origin frame, not one of ours */ }
    }
  }

  // Opening the real dialog from inside a feature page, so there is one
  // Connections modal on this platform rather than a second one that only
  // looks similar.
  window.aiuiOpenConnections = function () {
    document.body.appendChild(createIntegrationsModal());
  };

  window.addEventListener('message', function (ev) {
    var d = ev && ev.data;
    if (d && d.type === 'aiui:open-connections') {
      window.aiuiOpenConnections();
    }
  });

  function updateCardConnected(modal, integrationId) {
    var status = modal.querySelector('#aiui-status-' + integrationId);
    var connectBtn = modal.querySelector('#aiui-connect-' + integrationId);
    var disconnectBtn = modal.querySelector('#aiui-disconnect-' + integrationId);
    var card = connectBtn ? connectBtn.closest('[data-integration]') : null;
    if (status) status.style.display = 'inline';
    if (connectBtn) connectBtn.style.display = 'none';
    if (disconnectBtn) disconnectBtn.style.display = 'inline-block';
    if (card) card.style.borderColor = '#00ac47';
    notifyConnectionsChanged();
  }

  function updateCardDisconnected(modal, integrationId) {
    var status = modal.querySelector('#aiui-status-' + integrationId);
    var connectBtn = modal.querySelector('#aiui-connect-' + integrationId);
    var disconnectBtn = modal.querySelector('#aiui-disconnect-' + integrationId);
    var card = connectBtn ? connectBtn.closest('[data-integration]') : null;
    if (status) status.style.display = 'none';
    if (connectBtn) connectBtn.style.display = 'inline-block';
    if (disconnectBtn) disconnectBtn.style.display = 'none';
    if (card) card.style.borderColor = '#333';
    notifyConnectionsChanged();
  }

  function createIntegrationsModal() {
    var email = getEffectiveEmail();
    var overlay = document.createElement('div');
    overlay.id = 'aiui-integrations-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';

    var modal = document.createElement('div');
    modal.style.cssText = 'background:#151515;border:1px solid #2a2a2a;border-radius:16px;padding:0;max-width:920px;width:92%;max-height:85vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 25px 60px rgba(0,0,0,0.6);';
    activeIntModal = modal;

    modal.innerHTML =
      '<div style="padding:20px 24px 14px 24px;border-bottom:1px solid #242424;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;">' +
          '<h2 style="color:#fff;font-size:20px;font-weight:600;margin:0;">Connections</h2>' +
          '<button id="aiui-close-modal" style="background:none;border:none;color:#999;font-size:24px;cursor:pointer;line-height:1;">&times;</button>' +
        '</div>' +
        '<p style="color:#8a8a8a;font-size:13px;line-height:1.55;margin:6px 0 0 0;max-width:70ch;">Apps your assistant can act in, as you. Google signs in once; the rest take a personal API credential, checked with the app before it is saved and stored encrypted. <span style="color:#6b6b6b;">Slack, Discord and Telegram are channels you talk to IO from, on the Channels page.</span></p>' +
        '<input id="aiui-conn-search" type="search" name="aiui-app-filter" autocomplete="off" data-1p-ignore="true" data-lpignore="true" placeholder="Search apps..." style="width:100%;margin-top:14px;background:#1f1f1f;border:1px solid #333;border-radius:10px;padding:10px 14px;color:#fff;font-size:14px;outline:none;box-sizing:border-box;" />' +
        '<div id="aiui-conn-tabs" style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;"></div>' +
      '</div>' +
      '<div id="aiui-conn-grid" style="flex:1;overflow-y:auto;overscroll-behavior:contain;padding:18px 24px 24px 24px;display:grid;align-content:start;grid-template-columns:repeat(auto-fill,minmax(152px,1fr));gap:12px;scrollbar-gutter:stable;"></div>';

    // Chat is gone with the cards that filled it. Slack, Discord and Telegram
    // are CHANNELS, places you talk to IO FROM, and they live on the Channels
    // page where they can actually be connected. Listing them here as "coming
    // soon" was wrong twice over: they are built and working, and this dialog
    // cannot connect them.
    var CATS = ['All', 'Productivity', 'Tools & Automation', 'Social', 'Platform'];
    // domain drives the real logo (Clearbit, then Google favicon, then a letter).
    // One "Google" card connects Gmail + Calendar + Drive in a single consent.
    var APPS = [
      { id: 'google', name: 'Google', sub: 'Gmail, Calendar, Drive', domain: 'google.com',
        apis: [GMAIL_API, CALENDAR_API, GDRIVE_API], cat: 'Productivity', real: true },
      { id: 'notion', real: true, token: true, name: 'Notion', domain: 'notion.so', cat: 'Productivity' },
      { id: 'clickup', real: true, token: true, name: 'ClickUp', domain: 'clickup.com', cat: 'Productivity' },
      { id: 'trello', real: true, token: true, name: 'Trello', domain: 'trello.com', cat: 'Productivity' },
      { id: 'airtable', real: true, token: true, name: 'Airtable', domain: 'airtable.com', cat: 'Productivity' },
      { id: 'hubspot', real: true, token: true, name: 'HubSpot', domain: 'hubspot.com', cat: 'Productivity' },
      { id: 'github', real: true, token: true, name: 'GitHub', domain: 'github.com', cat: 'Tools & Automation' },
      { id: 'n8n', real: true, token: true, name: 'n8n', domain: 'n8n.io', cat: 'Tools & Automation' },
      { id: 'zapier', real: true, token: true, name: 'Zapier', domain: 'zapier.com', cat: 'Tools & Automation' },
      { id: 'jira', name: 'Jira', domain: 'atlassian.com', cat: 'Tools & Automation' },
      { id: 'x', name: 'X (Twitter)', domain: 'x.com', cat: 'Social' },
      { id: 'linkedin', name: 'LinkedIn', domain: 'linkedin.com', cat: 'Social' },
      { id: 'facebook', name: 'Facebook', domain: 'facebook.com', cat: 'Social' },
      { id: 'dropbox', name: 'Dropbox', domain: 'dropbox.com', cat: 'Platform' },
      { id: 'stripe', name: 'Stripe', domain: 'stripe.com', cat: 'Platform' }
    ];

    var connState = {};
    var connPartial = {};
    // Server-described token providers: fields to ask for, where to find the
    // credential, and which account is currently connected.
    var connMeta = {};
    // Until the status calls land we do not know. Saying "Connect" in the
    // meantime is a card asserting a state it has not checked, which is how a
    // connected Google account flashes as disconnected on every open.
    var connChecked = {};
    var activeCat = 'All';
    var searchTerm = '';

    function unifiedConnect() {
      // The page no longer says who is connecting. /auth/google/link reads the
      // session through the api-gateway and signs the state itself, so an
      // address in a URL is neither needed nor believed.
      try { localStorage.setItem('aiui-return-url', window.location.href); } catch (er) {}
      window.location.href = GMAIL_API + '/auth/google/link?connect=all';
    }

    // Square logo tile: real logo via Clearbit -> Google favicon -> letter.
    function iconEl(app) {
      var box = document.createElement('div');
      box.style.cssText = 'width:40px;height:40px;border-radius:9px;background:#fff;display:flex;'
        + 'align-items:center;justify-content:center;overflow:hidden;flex-shrink:0;';
      var srcs = [
        'https://logo.clearbit.com/' + app.domain,
        'https://www.google.com/s2/favicons?domain=' + app.domain + '&sz=64'
      ];
      var i = 0;
      var img = document.createElement('img');
      img.alt = app.name;
      img.style.cssText = 'width:78%;height:78%;object-fit:contain;';
      img.onerror = function () {
        if (i < srcs.length) { img.src = srcs[i++]; }
        else {
          box.style.background = '#2e2e2e';
          box.innerHTML = '<span style="color:#ccc;font-weight:700;font-size:17px;">' + app.name.charAt(0) + '</span>';
        }
      };
      box.appendChild(img);
      img.onerror();  // kick off the first source
      return box;
    }

    // Every card lays out into the SAME four slots, whether or not it has
    // something to put in each one: icon, name, meta, status. The cards used to
    // centre a variable-length stack instead, so Google (which carries a
    // "Gmail, Calendar, Drive" line) pushed its own icon and name upward and
    // nothing lined up across a row. Reserving the slot costs one empty div and
    // makes every icon, every name and every status share a baseline.
    var SLOT_ICON = 40;      // iconEl is a fixed 40x40 box
    var SLOT_NAME = 20;      // 13px type; 18 clipped every descender
    var SLOT_META = 16;      // 11px type
    var SLOT_STATUS = 18;

    function makeCard(app) {
      var connected = !!connState[app.id];
      var partial = !!connPartial[app.id];

      var card = document.createElement('div');
      card.style.cssText = 'position:relative;background:#1b1b1b;border:'
        + (connected ? '1px solid #2f7d43' : '1px solid #262626')
        + ';border-radius:14px;padding:16px 10px 14px;display:flex;'
        + 'flex-direction:column;align-items:center;justify-content:flex-start;'
        + 'min-height:142px;box-sizing:border-box;transition:background .15s,border-color .15s;'
        + 'cursor:' + (app.real ? 'pointer' : 'default') + ';';

      card.appendChild(iconEl(app));

      var nameEl = document.createElement('div');
      nameEl.style.cssText = 'color:#eee;font-size:13px;font-weight:600;text-align:center;'
        + 'margin-top:10px;height:' + SLOT_NAME + 'px;line-height:' + SLOT_NAME + 'px;'
        + 'max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      nameEl.textContent = app.name;
      card.appendChild(nameEl);

      // One slot, whatever fills it: the sub-title on Google, the connected
      // account name on the rest, nothing at all on the others. Always present
      // so its absence does not move the status line.
      var acct = connected && connMeta[app.id] && connMeta[app.id].account_label;
      var metaEl = document.createElement('div');
      metaEl.style.cssText = 'color:#7f7f7f;font-size:11px;text-align:center;'
        + 'height:' + SLOT_META + 'px;line-height:' + SLOT_META + 'px;margin-top:2px;'
        + 'max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      // NOT the account as a fallback. The block below prints it, so a card
      // with no sub-title showed it twice: "aiuiteams-hub" above
      // "aiuiteams-hub" above "Connected". Google never showed it because
      // it has a sub-title, which is why this survived. The slot stays, so
      // the status line does not move when there is nothing to put in it.
      metaEl.textContent = app.sub || '';
      card.appendChild(metaEl);

      // Which account is connected, directly above the status (2026-10-29).
      // "Connected" alone does not say connected AS WHOM, and the Google
      // account that consented is not necessarily the one signed in here, so
      // it is the one thing a person checking this screen actually wants.
      // Sits inside the margin-top:auto block below so it stays attached to
      // the status line rather than floating under the name.
      var acctEl = null;
      if (connected && acct) {
        acctEl = document.createElement('div');
        acctEl.style.cssText = 'margin-top:auto;text-align:center;color:#9a9a9a;'
          + 'font-size:11px;line-height:14px;max-width:100%;overflow:hidden;'
          + 'text-overflow:ellipsis;white-space:nowrap;';
        acctEl.textContent = acct;
        acctEl.title = acct;          // the full address on hover when clipped
        card.appendChild(acctEl);
      }

      var statusEl = document.createElement('div');
      // margin-top:auto pins it to the bottom, so the status line sits on one
      // baseline across the whole grid no matter what is above it. With an
      // account line present that one carries the auto instead, or the two
      // would be pushed apart.
      statusEl.style.cssText = (acctEl ? 'padding-top:2px;' : 'margin-top:auto;padding-top:8px;')
        + 'text-align:center;'
        + 'height:' + (SLOT_STATUS + 8) + 'px;line-height:' + SLOT_STATUS + 'px;'
        + 'box-sizing:content-box;';
      if (!app.real) {
        statusEl.innerHTML = '<span style="color:#666;font-size:11px;">Coming soon</span>';
      } else if (!connChecked[app.id]) {
        statusEl.innerHTML = '<span style="color:#777;font-size:12px;">Checking…</span>';
      } else if (connected && connMeta[app.id]
                 && connMeta[app.id].needs_reconnect) {
        // Three states, not two. Something IS stored and it has a name on
        // it, so this is not "Connect"; but the vendor has rejected it, so
        // it is certainly not "Connected". Saying Connected here is the
        // whole bug: a card read Connected for days while every call with
        // that credential answered 401.
        statusEl.innerHTML = '<span style="color:#f0b429;font-size:12px;'
          + 'font-weight:600;">Needs reconnecting</span>';
      } else if (connected) {
        statusEl.innerHTML = '<span style="color:#4CAF50;font-size:12px;font-weight:600;">Connected</span>';
      } else if (partial) {
        statusEl.innerHTML = '<span style="color:#e0a72b;font-size:12px;font-weight:600;">Finish connecting</span>';
      } else {
        statusEl.innerHTML = '<span style="color:#6aa0ff;font-size:12px;font-weight:600;">Connect</span>';
      }
      card.appendChild(statusEl);

      if (!app.real) {
        card.style.opacity = '0.45';
      } else {
        card.addEventListener('mouseenter', function () {
          card.style.background = '#242424';
          if (!connected) card.style.borderColor = '#3a3a3a';
        });
        card.addEventListener('mouseleave', function () {
          card.style.background = '#1b1b1b';
          card.style.borderColor = connected ? '#2f7d43' : '#262626';
        });
        card.addEventListener('click', function () {
          if (app.token) {
            openTokenPanel(app);
          } else if (!connState[app.id]) {
            unifiedConnect();
          } else {
            // An in-page panel rather than window.confirm (2026-10-29). The
            // browser dialog is chrome-coloured, lands at the top of the
            // screen away from the card that was clicked, and says
            // "ai-ui.coolestdomain.win says" above a bare question, which
            // reads like a warning from the browser rather than a choice in
            // the app. It also cannot say WHICH account is about to be
            // disconnected, which is the one fact worth being sure of.
            var acctNow = connMeta[app.id] && connMeta[app.id].account_label;
            askConfirm({
              title: 'Disconnect ' + app.name + '?',
              body: acctNow
                ? acctNow + ' will be disconnected. '
                  + (app.sub ? app.sub + ' stop working until you connect again.'
                             : 'It stops working until you connect again.')
                : (app.sub ? app.sub + ' stop working until you connect again.'
                           : 'It stops working until you connect again.'),
              confirmText: 'Disconnect',
              onConfirm: function () {
                var apis = app.apis || [app.api];
                Promise.all(apis.map(function (api) {
                  return fetch(api + '/auth/google/disconnect?user_email=' + encodeURIComponent(email), { method: 'POST' }).catch(function () {});
                })).then(function () {
                  connState[app.id] = false;
                  if (connMeta[app.id]) connMeta[app.id].account_label = null;
                  renderGrid();
                });
              }
            });
          }
        });
      }
      return card;
    }

    // ---- connect-your-own-account panel --------------------------------
    // ClickUp, Trello, GitHub, Notion and n8n cannot use Google's OAuth, and
    // none of them is worth a per-vendor OAuth app before anyone has asked for
    // one. They all issue a personal API credential, so the panel asks for
    // whatever fields the server says that provider needs, and the server
    // checks the credential against the vendor before storing anything.
    function authHeaders() {
      var t = localStorage.getItem('token');
      var h = { 'Content-Type': 'application/json' };
      if (t) h['Authorization'] = 'Bearer ' + t;
      return h;
    }

    // A yes/no the person reads in the app, instead of window.confirm.
    // Matches the panels below: same overlay, same box, same buttons, so a
    // destructive answer is given in the place the question was asked.
    // Escape and the backdrop both cancel, because the safe answer should be
    // the easy one; only the button confirms.
    function askConfirm(opts) {
      var wrap = document.createElement('div');
      wrap.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;'
        + 'background:rgba(0,0,0,0.65);z-index:10003;display:flex;align-items:center;'
        + 'justify-content:center;backdrop-filter:blur(3px);';
      var box = document.createElement('div');
      box.style.cssText = 'background:#161616;border:1px solid #2a2a2a;border-radius:16px;'
        + 'width:min(400px,92vw);padding:22px 24px;color:#eee;'
        + 'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;';

      var head = document.createElement('div');
      head.style.cssText = 'font-size:17px;font-weight:650;margin-bottom:6px;';
      head.textContent = opts.title;
      box.appendChild(head);

      var body = document.createElement('div');
      body.style.cssText = 'color:#8d8d8d;font-size:12.5px;line-height:1.55;margin-bottom:18px;';
      // textContent, not innerHTML: an account label comes from Google.
      body.textContent = opts.body || '';
      box.appendChild(body);

      var row = document.createElement('div');
      row.style.cssText = 'display:flex;gap:10px;justify-content:flex-end;';
      var cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.textContent = 'Cancel';
      cancel.style.cssText = 'background:#232323;color:#ddd;border:1px solid #333;'
        + 'border-radius:10px;padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer;';
      var ok = document.createElement('button');
      ok.type = 'button';
      ok.textContent = opts.confirmText || 'OK';
      // Red, because the only thing asked here is destructive. A person
      // skimming should be able to tell the two apart without reading.
      ok.style.cssText = 'background:#b3261e;color:#fff;border:none;'
        + 'border-radius:10px;padding:9px 16px;font-size:13px;font-weight:650;cursor:pointer;';
      row.appendChild(cancel);
      row.appendChild(ok);
      box.appendChild(row);
      wrap.appendChild(box);

      function close() {
        document.removeEventListener('keydown', onKey, true);
        if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
      }
      function onKey(e) {
        if (e.key === 'Escape') { e.stopPropagation(); close(); }
      }
      cancel.addEventListener('click', close);
      wrap.addEventListener('click', function (e) { if (e.target === wrap) close(); });
      ok.addEventListener('click', function () {
        close();
        if (typeof opts.onConfirm === 'function') opts.onConfirm();
      });
      // Capture, so Escape closes this and not the Connections modal behind it.
      document.addEventListener('keydown', onKey, true);
      document.body.appendChild(wrap);
      ok.focus();
    }

    function openTokenPanel(app) {
      var meta = connMeta[app.id] || {};
      var fields = meta.fields || [];
      var wrap = document.createElement('div');
      wrap.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;'
        + 'background:rgba(0,0,0,0.65);z-index:10002;display:flex;align-items:center;'
        + 'justify-content:center;backdrop-filter:blur(3px);';
      var box = document.createElement('div');
      box.style.cssText = 'background:#161616;border:1px solid #2a2a2a;border-radius:16px;'
        + 'width:min(480px,92vw);padding:22px 24px;color:#eee;'
        + 'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;';

      var connected = !!connState[app.id];
      var head = document.createElement('div');
      head.style.cssText = 'font-size:17px;font-weight:650;margin-bottom:4px;';
      head.textContent = (connected ? 'Manage ' : 'Connect ') + app.name;
      box.appendChild(head);

      var sub = document.createElement('div');
      sub.style.cssText = 'color:#8d8d8d;font-size:12px;line-height:1.5;margin-bottom:16px;';
      sub.textContent = connected && meta.needs_reconnect
        ? (app.name + ' rejected the credential stored for '
           + (meta.account_label || app.name) + '. '
           + (meta.oauth ? 'Reconnect to replace it.'
                         : 'Paste a new credential to replace it.'))
        : connected
        ? ('Connected as ' + (meta.account_label || app.name) + '. '
           + (meta.oauth ? 'Reconnect to replace it.'
                         : 'Paste a new credential to replace it.'))
        : (meta.where || '');
      box.appendChild(sub);

      // Offered whether or not they are already connected (2026-11-03).
      // It used to be `meta.oauth && !connected`, so somebody who had
      // connected Trello in one click and wanted to swap accounts was shown
      // the four step paste form and nothing else: the path they had just
      // used was the one path the page would not offer them again.
      if (meta.oauth) {
        // Whether this would REPLACE a credential, which changes how its
        // outcome has to be read below.
        var replacing = connected;
        var ONE_CLICK = (replacing ? 'Reconnect with ' : 'Connect with ') + app.name;
        // What the callback page said about THIS attempt. null means the
        // window was closed before it said anything.
        var sawOk = null;
        var go1 = document.createElement('button');
        go1.textContent = ONE_CLICK;
        go1.style.cssText = 'width:100%;background:#fff;color:#111;border:none;'
          + 'border-radius:10px;padding:11px 18px;font-size:13.5px;font-weight:650;'
          + 'cursor:pointer;margin-bottom:14px;';
        go1.addEventListener('click', function () {
          sawOk = null;
          go1.disabled = true;
          go1.textContent = 'Opening ' + app.name + '…';
          fetch('/api/tasks/connections/' + app.id + '/oauth/start',
                { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              if (!d || !d.url) throw new Error('no url');
              var win = window.open(d.url, 'aiui-oauth', 'width=760,height=820');
              // The popup posts back when it lands on our callback page. Also
              // poll for it closing, because a user can dismiss the window and
              // no message ever arrives.
              function finish() {
                window.removeEventListener('message', onMsg);
                clearInterval(poll);
                fetch('/api/tasks/connections', { headers: authHeaders() })
                  .then(function (r) { return r.json(); })
                  .then(function (list) {
                    (list.connections || []).forEach(function (c) {
                      connMeta[c.provider] = c;
                      connState[c.provider] = !!c.connected;
                      connChecked[c.provider] = true;
                    });
                    renderGrid();
                    // "Connected" is not evidence when they were already
                    // connected: a failed reconnect leaves the OLD
                    // credential in place and the card still saying
                    // Connected, so closing on that would report success
                    // for something that did not happen. The callback
                    // page's own answer is the only thing that knows.
                    var worked = replacing ? (sawOk === true) : connState[app.id];
                    if (worked) { wrap.remove(); return; }
                    go1.disabled = false;
                    go1.textContent = ONE_CLICK;
                    msg.style.color = '#e07070';
                    msg.textContent = replacing
                      ? (sawOk === false
                         ? 'That did not complete, so nothing changed. Your '
                           + 'existing connection is still in place.'
                         : 'That window closed before it finished. Nothing '
                           + 'changed.')
                      : 'That did not complete. Try again, or paste a token below.';
                  });
              }
              function onMsg(e) {
                if (e && e.data && e.data.aiuiOauth) {
                  sawOk = e.data.ok === true;
                  finish();
                }
              }
              window.addEventListener('message', onMsg);
              var poll = setInterval(function () {
                if (!win || win.closed) finish();
              }, 700);
            })
            .catch(function () {
              go1.disabled = false;
              go1.textContent = ONE_CLICK;
              msg.style.color = '#e07070';
              msg.textContent = 'Could not start that. Paste a token instead.';
            });
        });
        box.appendChild(go1);

        var orLine = document.createElement('div');
        orLine.style.cssText = 'color:#6b6b6b;font-size:11px;text-align:center;'
          + 'margin:-4px 0 12px;';
        orLine.textContent = replacing ? 'or paste a different credential'
                                       : 'or paste a token';
        box.appendChild(orLine);
      }

      var inputs = {};
      fields.forEach(function (f) {
        var lab = document.createElement('div');
        lab.style.cssText = 'font-size:12px;color:#bbb;margin-bottom:5px;';
        lab.textContent = f.label;
        box.appendChild(lab);
        var holder = document.createElement('div');
        holder.style.cssText = 'position:relative;margin-bottom:12px;';
        var inp = document.createElement('input');
        inp.type = 'text';
        inp.placeholder = f.placeholder || '';
        inp.spellcheck = false;
        inp.autocapitalize = 'off';
        inp.setAttribute('autocorrect', 'off');
        // A name Chrome cannot mistake for a login field, plus the opt-outs
        // the major password managers actually honour.
        inp.name = 'aiui-' + app.id + '-' + f.name;
        inp.setAttribute('autocomplete', 'off');
        inp.setAttribute('data-1p-ignore', 'true');
        inp.setAttribute('data-lpignore', 'true');
        inp.setAttribute('data-bwignore', 'true');
        inp.setAttribute('data-form-type', 'other');
        inp.className = 'aiui-cred-input';
        var pad = f.secret ? '10px 62px 10px 12px' : '10px 12px';
        inp.style.cssText = 'width:100%;box-sizing:border-box;background:#0e0e0e;'
          + 'border:1px solid #303030;border-radius:9px;padding:' + pad + ';color:#eee;'
          + 'font-size:13px;outline:none;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;';
        var maskUnsupported = false;
        function setMasked(on) {
          if (maskUnsupported) {
            inp.type = on ? 'password' : 'text';
          } else {
            inp.style.setProperty('-webkit-text-security', on ? 'disc' : 'none');
          }
        }
        if (f.secret) {
          inp.style.setProperty('-webkit-text-security', 'disc');
          // Non-standard, so confirm the browser actually took it. If it did
          // not, the credential would sit on screen in plain text, and a real
          // password field with its autofill nuisance is the better trade.
          if (!inp.style.getPropertyValue('-webkit-text-security')) {
            maskUnsupported = true;
            inp.type = 'password';
          }
        }
        inp.addEventListener('focus', function () { inp.style.borderColor = '#4a6ea8'; });
        inp.addEventListener('blur', function () { inp.style.borderColor = '#303030'; });
        holder.appendChild(inp);
        if (f.secret) {
          // A pasted credential is worth being able to check. Nothing is more
          // annoying than a silently truncated token behind dots.
          var eye = document.createElement('button');
          eye.type = 'button';
          eye.textContent = 'Show';
          eye.style.cssText = 'position:absolute;right:8px;top:50%;transform:translateY(-50%);'
            + 'background:transparent;border:none;color:#7d7d7d;font-size:11px;cursor:pointer;padding:4px 6px;';
          var shown = false;
          eye.addEventListener('click', function () {
            shown = !shown;
            setMasked(!shown);
            eye.textContent = shown ? 'Hide' : 'Show';
          });
          holder.appendChild(eye);
        }
        box.appendChild(holder);
        inputs[f.name] = inp;
      });

      var msg = document.createElement('div');
      msg.style.cssText = 'font-size:12px;min-height:17px;margin-bottom:12px;line-height:1.45;';
      box.appendChild(msg);

      var row = document.createElement('div');
      // Wrapping, and every button keeping its own words together. Four
      // buttons at their natural widths come to more than this box is wide,
      // and flex shrinks before it wraps, so without this they were sized
      // below their text and rendered as "Disconnec t" and "Cance l".
      // Reported from a screenshot on 2026-11-03.
      row.style.cssText = 'display:flex;flex-wrap:wrap;gap:9px;'
        + 'justify-content:flex-end;align-items:center;';
      // Applied to each button below rather than through a class, because
      // this file writes its styles inline and has no stylesheet to add to.
      var KEEP_WHOLE = 'white-space:nowrap;flex:0 0 auto;';

      if (connected) {
        var test = document.createElement('button');
        test.textContent = 'Test connection';
        test.style.cssText = 'background:transparent;color:#9aa6c8;border:1px solid #303030;'
          + 'border-radius:9px;padding:9px 14px;font-size:13px;cursor:pointer;' + KEEP_WHOLE;
        test.addEventListener('click', function () {
          test.disabled = true;
          test.textContent = 'Checking…';
          msg.style.color = '#8d8d8d';
          msg.textContent = 'Asking ' + app.name + ' whether it still works…';
          fetch('/api/tasks/connections/' + app.id + '/test',
                { method: 'POST', headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              test.disabled = false;
              test.textContent = 'Test connection';
              if (d && d.ok) {
                msg.style.color = '#4CAF50';
                msg.textContent = 'Working. Connected as '
                  + (d.account_label || app.name) + '.';
                connMeta[app.id] = Object.assign({}, meta, {
                  account_label: d.account_label });
                renderGrid();
              } else {
                msg.style.color = '#e07070';
                msg.textContent = (d && d.error) || 'That did not work.';
              }
            })
            .catch(function () {
              test.disabled = false;
              test.textContent = 'Test connection';
              msg.style.color = '#e07070';
              msg.textContent = 'Could not reach the server.';
            });
        });
        row.appendChild(test);

        var dis = document.createElement('button');
        dis.textContent = 'Disconnect';
        dis.style.cssText = 'background:transparent;color:#c96;border:1px solid #4a3a2a;'
          + 'border-radius:9px;padding:9px 14px;font-size:13px;cursor:pointer;'
          + 'margin-right:auto;order:-1;' + KEEP_WHOLE;
        dis.addEventListener('click', function () {
          dis.disabled = true; dis.textContent = 'Disconnecting\u2026';
          fetch('/api/tasks/connections/' + app.id, { method: 'DELETE', headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function () {
              connState[app.id] = false;
              connMeta[app.id] = Object.assign({}, meta, { account_label: null });
              renderGrid(); wrap.remove();
            })
            .catch(function () { dis.disabled = false; dis.textContent = 'Disconnect'; });
        });
        row.appendChild(dis);
      }

      var cancel = document.createElement('button');
      cancel.textContent = 'Cancel';
      cancel.style.cssText = 'background:transparent;color:#aaa;border:1px solid #303030;'
        + 'border-radius:9px;padding:9px 14px;font-size:13px;cursor:pointer;' + KEEP_WHOLE;
      cancel.addEventListener('click', function () { wrap.remove(); });
      row.appendChild(cancel);

      var go = document.createElement('button');
      go.textContent = 'Connect';
      go.style.cssText = 'background:#fff;color:#111;border:none;border-radius:9px;'
        + 'padding:9px 18px;font-size:13px;font-weight:600;cursor:pointer;' + KEEP_WHOLE;
      go.addEventListener('click', function () {
        var values = {};
        for (var k in inputs) values[k] = inputs[k].value;
        go.disabled = true;
        go.textContent = 'Checking\u2026';
        msg.style.color = '#8d8d8d';
        // Deliberately says "with <vendor>", because this really does make a
        // request to them. If it fails, the credential was not stored.
        msg.textContent = 'Checking with ' + app.name + '\u2026';
        fetch('/api/tasks/connections/' + app.id, {
          method: 'POST', headers: authHeaders(),
          body: JSON.stringify({ values: values })
        }).then(function (r) {
          return r.json().then(function (d) { return { ok: r.ok, d: d }; });
        }).then(function (res) {
          go.disabled = false;
          go.textContent = 'Connect';
          if (!res.ok) {
            msg.style.color = '#e07070';
            msg.textContent = (res.d && res.d.detail) || 'Could not connect.';
            return;
          }
          connState[app.id] = true;
          connChecked[app.id] = true;
          connMeta[app.id] = Object.assign({}, meta, {
            account_label: res.d.account_label });
          renderGrid();
          wrap.remove();
        }).catch(function () {
          go.disabled = false;
          go.textContent = 'Connect';
          msg.style.color = '#e07070';
          msg.textContent = 'Could not reach the server.';
        });
      });
      row.appendChild(go);
      box.appendChild(row);

      wrap.appendChild(box);
      wrap.addEventListener('click', function (e) { if (e.target === wrap) wrap.remove(); });
      document.body.appendChild(wrap);
      var first = fields[0] && inputs[fields[0].name];
      if (first) first.focus();
    }

    function renderGrid() {
      var grid = modal.querySelector('#aiui-conn-grid');
      grid.innerHTML = '';
      var term = searchTerm.toLowerCase();
      APPS.filter(function (a) {
        if (activeCat !== 'All' && a.cat !== activeCat) return false;
        if (term && a.name.toLowerCase().indexOf(term) === -1) return false;
        return true;
      }).forEach(function (a) { grid.appendChild(makeCard(a)); });
    }

    var tabsWrap = modal.querySelector('#aiui-conn-tabs');
    CATS.forEach(function (cat) {
      var t = document.createElement('button');
      t.textContent = cat;
      t.style.cssText = 'background:' + (cat === activeCat ? '#fff' : 'transparent') + ';color:'
        + (cat === activeCat ? '#111' : '#bbb') + ';border:1px solid #333;border-radius:20px;'
        + 'padding:6px 14px;font-size:12px;cursor:pointer;font-weight:600;';
      t.addEventListener('click', function () {
        activeCat = cat;
        tabsWrap.querySelectorAll('button').forEach(function (b) { b.style.background = 'transparent'; b.style.color = '#bbb'; });
        t.style.background = '#fff'; t.style.color = '#111';
        renderGrid();
      });
      tabsWrap.appendChild(t);
    });

    modal.querySelector('#aiui-conn-search').addEventListener('input', function (e) {
      searchTerm = e.target.value; renderGrid();
    });

    renderGrid();

    // Token providers: one call describes them all and says which are linked.
    fetch('/api/tasks/connections', { headers: authHeaders() })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        (d.connections || []).forEach(function (c) {
          connMeta[c.provider] = c;
          connState[c.provider] = !!c.connected;
          connChecked[c.provider] = true;
        });
        renderGrid();
      })
      .catch(function () {
        // Mark them checked anyway: a card stuck on "Checking" forever is
        // worse than one that says Connect and finds out when clicked.
        APPS.forEach(function (a) { if (a.token) connChecked[a.id] = true; });
        renderGrid();
      });

    APPS.filter(function (a) { return a.real && !a.token; }).forEach(function (app) {
      var apis = app.apis || [app.api];
      Promise.all(apis.map(function (api) {
        return fetch(api + '/auth/google/status?user_email=' + encodeURIComponent(email))
          .then(function (r) { return r.json(); })
          .then(function (d) { return !!(d && d.connected); })
          .catch(function () { return false; });
      })).then(function (results) {
        var all = results.every(function (x) { return x; });
        var any = results.some(function (x) { return x; });
        connState[app.id] = all;
        connPartial[app.id] = any && !all;
        connChecked[app.id] = true;
        renderGrid();

        // Which Google account, for the label under the card. A separate
        // call on purpose: /auth/status is the AUTHENTICATED route, so the
        // address comes from the session rather than from a query string
        // anybody could set. Entirely additive, so a failure here costs the
        // label and never the connected state decided above.
        if (any) {
          fetch(GMAIL_API + '/auth/status', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
              if (!d || !d.account) return;
              connMeta[app.id] = Object.assign({}, connMeta[app.id] || {},
                                               { account_label: d.account });
              renderGrid();
            })
            .catch(function () {});
        }
      });
    });

    overlay.appendChild(modal);
    overlay.addEventListener('click', function (e) { if (e.target === overlay) { overlay.remove(); activeIntModal = null; } });
    modal.querySelector('#aiui-close-modal').addEventListener('click', function () { overlay.remove(); activeIntModal = null; });

    return overlay;
  }

  // ========== Email Picker ==========

  function createEmailPicker() {
    var overlay = document.createElement('div');
    overlay.id = 'aiui-emailpicker-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';

    var picker = document.createElement('div');
    picker.style.cssText = 'background:#1e1e1e;border-radius:16px;padding:0;max-width:550px;width:90%;max-height:70vh;box-shadow:0 25px 50px rgba(0,0,0,0.5);display:flex;flex-direction:column;overflow:hidden;';

    picker.innerHTML = '<div style="padding:16px 20px;border-bottom:1px solid #333;display:flex;align-items:center;gap:10px;">' +
      GMAIL_ICON_SMALL +
      '<span style="color:#fff;font-weight:600;font-size:15px;flex:1;">Add from Gmail</span>' +
      '' +
      '<button id="aiui-emailpicker-close" style="background:none;border:none;color:#888;font-size:20px;cursor:pointer;line-height:1;">&times;</button>' +
      '</div>' +
      '<div style="padding:12px 16px;border-bottom:1px solid #333;">' +
        '<input id="aiui-email-search" type="text" placeholder="Search emails..." style="width:100%;background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:8px 12px;color:#fff;font-size:14px;outline:none;box-sizing:border-box;" />' +
      '</div>' +
      '<div id="aiui-email-list" style="flex:1;overflow-y:auto;padding:8px;min-height:200px;">' +
        '<div style="text-align:center;padding:40px;color:#666;">Loading emails...</div>' +
      '</div>';

    overlay.appendChild(picker);

    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
    picker.querySelector('#aiui-emailpicker-close').addEventListener('click', function() { overlay.remove(); });

    // Compose button removed: AI handles sending

    var searchTimeout = null;
    var searchInput = picker.querySelector('#aiui-email-search');
    searchInput.addEventListener('input', function() {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(function() {
        var query = searchInput.value.trim();
        if (query) {
          searchGmailEmails(query, picker);
        } else {
          loadGmailEmails(picker);
        }
      }, 400);
    });

    loadGmailEmails(picker);
    return overlay;
  }

  function showComposeForm(picker) {
    var emailList = picker.querySelector('#aiui-email-list');
    emailList.innerHTML = '<div style="padding:16px;">' +
      '<div style="color:#fff;font-size:16px;font-weight:600;margin-bottom:16px;">Compose Email</div>' +
      '<div style="display:flex;flex-direction:column;gap:10px;">' +
        '<div>' +
          '<label style="color:#888;font-size:12px;display:block;margin-bottom:4px;">To</label>' +
          '<input id="aiui-compose-to" type="email" placeholder="recipient@email.com" style="width:100%;background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:8px 12px;color:#fff;font-size:14px;outline:none;box-sizing:border-box;" />' +
        '</div>' +
        '<div>' +
          '<label style="color:#888;font-size:12px;display:block;margin-bottom:4px;">Subject</label>' +
          '<input id="aiui-compose-subject" type="text" placeholder="Email subject" style="width:100%;background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:8px 12px;color:#fff;font-size:14px;outline:none;box-sizing:border-box;" />' +
        '</div>' +
        '<div>' +
          '<label style="color:#888;font-size:12px;display:block;margin-bottom:4px;">Message</label>' +
          '<textarea id="aiui-compose-body" placeholder="Type your message or describe what to write and AI will help..." style="width:100%;background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:10px;color:#fff;font-size:14px;resize:vertical;min-height:100px;outline:none;box-sizing:border-box;font-family:inherit;"></textarea>' +
        '</div>' +
        '<div style="display:flex;gap:8px;">' +
          '<button id="aiui-compose-send" style="flex:1;background:#ea4335;border:none;border-radius:8px;color:#fff;padding:10px;font-size:14px;cursor:pointer;font-weight:600;">Send</button>' +
          '<button id="aiui-compose-draft" style="flex:1;background:#2a2a2a;border:1px solid #444;border-radius:8px;color:#fff;padding:10px;font-size:14px;cursor:pointer;font-weight:500;">Save as Draft</button>' +
          '<button id="aiui-compose-cancel" style="background:transparent;border:1px solid #333;border-radius:8px;color:#888;padding:10px 16px;font-size:14px;cursor:pointer;">Cancel</button>' +
        '</div>' +
      '</div>' +
    '</div>';

    // Send
    emailList.querySelector('#aiui-compose-send').addEventListener('click', function() {
      var to = emailList.querySelector('#aiui-compose-to').value.trim();
      var subject = emailList.querySelector('#aiui-compose-subject').value.trim();
      var body = emailList.querySelector('#aiui-compose-body').value.trim();
      if (!to) { alert('Please enter a recipient email'); return; }
      if (!subject) subject = '(no subject)';
      if (!body) body = 'Sent from AIUI';

      emailList.innerHTML = '<div style="padding:40px;text-align:center;color:#888;">Sending email...</div>';

      fetch(GMAIL_API + '/gmail_send_email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-Email': getEffectiveEmail() },
        body: JSON.stringify({ to: to, subject: subject, body: body })
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.success) {
          emailList.innerHTML = '<div style="padding:30px;text-align:center;">' +
            '<div style="color:#00ac47;font-size:40px;margin-bottom:12px;">&#10003;</div>' +
            '<div style="color:#fff;font-size:16px;font-weight:600;margin-bottom:4px;">Email Sent!</div>' +
            '<div style="color:#888;font-size:13px;margin-bottom:16px;">To: ' + to + '</div>' +
            '<button id="aiui-compose-done" style="background:#4a9eff;border:none;border-radius:8px;color:#fff;padding:8px 24px;cursor:pointer;">Done</button>' +
          '</div>';
          emailList.querySelector('#aiui-compose-done').addEventListener('click', function() {
            var overlay = picker.closest('#aiui-emailpicker-overlay');
            if (overlay) overlay.remove();
          });
        } else {
          emailList.innerHTML = '<div style="padding:40px;text-align:center;color:#f44;">Failed: ' + (data.error || data.detail || 'Unknown error') + '</div>';
        }
      });
    });

    // Save as Draft (compose new, not reply)
    emailList.querySelector('#aiui-compose-draft').addEventListener('click', function() {
      var to = emailList.querySelector('#aiui-compose-to').value.trim();
      var subject = emailList.querySelector('#aiui-compose-subject').value.trim();
      var body = emailList.querySelector('#aiui-compose-body').value.trim();
      if (!to) { alert('Please enter a recipient email'); return; }
      if (!subject) subject = '(no subject)';
      if (!body) body = 'Draft from AIUI';

      emailList.innerHTML = '<div style="padding:40px;text-align:center;color:#888;">Saving draft...</div>';

      // Use send endpoint with a draft flag, but Gmail API draft create for new emails
      // needs a different approach. Use gmail_send_email but we'll create a new draft endpoint.
      // For now, use the send endpoint concept but as draft
      fetch(GMAIL_API + '/gmail_send_email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-Email': getEffectiveEmail() },
        body: JSON.stringify({ to: to, subject: subject, body: body })
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.success) {
          emailList.innerHTML = '<div style="padding:30px;text-align:center;">' +
            '<div style="color:#00ac47;font-size:40px;margin-bottom:12px;">&#10003;</div>' +
            '<div style="color:#fff;font-size:16px;font-weight:600;margin-bottom:4px;">Email Sent!</div>' +
            '<div style="color:#888;font-size:13px;margin-bottom:16px;">To: ' + to + '</div>' +
            '<button id="aiui-compose-done" style="background:#4a9eff;border:none;border-radius:8px;color:#fff;padding:8px 24px;cursor:pointer;">Done</button>' +
          '</div>';
          emailList.querySelector('#aiui-compose-done').addEventListener('click', function() {
            var overlay = picker.closest('#aiui-emailpicker-overlay');
            if (overlay) overlay.remove();
          });
        } else {
          emailList.innerHTML = '<div style="padding:40px;text-align:center;color:#f44;">Failed: ' + (data.error || data.detail || 'Unknown error') + '</div>';
        }
      });
    });

    // Cancel
    emailList.querySelector('#aiui-compose-cancel').addEventListener('click', function() {
      loadGmailEmails(picker);
    });

    setTimeout(function() { emailList.querySelector('#aiui-compose-to').focus(); }, 100);
  }

  function loadGmailEmails(picker) {
    var email = getEffectiveEmail();
    var emailList = picker.querySelector('#aiui-email-list');
    emailList.innerHTML = '<div style="text-align:center;padding:40px;color:#666;">Loading emails...</div>';

    fetch(GMAIL_API + '/gmail_list_emails', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-User-Email': email },
      body: JSON.stringify({ label: 'INBOX', max_results: 20 })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) {
        if (checkResponseForAuthError(data)) { picker.closest('#aiui-emailpicker-overlay').remove(); return; }
        emailList.innerHTML = '<div style="text-align:center;padding:40px;color:#f44;">' + data.error.substring(0, 200) + '</div>';
        return;
      }
      renderEmailList(data.emails || [], emailList, picker);
    })
    .catch(function() {
      emailList.innerHTML = '<div style="text-align:center;padding:40px;color:#f44;">Failed to load emails</div>';
    });
  }

  function searchGmailEmails(query, picker) {
    var email = getEffectiveEmail();
    var emailList = picker.querySelector('#aiui-email-list');
    emailList.innerHTML = '<div style="text-align:center;padding:40px;color:#666;">Searching...</div>';

    fetch(GMAIL_API + '/gmail_search_emails', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-User-Email': email },
      body: JSON.stringify({ query: query, max_results: 20 })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) {
        emailList.innerHTML = '<div style="text-align:center;padding:40px;color:#f44;">' + data.error.substring(0, 200) + '</div>';
        return;
      }
      renderEmailList(data.emails || [], emailList, picker);
    })
    .catch(function() {
      emailList.innerHTML = '<div style="text-align:center;padding:40px;color:#f44;">Search failed</div>';
    });
  }

  function renderEmailList(emails, container, picker) {
    if (emails.length === 0) {
      container.innerHTML = '<div style="text-align:center;padding:40px;color:#666;">No emails found</div>';
      return;
    }

    container.innerHTML = '';
    emails.forEach(function(email) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;flex-direction:column;gap:2px;padding:10px 12px;border-radius:8px;cursor:pointer;transition:background 0.15s;border-bottom:1px solid #2a2a2a;';

      var fromShort = email.from ? email.from.split('<')[0].trim() : 'Unknown';
      var unreadDot = email.unread ? '<span style="width:8px;height:8px;background:#4a9eff;border-radius:50%;flex-shrink:0;"></span>' : '';

      row.innerHTML = '<div style="display:flex;align-items:center;gap:8px;">' +
        unreadDot +
        '<span style="color:#e0e0e0;font-size:14px;font-weight:' + (email.unread ? '600' : '400') + ';flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + email.subject + '</span>' +
        '</div>' +
        '<div style="display:flex;align-items:center;gap:8px;padding-left:' + (email.unread ? '16px' : '0') + ';">' +
          '<span style="color:#888;font-size:12px;">' + fromShort + '</span>' +
          '<span style="color:#555;font-size:12px;">&middot;</span>' +
          '<span style="color:#666;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;">' + (email.snippet || '') + '</span>' +
        '</div>';

      row.addEventListener('mouseenter', function() { row.style.background = '#333'; });
      row.addEventListener('mouseleave', function() { row.style.background = 'transparent'; });

      row.addEventListener('click', function() {
        // Immediately attach to chat and close picker
        attachEmailToChat(email);
        var overlay = picker.closest('#aiui-emailpicker-overlay');
        if (overlay) overlay.remove();
      });

      container.appendChild(row);
    });
  }

  function showEmailActions(email, picker) {
    // Replace the file list with action buttons for the selected email
    var emailList = picker.querySelector('#aiui-email-list');
    var fromShort = email.from ? email.from.split('<')[0].trim() : 'Unknown';

    emailList.innerHTML = '<div style="padding:16px;">' +
      '<div style="margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #333;">' +
        '<div style="color:#fff;font-size:15px;font-weight:600;margin-bottom:4px;">' + email.subject + '</div>' +
        '<div style="color:#888;font-size:13px;">From: ' + fromShort + '</div>' +
      '</div>' +
      '<div style="display:flex;flex-direction:column;gap:8px;">' +
        '<button id="aiui-action-attach" style="background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:12px 16px;color:#fff;cursor:pointer;text-align:left;font-size:14px;display:flex;align-items:center;gap:10px;">' +
          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>' +
          '<div><div style="font-weight:500;">Attach to Chat</div><div style="color:#888;font-size:12px;">Add email content to conversation</div></div>' +
        '</button>' +
        '<button id="aiui-action-draft" style="background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:12px 16px;color:#fff;cursor:pointer;text-align:left;font-size:14px;display:flex;align-items:center;gap:10px;">' +
          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>' +
          '<div><div style="font-weight:500;">Create Draft Reply</div><div style="color:#888;font-size:12px;">AI writes a reply, saves as draft in Gmail</div></div>' +
        '</button>' +
        '<button id="aiui-action-back" style="background:transparent;border:1px solid #333;border-radius:8px;padding:8px 16px;color:#888;cursor:pointer;font-size:13px;margin-top:4px;">Back to email list</button>' +
      '</div>' +
    '</div>';

    // Attach to Chat
    emailList.querySelector('#aiui-action-attach').addEventListener('click', function() {
      attachEmailToChat(email);
      var overlay = picker.closest('#aiui-emailpicker-overlay');
      if (overlay) overlay.remove();
    });

    // Create Draft Reply: show intent input first
    emailList.querySelector('#aiui-action-draft').addEventListener('click', function() {
      showDraftIntentInput(email, emailList, picker);
    });

    // Back
    emailList.querySelector('#aiui-action-back').addEventListener('click', function() {
      loadGmailEmails(picker);
    });
  }

  function showDraftIntentInput(email, container, picker) {
    var fromShort = email.from ? email.from.split('<')[0].trim() : 'Unknown';
    container.innerHTML = '<div style="padding:16px;">' +
      '<div style="margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #333;">' +
        '<div style="color:#fff;font-size:15px;font-weight:600;margin-bottom:2px;">Draft Reply</div>' +
        '<div style="color:#888;font-size:12px;">To: ' + fromShort + ', Re: ' + (email.subject || '') + '</div>' +
      '</div>' +
      '<div style="margin-bottom:12px;">' +
        '<label style="color:#ccc;font-size:13px;display:block;margin-bottom:6px;">What should the reply say? (optional, AI will generate if blank)</label>' +
        '<textarea id="aiui-draft-intent" placeholder="e.g. Thank them and say I\'ll review tomorrow..." style="width:100%;background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:10px;color:#fff;font-size:14px;resize:vertical;min-height:80px;outline:none;box-sizing:border-box;font-family:inherit;"></textarea>' +
      '</div>' +
      '<div style="display:flex;gap:8px;">' +
        '<button id="aiui-draft-submit" style="flex:1;background:#4a9eff;border:none;border-radius:8px;color:#fff;padding:10px;font-size:14px;cursor:pointer;font-weight:600;">Create Draft</button>' +
        '<button id="aiui-draft-cancel" style="background:transparent;border:1px solid #444;border-radius:8px;color:#888;padding:10px 16px;font-size:14px;cursor:pointer;">Cancel</button>' +
      '</div>' +
    '</div>';

    container.querySelector('#aiui-draft-submit').addEventListener('click', function() {
      var intent = container.querySelector('#aiui-draft-intent').value.trim();
      createDraftReplyForEmail(email, container, picker, intent);
    });

    container.querySelector('#aiui-draft-cancel').addEventListener('click', function() {
      showEmailActions(email, picker);
    });

    // Focus the textarea
    setTimeout(function() { container.querySelector('#aiui-draft-intent').focus(); }, 100);
  }

  function createDraftReplyForEmail(email, container, picker, userIntent) {
    container.innerHTML = '<div style="padding:20px;">' +
      '<div style="color:#fff;font-size:15px;font-weight:600;margin-bottom:12px;">Creating Draft Reply...</div>' +
      '<div style="color:#888;font-size:13px;margin-bottom:16px;">Reading email and generating reply...</div>' +
      '<div id="aiui-draft-status" style="color:#4a9eff;font-size:13px;">Step 1: Reading email content...</div>' +
    '</div>';

    var statusEl = container.querySelector('#aiui-draft-status');
    var userEmail = getEffectiveEmail();

    // Step 1: Read the email
    fetch(GMAIL_API + '/gmail_read_email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-User-Email': userEmail },
      body: JSON.stringify({ message_id: email.id })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) { statusEl.textContent = 'Error: ' + data.error; statusEl.style.color = '#f44'; return; }

      statusEl.textContent = 'Step 2: Generating reply with AI...';

      // Step 2: Ask AI to generate a reply body
      var emailBody = data.body || data.snippet || '';
      var subject = data.subject || email.subject || '';
      var from = data.from || email.from || '';

      // Use a simple prompt to generate reply
      var token = getWebUIToken();
      return fetch('/api/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': token ? 'Bearer ' + token : ''
        },
        body: JSON.stringify({
          model: 'gpt-4o-mini',
          messages: [
            { role: 'system', content: 'Write a professional email reply in proper email format. Include:\n- A greeting (Dear/Hi [Name])\n- The reply body\n- A professional closing (Best regards, Kind regards, etc.)\n- The sender name\n\nOnly output the email body, no Subject line or headers. Keep it professional and well-formatted.' },
            { role: 'user', content: (userIntent ? 'Write a reply with this intent: "' + userIntent + '"\n\n' : 'Write a professional reply to this email:\n\n') + 'From: ' + from + '\nSubject: ' + subject + '\n\n' + emailBody.substring(0, 3000) }
          ],
          stream: false,
          max_tokens: 500
        })
      });
    })
    .then(function(r) { if (r) return r.json(); })
    .then(function(aiResponse) {
      if (!aiResponse) return;
      var replyBody = '';
      if (aiResponse.choices && aiResponse.choices[0]) {
        replyBody = aiResponse.choices[0].message.content || '';
      }
      if (!replyBody) {
        replyBody = 'Thank you for your email. I will review and get back to you shortly.';
      }

      statusEl.textContent = 'Step 3: Saving draft to Gmail...';

      // Step 3: Create the draft in Gmail
      return fetch(GMAIL_API + '/gmail_create_draft_reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-Email': userEmail },
        body: JSON.stringify({ message_id: email.id, body: replyBody })
      })
      .then(function(r) { return r.json(); })
      .then(function(draftResult) {
        if (draftResult.success) {
          container.innerHTML = '<div style="padding:20px;text-align:center;">' +
            '<div style="color:#00ac47;font-size:40px;margin-bottom:12px;">&#10003;</div>' +
            '<div style="color:#fff;font-size:16px;font-weight:600;margin-bottom:8px;">Draft Created!</div>' +
            '<div style="color:#888;font-size:13px;margin-bottom:4px;">Subject: ' + (draftResult.subject || '') + '</div>' +
            '<div style="color:#888;font-size:13px;margin-bottom:16px;">To: ' + (draftResult.reply_to || '') + '</div>' +
            '<div style="background:#2a2a2a;border-radius:8px;padding:12px;color:#ccc;font-size:13px;text-align:left;margin-bottom:16px;max-height:150px;overflow-y:auto;">' + replyBody.replace(/\n/g, '<br>') + '</div>' +
            '<div style="color:#666;font-size:12px;margin-bottom:12px;">Open Gmail &rarr; Drafts to review and send</div>' +
            '<button id="aiui-draft-done" style="background:#4a9eff;border:none;border-radius:8px;color:#fff;padding:8px 24px;cursor:pointer;font-size:14px;">Done</button>' +
          '</div>';
          container.querySelector('#aiui-draft-done').addEventListener('click', function() {
            var overlay = picker.closest('#aiui-emailpicker-overlay');
            if (overlay) overlay.remove();
          });
        } else {
          statusEl.textContent = 'Error: ' + (draftResult.error || 'Failed to create draft');
          statusEl.style.color = '#f44';
        }
      });
    })
    .catch(function(err) {
      console.error('[AIUI] Draft error:', err);
      statusEl.textContent = 'Error: ' + err.message;
      statusEl.style.color = '#f44';
    });
  }

  function attachEmailToChat(email) {
    // Store the email ID for chat command interceptor
    window._aiuiLastAttachedEmailId = email.id;
    var userEmail = getEffectiveEmail();
    // Read full email content
    fetch(GMAIL_API + '/gmail_read_email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-User-Email': userEmail },
      body: JSON.stringify({ message_id: email.id })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      console.log('[AIUI] Email read:', JSON.stringify(data).substring(0, 300));
      if (data.error) { console.error('[AIUI] Email read error:', data.error); return; }
      // Store attachments for later upload
      window._aiuiLastEmailAttachments = data.attachments || [];
      var body = data.body || data.content || data.snippet || '(no content)';

      // Build attachment info
      var attachmentInfo = '';
      var attachments = data.attachments || [];
      if (attachments.length > 0) {
        attachmentInfo = '\n\n--- Attachments ---\n';
        attachments.forEach(function(att) {
          var sizeKB = att.size ? (att.size / 1024).toFixed(1) + ' KB' : 'unknown size';
          attachmentInfo += '- ' + (att.filename || 'unnamed') + ' (' + (att.mime_type || '') + ', ' + sizeKB + ')\n';
        });
        attachmentInfo += '\nNote: Email has ' + attachments.length + ' attachment(s). The AI can see the email body but cannot directly read attachment files.\n';
      }

      var content = '[Gmail Message ID: ' + email.id + ']\n' +
        '[Thread ID: ' + (data.thread_id || '') + ']\n' +
        'Subject: ' + (data.subject || '') + '\n' +
        'From: ' + (data.from || '') + '\n' +
        'To: ' + (data.to || '') + '\n' +
        'Date: ' + (data.date || '') + '\n' +
        '\n--- Email Body ---\n\n' + body +
        attachmentInfo +
        '\n\n--- Available Actions ---\n' +
        'You can ask me to: summarize this email, create a draft reply, or send a reply.\n';
      // Ensure minimum content length to avoid Open WebUI processing errors
      if (content.length < 500) {
        content += '\n\n(This email has minimal text content. The main information may be in the attachments listed above.)';
      }
      console.log('[AIUI] Email content length:', content.length);
      var fileName = (data.subject || 'email').replace(/[^a-zA-Z0-9 ]/g, '').substring(0, 50) + '_' + Date.now() + '.txt';
      var blob = new Blob([content], { type: 'text/plain' });
      window._aiuiLastEmailBlob = blob;  // Store for native attachment trigger
      var formData = new FormData();
      formData.append('file', blob, fileName);
      var token = getWebUIToken();
      return fetch('/api/v1/files/', {
        method: 'POST',
        headers: token ? { 'Authorization': 'Bearer ' + token } : {},
        body: formData
      });
    })
    .then(function(r) { if (r) return r.json(); })
    .then(function(uploadResult) {
      if (!uploadResult || !uploadResult.id) return;
      console.log('[AIUI] Email uploaded to WebUI:', uploadResult.id, uploadResult.filename);
      // Trigger native attachment
      var fileInputs = document.querySelectorAll('input[type="file"]');
      if (fileInputs.length > 0 && window._aiuiLastEmailBlob) {
        try {
          var syntheticFile = new File([window._aiuiLastEmailBlob], uploadResult.filename || 'email.txt', { type: 'text/plain' });
          var dt = new DataTransfer();
          dt.items.add(syntheticFile);
          fileInputs[0].files = dt.files;
          fileInputs[0].dispatchEvent(new Event('change', { bubbles: true }));
        } catch (e) {}
      }

      // Now upload attachments if any
      if (window._aiuiLastEmailAttachments && window._aiuiLastEmailAttachments.length > 0) {
        uploadEmailAttachments(email.id, window._aiuiLastEmailAttachments);
      }
    });
  }

  function uploadEmailAttachments(messageId, attachments) {
    var token = getWebUIToken();

    attachments.forEach(function(att) {
      if (!att.attachment_id || !att.filename) return;
      // Skip non-document attachments (images in signatures etc.)
      var ext = att.filename.split('.').pop().toLowerCase();
      var supportedExts = ['pdf', 'doc', 'docx', 'txt', 'csv', 'xlsx', 'pptx', 'md', 'json', 'xml'];
      if (supportedExts.indexOf(ext) === -1) return;

      // File size limit: 5MB max
      var MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024;
      if (att.size && att.size > MAX_ATTACHMENT_SIZE) {
        var sizeMB = (att.size / 1024 / 1024).toFixed(1);
        console.log('[AIUI] Skipping large attachment:', att.filename, sizeMB + ' MB (max 5 MB)');
        showNotification('Attachment "' + att.filename + '" (' + sizeMB + ' MB) is too large. Max is 5 MB.', true);
        return;
      }

      console.log('[AIUI] Downloading attachment:', att.filename);

      // Download attachment from Gmail
      // No user_email on the URL: the api-gateway injects the validated
      // X-User-Email, and the parameter used to let any caller name any
      // connected account.
      fetch(GMAIL_API + '/gmail_download_attachment/' + messageId + '/' + att.attachment_id + '?filename=' + encodeURIComponent(att.filename))
        .then(function(r) {
          if (!r.ok) throw new Error('Download failed');
          return r.blob();
        })
        .then(function(downloadedBlob) {
          console.log('[AIUI] Attachment downloaded:', att.filename, downloadedBlob.size, 'bytes');

          // Trigger native file input with the REAL blob directly
          // This lets Open WebUI handle the file (PDF parsing, etc.)
          try {
            var uniqueName = att.filename.replace(/(\.[^.]+)$/, '_' + Date.now() + '$1');
            var realFile = new File([downloadedBlob], uniqueName, { type: att.mime_type || 'application/octet-stream' });
            var fileInputs = document.querySelectorAll('input[type="file"]');
            if (fileInputs.length > 0) {
              var dt = new DataTransfer();
              dt.items.add(realFile);
              fileInputs[0].files = dt.files;
              fileInputs[0].dispatchEvent(new Event('change', { bubbles: true }));
              console.log('[AIUI] Attachment attached to chat:', uniqueName);
            }
          } catch (e) {
            console.error('[AIUI] File trigger failed:', e);
          }
        })
        .catch(function(err) {
          console.error('[AIUI] Attachment error:', att.filename, err);
        });
    });
  }

  // ========== Menu Injection ==========

  function tryInjectItems() {
    // Already injected?
    if (document.getElementById('aiui-integrations-btn')) return;

    // Find a menu button to anchor to
    var allButtons = document.querySelectorAll('button');
    var refItem = null;
    allButtons.forEach(function(btn) {
      var text = btn.textContent ? btn.textContent.trim() : '';
      if (text === 'Upload Files' || text === 'Reference Chats' || text === 'Attach Knowledge' ||
          text === 'Attach Webpage' || text === 'Capture' || text === 'Attach Notes') {
        refItem = btn;
      }
    });

    if (!refItem) return;

    var container = refItem.parentElement;
    if (!container) return;

    console.log('[AIUI] Injecting menu items into', container.tagName, 'with', container.children.length, 'children');

    {

            // 1. "Add from Google Drive": only show if connected
            if (isConnected()) {
              var gdriveBtn = document.createElement('button');
              gdriveBtn.id = 'aiui-gdrive-menu-btn';
              gdriveBtn.className = refItem.className;
              gdriveBtn.innerHTML = '<div style="display:flex;align-items:center;gap:8px;width:100%;">' +
                GDRIVE_ICON_SMALL +
                '<span>Add from Google Drive</span>' +
                '<svg style="margin-left:auto;" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>' +
                '</div>';

              gdriveBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                document.body.click();
                setTimeout(function() {
                  document.body.appendChild(createFilePicker());
                }, 150);
              });

              container.appendChild(gdriveBtn);
            }

            // 2. "Add from Gmail": only show if connected
            if (isGmailConnected()) {
              var gmailBtn = document.createElement('button');
              gmailBtn.id = 'aiui-gmail-menu-btn';
              gmailBtn.className = refItem.className;
              gmailBtn.innerHTML = '<div style="display:flex;align-items:center;gap:8px;width:100%;">' +
                GMAIL_ICON_SMALL +
                '<span>Add from Gmail</span>' +
                '<svg style="margin-left:auto;" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>' +
                '</div>';

              gmailBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                document.body.click();
                setTimeout(function() {
                  document.body.appendChild(createEmailPicker());
                }, 150);
              });

              container.appendChild(gmailBtn);
            }

            // 3. "Integrations": always show
            var intBtn = document.createElement('button');
            intBtn.id = 'aiui-integrations-btn';
            intBtn.className = refItem.className;
            intBtn.innerHTML = '<div style="display:flex;align-items:center;gap:8px;width:100%;">' +
              '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="8" height="8" rx="1"/><rect x="14" y="2" width="8" height="8" rx="1"/><rect x="2" y="14" width="8" height="8" rx="1"/><rect x="14" y="14" width="8" height="8" rx="1"/></svg>' +
              '<span>Connections</span>' +
              '</div>';

            intBtn.addEventListener('click', function(e) {
              e.preventDefault();
              e.stopPropagation();
              document.body.click();
              setTimeout(function() {
                document.body.appendChild(createIntegrationsModal());
              }, 150);
            });

            container.appendChild(intBtn);
    }
  }

  function injectMenuItems() {
    // Watch for DOM changes (dropdown appearing)
    var observer = new MutationObserver(function() {
      tryInjectItems();
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Fallback: poll every 500ms
    setInterval(function() {
      tryInjectItems();
    }, 500);

    // Also intercept clicks on + buttons to trigger rapid injection
    document.addEventListener('click', function(e) {
      var btn = e.target.closest('button');
      if (btn) {
        var text = btn.textContent.trim();
        // If clicked button looks like the + button (empty or just "+")
        if (text === '+' || text === '' || btn.querySelector('svg')) {
          // Rapid-fire injection attempts after click
          setTimeout(tryInjectItems, 50);
          setTimeout(tryInjectItems, 150);
          setTimeout(tryInjectItems, 300);
          setTimeout(tryInjectItems, 600);
        }
      }
    }, true);
  }

  // ========== Init ==========

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectMenuItems);
  } else {
    injectMenuItems();
  }

  // ========== Auto Gmail Action Watcher ==========
  // Watches for new messages in the chat and auto-creates drafts when user asks

  function setupGmailWatcher() {
    // Disabled: this auto-send watcher popped a "Review Email Before Sending"
    // modal and called gmail_create_draft_reply (422) whenever a message
    // mentioned sending/emailing. Connecting is now a clean inline button
    // (see linkifyConnectButtons); drafting goes through the draft_email tool.
    return;
    var lastMsgCount = 0;
    var processing = false;

    // Watch for new messages appearing in the DOM
    var observer = new MutationObserver(function() {
      if (processing) return;

      // Count current messages
      var userMsgs = document.querySelectorAll('[class*="prose"]');
      if (userMsgs.length <= lastMsgCount) return;
      lastMsgCount = userMsgs.length;

      // Get the stored email ID (may be null for new emails)
      var emailId = window._aiuiLastAttachedEmailId;

      // Find the latest user message text from the page
      var allText = document.body.innerText || '';

      // Check for draft or send keywords
      var draftKeywords = ['create a draft', 'draft reply', 'draft a reply', 'make a draft', 'write a draft', 'create draft', 'draft for this'];
      var sendKeywords = ['send email', 'send a reply', 'send reply', 'send this email', 'send to', 'email to', 'send a message'];
      var hasDraftIntent = false;
      var hasSendIntent = false;
      var userIntent = '';

      var textBlocks = allText.split('\n').filter(function(l) { return l.trim().length > 5; });
      var recentText = textBlocks.slice(-20).join(' ').toLowerCase();

      for (var i = 0; i < draftKeywords.length; i++) {
        if (recentText.indexOf(draftKeywords[i]) > -1) {
          hasDraftIntent = true;
          for (var j = textBlocks.length - 1; j >= Math.max(0, textBlocks.length - 10); j--) {
            var line = textBlocks[j].toLowerCase();
            if (draftKeywords.some(function(kw) { return line.indexOf(kw) > -1; })) {
              userIntent = textBlocks[j];
              break;
            }
          }
          break;
        }
      }

      if (!hasDraftIntent) {
        for (var i = 0; i < sendKeywords.length; i++) {
          if (recentText.indexOf(sendKeywords[i]) > -1) {
            hasSendIntent = true;
            for (var j = textBlocks.length - 1; j >= Math.max(0, textBlocks.length - 10); j--) {
              var line = textBlocks[j].toLowerCase();
              if (sendKeywords.some(function(kw) { return line.indexOf(kw) > -1; })) {
                userIntent = textBlocks[j];
                break;
              }
            }
            break;
          }
        }
      }

      if (!hasDraftIntent && !hasSendIntent) return;

      // Draft requires an attached email
      if (hasDraftIntent && !emailId) return;

      // Check if we already processed this
      var processKey = (emailId || 'new') + '_' + lastMsgCount;
      if (window._aiuiLastProcessed === processKey) return;
      window._aiuiLastProcessed = processKey;

      processing = true;
      if (hasSendIntent) {
        // For send, extract email address from the page text
        var targetEmail = '';
        var emailMatch = recentText.match(/[\w.-]+@[\w.-]+\.\w+/);
        if (emailMatch) targetEmail = emailMatch[0];

        if (!targetEmail) { processing = false; return; }

        autoNewEmailWithConfirmation(targetEmail, userIntent, emailId);
      } else {
        autoCreateDraft(emailId, userIntent);
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  function autoCreateDraft(emailId, userIntent) {
    var userEmail = getEffectiveEmail();
    showNotification('Reading email and creating draft...');

    // Step 1: Read the email
    fetch(GMAIL_API + '/gmail_read_email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-User-Email': userEmail },
      body: JSON.stringify({ message_id: emailId })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) { showNotification('Gmail error: ' + data.error, true); return; }

      showNotification('Generating reply...');
      var emailBody = data.body || data.snippet || '';
      var subject = data.subject || '';
      var from = data.from || '';

      // Step 2: Generate reply with AI
      var token = getWebUIToken();
      return fetch('/api/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': token ? 'Bearer ' + token : '' },
        body: JSON.stringify({
          model: 'gpt-4o-mini',
          messages: [
            { role: 'system', content: 'Write a professional email reply in proper email format. Include:\n- A greeting (Dear/Hi [Name])\n- The reply body\n- A professional closing (Best regards, Kind regards, etc.)\n- The sender name\n\nOnly output the email body, no Subject line or headers. Keep it professional and well-formatted.' },
            { role: 'user', content: (userIntent ? 'Write a reply with this intent: "' + userIntent + '"\n\n' : 'Write a professional reply:\n\n') + 'From: ' + from + '\nSubject: ' + subject + '\n\n' + emailBody.substring(0, 3000) }
          ],
          stream: false,
          max_tokens: 500
        })
      });
    })
    .then(function(r) { if (r) return r.json(); })
    .then(function(aiResp) {
      if (!aiResp) return;
      var replyBody = (aiResp.choices && aiResp.choices[0]) ? aiResp.choices[0].message.content : 'Thank you for your email. I will review and respond shortly.';

      showNotification('Saving draft to Gmail...');

      // Step 3: Create draft in actual Gmail
      return fetch(GMAIL_API + '/gmail_create_draft_reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-Email': userEmail },
        body: JSON.stringify({ message_id: emailId, body: replyBody })
      })
      .then(function(r) { return r.json(); })
      .then(function(result) {
        if (result.success) {
          showNotification('Draft saved to Gmail! Re: ' + (result.subject || '') + '. Check Gmail Drafts', false, true);
          // Clear the stored email ID so we don't double-process
          window._aiuiLastAttachedEmailId = null;
        } else {
          showNotification('Failed: ' + (result.error || result.detail || 'Unknown error'), true);
        }
      });
    })
    .catch(function(err) {
      showNotification('Error: ' + err.message, true);
    });
  }

  function autoNewEmailWithConfirmation(targetEmail, userIntent, emailId) {
    var userEmail = getEffectiveEmail();
    showNotification('Preparing email...');

    // Extract the message content from user intent (text after the email address)
    var msgBody = userIntent || '';
    var afterEmail = msgBody.split(targetEmail);
    var rawBody = afterEmail.length > 1 ? afterEmail[1].trim() : msgBody.replace(/send\s*(email|message|a message|a reply)?\s*(to)?\s*/i, '').replace(targetEmail, '').trim();

    if (!rawBody) rawBody = 'Hello';

    // Generate a formatted email with AI
    var token = getWebUIToken();
    fetch('/api/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': token ? 'Bearer ' + token : '' },
      body: JSON.stringify({
        model: 'gpt-4o-mini',
        messages: [
          { role: 'system', content: 'Write a professional email in proper format. Include a greeting, the message body, and a professional closing with sender name. Only output the email body, no Subject line or To/From headers.' },
          { role: 'user', content: 'Write an email with this intent: "' + rawBody + '"' }
        ],
        stream: false,
        max_tokens: 500
      })
    })
    .then(function(r) { return r.json(); })
    .then(function(aiResp) {
      var formattedBody = (aiResp && aiResp.choices && aiResp.choices[0]) ? aiResp.choices[0].message.content : rawBody;

      // Determine subject from intent
      var subject = 'Message from AIUI';
      if (rawBody.length < 50) {
        subject = rawBody.charAt(0).toUpperCase() + rawBody.slice(1);
      }

      // Show confirmation popup
      showSendConfirmation(emailId, targetEmail, subject, formattedBody, userEmail);
    })
    .catch(function(err) {
      showNotification('Error: ' + err.message, true);
    });
  }

  function autoSendWithConfirmation(emailId, userIntent) {
    var userEmail = getEffectiveEmail();
    showNotification('Reading email and preparing reply...');

    // Extract target email from userIntent (e.g. "send to bob@email.com")
    var targetEmail = '';
    var emailMatch = userIntent.match(/[\w.-]+@[\w.-]+\.\w+/);
    if (emailMatch) targetEmail = emailMatch[0];

    // Step 1: Read the email
    fetch(GMAIL_API + '/gmail_read_email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-User-Email': userEmail },
      body: JSON.stringify({ message_id: emailId })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) { showNotification('Gmail error: ' + data.error, true); return; }

      var emailBody = data.body || data.snippet || '';
      var subject = data.subject || '';
      var from = data.from || '';
      if (!targetEmail) {
        // Reply to the sender
        var fromMatch = from.match(/[\w.-]+@[\w.-]+\.\w+/);
        if (fromMatch) targetEmail = fromMatch[0];
      }

      showNotification('Generating reply...');

      // Step 2: Generate reply with AI
      var token = getWebUIToken();
      return fetch('/api/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': token ? 'Bearer ' + token : '' },
        body: JSON.stringify({
          model: 'gpt-4o-mini',
          messages: [
            { role: 'system', content: 'Write a professional email reply in proper email format. Include a greeting, reply body, and closing with sender name. No Subject line or headers.' },
            { role: 'user', content: (userIntent ? 'Write a reply with this intent: "' + userIntent + '"\n\n' : 'Write a professional reply:\n\n') + 'From: ' + from + '\nSubject: ' + subject + '\n\n' + emailBody.substring(0, 3000) }
          ],
          stream: false,
          max_tokens: 500
        })
      })
      .then(function(r) { return r.json(); })
      .then(function(aiResp) {
        var replyBody = (aiResp && aiResp.choices && aiResp.choices[0]) ? aiResp.choices[0].message.content : 'Thank you for your email. I will review and respond shortly.\n\nBest regards';

        // Step 3: Show confirmation dialog
        showSendConfirmation(emailId, targetEmail, subject, replyBody, userEmail);
      });
    })
    .catch(function(err) {
      showNotification('Error: ' + err.message, true);
    });
  }

  function showSendConfirmation(emailId, to, subject, body, userEmail) {
    // Remove any existing notification
    var existing = document.getElementById('aiui-notify');
    if (existing) existing.remove();

    var replySubject = subject.toLowerCase().startsWith('re:') ? subject : 'Re: ' + subject;

    var overlay = document.createElement('div');
    overlay.id = 'aiui-send-confirm';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10001;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';

    var modal = document.createElement('div');
    modal.style.cssText = 'background:#1e1e1e;border-radius:16px;padding:24px;max-width:550px;width:90%;box-shadow:0 25px 50px rgba(0,0,0,0.5);';

    modal.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">' +
      '<h3 style="color:#fff;margin:0;font-size:18px;">Review Email Before Sending</h3>' +
      '<button id="aiui-confirm-close" style="background:none;border:none;color:#888;font-size:20px;cursor:pointer;">&times;</button>' +
      '</div>' +
      '<div style="margin-bottom:12px;">' +
        '<div style="color:#888;font-size:12px;margin-bottom:4px;">To</div>' +
        '<div style="color:#fff;font-size:14px;">' + to + '</div>' +
      '</div>' +
      '<div style="margin-bottom:12px;">' +
        '<div style="color:#888;font-size:12px;margin-bottom:4px;">Subject</div>' +
        '<div style="color:#fff;font-size:14px;">' + replySubject + '</div>' +
      '</div>' +
      '<div style="margin-bottom:16px;">' +
        '<div style="color:#888;font-size:12px;margin-bottom:4px;">Message (edit before sending)</div>' +
        '<textarea id="aiui-confirm-body" style="width:100%;background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:12px;color:#ccc;font-size:14px;min-height:180px;resize:vertical;outline:none;box-sizing:border-box;font-family:inherit;line-height:1.5;">' + body.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</textarea>' +
      '</div>' +
      '<div style="display:flex;gap:8px;">' +
        '<button id="aiui-confirm-send" style="flex:1;background:#ea4335;border:none;border-radius:8px;color:#fff;padding:12px;font-size:14px;cursor:pointer;font-weight:600;">Send Now</button>' +
        '<button id="aiui-confirm-draft" style="flex:1;background:#2a2a2a;border:1px solid #444;border-radius:8px;color:#fff;padding:12px;font-size:14px;cursor:pointer;">Save as Draft Instead</button>' +
        '<button id="aiui-confirm-cancel" style="background:transparent;border:1px solid #333;border-radius:8px;color:#888;padding:12px 16px;font-size:14px;cursor:pointer;">Cancel</button>' +
      '</div>';

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Close
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
    modal.querySelector('#aiui-confirm-close').addEventListener('click', function() { overlay.remove(); });
    modal.querySelector('#aiui-confirm-cancel').addEventListener('click', function() { overlay.remove(); });

    // Send Now
    modal.querySelector('#aiui-confirm-send').addEventListener('click', function() {
      var editedBody = modal.querySelector('#aiui-confirm-body').value;
      overlay.remove();
      showNotification('Sending email...');
      fetch(GMAIL_API + '/gmail_send_email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-Email': userEmail },
        body: JSON.stringify({ to: to, subject: replySubject, body: editedBody, reply_to_message_id: emailId })
      })
      .then(function(r) { return r.json(); })
      .then(function(result) {
        if (result.success) {
          showNotification('Email sent to ' + to + '!', false, true);
          window._aiuiLastAttachedEmailId = null;
        } else {
          showNotification('Failed to send: ' + (result.error || 'Unknown error'), true);
        }
      });
    });

    // Save as Draft Instead
    modal.querySelector('#aiui-confirm-draft').addEventListener('click', function() {
      var editedBody = modal.querySelector('#aiui-confirm-body').value;
      overlay.remove();
      showNotification('Saving draft to Gmail...');
      fetch(GMAIL_API + '/gmail_create_draft_reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-Email': userEmail },
        body: JSON.stringify({ message_id: emailId, body: editedBody })
      })
      .then(function(r) { return r.json(); })
      .then(function(result) {
        if (result.success) {
          showNotification('Draft saved! Check Gmail Drafts.', false, true);
          window._aiuiLastAttachedEmailId = null;
        } else {
          showNotification('Failed: ' + (result.error || 'Unknown error'), true);
        }
      });
    });
  }

  function showNotification(msg, isError, isPersistent) {
    var existing = document.getElementById('aiui-notify');
    if (existing) existing.remove();

    var el = document.createElement('div');
    el.id = 'aiui-notify';
    el.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);z-index:10000;' +
      'background:' + (isError ? '#dc3545' : '#1a1a2e') + ';' +
      'border:1px solid ' + (isError ? '#dc3545' : '#4a9eff') + ';' +
      'border-radius:12px;padding:14px 24px;color:#fff;font-size:14px;' +
      'box-shadow:0 8px 30px rgba(0,0,0,0.4);max-width:500px;white-space:pre-wrap;';
    el.textContent = msg;
    document.body.appendChild(el);

    if (!isPersistent) {
      setTimeout(function() { if (el.parentElement) el.remove(); }, 4000);
    } else {
      var btn = document.createElement('button');
      btn.textContent = '\u00d7';
      btn.style.cssText = 'position:absolute;top:4px;right:8px;background:none;border:none;color:#888;font-size:18px;cursor:pointer;';
      btn.addEventListener('click', function() { el.remove(); });
      el.style.paddingRight = '30px';
      el.appendChild(btn);
    }
  }

  setupGmailWatcher();

  // ===== In-chat Connect card =====
  // When the user sends a message about email / Drive and their Google account
  // isn't linked, inject a Connect card with a button right into the chat so
  // it's impossible to miss. Frontend-only, so it renders reliably (unlike an
  // outlet filter, whose injected content OWUI won't re-render live).
  function buildChatConnectCard(service, email) {
    var api = service === 'gdrive' ? GDRIVE_API : GMAIL_API;
    var icon = service === 'gdrive' ? GDRIVE_ICON_BIG : GMAIL_ICON_BIG;
    var title = service === 'gdrive' ? 'Connect your Google Drive' : 'Connect your Gmail';
    var label = service === 'gdrive' ? 'Connect Google Drive' : 'Connect Gmail';
    var url = api + '/auth/google/link';
    var card = document.createElement('div');
    card.id = 'aiui-chat-connect-card';
    card.setAttribute('data-service', service);
    card.style.cssText = 'max-width:760px;margin:10px auto;padding:16px 18px;' +
      'background:linear-gradient(135deg,#1e3a5f,#2d5a87);border-radius:14px;color:#fff;' +
      'box-shadow:0 8px 24px rgba(0,0,0,0.35);font-family:inherit;';
    card.innerHTML =
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">' + icon +
      '<span style="font-size:16px;font-weight:600;">' + title + '</span></div>' +
      '<div style="opacity:0.9;margin-bottom:12px;font-size:14px;line-height:1.4;">' +
      'Link your Google account so I can do this for you in chat. Drafts are saved to ' +
      'your Gmail Drafts, nothing is sent automatically.</div>' +
      '<button id="aiui-chat-connect-btn" style="padding:12px 22px;background:#4CAF50;' +
      'color:#fff;border:none;border-radius:8px;font-weight:bold;font-size:14px;cursor:pointer;">' +
      label + '</button>' +
      '<button id="aiui-chat-connect-dismiss" style="margin-left:10px;padding:12px 16px;' +
      'background:transparent;color:#cfe0f5;border:1px solid rgba(255,255,255,0.25);' +
      'border-radius:8px;font-size:13px;cursor:pointer;">Not now</button>';
    card.querySelector('#aiui-chat-connect-btn').addEventListener('click', function() {
      // Same-tab redirect (most inline). Google blocks embedding their login,
      // so we navigate this tab to Google and it returns to the chat after.
      try { localStorage.setItem('aiui-return-url', window.location.href); } catch (e) {}
      window.location.href = url;
    });
    card.querySelector('#aiui-chat-connect-dismiss').addEventListener('click', function() {
      card.remove();
    });
    return card;
  }

  function removeChatConnectCard() {
    var c = document.getElementById('aiui-chat-connect-card');
    if (c) c.remove();
  }

  function showChatConnectCard(service) {
    removeChatConnectCard();
    var card = buildChatConnectCard(service, getEffectiveEmail());
    var ta = document.querySelector('textarea');
    var form = ta ? ta.closest('form') : null;
    if (form && form.parentElement) {
      form.parentElement.insertBefore(card, form);
    } else if (ta && ta.parentElement) {
      ta.parentElement.insertBefore(card, ta);
    } else {
      // Last resort: pin above the viewport bottom so it's still visible.
      card.style.position = 'fixed';
      card.style.left = '50%';
      card.style.bottom = '120px';
      card.style.transform = 'translateX(-50%)';
      card.style.zIndex = '9999';
      document.body.appendChild(card);
    }
  }

  function detectConnectService(text) {
    var low = (text || '').toLowerCase();
    if (/(google drive|gdrive|my drive|save to drive|to my drive|drive folder)/.test(low)) return 'gdrive';
    if (/(gmail|e-?mail|inbox|compose an email|draft an email|send an email|draft.*email|email .*@)/.test(low)) return 'gmail';
    return null;
  }

  function maybePromptConnect(text) {
    var service = detectConnectService(text);
    console.log('[AIUI] chatcard: send detected, text=', (text || '').slice(0, 60), 'service=', service);
    if (!service) return;
    var email = getEffectiveEmail();
    var api = service === 'gdrive' ? GDRIVE_API : GMAIL_API;
    fetch(api + '/auth/google/status?user_email=' + encodeURIComponent(email))
      .then(function(r) { return r.json(); })
      .then(function(d) {
        var connected = !!(d && d.connected === true);
        console.log('[AIUI] chatcard: status for', email, '=', connected, '- showing card:', !connected);
        if (!connected) showChatConnectCard(service);
      })
      .catch(function(err) {
        console.log('[AIUI] chatcard: status check failed, showing card anyway', err);
        showChatConnectCard(service);
      });
  }

  // Find the message composer textarea specifically (not a draft/edit box).
  function getComposerTextarea() {
    var tas = document.querySelectorAll('textarea');
    for (var i = 0; i < tas.length; i++) {
      var ph = (tas[i].getAttribute('placeholder') || '').toLowerCase();
      if (ph.indexOf('message') !== -1 || ph.indexOf('send a') !== -1) return tas[i];
    }
    return tas.length ? tas[tas.length - 1] : null;  // composer is usually last
  }

  function readLastUserMessage(bodyStr) {
    try {
      var data = JSON.parse(bodyStr);
      var msgs = (data && data.messages) || [];
      for (var i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i] && msgs[i].role === 'user') {
          var c = msgs[i].content;
          if (typeof c === 'string') return c;
          if (Array.isArray(c)) {
            return c.map(function(p) { return (p && p.text) || ''; }).join(' ');
          }
          return '';
        }
      }
    } catch (e) {}
    return '';
  }

  function setupChatConnectWatcher() {
    // Disabled: this keyword watcher fired maybePromptConnect whenever a
    // message merely contained a word like email or inbox, popping a card
    // even when the person had no intent to connect anything. The My
    // Account tool replaced it: the model decides deliberately and prints
    // an #aiui-connect: link, which wireAiuiConnectLinks turns into a
    // button.
    return;
    // Robust detection: read the ACTUAL user message from the outgoing chat
    // request, not from a textarea (which can hold a draft/edit box's text).
    var _origFetch = window.fetch;
    window.fetch = function(input, init) {
      try {
        var url = (typeof input === 'string') ? input : (input && input.url) || '';
        var body = init && init.body;
        if (url.indexOf('/api/chat/completions') !== -1 && typeof body === 'string') {
          var txt = readLastUserMessage(body);
          if (txt) setTimeout(function() { maybePromptConnect(txt); }, 200);
        }
      } catch (e) {}
      return _origFetch.apply(this, arguments);
    };
    // Also patch XHR in case a code path uses it instead of fetch.
    var _origSend = XMLHttpRequest.prototype.send;
    var _origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
      this.__aiui_url = url || '';
      return _origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body) {
      try {
        if (this.__aiui_url && this.__aiui_url.indexOf('/api/chat/completions') !== -1 &&
            typeof body === 'string') {
          var txt = readLastUserMessage(body);
          if (txt) setTimeout(function() { maybePromptConnect(txt); }, 200);
        }
      } catch (e) {}
      return _origSend.apply(this, arguments);
    };
    // Remove the card once the account gets connected.
    window.addEventListener('message', function(e) {
      if (e.data && typeof e.data.type === 'string' &&
          e.data.type.indexOf('connected') !== -1) {
        removeChatConnectCard();
      }
    });
  }

  setupChatConnectWatcher();

  // Turn the plain connect URL the model prints (".../auth/google/link...")
  // into a clean, clickable inline button. The older ".../start?user_email="
  // form is matched too, so a connect line in an old conversation still works;
  // the button it builds points at the link endpoint either way.
  // Robust: reads the rendered message,
  // no textareas, no dependence on catching the send. Same-tab redirect.
  function _renderConnectState(container, service, url, email, connected) {
    container.innerHTML = '';
    var api = service === 'gdrive' ? GDRIVE_API : (service === 'calendar' ? CALENDAR_API : GMAIL_API);
    var icon = service === 'gdrive' ? GDRIVE_ICON_SMALL : (service === 'calendar' ? CALENDAR_ICON_SMALL : GMAIL_ICON_SMALL);
    var name = service === 'gdrive' ? 'Google Drive' : (service === 'calendar' ? 'Google Calendar' : 'Gmail');
    if (!connected) {
      // Unified connect: one consent links Gmail + Calendar + Drive. Whatever
      // service prompted this, send the user through the single Google flow.
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.style.cssText = 'display:inline-flex;align-items:center;gap:8px;margin:8px 0;' +
        'padding:11px 20px;background:#4CAF50;color:#fff;border:none;border-radius:10px;' +
        'font-weight:600;font-size:14px;cursor:pointer;box-shadow:0 3px 10px rgba(0,0,0,0.25);';
      btn.innerHTML = icon + '<span>Connect Google</span>';
      btn.addEventListener('click', function () {
        try { localStorage.setItem('aiui-return-url', window.location.href); } catch (e) {}
        window.location.href = GMAIL_API + '/auth/google/link?connect=all';
      });
      container.appendChild(btn);
      var note = document.createElement('div');
      note.style.cssText = 'font-size:12px;opacity:0.7;margin-top:6px;';
      note.textContent = 'Links Gmail, Calendar, and Drive in one step.';
      container.appendChild(note);
    } else {
      var chip = document.createElement('span');
      chip.style.cssText = 'display:inline-flex;align-items:center;gap:8px;margin:8px 8px 8px 0;' +
        'padding:9px 16px;background:rgba(76,175,80,0.15);color:#4CAF50;border:1px solid #4CAF50;' +
        'border-radius:10px;font-weight:600;font-size:14px;';
      chip.innerHTML = icon + '<span>' + name + ' connected</span>';
      var dbtn = document.createElement('button');
      dbtn.type = 'button';
      dbtn.style.cssText = 'display:inline-flex;align-items:center;margin:8px 0;padding:9px 16px;' +
        'background:transparent;color:#e57373;border:1px solid #e57373;border-radius:10px;' +
        'font-weight:600;font-size:13px;cursor:pointer;';
      dbtn.textContent = 'Disconnect';
      dbtn.addEventListener('click', function () {
        dbtn.disabled = true; dbtn.textContent = 'Disconnecting...';
        fetch(api + '/auth/google/disconnect?user_email=' + encodeURIComponent(email), { method: 'POST' })
          .then(function () { _renderConnectState(container, service, url, email, false); })
          .catch(function () { dbtn.disabled = false; dbtn.textContent = 'Disconnect'; });
      });
      container.appendChild(chip);
      container.appendChild(dbtn);
    }
  }

  function styleConnectButton(anchor) {
    if (!anchor) return;
    var url = anchor.href || '';
    if (url.indexOf('/auth/google/') === -1) return;
    var service = url.indexOf('/gdrive/') !== -1 ? 'gdrive'
      : (url.indexOf('/calendar/') !== -1 ? 'calendar' : 'gmail');
    var api = service === 'gdrive' ? GDRIVE_API : (service === 'calendar' ? CALENDAR_API : GMAIL_API);
    var email = getEffectiveEmail();
    var container = document.createElement('span');
    container.className = 'aiui-connect-inline';
    if (anchor.parentNode) anchor.parentNode.replaceChild(container, anchor);
    // Show Connect immediately, then flip to connected/disconnect if the
    // server says this user is already linked.
    _renderConnectState(container, service, url, email, false);
    fetch(api + '/auth/google/status?user_email=' + encodeURIComponent(email))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.connected === true) _renderConnectState(container, service, url, email, true);
      })
      .catch(function () {});
  }

  // ===== The assistant's connect links =====
  // The My Account tool prints [Connect Gmail](#aiui-connect:gmail). This
  // finds those and turns them into buttons.
  //
  // Popup first, because that is the flow somebody actually wants: one
  // click and the vendor's login opens. Chrome blocks a window.open that no
  // click triggered, and a blocked call returns null, so we can tell and
  // say so. Once the person allows popups for this site the block is gone
  // for good and later connects open with no fuss.
  //
  // Panel second, so that somebody who never allows popups is never stuck.
  //
  // The login itself is always theirs. We open the door.
  var AIUI_CONNECT_MARKER = '#aiui-connect:';

  function aiuiConnectUrlFor(provider) {
    // Only the Google apps have a URL that is ready to open immediately.
    // Notion is OAuth too (see _can_log_in in account_summary.py) but
    // its start URL has to be fetched from our own API first, so it is
    // handled separately in the click handler below, not here. Anything
    // else is a key-paste app with no login to open at all.
    if (provider === 'gmail') return GMAIL_API + '/auth/google/link';
    if (provider === 'gdrive') return GDRIVE_API + '/auth/google/link';
    if (provider === 'calendar') return CALENDAR_API + '/auth/google/link';
    return null;
  }

  function aiuiAuthHeaders() {
    // Mirrors authHeaders() inside createIntegrationsModal above, which is
    // out of reach from here: that copy is scoped inside a different
    // top-level function, not on window.
    var t = localStorage.getItem('token');
    var h = { 'Content-Type': 'application/json' };
    if (t) h['Authorization'] = 'Bearer ' + t;
    return h;
  }

  // Ask a browser to draw a glyph as TEXT rather than as an emoji.
  //
  // U+270E (the pencil) and U+2197 (the open-in-a-tab arrow) both have an
  // emoji presentation a browser is free to prefer, and one did: the
  // pencil came out orange beside five monochrome glyphs (2026-11-12,
  // Ralph: "change the icon for pencil because it colorful and the other
  // icon isnt... or fix all").
  //
  // U+FE0E is the variation selector that asks for text. It changes
  // nothing for a character with no emoji form, which is why it goes on
  // all of them rather than on the two that misbehave today: the next
  // glyph somebody adds is covered without anybody remembering this.
  function aiuiGlyph(ch) {
    return String(ch || '') + '\ufe0e';
  }

  function aiuiPopupBlocked(win) {
    // A blocked window.open returns null in Chrome; some browsers return a
    // window that is immediately closed.
    return !win || win.closed || typeof win.closed === 'undefined';
  }

  function aiuiSayBlocked(container) {
    var note = document.createElement('div');
    note.className = 'aiui-connect-note';
    note.style.cssText = 'margin-top:6px;font-size:12.5px;color:#c8c8c8;';
    note.textContent = 'Your browser blocked that window, so I opened the '
      + 'Connections panel instead. Click the blocked icon in your address '
      + 'bar and choose to always allow popups here, and these will open '
      + 'directly next time.';
    if (!container.querySelector('.aiui-connect-note')) container.appendChild(note);
  }

  function wireAiuiConnectLink(anchor) {
    if (!anchor || anchor.getAttribute('data-aiui-wired')) return;
    var href = anchor.getAttribute('href') || '';
    var i = href.indexOf(AIUI_CONNECT_MARKER);
    if (i === -1) return;
    var provider = href.slice(i + AIUI_CONNECT_MARKER.length).trim();
    if (!provider) return;
    anchor.setAttribute('data-aiui-wired', '1');

    var container = document.createElement('span');
    container.className = 'aiui-connect-inline';
    // Room around each button: two in a row had nothing between them, and
    // the last one sat against the reply's toolbar (2026-11-12).
    container.style.cssText = 'display:inline-block;margin:10px 8px 8px 0;'
      + 'vertical-align:middle;';
    var btn = document.createElement('button');
    btn.textContent = anchor.textContent || ('Connect ' + provider);
    btn.style.cssText = 'padding:8px 16px;background:#4CAF50;color:#fff;border:none;'
      + 'border-radius:8px;font-size:13.5px;font-weight:600;cursor:pointer;';
    container.appendChild(btn);
    if (anchor.parentNode) anchor.parentNode.replaceChild(container, anchor);

    btn.addEventListener('click', function () {
      // Three cases. A Google app has a direct URL and opens immediately.
      // Notion needs its start URL fetched from our API, so the window is
      // opened synchronously right here and navigated once the URL
      // arrives, because a window opened after an await has lost the
      // click that justified it and gets blocked. Anything else has no
      // login to open at all, so it goes straight to the panel.
      var url = aiuiConnectUrlFor(provider);
      if (url) {
        var win = window.open(url, '_blank');
        if (aiuiPopupBlocked(win)) {
          aiuiSayBlocked(container);
          window.aiuiOpenConnections();
        }
        return;
      }

      if (provider === 'notion') {
        // Notion's connect URL has to be fetched, but a window opened
        // after an await has lost the click that justified it and gets
        // blocked. So open synchronously first and navigate it once the
        // URL arrives.
        var notionWin = window.open('', '_blank');
        if (aiuiPopupBlocked(notionWin)) {
          aiuiSayBlocked(container);
          window.aiuiOpenConnections();
          return;
        }
        fetch('/api/tasks/connections/' + encodeURIComponent(provider) + '/oauth/start',
              { headers: aiuiAuthHeaders() })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d && d.url) { notionWin.location = d.url; }
            else { notionWin.close(); window.aiuiOpenConnections(); }
          })
          .catch(function () { notionWin.close(); window.aiuiOpenConnections(); });
        return;
      }

      // A key-paste app. There is no vendor login to open, so the panel
      // is the whole flow rather than a fallback.
      window.aiuiOpenConnections();
    });
  }

  function wireAiuiConnectLinks() {
    var pending = false;
    function scan() {
      pending = false;
      var anchors = document.querySelectorAll('a[href*="' + AIUI_CONNECT_MARKER + '"]');
      for (var i = 0; i < anchors.length; i++) wireAiuiConnectLink(anchors[i]);
    }
    var obs = new MutationObserver(function () {
      if (pending) return;
      pending = true;
      setTimeout(scan, 200);
    });
    obs.observe(document.body, { childList: true, subtree: true });
    scan();
  }

  function linkifyConnectButtons() {
    var pending = false;
    function scan() {
      pending = false;
      var anchors = document.querySelectorAll('a[href*="/auth/google/"]');
      for (var i = 0; i < anchors.length; i++) styleConnectButton(anchors[i]);
    }
    var obs = new MutationObserver(function() {
      if (pending) return;
      pending = true;
      setTimeout(scan, 200);
    });
    obs.observe(document.body, { childList: true, subtree: true });
    scan();
  }

  // ===== Agent name in the reply header =====
  // Open WebUI headers every assistant reply with the MODEL name
  // (#response-message-model-name), and our own code puts the agent's
  // name as plain text at the top of the body instead ("Mia:" then the
  // reply). The name someone actually asked for ends up buried in the
  // body while the header shows a model id nobody asked about.
  //
  // This rewrites the header span to the name of whichever agent
  // answered, or to both names when two of them did, and removes the
  // now redundant name line from the body when only one spoke.
  //
  // Structural, not class based: Tailwind classes move between Open
  // WebUI versions, an id does not. The span sits inside a Name
  // wrapper; the body is a sibling div whose class starts with
  // "chat-". Walking up from the span and checking immediate siblings
  // at each level finds that div without assuming how deep the Name
  // wrapper is, or what it is called.
  //
  // A bare name and a colon, nothing else on the line: letters,
  // digits, spaces or hyphens, at most 40 characters, anchored at the
  // start. That shape alone cannot tell "Mia:" from a reply that
  // genuinely opens with "Note:", "Warning:" or "TODO:" on its own
  // line, so the shape match is only ever a candidate: it gates the
  // rewrite only when the name is also one of this signed in person's
  // real agents (see aiuiAgentNames below). An empty or unfetched set
  // of names means no rewrite ever happens, on purpose: leaving a
  // message untouched costs nothing, and a wrong rewrite would
  // silently change what somebody reads.
  //
  // #response-message-model-name is only ever rendered for an
  // assistant reply, so this never touches a message the user typed.
  var AIUI_AGENT_NAME_LINE_RE = /^([A-Za-z0-9 -]{1,40}):\r?\n/;
  var AIUI_AGENT_NAME_BARE_RE = /^([A-Za-z0-9 -]{1,40}):$/;

  function aiuiIsBareName(name) {
    return !!name && name === name.replace(/^\s+|\s+$/g, '');
  }

  // ----- Known agent names -----
  // agents.html lists a person's agents the same way: fetch
  // /api/v1/models/list (paged, because a person can own more than
  // one page of them), keep only rows whose id this platform minted
  // ("agent-..."), and read the display name off .name. Auth reuses
  // aiuiAuthHeaders(), already defined above for the connect flow.
  //
  // Fetched once up front, then re-fetched at most every couple of
  // minutes and only when something the header code saw did not
  // match any known name, so a whole conversation full of "Note:"
  // lines costs one request rather than one per message. A failure
  // here never throws and never clears a list that was already
  // fetched successfully; it just leaves things as they are.
  var AIUI_AGENT_NAMES_TTL_MS = 120000;
  var aiuiAgentNames = new Set();
  var aiuiAgentNameById = {};
  var aiuiAgentNamesFetchedAt = 0;
  var aiuiAgentNamesFetching = false;

  function aiuiIsMintedAgent(item) {
    return !!(item && /^agent-/.test(item.id || ''));
  }

  function aiuiFetchAgentNamesPage(pageNo, items, total, guard) {
    if (guard > 25) return Promise.resolve(items);
    return fetch('/api/v1/models/list?page=' + pageNo, { headers: aiuiAuthHeaders() })
      .then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      })
      .then(function (listed) {
        var batch = (listed && Array.isArray(listed.items)) ? listed.items : [];
        var newTotal = (listed && typeof listed.total === 'number') ? listed.total : batch.length;
        var all = items.concat(batch);
        if (!batch.length || all.length >= newTotal) return all;
        return aiuiFetchAgentNamesPage(pageNo + 1, all, newTotal, guard + 1);
      });
  }

  function aiuiRefreshAgentNames() {
    var now = Date.now();
    if (aiuiAgentNamesFetching) return;
    if (aiuiAgentNamesFetchedAt && (now - aiuiAgentNamesFetchedAt) < AIUI_AGENT_NAMES_TTL_MS) return;
    aiuiAgentNamesFetching = true;
    aiuiAgentNamesFetchedAt = now;
    aiuiFetchAgentNamesPage(1, [], 0, 0)
      .then(function (items) {
        var names = new Set();
        var byId = {};
        for (var i = 0; i < items.length; i++) {
          if (aiuiIsMintedAgent(items[i]) && items[i].name) {
            names.add(String(items[i].name).trim().toLowerCase());
            byId[items[i].id] = String(items[i].name).trim();
          }
        }
        aiuiAgentNames = names;
        aiuiAgentNameById = byId;
        aiuiAgentNamesFetching = false;
        // The refresh itself can be what makes a message match for
        // the first time, an agent created mid conversation. Give the
        // observer one more pass now rather than waiting on an
        // unrelated mutation to trigger the next one.
        aiuiScanAgentNameHeaders();
      })
      .catch(function () {
        aiuiAgentNamesFetching = false;
        // Leave whatever names are already known, possibly none if
        // this was the very first attempt. A failed refresh must
        // never wipe out a previously good list, and must never
        // throw.
      });
  }

  function aiuiNameIsKnownAgent(name) {
    return aiuiAgentNames.has(String(name).toLowerCase());
  }

  // Two shapes, because Open WebUI changed the reply body between
  // versions. Older builds gave it a class starting "chat-", which is what
  // the first pass looks for. Newer builds (seen live 2026-09-04) render it
  // as a div with NO class at all, the next sibling of the wrapper that
  // holds the name. So the second pass is structural: walking up from the
  // name, the first following sibling that is a div with real text in it,
  // and that does not itself hold a reply header, is the body. Reading
  // order is what makes "following" safe: the name always precedes its
  // own body and never precedes a neighbouring message's.
  function aiuiFindReplyBody(nameSpan) {
    var node = nameSpan;
    for (var depth = 0; depth < 8 && node; depth++) {
      var candidates = [node.previousElementSibling, node.nextElementSibling];
      for (var i = 0; i < candidates.length; i++) {
        var sib = candidates[i];
        if (sib && sib.tagName === 'DIV' && typeof sib.className === 'string') {
          var classes = sib.className.split(/\s+/);
          for (var c = 0; c < classes.length; c++) {
            if (classes[c].indexOf('chat-') === 0) return sib;
          }
        }
      }
      node = node.parentElement;
    }

    node = nameSpan;
    for (var up = 0; up < 8 && node; up++) {
      var next = node.nextElementSibling;
      if (next && next.tagName === 'DIV'
          && (next.textContent || '').trim().length > 0
          && !next.querySelector('#response-message-model-name')) {
        return next;
      }
      node = node.parentElement;
    }
    return null;
  }

  // Only the very first content of the body, following the first-child
  // chain through wrapper elements. This can never land on a later
  // paragraph, only on whatever text opens the message.
  function aiuiFirstTextNode(container) {
    // Svelte scatters comment markers and whitespace-only text through
    // every rendered block, so the plain first-child chain hits a comment
    // and stops before it ever reaches a word. Those are stepped over
    // sideways. Descent is still first-child only, and an element whose
    // children are all markers yields nothing rather than its next
    // sibling, so this still cannot land on a later paragraph.
    var node = container.firstChild;
    for (var steps = 0; node && steps < 48; steps++) {
      var blank = node.nodeType === 3 && !(node.textContent || '').trim();
      if (node.nodeType === 8 || blank) { node = node.nextSibling; continue; }
      if (node.nodeType === 3) return node;
      if (node.nodeType === 1) { node = node.firstChild; continue; }
      return null;
    }
    return null;
  }

  // Every agent label that opens a top-level block of the reply, in
  // order. One request can wake more than one agent, and their answers
  // come back in a single bubble with a label each, so the header has to
  // be able to name all of them. Reading only what OPENS each top-level
  // block keeps this away from two things that would otherwise match:
  // the tool result panel Open WebUI now renders first, whose own text
  // is never an agent name, and anything quoted deeper inside a reply.
  function aiuiAgentLabelsIn(body) {
    var result = { labels: [], sawUnknownName: false, holder: null };
    var seen = {};
    // The body's own children are wrapper divs now, not paragraphs, so a
    // second agent's label sits inside the first wrapper rather than as a
    // sibling of it. Find the element that actually holds the rendered
    // blocks: start from the first real text, walk up until an ancestor
    // has more than one element child, and scan THAT element's children.
    // Falls back to the body itself when the reply is a single block.
    var opening = aiuiFirstTextNode(body);
    var holder = opening ? opening.parentNode : body;
    for (var up = 0; holder && holder !== body && up < 12; up++) {
      if (holder.children && holder.children.length > 1) break;
      holder = holder.parentNode;
    }
    if (!holder) holder = body;
    result.holder = holder;
    var candidates = [body];
    for (var c = 0; c < holder.children.length; c++) candidates.push(holder.children[c]);

    for (var i = 0; i < candidates.length; i++) {
      var textNode = aiuiFirstTextNode(candidates[i]);
      if (!textNode) continue;
      var full = textNode.textContent || '';
      var match = AIUI_AGENT_NAME_LINE_RE.exec(full) || AIUI_AGENT_NAME_BARE_RE.exec(full);
      if (!match || !aiuiIsBareName(match[1])) continue;
      if (!aiuiNameIsKnownAgent(match[1])) { result.sawUnknownName = true; continue; }
      if (seen[match[1]]) continue;
      seen[match[1]] = true;
      result.labels.push({ name: match[1], node: textNode, block: candidates[i] });
    }
    return result;
  }

  // More than one label in one bubble cannot happen for a reply written
  // since first_only shipped, but it is exactly what a bubble stored
  // BEFORE it looks like. Naming only the first would head such a message
  // "Ada" with "Mia:" still sitting in its body.
  function aiuiJoinNames(names) {
    if (names.length < 2) return names[0] || '';
    return names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
  }

  // Removes a name line the header has taken over. Two shapes, because
  // the renderer splits "Name:" and the reply differently depending on
  // whether the blank line after the name survived as a break beside it
  // or as a block of its own.
  function aiuiStripLabel(body, label) {
    var textNode = label.node;
    var full = textNode.textContent || '';

    var lineMatch = AIUI_AGENT_NAME_LINE_RE.exec(full);
    if (lineMatch) {
      textNode.textContent = full.slice(lineMatch[0].length);
      return;
    }

    var nextNode = textNode.nextSibling;
    if (nextNode && nextNode.nodeType === 1 && nextNode.tagName === 'BR') {
      nextNode.parentNode.removeChild(nextNode);
      textNode.parentNode.removeChild(textNode);
      return;
    }
    if (!nextNode && textNode.parentNode && textNode.parentNode !== body
        && textNode.parentNode.parentNode) {
      var block = textNode.parentNode;
      block.parentNode.removeChild(block);
    }
  }

  // A reply arrives a token at a time, so the set of labels can still
  // grow between two scans: "Mia:" is on screen a beat before "Ada:"
  // exists. Removing a label the moment it is the only one would delete
  // it right before it stops being the only one. So the header is
  // rewritten on every scan, which is safe because it only ever
  // overwrites itself, while the one destructive step waits until two
  // consecutive looks agree on what the reply holds.
  var aiuiSettleScanTimer = 0;

  function aiuiScheduleSettleScan() {
    if (aiuiSettleScanTimer) return;
    aiuiSettleScanTimer = setTimeout(function () {
      aiuiSettleScanTimer = 0;
      aiuiScanAgentNameHeaders();
    }, 700);
  }



  // ===== Agents take turns =====
  // A pipe returns one reply and Open WebUI shows it as one message, and
  // no event a pipe can send makes a second one. So when two agents
  // answer, the pipe shows the first and hides a marker naming everybody
  // who answers, in order. This code finds that marker on the last reply,
  // waits until Open WebUI has saved it, asks the service to run the next
  // agent, writes the answer into the chat's own history as a new message
  // that is a child of the last one, and navigates away and back so the
  // chat loads again and shows it. Then the new tail carries the marker
  // for whoever is next, and the observer calls back in.
  //
  // Two facts this rests on, both checked on the live site 2026-09-04: the
  // chat renders an assistant message whose parent is another assistant
  // message as its own row; and a real link click is a SvelteKit soft
  // navigation, where a synthetic popstate is not.
  //
  // A pending approval carries no marker at all: the service withholds it
  // while the first agent waits to be told whether to send. So this finds
  // nothing and does nothing, with no special case of its own.
  var aiuiTurnsBusy = {};

  function aiuiChatIdFromUrl() {
    var m = /\/c\/([0-9a-f-]{36})/.exec(location.pathname);
    return m ? m[1] : null;
  }

  // The LAST marker, not the first. The pipes already strip marker shaped
  // text out of an agent's own words before appending the real one, but if
  // one ever slipped through, the real marker is the one appended at the
  // very end.
  function aiuiParseTurns(content) {
    var re = /<!--\s*aiui:turns\s+([^\s>]+)\s*-->/g;
    var m, last = null;
    while ((m = re.exec(content || '')) !== null) last = m;
    if (!last) return null;
    var ids = last[1].split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    return ids.length ? ids : null;
  }

  function aiuiStripTurnsMarker(content) {
    return String(content || '').replace(/<!--\s*aiui:turns\b[^>]*-->/g, '').replace(/\s+$/, '');
  }

  // The label the pipe put at the top, "Ada:" on its own line. Text, not
  // DOM: this runs on the stored content.
  //
  // Only ever removed when it names the agent this message is being claimed
  // for. Stripping any leading "Word:" line deleted real content whenever
  // SHOW_AGENT_NAME was off: an answer opening "Here is the plan:" lost
  // that line permanently, in storage, with nothing to undo it.
  function aiuiStripLeadingLabelText(content, agentId) {
    var name = aiuiAgentNameById[agentId];
    if (!name) return content;
    var m = /^\s*([A-Za-z0-9 -]{1,40}):[ \t]*\r?\n/.exec(content || '');
    if (!m || m[1].trim().toLowerCase() !== String(name).trim().toLowerCase()) {
      return content;
    }
    return content.slice(m[0].length);
  }

  // The messages on the current branch, root first. The history is a tree
  // and currentId names the tail, so walk parents and reverse.
  // The same question the pipe asks (io_gateway_pipe._approval_question),
  // rendered the same way: the tool's own name and arguments, never a hand
  // written phrase per tool. A phrasebook covering 300+ tools would be
  // wrong somewhere, and where it was wrong is exactly where somebody would
  // approve the wrong thing.
  var AIUI_MAX_ARGS_SHOWN = 5;
  var AIUI_MAX_ARG_CHARS = 120;

  function aiuiApprovalQuestion(name, calls) {
    var lines = [(name || 'This agent') + ' wants to run:'];
    var list = Array.isArray(calls) ? calls : [];
    for (var i = 0; i < list.length; i++) {
      var call = (list[i] && typeof list[i] === 'object') ? list[i] : {};
      var fn = (call.function && typeof call.function === 'object') ? call.function : {};
      var fname = (typeof fn.name === 'string' && fn.name.trim())
        ? fn.name.trim() : 'an unnamed tool';
      lines.push('  ' + fname);
      var args = {};
      try {
        args = typeof fn.arguments === 'string'
          ? JSON.parse(fn.arguments) : (fn.arguments || {});
      } catch (e) { args = {}; }
      if (args && typeof args === 'object') {
        var keys = Object.keys(args).slice(0, AIUI_MAX_ARGS_SHOWN);
        for (var k = 0; k < keys.length; k++) {
          lines.push('     ' + keys[k] + ': '
            + String(args[keys[k]]).slice(0, AIUI_MAX_ARG_CHARS));
        }
      }
    }
    if (lines.length === 1) lines.push('  something it did not name');
    lines.push('');
    lines.push('Reply yes to let it, or no to skip.');
    return lines.join('\n');
  }

  function aiuiChainFromHistory(history) {
    var msgs = history && history.messages ? history.messages : {};
    var id = history ? history.currentId : null;
    var chain = [];
    for (var guard = 0; id && msgs[id] && guard < 500; guard++) {
      chain.unshift(msgs[id]);
      id = msgs[id].parentId;
    }
    return chain;
  }

  function aiuiUuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 3 | 8)).toString(16);
    });
  }

  function aiuiTypingLine(text) {
    var el = document.getElementById('aiui-typing');
    if (!el) {
      el = document.createElement('div');
      el.id = 'aiui-typing';
      el.style.cssText = 'padding:.25rem 0 .75rem 3.75rem;opacity:.65;font-size:.9rem;';
      aiuiPutUnderLastMessage(el);
    }
    el.setAttribute('data-aiui-chat', String(aiuiChatIdFromUrl() || ''));
    el.textContent = text;
  }

  // The failure lines are the ones nothing else clears: "Mia did not
  // answer" stays until something removes it, and a chat change is not
  // something it notices. Without this a foreign line hangs under an
  // unrelated conversation.
  function aiuiDropStaleTypingLine() {
    var el = document.getElementById('aiui-typing');
    if (!el) return;
    if (el.getAttribute('data-aiui-chat') !== String(aiuiChatIdFromUrl() || '')) {
      if (el.parentNode) el.parentNode.removeChild(el);
    }
  }

  function aiuiClearTypingLine() {
    var el = document.getElementById('aiui-typing');
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  // SvelteKit intercepts a same-origin link click as a soft navigation.
  // Away to a fresh chat and back makes the chat component see its id
  // change and load again: about a second, no flash. If the rows have not
  // grown in five seconds the message is still saved, so reload the hard
  // way and accept the flash.
  function aiuiSoftReload(chatId) {
    function go(href) {
      var a = document.createElement('a');
      a.href = href;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    // The count is no use: the list renders at most 8 rows by default, so
    // in any chat already at that cap the count never grows and every turn
    // would hard reload after five seconds. The identity of the last row
    // changes whether or not the count does.
    // What the thread looks like now. It only has to CHANGE when a turn
    // lands, which is why the last message's length is in it: a reply
    // streams in under the same element, and counting elements alone
    // would miss it.
    function lastRowId() {
      var thread = aiuiThread();
      if (!thread) return '';
      var last = thread.lastElementChild;
      return thread.childElementCount + ':'
        + (last ? String(last.textContent || '').length : 0);
    }
    var before = lastRowId();
    go('/');
    setTimeout(function () { go('/c/' + chatId); }, 400);
    var tries = 0;
    var timer = setInterval(function () {
      tries++;
      var now = lastRowId();
      if (now && now !== before) { clearInterval(timer); return; }
      // NOT location.reload(): if the second synthetic click was dropped
      // the person is sitting on '/', and reloading that strands them on a
      // blank new chat instead of their conversation.
      if (tries >= 20) { clearInterval(timer); location.href = '/c/' + chatId; }
    }, 250);
  }

  function aiuiFetchChat(chatId) {
    return fetch('/api/v1/chats/' + chatId, { headers: aiuiAuthHeaders() })
      .then(function (r) {
        if (!r.ok) throw new Error('chat fetch ' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!data || !data.chat || !data.chat.history) throw new Error('chat shape');
        return data;
      });
  }

  // Whatever the caller passes is what gets sent. Every caller passes
  // { history: ... } and nothing else, on purpose: this route merges the
  // history but REPLACES title, tags and the flat messages list with
  // whatever the body carries, so posting a whole fetched chat back would
  // revert a title the server generated moments ago.
  function aiuiSaveChat(chatId, chat) {
    return fetch('/api/v1/chats/' + chatId, {
      method: 'POST', headers: aiuiAuthHeaders(), body: JSON.stringify({ chat: chat })
    }).then(function (r) {
      if (!r.ok) throw new Error('chat save ' + r.status);
    });
  }

  // Open WebUI saves the whole chat after a reply completes. Anything
  // written before that save is replaced by it. So wait until the stored
  // tail is the reply that carries the marker.
  //
  // The marker is read from the STORED content, never from the rendered
  // page: DOMPurify may strip an HTML comment out of what gets rendered.
  // The backend upserts a finished reply's content and done:true together
  // before it tells the frontend the reply is done, so done is the signal
  // that the stored copy is final. Stopping on done rather than on a marker
  // means an ordinary single-agent reply costs ONE GET, and a long streamed
  // reply, which is not finished when the observer first sees it, is still
  // waited out for up to ninety seconds at one look a second.
  //
  // Resolves { examined, data }. `examined` says a done assistant tail was
  // actually read, which is what lets the caller stop asking; `data` is the
  // chat only when that tail carries a marker. The two are separate because
  // "finished, nothing to do" and "never got to see it" have to be told
  // apart: latching on the second would lose the round for good.
  function aiuiWaitForSavedMarker(chatId) {
    var attempt = 0;
    function look() {
      return aiuiFetchChat(chatId).then(function (data) {
        var chain = aiuiChainFromHistory(data.chat.history);
        var tail = chain[chain.length - 1];
        // A tail that is not an assistant message has nothing to examine:
        // the last thing in the chat is the person's own message. That is
        // one GET, not ninety.
        if (!tail || tail.role !== 'assistant') return { examined: false, data: null };
        if (tail.done === true) {
          return { examined: true, data: aiuiParseTurns(tail.content) ? data : null };
        }
        if (++attempt >= 90) return { examined: false, data: null };
        return new Promise(function (r) { setTimeout(r, 1000); }).then(look);
      });
    }
    return look();
  }

  function aiuiSpeak(chatId, agentId, chain, afterId) {
    // The route caps the chain at 200 messages and each one at 32000
    // characters. Sending more is a 422 that never clears by itself, so a
    // long conversation would stop taking turns permanently.
    var messages = chain.slice(-200).map(function (m) {
      var content = aiuiStripTurnsMarker(m.content);
      if (content.length > 32000) content = content.slice(0, 32000);
      return { role: m.role, content: content };
    });
    return fetch('/api/tasks/agents/speak', {
      method: 'POST', headers: aiuiAuthHeaders(),
      body: JSON.stringify({ chat_id: chatId, agent_id: agentId,
                             after_id: afterId, messages: messages })
    }).then(function (r) {
      if (r.status === 403) return { refused: true };
      // Somebody else owns this exact turn. The service decided it under
      // a primary key, which is the only place it CAN be decided: the
      // page's own claim cannot be atomic against a chat endpoint with
      // no If-Match. Not a failure, and not ours to report.
      if (r.status === 409) return { taken: true };
      if (!r.ok) throw new Error('speak ' + r.status);
      return r.json();
    });
  }

  // Resolves true when a done assistant tail was actually examined, marker
  // or not, and including the abandoned and refused paths; false when the
  // poll ran out, the chat had nothing to look at, or a turn was already
  // running. The caller latches only on true, so a reply that finishes
  // after the poll gave up is still looked at again later.
  // Claim the turn before running it. Side effects beat retry.
  //
  // Two tabs open on the same chat both find the same marker, and without
  // this both POST /agents/speak, so an agent with write tools sends the
  // same email twice. Removing the agent from the STORED marker before it
  // runs makes the claim the thing that decides who runs it, and the loser
  // finds nothing to do.
  //
  // The same property covers failure. A claimed turn that fails is not
  // retried by a reload, because the marker no longer names it. An agent
  // that may have half done its work must not be run again by somebody
  // pressing refresh.
  //
  // Compare and swap, not just a write: the turn is only ours if the
  // stored marker STILL names this agent as the next to speak.
  function aiuiClaimTurn(chatId, tailId, agentId, spoke, rest) {
    return aiuiFetchChat(chatId).then(function (fresh) {
      var fh = fresh.chat.history;
      var fchain = aiuiChainFromHistory(fh);
      var ftail = fchain[fchain.length - 1];
      if (!ftail || ftail.id !== tailId) return null;
      var live = aiuiParseTurns(ftail.content);
      if (!live || live[1] !== agentId) return null;

      var body = aiuiStripTurnsMarker(ftail.content);
      var model = ftail.model;
      var modelName = ftail.modelName;
      // Claim the tail for its author too, if the pipe wrote it. A message
      // the page wrote already carries its agent as its model.
      if (model !== spoke) {
        model = spoke;
        modelName = aiuiAgentNameById[spoke] || spoke;
        body = aiuiStripLeadingLabelText(body, spoke);
      }
      var remaining = [spoke].concat(rest);
      if (remaining.length > 1) {
        body += '\n\n<!-- aiui:turns ' + remaining.join(',') + ' -->';
      }
      ftail.content = body;
      ftail.model = model;
      ftail.modelName = modelName;
      return aiuiSaveChat(chatId, { history: fh }).then(function () {
        return { content: body, model: model, modelName: modelName };
      }, function () { return null; });
    }, function () { return null; });
  }

  function aiuiTakeTurns(chatId) {
    if (!chatId || aiuiTurnsBusy[chatId]) return Promise.resolve(false);
    aiuiTurnsBusy[chatId] = true;

    var examined = false;
    var again = false;
    var chat, history, chain, tail, turns, spoke, next, rest, nextName;
    return aiuiWaitForSavedMarker(chatId).then(function (outcome) {
      examined = outcome.examined;
      var data = outcome.data;
      if (!data) return null;
      chat = data.chat;
      history = chat.history;
      chain = aiuiChainFromHistory(history);
      tail = chain[chain.length - 1];
      turns = aiuiParseTurns(tail.content);

      if (!turns || turns.length < 2) {
        // A marker with nobody left to speak. Clean it off and stop.
        tail.content = aiuiStripTurnsMarker(tail.content);
        return aiuiSaveChat(chatId, { history: history }).then(function () { return null; });
      }
      spoke = turns[0];
      next = turns[1];
      rest = turns.slice(2);
      nextName = aiuiAgentNameById[next] || next;

      aiuiTypingLine(nextName + ' is typing');
      return aiuiClaimTurn(chatId, tail.id, next, spoke, rest).then(function (claimed) {
        if (!claimed) {
          // Another tab took this turn, or the chat moved under us. Not
          // ours to run, and running it anyway is how an email goes twice.
          aiuiClearTypingLine();
          return null;
        }
        tail.content = claimed.content;
        tail.model = claimed.model;
        tail.modelName = claimed.modelName;
        return aiuiSpeak(chatId, next, chain, tail.id).then(function (out) {
          return { out: out };
        }, function () {
          // Claimed and failed. Deliberately NOT retried: the marker no
          // longer names this agent, so a reload will not run it again.
          // The typing line is for the person watching right now; the real
          // record is written below, because this one does not survive a
          // render or a reload.
          aiuiTypingLine(nextName + ' did not answer, and will not be retried');
          return { out: { unreachable: true } };
        });
      });
    }).then(function (step) {
      if (!step) return;
      var out = step.out;

      if (out.taken) {
        // Another tab is running this turn. Nothing to say and nothing to
        // write: it will write the reply itself.
        aiuiClearTypingLine();
        return;
      }

      if (out.refused) {
        // Not this person's agent any more. Nothing to write: the claim
        // already took this agent out of the stored marker and left the
        // rest, so the next round runs whoever is left.
        //
        // The recursion waits for the outer chain to settle. Clearing the
        // busy flag here and recursing under a still-running chain let the
        // outer .then clear it a second time, so a third run could start.
        aiuiClearTypingLine();
        if (rest.length) again = true;
        return;
      }

      var pending = (out.pending && typeof out.pending === 'object') ? out.pending : null;
      var answer;
      if (out.unreachable) {
        // The turn was claimed and then the service could not be reached, so
        // it will never run and nothing will retry it. This has to be a real
        // message. The typing line is gone on the next render and says
        // nothing at all after a reload, so a person who looked away, or who
        // reloaded, would see Ada's answer, no Mia, and no sign that a turn
        // had ever been attempted. It is written as that agent's own message,
        // the same way a successful turn is, so it reads as coming from the
        // agent that was asked.
        answer = nextName + ' could not be reached, so this turn did not run.'
          + ' Ask again if you still want it.';
      } else if (pending && Array.isArray(pending.calls) && pending.calls.length) {
        // The agent stopped to ask. Show its question, the same one the
        // pipe shows, not the empty-answer placeholder.
        answer = aiuiApprovalQuestion(nextName, pending.calls);
      } else {
        answer = String(out.answer || '').trim();
        var notes = (out.notes || []).filter(function (n) { return typeof n === 'string'; });
        if (notes.length) answer = answer ? answer + '\n\n' + notes.join('\n') : notes.join('\n');
        if (!answer) answer = 'There was nothing to answer.';
      }
      if (rest.length) answer += '\n\n<!-- aiui:turns ' + [next].concat(rest).join(',') + ' -->';

      return aiuiFetchChat(chatId).then(function (fresh) {
        // The chat may have moved while the agent was answering. Write
        // against what is stored NOW, and only if the tail is still the
        // message this turn was taken for; otherwise the person sent
        // something and this turn is abandoned, marker left for a retry.
        var fh = fresh.chat.history;
        var fchain = aiuiChainFromHistory(fh);
        var ftail = fchain[fchain.length - 1];
        if (!ftail || ftail.id !== tail.id) { aiuiClearTypingLine(); return; }

        // Idempotent: the frontend's own save can revert the tail after a
        // run already wrote this agent's reply. Reuse it, never duplicate.
        var existing = (ftail.childrenIds || []).map(function (id) { return fh.messages[id]; })
          .filter(function (m) { return m && m.role === 'assistant' && m.model === next; })[0];
        var newId = existing ? existing.id : aiuiUuid();

        // The queue moves onto the new message, which carries the marker
        // for whoever is left. Clearing it here is what stops a drained
        // round leaving a live marker on a message that is no longer the
        // tail: a later branch switch would find it and run an agent that
        // has already spoken. The claim only removed the agent it ran.
        ftail.content = aiuiStripTurnsMarker(tail.content);
        if (ftail.model !== spoke) { ftail.model = spoke; ftail.modelName = tail.modelName; }
        if (!existing) {
          fh.messages[newId] = {
            id: newId, parentId: ftail.id, childrenIds: [], role: 'assistant',
            content: answer, model: next, modelName: nextName, modelIdx: 0,
            done: true, timestamp: Math.floor(Date.now() / 1000)
          };
          ftail.childrenIds = (ftail.childrenIds || []).concat([newId]);
        }
        fh.currentId = newId;
        return aiuiSaveChat(chatId, { history: fh }).then(function () {
          aiuiClearTypingLine();
          aiuiSoftReload(chatId);
        }, function () {
          aiuiTypingLine('could not add ' + nextName + "'s reply");
          console.warn('[AIUI turns] reply not saved for', next, ':', answer);
        });
      });
    }).catch(function (e) {
      console.warn('[AIUI turns]', e && e.message ? e.message : e);
    }).then(function () {
      aiuiTurnsBusy[chatId] = false;
      if (again) setTimeout(function () { aiuiTakeTurns(chatId); }, 0);
      return examined;
    });
  }

  function aiuiRewriteAgentHeader(span) {
    if (!span) return;
    var body = aiuiFindReplyBody(span);
    if (!body) return;

    var scan = aiuiAgentLabelsIn(body);
    if (!scan.labels.length) {
      // Nothing here names an agent. Refresh only when a name-shaped
      // line went unrecognised, so an ordinary conversation full of
      // "Note:" lines still costs no requests at all.
      if (scan.sawUnknownName) aiuiRefreshAgentNames();
      return;
    }

    var names = [];
    for (var i = 0; i < scan.labels.length; i++) names.push(scan.labels[i].name);
    var joined = aiuiJoinNames(names);
    if (span.textContent !== joined) span.textContent = joined;
    span.setAttribute('data-aiui-agent-header', '1');

    var signature = names.length + ':' + (body.textContent || '').length;
    var settled = span.getAttribute('data-aiui-agent-seen') === signature;
    span.setAttribute('data-aiui-agent-seen', signature);
    if (!settled) {
      aiuiScheduleSettleScan();
      return;
    }

    // One agent per reply now, so the label below always repeats the
    // header and goes.
    //
    // Turn taking is deliberately NOT hung off this function. A reply the
    // page itself wrote carries no label, so every path above returns
    // early on it; with the turn taking here, the second agent's message
    // would never be looked at and a third agent would never speak.
    // aiuiScanAgentNameHeaders drives it separately.
    if (span.getAttribute('data-aiui-agent-stripped') === '1') return;
    span.setAttribute('data-aiui-agent-stripped', '1');
    // Only when one agent spoke. In an older bubble holding two answers the
    // labels are the only thing saying which answer belongs to whom, so
    // they stay and the header names both.
    if (names.length === 1) aiuiStripLabel(body, scan.labels[0]);
  }

  // Once per reply, once it has stopped changing. The settle check is the
  // same shape the header rewrite uses, kept separate so the two never
  // depend on each other.
  //
  // Open WebUI renders the assistant row with EMPTY content before the
  // completion request has even returned. That empty body has a stable
  // length, so a settle check that accepted it would fire about half a
  // second after send: too early for the chat to have an id yet on a new
  // chat, and long before the reply is stored. Requiring real text is what
  // keeps this from checking nothing and latching shut on the result.
  function aiuiMaybeTakeTurns(span) {
    var body = aiuiFindReplyBody(span);
    var sig = String(body ? (body.textContent || '').trim().length : 0);
    if (sig === '0') return;
    if (span.getAttribute('data-aiui-turns-checked') === sig) return;
    if (span.getAttribute('data-aiui-turns-seen') !== sig) {
      span.setAttribute('data-aiui-turns-seen', sig);
      aiuiScheduleSettleScan();
      return;
    }
    var chatId = aiuiChatIdFromUrl();
    if (!chatId) {
      // A Temporary Chat stays on '/' and a shared chat on '/s/<id>', so
      // there is no chat id and there never will be. Nothing on this path
      // can latch, and turns-seen already equals sig, so rescheduling
      // unconditionally re-armed the 700ms timer for the life of the tab:
      // a full querySelectorAll, body walk and label scan 1.4 times a
      // second, forever, for people who own no agents at all. A few tries
      // still covers the real case, a brand new chat whose URL is only set
      // once the completion request returns.
      var tries = Number(span.getAttribute('data-aiui-turns-tries') || 0) + 1;
      span.setAttribute('data-aiui-turns-tries', String(tries));
      if (tries < 3) aiuiScheduleSettleScan();
      return;
    }
    aiuiTakeTurns(chatId).then(function (examined) {
      // Latch only once a done tail was actually examined, keyed to the
      // body length so a reply that finishes later, and is therefore
      // longer, is looked at again. A poll that ran out, or a chat with
      // no id yet, is not a check and leaves no latch.
      if (examined) span.setAttribute('data-aiui-turns-checked', sig);
    });
  }

  function aiuiScanAgentNameHeaders() {
    var spans = document.querySelectorAll('#response-message-model-name');
    for (var i = 0; i < spans.length; i++) aiuiRewriteAgentHeader(spans[i]);
    aiuiDropStaleTypingLine();
    // Turn taking is independent of labels. The last reply may be one the
    // page itself wrote, which carries no label and a marker for whoever
    // is next, so it must be looked at regardless of what the header
    // rewrite found.
    if (spans.length) aiuiMaybeTakeTurns(spans[spans.length - 1]);
    aiuiWatchBuilds();
  }

  function wireAiuiAgentNameHeaders() {
    var pending = false;
    function scan() {
      pending = false;
      aiuiScanAgentNameHeaders();
    }
    var obs = new MutationObserver(function () {
      if (pending) return;
      pending = true;
      setTimeout(scan, 200);
    });
    obs.observe(document.body, { childList: true, subtree: true });
    aiuiRefreshAgentNames();
    scan();
  }

  // ===== Build watcher =====
  //
  // A build started from the main chat answers in seconds with "Building X
  // now ... Watch it here: <preview.html?task=id>" and then runs for
  // minutes. Until 2026-11-03 the chat said nothing more unless somebody
  // asked, so a person could not tell working from finished from broken
  // (Lukas, 2026-10-31). The page watches that link and, when the build
  // settles, adds ONE message with the link to the app, the question it is
  // waiting on, or why it failed.
  //
  // The page and not the service, because Open WebUI's page saves its own
  // copy of the whole chat on the next message: a message the service wrote
  // behind its back could be wiped out. The cost is that nothing is posted
  // while the chat is closed; it catches up when the chat is opened again.
  // ===== What a reply carries =====
  //
  // A reply is text, and the page has been reading things OUT of that
  // text to know what the message is about: a preview.html link means a
  // build to watch, and the sentence "Its id is <uuid>" means a video.
  //
  // The second one is the problem. It keys on a sentence a tool writes in
  // English. Reword that sentence and video watching stops, with nothing
  // failing and nothing saying so.
  //
  // So a reply may now declare what it carries, as a markdown link
  // reference definition, which the parser consumes and does not render:
  //
  //     [aiui-artifact]: #app/nike-tshirt-landing-6430
  //     [aiui-artifact]: #build/528f5422-5dea-4c5a-8638-8e919a01109b
  //     [aiui-artifact]: #video/55785e0a-a4e4-4d4c-a2d5-5747c8899019
  //
  // Nothing writes those yet; the services still write prose. This is the
  // reading half, so the writing half is one line wherever a reply is
  // composed, and so the two scanners that exist become one contract with
  // one place to change. The prose forms stay, because they are what every
  // message already in somebody's history says.
  // The id must START with a letter or a digit, so ".." cannot be one.
  // It becomes part of a URL further down, and although the slug check
  // there would refuse it, a parser that hands out ".." at all is one
  // careless caller away from a traversal.
  // The trailing lookahead makes an over-long id NO MATCH rather than a
  // match of its first 120 characters. Truncating an id silently hands
  // back a different one, which is worse than ignoring a marker nobody
  // should have written.
  var AIUI_ARTIFACT = /\[aiui-artifact\]: #(app|build|video)\/([A-Za-z0-9][A-Za-z0-9._-]{0,119})(?![A-Za-z0-9._-])/g;

  //: A video job and a build task are both uuids; an app is a slug.
  var AIUI_UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';

  function aiuiArtifactsIn(content) {
    var text = String(content || '');
    var found = [];
    function add(kind, id) {
      if (!id) return;
      // Belt and braces with the pattern above: a dot run anywhere in an
      // id has no legitimate use and every traversal needs one.
      if (id.indexOf('..') >= 0) return;
      for (var i = 0; i < found.length; i++) {
        if (found[i].kind === kind && found[i].id === id) return;
      }
      found.push({ kind: kind, id: id });
    }

    // Declared, and therefore trusted first.
    AIUI_ARTIFACT.lastIndex = 0;
    var m;
    while ((m = AIUI_ARTIFACT.exec(text)) !== null) add(m[1], m[2]);

    // Read out of the prose, for everything written before the marker
    // existed. Each of these is a guess about wording, which is the whole
    // reason the marker is better.
    var link = new RegExp('/tasks/static/preview\\.html\\?task=(' + AIUI_UUID + ')', 'g');
    while ((m = link.exec(text)) !== null) add('build', m[1]);
    var vid = new RegExp('[Ii]ts id is (' + AIUI_UUID + ')', 'g');
    while ((m = vid.exec(text)) !== null) add('video', m[1]);

    // "task_id: <uuid>", which is how a build names itself when it goes
    // through an APPROVAL rather than answering with a link.
    //
    // Ralph, 2026-11-05: a build he approved showed no panel at all. The
    // reply was prose, "is still building, give it a few minutes", with
    // the id sitting in the message as task_id and nothing reading it.
    // The panel only ever appeared for the one phrasing that happened to
    // carry a preview link, which is the whole reason a reply should
    // DECLARE what it carries rather than be read for it.
    var tid = new RegExp('task_id\\s*:\\s*(' + AIUI_UUID + ')', 'g');
    while ((m = tid.exec(text)) !== null) add('build', m[1]);

    // And the bare "?task=<uuid>" of any preview URL, however it is
    // written or wrapped.
    var any = new RegExp('[?&]task=(' + AIUI_UUID + ')', 'g');
    while ((m = any.exec(text)) !== null) add('build', m[1]);

    // The FINISHED build's own URL, which names a slug and carries no
    // task id at all.
    //
    // Ralph, 2026-11-05: a build finished and the chat showed a link
    // and nothing else. Every pattern above wants a uuid, and "X is
    // built. Open it here: /tasks/preview-app/X/" has none, so the one
    // message that announces a finished app was the one message
    // nothing could read. The panel was only ever drawn by the watcher
    // at the moment it saw the build complete, so a reload, a second
    // tab, or a build already closed all showed the bare link.
    var appUrl = new RegExp(
      '/tasks/preview-app/([a-z0-9][a-z0-9-]{0,80})', 'g');
    while ((m = appUrl.exec(text)) !== null) add('app', m[1]);
    return found;
  }

  function aiuiArtifactIds(content, kind) {
    return aiuiArtifactsIn(content)
      .filter(function (a) { return a.kind === kind; })
      .map(function (a) { return a.id; });
  }
  // ===== End what a reply carries =====

  var AIUI_BUILD_LINK = /\/tasks\/static\/preview\.html\?task=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/g;
  var AIUI_BUILD_POLL_MS = 10000;
  var AIUI_BUILD_GIVE_UP_MS = 60 * 60 * 1000;
  var AIUI_BUILD_LOOK_MS = 5000;
  // A link older than this is a build from before the watcher, or one
  // already reported elsewhere. Closing those on first open would post a
  // pile of "is built" messages for builds from weeks ago.
  var AIUI_BUILD_RECENT_S = 2 * 60 * 60;
  var aiuiBuildWatched = {};
  var aiuiBuildLastLook = 0;

  function aiuiBuildIdsIn(content) {
    return aiuiArtifactIds(content, 'build');
  }

  // A MARKDOWN LINK REFERENCE DEFINITION, not an HTML comment.
  //
  // Open WebUI renders a message as markdown and escapes the HTML in it,
  // so "<!-- aiui:build-done ... -->" was printed to the person, under
  // every finished build, from the day the watcher shipped. Ralph saw it
  // on his first real build (2026-11-04) and it looked like debris,
  // because it was.
  //
  // "[name]: #id" is consumed by the markdown parser and produces no
  // output at all, which is what a marker is supposed to do. It still
  // sits in the message text, so it still survives a reload and another
  // tab, which is the whole reason it lives there rather than in this
  // page's memory.
  function aiuiBuildDoneMarker(id) {
    return '[aiui-build-done]: #' + id;
  }

  // What the marker used to be. Still recognised, so a build already
  // closed under the old shape is not reported a second time, and so the
  // old text can be recognised wherever it is still sitting in somebody's
  // history.
  function aiuiLegacyBuildMarker(id) {
    return '<!-- aiui:build-done ' + id + ' -->';
  }

  // One marker or several. Several, because a marker's shape changed
  // once and anything already written under the old one still counts as
  // closed; reporting those builds again would post "is built" under
  // every finished build in somebody's history.
  function aiuiIsClosed(chain, markers) {
    var want = (typeof markers === 'string') ? [markers] : (markers || []);
    for (var i = 0; i < chain.length; i++) {
      var text = String((chain[i] && chain[i].content) || '');
      for (var j = 0; j < want.length; j++) {
        if (want[j] && text.indexOf(want[j]) >= 0) return true;
      }
    }
    return false;
  }

  function aiuiBuildIsClosed(chain, id) {
    return aiuiIsClosed(chain, [aiuiBuildDoneMarker(id),
                                aiuiLegacyBuildMarker(id)]);
  }

  // Mirrors routes_aiuibuilder._public_build_status and _preview_url, so the
  // page says what the build_status tool would say.
  function aiuiBuildOutcome(task, id, origin) {
    var status = String((task && task.status) || '');
    if (status === 'running' || status === 'planning') return null;
    var slug = (task && task.built_app_slug) || 'The app';
    var why = String((task && task.result) || '').trim().slice(0, 500);
    var said;
    if (status === 'completed') {
      // No link. The app itself runs in the reply, so a URL here is a
      // second way to reach what is already on screen. The slug is
      // declared below instead, which is what draws it.
      said = slug + ' is built.';
      // Declared, not left to be read out of the sentence. The URL
      // above is recognised too, for every build written before
      // this, but a reply that says what it carries is the thing
      // that does not break when somebody rewords it.
      if (task && task.built_app_slug) {
        said += '\n\n[aiui-artifact]: #app/' + task.built_app_slug;
      }
    } else if (status === 'awaiting_input') {
      said = slug + ' is waiting on an answer.' + (why ? '\n' + why : '')
        + '\nAnswer it here: ' + origin + '/tasks/static/preview.html?task=' + id;
    } else {
      said = slug + ' did not finish building.' + (why ? '\n' + why : '');
    }
    return said + '\n\n' + aiuiBuildDoneMarker(id);
  }

  // The app itself, under the reply, when a build finishes (2026-11-04).
  // A build used to end with a link, so seeing what was made meant opening
  // a second tab and coming back.
  //
  // An IFRAME of the app's own published URL, deliberately, rather than
  // anything that reads its files: main.py::serve_published_app injects
  // the project's Supabase url and anon key AT REQUEST TIME, so they are
  // not in the app's files at all. Anything that assembles the page
  // another way serves an app whose database silently does not work,
  // while the same app in a tab works fine.
  // One place, because three things now sit under a reply: the build
  // while it runs, the app when it is done, and a video when it is
  // rendered. Three copies of "find the last message" would drift.
  // The element that holds the conversation.
  //
  // Open WebUI 0.12 renders it as:
  //
  //   <div id="messages-container" class="... flex flex-col-reverse ...">
  //     <div id="full-messages-container"> ...the messages... </div>
  //
  // The outer one is col-REVERSE, so appending to it puts a thing at the
  // TOP of the thread. It is the inner one or nothing.
  //
  // Everything here used to look for '[id^="message-"]'. This version has
  // no per-message ids, and the only element whose id starts that way is
  // "message-input-container", the COMPOSER. So the typing line, the
  // build line and every panel were placed after the input box, outside
  // the conversation entirely (Ralph, 2026-11-04: "not below in the chat
  // please fix"), the reload check compared the composer against itself,
  // and the scan for build links read the composer's markup.
  // The TWO ids Open WebUI gives us, named here and nowhere else.
  //
  // They have moved once already and will move again, and when they do
  // this is the only place to change. A test asserts no other line in
  // this file mentions them, which is how a second copy was found in the
  // split view the day this was written.
  function aiuiScroller() {
    return document.getElementById('messages-container');
  }

  function aiuiComposer() {
    return document.getElementById('message-input-container');
  }

  function aiuiThread() {
    // Tried in order, because the exact id is not something to rely on.
    //
    // "full-messages-container" came from a SOURCE MAP, not from the
    // markup this version renders, and it is not in the live page: every
    // panel fell through to document.body and landed under the message
    // box, which is the same bug twice (Ralph, 2026-11-05: "still in
    // below the chat").
    //
    // The scroller is in the compiled bundle and is reliable. It is
    // flex-col-REVERSE, so appending to IT puts a thing at the top of the
    // conversation; its inner wrapper is where the messages live, and
    // appending there is the bottom. The wrapper is taken by position
    // rather than by name so a rename cannot do this a third time.
    var named = document.getElementById('full-messages-container');
    if (named) return named;
    return aiuiScroller();
  }

  // Whether the thread is laid out bottom-up. The chat view renders
  // #messages-container with "flex flex-col-reverse overflow-auto", and in
  // a reversed column the FIRST child is the one at the bottom. Appending
  // to it would put a panel at the top of the conversation, above every
  // message, which is a different wrong place from the one this is
  // fixing.
  function aiuiThreadIsReversed(el) {
    try {
      return String(getComputedStyle(el).flexDirection || '')
        .indexOf('reverse') >= 0;
    } catch (e) {
      return false;
    }
  }

  // The last reply's own content block, or null.
  //
  // Open WebUI 0.12 builds a message like this (its own ResponseMessage
  // source, read from the source map of the compiled chunk on the
  // server, not reasoned about):
  //
  //   <div class=" flex w-full message-{id}" id="message-{id}">
  //     <div class="shrink-0 ...">                 the avatar
  //     <div class="flex-auto w-0 pl-1 relative">  the column
  //       <Name><Tooltip><span id="response-message-model-name">
  //       <div>
  //         <div class="chat-{message.role} w-full min-w-full">
  //           <div> ...what the model said...
  //
  // So the block holding the reply is chat-assistant, and it is a
  // GRANDCHILD of the column, not a sibling of the name. A walk that
  // checks a sibling's own class lands in the column instead: inside the
  // message, but beside what the model said rather than part of it,
  // which is the difference Ralph has now pointed at three times.
  //
  // Two things reading that source corrected:
  //
  //   There ARE per-message ids. "no per-message ids" was wrong. The
  //   only trouble was that message-input-container, the COMPOSER,
  //   shares the "message-" prefix, which is what the first attempt hit.
  //
  //   chat-assistant IS in the DOM. Grepping the built bundle for it
  //   finds nothing, because it is assembled at runtime from
  //   'chat-' + message.role, so searching the build says "absent" about
  //   a class that is on screen. That is what made this look unusable.
  function aiuiLastReplyBody() {
    var thread = aiuiThread();
    var scope = thread || document;

    // Named, not walked. chat-user exists too, so this asks for the
    // model's block rather than for whatever block happens to be last.
    var bodies = scope.querySelectorAll('.chat-assistant');
    if (bodies.length) return bodies[bodies.length - 1];

    // The markup has moved. The walk from the model name still finds
    // something inside the message, which is worse than the line above
    // and much better than the bottom of the page.
    var spans = document.querySelectorAll('#response-message-model-name');
    for (var i = spans.length - 1; i >= 0; i--) {
      var body = aiuiFindReplyBody(spans[i]);
      if (body) return body;
    }
    return null;
  }

  function aiuiPutUnderLastMessage(box) {
    // Inside the reply itself, which is where a person reads it. A box
    // appended after the message is a separate thing sitting under the
    // conversation; this is part of what the model said.
    //
    // Open WebUI rebuilds a message's content when it changes, so a panel
    // put here can be thrown away. That is survivable and deliberate:
    // every caller checks for its own id first and the scan runs again,
    // so a discarded panel comes straight back.
    var reply = aiuiLastReplyBody();
    if (reply) {
      // The avatar gutter is already applied by the reply itself, so the
      // indent every panel carries for the thread would double up here.
      // Cleared centrally, because six panels carry it and a seventh
      // would forget.
      aiuiSetIndent(box, '0');
      box.style.paddingLeft = '0';
      reply.appendChild(box);
      // After it is in the page: how much wider it may grow is measured
      // against the column it sits in and the window around it.
      aiuiSetIndent(box, '0');
      return;
    }
    var thread = aiuiThread();
    if (thread) {
      // The messages usually sit in one wrapper inside the scroller. Put
      // the panel in there, after the last of them, which is the bottom
      // of the conversation however the scroller itself is laid out.
      var inner = thread.firstElementChild;
      if (inner && inner.children.length && !aiuiThreadIsReversed(thread)) {
        inner.appendChild(box);
        return;
      }
      if (aiuiThreadIsReversed(thread)) {
        thread.insertBefore(box, thread.firstChild);
        return;
      }
      thread.appendChild(box);
      return;
    }
    // Better somewhere visible than nowhere. It is also the one place
    // that says the markup has moved again, so it says so out loud: this
    // fell back silently for two days and looked like a styling problem.
    try {
      if (window.console && console.warn) {
        console.warn('[aiui] no chat thread found; '
                     + 'putting this under the page instead');
      }
    } catch (e) { /* no console */ }
    document.body.appendChild(box);
  }

  // The build itself, watchable in the chat (2026-11-04, Ralph: "it should
  // inline in the chat should see the process or to watch instead of link
  // only"). The reply carried a link to preview.html and nothing else, so
  // watching a build meant leaving the conversation.
  //
  // It IS preview.html, in a frame. That page already draws the live
  // build: the overlay, the progress bar, the status chip, the history.
  // A second implementation of all that, kept in step with the first, is
  // the kind of thing that is right for a week.
  function aiuiBuildBoxId(id) { return 'aiui-build-' + id; }

  function aiuiShowBuildInline(chatId, id) {
    if (aiuiChatIdFromUrl() !== chatId) return;
    if (document.getElementById(aiuiBuildBoxId(id))) return;
    if (!aiuiLastReplyBody()) return;

    var box = document.createElement('div');
    box.id = aiuiBuildBoxId(id);
    box.style.cssText = 'margin:.5rem 0 1rem 3.75rem;max-width:46rem;'
      + 'border:1px solid rgba(127,127,127,.3);border-radius:10px;overflow:hidden;';

    var bar = document.createElement('div');
    bar.style.cssText = 'display:flex;align-items:center;justify-content:space-between;'
      + 'gap:.5rem;padding:.4rem .6rem;font-size:.8rem;opacity:.75;';
    var who = document.createElement('span');
    who.textContent = 'Building';
    var open = document.createElement('a');
    open.href = '/tasks/static/preview.html?task=' + id;
    open.target = '_blank';
    open.rel = 'noopener';
    open.textContent = 'Open in a new tab';
    open.style.cssText = 'color:#8ab4f8;text-decoration:none;';
    bar.appendChild(who);
    bar.appendChild(open);

    var frame = document.createElement('iframe');
    // allow-same-origin because it is our own page on our own origin and
    // it reads the signed-in token to watch the build. No
    // allow-top-navigation: a page in a frame must not move the chat.
    frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-same-origin');
    frame.title = 'Building';
    frame.src = '/tasks/static/preview.html?task=' + id;
    frame.style.cssText = 'display:block;width:100%;height:26rem;border:0;background:#111;';

    box.appendChild(bar);
    box.appendChild(frame);
    aiuiPutUnderLastMessage(box);
  }

  function aiuiHideBuildInline(id) {
    var box = document.getElementById(aiuiBuildBoxId(id));
    // Taken away when the build settles: what replaces it is the app
    // itself, and leaving a finished build's frame above it means the
    // same thing twice.
    if (box && box.parentElement) box.parentElement.removeChild(box);
  }

  //: How tall the app sits in the conversation, and how tall it goes when
  //: somebody expands it. Small by default: it is one turn in a chat, not
  //: the page.
  //: How wide a preview sits in the conversation at rest. One turn in a
  //: chat, not the page.
  //:
  //: It is a CAP, which is why the drag shipped on 2026-11-11 looked
  //: broken: a block element does not grow past its max-width however
  //: negative its margins are, so the handle moved the box around inside
  //: its column and every test of it passed, having measured a box with
  //: no such cap on it.
  var AIUI_APP_MAXW = '46rem';
  var AIUI_APP_H = '22rem';
  var AIUI_APP_H_BIG = '80vh';

  //: The height of an app preview is the person's to choose, in pixels.
  //:
  //: 22rem was one guess for every app ever built, and a landing page at
  //: 22rem is a letterbox (2026-11-11, Ralph, looking at a cup landing page
  //: in a chat). The floor is not taste: a preview dragged to nothing is a
  //: control that destroys the thing it controls, with no obvious way back.
  //: The ceiling keeps one panel from being taller than any screen it is
  //: read on.
  var AIUI_APP_MIN = 180;
  var AIUI_APP_MAX = 1400;
  //: One arrow press. Big enough to be worth pressing, small enough to land
  //: where somebody meant.
  var AIUI_APP_STEP = 48;
  //: Remembered per browser, not per app. The person is choosing how tall a
  //: preview should be in their chat, which is an answer about their screen
  //: and their eyes, not about one landing page.
  var AIUI_APP_H_KEY = 'aiui-app-height';

  //: And how much WIDER than its column, which is the other half of the
  //: same answer (2026-11-12, Ralph: "the size cant be widen only hight i
  //: can adjust.. please add that also").
  //:
  //: A landing page is wide. The message column is roughly 720 pixels on a
  //: 1920 screen, so a page was being rendered into a third of the window
  //: and read at a third of its size, with two thirds of the screen empty
  //: on either side of it.
  //:
  //: What is stored is the EXTRA beyond the column, never a width. The box
  //: lives in the column's normal flow: a width larger than the column
  //: overflows to one side and sits off centre, while symmetric NEGATIVE
  //: margins keep it in flow, centred, and growing both ways, which is
  //: what "wider" looks like to the person dragging it. An extra also
  //: survives the column itself changing width, which a stored width does
  //: not.
  var AIUI_APP_W_KEY = 'aiui-app-width';
  //: One arrow press sideways. Wider than the vertical step because
  //: horizontal room is what there is most of.
  var AIUI_APP_W_STEP = 64;
  //: Kept off the window's own edges, so the drag always has somewhere
  //: left to grab.
  var AIUI_APP_W_GUTTER = 16;

  // ===== The name opens a menu =====
  //
  // What the app's name offers, the way ChatGPT's canvas does: where it
  // came from, its history, and a copy of it.
  //
  // Almost none of this is new. Version history is already
  // "git log -- apps/<slug>/" behind /api/aiuibuilder/<slug>/versions, and
  // the download is the export the App Builder card has had for months.
  // This puts them where somebody is actually looking at the app.
  var AIUI_VERSIONS_SHOWN = 8;

  function aiuiAppMenu(slug, anchorEl) {
    var open = document.getElementById('aiui-app-menu');
    if (open) {
      open.parentNode.removeChild(open);
      if (open.getAttribute('data-for') === slug) return;
    }

    var menu = document.createElement('div');
    menu.id = 'aiui-app-menu';
    menu.setAttribute('data-for', slug);
    menu.setAttribute('role', 'menu');
    var at = anchorEl.getBoundingClientRect();
    menu.style.cssText = 'position:fixed;z-index:9500;min-width:17rem;'
      + 'max-width:26rem;max-height:60vh;overflow:auto;'
      + 'background:#17171a;color:#ededee;border-radius:10px;'
      + 'border:1px solid rgba(127,127,127,.35);padding:.35rem;'
      + 'box-shadow:0 10px 30px rgba(0,0,0,.45);font-size:.85rem;'
      + 'left:' + Math.round(at.left) + 'px;top:' + Math.round(at.bottom + 6) + 'px;';

    function row(text, onPick) {
      var el = document.createElement(onPick ? 'button' : 'div');
      if (onPick) {
        el.type = 'button';
        el.setAttribute('role', 'menuitem');
        el.addEventListener('click', onPick);
      }
      el.textContent = text;
      el.style.cssText = 'display:block;width:100%;text-align:left;'
        + 'background:none;border:0;color:inherit;padding:.4rem .5rem;'
        + 'border-radius:6px;font-size:.85rem;'
        + (onPick ? 'cursor:pointer;' : 'opacity:.6;');
      if (onPick) {
        el.addEventListener('mouseenter', function () {
          el.style.background = 'rgba(127,127,127,.18)';
        });
        el.addEventListener('mouseleave', function () {
          el.style.background = 'none';
        });
      }
      menu.appendChild(el);
      return el;
    }

    row(slug);
    row('Open in App Builder', function () {
      window.open(location.origin + '/app-builder', '_blank', 'noopener');
      shut();
    });
    row('Download it', function () {
      // A plain navigation, so the browser saves the file instead of this
      // page holding a zip of somebody's app in memory.
      window.open('/api/projects/' + encodeURIComponent(slug) + '/export',
                  '_blank', 'noopener');
      shut();
    });

    var hist = row('History');
    var list = document.createElement('div');
    menu.appendChild(list);
    fetch('/api/aiuibuilder/' + encodeURIComponent(slug) + '/versions',
          { headers: aiuiAuthHeaders() })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (rows) {
        if (!rows || !rows.length) {
          hist.textContent = 'No history yet';
          return;
        }
        hist.textContent = 'History';
        rows.slice(0, AIUI_VERSIONS_SHOWN).forEach(function (v) {
          var when = String(v.date || '').slice(0, 16).replace('T', ' ');
          var said = String(v.message || '').slice(0, 70);
          var r2 = row((v.is_current ? '✓ ' : '    ')
                       + when + '  ' + said,
                       v.is_current ? null : function () {
            // Asked first. Rolling back throws away everything since,
            // and the menu row is one click from a stray hover.
            if (!window.confirm('Put the app back to how it was at '
                                + when + '?')) return;
            fetch('/api/aiuibuilder/' + encodeURIComponent(slug) + '/rollback', {
              method: 'POST',
              headers: aiuiAuthHeaders(),
              body: JSON.stringify({ sha: v.sha })
            }).then(function (res) {
              r2.textContent = res.ok ? 'Put back. Reload to see it.'
                                      : 'That could not be put back.';
            }).catch(function () {
              r2.textContent = 'That could not be put back.';
            });
          });
          if (v.is_current) r2.style.opacity = '.75';
        });
      }).catch(function () { hist.textContent = 'History is not available'; });

    function shut() {
      if (menu.parentNode) menu.parentNode.removeChild(menu);
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('mousedown', onAway, true);
    }
    function onKey(e) { if (e.key === 'Escape') shut(); }
    function onAway(e) {
      if (!menu.contains(e.target) && e.target !== anchorEl) shut();
    }
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('mousedown', onAway, true);
    document.body.appendChild(menu);
  }
  // ===== End the name opens a menu =====

  // ===== Annotate =====
  //
  // Point at a part of the site and say what to change, rather than
  // describing where it is in words. The panel already shows the running
  // app, so the thing somebody wants to change is right there under the
  // pointer.
  //
  // It can reach inside the frame because the app is served from OUR
  // origin and the sandbox carries allow-same-origin. That is also the
  // limit of it: this works for an app of ours and would not, and should
  // not, for anything else.
  var AIUI_MARK = 'aiui-annotate-outline';

  function aiuiSelectorFor(el) {
    // Enough for a person's agent to find it again, and no more. An id is
    // the whole answer; otherwise walk up far enough to be unambiguous
    // without producing a selector nobody can read.
    if (!el || !el.tagName) return '';
    if (el.id) return '#' + el.id;
    var parts = [];
    var node = el;
    for (var depth = 0; node && node.tagName && depth < 4; depth += 1) {
      var part = node.tagName.toLowerCase();
      var cls = String(node.className || '').trim().split(/\s+/)
        .filter(function (c) { return c && c !== AIUI_MARK; })[0];
      if (cls) part += '.' + cls;
      var parent = node.parentElement;
      if (parent) {
        var same = [];
        for (var i = 0; i < parent.children.length; i++) {
          if (parent.children[i].tagName === node.tagName) {
            same.push(parent.children[i]);
          }
        }
        if (same.length > 1) {
          part += ':nth-of-type(' + (same.indexOf(node) + 1) + ')';
        }
      }
      parts.unshift(part);
      if (node.id) { parts[0] = '#' + node.id; break; }
      node = parent;
    }
    return parts.join(' > ');
  }

  function aiuiAnnotateOff(state) {
    if (!state || !state.doc) return;
    try {
      state.doc.removeEventListener('click', state.onClick, true);
      state.doc.removeEventListener('mouseover', state.onOver, true);
      if (state.style && state.style.parentNode) {
        state.style.parentNode.removeChild(state.style);
      }
      var marked = state.doc.querySelectorAll('.' + AIUI_MARK);
      for (var i = 0; i < marked.length; i++) {
        marked[i].classList.remove(AIUI_MARK);
      }
    } catch (e) { /* the frame went away under us */ }
  }

  function aiuiAnnotateOn(frame, onPick) {
    var doc;
    try {
      doc = frame.contentDocument;
    } catch (e) {
      doc = null;
    }
    // No document means the app has not finished loading, or something
    // about this frame is not what we think. Either way there is nothing
    // to point at, and saying so beats a mode that quietly does nothing.
    if (!doc || !doc.body) return null;

    var style = doc.createElement('style');
    style.textContent = '.' + AIUI_MARK + '{outline:2px solid #6b73ff !important;'
      + 'outline-offset:1px;cursor:crosshair !important;}'
      + 'body{cursor:crosshair !important;}';
    doc.head.appendChild(style);

    var last = null;
    function onOver(e) {
      if (last) last.classList.remove(AIUI_MARK);
      last = e.target;
      if (last && last.classList) last.classList.add(AIUI_MARK);
    }
    function onClick(e) {
      // The app is live: a click would follow its links and submit its
      // forms, and the person is pointing, not using it.
      e.preventDefault();
      e.stopPropagation();
      var el = e.target;
      var said = String(el.textContent || '').trim();
      onPick({
        selector: aiuiSelectorFor(el),
        tag: (el.tagName || '').toLowerCase(),
        // What the AGENT is shown. 200 is plenty to describe an element.
        text: said.slice(0, 200),
        // What a direct swap MATCHES, and ONLY when this element's text
        // is one contiguous run.
        //
        // An element with element children of its own is not. The
        // heading
        //     <h1>A cup that<br>holds the heat,<br>not you back.</h1>
        // reads back as "A cup thatholds the heat,not you back", because
        // textContent contributes nothing for a <br>, and that string
        // appears nowhere in the file. The swap refused correctly and
        // said to ask the agent, which works, but a box that can only
        // refuse should not have been offered: this is knowable before
        // anything is typed (2026-11-12, from Ralph's screenshot).
        //
        // Never truncated either: a prefix match replaces the front of
        // the words and leaves the tail behind, which is a mangled page
        // rather than a failed change.
        full: (el.children && el.children.length === 0) ? said : ''
      });
    }
    doc.addEventListener('mouseover', onOver, true);
    doc.addEventListener('click', onClick, true);
    return { doc: doc, style: style, onOver: onOver, onClick: onClick };
  }

  // What the agent is told. The element is described three ways on
  // purpose: a selector it can search for, the tag, and the words the
  // person could see, because a selector alone is brittle and the visible
  // text is what they were actually pointing at.
  function aiuiAnnotatePrompt(pick, said) {
    var where = 'On the page, change this element:\n'
      + '- selector: ' + (pick.selector || '(unknown)') + '\n'
      + '- tag: <' + (pick.tag || '?') + '>\n';
    if (pick.text) where += '- it currently reads: "' + pick.text + '"\n';
    return where + '\nThe change: ' + said
      + '\n\nChange only that part. Leave the rest of the page alone.';
  }

  //: How long to wait on a change before letting go. An enhance is a
  //: build: minutes, not seconds.
  var AIUI_CHANGE_POLL_MS = 8000;
  var AIUI_CHANGE_GIVE_UP_MS = 30 * 60 * 1000;

  // A change asked for by pointing is a BUILD, so the build line already
  // says what it is doing. The only thing left is to show the result:
  // reload the frame once it lands, because an app whose code changed
  // five minutes ago and still shows the old page looks like the change
  // was ignored.
  function aiuiWatchChange(chatId, taskId, frame, started) {
    started = started || Date.now();
    fetch('/api/tasks/' + taskId, { headers: aiuiAuthHeaders() })
      .then(function (r) {
        if (r.status === 403 || r.status === 404) return 'stop';
        return r.ok ? r.json() : null;
      }).then(function (task) {
        if (task === 'stop') return true;
        if (!task) return false;
        var status = String(task.status || '');
        if (status === 'completed') {
          // Cache-busted: the app is served from its own URL and the
          // browser has every reason to believe it has not changed.
          try {
            var at = frame.src.split('#')[0].split('?')[0];
            frame.src = at + '?changed=' + Date.now();
          } catch (e) { /* the frame went away */ }
          aiuiBuildLine(chatId, 'The change is in. Reloading it.');
          aiuiWorkingDone(frame);
          setTimeout(function () { aiuiClearBuildLine(); }, 4000);
          return true;
        }
        if (status === 'failed') {
          aiuiBuildLine(chatId, 'That change did not work out. The app is'
                        + ' as it was.');
          // A strip still shimmering after a failure says work is
          // happening when none is.
          aiuiWorkingDone(frame);
          setTimeout(function () { aiuiClearBuildLine(); }, 8000);
          return true;
        }
        var said = String(task.build_step_said || '').trim();
        said = said ? said + '...' : 'Making that change...';
        aiuiBuildLine(chatId, said);
        // The same sentence where the app is, because the side panel
        // covers the chat the line above goes to.
        aiuiWorkingSay(frame, said);
        return false;
      }).catch(function () { return false; })
      .then(function (finished) {
        if (finished) return;
        if (Date.now() - started > AIUI_CHANGE_GIVE_UP_MS) {
          // Thirty minutes, reached without either ending above.
          aiuiWorkingDone(frame);
          return;
        }
        setTimeout(function () {
          aiuiWatchChange(chatId, taskId, frame, started);
        }, AIUI_CHANGE_POLL_MS);
      });
  }

  // ===== End annotate =====

  // ===== The app beside the chat =====
  //
  // Expanding used to make the panel taller in place, which is the cheap
  // half of what was asked for: the app should sit BESIDE the
  // conversation, with the message in the thread collapsed to a chip
  // naming it.
  //
  // The iframe is MOVED, never rebuilt. Recreating it reloads the app,
  // which throws away the scroll position and anything typed into it, and
  // the whole point of expanding is to look at the thing you were already
  // looking at.
  //: How wide the panel beside the chat is, in pixels.
  //:
  //: It was 50vw, decided once for every screen and every page. A landing
  //: page wants more than half of a 1920 screen and a short form wants
  //: less, and the conversation on the other side has the same argument
  //: in reverse (2026-11-12, Ralph: "user can't adjust the sizez in here
  //: to the left").
  //:
  //: The floor and the ceiling are not taste. Below the floor the panel
  //: is too narrow to render a page into; above the ceiling the chat it
  //: sits beside is a sliver with the handle on top of it, and neither
  //: has an obvious way back.
  var AIUI_SPLIT_MIN = 320;
  var AIUI_SPLIT_KEY = 'aiui-split-width';
  //: One arrow press.
  var AIUI_SPLIT_STEP = 64;

  function aiuiSplitMax() {
    // Always leaves the conversation something to be. Computed rather
    // than stored, because a window can be made smaller after the fact.
    return Math.max(AIUI_SPLIT_MIN,
                    Math.round(window.innerWidth * 0.85));
  }

  function aiuiClampSplit(px) {
    var n = Number(px);
    if (!isFinite(n)) return null;
    return Math.max(AIUI_SPLIT_MIN, Math.min(aiuiSplitMax(), Math.round(n)));
  }

  function aiuiSavedSplit() {
    var raw = null;
    try {
      raw = window.localStorage.getItem(AIUI_SPLIT_KEY);
    } catch (e) {
      raw = null;
    }
    // Half the window is what it has always been, and is still the right
    // answer for somebody who has never moved it.
    if (!raw) return aiuiClampSplit(Math.round(window.innerWidth / 2));
    return aiuiClampSplit(parseFloat(raw))
      || aiuiClampSplit(Math.round(window.innerWidth / 2));
  }

  function aiuiSaveSplit(px) {
    var clamped = aiuiClampSplit(px);
    if (!clamped) return;
    try {
      window.localStorage.setItem(AIUI_SPLIT_KEY, String(clamped));
    } catch (e) {
      // Storage switched off still resizes, it just does not remember.
    }
  }

  // The panel's left edge, as a control.
  //
  // Two things have to move with it, and both would be silent if they did
  // not: `pane.style.paddingRight` is the only thing keeping the panel off
  // the conversation, and the frame inside is SCALED to fit, so a panel
  // that changes width without re-fitting shows the app rendered for the
  // width it used to have.
  function aiuiSplitHandle(panel, pane, frame, holder) {
    var grip = document.createElement('div');
    grip.setAttribute('data-aiui-split-handle', '1');
    grip.setAttribute('role', 'separator');
    grip.setAttribute('aria-orientation', 'vertical');
    grip.setAttribute('aria-label',
                      'Resize the panel. Use the left and right arrows.');
    grip.setAttribute('tabindex', '0');
    grip.style.cssText = 'position:absolute;left:0;top:0;bottom:0;width:10px;'
      + 'cursor:ew-resize;touch-action:none;z-index:2;'
      + 'background:transparent;';

    function apply(px, remember) {
      var w = aiuiClampSplit(px);
      if (!w) return;
      panel.style.width = w + 'px';
      if (pane) pane.style.paddingRight = w + 'px';
      grip.setAttribute('aria-valuenow', String(w));
      aiuiFitDesktop(frame, holder);
      if (remember) aiuiSaveSplit(w);
    }

    function width() {
      return Math.round(panel.getBoundingClientRect().width);
    }

    grip.addEventListener('pointerdown', function (down) {
      down.preventDefault();
      // The panel is pinned to the RIGHT, so its width is the distance
      // from the pointer to that edge. Measured from the window rather
      // than from a start offset, which is what keeps the edge under the
      // finger when the drag outruns the pointer events.
      function move(e) { apply(window.innerWidth - e.clientX, false); }
      function up() {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        grip.style.background = 'transparent';
        aiuiSaveSplit(width());
      }
      grip.style.background = 'rgba(127,127,127,.22)';
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });

    grip.addEventListener('keydown', function (e) {
      var k = e.key;
      var now = width();
      // Left makes the panel WIDER, because its left edge is what moves.
      if (k === 'ArrowLeft') apply(now + AIUI_SPLIT_STEP, true);
      else if (k === 'ArrowRight') apply(now - AIUI_SPLIT_STEP, true);
      else if (k === 'Home') apply(AIUI_SPLIT_MIN, true);
      else if (k === 'End') apply(aiuiSplitMax(), true);
      else return;
      e.preventDefault();
    });

    grip.setAttribute('aria-valuenow', String(width()));
    return grip;
  }

  var aiuiSplit = null;

  // The element holding both the messages and the composer, found rather
  // than named: Open WebUI's class names change between versions, but the
  // pane is reliably the nearest ancestor of the message list that also
  // contains the message box.
  function aiuiChatPane() {
    var msgs = aiuiScroller();
    var input = aiuiComposer();
    if (!msgs || !input) return null;
    var node = msgs.parentElement;
    while (node && !node.contains(input)) node = node.parentElement;
    return node;
  }

  // How wide a site is laid out in the side panel. The panel is half the
  // window, about 700 px on a laptop, which is under most sites' breakpoint,
  // so they showed their phone layout with a hamburger menu (2026-11-10,
  // Lukas). Laid out at this width and scaled down, an app shows the layout
  // a computer gets.
  var AIUI_DESKTOP_W = 1280;

  // {width, height, scale} for a frame in a holder of this size; width and
  // height 0 and scale 1 mean "fill it as it is".
  function aiuiDesktopFit(holderW, holderH) {
    if (!holderW || holderW >= AIUI_DESKTOP_W) {
      return { width: 0, height: 0, scale: 1 };
    }
    var scale = holderW / AIUI_DESKTOP_W;
    return { width: AIUI_DESKTOP_W, height: Math.round(holderH / scale), scale: scale };
  }

  function aiuiFitDesktop(frame, holder) {
    var fit = aiuiDesktopFit(holder.clientWidth, holder.clientHeight);
    if (fit.scale === 1) {
      frame.style.width = '100%';
      frame.style.height = '100%';
      frame.style.transform = '';
      frame.style.transformOrigin = '';
      return;
    }
    frame.style.width = fit.width + 'px';
    frame.style.height = fit.height + 'px';
    frame.style.transform = 'scale(' + fit.scale + ')';
    frame.style.transformOrigin = '0 0';
  }

  function aiuiSplitClose() {
    if (!aiuiSplit) return;
    var s = aiuiSplit;
    aiuiSplit = null;
    if (s.onResize) window.removeEventListener('resize', s.onResize);
    // Home first, so the app is never parentless even for a tick.
    if (s.home && s.frame) {
      s.frame.style.transform = '';
      s.frame.style.transformOrigin = '';
      s.frame.style.width = '100%';
      s.frame.style.height = s.homeHeight;
      s.home.appendChild(s.frame);
    }
    // Home before the panel goes, or everything still inside it leaves
    // the document with it. Reversed so re-inserting one control never
    // moves the next one's anchor.
    for (var i = (s.moved || []).length - 1; i >= 0; i -= 1) {
      var m = s.moved[i];
      if (!m.home) continue;
      if (m.next && m.next.parentNode === m.home) {
        m.home.insertBefore(m.el, m.next);
      } else {
        m.home.appendChild(m.el);
      }
    }
    if (s.panel && s.panel.parentNode) s.panel.parentNode.removeChild(s.panel);
    if (s.chip && s.chip.parentNode) s.chip.style.display = 'none';
    if (s.bar) s.bar.style.display = '';
    if (s.bar) aiuiShowSizeHandle(s.bar, true);
    if (s.box) aiuiApplyAppWidth(s.box, aiuiSavedAppExtra());
    if (s.pane) s.pane.style.paddingRight = s.panePad;
    if (s.onKey) document.removeEventListener('keydown', s.onKey);
  }

  // `tools` are buttons from the thread's bar that belong in the panel's
  // head, and `footers` are the panels they open, which belong under the
  // app. Both are MOVED, never copied, for the same reason the iframe is:
  // these are live closures over this app's frame, and a copy would be a
  // second control wired to nothing.
  //
  // Both are optional, so a caller with no bar of its own still gets a
  // panel rather than a crash.
  function aiuiSplitOpen(slug, box, bar, frame, chip, tools, footers) {
    aiuiSplitClose();
    var pane = aiuiChatPane();
    if (!pane) return false;   // caller falls back to growing in place

    var wide = aiuiSavedSplit();
    var panel = document.createElement('div');
    panel.style.cssText = 'position:fixed;top:0;right:0;bottom:0;'
      + 'width:' + wide + 'px;'
      + 'z-index:9000;background:#0e0e10;display:flex;flex-direction:column;'
      + 'border-left:1px solid rgba(127,127,127,.3);';

    var head = document.createElement('div');
    head.style.cssText = 'display:flex;align-items:center;gap:.5rem;'
      + 'padding:.5rem .7rem;font-size:.85rem;color:#ededee;'
      + 'border-bottom:1px solid rgba(127,127,127,.25);flex:0 0 auto;';
    var name = document.createElement('span');
    name.textContent = slug;
    name.style.cssText = 'font-weight:600;flex:1 1 auto;overflow:hidden;'
      + 'text-overflow:ellipsis;white-space:nowrap;';
    var out = document.createElement('a');
    out.href = frame.src;
    out.target = '_blank';
    out.rel = 'noopener';
    out.textContent = aiuiGlyph('↗');
    out.title = 'Open in a new tab';
    out.setAttribute('aria-label', 'Open in a new tab');
    out.style.cssText = 'color:inherit;opacity:.65;text-decoration:none;'
      + 'padding:.1rem .35rem;';
    var shut = document.createElement('button');
    shut.type = 'button';
    shut.textContent = aiuiGlyph('✕');
    shut.title = 'Put it back in the chat';
    shut.setAttribute('aria-label', 'Put it back in the chat');
    shut.style.cssText = 'background:none;border:0;color:inherit;opacity:.65;'
      + 'cursor:pointer;font-size:.95rem;padding:.1rem .35rem;';
    shut.addEventListener('click', aiuiSplitClose);
    head.appendChild(name);
    head.appendChild(out);
    head.appendChild(shut);

    var holder = document.createElement('div');
    holder.style.cssText = 'flex:1 1 auto;min-height:0;overflow:hidden;';

    // Where each borrowed control came from, so closing the panel puts it
    // back where it was rather than merely back in the bar: a row of icons
    // has nothing but its order.
    var moved = [];
    function borrow(el, into, before) {
      if (!el) return;
      moved.push({ el: el, home: el.parentNode, next: el.nextSibling });
      if (before && before.parentNode === into) into.insertBefore(el, before);
      else into.appendChild(el);
    }

    var home = frame.parentNode;
    var homeHeight = frame.style.height;
    frame.style.height = '100%';
    holder.appendChild(frame);
    // Before the open-in-a-tab link, so the panel's own controls stay on
    // the right where they were.
    for (var t = 0; t < (tools || []).length; t += 1) {
      borrow(tools[t], head, out);
    }
    panel.appendChild(head);
    panel.appendChild(holder);
    for (var f = 0; f < (footers || []).length; f += 1) {
      borrow(footers[f], panel);
    }
    document.body.appendChild(panel);
    aiuiFitDesktop(frame, holder);
    // The edge, last so it sits above the head and the holder both.
    panel.appendChild(aiuiSplitHandle(panel, pane, frame, holder));
    function onResize() { aiuiFitDesktop(frame, holder); }
    window.addEventListener('resize', onResize);

    var panePad = pane.style.paddingRight;
    pane.style.paddingRight = wide + 'px';
    // The box left behind in the thread is empty once the app moves out.
    // Negative margins on an empty box push it out over the conversation,
    // and the pane sets its own size anyway.
    aiuiApplyAppWidth(box, 0);
    bar.style.display = 'none';
    aiuiShowSizeHandle(bar, false);
    chip.style.display = '';

    function onKey(e) { if (e.key === 'Escape') aiuiSplitClose(); }
    document.addEventListener('keydown', onKey);

    aiuiSplit = { panel: panel, frame: frame, home: home, bar: bar,
                  box: box, chip: chip, pane: pane, panePad: panePad,
                  moved: moved,
                  homeHeight: homeHeight, onKey: onKey, onResize: onResize };
    return true;
  }
  // A dark cover saying the app is loading, over `frame` inside `holder`,
  // gone when the frame's page has loaded. Still there after a while means
  // the page is slow or broken, and it says where else to look.
  var AIUI_COVER_SLOW_MS = 25000;

  // The shape of a page, in grey. A nav strip, a hero, and a couple of
  // lines of text.
  //
  // Shaped rather than blank on purpose. A flat rectangle reads as a broken
  // panel; a page-shaped one reads as a page on its way, which is the whole
  // difference between "this is loading" and "this is wrong".
  function aiuiSkeletonBody() {
    aiuiMotion();
    var body = document.createElement('div');
    body.style.cssText = 'display:flex;flex-direction:column;gap:.7rem;'
      + 'padding:.9rem 1rem;height:100%;box-sizing:border-box;';

    function block(css) {
      var b = document.createElement('div');
      b.className = 'aiui-shimmer';
      b.style.cssText = css;
      body.appendChild(b);
      return b;
    }

    // The nav: a mark on the left, a button on the right.
    var nav = document.createElement('div');
    nav.style.cssText = 'display:flex;align-items:center;gap:.6rem;';
    var mark = document.createElement('div');
    mark.className = 'aiui-shimmer';
    mark.style.cssText = 'height:.85rem;width:6rem;';
    var spacer = document.createElement('div');
    spacer.style.cssText = 'flex:1 1 auto;';
    var cta = document.createElement('div');
    cta.className = 'aiui-shimmer';
    cta.style.cssText = 'height:1.5rem;width:5rem;border-radius:999px;';
    nav.appendChild(mark);
    nav.appendChild(spacer);
    nav.appendChild(cta);
    body.appendChild(nav);

    block('height:2.1rem;width:72%;margin-top:.5rem;');
    block('height:2.1rem;width:58%;');
    block('height:.75rem;width:86%;margin-top:.3rem;');
    block('height:.75rem;width:64%;');
    block('flex:1 1 auto;min-height:1.5rem;');
    return body;
  }

  // A panel-shaped placeholder, drawn while a build runs so the finished
  // preview fills a space the eye already knows about.
  //
  // Ralph, 2026-11-11: "it popup showed soo long like user didnt notice it".
  // A build takes a minute, the step list says what is happening, and then
  // the panel appears in a part of the page that was not there a moment
  // before. Somebody who looked away misses it entirely.
  //
  // One at a time, by id: the watcher runs every few seconds and a skeleton
  // per scan would stack a column of them under the reply.
  function aiuiSkeletonPanel() {
    var found = document.getElementById('aiui-app-skeleton');
    if (found) return found;
    aiuiMotion();
    var box = document.createElement('div');
    box.id = 'aiui-app-skeleton';
    box.setAttribute('aria-hidden', 'true');
    // The same size as the panel that replaces it. A placeholder of a
    // different width is a layout jump dressed up as a loading state.
    box.setAttribute('data-aiui-indent', '3.75rem');
    box.setAttribute('data-aiui-widenable', '1');
    box.style.cssText = 'margin:.5rem 0 .25rem;max-width:' + AIUI_APP_MAXW
      + ';'
      + 'border:1px solid rgba(127,127,127,.28);border-radius:12px;'
      + 'overflow:hidden;background:rgba(127,127,127,.06);';

    var bar = document.createElement('div');
    bar.setAttribute('data-aiui-skeleton-bar', '1');
    bar.style.cssText = 'display:flex;align-items:center;gap:.5rem;'
      + 'padding:.45rem .6rem;'
      + 'border-bottom:1px solid rgba(127,127,127,.2);';
    var nameBlock = document.createElement('div');
    nameBlock.className = 'aiui-shimmer';
    nameBlock.style.cssText = 'height:.8rem;width:11rem;';
    bar.appendChild(nameBlock);

    var stage = document.createElement('div');
    stage.style.cssText = 'height:' + aiuiSavedAppHeight() + ';';
    stage.appendChild(aiuiSkeletonBody());

    box.appendChild(bar);
    box.appendChild(stage);
    aiuiApplyAppWidth(box, aiuiSavedAppExtra());
    return box;
  }

  // The preview's shape, under the reply, while a build runs.
  //
  // Drawn from the FIRST tick of the watcher rather than once the step
  // list arrives: that needs the task to have answered and its labels to
  // have loaded, which is seconds in, and until then a build in the chat
  // looked like nothing happening at all (2026-11-12, Ralph: "user didnt
  // know its loading and working on it").
  //
  // Once, however many polls there are, and only when there is a reply to
  // put it under: a chat just opened can answer its first poll before any
  // reply is drawn, and a panel put then goes to the end of the page and
  // stays there.
  function aiuiShowBuildGhost() {
    if (document.getElementById('aiui-app-skeleton')) return null;
    if (!aiuiLastReplyBody()) return null;
    var ghost = aiuiSkeletonPanel();
    ghost.style.marginLeft = '3.75rem';
    aiuiPutUnderLastMessage(ghost);
    return ghost;
  }

  function aiuiClearSkeletonPanel() {
    var el = document.getElementById('aiui-app-skeleton');
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  function aiuiCoverWhileLoading(holder, frame) {
    aiuiMotion();
    var cover = document.createElement('div');
    cover.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;'
      + 'display:flex;flex-direction:column;background:#141416;'
      + 'color:#cfcfd4;font-size:.8rem;overflow:hidden;';
    cover.appendChild(aiuiSkeletonBody());

    // Said only once it has been slow, because a panel that announces its
    // own loading before anything is wrong is noise.
    var said = document.createElement('div');
    said.style.cssText = 'display:none;padding:.5rem 1rem .8rem;'
      + 'text-align:center;opacity:.8;';
    cover.appendChild(said);
    holder.appendChild(cover);

    function gone() {
      if (cover.parentNode) cover.parentNode.removeChild(cover);
    }
    frame.addEventListener('load', gone);
    setTimeout(function () {
      if (!cover.parentNode) return;
      said.textContent = 'Still loading. If nothing appears, open it in a '
        + 'new tab.';
      said.style.display = 'block';
    }, AIUI_COVER_SLOW_MS);
    return cover;
  }

  // A thin shimmering strip across the TOP of the preview, saying what is
  // being done to it.
  //
  // Not `aiuiCoverWhileLoading`, which hides the whole frame behind a
  // skeleton. That is right for an app that has not arrived and wrong for
  // one being changed: an enhance takes minutes, and hiding somebody's
  // page for minutes to tell them it is busy costs more than it gives.
  // They are watching it precisely to see it change.
  //
  // Attached to whatever the frame's parent currently is, because the
  // frame MOVES between the thread and the side panel and the strip has
  // to appear in the one being looked at. The progress was already being
  // reported before this existed, by aiuiBuildLine into the CHAT, which
  // the side panel covers (2026-11-12, Ralph, watching an enhance with no
  // sign anything was happening).
  function aiuiWorkingSay(frame, said) {
    var holder = frame && frame.parentNode;
    if (!holder || !holder.appendChild) return null;
    aiuiMotion();

    // An absolutely positioned child escapes a static parent. The holder
    // is ours either way: the stage in the thread, or the panel's holder.
    var how = '';
    try {
      how = window.getComputedStyle(holder).position;
    } catch (e) { how = ''; }
    if (how === 'static' || !how) holder.style.position = 'relative';

    // Found again rather than stacked: the watcher calls this on every
    // poll, which is once every eight seconds for up to thirty minutes.
    var strip = holder.querySelector
      ? holder.querySelector('[data-aiui-working]') : null;
    if (!strip) {
      strip = document.createElement('div');
      strip.setAttribute('data-aiui-working', '1');
      strip.setAttribute('role', 'status');
      strip.setAttribute('aria-live', 'polite');
      strip.className = 'aiui-shimmer';
      strip.style.cssText = 'position:absolute;top:0;left:0;right:0;'
        + 'z-index:3;padding:.4rem .7rem;font-size:.78rem;'
        + 'color:#ededee;background-color:rgba(20,20,22,.92);'
        + 'border-radius:0;overflow:hidden;text-overflow:ellipsis;'
        + 'white-space:nowrap;pointer-events:none;';
      holder.appendChild(strip);
    }
    strip.textContent = said || 'Working on it...';
    return strip;
  }

  function aiuiWorkingDone(frame) {
    var holder = frame && frame.parentNode;
    var strip = holder && holder.querySelector
      ? holder.querySelector('[data-aiui-working]') : null;
    if (strip && strip.parentNode) strip.parentNode.removeChild(strip);
  }

  // Hide or show the grab bar that sits beside `bar`, by walking to the
  // panel they share.
  //
  // Called wherever the in-chat chrome is hidden, which today is the move
  // to the side pane. There the PANE owns the height and the stage left
  // behind in the thread is empty, so a grab bar under it would resize
  // something the person is not looking at.
  //
  // Finds nothing and does nothing for a panel that has no preview, which
  // is the video panel sharing this same split code.
  function aiuiShowSizeHandle(bar, shown) {
    var box = bar && bar.parentNode;
    var handle = box && box.querySelector
      ? box.querySelector('[data-aiui-size-handle]') : null;
    if (handle) handle.style.display = shown ? 'flex' : 'none';
  }

  // ===== The size of a preview is the person's =====

  function aiuiClampAppHeight(px) {
    var n = Number(px);
    if (!isFinite(n)) return null;
    return Math.max(AIUI_APP_MIN, Math.min(AIUI_APP_MAX, Math.round(n)));
  }

  // The remembered height as a CSS length, or the default.
  //
  // localStorage is editable, shared with everything else on this origin,
  // and survives a release that changes what a value means, so anything
  // unreadable falls back rather than being trusted.
  function aiuiSavedAppHeight() {
    var raw = null;
    try {
      raw = window.localStorage.getItem(AIUI_APP_H_KEY);
    } catch (e) {
      raw = null;
    }
    if (!raw) return AIUI_APP_H;
    var px = aiuiClampAppHeight(parseFloat(raw));
    return px ? px + 'px' : AIUI_APP_H;
  }

  function aiuiSaveAppHeight(px) {
    var clamped = aiuiClampAppHeight(px);
    if (!clamped) return;
    try {
      window.localStorage.setItem(AIUI_APP_H_KEY, String(clamped));
    } catch (e) {
      // A browser with storage switched off still resizes, it just does
      // not remember. Worth nothing happening rather than a thrown error
      // halfway through a drag.
    }
  }

  // The widest this box may grow BEYOND its column, in pixels.
  //
  // Measured against the column rather than the box, because the box's own
  // width already contains whatever extra is applied: measuring that would
  // compound on every drag and run off the screen in three pulls.
  function aiuiMaxAppExtra(box) {
    // Nothing that cannot be MEASURED is widened. A detached node, or
    // anything that is not a laid-out element, has no column to grow
    // beyond and no window to fit inside, so the honest allowance is
    // none rather than a guess at one.
    function widthOf(el) {
      if (!el || typeof el.getBoundingClientRect !== 'function') return null;
      try {
        return el.getBoundingClientRect().width;
      } catch (e) { return null; }
    }
    var colW = widthOf(box && box.parentElement);
    if (colW === null) colW = widthOf(box);
    if (colW === null || !window.innerWidth) return 0;
    var room = window.innerWidth - colW - (AIUI_APP_W_GUTTER * 2);
    return Math.max(0, Math.round(room));
  }

  function aiuiClampAppExtra(px, box) {
    var n = Number(px);
    if (!isFinite(n)) return 0;
    // Zero is the floor: a negative extra is a POSITIVE margin, which is a
    // preview shrinking away from a column that already fits it. Narrower
    // than the column is not something anybody asked for, and it has no
    // obvious way back.
    return Math.max(0, Math.min(aiuiMaxAppExtra(box), Math.round(n)));
  }

  // What was stored, floored but NOT fitted to a screen: the box is what
  // knows how much room there is, and it does that fitting in
  // aiuiApplyAppWidth, which is the only place a value reaches the page.
  // One clamp, at the one moment both the number and the box are known.
  function aiuiSavedAppExtra() {
    var raw = null;
    try {
      raw = window.localStorage.getItem(AIUI_APP_W_KEY);
    } catch (e) {
      raw = null;
    }
    var n = raw ? parseFloat(raw) : 0;
    return isFinite(n) ? Math.max(0, Math.round(n)) : 0;
  }

  function aiuiSaveAppExtra(px) {
    try {
      window.localStorage.setItem(AIUI_APP_W_KEY,
                                  String(Math.max(0, Math.round(px) || 0)));
    } catch (e) {
      // Same as the height: a browser with storage switched off still
      // resizes, it just does not remember. A thrown error halfway
      // through a drag is worse than forgetting.
    }
  }

  // The thread's avatar gutter for this box, kept as its own value.
  //
  // `marginLeft` used to carry two meanings at once: this gutter, which
  // both placement functions set to 0 when a panel goes inside a reply,
  // and half the extra width. Whichever was written last won, so a
  // widened panel snapped back to its column every time Open WebUI
  // rebuilt the message and the panel was re-placed.
  function aiuiIndentOf(box) {
    var raw = (box && box.getAttribute
               && box.getAttribute('data-aiui-indent')) || '0px';
    // A UNIT, always, because this value goes into calc().
    //
    // `calc(0 - 300px)` is invalid: calc will not subtract a length from
    // a unitless number, so the browser drops the whole declaration. The
    // right margin still applied, so a widened panel grew only to the
    // right and only by half of what was asked for.
    //
    // Measured inside Open WebUI's own reply markup on 2026-11-12:
    //     at rest        width 736  left 592  right 1328
    //     widened by 600 width 1036 left 592  right 1628
    // The left edge never moved, which is what "it still cannot be
    // widened in the chat" looked like from the outside.
    return (raw === '0' || raw === '') ? '0px' : raw;
  }

  // Set the gutter, and put the width back on top of it.
  //
  // Does nothing clever for a box that cannot be widened, which is the
  // video panel and the build panel: they share these placement
  // functions and have no width of their own to restore.
  function aiuiSetIndent(box, indent) {
    if (!box || !box.style) return;
    if (box.setAttribute) box.setAttribute('data-aiui-indent', indent);
    if (box.hasAttribute && box.hasAttribute('data-aiui-widenable')) {
      aiuiApplyAppWidth(box, aiuiSavedAppExtra());
      return;
    }
    box.style.marginLeft = indent;
  }

  // Widen the box by `extra` pixels, half on each side, and never by more
  // than the screen has room for.
  //
  // THE one place an extra reaches the page, so THE one place it is fitted
  // to the window. A stored value is editable, shared with everything else
  // on this origin, and survives a window being resized or a release that
  // changes what it means; clamping here covers the drag, the arrows and
  // the restore with a single rule.
  function aiuiApplyAppWidth(box, extra) {
    if (!box || !box.style) return 0;
    var fitted = aiuiClampAppExtra(extra, box);
    var half = fitted / 2;
    var indent = aiuiIndentOf(box);
    // Composed with the gutter rather than replacing it, so a widened
    // panel inside a reply keeps its indent and a widened panel in the
    // thread keeps the avatar's.
    box.style.marginLeft = half
      ? ('calc(' + indent + ' - ' + half + 'px)') : indent;
    box.style.marginRight = half ? (-half + 'px') : '';
    // Without this the margins move the box and the cap holds its width,
    // which is exactly what "it can only stretch up and down" looked
    // like.
    box.style.maxWidth = fitted ? 'none' : AIUI_APP_MAXW;
    return fitted;
  }

  // A grab bar under the preview. Drag it, or focus it and use the arrows.
  //
  // Keyboard as well as pointer because a drag-only control is a control
  // some people do not have, and this one is the only way to make a
  // letterboxed preview readable.
  function aiuiSizeHandle(frame, box) {
    var handle = document.createElement('div');
    handle.setAttribute('data-aiui-size-handle', '1');
    handle.setAttribute('role', 'separator');
    handle.setAttribute('aria-orientation', 'horizontal');
    handle.setAttribute('aria-label',
                        'Resize the preview. Drag it, or use the up and down'
                        + ' arrows for height and the left and right arrows'
                        + ' for width.');
    handle.setAttribute('tabindex', '0');
    handle.setAttribute('aria-valuemin', String(AIUI_APP_MIN));
    handle.setAttribute('aria-valuemax', String(AIUI_APP_MAX));
    handle.style.cssText = 'display:flex;align-items:center;'
      + 'justify-content:center;height:14px;cursor:move;'
      + 'border-top:1px solid rgba(127,127,127,.2);'
      + 'background:rgba(127,127,127,.06);touch-action:none;';

    var grip = document.createElement('div');
    grip.style.cssText = 'width:2.2rem;height:3px;border-radius:999px;'
      + 'background:rgba(127,127,127,.45);';
    handle.appendChild(grip);

    function height() {
      return Math.round(frame.getBoundingClientRect().height);
    }

    function apply(px, remember) {
      var clamped = aiuiClampAppHeight(px);
      if (!clamped) return;
      frame.style.height = clamped + 'px';
      handle.setAttribute('aria-valuenow', String(clamped));
      if (remember) aiuiSaveAppHeight(clamped);
    }

    handle.setAttribute('aria-valuenow', String(height()));

    // How much wider than its column the box is RIGHT NOW, read back off
    // the margins rather than kept in a variable here.
    //
    // A remembered copy drifts the moment anything else widens the box,
    // and something else does: the caller restores the saved width after
    // it puts the box in the page, because until then there is no column
    // to measure against and no window to fit inside. A cached number
    // would have the handle believing the box is 160 wider than the page
    // shows, and the first arrow press would jump.
    function extraNow() {
      var m = parseFloat((box && box.style && box.style.marginLeft) || 0);
      return isFinite(m) ? Math.max(0, Math.round(-m * 2)) : 0;
    }

    function widen(px, remember) {
      var now = aiuiApplyAppWidth(box, px);
      if (remember) aiuiSaveAppExtra(now);
      return now;
    }

    handle.addEventListener('pointerdown', function (down) {
      down.preventDefault();
      var startY = down.clientY;
      var startX = down.clientX;
      var startH = height();
      var startExtra = extraNow();
      // Listened for on the window rather than captured on the element:
      // a pointer dragged off a 14 pixel bar must not end the drag, and
      // this needs no pointer id to be right.
      function move(e) {
        apply(startH + (e.clientY - startY), false);
        // Twice the pointer's travel, because the box grows from both
        // edges at once: that is what keeps the right edge under the
        // finger that is dragging it.
        widen(startExtra + ((e.clientX - startX) * 2), false);
      }
      function up() {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        handle.style.background = 'rgba(127,127,127,.06)';
        aiuiSaveAppHeight(height());
        aiuiSaveAppExtra(extraNow());
      }
      handle.style.background = 'rgba(127,127,127,.16)';
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });

    handle.addEventListener('keydown', function (e) {
      var k = e.key;
      var now = height();
      // Up and down are height, left and right are WIDTH. They used to be
      // a second way to change the height, which left no key at all for
      // the direction somebody on a keyboard cannot drag.
      if (k === 'ArrowDown') apply(now + AIUI_APP_STEP, true);
      else if (k === 'ArrowUp') apply(now - AIUI_APP_STEP, true);
      else if (k === 'ArrowRight') widen(extraNow() + AIUI_APP_W_STEP, true);
      else if (k === 'ArrowLeft') widen(extraNow() - AIUI_APP_W_STEP, true);
      else if (k === 'Home') apply(AIUI_APP_MIN, true);
      else if (k === 'End') apply(AIUI_APP_MAX, true);
      else return;
      e.preventDefault();
    });

    return handle;
  }
  // ===== End app beside the chat =====

  // ===== Appearance =====
  //
  // Colours, type and spacing, changed live and saved only when asked.
  //
  // This panel can only move what the APP declares. A site restyles
  // instantly because its own stylesheet declares its palette as CSS
  // variables on :root and this writes those variables on the iframe's
  // root element; nothing is rebuilt and no file is touched until Save.
  //
  // Measured 2026-11-05: not one app in the repo declared a single CSS
  // variable, because the builder had never been asked for them. That is
  // why this panel has a second state at all: an app built before then
  // gets an offer to be upgraded rather than sliders that move nothing.
  //
  // The token list is SERVED, never copied here, for the same reason the
  // build steps are: one list, one place to change it.

  var AIUI_FONTS = [
    'system-ui, -apple-system, sans-serif',
    'Georgia, serif',
    '"Times New Roman", Times, serif',
    '"Helvetica Neue", Helvetica, Arial, sans-serif',
    '"Courier New", Courier, monospace',
    'Verdana, Geneva, sans-serif',
    '"Trebuchet MS", sans-serif',
    'Palatino, "Palatino Linotype", serif'
  ];

  function aiuiThemeRoot(frame) {
    // Same origin as the chat, so this is reachable. It can still be
    // null while the app is loading, which is a normal state and not an
    // error.
    try {
      var doc = frame && frame.contentDocument;
      return (doc && doc.documentElement) || null;
    } catch (e) { return null; }
  }

  function aiuiThemeSet(frame, name, value) {
    var root = aiuiThemeRoot(frame);
    if (!root) return false;
    root.style.setProperty(name, value);
    return true;
  }

  function aiuiThemeDrop(frame, names) {
    var root = aiuiThemeRoot(frame);
    if (!root) return;
    for (var i = 0; i < names.length; i++) root.style.removeProperty(names[i]);
  }

  function aiuiAppearance(chatId, slug, frame) {
    var wrap = document.createElement('div');
    wrap.style.cssText = 'display:none;padding:.6rem .7rem;'
      + 'border-top:1px solid rgba(127,127,127,.25);font-size:.85rem;';

    var body = document.createElement('div');
    wrap.appendChild(body);

    var loaded = false;
    var changed = {};          // only what this person actually moved
    var touched = [];          // every name we wrote, so Reset can clear it

    function say(text) {
      body.textContent = '';
      var line = document.createElement('div');
      line.style.cssText = 'opacity:.7;';
      line.textContent = text;
      body.appendChild(line);
    }

    function row(label) {
      var el = document.createElement('div');
      el.style.cssText = 'display:flex;align-items:center;gap:.5rem;'
        + 'margin:.3rem 0;';
      var name = document.createElement('span');
      name.textContent = label;
      name.style.cssText = 'flex:0 0 9rem;opacity:.75;';
      el.appendChild(name);
      return el;
    }

    function control(tok, current) {
      var el = row(tok.label);
      var input;

      if (tok.kind === 'color') {
        input = document.createElement('input');
        input.type = 'color';
        // A colour input can only hold #rrggbb. An app whose value is
        // rgb() or a shorthand still gets a working control; it just
        // starts from the default rather than lying about the value.
        input.value = /^#[0-9a-fA-F]{6}$/.test(current) ? current
          : (/^#[0-9a-fA-F]{6}$/.test(tok['default']) ? tok['default'] : '#000000');
        input.style.cssText = 'flex:0 0 auto;width:2.4rem;height:1.6rem;'
          + 'padding:0;border:1px solid rgba(127,127,127,.35);'
          + 'border-radius:6px;background:none;cursor:pointer;';
      } else if (tok.kind === 'font') {
        input = document.createElement('select');
        var options = AIUI_FONTS.slice();
        if (current && options.indexOf(current) < 0) options.unshift(current);
        for (var i = 0; i < options.length; i++) {
          var opt = document.createElement('option');
          opt.value = options[i];
          opt.textContent = options[i].replace(/["']/g, '').split(',')[0];
          input.appendChild(opt);
        }
        input.value = current || tok['default'];
        input.style.cssText = 'flex:1 1 auto;min-width:0;padding:.2rem .3rem;'
          + 'border:1px solid rgba(127,127,127,.35);border-radius:6px;'
          + 'background:transparent;color:inherit;font-size:.82rem;';
      } else {
        input = document.createElement('input');
        input.type = 'range';
        input.min = String(tok.low);
        input.max = String(tok.high);
        input.step = '0.05';
        input.value = String(parseFloat(current) || parseFloat(tok['default']) || 1);
        input.style.cssText = 'flex:1 1 auto;min-width:0;';
      }

      var shown = document.createElement('span');
      shown.style.cssText = 'flex:0 0 3rem;text-align:right;opacity:.6;'
        + 'font-size:.78rem;';
      if (tok.kind === 'scale') shown.textContent = input.value;

      function moved() {
        var value = input.value;
        changed[tok.name] = value;
        if (touched.indexOf(tok.name) < 0) touched.push(tok.name);
        if (tok.kind === 'scale') shown.textContent = value;
        if (!aiuiThemeSet(frame, tok.name, value)) {
          say('Wait for the app to finish loading, then open this again.');
        }
        dirty();
      }
      input.addEventListener('input', moved);
      input.addEventListener('change', moved);

      el.appendChild(input);
      el.appendChild(shown);
      return el;
    }

    var save, reset, status;

    function dirty() {
      var any = false;
      for (var k in changed) { if (changed.hasOwnProperty(k)) { any = true; break; } }
      if (save) save.disabled = !any;
      if (reset) reset.disabled = !any;
      if (status && any) status.textContent = 'Not saved yet';
    }

    function drawControls(state) {
      body.textContent = '';
      var hint = document.createElement('div');
      hint.style.cssText = 'opacity:.6;margin-bottom:.45rem;font-size:.78rem;';
      hint.textContent = 'Changes show straight away. Nothing is saved until '
        + 'you press Save.';
      body.appendChild(hint);

      for (var i = 0; i < state.tokens.length; i++) {
        var tok = state.tokens[i];
        body.appendChild(control(tok, state.values[tok.name] || ''));
      }

      var feet = document.createElement('div');
      feet.style.cssText = 'display:flex;align-items:center;gap:.45rem;'
        + 'margin-top:.55rem;';

      save = document.createElement('button');
      save.type = 'button';
      save.textContent = 'Save';
      save.disabled = true;
      save.style.cssText = 'padding:.3rem .7rem;border-radius:7px;'
        + 'border:1px solid rgba(127,127,127,.4);background:transparent;'
        + 'color:inherit;cursor:pointer;font-size:.82rem;';

      reset = document.createElement('button');
      reset.type = 'button';
      reset.textContent = 'Put it back';
      reset.disabled = true;
      reset.style.cssText = save.style.cssText + 'opacity:.75;';

      status = document.createElement('span');
      status.style.cssText = 'opacity:.6;font-size:.78rem;';

      reset.addEventListener('click', function () {
        aiuiThemeDrop(frame, touched);
        changed = {};
        touched = [];
        status.textContent = '';
        loaded = false;          // redraw from the file on next open
        load();
      });

      save.addEventListener('click', function () {
        save.disabled = true;
        status.textContent = 'Saving...';
        fetch('/api/aiuibuilder/' + encodeURIComponent(slug) + '/theme', {
          method: 'PUT',
          headers: aiuiAuthHeaders(),
          body: JSON.stringify({ values: changed })
        }).then(function (r) {
          return r.ok ? r.json() : r.json().then(function (j) {
            throw new Error(j.detail || 'that could not be saved');
          });
        }).then(function (state) {
          changed = {};
          status.textContent = 'Saved';
          dirty();
          // The values are in the app's own stylesheet now, so our
          // inline overrides are no longer the truth. Dropping them and
          // re-fetching is what proves the save actually took.
          //
          // A cache-busted src, and not merely as a matter of style.
          // Cloudflare rewrites this origin's no-cache to a four hour
          // max-age, so asking the frame to load itself again can be
          // handed the stylesheet as it was BEFORE the save: a save that
          // worked, showing nothing. A new query string is a different
          // URL to the cache. Same reason the change watcher does it
          // this way.
          //
          // The other way of spelling this is deliberately not written
          // anywhere above, comment included: a test forbids it in this
          // file and a string match cannot tell a mention from a call.
          aiuiThemeDrop(frame, touched);
          touched = [];
          frame.src = String(frame.src).split('?')[0]
            + '?changed=' + Date.now();
        }).catch(function (err) {
          save.disabled = false;
          status.textContent = String((err && err.message)
                                      || 'That did not save.');
        });
      });

      feet.appendChild(save);
      feet.appendChild(reset);
      feet.appendChild(status);
      body.appendChild(feet);
    }

    function drawOffer() {
      body.textContent = '';
      var line = document.createElement('div');
      line.style.cssText = 'opacity:.75;margin-bottom:.45rem;';
      line.textContent = 'This app was built before appearance changes '
        + 'existed, so it has no colours or fonts to move yet. I can lift '
        + 'the palette it already has into settings, without changing how '
        + 'it looks.';
      body.appendChild(line);

      var go = document.createElement('button');
      go.type = 'button';
      go.textContent = 'Make it changeable';
      go.style.cssText = 'padding:.3rem .7rem;border-radius:7px;'
        + 'border:1px solid rgba(127,127,127,.4);background:transparent;'
        + 'color:inherit;cursor:pointer;font-size:.82rem;';
      var how = document.createElement('span');
      how.style.cssText = 'opacity:.6;font-size:.78rem;margin-left:.45rem;';

      go.addEventListener('click', function () {
        go.disabled = true;
        how.textContent = 'Asking for that...';
        fetch('/api/aiuibuilder/' + encodeURIComponent(slug) + '/theme/upgrade', {
          method: 'POST',
          headers: aiuiAuthHeaders(),
          body: JSON.stringify({})
        }).then(function (r) {
          return r.ok ? r.json() : r.json().then(function (j) {
            throw new Error(j.detail || 'that could not be started');
          });
        }).then(function (made) {
          how.textContent = 'Working on it. This takes a few minutes.';
          // A normal build, so the watcher that already exists reports
          // it and reloads the frame. Nothing here polls.
          if (made && made.task_id) {
            aiuiWatchChange(chatId, made.task_id, frame);
            loaded = false;
          }
        }).catch(function (err) {
          go.disabled = false;
          how.textContent = String((err && err.message) || 'That did not work.');
        });
      });

      body.appendChild(go);
      body.appendChild(how);
    }

    function load() {
      if (loaded) return;
      say('Reading this app...');
      fetch('/api/aiuibuilder/' + encodeURIComponent(slug) + '/theme', {
        headers: aiuiAuthHeaders()
      }).then(function (r) {
        if (!r.ok) throw new Error('that could not be read');
        return r.json();
      }).then(function (state) {
        loaded = true;
        if (state && state.themeable) drawControls(state);
        else drawOffer();
      }).catch(function () {
        say('I could not read this app just now.');
      });
    }

    return {
      el: wrap,
      isOpen: function () { return wrap.style.display !== 'none'; },
      close: function () { wrap.style.display = 'none'; },
      open: function () { wrap.style.display = ''; load(); }
    };
  }

  function aiuiShowAppInline(chatId, slug, messageId) {
    if (aiuiChatIdFromUrl() !== chatId) return;
    if (!/^[a-z0-9][a-z0-9-]{0,80}$/.test(String(slug || ''))) return;
    // The placeholder has done its job the moment there is a real panel to
    // draw. One that outlives the thing it stands for is worse than no
    // placeholder at all.
    aiuiClearSkeletonPanel();
    var id = 'aiui-app-' + slug;
    var inReply = aiuiReplyFor(id, messageId);
    if (inReply === undefined) return;

    // Already drawn. It may be in the wrong reply: either from before
    // this chat knew which message announced the app, or because
    // aiuiPollBuild draws on the way past, before the closing message
    // that declares it has been written. Once the right reply is on the
    // page, move it there rather than leaving it in somebody else's
    // message.
    //
    // Moving a node with an iframe in it reloads that iframe, so the app
    // flickers once. That happens at most once per panel and is a far
    // smaller thing than a landing page sitting under a reply about a
    // shopping list.
    var drawn = document.getElementById(id);
    if (drawn) {
      if (inReply && !inReply.contains(drawn)) aiuiPutInReply(drawn, inReply);
      // Whether or not it moved: a rebuilt message can hand back a panel
      // whose inline styles were rewritten under it.
      aiuiApplyAppWidth(drawn, aiuiSavedAppExtra());
      return;
    }

    // The app's OWN published URL. main.py::serve_published_app injects
    // the project's Supabase url and anon key AT REQUEST TIME, so they
    // are in no file of the app. Anything that assembles the page another
    // way shows an app whose database quietly does not work, while the
    // same app in a tab works perfectly.
    var url = location.origin + '/tasks/preview-app/' + slug + '/';

    var box = document.createElement('div');
    box.id = id;
    // The gutter is an attribute as well as a margin, because the margin
    // is also where the extra width goes and the two have to compose.
    box.setAttribute('data-aiui-indent', '3.75rem');
    box.setAttribute('data-aiui-widenable', '1');
    box.style.cssText = 'margin:.5rem 0 1rem 3.75rem;max-width:'
      + AIUI_APP_MAXW + ';'
      + 'border:1px solid rgba(127,127,127,.28);border-radius:12px;'
      + 'overflow:hidden;background:rgba(127,127,127,.06);';

    var bar = document.createElement('div');
    bar.style.cssText = 'display:flex;align-items:center;gap:.5rem;'
      + 'padding:.45rem .6rem;font-size:.85rem;'
      + 'border-bottom:1px solid rgba(127,127,127,.2);';

    var dot = document.createElement('span');
    dot.textContent = aiuiGlyph('▣');
    dot.style.cssText = 'opacity:.55;';
    var name = document.createElement('button');
    name.type = 'button';
    name.textContent = slug;
    name.title = 'History, download, and where it came from';
    name.setAttribute('aria-label', name.title);
    name.style.cssText = 'font-weight:600;flex:1 1 auto;overflow:hidden;'
      + 'text-overflow:ellipsis;white-space:nowrap;text-align:left;'
      + 'background:none;border:0;color:inherit;cursor:pointer;font-size:.85rem;';
    name.addEventListener('click', function () { aiuiAppMenu(slug, name); });

    function iconBtn(glyph, label) {
      var el = document.createElement('button');
      el.type = 'button';
      el.textContent = glyph;
      el.title = label;
      el.setAttribute('aria-label', label);
      el.style.cssText = 'flex:0 0 auto;background:none;border:0;'
        + 'color:inherit;opacity:.6;cursor:pointer;font-size:.95rem;'
        + 'padding:.1rem .3rem;border-radius:6px;';
      el.addEventListener('mouseenter', function () { el.style.opacity = '1'; });
      el.addEventListener('mouseleave', function () { el.style.opacity = '.6'; });
      return el;
    }

    var frame = document.createElement('iframe');

    // What is left in the thread once the app moves out to the side: the
    // name, and a way back. Without it the message becomes a blank gap
    // and nothing says what the panel beside the chat belongs to.
    var chip = document.createElement('button');
    chip.type = 'button';
    chip.style.cssText = 'display:none;width:100%;text-align:left;'
      + 'background:none;border:0;color:inherit;cursor:pointer;'
      + 'padding:.55rem .7rem;font-size:.85rem;';
    chip.textContent = aiuiGlyph('▣') + '  ' + slug
      + '  ·  showing beside the chat';

    // Point at a part of the page and say what to change.
    var ask = document.createElement('div');
    ask.style.cssText = 'display:none;padding:.6rem .7rem;'
      + 'border-top:1px solid rgba(127,127,127,.25);';
    var asked = document.createElement('input');
    asked.type = 'text';
    asked.placeholder = 'What would you like to change?';
    asked.style.cssText = 'width:100%;padding:.45rem .55rem;border-radius:8px;'
      + 'border:1px solid rgba(127,127,127,.35);background:transparent;'
      + 'color:inherit;font-size:.88rem;';
    var askWhat = document.createElement('div');
    askWhat.style.cssText = 'font-size:.75rem;opacity:.6;margin-bottom:.35rem;'
      + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';

    // The fast half, and first because it is the one that is right most
    // often: change the words themselves. Asking the agent is a BUILD,
    // minutes and a commit, which is the right price for "make the hero
    // more dramatic" and the wrong one for a typo in a rating.
    var wordsRow = document.createElement('div');
    wordsRow.style.cssText = 'display:flex;gap:.4rem;align-items:center;'
      + 'margin-bottom:.45rem;';
    var words = document.createElement('input');
    words.type = 'text';
    words.setAttribute('aria-label', 'The words on the page');
    words.style.cssText = 'flex:1 1 auto;min-width:0;padding:.45rem .55rem;'
      + 'border-radius:8px;border:1px solid rgba(127,127,127,.35);'
      + 'background:transparent;color:inherit;font-size:.88rem;';
    var swapBtn = document.createElement('button');
    swapBtn.type = 'button';
    swapBtn.textContent = 'Replace';
    swapBtn.style.cssText = 'flex:0 0 auto;padding:.45rem .7rem;'
      + 'border-radius:8px;border:1px solid rgba(127,127,127,.35);'
      + 'background:rgba(127,127,127,.12);color:inherit;cursor:pointer;'
      + 'font-size:.82rem;';
    wordsRow.appendChild(words);
    wordsRow.appendChild(swapBtn);

    // Two inputs with nothing between them is a guessing game.
    var orLine = document.createElement('div');
    orLine.textContent = 'or ask for a change';
    orLine.style.cssText = 'font-size:.72rem;opacity:.5;margin-bottom:.3rem;';

    ask.appendChild(askWhat);
    ask.appendChild(wordsRow);
    ask.appendChild(orLine);
    ask.appendChild(asked);

    var picked = null;
    var mode = null;

    function annotateStop() {
      aiuiAnnotateOff(mode);
      mode = null;
      picked = null;
      ask.style.display = 'none';
      // The send disables the box and this hides it. Re-opening the pencil
      // shows the SAME input again, so without this a change that worked
      // still leaves a dead box behind, which is how it looked on
      // 2026-11-12: "once i submitted i cant type anymore it in".
      asked.disabled = false;
      asked.style.display = '';
      words.disabled = false;
      swapBtn.disabled = false;
      note.style.opacity = '.6';
      note.title = 'Point at something to change it';
      note.setAttribute('aria-label', note.title);
    }

    var note = iconBtn(aiuiGlyph('✎'), 'Point at something to change it');
    note.addEventListener('click', function () {
      if (mode) { annotateStop(); return; }
      mode = aiuiAnnotateOn(frame, function (pick) {
        picked = pick;
        askWhat.textContent = 'Changing: ' + (pick.text || pick.selector
                                              || pick.tag);
        ask.style.display = '';
        // An image, a spacer, a wrapper around other elements: there is
        // nothing to put in a words box, and an empty one only invites a
        // change that can be refused.
        var hasWords = !!pick.full;
        wordsRow.style.display = hasWords ? 'flex' : 'none';
        orLine.style.display = hasWords ? '' : 'none';
        words.value = pick.full || '';
        asked.value = '';
        if (hasWords) words.focus();
        else asked.focus();
      });
      if (!mode) {
        // Nothing to point at: the app has not finished loading, or this
        // frame is not one we can reach into. Saying so beats a button
        // that looks armed and does nothing.
        askWhat.textContent = 'Wait for the app to finish loading, then try again.';
        ask.style.display = '';
        asked.style.display = 'none';
        setTimeout(function () {
          ask.style.display = 'none';
          asked.style.display = '';
        }, 2600);
        return;
      }
      note.style.opacity = '1';
      note.title = 'Stop pointing';
      note.setAttribute('aria-label', note.title);
    });

    function doSwap() {
      var want = words.value.trim();
      if (!want || !picked || !picked.full) return;
      if (want === picked.full) {
        askWhat.textContent = 'Those are the same words.';
        return;
      }
      words.disabled = true;
      swapBtn.disabled = true;
      askWhat.textContent = 'Changing the words...';
      // Fast, but it still writes a file, commits and reloads, and in the
      // side panel this strip is the only thing that says so.
      aiuiWorkingSay(frame, 'Changing the words...');
      // Wrapped for the same reason the enhance below is: a `.catch`
      // cannot catch a throw raised while the request is still being
      // built, and the box would stay dead with nothing sent.
      try {
        fetch('/api/aiuibuilder/' + encodeURIComponent(slug) + '/text', {
          method: 'POST',
          headers: aiuiAuthHeaders(),
          body: JSON.stringify({ old: picked.full, new: want })
        }).then(function (r) {
          return r.ok ? r.json() : r.json().then(function (j) {
            throw new Error(j.detail || 'that could not be changed');
          });
        }).then(function () {
          // The file changed under a frame with every reason to believe
          // it did not, so the same cache-bust the build watcher uses.
          try {
            var at = frame.src.split('#')[0].split('?')[0];
            frame.src = at + '?changed=' + Date.now();
            frame.addEventListener('load', function once() {
              frame.removeEventListener('load', once);
              aiuiWorkingDone(frame);
            });
          } catch (e) { aiuiWorkingDone(frame); }
          annotateStop();
        }).catch(function (err) {
          aiuiWorkingDone(frame);
          words.disabled = false;
          swapBtn.disabled = false;
          askWhat.textContent = String((err && err.message)
                                       || 'That did not work.');
        });
      } catch (err) {
        aiuiWorkingDone(frame);
        words.disabled = false;
        swapBtn.disabled = false;
        askWhat.textContent = 'That could not be sent. Try again.';
      }
    }

    swapBtn.addEventListener('click', doSwap);
    words.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { annotateStop(); return; }
      if (e.key === 'Enter') { e.preventDefault(); doSwap(); }
    });

    asked.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { annotateStop(); return; }
      if (e.key !== 'Enter') return;
      var said = asked.value.trim();
      if (!said || !picked) return;
      asked.disabled = true;
      askWhat.textContent = 'Asking for that change...';
      // Wrapped because a `.catch` cannot catch a throw raised while
      // fetch's own arguments are still being built: there is no promise
      // yet. That is precisely what happened on 2026-11-12, when the
      // headers came from a function that is not in scope here. No request
      // went out and nothing ever re-enabled the box, so the feature
      // looked dead rather than broken.
      try {
        fetch('/api/aiuibuilder/' + encodeURIComponent(slug) + '/enhance', {
          method: 'POST',
          headers: aiuiAuthHeaders(),
          body: JSON.stringify({ prompt: aiuiAnnotatePrompt(picked, said) })
        }).then(function (r) {
          return r.ok ? r.json() : r.json().then(function (j) {
            throw new Error(j.detail || 'that could not be asked for');
          });
        }).then(function (made) {
          annotateStop();
          // The change is a BUILD, so it is watched like any other and the
          // panel reloads when it lands. Nothing here polls: the watcher
          // already does, and two pollers on one task is two answers.
          if (made && made.task_id) {
            aiuiWatchChange(chatId, made.task_id, frame);
          }
        }).catch(function (err) {
          asked.disabled = false;
          askWhat.textContent = String((err && err.message)
                                       || 'That did not work.');
        });
      } catch (err) {
        asked.disabled = false;
        askWhat.textContent = 'That could not be sent. Try again.';
      }
    });

    // Appearance: its own panel under the frame, like the pencil's.
    var look = aiuiAppearance(chatId, slug, frame);
    var paint = iconBtn(aiuiGlyph('◐'), 'Change the colours and type');
    paint.addEventListener('click', function () {
      if (look.isOpen()) {
        look.close();
        paint.style.opacity = '.6';
        return;
      }
      look.open();
      paint.style.opacity = '1';
    });

    var grow = iconBtn(aiuiGlyph('⤢'), 'Show it beside the chat');
    var big = false;
    grow.addEventListener('click', function () {
      if (aiuiSplit && aiuiSplit.frame === frame) {
        aiuiSplitClose();
        return;
      }
      if (aiuiSplitOpen(slug, box, bar, frame, chip,
                        [note, paint], [ask, look.el])) return;
      // No chat pane to shrink, so this markup is not what we expect.
      // Growing in place is worse than sitting beside the chat and much
      // better than a control that does nothing.
      big = !big;
      frame.style.height = big ? AIUI_APP_H_BIG : aiuiSavedAppHeight();
      grow.title = big ? 'Make it smaller' : 'Make it bigger';
      grow.setAttribute('aria-label', grow.title);
    });
    chip.addEventListener('click', aiuiSplitClose);

    var out = document.createElement('a');
    out.href = url;
    out.target = '_blank';
    out.rel = 'noopener';
    out.textContent = aiuiGlyph('↗');
    out.title = 'Open in a new tab';
    out.setAttribute('aria-label', 'Open in a new tab');
    out.style.cssText = 'flex:0 0 auto;color:inherit;opacity:.6;'
      + 'text-decoration:none;font-size:.95rem;padding:.1rem .3rem;';

    bar.appendChild(dot);
    bar.appendChild(name);
    bar.appendChild(note);
    bar.appendChild(paint);
    bar.appendChild(grow);
    bar.appendChild(out);

    // Our own app on our own origin, so not a trust boundary. The sandbox
    // is here so a built page cannot navigate the chat out from under the
    // person reading it.
    frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-same-origin allow-popups');
    frame.setAttribute('loading', 'lazy');
    frame.title = slug;
    frame.src = url;
    frame.style.cssText = 'display:block;width:100%;height:'
      + aiuiSavedAppHeight() + ';border:0;background:#fff;';

    // The frame sits in a holder so a cover can lie over it until the app's
    // page has loaded. Until then the panel was a blank white box
    // (2026-11-10, Lukas: "it needs an embed, which takes time").
    var stage = document.createElement('div');
    stage.style.cssText = 'position:relative;';
    stage.appendChild(frame);
    aiuiCoverWhileLoading(stage, frame);

    box.appendChild(bar);
    box.appendChild(chip);
    box.appendChild(stage);
    // Under the preview, above the ask box, so dragging it never covers
    // the thing being resized.
    box.appendChild(aiuiSizeHandle(frame, box));
    box.appendChild(ask);
    box.appendChild(look.el);
    if (inReply) aiuiPutInReply(box, inReply);
    else aiuiPutUnderLastMessage(box);
    // AFTER the box is in the page, never before. How much wider it may
    // grow is measured against the column it sits in and the window
    // around it, and a box with no parent has neither: restoring it
    // first produced a preview 568 pixels wider than the screen, caught
    // in a browser on 2026-11-12 and by nothing else.
    aiuiApplyAppWidth(box, aiuiSavedAppExtra());
  }
  // ===== The whole walk, not just the step it is on =====
  //
  // The line under a reply said one thing: the step it was on, and the
  // minutes. That is where the build is, and nothing about how much of
  // the job is behind it or still to come.
  //
  // The step's own sentence is deliberately not quoted in this comment.
  // A test forbids any of them appearing in this file, and a quotation
  // is indistinguishable from a copy to anything reading the source.
  //
  // The steps and their wording are SERVED, never copied here. Two places
  // already show a step to somebody, this and the build view, and a third
  // copy of those sentences would be a third place to change and a third
  // to fall out of step with the pipeline that writes them.
  // One list per lane, because there are two walks and they are
  // different lengths.
  //
  // A simple site is written by one model call and walks three steps in
  // under a minute. The agent walks six over several minutes. Drawing
  // the agent's six against a light build would show somebody a bar that
  // is wrong about how much is left, which is the opposite of what this
  // panel is for. The task says which lane it is on.
  var AIUI_STEPS = {};
  var aiuiStepsAsked = {};
  // What to call the lane, served with its steps. Not written here: the
  // reply itself says in words why a build took the slow lane, and two
  // copies of that vocabulary is two places to change.
  var AIUI_LANE_SAID = {};

  function aiuiLaneOf(task) {
    var lane = String((task && task.build_lane) || 'agent');
    return lane === 'light' ? 'light' : 'agent';
  }

  function aiuiLoadSteps(lane) {
    var key = lane === 'light' ? 'light' : 'agent';
    if (aiuiStepsAsked[key]) return Promise.resolve(AIUI_STEPS[key]);
    aiuiStepsAsked[key] = true;
    return fetch('/api/tasks/build-steps?lane=' + encodeURIComponent(key),
                 { headers: aiuiAuthHeaders() })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (body) {
        AIUI_STEPS[key] = (body && body.steps) || null;
        AIUI_LANE_SAID[key] = (body && body.said) || '';
        return AIUI_STEPS[key];
      }).catch(function () { return null; });
  }

  // done | working | waiting, for every step, from the one the build says
  // it is on.
  //
  // A step the build SKIPPED also reads as done: autofix only runs when
  // the browser check found something, and the row carries only the step
  // it is on, not the ones it passed. Saying "done" for a step that was
  // not needed is a small lie; leaving it "waiting" while the build is
  // three steps further on is a confusing one.
  function aiuiStepStates(steps, at) {
    var now = -1;
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].key === at) { now = i; break; }
    }

    // A build that has not said which step it is on yet is still a build
    // that is running, and it is running the FIRST step. Saying nothing
    // is happening, six times over, is both untrue and the thing Ralph
    // saw on 2026-11-05: a minute in, every row read "Waiting".
    //
    // Only when the build has said NOTHING. A step we do not recognise
    // means it is somewhere we cannot place, out of band on a guard or a
    // question, and claiming it is back at step one would be a guess
    // dressed up as progress.
    if (now < 0 && !at) now = 0;

    return steps.map(function (s, i) {
      var state = 'waiting';
      if (now >= 0) state = (i < now) ? 'done' : (i === now ? 'working' : 'waiting');
      return { key: s.key, said: s.said, state: state };
    });
  }

  function aiuiStepPanel(chatId, task, mins) {
    if (aiuiChatIdFromUrl() !== chatId) return false;
    // The walk THIS build is on, not whichever list was fetched first.
    var steps = AIUI_STEPS[aiuiLaneOf(task)];
    if (!steps || !steps.length) return false;

    var at = String((task && task.build_step) || '');
    var rows = aiuiStepStates(steps, at);
    var el = document.getElementById('aiui-steps');
    if (!el) {
      if (!aiuiLastReplyBody()) return false;
      aiuiMotion();
      el = document.createElement('div');
      el.id = 'aiui-steps';
      el.style.cssText = 'margin:.4rem 0 .6rem 3.75rem;max-width:46rem;'
        + 'border:1px solid rgba(127,127,127,.28);border-radius:12px;'
        + 'font-size:.85rem;';
      aiuiPutUnderLastMessage(el);

      // The placeholder is NOT drawn here any more. It used to be, because
      // this was the earliest thing that ran; the watcher now draws it on
      // its first tick, before this panel's labels have even been
      // fetched, which is seconds earlier and the whole point. Two
      // callers would be two places to change and one chance to drift.
    }

    var done = 0;
    // The padding lives on an inner element. aiuiPutUnderLastMessage sets
    // a box's own paddingLeft to 0, because it is built for boxes that
    // carry the thread's indent, and live the text sat against the border
    // (2026-11-10).
    var html = '<div style="padding:.6rem .75rem;">';

    // Which lane, above the steps. A simple site walks three in under a
    // minute and the full builder walks six over several, and until
    // 2026-11-06 the only difference a person could see was that one of
    // them seemed broken. Nothing is drawn when the name has not arrived.
    var laneName = AIUI_LANE_SAID[aiuiLaneOf(task)] || '';
    if (laneName) {
      html += '<div style="font-size:.72rem;letter-spacing:.04em;'
        + 'text-transform:uppercase;opacity:.5;margin-bottom:.4rem;">'
        + aiuiEscape(laneName) + '</div>';
    }

    rows.forEach(function (s) { if (s.state === 'done') done += 1; });
    html += aiuiStepRows(rows);

    // Out of band: not a stage on the way to a finished app, so it is said
    // underneath rather than drawn as one of the numbered steps.
    var said = String((task && task.build_step_said) || '').trim();
    var known = rows.some(function (s) { return s.key === at; });
    if (at && !known && said) {
      html += '<div style="margin-top:.35rem;font-size:.8rem;opacity:.8;">'
        + aiuiEscape(said) + '</div>';
    }

    var pct = Math.round((done / rows.length) * 100);
    html += '<div style="margin-top:.5rem;height:3px;border-radius:999px;'
      + 'background:rgba(127,127,127,.2);overflow:hidden;">'
      + '<div style="height:100%;width:' + pct + '%;background:#6b73ff;'
      + 'transition:width .4s ease;"></div></div>'
      + '<div style="margin-top:.3rem;font-size:.72rem;opacity:.5;">'
      + mins + ' min so far</div></div>';
    el.innerHTML = html;
    return true;
  }

  function aiuiClearSteps() {
    var el = document.getElementById('aiui-steps');
    if (el && el.parentNode) el.parentNode.removeChild(el);
    // A build that ended with no app, because it failed, must not leave a
    // preview-shaped ghost waiting for one that is never coming.
    aiuiClearSkeletonPanel();
  }

  // The numbered rows with their Done / Working on it / Waiting pills, for
  // a build and for a video alike. The pill of the step in progress pulses,
  // so a panel that has not changed for a minute still reads as alive
  // (2026-11-10, Lukas: "some nicer loading thing").
  function aiuiStepRows(rows) {
    var html = '';
    rows.forEach(function (s, i) {
      var pill = s.state === 'done' ? 'Done'
               : (s.state === 'working' ? 'Working on it' : 'Waiting');
      var colour = s.state === 'done' ? 'rgba(80,200,120,.18);color:#4ec37a'
                 : (s.state === 'working' ? 'rgba(107,115,255,.22);color:#9aa2ff'
                                          : 'rgba(127,127,127,.15);color:inherit');
      html += '<div style="display:flex;gap:.5rem;align-items:baseline;'
        + 'padding:.18rem 0;' + (s.state === 'waiting' ? 'opacity:.55;' : '')
        + '"><span style="opacity:.5;min-width:1rem;">' + (i + 1) + '</span>'
        + '<span style="flex:1 1 auto;">' + aiuiEscape(s.said) + '</span>'
        + '<span' + (s.state === 'working' ? ' class="aiui-working"' : '')
        + ' style="flex:0 0 auto;font-size:.7rem;padding:.05rem .4rem;'
        + 'border-radius:999px;white-space:nowrap;background:' + colour + ';">'
        + pill + '</span></div>';
    });
    return html;
  }

  // One stylesheet for the motion in these panels, added once. Off for
  // anybody whose system asks for less motion.
  function aiuiMotion() {
    if (document.getElementById('aiui-motion')) return;
    var st = document.createElement('style');
    st.id = 'aiui-motion';
    st.textContent = '@keyframes aiui-pulse{0%,100%{opacity:1}50%{opacity:.45}}'
      + '@keyframes aiui-slide{0%{transform:translateX(-100%)}'
      + '100%{transform:translateX(250%)}}'
      + '@keyframes aiui-shimmer{0%{background-position:-150% 0}'
      + '100%{background-position:250% 0}}'
      + '.aiui-working{animation:aiui-pulse 1.6s ease-in-out infinite;}'
      + '.aiui-sliding{width:40%;animation:aiui-slide 1.6s ease-in-out infinite;}'
      // Grey on grey, so it reads the same in either theme without this
      // file knowing which one is on.
      + '.aiui-shimmer{border-radius:6px;background-size:300% 100%;'
      + 'background-image:linear-gradient(90deg,rgba(127,127,127,.13) 25%,'
      + 'rgba(127,127,127,.27) 37%,rgba(127,127,127,.13) 63%);'
      + 'animation:aiui-shimmer 1.8s ease-in-out infinite;}'
      + '@media (prefers-reduced-motion: reduce){'
      + '.aiui-working,.aiui-sliding,.aiui-shimmer{animation:none;}}';
    (document.head || document.body).appendChild(st);
  }

  // Every sentence here is ours and fixed, but it reaches innerHTML, and
  // "ours today" is how an escaping hole starts.
  function aiuiEscape(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  // ===== End the whole walk =====

  function aiuiBuildLine(chatId, text) {
    if (aiuiChatIdFromUrl() !== chatId) return;
    var el = document.getElementById('aiui-build-line');
    if (!el) {
      // A chat just opened can answer its first poll before any reply is
      // on screen, and a line put at the end of the page is never seen and
      // never moved. The next poll draws it.
      if (!aiuiLastReplyBody()) return;
      el = document.createElement('div');
      el.id = 'aiui-build-line';
      el.style.cssText = 'padding:.25rem 0 .75rem 3.75rem;opacity:.65;font-size:.9rem;';
      aiuiPutUnderLastMessage(el);
    }
    el.textContent = text;
  }

  function aiuiClearBuildLine() {
    var el = document.getElementById('aiui-build-line');
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  // Resolves true when the build is closed (written now, or by another tab
  // already), false to try again on the next tick. Written under the
  // current tail, and only when that tail is a finished reply: while the
  // person's next message is being answered, writing would race Open
  // WebUI's own save of it.
  function aiuiCloseBuild(chatId, id, text) {
    return aiuiCloseWith(chatId, [aiuiBuildDoneMarker(id),
                                  aiuiLegacyBuildMarker(id)], text);
  }

  // The same write, for anything that watches something and reports once.
  // Generalised when the video watcher arrived rather than copied, because
  // two copies of "append a message to somebody's chat without racing Open
  // WebUI's own save" is two chances to get that wrong.
  function aiuiCloseWith(chatId, markers, text) {
    return aiuiFetchChat(chatId).then(function (fresh) {
      var fh = fresh.chat.history;
      var chain = aiuiChainFromHistory(fh);
      if (aiuiIsClosed(chain, markers)) return true;
      var tail = chain[chain.length - 1];
      if (!tail || tail.role !== 'assistant' || tail.done !== true) return false;
      var newId = aiuiUuid();
      fh.messages[newId] = {
        id: newId, parentId: tail.id, childrenIds: [], role: 'assistant',
        content: text, model: tail.model, modelName: tail.modelName, modelIdx: 0,
        done: true, timestamp: Math.floor(Date.now() / 1000)
      };
      tail.childrenIds = (tail.childrenIds || []).concat([newId]);
      fh.currentId = newId;
      return aiuiSaveChat(chatId, { history: fh }).then(function () {
        // The message just written is what declares the app.
        aiuiSavedRead.force = true;
        if (aiuiChatIdFromUrl() === chatId) aiuiSoftReload(chatId);
        return true;
      }, function () { return false; });
    }, function () { return false; });
  }

  function aiuiPollBuild(chatId, id, started) {
    // Before the fetch, not after it: the wait for the first answer is
    // the wait this covers.
    aiuiShowBuildGhost();
    fetch('/api/tasks/' + id, { headers: aiuiAuthHeaders() }).then(function (r) {
      // Not this person's build, or gone: nothing to report, ever.
      if (r.status === 403 || r.status === 404) return 'stop';
      return r.ok ? r.json() : null;
    }).then(function (task) {
      if (task === 'stop') return true;
      if (!task) return false;
      var text = aiuiBuildOutcome(task, id, location.origin);
      if (text) {
        aiuiHideBuildInline(id);
        aiuiClearSteps();
        // Drawn on the way past, not after the write: closing can take
        // another tick or be done by another tab, and the person is
        // looking at the chat NOW.
        if (String(task.status || '') === 'completed' && task.built_app_slug) {
          aiuiShowAppInline(chatId, task.built_app_slug);
        }
        return aiuiCloseBuild(chatId, id, text);
      }
      // What it is DOING, when the build has said. A timer tells somebody
      // the thing is alive and nothing about whether it is nearly done,
      // stuck on a browser check, or rolling back a change that broke the
      // app. build_step is the build's own word for the step it is on, in
      // the language of the person who asked for a website.
      //
      // Minutes stay as the fallback, which is every build that predates
      // this and any build between steps.
      var mins = Math.max(1, Math.round((Date.now() - started) / 60000));
      // ONE view of a running build, not two.
      //
      // The step list and the embedded build page say the same thing, and
      // showing both gave a reply a numbered list under a tall panel whose
      // preview area is empty for the whole build. The list is the better
      // of the two: it is compact, it says what every step is, and it says
      // which one is happening now.
      //
      // The embedded page stays as the fallback, for exactly the case the
      // list cannot cover: the labels could not be fetched. A build must
      // never go quiet because a list of words did not arrive.
      aiuiLoadSteps(aiuiLaneOf(task)).then(function () {
        // Nothing until a reply is on screen. A chat just opened can answer
        // its first poll before any reply is drawn, and a panel put then
        // went to the end of the page and stayed there (2026-11-10, Lukas:
        // "it sometimes didn't show up"). The next poll draws it.
        if (!aiuiLastReplyBody()) return;
        if (aiuiStepPanel(chatId, task, mins)) {
          aiuiClearBuildLine();
          aiuiHideBuildInline(id);
          return;
        }
        // Drawn here and not when the watch starts, because by now the
        // task has answered and is known to be a real build this person
        // may see.
        aiuiShowBuildInline(chatId, id);
        var step = String((task && task.build_step_said) || '').trim();
        aiuiBuildLine(chatId, step
          ? step + '. ' + mins + ' min so far.'
          : 'Still building, ' + mins + ' min so far. '
            + 'A message will appear here when it is done.');
      });
      return false;
    }).catch(function () { return false; }).then(function (finished) {
      if (finished || Date.now() - started > AIUI_BUILD_GIVE_UP_MS) {
        aiuiClearBuildLine();
        aiuiClearSteps();
        return;
      }
      setTimeout(function () { aiuiPollBuild(chatId, id, started); }, AIUI_BUILD_POLL_MS);
    });
  }

  // From the page scan, at most once every few seconds. Reads the rendered
  // rows first, which costs nothing, and fetches the stored chat only when
  // a build link it is not already watching turns up.
  // ===== What the saved messages declare =====
  //
  // A declared artifact is a markdown link reference definition, on
  // purpose: the parser consumes it and the person never sees it. That
  // means it is never in the rendered page either, so a scan of the page
  // can only find nothing. Measured live 2026-11-09: the saved message held
  // "[aiui-artifact]: #app/<slug>", the page held neither that nor a
  // preview link, and the chat said "is built." with nothing to look at.
  // It had worked only while replies still carried a link (#127 and #129
  // removed the last one).
  //
  // So this reads the saved chat. One fetch when the thread has changed
  // and then held still, because a thread still streaming is not saved
  // yet. What it found is kept and drawn again on every scan, because Open
  // WebUI rebuilds a message when it changes and throws our panel away.
  var aiuiSavedRead = { chat: '', key: '', last: '', busy: false, force: false,
                        chain: null, apps: [], videos: [] };
  var aiuiVideoJobs = {};

  // Each app the chat declares, with the last message to mention it, so
  // its panel sits in the reply that announced it.
  function aiuiSavedApps(chain) {
    var where = {}, order = [];
    (chain || []).forEach(function (m) {
      if (!m || m.role !== 'assistant') return;
      aiuiArtifactIds(m.content, 'app').forEach(function (slug) {
        if (!(slug in where)) order.push(slug);
        where[slug] = m.id;
      });
    });
    return order.map(function (slug) {
      return { slug: slug, messageId: where[slug] };
    });
  }

  // Each finished video, with the message that closed it.
  function aiuiSavedVideos(chain) {
    var out = [], seen = {};
    (chain || []).forEach(function (m) {
      if (!m || m.role !== 'assistant') return;
      aiuiVideoIdsIn(m.content).forEach(function (id) {
        if (seen[id]) return;
        seen[id] = true;
        var marker = aiuiVideoDoneMarker(id);
        var closing = chain.filter(function (c) {
          return c && String(c.content || '').indexOf(marker) >= 0;
        })[0];
        if (closing) out.push({ id: id, messageId: closing.id });
      });
    });
    return out;
  }

  // The reply a panel belongs to: the element, null for "whichever reply is
  // last", or undefined for "not on screen yet, ask again on the next scan".
  // Three scans of waiting, so a row that never appears still gets its
  // panel somewhere.
  function aiuiReplyFor(key, messageId) {
    // null means "no particular reply", which every caller turns into the
    // last one. undefined means "the right one is not on the page yet",
    // which means draw nothing and look again.
    //
    // It used to count three looks and then answer null. Ralph,
    // 2026-11-10: a landing page panel was sitting under a reply about a
    // ClickUp task, fifteen messages below the one that announced it. The
    // message had simply not painted yet, and a burst from the mutation
    // observer spends three looks in milliseconds, so "not yet" was read
    // as "never" and the panel was planted in whatever the conversation
    // had got to since. Not drawing yet is recoverable, the scan runs
    // again every few seconds; drawing it inside somebody else's message
    // is not.
    if (!messageId) return null;
    var row = document.getElementById('message-' + messageId);
    var body = row ? row.querySelector('.chat-assistant') : null;
    return body || undefined;
  }

  //: The message row a node sits in, found by walking up.
  //
  //: Deliberately not closest('[id^="message-"]'). That prefix also
  //: matches message-input-container, the COMPOSER, which is the bug this
  //: page shipped twice, and a blanket test forbids the selector anywhere
  //: in this file so that it cannot come back by a different route.
  function aiuiMessageRowOf(node) {
    for (var up = node; up; up = up.parentElement) {
      if (String(up.id || '').indexOf('message-') === 0) return up;
    }
    return null;
  }

  //: The id out of a message row, or '' for anything that is not one.
  //
  //: The composer is still refused by name, because walking up from a
  //: .chat-assistant should never reach it and a guard that only holds
  //: while an assumption holds is worth having.
  function aiuiMessageIdOf(row) {
    var id = row ? String(row.id || '') : '';
    if (id.indexOf('message-') !== 0) return '';
    var rest = id.slice(8);
    return rest === 'input-container' ? '' : rest;
  }

  //: Which assistant message announced each app, read one message at a
  //: time so a slug is never separated from the reply it belongs to.
  //
  //: This replaces a scan of the whole thread's innerHTML as one blob.
  //: A blob cannot say which message anything came from, so everything it
  //: found was placed by the fallback above, by construction. It also
  //: could not tell a declaration from an echo: a panel's own iframe src
  //: carries the slug, so once a panel was in the wrong message the scan
  //: kept finding it there and agreeing. The EARLIEST message naming an
  //: app is the one that announced it, so the first wins.
  //
  //: Only .chat-assistant, so a link somebody pasted in their own message
  //: is not the platform saying it built something.
  function aiuiAppsDeclaredIn(thread) {
    var out = [];
    if (!thread) return out;
    var seen = {};
    var bodies = thread.querySelectorAll('.chat-assistant');
    for (var i = 0; i < bodies.length; i++) {
      var body = bodies[i];
      var mid = aiuiMessageIdOf(aiuiMessageRowOf(body));
      if (!mid) continue;
      var slugs = aiuiArtifactIds(body.innerHTML, 'app');
      for (var j = 0; j < slugs.length; j++) {
        if (seen[slugs[j]]) continue;
        seen[slugs[j]] = true;
        out.push({ slug: slugs[j], messageId: mid });
      }
    }
    return out;
  }

  function aiuiPutInReply(box, body) {
    // The reply already has the avatar gutter, as in aiuiPutUnderLastMessage.
    aiuiSetIndent(box, '0');
    box.style.paddingLeft = '0';
    body.appendChild(box);
    // Again once it is in the page, because the width it may grow to is
    // measured against the column it sits in.
    aiuiSetIndent(box, '0');
  }

  function aiuiDrawSavedVideo(chatId, video) {
    if (video.id in aiuiVideoJobs) {
      if (aiuiVideoJobs[video.id]) {
        aiuiShowVideoInline(chatId, aiuiVideoJobs[video.id], video.id, video.messageId);
      }
      return;
    }
    // Asked once per video per page, however many scans there are.
    aiuiVideoJobs[video.id] = null;
    fetch('/api/video-jobs/' + video.id, { headers: aiuiAuthHeaders() }).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (job) {
      if (!job || String(job.status || '') !== 'done') return;
      aiuiVideoJobs[video.id] = job;
      aiuiShowVideoInline(chatId, job, video.id, video.messageId);
    }).catch(function () { /* the closing message still says it is ready */ });
  }

  function aiuiDrawSaved(chatId) {
    var s = aiuiSavedRead;
    if (s.chat !== chatId || !s.chain) return;
    s.apps.forEach(function (a) { aiuiShowAppInline(chatId, a.slug, a.messageId); });
    s.videos.forEach(function (v) { aiuiDrawSavedVideo(chatId, v); });
  }

  function aiuiWatchSavedBuilds(chatId, chain) {
    var nowS = Math.floor(Date.now() / 1000);
    chain.forEach(function (m) {
      if (!m || m.role !== 'assistant') return;
      aiuiBuildIdsIn(m.content).forEach(function (id) {
        if (aiuiBuildWatched[id]) return;
        aiuiBuildWatched[id] = true;
        if (aiuiBuildIsClosed(chain, id)) return;
        if (nowS - Number(m.timestamp || 0) > AIUI_BUILD_RECENT_S) return;
        aiuiPollBuild(chatId, id, Number(m.timestamp) * 1000 || Date.now());
      });
    });
  }

  function aiuiReadSaved(chatId, html) {
    var s = aiuiSavedRead;
    if (s.chat !== chatId) {
      s.chat = chatId;
      s.key = s.last = '';
      s.chain = null;
      s.apps = [];
      s.videos = [];
      s.force = true;
    }
    aiuiDrawSaved(chatId);
    var key = String(html.length);
    var settled = s.force || key === s.last;
    s.last = key;
    if (!settled || s.busy || (key === s.key && !s.force)) return Promise.resolve();
    s.busy = true;
    s.force = false;
    return aiuiFetchChat(chatId).then(function (data) {
      s.busy = false;
      if (s.chat !== chatId) return;
      s.key = key;
      s.chain = aiuiChainFromHistory(data.chat.history);
      var chain = s.chain;
      s.apps = aiuiSavedApps(chain);
      s.videos = aiuiSavedVideos(chain);
      aiuiDrawSaved(chatId);
      aiuiWatchVideos(chain, chatId);
      aiuiWatchSavedBuilds(chatId, chain);
    }, function () {
      s.busy = false;
      s.force = true;
    });
  }
  // ===== End what the saved messages declare =====

  function aiuiWatchBuilds() {
    var chatId = aiuiChatIdFromUrl();
    if (!chatId) return;
    var now = Date.now();
    if (now - aiuiBuildLastLook < AIUI_BUILD_LOOK_MS) return;
    aiuiBuildLastLook = now;
    var thread = aiuiThread();
    var html = thread ? thread.innerHTML : '';

    // The apps this chat already says it has, drawn from the messages
    // themselves rather than from a build we happen to be watching.
    //
    // This is deliberately BEFORE the early return below. The panel
    // used to be drawn in one place only, the moment the watcher saw a
    // build finish, so a finished build showed its app in exactly one
    // tab and once: reload, and the build is closed, the watcher skips
    // it, and the chat is a bare link again. The chat still says which
    // app it built, so that is what this reads.
    //
    // It shares the look throttle above and the single innerHTML read,
    // because this runs on a mutation observer and the thread can be
    // long. aiuiShowAppInline is a no-op once its panel exists, so
    // running every few seconds costs a scan and nothing else.
    aiuiAppsDeclaredIn(thread).forEach(function (a) {
      aiuiShowAppInline(chatId, a.slug, a.messageId);
    });

    // Before the early return below, because a chat with nothing new on
    // screen is exactly the chat whose panel needs drawing.
    aiuiReadSaved(chatId, html);

    var fresh = [];
    aiuiBuildIdsIn(html).forEach(function (id) {
      if (!aiuiBuildWatched[id] && fresh.indexOf(id) < 0) fresh.push(id);
    });
    if (!fresh.length) return;
    fresh.forEach(function (id) { aiuiBuildWatched[id] = true; });
    aiuiFetchChat(chatId).then(function (data) {
      var chain = aiuiChainFromHistory(data.chat.history);
      var nowS = Math.floor(Date.now() / 1000);
      fresh.forEach(function (id) {
        if (aiuiBuildIsClosed(chain, id)) return;
        var said = chain.filter(function (m) {
          return m && m.role === 'assistant' && aiuiBuildIdsIn(m.content).indexOf(id) >= 0;
        })[0];
        if (!said || nowS - Number(said.timestamp || 0) > AIUI_BUILD_RECENT_S) return;
        aiuiPollBuild(chatId, id, Number(said.timestamp) * 1000 || Date.now());
      });
    }).catch(function () {
      // Could not read the chat: look again on a later scan.
      fresh.forEach(function (id) { delete aiuiBuildWatched[id]; });
    });
  }
  // ===== Video watcher =====
  //
  // make_video answers in seconds with "it is in the queue ... Its id is
  // <id>" and then renders for minutes. Until now the chat said nothing
  // more unless somebody asked for it by that id, which is the same gap
  // the build watcher closed above and is closed the same way.
  //
  // The finished video is SHOWN, not linked. routes_video serves it with
  // an inline disposition for exactly this, so the element can play it.
  var AIUI_VIDEO_ID = /[Ii]ts id is ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/g;
  var AIUI_VIDEO_POLL_MS = 15000;
  var AIUI_VIDEO_GIVE_UP_MS = 60 * 60 * 1000;
  var aiuiVideoWatched = {};

  function aiuiVideoIdsIn(content) {
    return aiuiArtifactIds(content, 'video');
  }

  // Invisible, for the same reason the build one is: Open WebUI escapes
  // the HTML in a message, so an HTML comment is printed to the person.
  // No legacy shape to recognise here, because this watcher has not been
  // in anybody's hands long enough to have written one.
  function aiuiVideoDoneMarker(id) {
    return '[aiui-video-done]: #' + id;
  }

  // The address a player may load, or '' when this video cannot be played
  // here. Ours, and only ours: the src goes into a media element, and a link
  // from a row is not a reason to fetch somebody else's host.
  function aiuiVideoPlayableSrc(job) {
    var src = String((job && job.share_url) || '');
    return src.indexOf(location.origin + '/api/video-jobs/') === 0 ? src : '';
  }

  // Mirrors the video_status tool, so the page says what asking would say,
  // less the link when the player is sitting in this very reply.
  function aiuiVideoOutcome(job, id) {
    var status = String((job && job.status) || '');
    if (status !== 'done' && status !== 'failed') return null;
    var title = String((job && job.title) || 'The video');
    var said;
    if (status === 'failed') {
      var why = String((job && job.error) || '').trim().slice(0, 300);
      said = title + ' failed.' + (why ? ' ' + why : '');
    } else if (job && job.output_available && aiuiVideoPlayableSrc(job)) {
      said = title + ' is ready.';
    } else if (job && job.output_available && job.share_url) {
      said = title + ' is ready.\nWatch it here: ' + String(job.share_url);
    } else {
      // Rendered, but the share link needs a setting this platform may not
      // have. Saying "ready" with nowhere to go is worse than this.
      said = title + ' has finished rendering. It is on the Video page.';
    }
    return said + '\n\n' + aiuiVideoDoneMarker(id);
  }

  function aiuiShowVideoInline(chatId, job, id, messageId) {
    if (aiuiChatIdFromUrl() !== chatId) return;
    var src = aiuiVideoPlayableSrc(job);
    if (!src) return;
    var box_id = 'aiui-video-' + id;
    if (document.getElementById(box_id)) return;
    var inReply = aiuiReplyFor(box_id, messageId);
    if (inReply === undefined) return;

    var box = document.createElement('div');
    box.id = box_id;
    box.style.cssText = 'margin:.5rem 0 1rem 3.75rem;max-width:46rem;';
    var el = document.createElement('video');
    el.src = src;
    el.controls = true;
    el.preload = 'metadata';
    el.style.cssText = 'display:block;width:100%;border-radius:10px;background:#000;';
    box.appendChild(el);

    if (inReply) aiuiPutInReply(box, inReply);
    else aiuiPutUnderLastMessage(box);
  }

  // The worker leaves a job queued while the server is short of memory,
  // with nothing ahead of it, so an empty queue does not mean rendering.
  function aiuiVideoProgress(job, mins) {
    var ahead = job.queue_position;
    if (typeof ahead === 'number' && ahead > 0) {
      return 'Waiting to render, ' + ahead + ' ahead of it.';
    }
    // The same step the panel marks. Live on 2026-11-10 a video writing its
    // script showed that step working over "Rendering the video".
    var status = String(job.status || '');
    if (status === 'scripting') {
      return 'Writing the script, ' + mins + ' min so far.';
    }
    if (status === 'rendering' || status === 'voicing') {
      return 'Rendering the video, ' + mins + ' min so far.';
    }
    return 'Waiting to start rendering, ' + mins + ' min so far.';
  }

  // The three things a video goes through, in the words of somebody
  // waiting for one. The worker's own stages are queued, scripting and
  // rendering; voicing happens inside rendering, so it is that row.
  var AIUI_VIDEO_STEPS = [
    { key: 'queued', said: 'In the queue' },
    { key: 'scripting', said: 'Writing the script' },
    { key: 'rendering', said: 'Recording the voice and rendering' }
  ];

  function aiuiVideoSteps(job) {
    var status = String((job && job.status) || 'queued');
    if (status === 'voicing') status = 'rendering';
    var at = 0;
    for (var i = 0; i < AIUI_VIDEO_STEPS.length; i++) {
      if (AIUI_VIDEO_STEPS[i].key === status) { at = i; break; }
    }
    return AIUI_VIDEO_STEPS.map(function (s, i) {
      return { key: s.key, said: s.said,
               state: i < at ? 'done' : (i === at ? 'working' : 'waiting') };
    });
  }

  function aiuiVideoPanelId(id) { return 'aiui-video-steps-' + id; }

  // Where a video is, as the build panel shows a build (2026-11-10, Lukas:
  // "some nicer loading thing for the user"). Before this the chat showed
  // one grey line. False, drawing nothing, while no reply is on screen.
  function aiuiVideoPanel(chatId, id, job, mins) {
    if (aiuiChatIdFromUrl() !== chatId) return false;
    var el = document.getElementById(aiuiVideoPanelId(id));
    if (!el) {
      if (!aiuiLastReplyBody()) return false;
      aiuiMotion();
      el = document.createElement('div');
      el.id = aiuiVideoPanelId(id);
      el.style.cssText = 'margin:.4rem 0 .6rem 3.75rem;max-width:46rem;'
        + 'border:1px solid rgba(127,127,127,.28);border-radius:12px;'
        + 'font-size:.85rem;';
      aiuiPutUnderLastMessage(el);
    }
    // Padding inside: aiuiPutUnderLastMessage clears a box's own left
    // padding, and live the text sat against the border.
    el.innerHTML = '<div style="padding:.6rem .75rem;">'
      + '<div style="font-size:.72rem;letter-spacing:.04em;'
      + 'text-transform:uppercase;opacity:.5;margin-bottom:.4rem;">'
      + 'Making the video</div>'
      + aiuiStepRows(aiuiVideoSteps(job))
      // No percentage exists for a render, so the bar moves rather than
      // pretending to fill.
      + '<div style="margin-top:.5rem;height:3px;border-radius:999px;'
      + 'background:rgba(127,127,127,.2);overflow:hidden;">'
      + '<div class="aiui-sliding" style="height:100%;background:#6b73ff;'
      + 'border-radius:999px;"></div></div>'
      + '<div style="margin-top:.3rem;font-size:.72rem;opacity:.6;">'
      + aiuiEscape(aiuiVideoProgress(job, mins)) + '</div></div>';
    return true;
  }

  function aiuiClearVideoPanel(id) {
    var el = document.getElementById(aiuiVideoPanelId(id));
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  function aiuiPollVideo(chatId, id, started) {
    fetch('/api/video-jobs/' + id, { headers: aiuiAuthHeaders() }).then(function (r) {
      if (r.status === 403 || r.status === 404) return 'stop';
      return r.ok ? r.json() : null;
    }).then(function (job) {
      if (job === 'stop') return true;
      if (!job) return false;
      var text = aiuiVideoOutcome(job, id);
      if (text) {
        // The player comes from the saved read that this sets off, in the
        // closing message. Drawn here, on a chat just opened, it went to
        // the end of the page under the message box, because no reply was
        // on screen yet, and it was never moved.
        aiuiClearVideoPanel(id);
        return aiuiCloseWith(chatId, aiuiVideoDoneMarker(id), text);
      }
      var mins = Math.max(1, Math.round((Date.now() - started) / 60000));
      aiuiVideoPanel(chatId, id, job, mins);
      return false;
    }).catch(function () { return false; }).then(function (finished) {
      if (finished || Date.now() - started > AIUI_VIDEO_GIVE_UP_MS) {
        aiuiClearVideoPanel(id);
        return;
      }
      setTimeout(function () { aiuiPollVideo(chatId, id, started); }, AIUI_VIDEO_POLL_MS);
    });
  }

  function aiuiWatchVideos(chain, chatId) {
    var nowS = Math.floor(Date.now() / 1000);
    chain.forEach(function (m) {
      if (!m || m.role !== 'assistant') return;
      aiuiVideoIdsIn(m.content).forEach(function (id) {
        if (aiuiVideoWatched[id]) return;
        if (aiuiIsClosed(chain, aiuiVideoDoneMarker(id))) return;
        if (nowS - Number(m.timestamp || 0) > AIUI_BUILD_RECENT_S) return;
        aiuiVideoWatched[id] = true;
        aiuiPollVideo(chatId, id, Number(m.timestamp) * 1000 || Date.now());
      });
    });
  }
  // ===== End video watcher =====

  // ===== End build watcher =====

  linkifyConnectButtons();
  wireAiuiConnectLinks();
  wireAiuiAgentNameHeaders();
  // The scan above runs on a page mutation, and a thread that has finished
  // changing produces none, so the last change could go unread for ever.
  setInterval(aiuiWatchBuilds, AIUI_BUILD_LOOK_MS + 250);

  console.log('[AIUI] Integrations UI v16-connect-your-own loaded');
})();
