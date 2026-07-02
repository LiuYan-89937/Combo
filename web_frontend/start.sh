#!/usr/bin/env bash
# One-command startup for the FastAgentFactory web frontend.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/runtime_env.sh"

web_require_project_root
cd "${PROJECT_ROOT}"

echo "==================================="
echo "FastAgentFactory Web Frontend"
echo "==================================="
echo ""

web_sync_python_dependencies
web_sync_frontend_dependencies
web_ensure_runtime_image

BACKEND_PID=""

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
        echo ""
        echo "Stopping backend service..."
        kill "${BACKEND_PID}" >/dev/null 2>&1 || true
        wait "${BACKEND_PID}" 2>/dev/null || true
    fi
    exit "${exit_code}"
}
trap cleanup EXIT INT TERM

echo ""
echo "Starting backend web runtime service on port 8000..."
"${PYTHON_BIN}" web_frontend/backend/event_api_server.py &
BACKEND_PID=$!

echo "Waiting for backend to be ready..."
if ! web_wait_for_backend "${BACKEND_PID}" 45 1; then
    echo "Backend failed to start"
    exit 1
fi

echo "Backend runtime service ready: http://localhost:8000"
echo ""
echo "Starting frontend development server on port 3000..."
echo ""
echo "==================================="
echo "Application ready"
echo "Frontend: http://localhost:3000"
echo "Backend:  http://localhost:8000"
echo "==================================="
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

(
    cd "${FRONTEND_DIR}"
    npm run dev
)
