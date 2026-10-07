#!/usr/bin/env bash
# Manual redeploy — run this from your Mac whenever you push a code change.
# Usage: ./deploy.sh

set -euo pipefail

RESOURCE_GROUP="ak-brand-report"
ACR_NAME="geoevaluatoracr"
APP_NAME="geo-evaluator"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Unique tag per deploy so Azure always pulls the new image (avoid :latest cache)
TAG="$(date -u +%Y%m%d-%H%M%S)"
IMAGE="$ACR_NAME.azurecr.io/geo-evaluator:$TAG"

echo "▶ Building image in Azure Container Registry (tag: $TAG)…"
az acr build \
  --registry "$ACR_NAME" \
  --image "geo-evaluator:$TAG" \
  --image "geo-evaluator:latest" \
  "$PROJECT_DIR"

echo "▶ Updating Container App to new image…"
az containerapp update \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --image "$IMAGE" \
  --output table

echo ""
echo "✓ Deployed. App URL:"
az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn \
  --output tsv | awk '{print "  https://" $1}'
