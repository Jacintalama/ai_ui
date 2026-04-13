# Fathom KB Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add OpenWebUI Knowledge Base saving as a third parallel output to the existing Fathom n8n workflow, so the AI can search past meetings and return summaries with recording links.

**Architecture:** Extend the existing n8n workflow (Trigger → Parse → [Sheets, Discord]) with a third parallel branch (Parse → Format Markdown → Upload to OpenWebUI → Add to KB). Uses OpenWebUI's built-in KB API with PGVector auto-embedding. No new containers.

**Tech Stack:** n8n Cloud (API), OpenWebUI REST API, Python (for deployment script)

---

### Task 1: Create "Meeting Transcripts" Knowledge Base in OpenWebUI

**Context:** OpenWebUI needs a KB collection to exist before we can add files to it. We create it once via API.

**Step 1: Generate an OpenWebUI API key**

Open `https://ai-ui.coolestdomain.win` → Settings → Account → API Keys → Create new key. Save the key — it will be used as Bearer token for all KB API calls.

Alternatively, check if the existing n8n workflows use a token. Look at the gdrive-knowledge-sync workflow for the auth header pattern.

**Step 2: Create the KB via API**

```bash
curl -X POST "https://ai-ui.coolestdomain.win/api/v1/knowledge/create" \
  -H "Authorization: Bearer {OPENWEBUI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"name": "Meeting Transcripts", "description": "Fathom meeting summaries with recording links. Auto-populated from team meetings."}'
```

Expected response: `{"id": "kb-uuid-here", "name": "Meeting Transcripts", ...}`

**Step 3: Save the KB ID**

Note the `id` from the response. This will be hardcoded in the n8n workflow nodes.

**Step 4: Verify KB exists**

```bash
curl "https://ai-ui.coolestdomain.win/api/v1/knowledge/" \
  -H "Authorization: Bearer {OPENWEBUI_API_KEY}" | python3 -c "
import sys,json
data = json.load(sys.stdin)
items = data if isinstance(data, list) else data.get('items', data.get('data', []))
for kb in items:
    print(kb.get('id','?'), kb.get('name','?'))
"
```

Expected: See "Meeting Transcripts" in the list.

---

### Task 2: Test the KB upload flow manually

**Context:** Before adding to n8n, verify the 3-step upload works: upload file → poll status → add to KB.

**Step 1: Upload a test Markdown file**

```bash
curl -X POST "https://ai-ui.coolestdomain.win/api/v1/files/" \
  -H "Authorization: Bearer {OPENWEBUI_API_KEY}" \
  -F "file=@-;filename=test-meeting.md;type=text/markdown" <<'EOF'
# Test Meeting
Date: 2026-04-02 | Attendees: Test User

## Summary
This is a test meeting to verify KB upload works.

## Recording
https://fathom.video/test
EOF
```

Expected: `{"id": "file-uuid", "filename": "test-meeting.md", ...}`

**Step 2: Poll for processing completion**

```bash
curl "https://ai-ui.coolestdomain.win/api/v1/files/{file-uuid}/process/status" \
  -H "Authorization: Bearer {OPENWEBUI_API_KEY}"
```

Expected: `{"status": "completed"}` (may need to poll a few times)

**Step 3: Add file to KB**

```bash
curl -X POST "https://ai-ui.coolestdomain.win/api/v1/knowledge/{kb-id}/file/add" \
  -H "Authorization: Bearer {OPENWEBUI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"file_id": "{file-uuid}"}'
```

Expected: Success response.

**Step 4: Verify in AIUI chat**

Go to `https://ai-ui.coolestdomain.win`, start a chat, select "Meeting Transcripts" knowledge base, and ask "What was discussed in the test meeting?" — should return the summary.

**Step 5: Clean up test file**

Delete the test file from the KB if desired.

---

### Task 3: Add KB nodes to the n8n workflow

**Context:** The current workflow `Sm87Or7vch38JCUE` has: Parse → [Sheets, Discord]. We add a third branch: Parse → [Sheets, Discord, KB Save Chain].

