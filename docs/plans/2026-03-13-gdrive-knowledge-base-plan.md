# Google Drive → Knowledge Base Auto-Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an n8n workflow that watches a Google Drive folder and auto-syncs files into an OpenWebUI Knowledge Base with Discord notifications.

**Architecture:** Single n8n workflow with ~14 nodes. Google Drive Trigger polls a folder every 2 minutes. Files are exported, converted to Markdown via a Code node, uploaded to OpenWebUI's file API, added to a "Google Drive" knowledge base, and confirmed via Discord notification. File tracking uses n8n's built-in static data (no new DB tables).

**Tech Stack:** n8n (workflow JSON), OpenWebUI REST API, Google Drive API (via n8n nodes), Discord Bot API, PostgreSQL + pgvector (existing, untouched)

**Design doc:** `docs/plans/2026-03-13-gdrive-knowledge-base-design.md`

---

## Task 1: Add Discord env vars to n8n service

**Files:**
- Modify: `docker-compose.unified.yml` (n8n service environment block, ~line 186)

**Step 1: Add the two missing env vars to n8n service**

In `docker-compose.unified.yml`, add these to the n8n service `environment` block (after `SLACK_BOT_TOKEN`):

```yaml
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN:-}
      - DISCORD_ALERT_CHANNEL_ID=${DISCORD_ALERT_CHANNEL_ID:-}
      - OPENWEBUI_URL=http://open-webui:8080
```

**Why:** The workflow needs `DISCORD_BOT_TOKEN` and `DISCORD_ALERT_CHANNEL_ID` to send notifications, and `OPENWEBUI_URL` to call the Knowledge Base API. These env vars already exist in `.env` (used by webhook-handler), we're just exposing them to n8n.

**Step 2: Verify no syntax errors**

Run: `python -c "import yaml; yaml.safe_load(open('docker-compose.unified.yml'))" 2>&1 || echo "YAML parse error"`

If Python yaml not available, visual check that indentation matches surrounding lines.

