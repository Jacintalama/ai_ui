// AIUI Integrations - Custom UI injection for Open WebUI
(function() {
  'use strict';

  var GDRIVE_API = 'http://localhost:8005';
  var GMAIL_API = 'http://localhost:8006';
  var GMAIL_ICON_SMALL = '<svg width="16" height="16" viewBox="0 0 75 75" xmlns="http://www.w3.org/2000/svg"><path d="M6.25 56.25h12.5V36.46L0 22.5v27.5c0 3.45 2.8 6.25 6.25 6.25z" fill="#4285f4"/><path d="M56.25 56.25h12.5c3.45 0 6.25-2.8 6.25-6.25V22.5l-18.75 13.96" fill="#34a853"/><path d="M56.25 25v31.25h12.5c3.45 0 6.25-2.8 6.25-6.25V22.5l-11.72 8.72" fill="#34a853"/><path d="M18.75 56.25V36.46L37.5 50l18.75-13.54V25L37.5 38.54 18.75 25" fill="#ea4335"/><path d="M0 22.5l18.75 13.96V25L6.25 18.75C2.8 18.75 0 21.55 0 22.5" fill="#c5221f"/><path d="M56.25 25v11.46L75 22.5c0-.95-2.8-3.75-6.25-3.75L56.25 25" fill="#0d652d"/><path d="M18.75 25L6.25 18.75C2.8 18.75 0 21.55 0 22.5l18.75 13.96" fill="#c5221f"/><path d="M56.25 25l12.5-6.25C65.3 18.75 62.5 21.55 62.5 22.5" fill="#0d652d"/></svg>';
  var GMAIL_ICON_BIG = '<svg width="24" height="24" viewBox="0 0 75 75" xmlns="http://www.w3.org/2000/svg"><path d="M6.25 56.25h12.5V36.46L0 22.5v27.5c0 3.45 2.8 6.25 6.25 6.25z" fill="#4285f4"/><path d="M56.25 56.25h12.5c3.45 0 6.25-2.8 6.25-6.25V22.5l-18.75 13.96" fill="#34a853"/><path d="M56.25 25v31.25h12.5c3.45 0 6.25-2.8 6.25-6.25V22.5l-11.72 8.72" fill="#34a853"/><path d="M18.75 56.25V36.46L37.5 50l18.75-13.54V25L37.5 38.54 18.75 25" fill="#ea4335"/><path d="M0 22.5l18.75 13.96V25L6.25 18.75C2.8 18.75 0 21.55 0 22.5" fill="#c5221f"/><path d="M56.25 25v11.46L75 22.5c0-.95-2.8-3.75-6.25-3.75L56.25 25" fill="#0d652d"/><path d="M18.75 25L6.25 18.75C2.8 18.75 0 21.55 0 22.5l18.75 13.96" fill="#c5221f"/><path d="M56.25 25l12.5-6.25C65.3 18.75 62.5 21.55 62.5 22.5" fill="#0d652d"/></svg>';
  var GDRIVE_ICON_SMALL = '<svg width="16" height="16" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg"><path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/><path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-20.4 35.3c-.8 1.4-1.2 2.95-1.2 4.5h27.5z" fill="#00ac47"/><path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.5l5.4 9.35z" fill="#ea4335"/><path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/><path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc"/><path d="m73.4 26.5-10.1-17.5c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 23.8h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/></svg>';
  var GDRIVE_ICON_BIG = '<svg width="24" height="24" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg"><path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/><path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-20.4 35.3c-.8 1.4-1.2 2.95-1.2 4.5h27.5z" fill="#00ac47"/><path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.5l5.4 9.35z" fill="#ea4335"/><path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/><path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc"/><path d="m73.4 26.5-10.1-17.5c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 23.8h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/></svg>';

  // ========== Helpers ==========

  function getEffectiveEmail() {
    var stored = localStorage.getItem('aiui-gdrive-email');
    if (stored) return stored;
    for (var i = 0; i < localStorage.length; i++) {
      try {
        var val = localStorage.getItem(localStorage.key(i));
        if (!val) continue;
        var obj = JSON.parse(val);
        if (obj && obj.email) return obj.email;
        if (obj && obj.user && obj.user.email) return obj.user.email;
      } catch (e) {}
    }
    return 'default@local';
  }

  function isConnected() {
    return localStorage.getItem('aiui-gdrive-connected') === 'true';
  }

  function isGmailConnected() {
    return localStorage.getItem('aiui-gmail-connected') === 'true';
  }

  function handleDisconnected() {
    // Clear local state
    localStorage.removeItem('aiui-gdrive-connected');
    localStorage.removeItem('aiui-gdrive-email');
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
      localStorage.setItem('aiui-gdrive-email', event.data.email);
      localStorage.setItem('aiui-gdrive-connected', 'true');
      if (activeIntModal) updateCardConnected(activeIntModal, 'google-drive');
    }
    if (event.data && event.data.type === 'aiui-gmail-connected') {
      localStorage.setItem('aiui-gmail-email', event.data.email);
      localStorage.setItem('aiui-gmail-connected', 'true');
      if (activeIntModal) updateCardConnected(activeIntModal, 'gmail');
    }
  });

  // ========== Attached files tracking ==========

  var attachedDriveFiles = [];

  function addDriveAttachment(file) {
    // Always allow — create unique copy with unique ID for tracking
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

  function updateCardConnected(modal, integrationId) {
    var status = modal.querySelector('#aiui-status-' + integrationId);
    var connectBtn = modal.querySelector('#aiui-connect-' + integrationId);
    var disconnectBtn = modal.querySelector('#aiui-disconnect-' + integrationId);
    var card = connectBtn ? connectBtn.closest('[data-integration]') : null;
    if (status) status.style.display = 'inline';
    if (connectBtn) connectBtn.style.display = 'none';
    if (disconnectBtn) disconnectBtn.style.display = 'inline-block';
    if (card) card.style.borderColor = '#00ac47';
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
  }

  function createIntegrationsModal() {
    var overlay = document.createElement('div');
    overlay.id = 'aiui-integrations-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';

    var modal = document.createElement('div');
    modal.style.cssText = 'background:#1e1e1e;border-radius:16px;padding:32px;max-width:700px;width:90%;max-height:80vh;overflow-y:auto;box-shadow:0 25px 50px rgba(0,0,0,0.5);';
    activeIntModal = modal;

    modal.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
      '<h2 style="color:#fff;font-size:22px;font-weight:600;margin:0;">Integrations</h2>' +
      '<button id="aiui-close-modal" style="background:none;border:none;color:#999;font-size:24px;cursor:pointer;padding:4px 8px;line-height:1;">&times;</button>' +
      '</div>' +
      '<p style="color:#999;font-size:14px;margin:0 0 24px 0;">Connect AIUI to your apps, files, and services. Each connection is personal to your account.</p>' +
      '<div id="aiui-integrations-grid" style="display:grid;grid-template-columns:1fr;gap:12px;"></div>';

    var grid = modal.querySelector('#aiui-integrations-grid');

    // Google Drive card
    var card = document.createElement('div');
    card.setAttribute('data-integration', 'google-drive');
    card.style.cssText = 'background:#2a2a2a;border:1px solid #333;border-radius:12px;padding:16px;transition:all 0.2s;display:flex;align-items:center;gap:14px;';

    card.innerHTML = '<div style="width:44px;height:44px;flex-shrink:0;display:flex;align-items:center;justify-content:center;background:#333;border-radius:10px;padding:8px;">' + GDRIVE_ICON_BIG + '</div>' +
      '<div style="flex:1;min-width:0;">' +
        '<div style="display:flex;align-items:center;gap:8px;">' +
          '<span style="color:#fff;font-weight:600;font-size:15px;">Google Drive</span>' +
          '<span id="aiui-status-google-drive" style="display:none;background:#00ac47;color:#fff;font-size:11px;padding:2px 10px;border-radius:10px;font-weight:600;">Connected</span>' +
        '</div>' +
        '<p style="color:#888;font-size:13px;margin:3px 0 0 0;">Find and analyze files instantly</p>' +
      '</div>' +
      '<div style="display:flex;gap:8px;flex-shrink:0;">' +
        '<button id="aiui-connect-google-drive" style="background:#4a9eff;border:none;border-radius:8px;color:#fff;padding:8px 18px;font-size:13px;cursor:pointer;font-weight:600;">Connect</button>' +
        '<button id="aiui-disconnect-google-drive" style="display:none;background:transparent;border:1px solid #666;border-radius:8px;color:#ccc;padding:8px 18px;font-size:13px;cursor:pointer;font-weight:500;">Disconnect</button>' +
      '</div>';

    card.addEventListener('mouseenter', function() { card.style.background = '#333'; });
    card.addEventListener('mouseleave', function() { card.style.background = '#2a2a2a'; });

    card.querySelector('#aiui-connect-google-drive').addEventListener('click', function(e) {
      e.stopPropagation();
      var url = GDRIVE_API + '/auth/google/start?user_email=' + encodeURIComponent(getEffectiveEmail());
      window.open(url, 'aiui-oauth', 'width=600,height=700');
    });

    card.querySelector('#aiui-disconnect-google-drive').addEventListener('click', function(e) {
      e.stopPropagation();
      fetch(GDRIVE_API + '/auth/google/disconnect?user_email=' + encodeURIComponent(getEffectiveEmail()), { method: 'POST' })
        .then(function() {
          localStorage.removeItem('aiui-gdrive-email');
          localStorage.removeItem('aiui-gdrive-connected');
          updateCardDisconnected(modal, 'google-drive');
        });
    });

    grid.appendChild(card);

    // --- Gmail Card ---
    var gmailCard = document.createElement('div');
    gmailCard.setAttribute('data-integration', 'gmail');
    gmailCard.style.cssText = 'background:#2a2a2a;border:1px solid #333;border-radius:12px;padding:16px;transition:all 0.2s;display:flex;align-items:center;gap:14px;';

    gmailCard.innerHTML = '<div style="width:44px;height:44px;flex-shrink:0;display:flex;align-items:center;justify-content:center;background:#333;border-radius:10px;padding:8px;">' + GMAIL_ICON_BIG + '</div>' +
      '<div style="flex:1;min-width:0;">' +
        '<div style="display:flex;align-items:center;gap:8px;">' +
          '<span style="color:#fff;font-weight:600;font-size:15px;">Gmail</span>' +
          '<span id="aiui-status-gmail" style="display:none;background:#00ac47;color:#fff;font-size:11px;padding:2px 10px;border-radius:10px;font-weight:600;">Connected</span>' +
        '</div>' +
        '<p style="color:#888;font-size:13px;margin:3px 0 0 0;">Read, send, draft replies, summarize, and extract email content</p>' +
      '</div>' +
      '<div style="display:flex;gap:8px;flex-shrink:0;">' +
        '<button id="aiui-connect-gmail" style="background:#4a9eff;border:none;border-radius:8px;color:#fff;padding:8px 18px;font-size:13px;cursor:pointer;font-weight:600;">Connect</button>' +
        '<button id="aiui-disconnect-gmail" style="display:none;background:transparent;border:1px solid #666;border-radius:8px;color:#ccc;padding:8px 18px;font-size:13px;cursor:pointer;font-weight:500;">Disconnect</button>' +
      '</div>';

    gmailCard.addEventListener('mouseenter', function() { gmailCard.style.background = '#333'; });
    gmailCard.addEventListener('mouseleave', function() { gmailCard.style.background = '#2a2a2a'; });

    gmailCard.querySelector('#aiui-connect-gmail').addEventListener('click', function(e) {
      e.stopPropagation();
      var url = GMAIL_API + '/auth/google/start?user_email=' + encodeURIComponent(getEffectiveEmail());
      window.open(url, 'aiui-oauth-gmail', 'width=600,height=700');
    });

    gmailCard.querySelector('#aiui-disconnect-gmail').addEventListener('click', function(e) {
      e.stopPropagation();
      fetch(GMAIL_API + '/auth/google/disconnect?user_email=' + encodeURIComponent(getEffectiveEmail()), { method: 'POST' })
        .then(function() {
          localStorage.removeItem('aiui-gmail-email');
          localStorage.removeItem('aiui-gmail-connected');
          updateCardDisconnected(modal, 'gmail');
        });
    });

    grid.appendChild(gmailCard);

    // Check Gmail status
    if (isGmailConnected()) updateCardConnected(modal, 'gmail');
    fetch(GMAIL_API + '/auth/google/status?user_email=' + encodeURIComponent(getEffectiveEmail()))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.connected) { localStorage.setItem('aiui-gmail-connected', 'true'); updateCardConnected(modal, 'gmail'); }
        else { localStorage.removeItem('aiui-gmail-connected'); updateCardDisconnected(modal, 'gmail'); }
      }).catch(function() {});

    // Check GDrive status
    if (isConnected()) updateCardConnected(modal, 'google-drive');
    fetch(GDRIVE_API + '/auth/google/status?user_email=' + encodeURIComponent(getEffectiveEmail()))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.connected) { localStorage.setItem('aiui-gdrive-connected', 'true'); updateCardConnected(modal, 'google-drive'); }
        else { localStorage.removeItem('aiui-gdrive-connected'); updateCardDisconnected(modal, 'google-drive'); }
      }).catch(function() {});

    overlay.appendChild(modal);
    overlay.addEventListener('click', function(e) { if (e.target === overlay) { overlay.remove(); activeIntModal = null; } });
    modal.querySelector('#aiui-close-modal').addEventListener('click', function() { overlay.remove(); activeIntModal = null; });

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

    // Compose button removed — AI handles sending

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

      // Use send endpoint with a draft flag — but Gmail API draft create for new emails
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

    // Create Draft Reply — show intent input first
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
        '<div style="color:#888;font-size:12px;">To: ' + fromShort + ' — Re: ' + (email.subject || '') + '</div>' +
      '</div>' +
      '<div style="margin-bottom:12px;">' +
        '<label style="color:#ccc;font-size:13px;display:block;margin-bottom:6px;">What should the reply say? (optional — AI will generate if blank)</label>' +
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

  function injectMenuItems() {
    var observer = new MutationObserver(function(mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var addedNodes = mutations[i].addedNodes;
        for (var j = 0; j < addedNodes.length; j++) {
          var node = addedNodes[j];
          if (node.nodeType !== 1) continue;

          var allButtons = node.querySelectorAll ? node.querySelectorAll('button') : [];
          var refItem = null;
          allButtons.forEach(function(btn) {
            var text = btn.textContent ? btn.textContent.trim() : '';
            if (text.includes('Reference Chats') || text.includes('Attach Knowledge') || text.includes('Upload Files')) {
              refItem = btn;
            }
          });

          if (refItem && !document.getElementById('aiui-integrations-btn')) {
            var container = refItem.parentElement;
            if (!container) continue;

            // 1. "Add from Google Drive" — only show if connected
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

            // 2. "Add from Gmail" — only show if connected
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

            // 3. "Integrations" — always show
            var intBtn = document.createElement('button');
            intBtn.id = 'aiui-integrations-btn';
            intBtn.className = refItem.className;
            intBtn.innerHTML = '<div style="display:flex;align-items:center;gap:8px;width:100%;">' +
              '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="8" height="8" rx="1"/><rect x="14" y="2" width="8" height="8" rx="1"/><rect x="2" y="14" width="8" height="8" rx="1"/><rect x="14" y="14" width="8" height="8" rx="1"/></svg>' +
              '<span>Integrations</span>' +
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
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
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
          showNotification('Draft saved to Gmail! Re: ' + (result.subject || '') + ' — Check Gmail Drafts', false, true);
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

  console.log('[AIUI] Integrations UI v2 loaded');
})();
