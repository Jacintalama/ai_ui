#!/bin/bash
# kubernetes/deploy.sh
# =============================================================================
# Unified MCP Proxy - Kubernetes Deployment Script (Bash)
# =============================================================================
# Deploys the complete MCP infrastructure to Kubernetes
#
# Usage:
#   ./deploy.sh              # Full deployment
#   ./deploy.sh --skip-build # Skip Docker build
#   ./deploy.sh --teardown   # Remove all resources
#
# Access after deployment:
#   http://localhost:30800    # NodePort
#   http://localhost:8080     # Port-forward
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Flags
SKIP_BUILD=false
TEARDOWN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --teardown)
            TEARDOWN=true
            shift
            ;;
        --help|-h)
            echo "Usage: ./deploy.sh [options]"
            echo ""
            echo "Options:"
            echo "  --skip-build    Skip building Docker images"
            echo "  --teardown      Remove all deployed resources"
            echo "  --help, -h      Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Header
echo ""
echo -e "${MAGENTA}============================================================${NC}"
echo -e "${MAGENTA}  MCP Proxy Gateway - Kubernetes Deployment${NC}"
echo -e "${MAGENTA}  Unified URL: http://localhost:30800${NC}"
echo -e "${MAGENTA}============================================================${NC}"
echo ""

# =============================================================================
# TEARDOWN MODE
# =============================================================================
if [ "$TEARDOWN" = true ]; then
    echo -e "${YELLOW}Tearing down MCP infrastructure...${NC}"

    kubectl delete -f "$SCRIPT_DIR/mcpo-stdio-deployment.yaml" 2>/dev/null || true
    kubectl delete -f "$SCRIPT_DIR/mcpo-sse-deployment.yaml" 2>/dev/null || true
    kubectl delete -f "$SCRIPT_DIR/mcp-github-deployment.yaml" 2>/dev/null || true
    kubectl delete -f "$SCRIPT_DIR/mcp-filesystem-deployment.yaml" 2>/dev/null || true
    kubectl delete -f "$SCRIPT_DIR/mcp-proxy-deployment.yaml" 2>/dev/null || true
    kubectl delete -f "$SCRIPT_DIR/mcp-secrets.yaml" 2>/dev/null || true
    kubectl delete -f "$SCRIPT_DIR/namespace.yaml" 2>/dev/null || true

    echo -e "${GREEN}Teardown complete!${NC}"
    exit 0
fi

# =============================================================================
# PREREQUISITES CHECK
# =============================================================================
echo -e "${CYAN}[1/8] Checking prerequisites...${NC}"

# Check kubectl
if command -v kubectl &> /dev/null; then
    echo -e "${GREEN}  kubectl: OK${NC}"
else
    echo -e "${RED}  kubectl: NOT FOUND - Please install kubectl${NC}"
    exit 1
fi

# Check Docker
if docker version &> /dev/null; then
    echo -e "${GREEN}  docker: OK${NC}"
else
    echo -e "${RED}  docker: NOT RUNNING - Please start Docker${NC}"
    exit 1
fi

# Check Kubernetes cluster
if kubectl cluster-info &> /dev/null; then
    echo -e "${GREEN}  kubernetes cluster: OK${NC}"
else
    echo -e "${RED}  kubernetes cluster: NOT AVAILABLE${NC}"
    echo -e "${RED}  Please enable Kubernetes in Docker Desktop or start minikube${NC}"
    exit 1
fi

# =============================================================================
# BUILD DOCKER IMAGE
# =============================================================================
if [ "$SKIP_BUILD" = false ]; then
    echo -e "${CYAN}[2/8] Building MCP Proxy Docker image...${NC}"

    pushd "$PROJECT_ROOT/mcp-proxy" > /dev/null
    docker build -t mcp-proxy:local .
    popd > /dev/null

    echo -e "${GREEN}  mcp-proxy:local built successfully${NC}"
else
    echo -e "${YELLOW}[2/8] Skipping Docker build (--skip-build flag)${NC}"
fi

# =============================================================================
# CREATE NAMESPACE
# =============================================================================
echo -e "${CYAN}[3/8] Creating namespace...${NC}"

kubectl apply -f "$SCRIPT_DIR/namespace.yaml"
echo -e "${GREEN}  namespace/open-webui created${NC}"

# =============================================================================
# CREATE SECRETS
# =============================================================================
echo -e "${CYAN}[4/8] Creating secrets...${NC}"

