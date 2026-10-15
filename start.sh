#!/usr/bin/env bash
# ==============================================================================
# Checkout Radar — One-Command Startup Script (Linux & macOS)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# If Python 3 is available, delegate to the cross-platform launcher
if command -v python3 >/dev/null 2>&1; then
    exec python3 "${SCRIPT_DIR}/scripts/launcher.py" "$@"
fi

# Fallback: Pure Bash Startup
echo "[INFO] Starting Checkout Radar via bash fallback..."

# 1. Pre-flight Docker checks
if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] Docker is not installed or not in PATH."
    echo "Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "[ERROR] Docker daemon is not running."
    echo "Please start Docker Desktop (macOS) or run 'sudo systemctl start docker' (Linux)."
    exit 1
fi

# 2. Prepare .env if absent
if [ ! -f .env ]; then
    echo "[INFO] No .env found. Cloning default from .env.example (Mock Mode enabled)..."
    cp .env.example .env
fi

# 3. Docker Compose orchestration
COMPOSE_CMD="docker compose"
if ! docker compose version >/dev/null 2>&1; then
    if command -v docker-compose >/dev/null 2>&1; then
        COMPOSE_CMD="docker-compose"
    else
        echo "[ERROR] Neither 'docker compose' nor 'docker-compose' found."
        exit 1
    fi
fi

echo "[INFO] Building and launching containers in background..."
${COMPOSE_CMD} up --build -d

# 4. Resolve API port
API_MAP=$(${COMPOSE_CMD} port api 8000 2>/dev/null || echo "127.0.0.1:8000")
API_HOST=$(echo "${API_MAP}" | cut -d':' -f1)
API_PORT=$(echo "${API_MAP}" | cut -d':' -f2)
if [ -z "${API_HOST}" ] || [ "${API_HOST}" = "0.0.0.0" ]; then
    API_HOST="127.0.0.1"
fi

# 5. Wait for health endpoint
HEALTH_URL="http://${API_HOST}:${API_PORT}/health"
echo "[INFO] Waiting for Checkout Radar API to become ready at ${HEALTH_URL}..."

ATTEMPTS=0
MAX_ATTEMPTS=60
READY=0

while [ ${ATTEMPTS} -lt ${MAX_ATTEMPTS} ]; do
    if command -v curl >/dev/null 2>&1; then
        if curl -s -f -m 2 "${HEALTH_URL}" >/dev/null 2>&1; then
            READY=1
            break
        fi
    elif command -v wget >/dev/null 2>&1; then
        if wget -q -O - "${HEALTH_URL}" >/dev/null 2>&1; then
            READY=1
            break
        fi
    fi
    sleep 1.5
    ATTEMPTS=$((ATTEMPTS + 1))
done

if [ ${READY} -ne 1 ]; then
    echo "[ERROR] API did not become healthy within timeout. Container logs:"
    ${COMPOSE_CMD} logs --tail 30
    exit 1
fi

DASHBOARD_URL="http://${API_HOST}:${API_PORT}"
echo ""
echo "======================================================================"
echo " 📡 CHECKOUT RADAR IS READY"
echo "======================================================================"
echo "  • Auditor Dashboard:       ${DASHBOARD_URL}"
echo "  • Demo Merchant Harness:   http://127.0.0.1:8001"
echo "  • Interactive API Docs:    ${DASHBOARD_URL}/docs"
echo "======================================================================"
echo "  To stop services: run './stop.sh' or 'docker compose down'"
echo ""

# 6. Open browser if GUI available
if [ "${1:-}" != "--no-browser" ]; then
    if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ] || [ "$(uname)" = "Darwin" ]; then
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open "${DASHBOARD_URL}" >/dev/null 2>&1 || true
        elif command -v open >/dev/null 2>&1; then
            open "${DASHBOARD_URL}" >/dev/null 2>&1 || true
        fi
    fi
fi
