# Kubernetes Production Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy Open WebUI with MCP Proxy Gateway on Azure Kubernetes Service (AKS) using official Helm charts, connected to Azure Database for PostgreSQL with multi-tenant isolation.

**Architecture:**
- Open WebUI deployed via official Helm chart with external PostgreSQL (Azure managed)
- MCP Proxy Gateway deployed as sidecar/separate deployment for multi-tenant tool access
- Redis for session management across multiple replicas
- Row-level security via workspace_id in PostgreSQL for tenant isolation

**Tech Stack:**
- Azure Kubernetes Service (AKS)
- Azure Database for PostgreSQL Flexible Server (with pgvector)
- Official Open WebUI Helm Chart (v9.0.0+)
- Redis (for WebSocket sessions)
- Helm 3.x, kubectl

---

## Prerequisites

Before starting, ensure you have:
- Azure CLI installed and authenticated (`az login`)
- kubectl configured for your AKS cluster
- Helm 3.x installed
- Access to Azure portal for database creation

---

## Task 1: Create Azure Database for PostgreSQL

**Goal:** Set up managed PostgreSQL with pgvector extension for Open WebUI.

**Step 1: Create PostgreSQL Flexible Server via Azure CLI**

```bash
# Set variables
RESOURCE_GROUP="openwebui-prod-rg"
LOCATION="eastus"
PG_SERVER_NAME="openwebui-pg-prod"
PG_ADMIN_USER="openwebui_admin"
PG_ADMIN_PASSWORD="<generate-secure-password>"
PG_SKU="Standard_D4ds_v5"  # 4 vCores, good for 15k users

# Create resource group (if not exists)
az group create --name $RESOURCE_GROUP --location $LOCATION

# Create PostgreSQL Flexible Server
az postgres flexible-server create \
  --resource-group $RESOURCE_GROUP \
  --name $PG_SERVER_NAME \
  --location $LOCATION \
  --admin-user $PG_ADMIN_USER \
  --admin-password $PG_ADMIN_PASSWORD \
  --sku-name $PG_SKU \
  --storage-size 128 \
  --version 16 \
  --high-availability ZoneRedundant \
  --public-access None
```

Expected: PostgreSQL server created with zone-redundant HA.

**Step 2: Enable pgvector extension**

```bash
# Enable pgvector extension on the server
az postgres flexible-server parameter set \
  --resource-group $RESOURCE_GROUP \
  --server-name $PG_SERVER_NAME \
  --name azure.extensions \
  --value vector

# Connect and create database
az postgres flexible-server db create \
  --resource-group $RESOURCE_GROUP \
  --server-name $PG_SERVER_NAME \
  --database-name openwebui
```

**Step 3: Configure firewall for AKS**

```bash
# Get AKS outbound IP (or use private endpoint for production)
AKS_OUTBOUND_IP=$(az aks show -g $RESOURCE_GROUP -n openwebui-aks --query networkProfile.loadBalancerProfile.effectiveOutboundIPs[0].id -o tsv | xargs az network public-ip show --ids --query ipAddress -o tsv)

# Add firewall rule
az postgres flexible-server firewall-rule create \
  --resource-group $RESOURCE_GROUP \
  --name $PG_SERVER_NAME \
  --rule-name AllowAKS \
  --start-ip-address $AKS_OUTBOUND_IP \
  --end-ip-address $AKS_OUTBOUND_IP
```

**Step 4: Verify connection**

```bash
# Test connection (requires psql)
psql "host=${PG_SERVER_NAME}.postgres.database.azure.com port=5432 dbname=openwebui user=${PG_ADMIN_USER} sslmode=require"
```

Expected: Connected to PostgreSQL.

---

## Task 2: Create Kubernetes Namespace and Secrets

**Goal:** Set up namespace and secrets for Open WebUI deployment.

**Files:**
- Create: `kubernetes/namespace.yaml`
- Create: `kubernetes/secrets.yaml`

**Step 1: Create namespace manifest**

Create file `kubernetes/namespace.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: open-webui
  labels:
    app.kubernetes.io/name: open-webui
    app.kubernetes.io/part-of: company-gpt
```

**Step 2: Apply namespace**

```bash
kubectl apply -f kubernetes/namespace.yaml
```

Expected: `namespace/open-webui created`

**Step 3: Create secrets manifest**

