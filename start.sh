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
echo ""
web_sync_python_dependencies
web_sync_frontend_dependencies
web_ensure_builtin_web_search_mcp
web_ensure_runtime_image
web_require_command "curl" "Install curl first."
web_require_command "pgrep" "Install procps first."
web_require_command "tee" "Install coreutils first."

BACKEND_PID=""
FRONTEND_PID=""
BACKEND_HEALTH_URL="http://127.0.0.1:8000/health"
BACKEND_STARTUP_TIMEOUT_SECONDS="${AGENTFACTORY_WEB_BACKEND_STARTUP_TIMEOUT_SECONDS:-180}"
BACKEND_HEALTH_FAILURE_LIMIT="${AGENTFACTORY_WEB_BACKEND_HEALTH_FAILURE_LIMIT:-5}"
SERVICE_HEALTH_INTERVAL_SECONDS="${AGENTFACTORY_WEB_SERVICE_HEALTH_INTERVAL_SECONDS:-2}"
PROCESS_STOP_GRACE_SECONDS="${AGENTFACTORY_WEB_PROCESS_STOP_GRACE_SECONDS:-3}"
RUNTIME_LOG_DIR="${PROJECT_ROOT}/.agentfactory/logs"
BACKEND_LOG_PATH="${RUNTIME_LOG_DIR}/web-backend.log"
FRONTEND_LOG_PATH="${RUNTIME_LOG_DIR}/web-frontend.log"

if [[ ! "${BACKEND_STARTUP_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
    web_fail "AGENTFACTORY_WEB_BACKEND_STARTUP_TIMEOUT_SECONDS must be a positive integer"
fi
if [[ ! "${BACKEND_HEALTH_FAILURE_LIMIT}" =~ ^[1-9][0-9]*$ ]]; then
    web_fail "AGENTFACTORY_WEB_BACKEND_HEALTH_FAILURE_LIMIT must be a positive integer"
fi
if [[ ! "${SERVICE_HEALTH_INTERVAL_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
    web_fail "AGENTFACTORY_WEB_SERVICE_HEALTH_INTERVAL_SECONDS must be a positive integer"
fi
if [[ ! "${PROCESS_STOP_GRACE_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
    web_fail "AGENTFACTORY_WEB_PROCESS_STOP_GRACE_SECONDS must be a positive integer"
fi

stop_process_tree() {
    local pid="$1"
    local child
    local deadline
    while read -r child; do
        [[ -n "${child}" ]] && stop_process_tree "${child}"
    done < <(pgrep -P "${pid}" 2>/dev/null || true)
    kill "${pid}" >/dev/null 2>&1 || true
    deadline=$((SECONDS + PROCESS_STOP_GRACE_SECONDS))
    while (( SECONDS < deadline )); do
        kill -0 "${pid}" >/dev/null 2>&1 || return 0
        sleep 0.2
    done
    kill -KILL "${pid}" >/dev/null 2>&1 || true
}

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
        echo ""
        echo "Stopping frontend service..."
        stop_process_tree "${FRONTEND_PID}"
        wait "${FRONTEND_PID}" 2>/dev/null || true
    fi
    if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
        echo ""
        echo "Stopping backend service..."
        stop_process_tree "${BACKEND_PID}"
        wait "${BACKEND_PID}" 2>/dev/null || true
    fi
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
            web_fail "Backend exited with status ${backend_exit_code} before becoming ready; see ${BACKEND_LOG_PATH}"
        fi
        if curl --noproxy '*' --fail --silent --max-time 1 "${BACKEND_HEALTH_URL}" >/dev/null 2>&1; then
            echo "Backend is ready"
            return 0
        fi
        sleep 0.5
    done

    web_fail "Backend did not become ready within ${BACKEND_STARTUP_TIMEOUT_SECONDS} seconds; see ${BACKEND_LOG_PATH}"
}

supervise_services() {
    local health_failures=0
    local backend_exit_code=0
    local frontend_exit_code=0
    while true; do
        if ! kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
            wait "${BACKEND_PID}" || backend_exit_code=$?
            BACKEND_PID=""
            echo "ERROR: Backend exited with status ${backend_exit_code}; see ${BACKEND_LOG_PATH}" >&2
            return 1
        fi
        if ! kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
            wait "${FRONTEND_PID}" || frontend_exit_code=$?
            FRONTEND_PID=""
            echo "ERROR: Frontend exited with status ${frontend_exit_code}; see ${FRONTEND_LOG_PATH}" >&2
            return 1
        fi
        if curl --noproxy '*' --fail --silent --max-time 1 "${BACKEND_HEALTH_URL}" >/dev/null 2>&1; then
            health_failures=0
        else
            health_failures=$((health_failures + 1))
            if (( health_failures >= BACKEND_HEALTH_FAILURE_LIMIT )); then
                echo "ERROR: Backend health check failed ${health_failures} consecutive times; see ${BACKEND_LOG_PATH}" >&2
                return 1
            fi
        fi
        sleep "${SERVICE_HEALTH_INTERVAL_SECONDS}"
    done
}

echo ""
echo "Starting backend web runtime service on port 8000..."
mkdir -p "${RUNTIME_LOG_DIR}"
"${PYTHON_BIN}" web_frontend/backend/event_api_server.py > >(tee -a "${BACKEND_LOG_PATH}") 2>&1 &
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
echo "Backend log: ${BACKEND_LOG_PATH}"
echo "Frontend log: ${FRONTEND_LOG_PATH}"
echo "Press Ctrl+C to stop all services"
echo ""

(
    cd "${FRONTEND_DIR}"
    exec npm run dev
) > >(tee -a "${FRONTEND_LOG_PATH}") 2>&1 &
FRONTEND_PID=$!

supervise_services
