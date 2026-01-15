# Kubernetes Deployment Guide

This directory contains all Kubernetes manifests for deploying Open WebUI with MCP Proxy Gateway on Azure Kubernetes Service (AKS).

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Azure Kubernetes Service (AKS)               │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ Open WebUI  │  │ MCP Proxy   │  │   Redis     │              │
│  │ (3-10 pods) │  │ (2-5 pods)  │  │  (1 pod)    │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│         │                │                │                      │
│         └────────────────┼────────────────┘                      │
│                          │                                       │
└──────────────────────────│───────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│           Azure Database for PostgreSQL (Flexible Server)       │
│  • pgvector extension                                            │
│  • Row-level security by workspace_id                            │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Azure CLI installed and authenticated (`az login`)
- kubectl configured for your AKS cluster
- Helm 3.x installed
- Azure Database for PostgreSQL (Flexible Server) created

## Files Overview

| File | Purpose |
|------|---------|
| `namespace.yaml` | Creates the `open-webui` namespace |
| `secrets-template.yaml` | Template for secrets (copy to secrets.yaml) |
| `values-production.yaml` | Helm values for Open WebUI |
| `mcp-proxy-configmap.yaml` | Tenant configuration for MCP Proxy |
| `mcp-proxy-deployment.yaml` | MCP Proxy Gateway deployment |
| `mcp-proxy-service.yaml` | MCP Proxy service |
| `hpa.yaml` | Horizontal Pod Autoscalers |

## Deployment Steps

### Step 1: Create Azure Database for PostgreSQL

```bash
# Set variables
RESOURCE_GROUP="openwebui-prod-rg"
LOCATION="eastus"
PG_SERVER_NAME="openwebui-pg-prod"
PG_ADMIN_USER="openwebui_admin"
PG_ADMIN_PASSWORD="$(openssl rand -base64 24)"

# Create PostgreSQL Flexible Server
az postgres flexible-server create \
  --resource-group $RESOURCE_GROUP \
  --name $PG_SERVER_NAME \
  --location $LOCATION \
  --admin-user $PG_ADMIN_USER \
  --admin-password $PG_ADMIN_PASSWORD \
  --sku-name Standard_D4ds_v5 \
  --storage-size 128 \
  --version 16 \
  --high-availability ZoneRedundant

# Enable pgvector
az postgres flexible-server parameter set \
  --resource-group $RESOURCE_GROUP \
  --server-name $PG_SERVER_NAME \
  --name azure.extensions \
  --value vector

# Create database
az postgres flexible-server db create \
  --resource-group $RESOURCE_GROUP \
  --server-name $PG_SERVER_NAME \
  --database-name openwebui
```

### Step 2: Create Namespace

```bash
kubectl apply -f namespace.yaml
```

### Step 3: Create Secrets

```bash
# Copy template and edit with real values
cp secrets-template.yaml secrets.yaml

# Edit secrets.yaml with your values:
# - DATABASE_URL: Your PostgreSQL connection string
# - WEBUI_SECRET_KEY: openssl rand -hex 32
# - MCP_PROXY_API_KEY: openssl rand -hex 16
# - REDIS_PASSWORD: openssl rand -hex 16
# - Tenant API keys

# Apply secrets
kubectl apply -f secrets.yaml
```

### Step 4: Add Helm Repository

```bash
helm repo add open-webui https://helm.openwebui.com
helm repo update
```

### Step 5: Deploy Open WebUI

```bash
helm install open-webui open-webui/open-webui \
  --namespace open-webui \
  -f values-production.yaml \
  --wait \
  --timeout 10m
```

### Step 6: Deploy MCP Proxy Gateway

```bash
kubectl apply -f mcp-proxy-configmap.yaml
kubectl apply -f mcp-proxy-deployment.yaml
kubectl apply -f mcp-proxy-service.yaml
```

### Step 7: Apply HPA

```bash
kubectl apply -f hpa.yaml
```

### Step 8: Verify Deployment

```bash
# Check all pods
kubectl get pods -n open-webui

# Check services
kubectl get svc -n open-webui

# Check HPA
kubectl get hpa -n open-webui

# Check ingress
kubectl get ingress -n open-webui
```

## Configuration

### Update Domain Name

Edit `values-production.yaml` and replace `chat.company.com` with your actual domain.

### Update Tenant Configuration

Edit `mcp-proxy-configmap.yaml` to add/modify tenants:

```yaml
"your-tenant": {
  "tenant_id": "your-tenant",
  "display_name": "Your Tenant Name",
  "mcp_endpoint": "http://your-mcp-server:8001",
  "enabled": true,
  "allowed_users": ["*@yourdomain.com"],
  "allowed_groups": ["your-group"]
}
```

## Scaling

The HPA automatically scales:
- **Open WebUI:** 3-10 replicas (CPU 70%, Memory 80%)
- **MCP Proxy:** 2-5 replicas (CPU 70%)

Manual scaling:
```bash
kubectl scale deployment open-webui --replicas=5 -n open-webui
```

## Troubleshooting

### Check logs
```bash
kubectl logs -n open-webui -l app.kubernetes.io/name=open-webui --tail=100
kubectl logs -n open-webui -l app=mcp-proxy --tail=100
```

### Check database connection
```bash
kubectl exec -it -n open-webui deploy/open-webui -- env | grep DATABASE
```

### Restart deployment
```bash
kubectl rollout restart deployment/open-webui -n open-webui
kubectl rollout restart deployment/mcp-proxy -n open-webui
```

## Rollback

```bash
# Rollback Helm release
helm rollback open-webui -n open-webui

# Or uninstall completely
helm uninstall open-webui -n open-webui
kubectl delete -f mcp-proxy-deployment.yaml
kubectl delete -f mcp-proxy-service.yaml
kubectl delete -f mcp-proxy-configmap.yaml
kubectl delete -f hpa.yaml
```

## Security Notes

- Never commit `secrets.yaml` to git (only commit `secrets-template.yaml`)
- Use Azure Key Vault for production secrets management
- Enable network policies for pod-to-pod communication restrictions
- Configure Entra ID for SSO (Phase C)