Create file `kubernetes/secrets.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: open-webui-secrets
  namespace: open-webui
type: Opaque
stringData:
  # PostgreSQL connection
  DATABASE_URL: "postgresql://openwebui_admin:<password>@openwebui-pg-prod.postgres.database.azure.com:5432/openwebui?sslmode=require"

  # Open WebUI secret key (generate with: openssl rand -hex 32)
  WEBUI_SECRET_KEY: "<generate-32-byte-hex>"

  # MCP Proxy API Key
  MCP_PROXY_API_KEY: "<generate-api-key>"

---
apiVersion: v1
kind: Secret
metadata:
  name: mcp-tenant-credentials
  namespace: open-webui
type: Opaque
stringData:
  # Tenant API keys (add your tenant credentials here)
  GOOGLE_JIRA_API_KEY: "<google-jira-api-key>"
  MICROSOFT_JIRA_API_KEY: "<microsoft-jira-api-key>"
  GITHUB_TOKEN: "<github-token>"
```

**Step 4: Apply secrets**

```bash
# IMPORTANT: Replace placeholder values first!
kubectl apply -f kubernetes/secrets.yaml
```

Expected: `secret/open-webui-secrets created`

**Step 5: Verify secrets**

```bash
kubectl get secrets -n open-webui
```

Expected: Shows `open-webui-secrets` and `mcp-tenant-credentials`.

**Step 6: Commit**

```bash
git add kubernetes/
git commit -m "feat: add kubernetes namespace and secrets manifests"
```

---

## Task 3: Configure Open WebUI Helm Values

**Goal:** Create production Helm values file for Open WebUI.

**Files:**
- Create: `kubernetes/values-production.yaml`

**Step 1: Add Helm repository**

```bash
helm repo add open-webui https://helm.openwebui.com
helm repo update
```

Expected: `"open-webui" has been added to your repositories`

**Step 2: Create production values file**

Create file `kubernetes/values-production.yaml`:

```yaml
# kubernetes/values-production.yaml
# Open WebUI Production Configuration for Azure

# Replica count for high availability
replicaCount: 3

image:
  repository: ghcr.io/open-webui/open-webui
  tag: "main"
  pullPolicy: Always

# Service configuration
service:
  type: ClusterIP
  port: 8080

# Ingress configuration (Azure Application Gateway or NGINX)
ingress:
  enabled: true
  className: nginx  # or azure-application-gateway
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
  hosts:
    - host: chat.company.com  # Replace with actual domain
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: open-webui-tls
      hosts:
        - chat.company.com

# Persistence - using external PostgreSQL, so minimal local storage
persistence:
  enabled: true
  size: 10Gi  # For uploaded files only
  accessModes:
    - ReadWriteMany  # Required for multiple replicas
  storageClass: azurefile-csi  # Azure Files for RWX

# External PostgreSQL (Azure Database for PostgreSQL)
postgresql:
  enabled: false  # Disable in-cluster PostgreSQL

# Redis for WebSocket sessions (required for multiple replicas)
redis:
  enabled: true
  architecture: standalone
  auth:
    enabled: true
    existingSecret: open-webui-secrets
    existingSecretPasswordKey: REDIS_PASSWORD

# Ollama - disable if using external LLM APIs only
ollama:
  enabled: false

# Pipelines
pipelines:
  enabled: true

# Environment variables
env:
  # Database connection
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: open-webui-secrets
        key: DATABASE_URL

  # Security
  - name: WEBUI_SECRET_KEY
    valueFrom:
      secretKeyRef:
        name: open-webui-secrets
        key: WEBUI_SECRET_KEY

  # User info forwarding for MCP Proxy
  - name: ENABLE_FORWARD_USER_INFO_HEADERS
    value: "true"

  # Model access
  - name: BYPASS_MODEL_ACCESS_CONTROL
    value: "false"

  # Enable workspaces for multi-tenant
  - name: ENABLE_WORKSPACE
    value: "true"

# Resource limits for 15,000 users
resources:
  requests:
    memory: "2Gi"
    cpu: "1"
  limits:
    memory: "8Gi"
    cpu: "4"

# Pod disruption budget for HA
podDisruptionBudget:
  enabled: true
  minAvailable: 2

# Health checks
livenessProbe:
  enabled: true
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  enabled: true
  initialDelaySeconds: 10
  periodSeconds: 5

# Node affinity (optional - for dedicated nodes)
# nodeSelector:
#   workload: openwebui

# Tolerations (optional)
# tolerations: []
```

**Step 3: Validate values file**

```bash
helm template open-webui open-webui/open-webui \
  --namespace open-webui \
  -f kubernetes/values-production.yaml \
  --dry-run > /dev/null && echo "Values file valid"
```

Expected: `Values file valid`

**Step 4: Commit**

```bash
git add kubernetes/values-production.yaml
git commit -m "feat: add production Helm values for Open WebUI"
```

---

## Task 4: Deploy MCP Proxy Gateway

**Goal:** Deploy the MCP Proxy Gateway as a Kubernetes deployment alongside Open WebUI.