# Check if secrets file has been customized
if grep -q "REPLACE_WITH" "$SCRIPT_DIR/mcp-secrets.yaml"; then
    echo -e "${YELLOW}  WARNING: mcp-secrets.yaml contains placeholder values${NC}"
    echo -e "${YELLOW}  Edit kubernetes/mcp-secrets.yaml with your actual API keys${NC}"
fi

kubectl apply -f "$SCRIPT_DIR/mcp-secrets.yaml"
echo -e "${GREEN}  secrets/mcp-secrets created${NC}"

# =============================================================================
# DEPLOY MCP PROXY
# =============================================================================
echo -e "${CYAN}[5/8] Deploying MCP Proxy Gateway...${NC}"

kubectl apply -f "$SCRIPT_DIR/mcp-proxy-deployment.yaml"
echo -e "${GREEN}  deployment/mcp-proxy created${NC}"
echo -e "${GREEN}  service/mcp-proxy created${NC}"
echo -e "${GREEN}  service/mcp-proxy-external (NodePort 30800) created${NC}"

# =============================================================================
# DEPLOY LOCAL MCP SERVERS
# =============================================================================
echo -e "${CYAN}[6/8] Deploying local MCP servers...${NC}"

kubectl apply -f "$SCRIPT_DIR/mcp-filesystem-deployment.yaml"
echo -e "${GREEN}  deployment/mcp-filesystem created${NC}"

kubectl apply -f "$SCRIPT_DIR/mcp-github-deployment.yaml"
echo -e "${GREEN}  deployment/mcp-github created${NC}"

# =============================================================================
# DEPLOY MCPO PROXIES (TIER 2 & 3)
# =============================================================================
echo -e "${CYAN}[7/8] Deploying mcpo proxies (Tier 2 SSE & Tier 3 stdio)...${NC}"

kubectl apply -f "$SCRIPT_DIR/mcpo-sse-deployment.yaml"
echo -e "${GREEN}  deployment/mcpo-sse (Atlassian, Asana) created${NC}"

kubectl apply -f "$SCRIPT_DIR/mcpo-stdio-deployment.yaml"
echo -e "${GREEN}  deployment/mcpo-stdio (SonarQube, Sentry) created${NC}"

# =============================================================================
# WAIT FOR PODS
# =============================================================================
echo -e "${CYAN}[8/8] Waiting for pods to be ready...${NC}"

TIMEOUT=120
ELAPSED=0
INTERVAL=5

while [ $ELAPSED -lt $TIMEOUT ]; do
    READY=$(kubectl get pods -n open-webui -o jsonpath='{.items[*].status.phase}' 2>/dev/null | tr ' ' '\n' | grep -c "Running" || echo "0")
    TOTAL=$(kubectl get pods -n open-webui -o jsonpath='{.items[*].status.phase}' 2>/dev/null | tr ' ' '\n' | wc -l | tr -d ' ')

    echo -n "  Pods ready: $READY/$TOTAL"

    if [ "$READY" -eq "$TOTAL" ] && [ "$TOTAL" -gt 0 ]; then
        echo ""
        echo -e "${GREEN}  All pods are running!${NC}"
        break
    fi

    echo " (waiting...)"
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo -e "${YELLOW}  Timeout waiting for pods. Check status with: kubectl get pods -n open-webui${NC}"
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  DEPLOYMENT COMPLETE!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""

echo -e "${CYAN}Pod Status:${NC}"
kubectl get pods -n open-webui -o wide

echo ""
echo -e "${CYAN}Services:${NC}"
kubectl get svc -n open-webui

echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN}  ACCESS THE UNIFIED MCP PROXY${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""
echo -e "${YELLOW}  Option 1 - NodePort (direct):${NC}"
echo "    http://localhost:30800"
echo ""
echo -e "${YELLOW}  Option 2 - Port Forward:${NC}"
echo "    kubectl port-forward svc/mcp-proxy 8080:8000 -n open-webui"
echo "    http://localhost:8080"
echo ""
echo -e "${YELLOW}  Test Commands:${NC}"
echo "    curl http://localhost:30800/health"
echo "    curl http://localhost:30800/servers"
echo "    curl http://localhost:30800/github"
echo ""
echo -e "${YELLOW}  URL Structure (Lukas's Requirement):${NC}"
echo "    GET  /servers                    - List all servers"
echo "    GET  /github                     - List GitHub tools"
echo "    POST /github/search_repositories - Execute tool"
echo "    POST /filesystem/read_file       - Read a file"
echo ""
echo -e "${CYAN}============================================================${NC}"
