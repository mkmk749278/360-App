#!/usr/bin/env bash
# deploy_vps.sh — One-click VPS deployment for 360-Crypto-Scalping V2
#
# Deploys the engine via Docker Compose on a fresh or existing VPS.
# Handles everything: prerequisites, Docker, Redis, .env, build, and start.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/mkmk749278/360-v2/main/deploy_vps.sh | sudo bash
#   — OR —
#   git clone https://github.com/mkmk749278/360-v2.git && cd 360-v2
#   chmod +x deploy_vps.sh
#   sudo ./deploy_vps.sh
#
# Flags:
#   --clean    Nuke all existing containers/images before building
#
# Required .env variables:
#   TELEGRAM_BOT_TOKEN           — Telegram bot token
#   TELEGRAM_ACTIVE_CHANNEL_ID   — Active Trading channel ID
#   TELEGRAM_ADMIN_CHAT_ID       — Admin chat ID

set -euo pipefail

# ─── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✅  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️   $*${NC}"; }
err()  { echo -e "${RED}❌  $*${NC}" >&2; }
info() { echo -e "${CYAN}ℹ️   $*${NC}"; }

# ─── Error trap — shows which line caused an unexpected exit ───────────────────
on_error() {
    local exit_code=$?
    local line_no=$1
    err "Script failed at line $line_no (exit code $exit_code)"
    err "Re-run with 'bash -x deploy_vps.sh' for detailed debug output."
}
trap 'on_error $LINENO' ERR
hdr()  { echo -e "\n${BOLD}${CYAN}══════════════════════════════════════════════${NC}"; \
         echo -e "${BOLD}${CYAN}  $*${NC}"; \
         echo -e "${BOLD}${CYAN}══════════════════════════════════════════════${NC}"; }

# ─── Argument parsing ──────────────────────────────────────────────────────────
DO_CLEAN=false
for arg in "$@"; do
    case "$arg" in
        --clean) DO_CLEAN=true ;;
        *) echo "Usage: $0 [--clean]"; exit 1 ;;
    esac
done

# ─── Must run as root (or with sudo) ──────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (sudo bash deploy_vps.sh)"
    exit 1
fi

REAL_USER="${SUDO_USER:-root}"
if [[ "$REAL_USER" == "root" ]]; then
    DEPLOY_HOME="/root"
else
    DEPLOY_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
fi

hdr "🚀  360-Crypto-Scalping V2 — One-Click VPS Deployment"

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 1 — CLEAN (optional)
# ──────────────────────────────────────────────────────────────────────────────
if [ "$DO_CLEAN" = true ]; then
    hdr "PHASE 1 — CLEAN (--clean requested)"

    # Stop old systemd services from previous installs
    for svc in "360scalp-top50" "360-crypto-engine" "crypto-signal-engine" "360-crypto"; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            info "Stopping service: $svc"
            systemctl stop "$svc" 2>/dev/null || true
            systemctl disable "$svc" 2>/dev/null || true
        fi
    done

    # Stop Docker services
    if command -v docker &>/dev/null; then
        if [ -f docker-compose.yml ]; then
            docker compose down 2>/dev/null || true
        fi
        # Remove 360scalp containers
        SCALP_CONTAINERS=$(docker ps -a --format '{{.Names}}' | grep "360scalp" || true)
        if [ -n "$SCALP_CONTAINERS" ]; then
            echo "$SCALP_CONTAINERS" | while read -r c; do
                docker stop "$c" 2>/dev/null || true
                docker rm "$c" 2>/dev/null || true
            done
        fi
        # Remove project images
        IMAGE_IDS=$(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
            | grep -iE "360scalp|360-crypto" | awk '{print $2}' | sort -u || true)
        if [ -n "$IMAGE_IDS" ]; then
            echo "$IMAGE_IDS" | xargs -r docker rmi -f 2>/dev/null || true
        fi
        docker system prune -af 2>/dev/null || true
        docker builder prune -af 2>/dev/null || true
    fi

    # Flush Redis
    if command -v redis-cli &>/dev/null; then
        redis-cli -n 0 FLUSHDB 2>/dev/null || true
    fi

    ok "Cleanup complete"
fi

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2 — INSTALL PREREQUISITES
# ──────────────────────────────────────────────────────────────────────────────
hdr "PHASE 2 — INSTALL PREREQUISITES"

# Wait for any running apt/dpkg processes to finish (e.g. unattended-upgrades)
wait_for_apt_lock() {
    local max_wait=120   # seconds
    local waited=0
    while fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/lib/apt/lists/lock \
          /var/cache/apt/archives/lock >/dev/null 2>&1; do
        if [ "$waited" -eq 0 ]; then
            info "Waiting for other apt/dpkg processes to finish …"
        fi
        if [ "$waited" -ge "$max_wait" ]; then
            err "Timed out after ${max_wait}s waiting for apt lock."
            err "Kill the blocking process or try again later."
            exit 1
        fi
        sleep 5
        waited=$((waited + 5))
    done
    if [ "$waited" -gt 0 ]; then
        ok "apt lock released after ~${waited}s"
    fi
}

# Update packages
info "Updating system packages …"
if command -v apt-get &>/dev/null; then
    wait_for_apt_lock
    # apt-get update often returns non-zero when individual repos are
    # unreachable (stale mirrors, expired GPG keys on a fresh VPS).
    # Allow partial failures — the install step will catch real issues.
    apt-get update -qq || warn "apt-get update had warnings (non-fatal, continuing)"
    wait_for_apt_lock
    if ! apt-get install -y -qq git curl; then
        err "Failed to install prerequisites (git, curl) via apt-get"
        err "Check your internet connection and package sources, then retry."
        exit 1
    fi
