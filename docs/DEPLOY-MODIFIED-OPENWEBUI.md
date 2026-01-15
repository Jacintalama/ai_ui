# Deploy Modified Open WebUI with Group Header Forwarding

**Date:** January 15, 2026
**Changes:** MCP group header forwarding feature

---

## Summary of Code Changes

Two files modified in `C:\Users\alama\Desktop\Lukas Work\ai_ui\ai_ui`:

1. **backend/open_webui/utils/headers.py**
   - Added optional `groups` parameter
   - Now sends `X-OpenWebUI-User-Groups` header when groups provided

2. **backend/open_webui/utils/middleware.py**
   - Fetches user's groups from database
   - Passes groups to `include_user_info_headers()` when connecting to MCP servers

---

## Option 1: Build and Deploy Locally (Docker Desktop Kubernetes)

### Step 1: Build Docker Image

```powershell
cd "C:\Users\alama\Desktop\Lukas Work\ai_ui\ai_ui"

# Build the image (takes 10-30 minutes)
docker build -t open-webui:v0.7.2-groups .
```

### Step 2: Load Image to Kubernetes

For Docker Desktop Kubernetes, the image is automatically available.

### Step 3: Update Deployment

```powershell
# Update the statefulset to use new image
kubectl set image statefulset/open-webui open-webui=open-webui:v0.7.2-groups -n open-webui

# Or patch the statefulset
kubectl patch statefulset open-webui -n open-webui -p '{"spec":{"template":{"spec":{"containers":[{"name":"open-webui","image":"open-webui:v0.7.2-groups","imagePullPolicy":"IfNotPresent"}]}}}}'
```

### Step 4: Verify Deployment

```powershell
# Watch rollout
kubectl rollout status statefulset/open-webui -n open-webui

# Check pod is running
kubectl get pods -n open-webui -l app=open-webui

# Check logs
kubectl logs -f open-webui-0 -n open-webui
```

---

## Option 2: Push to Container Registry

### Step 1: Tag for Registry

```powershell
# Example for Docker Hub
docker tag open-webui:v0.7.2-groups yourusername/open-webui:v0.7.2-groups
docker push yourusername/open-webui:v0.7.2-groups

# Example for Azure Container Registry
docker tag open-webui:v0.7.2-groups yourregistry.azurecr.io/open-webui:v0.7.2-groups
docker push yourregistry.azurecr.io/open-webui:v0.7.2-groups
```

### Step 2: Update Kubernetes

```powershell
kubectl set image statefulset/open-webui open-webui=yourusername/open-webui:v0.7.2-groups -n open-webui
```

---

## Option 3: Quick Test with Port Forward

### Step 1: Build Image
```powershell
docker build -t open-webui:v0.7.2-groups "C:\Users\alama\Desktop\Lukas Work\ai_ui\ai_ui"
```

### Step 2: Run Locally
```powershell
docker run -d --name open-webui-test \
  -p 3000:8080 \
  -e ENABLE_FORWARD_USER_INFO_HEADERS=true \
  -e DATABASE_URL=postgresql://openwebui:password@host.docker.internal:5432/openwebui \
  open-webui:v0.7.2-groups
```

### Step 3: Test
Open http://localhost:3000 and test the group forwarding

---

## Verify Feature is Working

### Check Headers Being Sent

1. Login to Open WebUI
2. Open DevTools → Network tab
3. Trigger an MCP tool call
4. Check request headers for `X-OpenWebUI-User-Groups`

### Check MCP Proxy Logs

```powershell
kubectl logs -f deployment/mcp-proxy -n open-webui | findstr "groups"
```

Expected output:
```
[GROUP-BASED] user@highspring.com groups=['Tenant-Google'] -> github: True
```

---

## Rollback if Needed

```powershell
# Rollback to original image
kubectl set image statefulset/open-webui open-webui=ghcr.io/open-webui/open-webui:v0.7.2 -n open-webui
```

---

## Git Commits Made

```
ad1b44117 - feat: add optional groups parameter to include_user_info_headers
b6f8772f2 - feat: forward user groups to MCP servers via X-OpenWebUI-User-Groups header
```

---

*Created: January 15, 2026*
