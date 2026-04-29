#!/usr/bin/env bash
# setup.sh — First-time deployment of tradebot on TrueNAS SCALE
# Usage: ./setup.sh
set -euo pipefail

VERSION="0.1.0"
IMAGE="parabyte-ca/tradebot"
DATA_DIR="/mnt/shared_vol/tradebot/data"
MODELS_DIR="${DATA_DIR}/models"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[setup]${NC} $*"; }
warn()    { echo -e "${YELLOW}[setup]${NC} $*"; }
error()   { echo -e "${RED}[setup] ERROR:${NC} $*" >&2; exit 1; }

# 1. Check Docker
info "Checking Docker availability..."
command -v docker >/dev/null 2>&1 || error "Docker not found. Install Docker before running setup."
docker info >/dev/null 2>&1 || error "Docker daemon is not running. Start it and retry."
info "Docker OK"

# 2. Validate .env
info "Validating .env..."
[[ -f .env ]] || error ".env file not found. Copy .env.example to .env and fill in all required keys."

required_keys=(
    ALPACA_API_KEY
    ALPACA_SECRET_KEY
    FINNHUB_API_KEY
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
)

missing=()
for key in "${required_keys[@]}"; do
    val=$(grep -E "^${key}=" .env 2>/dev/null | cut -d= -f2- | tr -d ' ')
    if [[ -z "$val" ]]; then
        missing+=("$key")
    fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
    error "Missing required .env keys: ${missing[*]}\nEdit .env and re-run setup."
fi
info ".env validation passed"

# 3. Create data directories
info "Creating data directories..."
mkdir -p "${DATA_DIR}" "${MODELS_DIR}"
info "Directories: ${DATA_DIR}, ${MODELS_DIR}"

# 4. Build Docker image
info "Building Docker image ${IMAGE}:${VERSION}..."
docker build \
    --tag "${IMAGE}:${VERSION}" \
    --tag "${IMAGE}:latest" \
    --file Dockerfile \
    .
info "Image built: ${IMAGE}:${VERSION} + :latest"

# 5. Start stack
info "Starting Docker Compose stack..."
docker compose up -d

# 6. Health check
info "Waiting 15s for services to start..."
sleep 15

if docker compose ps | grep -q "unhealthy\|Exit"; then
    warn "One or more services may be unhealthy. Check logs with: docker compose logs"
fi

# 7. Print access URLs
echo ""
echo -e "${GREEN}============================= tradebot is up =============================${NC}"
echo ""
echo -e "  Grafana dashboard : ${YELLOW}http://192.168.2.15:8420${NC}  (or via Tailscale IP)"
echo -e "  Prometheus        : ${YELLOW}http://192.168.2.15:9090${NC}"
echo -e "  Bot metrics       : ${YELLOW}http://192.168.2.15:8421/metrics${NC}"
echo ""
echo -e "  Default Grafana login: admin / changeme  (set GRAFANA_PASSWORD in .env)"
echo ""
echo -e "${RED}  REMINDER: This is PAPER TRADING ONLY.${NC}"
echo -e "${RED}  Do NOT switch IBKR_PORT to 7496 until 90-day paper validation passes.${NC}"
echo ""