**Files:**
- Modify: n8n workflow via API (workflow ID from current active workflow)
- Reference: `mcp-servers/web-search/main.py:165-253` (KB upload pattern)
- Reference: `n8n-workflows/fathom-transcript-processor.json` (node structure)

**Step 1: Write the deployment script**

Create `scripts/deploy-fathom-kb.py` that:
1. Gets the current workflow via API
2. Adds 3 new nodes:
   - **"Format KB Document"** (Code node) — builds Markdown from `$json` fields
   - **"Upload to OpenWebUI"** (HTTP Request node) — POST multipart file upload
   - **"Add to KB"** (HTTP Request node) — POST to add file to KB
3. Updates connections: Parse → [Sheets, Discord, Format KB Document]
4. Chain: Format KB Document → Upload to OpenWebUI → Add to KB
5. Deletes old workflow, creates new, activates

**Format KB Document code node:**

```javascript
const r = $json;
const content = `# ${r.title || 'Meeting'}
Date: ${r.date || ''} | Duration: ${r.duration || 'N/A'} | Attendees: ${r.attendees || 'N/A'}

${r.summary || 'No summary available.'}

## Action Items
${r.action_items || 'None identified'}

## Recording
${r.fathom_link || 'No recording link'}
`;

const filename = `meeting-${r.date || 'unknown'}-${(r.title || 'meeting').toLowerCase().replace(/[^a-z0-9]+/g, '-').substring(0, 50)}.md`;

return [{
  json: {
    content,
    filename,
    title: r.title,
    date: r.date
  }
}];
```

**Upload to OpenWebUI node:**

- Method: POST
- URL: `https://ai-ui.coolestdomain.win/api/v1/files/`
- Auth: Bearer `{OPENWEBUI_API_KEY}`
- Body: Form-data with `file` field (content from previous node, filename from previous node)
- Content-Type: multipart/form-data

**Add to KB node:**

- Method: POST
- URL: `https://ai-ui.coolestdomain.win/api/v1/knowledge/{KB_ID}/file/add`
- Auth: Bearer `{OPENWEBUI_API_KEY}`
- Body: JSON `{"file_id": "{{ $json.id }}"}`

**Step 2: Handle file upload in n8n**

n8n's HTTP Request node can send form-data. The file content needs to be sent as a binary attachment. Two approaches:
- Use n8n's "Convert to File" node before the HTTP Request
- Or use a Code node that constructs the multipart request

The simplest: use a Code node that calls the OpenWebUI API directly with `fetch()` (n8n Code nodes support fetch).

**Alternative: Single Code node for entire KB flow:**

Instead of 3 nodes, use ONE Code node that does everything:
1. Format markdown
2. Upload via fetch()
3. Poll for completion
4. Add to KB

This is simpler and avoids n8n's multipart form-data quirks.

```javascript
// Save to OpenWebUI Knowledge Base
const r = $input.first().json;
const API_URL = 'https://ai-ui.coolestdomain.win';
const API_KEY = '{OPENWEBUI_API_KEY}';
const KB_ID = '{KB_ID}';

// 1. Format markdown
const content = `# ${r.title || 'Meeting'}
Date: ${r.date || ''} | Duration: ${r.duration || 'N/A'} | Attendees: ${r.attendees || 'N/A'}

${r.summary || 'No summary available.'}

## Action Items
${r.action_items || 'None identified'}

## Recording
${r.fathom_link || 'No recording link'}
`;

const filename = `meeting-${r.date}-${(r.title || 'meeting').toLowerCase().replace(/[^a-z0-9]+/g, '-').substring(0, 50)}.md`;

// 2. Upload file
const formData = new FormData();
formData.append('file', new Blob([content], {type: 'text/markdown'}), filename);

const uploadRes = await fetch(`${API_URL}/api/v1/files/`, {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${API_KEY}` },
  body: formData
});
const fileData = await uploadRes.json();

