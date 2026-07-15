#!/usr/bin/env bash
# One-command startup for FastAgentFactory Web.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/web_frontend/lib/runtime_env.sh"

web_require_project_root
cd "${PROJECT_ROOT}"

echo "==================================="
echo "FastAgentFactory Web"
echo "==================================="
echo ""

web_check_env_configuration

BACKEND_PID=""
BACKEND_HEALTH_URL="http://127.0.0.1:8000/health"
BACKEND_STARTUP_TIMEOUT_SECONDS="${AGENTFACTORY_WEB_BACKEND_STARTUP_TIMEOUT_SECONDS:-180}"

if [[ ! "${BACKEND_STARTUP_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
    web_fail "AGENTFACTORY_WEB_BACKEND_STARTUP_TIMEOUT_SECONDS must be a positive integer"
fi

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
        echo ""
        echo "Stopping backend service..."
        kill "${BACKEND_PID}" >/dev/null 2>&1 || true
        wait "${BACKEND_PID}" 2>/dev/null || true
    fi
    web_stop_inference_ssh_tunnel
    exit "${exit_code}"
}
trap cleanup EXIT INT TERM

wait_for_backend_ready() {
    local deadline=$((SECONDS + BACKEND_STARTUP_TIMEOUT_SECONDS))
    local backend_exit_code=0

    echo "Waiting for backend readiness at ${BACKEND_HEALTH_URL}..."
    while (( SECONDS < deadline )); do
        if ! kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
            wait "${BACKEND_PID}" || backend_exit_code=$?
            BACKEND_PID=""
            web_fail "Backend exited with status ${backend_exit_code} before becoming ready"
        fi
        if curl --noproxy '*' --fail --silent --max-time 1 "${BACKEND_HEALTH_URL}" >/dev/null 2>&1; then
            echo "Backend is ready"
            return 0
        fi
        sleep 0.5
    done

    web_fail "Backend did not become ready within ${BACKEND_STARTUP_TIMEOUT_SECONDS} seconds"
}

echo ""
web_start_inference_ssh_tunnel
web_sync_python_dependencies
web_sync_frontend_dependencies
web_ensure_builtin_web_search_mcp
web_ensure_runtime_image
web_require_command "curl" "Install curl first."

echo ""
echo "Starting backend web runtime service on port 8000..."
"${PYTHON_BIN}" web_frontend/backend/event_api_server.py &
BACKEND_PID=$!
wait_for_backend_ready
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
