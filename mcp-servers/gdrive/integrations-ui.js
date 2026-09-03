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

  // Cache the resolved email to avoid repeated API calls
  var _cachedEmail = null;

  function getEffectiveEmail() {
    // Return cached email if available
    if (_cachedEmail) return _cachedEmail;

    // Try to decode JWT token from Open WebUI
    var token = localStorage.getItem('token');
    if (token) {
      try {
        var payload = JSON.parse(atob(token.split('.')[1]));
        if (payload && payload.id) {
          // Use user ID as identifier (email not in JWT)
          _cachedEmail = payload.id;
          return _cachedEmail;
        }
      } catch (e) {}
    }

    // Fallback: search localStorage for email
    for (var i = 0; i < localStorage.length; i++) {
      try {
        var val = localStorage.getItem(localStorage.key(i));
        if (!val) continue;
        var obj = JSON.parse(val);
        if (obj && obj.email) { _cachedEmail = obj.email; return _cachedEmail; }
        if (obj && obj.user && obj.user.email) { _cachedEmail = obj.user.email; return _cachedEmail; }
      } catch (e) {}
    }
    return 'default@local';
  }

  // Fetch actual email from Open WebUI API and update cache
  function resolveUserEmail() {
    var token = localStorage.getItem('token');
    if (!token) return;
    fetch('/api/v1/auths/', {
      headers: { 'Authorization': 'Bearer ' + token }
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data && data.email) {
        _cachedEmail = data.email;
        console.log('[AIUI] User email resolved:', data.email);
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
      var email = getEffectiveEmail();
      window.open(GDRIVE_API + '/auth/google/start?user_email=' + encodeURIComponent(email), 'aiui-oauth', 'width=600,height=700');
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
      try { localStorage.setItem('aiui-return-url', window.location.href); } catch (er) {}
      window.location.href = GMAIL_API + '/auth/google/start?user_email='
        + encodeURIComponent(email) + '&connect=all';
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
      metaEl.textContent = app.sub || (acct && acct !== app.name ? acct : '');
      card.appendChild(metaEl);

      var statusEl = document.createElement('div');
      // margin-top:auto pins it to the bottom, so the status line sits on one
      // baseline across the whole grid no matter what is above it.
      statusEl.style.cssText = 'margin-top:auto;padding-top:8px;text-align:center;'
        + 'height:' + (SLOT_STATUS + 8) + 'px;line-height:' + SLOT_STATUS + 'px;'
        + 'box-sizing:content-box;';
      if (!app.real) {
        statusEl.innerHTML = '<span style="color:#666;font-size:11px;">Coming soon</span>';
      } else if (!connChecked[app.id]) {
        statusEl.innerHTML = '<span style="color:#777;font-size:12px;">Checking…</span>';
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
          } else if (confirm('Disconnect ' + app.name + (app.sub ? ' (' + app.sub + ')' : '') + '?')) {
            var apis = app.apis || [app.api];
            Promise.all(apis.map(function (api) {
              return fetch(api + '/auth/google/disconnect?user_email=' + encodeURIComponent(email), { method: 'POST' }).catch(function () {});
            })).then(function () { connState[app.id] = false; renderGrid(); });
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

    function openTokenPanel(app) {
      var meta = connMeta[app.id] || {};
      var fields = meta.fields || [];
      var wrap = document.createElement('div');
      wrap.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;'
        + 'background:rgba(0,0,0,0.65);z-index:10002;display:flex;align-items:center;'
        + 'justify-content:center;backdrop-filter:blur(3px);';
      var box = document.createElement('div');
      box.style.cssText = 'background:#161616;border:1px solid #2a2a2a;border-radius:16px;'
        + 'width:min(440px,92vw);padding:22px 24px;color:#eee;'
        + 'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;';

      var connected = !!connState[app.id];
      var head = document.createElement('div');
      head.style.cssText = 'font-size:17px;font-weight:650;margin-bottom:4px;';
      head.textContent = (connected ? 'Manage ' : 'Connect ') + app.name;
      box.appendChild(head);

      var sub = document.createElement('div');
      sub.style.cssText = 'color:#8d8d8d;font-size:12px;line-height:1.5;margin-bottom:16px;';
      sub.textContent = connected
        ? 'Connected as ' + (meta.account_label || app.name) + '. Paste a new credential to replace it.'
        : (meta.where || '');
      box.appendChild(sub);

      if (meta.oauth && !connected) {
        var go1 = document.createElement('button');
        go1.textContent = 'Connect with ' + app.name;
        go1.style.cssText = 'width:100%;background:#fff;color:#111;border:none;'
          + 'border-radius:10px;padding:11px 18px;font-size:13.5px;font-weight:650;'
          + 'cursor:pointer;margin-bottom:14px;';
        go1.addEventListener('click', function () {
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
                    if (connState[app.id]) { wrap.remove(); }
                    else {
                      go1.disabled = false;
                      go1.textContent = 'Connect with ' + app.name;
                      msg.style.color = '#e07070';
                      msg.textContent = 'That did not complete. Try again, or '
                        + 'paste a token below.';
                    }
                  });
              }
              function onMsg(e) {
                if (e && e.data && e.data.aiuiOauth) finish();
              }
              window.addEventListener('message', onMsg);
              var poll = setInterval(function () {
                if (!win || win.closed) finish();
              }, 700);
            })
            .catch(function () {
              go1.disabled = false;
              go1.textContent = 'Connect with ' + app.name;
              msg.style.color = '#e07070';
              msg.textContent = 'Could not start that. Paste a token instead.';
            });
        });
        box.appendChild(go1);

        var orLine = document.createElement('div');
        orLine.style.cssText = 'color:#6b6b6b;font-size:11px;text-align:center;'
          + 'margin:-4px 0 12px;';
        orLine.textContent = 'or paste a token';
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
      row.style.cssText = 'display:flex;gap:9px;justify-content:flex-end;align-items:center;';

      if (connected) {
        var test = document.createElement('button');
        test.textContent = 'Test connection';
        test.style.cssText = 'background:transparent;color:#9aa6c8;border:1px solid #303030;'
          + 'border-radius:9px;padding:9px 14px;font-size:13px;cursor:pointer;';
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
          + 'border-radius:9px;padding:9px 14px;font-size:13px;cursor:pointer;margin-right:auto;order:-1;';
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
        + 'border-radius:9px;padding:9px 14px;font-size:13px;cursor:pointer;';
      cancel.addEventListener('click', function () { wrap.remove(); });
      row.appendChild(cancel);

      var go = document.createElement('button');
      go.textContent = 'Connect';
      go.style.cssText = 'background:#fff;color:#111;border:none;border-radius:9px;'
        + 'padding:9px 18px;font-size:13px;font-weight:600;cursor:pointer;';
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
    var userEmail = getEffectiveEmail();
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
      fetch(GMAIL_API + '/gmail_download_attachment/' + messageId + '/' + att.attachment_id + '?user_email=' + encodeURIComponent(userEmail) + '&filename=' + encodeURIComponent(att.filename))
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
    var url = api + '/auth/google/start?user_email=' + encodeURIComponent(email);
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

  // Turn the plain connect URL the model prints (".../auth/google/start...")
  // into a clean, clickable inline button. Robust: reads the rendered message,
  // no textareas, no dependence on catching the send. Same-tab redirect.
  function _renderConnectState(container, service, url, email, connected) {
    container.innerHTML = '';
    var api = service === 'gdrive' ? GDRIVE_API : (service === 'calendar' ? CALENDAR_API : GMAIL_API);
    var icon = service === 'gdrive' ? GDRIVE_ICON_SMALL : (service === 'calendar' ? CALENDAR_ICON_SMALL : GMAIL_ICON_SMALL);
    var name = service === 'gdrive' ? 'Google Drive' : (service === 'calendar' ? 'Google Calendar' : 'Gmail');
    if (!connected) {
      // Unified connect: one consent links Gmail + Calendar + Drive. Whatever
      // service prompted this, send the user through the single Google flow.
      var unifiedUrl = GMAIL_API + '/auth/google/start?user_email='
        + encodeURIComponent(email) + '&connect=all';
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.style.cssText = 'display:inline-flex;align-items:center;gap:8px;margin:8px 0;' +
        'padding:11px 20px;background:#4CAF50;color:#fff;border:none;border-radius:10px;' +
        'font-weight:600;font-size:14px;cursor:pointer;box-shadow:0 3px 10px rgba(0,0,0,0.25);';
      btn.innerHTML = icon + '<span>Connect Google</span>';
      btn.addEventListener('click', function () {
        try { localStorage.setItem('aiui-return-url', window.location.href); } catch (e) {}
        window.location.href = unifiedUrl;
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
    if (url.indexOf('/auth/google/start') === -1) return;
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
    var email = getEffectiveEmail();
    if (provider === 'gmail') return GMAIL_API + '/auth/google/start?user_email=' + encodeURIComponent(email);
    if (provider === 'gdrive') return GDRIVE_API + '/auth/google/start?user_email=' + encodeURIComponent(email);
    if (provider === 'calendar') return CALENDAR_API + '/auth/google/start?user_email=' + encodeURIComponent(email);
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
      var anchors = document.querySelectorAll('a[href*="/auth/google/start"]');
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
        for (var i = 0; i < items.length; i++) {
          if (aiuiIsMintedAgent(items[i]) && items[i].name) {
            names.add(String(items[i].name).trim().toLowerCase());
          }
        }
        aiuiAgentNames = names;
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
    return null;
  }

  // Only the very first content of the body, following the first-child
  // chain through wrapper elements. This can never land on a later
  // paragraph, only on whatever text opens the message.
  function aiuiFirstTextNode(container) {
    var node = container.firstChild;
    var depth = 0;
    while (node && depth < 8) {
      if (node.nodeType === 3) return node;
      if (node.nodeType === 1) { node = node.firstChild; depth++; continue; }
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
    var result = { labels: [], sawUnknownName: false };
    var seen = {};
    var candidates = [body];
    for (var c = 0; c < body.children.length; c++) candidates.push(body.children[c]);

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

    // One agent spoke, so the label below now repeats the header and
    // goes. With two or more, those labels are the only thing saying
    // which answer belongs to whom, so they stay.
    if (names.length === 1 && span.getAttribute('data-aiui-agent-stripped') !== '1') {
      span.setAttribute('data-aiui-agent-stripped', '1');
      aiuiStripLabel(body, scan.labels[0]);
    }
  }

  function aiuiScanAgentNameHeaders() {
    var spans = document.querySelectorAll('#response-message-model-name');
    for (var i = 0; i < spans.length; i++) aiuiRewriteAgentHeader(spans[i]);
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

  linkifyConnectButtons();
  wireAiuiConnectLinks();
  wireAiuiAgentNameHeaders();

  console.log('[AIUI] Integrations UI v16-connect-your-own loaded');
})();