if (!fileData.id) {
  return [{ json: { kb_status: 'upload_failed', error: JSON.stringify(fileData) } }];
}

// 3. Poll for processing (max 30 retries)
let status = 'processing';
for (let i = 0; i < 30 && status === 'processing'; i++) {
  await new Promise(resolve => setTimeout(resolve, 2000));
  const pollRes = await fetch(`${API_URL}/api/v1/files/${fileData.id}/process/status`, {
    headers: { 'Authorization': `Bearer ${API_KEY}` }
  });
  const pollData = await pollRes.json();
  status = pollData.status || 'unknown';
}

if (status !== 'completed') {
  return [{ json: { kb_status: 'processing_timeout', file_id: fileData.id } }];
}

// 4. Add to KB
const addRes = await fetch(`${API_URL}/api/v1/knowledge/${KB_ID}/file/add`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${API_KEY}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ file_id: fileData.id })
});

return [{ json: { kb_status: 'saved', file_id: fileData.id, filename } }];
```

**Step 3: Deploy the updated workflow**

Run the deployment script to update the n8n workflow with the new KB node.

**Step 4: Commit**

```bash
git add scripts/deploy-fathom-kb.py docs/plans/2026-04-02-fathom-kb-integration-design.md
git commit -m "feat: add Fathom meeting KB integration design and deploy script"
```

---

### Task 4: Test end-to-end with a real Fathom email

**Step 1: Send a Fathom recording**

Have a short meeting with Fathom recording. Don't open the email.

**Step 2: Monitor execution**

```bash
curl -s "https://n8n.srv1041674.hstgr.cloud/api/v1/executions?workflowId={WF_ID}&limit=3" \
  -H "X-N8N-API-KEY: {N8N_KEY}" | python3 -c "..."
```

Expected: Execution with status "success".

**Step 3: Verify all 3 outputs**

1. **Google Sheet** — New row with meeting data
2. **Discord #general** — New message with formatted summary
3. **OpenWebUI KB** — New file in "Meeting Transcripts" collection

**Step 4: Test AI retrieval**

In AIUI chat, with "Meeting Transcripts" KB selected, ask:
- "What was our latest meeting about?"
- "What action items came from the last meeting?"
- "Show me the recording link for the meeting about [topic]"

Should return accurate answers with the Fathom video link.

---

### Task 5: Handle edge cases and deduplication

**Step 1: Add email_id tracking to prevent duplicates**

Use n8n workflow static data to track processed email IDs:
```javascript
const staticData = $getWorkflowStaticData('global');
if (!staticData.processedEmails) staticData.processedEmails = {};
if (staticData.processedEmails[r.email_id]) {
  return [{ json: { kb_status: 'skipped_duplicate' } }];
}
staticData.processedEmails[r.email_id] = { date: r.date, title: r.title };
```

**Step 2: Handle API failures gracefully**

Wrap KB code in try/catch — if KB save fails, return error status but don't break the workflow. Sheets and Discord continue independently.

**Step 3: Test duplicate handling**

Mark the same email as unread and let the workflow re-process. KB should skip it.

---

### Task 6 (Future): Discord KB retrieval

**Context:** Not blocking — can be added later. The webhook-handler already has an OpenWebUI chat client.

**Approach:** Add a Discord slash command `/meeting [query]` that:
1. Calls OpenWebUI chat completions API with the "Meeting Transcripts" KB context
2. Returns the AI's answer to Discord

**File to modify:** `webhook-handler/handlers/commands.py`

---

### Open Items Before Starting

1. **OpenWebUI API key** — Need to generate one from the admin panel, OR confirm which auth method the existing gdrive-sync workflow uses
2. **n8n → OpenWebUI connectivity** — Confirm n8n Cloud can reach `https://ai-ui.coolestdomain.win/api/v1/` through Caddy
3. **Current workflow ID** — Get the latest active Fathom workflow ID (currently `Sm87Or7vch38JCUE`)
