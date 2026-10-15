#!/usr/bin/env bash
# ==============================================================================
# Checkout Radar — Stop Script (Linux & macOS)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if command -v python3 >/dev/null 2>&1; then
    exec python3 "${SCRIPT_DIR}/scripts/launcher.py" --down
fi

echo "[INFO] Stopping Checkout Radar containers..."
if docker compose version >/dev/null 2>&1; then
    docker compose down
elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose down
fi
echo "[SUCCESS] Checkout Radar services stopped."
