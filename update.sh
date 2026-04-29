#!/usr/bin/env bash
# update.sh — Pull latest code and redeploy tradebot without data loss
# Usage: ./update.sh
set -euo pipefail

VERSION=$(cat VERSION)
IMAGE="parabyte-ca/tradebot"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[update]${NC} $*"; }
warn() { echo -e "${YELLOW}[update]${NC} $*"; }

info "Pulling latest changes from git..."
git pull --ff-only

info "Rebuilding Docker image ${IMAGE}:${VERSION}..."
docker build \
    --tag "${IMAGE}:${VERSION}" \
    --tag "${IMAGE}:latest" \
    --file Dockerfile \
    .

info "Restarting tradebot container (zero-downtime rolling for other services)..."
docker compose up -d --no-deps tradebot

info "tradebot updated to version ${VERSION}"
echo -e "${YELLOW}  Grafana: http://192.168.2.15:8420${NC}"