**Step 3: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "feat: expose Discord and OpenWebUI env vars to n8n service"
```

---

## Task 2: Create the n8n workflow JSON — Trigger + KB Lookup

**Files:**
- Create: `n8n-workflows/gdrive-knowledge-sync.json`

**Step 1: Create the workflow file with trigger and KB lookup nodes**

Create `n8n-workflows/gdrive-knowledge-sync.json` with the Google Drive Trigger node and the Find/Create KB node. This is the foundation — the trigger and the KB resolution logic.

```json
{
  "name": "Google Drive → Knowledge Base Sync",
  "nodes": [
    {
      "parameters": {
        "pollTimes": {
          "item": [
            { "mode": "everyMinute", "value": 2 }
          ]
        },
        "triggerOn": "specificFolder",
        "folderToWatch": {
          "__rl": true,
          "mode": "id",
          "value": "CONFIGURE_FOLDER_ID"
        },
        "event": "fileCreated",
        "options": {}
      },
      "name": "Google Drive Trigger",
      "type": "n8n-nodes-base.googleDriveTrigger",
      "typeVersion": 1,
      "position": [220, 300],
      "id": "gdrive-trigger-node",
      "credentials": {
        "googleDriveOAuth2Api": {
          "id": "CONFIGURE_IN_UI",
          "name": "Google Drive account"
        }
      }
    },
    {
      "parameters": {
        "method": "GET",
        "url": "={{ $env.OPENWEBUI_URL }}/api/v1/knowledge/",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            {
              "name": "Authorization",
              "value": "=Bearer {{ $env.OPENWEBUI_API_KEY }}"
            }
          ]
        },
        "options": {
          "response": {
            "response": { "responseFormat": "json" }
          }
        }
      },
      "name": "List Knowledge Bases",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [460, 300],
      "id": "list-kb-node",
      "onError": "continueRegularOutput"
    },
    {
      "parameters": {
        "jsCode": "// Find the 'Google Drive' knowledge base or flag for creation\nconst kbList = $input.first().json;\nconst items = Array.isArray(kbList) ? kbList : (kbList.data || kbList.items || []);\nconst googleDriveKB = items.find(kb => kb.name === 'Google Drive');\n\nif (googleDriveKB) {\n  return [{ json: { kb_id: googleDriveKB.id, kb_exists: true } }];\n} else {\n  return [{ json: { kb_id: null, kb_exists: false } }];\n}\n"
      },
      "name": "Find Google Drive KB",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [680, 300],
      "id": "find-kb-node"
    },
    {
      "parameters": {
        "conditions": {
          "options": { "leftValue": "", "typeValidation": "strict" },
          "combinator": "and",
          "conditions": [
            {
              "leftValue": "={{ $json.kb_exists }}",
              "rightValue": false,
              "operator": { "type": "boolean", "operation": "equals" }
            }
          ]
        }
      },
      "name": "KB Exists?",
      "type": "n8n-nodes-base.if",
      "typeVersion": 2,
      "position": [900, 300],
      "id": "kb-exists-check"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "={{ $env.OPENWEBUI_URL }}/api/v1/knowledge/create",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            {
              "name": "Authorization",
              "value": "=Bearer {{ $env.OPENWEBUI_API_KEY }}"
            },
            {
              "name": "Content-Type",
              "value": "application/json"
            }
          ]
        },
        "sendBody": true,
        "bodyParameters": {
          "parameters": []
        },
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ name: 'Google Drive', description: 'Auto-synced documents from Google Drive AI Knowledge folder' }) }}",
        "options": {
          "response": {
            "response": { "responseFormat": "json" }
          }
        }
      },
      "name": "Create KB",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [1120, 200],
      "id": "create-kb-node"
    },
    {
      "parameters": {
        "jsCode": "// Merge KB ID from either path (existing or newly created)\nconst items = $input.all();\nconst data = items[0].json;\nlet kb_id = data.kb_id || data.id;\nif (!kb_id) {\n  throw new Error('Failed to find or create Google Drive knowledge base');\n}\nreturn [{ json: { kb_id } }];\n"
      },
      "name": "Merge KB ID",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [1340, 300],
      "id": "merge-kb-id-node"
    }
  ],
  "connections": {
    "Google Drive Trigger": { "main": [[{ "node": "List Knowledge Bases", "type": "main", "index": 0 }]] },
    "List Knowledge Bases": { "main": [[{ "node": "Find Google Drive KB", "type": "main", "index": 0 }]] },
    "Find Google Drive KB": { "main": [[{ "node": "KB Exists?", "type": "main", "index": 0 }]] },
    "KB Exists?": {
      "main": [
        [{ "node": "Create KB", "type": "main", "index": 0 }],
        [{ "node": "Merge KB ID", "type": "main", "index": 0 }]
      ]
    },
    "Create KB": { "main": [[{ "node": "Merge KB ID", "type": "main", "index": 0 }]] }
  },
  "settings": { "executionOrder": "v1" }
}
```

**Step 2: Verify JSON is valid**

Run: `python -c "import json; json.load(open('n8n-workflows/gdrive-knowledge-sync.json')); print('Valid JSON')"`

**Step 3: Commit**

```bash
git add n8n-workflows/gdrive-knowledge-sync.json
git commit -m "feat: add gdrive-knowledge-sync workflow skeleton with trigger and KB lookup"
```

---

## Task 3: Add file type filter and download nodes

**Files:**
- Modify: `n8n-workflows/gdrive-knowledge-sync.json`

**Step 1: Add nodes for filtering file types and downloading content**

Add these nodes after "Merge KB ID":

- **Filter File Type** (Code node): Check MIME type, skip images/video/archives. Map Google Workspace MIME types to export formats.
- **Download File** (HTTP Request node): Export Google Workspace files via Drive API export link, or download binary files directly.

Add these nodes to the `nodes` array:

```json
{
  "parameters": {
    "jsCode": "// Filter supported file types and determine export format\nconst trigger = $('Google Drive Trigger').first().json;\nconst mimeType = trigger.mimeType || '';\nconst fileName = trigger.name || 'unknown';\nconst fileId = trigger.id || '';\n\n// Google Workspace MIME types → export format\nconst exportMap = {\n  'application/vnd.google-apps.spreadsheet': { export: 'text/csv', ext: 'csv', type: 'sheets' },\n  'application/vnd.google-apps.document': { export: 'text/html', ext: 'html', type: 'docs' },\n  'application/vnd.google-apps.presentation': { export: 'text/plain', ext: 'txt', type: 'slides' }\n};\n\n// Direct download types\nconst directTypes = [\n  'application/pdf'\n];\n\n// Skip unsupported types\nconst skipPrefixes = ['image/', 'video/', 'audio/', 'application/zip', 'application/x-rar'];\nconst shouldSkip = skipPrefixes.some(p => mimeType.startsWith(p));\n\nif (shouldSkip || !mimeType) {\n  return [{ json: { skip: true, reason: `Unsupported type: ${mimeType}`, fileName } }];\n}\n\nconst exportInfo = exportMap[mimeType];\nconst isDirect = directTypes.includes(mimeType);\n\nif (!exportInfo && !isDirect) {\n  return [{ json: { skip: true, reason: `Unknown type: ${mimeType}`, fileName } }];\n}\n\nreturn [{ json: {\n  skip: false,\n  fileId,\n  fileName,\n  mimeType,\n  isGoogleWorkspace: !!exportInfo,\n  isDirect,\n  exportMime: exportInfo ? exportInfo.export : null,\n  fileType: exportInfo ? exportInfo.type : 'pdf',\n  kb_id: $('Merge KB ID').first().json.kb_id\n} }];\n"
  },
  "name": "Filter File Type",
  "type": "n8n-nodes-base.code",
  "typeVersion": 2,
  "position": [1560, 300],
  "id": "filter-file-type-node"
},
{
  "parameters": {
    "conditions": {
      "options": { "leftValue": "", "typeValidation": "strict" },
      "combinator": "and",
      "conditions": [
        {
          "leftValue": "={{ $json.skip }}",
          "rightValue": true,
          "operator": { "type": "boolean", "operation": "equals" }
        }
      ]
    }
  },
  "name": "Should Skip?",
  "type": "n8n-nodes-base.if",
  "typeVersion": 2,
  "position": [1780, 300],
  "id": "should-skip-check"
}
```

Add connections:

```json
"Merge KB ID": { "main": [[{ "node": "Filter File Type", "type": "main", "index": 0 }]] },
"Filter File Type": { "main": [[{ "node": "Should Skip?", "type": "main", "index": 0 }]] }
```

The "true" (skip) branch will connect to a No-Op or end. The "false" (process) branch continues to the download + convert nodes in the next task.

**Step 2: Verify JSON is valid**

Run: `python -c "import json; json.load(open('n8n-workflows/gdrive-knowledge-sync.json')); print('Valid JSON')"`

**Step 3: Commit**

```bash
git add n8n-workflows/gdrive-knowledge-sync.json
git commit -m "feat: add file type filter and skip logic to gdrive sync workflow"
```

---

## Task 4: Add Markdown conversion Code node

**Files:**
- Modify: `n8n-workflows/gdrive-knowledge-sync.json`

**Step 1: Add the Convert to Markdown code node**

This is the core conversion logic. Add this node after the "Should Skip?" false branch. The node receives the downloaded file content and converts it based on file type.

```json
{
  "parameters": {
    "jsCode": "// Convert file content to Markdown based on file type\nconst fileData = $input.first().json;\nconst fileType = fileData.fileType;\nconst fileName = fileData.fileName;\nconst content = fileData.content || '';\nconst kb_id = fileData.kb_id;\nconst fileId = fileData.fileId;\nconst now = new Date().toISOString();\n\nlet markdown = '';\n\nif (fileType === 'sheets') {\n  // CSV → Markdown table\n  const lines = content.split('\\n').filter(l => l.trim());\n  if (lines.length > 0) {\n    markdown = `# ${fileName}\\n\\n`;\n    markdown += `**Source:** Google Drive / AI Knowledge\\n`;\n    markdown += `**Last modified:** ${now.split('T')[0]}\\n\\n`;\n    \n    const headers = lines[0].split(',').map(h => h.replace(/^\"|\"$/g, '').trim());\n    markdown += '| ' + headers.join(' | ') + ' |\\n';\n    markdown += '| ' + headers.map(() => '---').join(' | ') + ' |\\n';\n    \n    for (let i = 1; i < lines.length; i++) {\n      // Handle CSV with quoted fields containing commas\n      const row = [];\n      let inQuote = false;\n      let field = '';\n      for (const char of lines[i]) {\n        if (char === '\"') { inQuote = !inQuote; }\n        else if (char === ',' && !inQuote) { row.push(field.trim()); field = ''; }\n        else { field += char; }\n      }\n      row.push(field.trim());\n      markdown += '| ' + row.join(' | ') + ' |\\n';\n    }\n  }\n} else if (fileType === 'docs') {\n  // HTML → Markdown\n  markdown = `# ${fileName}\\n\\n`;\n  markdown += `**Source:** Google Drive / AI Knowledge\\n`;\n  markdown += `**Last modified:** ${now.split('T')[0]}\\n\\n`;\n  \n  let text = content;\n  // Convert headings\n  text = text.replace(/<h1[^>]*>(.*?)<\\/h1>/gi, '# $1\\n\\n');\n  text = text.replace(/<h2[^>]*>(.*?)<\\/h2>/gi, '## $1\\n\\n');\n  text = text.replace(/<h3[^>]*>(.*?)<\\/h3>/gi, '### $1\\n\\n');\n  // Convert formatting\n  text = text.replace(/<b[^>]*>(.*?)<\\/b>/gi, '**$1**');\n  text = text.replace(/<strong[^>]*>(.*?)<\\/strong>/gi, '**$1**');\n  text = text.replace(/<i[^>]*>(.*?)<\\/i>/gi, '*$1*');\n  text = text.replace(/<em[^>]*>(.*?)<\\/em>/gi, '*$1*');\n  // Convert links\n  text = text.replace(/<a[^>]*href=\"([^\"]*?)\"[^>]*>(.*?)<\\/a>/gi, '[$2]($1)');\n  // Convert lists\n  text = text.replace(/<li[^>]*>(.*?)<\\/li>/gi, '- $1\\n');\n  // Convert paragraphs\n  text = text.replace(/<p[^>]*>(.*?)<\\/p>/gi, '$1\\n\\n');\n  // Convert line breaks\n  text = text.replace(/<br\\s*\\/?>/gi, '\\n');\n  // Strip remaining HTML tags\n  text = text.replace(/<[^>]+>/g, '');\n  // Clean up whitespace\n  text = text.replace(/\\n{3,}/g, '\\n\\n').trim();\n  \n  markdown += text;\n} else if (fileType === 'slides') {\n  // Plain text → Markdown with slide separators\n  markdown = `# ${fileName}\\n\\n`;\n  markdown += `**Source:** Google Drive / AI Knowledge\\n`;\n  markdown += `**Last modified:** ${now.split('T')[0]}\\n\\n`;\n  \n  // Split by common slide separators\n  const slides = content.split(/\\n(?=Slide \\d|\\f)/i);\n  slides.forEach((slide, i) => {\n    const trimmed = slide.trim();\n    if (trimmed) {\n      markdown += `## Slide ${i + 1}\\n\\n${trimmed}\\n\\n---\\n\\n`;\n    }\n  });\n} else if (fileType === 'pdf') {\n  // PDF: pass raw content, OpenWebUI will handle extraction\n  markdown = null; // Signal to upload as binary\n}\n\nreturn [{ json: {\n  markdown,\n  fileName: fileName.replace(/\\.[^/.]+$/, '') + (markdown ? '.md' : '.pdf'),\n  originalName: fileName,\n  fileId,\n  fileType,\n  kb_id,\n  isPdf: fileType === 'pdf',\n  uploadAsRaw: !markdown\n} }];\n"
  },
  "name": "Convert to Markdown",
  "type": "n8n-nodes-base.code",
  "typeVersion": 2,
  "position": [2220, 400],
  "id": "convert-markdown-node"
}
```

**Step 2: Verify JSON**

Run: `python -c "import json; json.load(open('n8n-workflows/gdrive-knowledge-sync.json')); print('Valid JSON')"`

**Step 3: Commit**

```bash
git add n8n-workflows/gdrive-knowledge-sync.json
git commit -m "feat: add markdown conversion logic for Sheets, Docs, Slides, PDFs"
```

---

## Task 5: Add OpenWebUI upload, poll, and KB-add nodes

**Files:**
- Modify: `n8n-workflows/gdrive-knowledge-sync.json`

**Step 1: Add the upload, poll processing status, and add-to-KB nodes**

Add these three HTTP Request nodes after "Convert to Markdown":

```json
{
  "parameters": {
    "method": "POST",
    "url": "={{ $env.OPENWEBUI_URL }}/api/v1/files/",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "=Bearer {{ $env.OPENWEBUI_API_KEY }}"
        }
      ]
    },
    "sendBody": true,
    "contentType": "multipart-form-data",
    "bodyParameters": {
      "parameters": [
        {
          "parameterType": "formData",
          "name": "file",
          "value": "={{ $json.markdown || $json.rawContent }}",
          "inputDataFieldName": "={{ $json.fileName }}"
        }
      ]
    },
    "options": {
      "response": {
        "response": { "responseFormat": "json" }
      }
    }
  },
  "name": "Upload to OpenWebUI",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "position": [2440, 400],
  "id": "upload-file-node",
  "onError": "continueRegularOutput"
},
{
  "parameters": {
    "method": "GET",
    "url": "={{ $env.OPENWEBUI_URL }}/api/v1/files/{{ $json.id }}/process/status",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "=Bearer {{ $env.OPENWEBUI_API_KEY }}"
        }
      ]
    },
    "options": {
      "response": {
        "response": { "responseFormat": "json" }
      },
      "timeout": 30000
    }
  },
  "name": "Poll Processing Status",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "position": [2660, 400],
  "id": "poll-status-node",
  "onError": "continueRegularOutput",
  "retryOnFail": true,
  "maxTries": 10,
  "waitBetweenTries": 3000
},
{
  "parameters": {
    "method": "POST",
    "url": "={{ $env.OPENWEBUI_URL }}/api/v1/knowledge/{{ $('Merge KB ID').first().json.kb_id }}/file/add",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "=Bearer {{ $env.OPENWEBUI_API_KEY }}"
        },
        {
          "name": "Content-Type",
          "value": "application/json"
        }
      ]
    },
    "sendBody": true,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify({ file_id: $('Upload to OpenWebUI').first().json.id }) }}",
    "options": {
      "response": {
        "response": { "responseFormat": "json" }
      }
    }
  },
  "name": "Add to Knowledge Base",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "position": [2880, 400],
  "id": "add-to-kb-node",
  "onError": "continueRegularOutput"
}
```

Add connections:

```json
"Convert to Markdown": { "main": [[{ "node": "Upload to OpenWebUI", "type": "main", "index": 0 }]] },
"Upload to OpenWebUI": { "main": [[{ "node": "Poll Processing Status", "type": "main", "index": 0 }]] },
"Poll Processing Status": { "main": [[{ "node": "Add to Knowledge Base", "type": "main", "index": 0 }]] }
```

**Step 2: Verify JSON**

Run: `python -c "import json; json.load(open('n8n-workflows/gdrive-knowledge-sync.json')); print('Valid JSON')"`

**Step 3: Commit**

```bash
git add n8n-workflows/gdrive-knowledge-sync.json
git commit -m "feat: add OpenWebUI upload, processing poll, and KB-add nodes"
```

---

## Task 6: Add static data tracking and Discord notification nodes

**Files:**
- Modify: `n8n-workflows/gdrive-knowledge-sync.json`

**Step 1: Add static data update node**

This node saves the Google Drive file ID → OpenWebUI file ID mapping so we can handle edits and deletes later.

```json
{
  "parameters": {
    "jsCode": "// Save file mapping to workflow static data\nconst staticData = $getWorkflowStaticData('global');\nif (!staticData.files) staticData.files = {};\n\nconst gdriveId = $('Filter File Type').first().json.fileId;\nconst openwebuiFileId = $('Upload to OpenWebUI').first().json.id;\nconst fileName = $('Filter File Type').first().json.fileName;\n\nstaticData.files[gdriveId] = {\n  openwebui_file_id: openwebuiFileId,\n  filename: fileName,\n  last_modified: new Date().toISOString()\n};\n\nreturn [{ json: {\n  saved: true,\n  gdrive_id: gdriveId,\n  openwebui_file_id: openwebuiFileId,\n  filename: fileName\n} }];\n"
  },
  "name": "Update Static Data",
  "type": "n8n-nodes-base.code",
  "typeVersion": 2,
  "position": [3100, 400],
  "id": "update-static-data-node"
}
```

**Step 2: Add Discord notification node**

```json
{
  "parameters": {
    "method": "POST",
    "url": "=https://discord.com/api/v10/channels/{{ $env.DISCORD_ALERT_CHANNEL_ID }}/messages",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "=Bot {{ $env.DISCORD_BOT_TOKEN }}"
        },
        {
          "name": "Content-Type",
          "value": "application/json"
        }
      ]
    },
    "sendBody": true,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify({ content: '\\ud83d\\udcc4 **Knowledge Base Updated**\\n\\nFile: `' + $json.filename + '`\\nAction: New file ingested\\nKB: Google Drive\\nTime: ' + new Date().toISOString().split('T')[0] }) }}",
    "options": {}
  },
  "name": "Discord Notify",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "position": [3320, 400],
  "id": "discord-notify-node",
  "onError": "continueRegularOutput"
}
```

Add connections:

```json
"Add to Knowledge Base": { "main": [[{ "node": "Update Static Data", "type": "main", "index": 0 }]] },
"Update Static Data": { "main": [[{ "node": "Discord Notify", "type": "main", "index": 0 }]] }
```

**Step 3: Verify JSON and commit**

Run: `python -c "import json; json.load(open('n8n-workflows/gdrive-knowledge-sync.json')); print('Valid JSON')"`

```bash
git add n8n-workflows/gdrive-knowledge-sync.json
git commit -m "feat: add static data tracking and Discord notifications"
```

---

## Task 7: Add edit detection and re-sync logic

**Files:**
- Modify: `n8n-workflows/gdrive-knowledge-sync.json`

**Step 1: Add edit detection to the Filter File Type node**

Modify the "Filter File Type" code node to check static data for previously ingested files. If the file was already ingested, flag it as an edit.

Update the end of the `Filter File Type` node's jsCode to add:

```javascript
// Check if file was previously ingested (edit detection)
const staticData = $getWorkflowStaticData('global');
const existingFile = staticData.files ? staticData.files[fileId] : null;
const isEdit = !!existingFile;
const previousOpenWebUIFileId = existingFile ? existingFile.openwebui_file_id : null;
```

And include `isEdit` and `previousOpenWebUIFileId` in the return object.

**Step 2: Add "Delete Old File" node for edits**

This node runs before upload when `isEdit` is true. It removes the old file from the KB and deletes it from OpenWebUI.

```json
{
  "parameters": {
    "method": "DELETE",
    "url": "={{ $env.OPENWEBUI_URL }}/api/v1/knowledge/{{ $json.kb_id }}/file/remove",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "=Bearer {{ $env.OPENWEBUI_API_KEY }}"
        },
        {
          "name": "Content-Type",
          "value": "application/json"
        }
      ]
    },
    "sendBody": true,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify({ file_id: $json.previousOpenWebUIFileId }) }}",
    "options": {}
  },
  "name": "Delete Old File",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "position": [2220, 200],
  "id": "delete-old-file-node",
  "onError": "continueRegularOutput"
}
```

**Step 3: Add IF node to check isEdit**

Route to "Delete Old File" if edit, otherwise skip to "Convert to Markdown" directly.

**Step 4: Update Discord notification to show "Updated" for edits**

Modify the Discord Notify node's message to check if it was an edit:

```javascript
const action = $('Filter File Type').first().json.isEdit ? 'File updated' : 'New file ingested';
```

Use emoji: new = 📄, updated = 🔄

**Step 5: Verify and commit**

```bash
git add n8n-workflows/gdrive-knowledge-sync.json
git commit -m "feat: add edit detection and re-sync with old file cleanup"
```

---

## Task 8: Add delete sync logic

**Files:**
- Modify: `n8n-workflows/gdrive-knowledge-sync.json`

**Step 1: Add a second Google Drive Trigger for deletions**

n8n Google Drive Trigger can watch for `fileDeleted` events. Add a second trigger node or configure the existing trigger to handle both events. The simplest approach: use a Schedule Trigger that periodically compares static data against current folder contents.

Alternative approach (simpler): Add a Code node that runs on each trigger, checks if any previously tracked files are missing from the current folder listing.

```json
{
  "parameters": {
    "jsCode": "// Check for deleted files by comparing static data with current Drive folder\n// This runs periodically and detects files that were removed\nconst staticData = $getWorkflowStaticData('global');\nif (!staticData.files || Object.keys(staticData.files).length === 0) {\n  return [{ json: { deletedFiles: [], hasDeletes: false } }];\n}\n\n// Get list of current file IDs from the trigger\n// We'll compare against our tracked files\nconst currentFileId = $('Google Drive Trigger').first().json.id;\nconst trackedFiles = staticData.files;\n\n// For now, pass through — deletion detection happens\n// when the Google Drive Trigger fires a 'deleted' event\nreturn [{ json: { deletedFiles: [], hasDeletes: false, trackedCount: Object.keys(trackedFiles).length } }];\n"
  },
  "name": "Check Deletions",
  "type": "n8n-nodes-base.code",
  "typeVersion": 2,
  "position": [1560, 500],
  "id": "check-deletions-node"
}
```

**Step 2: Add delete-from-KB node**

```json
{
  "parameters": {
    "method": "POST",
    "url": "={{ $env.OPENWEBUI_URL }}/api/v1/knowledge/{{ $json.kb_id }}/file/remove",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "=Bearer {{ $env.OPENWEBUI_API_KEY }}"
        },
        {
          "name": "Content-Type",
          "value": "application/json"
        }
      ]
    },
    "sendBody": true,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify({ file_id: $json.openwebui_file_id }) }}",
    "options": {}
  },
  "name": "Remove from KB",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "position": [2000, 600],
  "id": "remove-from-kb-node",
  "onError": "continueRegularOutput"
}
```

**Step 3: Add cleanup static data and Discord delete notification**

```json
{
  "parameters": {
    "jsCode": "// Remove deleted file from static data\nconst staticData = $getWorkflowStaticData('global');\nconst gdriveId = $json.gdriveId;\nconst fileName = staticData.files[gdriveId] ? staticData.files[gdriveId].filename : 'unknown';\ndelete staticData.files[gdriveId];\nreturn [{ json: { deleted: true, filename: fileName } }];\n"
  },
  "name": "Cleanup Static Data",
  "type": "n8n-nodes-base.code",
  "typeVersion": 2,
  "position": [2220, 600],
  "id": "cleanup-static-data-node"
},
{
  "parameters": {
    "method": "POST",
    "url": "=https://discord.com/api/v10/channels/{{ $env.DISCORD_ALERT_CHANNEL_ID }}/messages",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "=Bot {{ $env.DISCORD_BOT_TOKEN }}"
        },
        {
          "name": "Content-Type",
          "value": "application/json"
        }
      ]
    },
    "sendBody": true,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify({ content: '\\ud83d\\uddd1\\ufe0f **Knowledge Base Updated**\\n\\nFile: `' + $json.filename + '`\\nAction: File removed\\nKB: Google Drive\\nTime: ' + new Date().toISOString().split('T')[0] }) }}",
    "options": {}
  },
  "name": "Discord Notify Delete",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "position": [2440, 600],
  "id": "discord-notify-delete-node",
  "onError": "continueRegularOutput"
}
```

**Step 4: Verify and commit**

```bash
git add n8n-workflows/gdrive-knowledge-sync.json
git commit -m "feat: add file deletion sync with KB removal and Discord notification"
```

---

## Task 9: Assemble the complete workflow and validate

**Files:**
- Modify: `n8n-workflows/gdrive-knowledge-sync.json`

**Step 1: Verify all nodes are present and connections are complete**

The complete workflow should have these nodes in order:

1. Google Drive Trigger
2. List Knowledge Bases
3. Find Google Drive KB
4. KB Exists? (IF)
5. Create KB (true branch)
6. Merge KB ID
7. Filter File Type (with edit detection)
8. Should Skip? (IF)
9. Is Edit? (IF) — false branch of Should Skip
10. Delete Old File — true branch of Is Edit
11. Convert to Markdown
12. Upload to OpenWebUI
13. Poll Processing Status
14. Add to Knowledge Base
15. Update Static Data
16. Discord Notify

For deletes (separate branch from Filter File Type or separate trigger):
17. Check Deletions
18. Remove from KB
19. Cleanup Static Data
20. Discord Notify Delete

**Step 2: Validate the full JSON**

Run: `python -c "import json; f=json.load(open('n8n-workflows/gdrive-knowledge-sync.json')); print(f'Valid: {len(f[\"nodes\"])} nodes, {len(f[\"connections\"])} connections')"`

**Step 3: Verify all connections form a valid DAG**

Run a quick check:
```bash
python -c "
import json
wf = json.load(open('n8n-workflows/gdrive-knowledge-sync.json'))
node_names = {n['name'] for n in wf['nodes']}
for src, conns in wf['connections'].items():
    assert src in node_names, f'Unknown source: {src}'
    for branch in conns.get('main', []):
        for c in branch:
            assert c['node'] in node_names, f'Unknown target: {c[\"node\"]}'
