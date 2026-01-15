# kubernetes/deploy.ps1
# =============================================================================
# Unified MCP Proxy - Kubernetes Deployment Script (Windows PowerShell)
# =============================================================================
# Deploys the complete MCP infrastructure to Kubernetes
#
# Usage:
#   .\deploy.ps1              # Full deployment
#   .\deploy.ps1 -SkipBuild   # Skip Docker build
#   .\deploy.ps1 -Teardown    # Remove all resources
#
# Access after deployment:
#   http://localhost:30800    # NodePort
#   http://localhost:8080     # Port-forward (run: kubectl port-forward svc/mcp-proxy 8080:8000 -n open-webui)
# =============================================================================

param(
    [switch]$SkipBuild,
    [switch]$Teardown,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# Colors for output
function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Info { Write-Host $args -ForegroundColor Cyan }
function Write-Warning { Write-Host $args -ForegroundColor Yellow }
function Write-Error { Write-Host $args -ForegroundColor Red }

# Header
Write-Host ""
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "  MCP Proxy Gateway - Kubernetes Deployment" -ForegroundColor Magenta
Write-Host "  Unified URL: http://localhost:30800" -ForegroundColor Magenta
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host ""

if ($Help) {
    Write-Host "Usage: .\deploy.ps1 [options]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -SkipBuild    Skip building Docker images"
    Write-Host "  -Teardown     Remove all deployed resources"
    Write-Host "  -Help         Show this help message"
    Write-Host ""
    exit 0
}

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# =============================================================================
# TEARDOWN MODE
# =============================================================================
if ($Teardown) {
    Write-Warning "Tearing down MCP infrastructure..."

    kubectl delete -f "$ScriptDir\mcpo-stdio-deployment.yaml" 2>$null
    kubectl delete -f "$ScriptDir\mcpo-sse-deployment.yaml" 2>$null
    kubectl delete -f "$ScriptDir\mcp-github-deployment.yaml" 2>$null
    kubectl delete -f "$ScriptDir\mcp-filesystem-deployment.yaml" 2>$null
    kubectl delete -f "$ScriptDir\mcp-proxy-deployment.yaml" 2>$null
    kubectl delete -f "$ScriptDir\mcp-secrets.yaml" 2>$null
    kubectl delete -f "$ScriptDir\namespace.yaml" 2>$null

    Write-Success "Teardown complete!"
    exit 0
}

# =============================================================================
# PREREQUISITES CHECK
# =============================================================================
Write-Info "[1/8] Checking prerequisites..."

# Check kubectl
try {
    $null = kubectl version --client 2>$null
    Write-Success "  kubectl: OK"
} catch {
    Write-Error "  kubectl: NOT FOUND - Please install kubectl"
    exit 1
}

# Check Docker
try {
    $null = docker version 2>$null
    Write-Success "  docker: OK"
} catch {
    Write-Error "  docker: NOT RUNNING - Please start Docker Desktop"
    exit 1
}

# Check Kubernetes cluster
try {
    $null = kubectl cluster-info 2>$null
    Write-Success "  kubernetes cluster: OK"
} catch {
    Write-Error "  kubernetes cluster: NOT AVAILABLE"
    Write-Error "  Please enable Kubernetes in Docker Desktop settings"
    exit 1
}

# =============================================================================
# BUILD DOCKER IMAGE
# =============================================================================
if (-not $SkipBuild) {
    Write-Info "[2/8] Building MCP Proxy Docker image..."

    Push-Location "$ProjectRoot\mcp-proxy"
    try {
        docker build -t mcp-proxy:local .
        if ($LASTEXITCODE -ne 0) { throw "Docker build failed" }
        Write-Success "  mcp-proxy:local built successfully"
    } finally {
        Pop-Location
    }
} else {
    Write-Warning "[2/8] Skipping Docker build (-SkipBuild flag)"
}

# =============================================================================
# CREATE NAMESPACE
# =============================================================================
Write-Info "[3/8] Creating namespace..."

kubectl apply -f "$ScriptDir\namespace.yaml"
Write-Success "  namespace/open-webui created"

# =============================================================================
# CREATE SECRETS
# =============================================================================
Write-Info "[4/8] Creating secrets..."

# Check if secrets file has been customized
$secretsContent = Get-Content "$ScriptDir\mcp-secrets.yaml" -Raw
if ($secretsContent -match "REPLACE_WITH") {
    Write-Warning "  WARNING: mcp-secrets.yaml contains placeholder values"
    Write-Warning "  Edit kubernetes/mcp-secrets.yaml with your actual API keys"
}

kubectl apply -f "$ScriptDir\mcp-secrets.yaml"
Write-Success "  secrets/mcp-secrets created"

# =============================================================================
# DEPLOY MCP PROXY
# =============================================================================
Write-Info "[5/8] Deploying MCP Proxy Gateway..."

kubectl apply -f "$ScriptDir\mcp-proxy-deployment.yaml"
Write-Success "  deployment/mcp-proxy created"
Write-Success "  service/mcp-proxy created"
Write-Success "  service/mcp-proxy-external (NodePort 30800) created"

# =============================================================================
# DEPLOY LOCAL MCP SERVERS
# =============================================================================
Write-Info "[6/8] Deploying local MCP servers..."

kubectl apply -f "$ScriptDir\mcp-filesystem-deployment.yaml"
Write-Success "  deployment/mcp-filesystem created"

kubectl apply -f "$ScriptDir\mcp-github-deployment.yaml"
Write-Success "  deployment/mcp-github created"

# =============================================================================
# DEPLOY MCPO PROXIES (TIER 2 & 3)
# =============================================================================
Write-Info "[7/8] Deploying mcpo proxies (Tier 2 SSE & Tier 3 stdio)..."

kubectl apply -f "$ScriptDir\mcpo-sse-deployment.yaml"
Write-Success "  deployment/mcpo-sse (Atlassian, Asana) created"

kubectl apply -f "$ScriptDir\mcpo-stdio-deployment.yaml"
Write-Success "  deployment/mcpo-stdio (SonarQube, Sentry) created"

# =============================================================================
# WAIT FOR PODS
# =============================================================================
Write-Info "[8/8] Waiting for pods to be ready..."

$timeout = 120
$elapsed = 0
$interval = 5

while ($elapsed -lt $timeout) {
    $pods = kubectl get pods -n open-webui -o jsonpath='{.items[*].status.phase}' 2>$null
    $readyCount = ($pods -split ' ' | Where-Object { $_ -eq 'Running' }).Count
    $totalCount = ($pods -split ' ').Count

    Write-Host "  Pods ready: $readyCount/$totalCount" -NoNewline

    if ($readyCount -eq $totalCount -and $totalCount -gt 0) {
        Write-Host ""
        Write-Success "  All pods are running!"
        break
    }

    Write-Host " (waiting...)"
    Start-Sleep -Seconds $interval
    $elapsed += $interval
}

if ($elapsed -ge $timeout) {
    Write-Warning "  Timeout waiting for pods. Check status with: kubectl get pods -n open-webui"
}

# =============================================================================
# SUMMARY
# =============================================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

Write-Info "Pod Status:"
kubectl get pods -n open-webui -o wide

Write-Host ""
Write-Info "Services:"
kubectl get svc -n open-webui

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  ACCESS THE UNIFIED MCP PROXY" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Option 1 - NodePort (direct):" -ForegroundColor Yellow
Write-Host "    http://localhost:30800"
Write-Host ""
Write-Host "  Option 2 - Port Forward:" -ForegroundColor Yellow
Write-Host "    kubectl port-forward svc/mcp-proxy 8080:8000 -n open-webui"
Write-Host "    http://localhost:8080"
Write-Host ""
Write-Host "  Test Commands:" -ForegroundColor Yellow
Write-Host "    curl http://localhost:30800/health"
Write-Host "    curl http://localhost:30800/servers"
Write-Host "    curl http://localhost:30800/github"
Write-Host ""
Write-Host "  URL Structure (Lukas's Requirement):" -ForegroundColor Yellow
Write-Host "    GET  /servers                  - List all servers"
Write-Host "    GET  /github                   - List GitHub tools"
Write-Host "    POST /github/search_repositories - Execute tool"
Write-Host "    POST /filesystem/read_file     - Read a file"
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