**Files:**
- Create: `kubernetes/mcp-proxy-deployment.yaml`
- Create: `kubernetes/mcp-proxy-service.yaml`
- Create: `kubernetes/mcp-proxy-configmap.yaml`

**Step 1: Create ConfigMap for tenant configuration**

Create file `kubernetes/mcp-proxy-configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-proxy-config
  namespace: open-webui
data:
  tenants.json: |
    {
      "google": {
        "tenant_id": "google",
        "display_name": "Google",
        "mcp_endpoint": "http://mcp-filesystem:8001",
        "enabled": true,
        "allowed_users": ["*@google.com"],
        "allowed_groups": ["google-employees"]
      },
      "microsoft": {
        "tenant_id": "microsoft",
        "display_name": "Microsoft",
        "mcp_endpoint": "http://mcp-filesystem:8001",
        "enabled": true,
        "allowed_users": ["*@microsoft.com"],
        "allowed_groups": ["microsoft-employees"]
      },
      "github": {
        "tenant_id": "github",
        "display_name": "GitHub",
        "mcp_endpoint": "http://mcp-github:8002",
        "enabled": true,
        "allowed_users": ["*"],
        "allowed_groups": ["developers"]
      }
    }
```

**Step 2: Create Deployment**

Create file `kubernetes/mcp-proxy-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-proxy
  namespace: open-webui
  labels:
    app: mcp-proxy
spec:
  replicas: 2
  selector:
    matchLabels:
      app: mcp-proxy
  template:
    metadata:
      labels:
        app: mcp-proxy
    spec:
      containers:
        - name: mcp-proxy
          image: ghcr.io/company/mcp-proxy:latest  # Build from mcp-proxy/ directory
          ports:
            - containerPort: 8000
          env:
            - name: WEBUI_SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: open-webui-secrets
                  key: WEBUI_SECRET_KEY
            - name: TENANT_CONFIG_PATH
              value: "/config/tenants.json"
          volumeMounts:
            - name: config
              mountPath: /config
            - name: credentials
              mountPath: /secrets
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
      volumes:
        - name: config
          configMap:
            name: mcp-proxy-config
        - name: credentials
          secret:
            secretName: mcp-tenant-credentials
```

**Step 3: Create Service**

Create file `kubernetes/mcp-proxy-service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: mcp-proxy
  namespace: open-webui
  labels:
    app: mcp-proxy
spec:
  type: ClusterIP
  ports:
    - port: 8000
      targetPort: 8000
      protocol: TCP
      name: http
  selector:
    app: mcp-proxy
```

**Step 4: Apply manifests**

```bash
kubectl apply -f kubernetes/mcp-proxy-configmap.yaml
kubectl apply -f kubernetes/mcp-proxy-deployment.yaml
kubectl apply -f kubernetes/mcp-proxy-service.yaml
```

Expected: All resources created.

**Step 5: Verify deployment**

```bash
kubectl get pods -n open-webui -l app=mcp-proxy
kubectl logs -n open-webui -l app=mcp-proxy --tail=20
```

Expected: 2 pods running, logs show "Cached X tools from Y tenants".

**Step 6: Commit**

```bash
git add kubernetes/mcp-proxy-*.yaml
git commit -m "feat: add MCP Proxy Gateway Kubernetes manifests"
```

---

## Task 5: Deploy Open WebUI with Helm

**Goal:** Install Open WebUI using official Helm chart with production values.

**Step 1: Install Open WebUI**

```bash
helm install open-webui open-webui/open-webui \
  --namespace open-webui \
  --create-namespace \
  -f kubernetes/values-production.yaml \
  --wait \
  --timeout 10m
```

Expected: `STATUS: deployed`

**Step 2: Verify pods**

```bash
kubectl get pods -n open-webui
```

Expected: Shows open-webui pods (3 replicas), redis pod, pipelines pod.

**Step 3: Check database connection**

```bash
kubectl logs -n open-webui -l app.kubernetes.io/name=open-webui --tail=50 | grep -i database
```

Expected: Shows successful PostgreSQL connection.

**Step 4: Verify ingress**

```bash
kubectl get ingress -n open-webui
```

Expected: Shows ingress with external IP/hostname.

**Step 5: Test health endpoint**

```bash
# Port forward for testing
kubectl port-forward -n open-webui svc/open-webui 8080:8080 &

# Test health
curl http://localhost:8080/health
```

Expected: `{"status":"healthy"}`

---

## Task 6: Configure MCP Proxy as Tool Server in Open WebUI

**Goal:** Register MCP Proxy Gateway as an external tool server in Open WebUI.

**Step 1: Access Open WebUI admin panel**

1. Navigate to https://chat.company.com (or port-forward)
2. Login with admin credentials
3. Go to Admin Panel → Settings → External Tools

