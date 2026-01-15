#!/bin/bash
# deploy-local.sh - Local Kubernetes testing with Minikube or Kind

set -e

echo "========================================"
echo "  Open WebUI Local Kubernetes Testing"
echo "========================================"

# Check if minikube or kind is available
if command -v minikube &> /dev/null; then
    K8S_TOOL="minikube"
    echo "Using Minikube"
elif command -v kind &> /dev/null; then
    K8S_TOOL="kind"
    echo "Using Kind"
else
    echo "ERROR: Neither minikube nor kind found!"
    echo ""
    echo "Install one of these:"
    echo "  Minikube: https://minikube.sigs.k8s.io/docs/start/"
    echo "  Kind: https://kind.sigs.k8s.io/docs/user/quick-start/"
    exit 1
fi

# Start cluster if not running
if [ "$K8S_TOOL" = "minikube" ]; then
    if ! minikube status | grep -q "Running"; then
        echo "Starting Minikube..."
        minikube start --memory=4096 --cpus=2
    fi
elif [ "$K8S_TOOL" = "kind" ]; then
    if ! kind get clusters | grep -q "open-webui"; then
        echo "Creating Kind cluster..."
        kind create cluster --name open-webui
    fi
fi

# Add Helm repo
echo "Adding Helm repository..."
helm repo add open-webui https://helm.openwebui.com 2>/dev/null || true
helm repo update

# Create namespace
echo "Creating namespace..."
kubectl apply -f namespace.yaml

# Deploy Open WebUI with local values
echo "Deploying Open WebUI..."
helm upgrade --install open-webui open-webui/open-webui \
    --namespace open-webui \
    -f values-local.yaml \
    --wait \
    --timeout 10m

# Deploy MCP Proxy (using local config)
echo "Deploying MCP Proxy..."
kubectl apply -f mcp-proxy-configmap.yaml
kubectl apply -f mcp-proxy-deployment.yaml
kubectl apply -f mcp-proxy-service.yaml

# Wait for pods
echo "Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=open-webui -n open-webui --timeout=300s

# Get access URL
echo ""
echo "========================================"
echo "  Deployment Complete!"
echo "========================================"
echo ""

if [ "$K8S_TOOL" = "minikube" ]; then
    echo "Access Open WebUI:"
    echo "  minikube service open-webui -n open-webui"
    echo ""
    echo "Or port-forward:"
    echo "  kubectl port-forward svc/open-webui 8080:8080 -n open-webui"
else
    echo "Access Open WebUI with port-forward:"
    echo "  kubectl port-forward svc/open-webui 8080:8080 -n open-webui"
fi

echo ""
echo "Then open: http://localhost:8080"
echo ""
echo "Check status:"
echo "  kubectl get pods -n open-webui"