elif command -v yum &>/dev/null; then
    if ! yum install -y -q git curl; then
        err "Failed to install prerequisites (git, curl) via yum"
        exit 1
    fi
elif command -v dnf &>/dev/null; then
    if ! dnf install -y -q git curl; then
        err "Failed to install prerequisites (git, curl) via dnf"
        exit 1
    fi
else
    warn "No supported package manager found (apt/yum/dnf) — assuming git and curl are available"
fi
ok "System packages ready"

# Install Docker if not present
if ! command -v docker &>/dev/null; then
    info "Installing Docker …"
    if ! curl -fsSL https://get.docker.com | sh; then
        err "Docker installation failed. Check your internet connection and try again."
        exit 1
    fi
    systemctl enable docker
    systemctl start docker
    ok "Docker installed"
else
    ok "Docker already installed ($(docker --version | head -c 40))"
fi

# Verify Docker Compose
if ! docker compose version &>/dev/null && ! docker-compose version &>/dev/null; then
    err "Docker Compose not available. Please install Docker Compose V2."
    exit 1
fi
ok "Docker Compose available"

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 3 — PROJECT FILES
# ──────────────────────────────────────────────────────────────────────────────
hdr "PHASE 3 — PROJECT FILES"

# If we're not already inside the repo, clone it
if [ ! -f "docker-compose.yml" ] || [ ! -f "src/main.py" ]; then
    PROJECT_DIR="$DEPLOY_HOME/360-v2"
    if [ -d "$PROJECT_DIR" ]; then
        info "Updating existing clone at $PROJECT_DIR …"
        cd "$PROJECT_DIR"
        git pull --ff-only 2>/dev/null || true
    else
        info "Cloning repository into $PROJECT_DIR …"
        git clone https://github.com/mkmk749278/360-v2.git "$PROJECT_DIR"
        cd "$PROJECT_DIR"
    fi
    ok "Project files ready at $PROJECT_DIR"
else
    PROJECT_DIR="$(pwd)"
    ok "Already inside project directory: $PROJECT_DIR"
fi

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 4 — ENVIRONMENT CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────
hdr "PHASE 4 — ENVIRONMENT CONFIGURATION"

if [ ! -f ".env" ]; then
    cp .env.example .env
    info ".env created from .env.example"
    echo ""
    warn "╔══════════════════════════════════════════════════════════════╗"
    warn "║  IMPORTANT: Edit .env with your credentials before restart  ║"
    warn "║                                                             ║"
    warn "║  Required:                                                  ║"
    warn "║    TELEGRAM_BOT_TOKEN=your_bot_token                        ║"
    warn "║    TELEGRAM_ACTIVE_CHANNEL_ID=your_channel_id               ║"
    warn "║    TELEGRAM_ADMIN_CHAT_ID=your_admin_chat_id                ║"
    warn "║                                                             ║"
    warn "║  Run: nano $PROJECT_DIR/.env                                ║"
    warn "╚══════════════════════════════════════════════════════════════╝"
    echo ""
else
    ok ".env already exists"
fi

# Validate bot token is not a placeholder
if grep -q "your_bot_token_here" .env 2>/dev/null; then
    warn "TELEGRAM_BOT_TOKEN is still a placeholder — edit .env before the engine can send signals"
fi

# Ensure TOP50 mode is configured
if ! grep -q "TOP50_FUTURES_ONLY" .env 2>/dev/null; then
    echo "" >> .env
    echo "# Top-50 futures-only mode" >> .env
    echo "TOP50_FUTURES_ONLY=true" >> .env
    echo "TOP50_FUTURES_COUNT=50" >> .env
    info "Added TOP50 configuration to .env"
fi

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 5 — BUILD & START
# ──────────────────────────────────────────────────────────────────────────────
hdr "PHASE 5 — BUILD & START"

mkdir -p logs

info "Building Docker image (this may take 1–2 minutes) …"
if [ "$DO_CLEAN" = true ]; then
    docker compose build --no-cache
else
    docker compose build
fi

info "Starting engine …"
docker compose up -d

# Wait for containers to start
sleep 3

# ──────────────────────────────────────────────────────────────────────────────
# DEPLOYMENT SUMMARY
# ──────────────────────────────────────────────────────────────────────────────
hdr "DEPLOYMENT COMPLETE 🎉"

echo ""
echo -e "${BOLD}Service Status:${NC}"
docker compose ps
echo ""

echo -e "${BOLD}Configuration:${NC}"
echo -e "  Project:  ${CYAN}$PROJECT_DIR${NC}"
echo -e "  Env file: ${CYAN}$PROJECT_DIR/.env${NC}"
echo ""

echo -e "${BOLD}Management Commands:${NC}"
echo -e "  ${GREEN}View logs    :${NC}  docker compose logs -f engine"
echo -e "  ${GREEN}Restart      :${NC}  docker compose restart engine"
echo -e "  ${GREEN}Stop         :${NC}  docker compose down"
echo -e "  ${GREEN}Rebuild      :${NC}  docker compose up -d --build"
echo -e "  ${GREEN}Status       :${NC}  docker compose ps"
echo -e "  ${GREEN}Clean deploy :${NC}  sudo bash deploy_vps.sh --clean"
echo ""

ok "Engine is running! Check logs: docker compose logs -f engine"