**Step 2: Add MCP Proxy Gateway**

Configure:
- **Name:** MCP Proxy Gateway
- **URL:** http://mcp-proxy.open-webui.svc.cluster.local:8000
- **Authentication:** Bearer Token
- **Token:** (from open-webui-secrets/MCP_PROXY_API_KEY)
- **Visibility:** Public

**Step 3: Verify connection**

Click "Verify Connection" - should show green checkmark.

**Step 4: Install MCP Proxy Bridge Tool**

1. Go to Admin Panel → Workspace → Tools
2. Add new tool with code from `open-webui-functions/mcp_proxy_bridge.py`
3. Set visibility to "Public"
4. Save

**Step 5: Test tool access**

1. Create a new chat
2. Enable MCP Proxy Bridge tool
3. Ask: "List my available MCP tools"
4. Verify tools are filtered by user's tenant access

---

## Task 7: Set Up Horizontal Pod Autoscaler

**Goal:** Configure autoscaling for Open WebUI based on load.

**Files:**
- Create: `kubernetes/hpa.yaml`

**Step 1: Create HPA manifest**

Create file `kubernetes/hpa.yaml`:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: open-webui-hpa
  namespace: open-webui
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: open-webui
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
```

**Step 2: Apply HPA**

```bash
kubectl apply -f kubernetes/hpa.yaml
```

Expected: `horizontalpodautoscaler.autoscaling/open-webui-hpa created`

**Step 3: Verify HPA**

```bash
kubectl get hpa -n open-webui
```

Expected: Shows HPA with current/target replicas.

**Step 4: Commit**

```bash
git add kubernetes/hpa.yaml
git commit -m "feat: add HPA for Open WebUI autoscaling"
```

---

## Task 8: Verification and Testing

**Goal:** Verify the complete deployment is working correctly.

**Step 1: Run end-to-end test**

```bash
# Check all pods are running
kubectl get pods -n open-webui

# Check services
kubectl get svc -n open-webui

# Check ingress
kubectl get ingress -n open-webui

# Check HPA
kubectl get hpa -n open-webui
```

**Step 2: Test multi-tenant isolation**

1. Login as Google user (google-employee@google.com)
2. List MCP tools - should only see Google tenant tools
3. Try to access Microsoft tool - should get "Access Denied"

4. Login as Microsoft user (ms-employee@microsoft.com)
5. List MCP tools - should only see Microsoft tenant tools
6. Try to access Google tool - should get "Access Denied"

7. Login as admin (admin@company.com)
8. List MCP tools - should see ALL tenant tools

**Step 3: Load test (optional)**

```bash
# Install k6 for load testing
# Run basic load test
k6 run --vus 100 --duration 5m scripts/load-test.js
```

**Step 4: Document deployment**

Update `docs/verification-report-2026-01-08.md` with:
- Kubernetes deployment status
- Pod counts and resource usage
- HPA behavior under load
- Multi-tenant isolation verification

---

## Summary: File Structure

After completing all tasks:

```
kubernetes/
├── namespace.yaml
├── secrets.yaml (DO NOT COMMIT - template only)
├── values-production.yaml
├── mcp-proxy-configmap.yaml
├── mcp-proxy-deployment.yaml
├── mcp-proxy-service.yaml
└── hpa.yaml
```

---

## Future Phases (To Be Planned)

### Phase B: MCP Server Protocol Audit
- Categorize 60-70 MCP integrations by protocol (HTTP vs SSE)
- Prioritize HTTP-based servers for quick wins
- Plan mcpo proxy deployment for SSE servers

### Phase C: Entra ID + API Gateway Integration
- Configure Azure API Management or Kong
- Integrate Microsoft Entra ID for SSO
- Token validation and user identity propagation
- Replace current JWT handling with Entra ID tokens

### Phase D: Code Analysis Pipeline
- Deploy GitHub MCP server for repository access
- Set up filesystem MCP for local file staging
- Integrate code analysis tools (Sourcegraph, etc.)
- Sandbox environment for code execution

---

## Rollback Procedure

If deployment fails:

```bash
# Rollback Helm release
helm rollback open-webui -n open-webui

# Or uninstall completely
helm uninstall open-webui -n open-webui

# Delete MCP Proxy
kubectl delete -f kubernetes/mcp-proxy-deployment.yaml
kubectl delete -f kubernetes/mcp-proxy-service.yaml
kubectl delete -f kubernetes/mcp-proxy-configmap.yaml
```

---

## Monitoring (Post-Deployment)

Recommended monitoring stack:
- **Prometheus** for metrics collection
- **Grafana** for dashboards
- **Azure Monitor** for Azure-native monitoring
- **Loki** for log aggregation

---

*Plan created: January 8, 2026*