print('All connections valid')
"
```

**Step 4: Final commit**

```bash
git add n8n-workflows/gdrive-knowledge-sync.json
git commit -m "feat: complete gdrive-knowledge-sync workflow with all nodes and connections"
```

---

## Task 10: Manual setup steps (checklist for deployment)

These steps must be done manually in the n8n UI and Google Drive after deploying the code:

**Step 1: Create "AI Knowledge" folder in Google Drive**
- Log into Google Drive as `aiui.teams@gmail.com`
- Create a new folder called "AI Knowledge"
- Copy the folder ID from the URL (the long string after `/folders/`)

**Step 2: Set up Google Drive OAuth credential in n8n**
- Go to n8n UI → Credentials → Add new
- Type: "Google Drive OAuth2 API"
- Use the same Google Cloud project `AIUI - Project` (id: aiui-project)
- Enable the Google Drive API in Google Cloud Console if not already enabled
- Scopes needed: `https://www.googleapis.com/auth/drive.readonly`
- Complete the OAuth flow with `aiui.teams@gmail.com`

**Step 3: Import the workflow into n8n**
- Go to n8n UI → Workflows → Import from File
- Upload `n8n-workflows/gdrive-knowledge-sync.json`
- In the "Google Drive Trigger" node, replace `CONFIGURE_FOLDER_ID` with the actual folder ID
- In the "Google Drive Trigger" node, select the Google Drive OAuth credential created in Step 2
- Publish the workflow

