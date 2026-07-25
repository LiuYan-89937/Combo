#!/usr/bin/env bash

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${AGENTFACTORY_PYTHON_BIN:-${PROJECT_ROOT}/.venv/bin/python}"
FRONTEND_DIR="${PROJECT_ROOT}/web_frontend/frontend"

web_fail() {
    echo "ERROR: $*" >&2
    exit 1
}

web_require_project_root() {
    [[ -f "${PROJECT_ROOT}/pyproject.toml" ]] || web_fail "project root is invalid: ${PROJECT_ROOT}"
}

web_require_command() {
    command -v "$1" >/dev/null 2>&1 || web_fail "$2"
}

web_check_env_configuration() {
    return 0
}

web_sync_python_dependencies() {
    [[ -x "${PYTHON_BIN}" ]] || web_fail "Python runtime not found: ${PYTHON_BIN}"
}

web_sync_frontend_dependencies() {
    web_require_command npm "Install Node.js and npm first."
    [[ -d "${FRONTEND_DIR}/node_modules" ]] || (cd "${FRONTEND_DIR}" && npm install --ignore-scripts)
}

web_print_port_status() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1 && lsof -i ":${port}" >/dev/null 2>&1; then
        echo "   ${port}: in use"
    else
        echo "   ${port}: available"
    fi
}
