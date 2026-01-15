# Kubernetes Deployment Guide

**Date:** 2026-01-07
**Purpose:** Kubernetes deployment using official Open WebUI Helm charts

---

## CRITICAL: Do NOT Use Custom Infrastructure!

**Client's infrastructure issue:**
> "Infrastructure guy built wrong solution - 10 databases, custom Kubernetes setup"

**Solution:** Use the **official Open WebUI Helm charts**. Do NOT reinvent the wheel!

---

## Official Helm Charts

### Repository Information

| Property | Value |
|----------|-------|
| **Helm Repo URL** | https://helm.openwebui.com |
| **GitHub** | https://github.com/open-webui/helm-charts |
| **ArtifactHub** | https://artifacthub.io/packages/helm/open-webui/open-webui |
| **Current Version** | 9.0.0 |

### Add Helm Repository

```bash
helm repo add open-webui https://helm.openwebui.com
helm repo update
```

---

## Installation

### Basic Installation

```bash
# Create namespace
kubectl create namespace open-webui

# Install with defaults
helm install open-webui open-webui/open-webui \
  --namespace open-webui
```

### Production Installation

```bash
helm install open-webui open-webui/open-webui \
  --namespace open-webui \
  --create-namespace \
  --set persistence.enabled=true \
  --set persistence.size=50Gi \
  --set ingress.enabled=true \
  --set ingress.host=chat.company.com
```

---

## Key Configuration Options

### Replicas & Scaling

| Setting | Default | Notes |
|---------|---------|-------|
| `replicaCount` | 1 | Start with 1, scale after initial setup |
| `persistence.accessModes` | ReadWriteOnce | Use `ReadWriteMany` for multiple replicas |

**CRITICAL SCALING WARNING:**

> If using multiple replicas (replicaCount > 1), you MUST:
> 1. Scale down to 1 replica during updates
> 2. Wait for database migrations to complete
> 3. Then scale back up
>
> **Failure to do this can cause database corruption!**

### Image Settings

```yaml
image:
  repository: ghcr.io/open-webui/open-webui
  tag: ""  # Uses chart version by default
  pullPolicy: IfNotPresent

# For slim image (smaller, no ML libraries)
useSlim: true
```

### Persistence

```yaml
persistence:
  enabled: true
  size: 50Gi  # Adjust based on needs
  accessModes:
    - ReadWriteOnce  # Change to ReadWriteMany for multiple replicas
  storageClass: ""  # Use cluster default or specify
```

### Ingress

```yaml
ingress:
  enabled: true
  className: nginx  # or gce, traefik, etc.
  hosts:
    - host: chat.company.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: open-webui-tls
      hosts:
        - chat.company.com
```

### Database Options

**Option A: SQLite (Default)**
- Simple, no external database needed
- Good for small deployments
- Persistence via PVC

**Option B: PostgreSQL (Recommended for Production)**
```yaml
postgresql:
  enabled: true
  auth:
    database: openwebui
    username: openwebui
  primary:
    persistence:
      enabled: true
      size: 20Gi
```

**NOT 10 databases** - just ONE PostgreSQL instance!

---

## Optional Dependencies

### Ollama (Local LLMs)

```yaml
ollama:
  enabled: true
  persistence:
    enabled: true
    size: 50Gi
  resources:
    requests:
      nvidia.com/gpu: 1
```

### Pipelines

```yaml
pipelines:
  enabled: true
```

### Redis (Required for Websockets with Multiple Replicas)

```yaml
redis:
  enabled: true
```

---

## Custom Values File

Create `kubernetes/values.yaml`:

```yaml
# kubernetes/values.yaml
# Open WebUI Helm Chart - Company GPT Configuration

replicaCount: 3  # Scale based on user load

image:
  repository: ghcr.io/open-webui/open-webui
  tag: main
  pullPolicy: Always

service:
  type: ClusterIP
  port: 8080

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: chat.company.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: open-webui-tls
      hosts:
        - chat.company.com

persistence:
  enabled: true
  size: 50Gi
  accessModes:
    - ReadWriteMany  # For multiple replicas
  storageClass: standard

postgresql:
  enabled: true
  auth:
    database: openwebui
    username: openwebui
    existingSecret: open-webui-postgres  # Create this secret
  primary:
    persistence:
      enabled: true
      size: 20Gi

redis:
  enabled: true  # Required for websockets with multiple replicas

# Environment variables
env:
  - name: BYPASS_MODEL_ACCESS_CONTROL
    value: "true"
  - name: ENABLE_FORWARD_USER_INFO_HEADERS
    value: "true"

# MCP Proxy sidecar (our multi-tenant gateway)
extraContainers:
  - name: mcp-proxy
    image: company/mcp-proxy:latest
    ports:
      - containerPort: 8080
        name: mcp-proxy
    env:
      - name: MCP_API_KEY
        valueFrom:
          secretKeyRef:
            name: mcp-secrets
            key: api-key
```

### Install with Custom Values

```bash
helm install open-webui open-webui/open-webui \
  --namespace open-webui \
  --create-namespace \
  -f kubernetes/values.yaml
```

---

## Scaling Guidelines

### For 15,000 Users

| Component | Recommendation |
|-----------|----------------|
| **Open WebUI Replicas** | 3-5 (start with 3) |
| **PostgreSQL** | Single instance, 20Gi+ |
| **Redis** | Single instance |
| **Storage Class** | Use RWX-capable storage |
| **Ingress** | Configure with load balancer |

### Resource Estimates

```yaml
resources:
  requests:
    memory: "1Gi"
    cpu: "500m"
  limits:
    memory: "4Gi"
    cpu: "2"
```

---

## Verification Commands

```bash
# Check pods
kubectl get pods -n open-webui

# Check services
kubectl get svc -n open-webui

# Check ingress
kubectl get ingress -n open-webui

# View logs
kubectl logs -f deployment/open-webui -n open-webui

# Check PVCs
kubectl get pvc -n open-webui
```

---

## Migration from Docker Compose

1. **Export existing data** from Docker volumes
2. **Create PVC** in Kubernetes
3. **Copy data** to PVC
4. **Install Helm chart** with persistence enabled
5. **Verify** data is accessible

---

## Common Issues

### Database Corruption on Update

**Cause:** Multiple replicas running during migration

**Solution:** Always scale to 1 replica before updates:
```bash
kubectl scale deployment open-webui --replicas=1 -n open-webui
# Wait for migration
kubectl scale deployment open-webui --replicas=3 -n open-webui
```

### Persistence Issues with Multiple Replicas

**Cause:** Using `ReadWriteOnce` with multiple pods

**Solution:** Use `ReadWriteMany` storage class or external database

### Ingress Not Working

**Cause:** Ingress class not installed

**Solution:** Install ingress controller:
```bash
helm install nginx-ingress ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace
```

---

## References

- [Official Helm Charts](https://github.com/open-webui/helm-charts)
- [Open WebUI Docs](https://docs.openwebui.com/getting-started/quick-start/)
- [ArtifactHub](https://artifacthub.io/packages/helm/open-webui/open-webui)
- [Helm Charts DeepWiki](https://deepwiki.com/open-webui/helm-charts)

---

## Summary

| DO | DON'T |
|----|-------|
| Use official Helm charts | Create custom infrastructure |
| Use ONE PostgreSQL database | Create 10 databases |
| Scale replicas carefully | Update with multiple replicas |
| Use ReadWriteMany for scaling | Ignore storage class requirements |
| Configure ingress properly | Expose NodePort directly |