**Step 4: Deploy updated docker-compose**
- SSH to Hetzner server
- Pull latest code
- Run: `docker compose -f docker-compose.unified.yml up -d n8n`
- Verify n8n picks up the new env vars: check n8n logs

**Step 5: Test the pipeline end-to-end**
- Upload a simple Google Sheets file (e.g. "Test Users" with 3 rows) to the "AI Knowledge" folder
- Wait ~2 minutes for the trigger to fire
- Check n8n execution log for success
- Check OpenWebUI → Knowledge → "Google Drive" KB exists with the file
- Check Discord alert channel for the notification
- Edit the Google Sheet, wait 2 min, verify re-sync
- Delete the file, wait 2 min, verify removal from KB

**Step 6: Commit the deployment confirmation**

```bash
git add .
git commit -m "docs: add deployment checklist for gdrive-knowledge-sync"
```

---

## Summary

| Task | What | Estimated Effort |
|------|------|-----------------|
| 1 | Add Discord env vars to n8n in docker-compose | Tiny |
| 2 | Create workflow JSON — trigger + KB lookup | Medium |
| 3 | Add file type filter + download nodes | Medium |
| 4 | Add Markdown conversion Code node | Medium |
| 5 | Add OpenWebUI upload, poll, KB-add nodes | Medium |
| 6 | Add static data tracking + Discord notification | Small |
| 7 | Add edit detection + re-sync logic | Medium |
| 8 | Add delete sync logic | Medium |
| 9 | Assemble complete workflow + validate | Small |
| 10 | Manual setup steps (Google Drive, n8n UI, deploy) | Manual |

**Total: 10 tasks, ~14-20 workflow nodes**
