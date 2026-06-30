#!/usr/bin/env bash
# Shared environment helpers for FastAgentFactory web frontend scripts.

WEB_FRONTEND_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_FRONTEND_DIR="$(cd "${WEB_FRONTEND_LIB_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${WEB_FRONTEND_DIR}/.." && pwd)"
FRONTEND_DIR="${WEB_FRONTEND_DIR}/frontend"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
RUNTIME_IMAGE="${AGENTFACTORY_RUNTIME_IMAGE:-agentfactory-runtime-python:3.12}"
RUNTIME_DOCKERFILE="${AGENTFACTORY_RUNTIME_DOCKERFILE:-${PROJECT_ROOT}/docker/agent-runtime/Dockerfile}"
BACKEND_HEALTH_URL="${AGENTFACTORY_WEB_BACKEND_HEALTH_URL:-http://localhost:8000/health}"

web_fail() {
    echo "ERROR: $*" >&2
    exit 1
}

web_require_project_root() {
    [[ -f "${PROJECT_ROOT}/pyproject.toml" ]] || web_fail "pyproject.toml not found at ${PROJECT_ROOT}"
}

web_require_command() {
    local command_name="$1"
    local install_hint="$2"
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        web_fail "${command_name} not found. ${install_hint}"
    fi
}

web_sync_python_dependencies() {
    web_require_command "uv" "Install uv first: https://docs.astral.sh/uv/"
    echo "Checking Python backend dependencies with uv..."
    (
        cd "${PROJECT_ROOT}"
        uv sync --extra web
    )
    [[ -x "${PYTHON_BIN}" ]] || web_fail "Python virtualenv was not created at ${PYTHON_BIN}"
    "${PYTHON_BIN}" -c "import fastapi, uvicorn, pydantic" \
        || web_fail "Python web dependencies are not importable from ${PYTHON_BIN}"
}

web_sync_frontend_dependencies() {
    web_require_command "node" "Install Node.js first."
    web_require_command "npm" "Install npm first."
    [[ -f "${FRONTEND_DIR}/package.json" ]] || web_fail "frontend package.json not found: ${FRONTEND_DIR}/package.json"

    echo "Checking frontend dependencies with npm..."
    (
        cd "${FRONTEND_DIR}"
        if [[ ! -d "node_modules" ]]; then
            if [[ -f "package-lock.json" ]]; then
                npm ci
            else
                npm install
            fi
        else
            echo "node_modules already exists"
        fi
    )
}

web_ensure_runtime_image() {
    if [[ "${AGENTFACTORY_SKIP_DOCKER_IMAGE_CHECK:-0}" == "1" ]]; then
        echo "Skipping Docker runtime image check because AGENTFACTORY_SKIP_DOCKER_IMAGE_CHECK=1"
        return
    fi

    web_require_command "docker" "Install Docker Desktop and ensure docker is on PATH."
    [[ -f "${RUNTIME_DOCKERFILE}" ]] || web_fail "runtime Dockerfile not found: ${RUNTIME_DOCKERFILE}"

    echo "Checking Docker daemon..."
    docker info >/dev/null || web_fail "Docker daemon is not available. Start Docker Desktop first."

    echo "Checking Docker runtime image: ${RUNTIME_IMAGE}"
    if docker image inspect "${RUNTIME_IMAGE}" >/dev/null 2>&1; then
        echo "Docker runtime image exists: ${RUNTIME_IMAGE}"
        return
    fi

    echo "Docker runtime image missing; building ${RUNTIME_IMAGE}..."
    local build_args=()
    if [[ -n "${AGENTFACTORY_PYTHON_BASE_IMAGE:-}" ]]; then
        build_args+=(--build-arg "PYTHON_BASE_IMAGE=${AGENTFACTORY_PYTHON_BASE_IMAGE}")
    fi
    if [[ -n "${AGENTFACTORY_DEBIAN_MIRROR:-}" ]]; then
        build_args+=(--build-arg "DEBIAN_MIRROR=${AGENTFACTORY_DEBIAN_MIRROR}")
    fi
    if [[ -n "${AGENTFACTORY_DEBIAN_SECURITY_MIRROR:-}" ]]; then
        build_args+=(--build-arg "DEBIAN_SECURITY_MIRROR=${AGENTFACTORY_DEBIAN_SECURITY_MIRROR}")
    fi

    (
        cd "${PROJECT_ROOT}"
        docker build -t "${RUNTIME_IMAGE}" "${build_args[@]}" -f "${RUNTIME_DOCKERFILE}" .
    )
}

web_wait_for_backend() {
    local backend_pid="$1"
    local attempts="${2:-30}"
    local delay_seconds="${3:-1}"

    web_require_command "curl" "Install curl first."

    for ((attempt = 1; attempt <= attempts; attempt++)); do
        if curl -fsS "${BACKEND_HEALTH_URL}" >/dev/null 2>&1; then
            return 0
        fi
        if ! kill -0 "${backend_pid}" >/dev/null 2>&1; then
            wait "${backend_pid}" 2>/dev/null || true
            return 1
        fi
        sleep "${delay_seconds}"
    done
    return 1
}

web_print_port_status() {
    local port="$1"
    if ! command -v lsof >/dev/null 2>&1; then
        echo "Port ${port}: lsof unavailable, skipped"
        return
    fi
    if lsof -i:"${port}" >/dev/null 2>&1; then
        echo "Port ${port}: in use"
        lsof -i:"${port}" | grep LISTEN || true
    else
        echo "Port ${port}: available"
    fi
}
