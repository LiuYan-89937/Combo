#!/usr/bin/env bash
# Shared environment helpers for FastAgentFactory web frontend scripts.

WEB_FRONTEND_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_FRONTEND_DIR="$(cd "${WEB_FRONTEND_LIB_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${WEB_FRONTEND_DIR}/.." && pwd)"
FRONTEND_DIR="${WEB_FRONTEND_DIR}/frontend"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
RUNTIME_IMAGE="${AGENTFACTORY_RUNTIME_IMAGE:-agentfactory-runtime-python:3.12}"
RUNTIME_DOCKERFILE="${AGENTFACTORY_RUNTIME_DOCKERFILE:-${PROJECT_ROOT}/docker/agent-runtime/Dockerfile}"
RUNTIME_SOURCE_DIGEST_LABEL="org.fastagentfactory.runtime.source_digest"
WEB_SEARCH_MCP_DIR="${AGENTFACTORY_WEB_SEARCH_MCP_DIR:-${PROJECT_ROOT}/.agentfactory/mcp/web_search}"
WEB_SEARCH_MCP_REPOSITORY="${AGENTFACTORY_WEB_SEARCH_MCP_REPOSITORY:-https://github.com/LiuYan-89937/WebSearchApi.git}"

web_fail() {
    echo "ERROR: $*" >&2
    exit 1
}

web_require_project_root() {
    [[ -f "${PROJECT_ROOT}/pyproject.toml" ]] || web_fail "pyproject.toml not found at ${PROJECT_ROOT}"
}

web_warn() {
    echo "WARNING: $*" >&2
}

web_require_command() {
    local command_name="$1"
    local install_hint="$2"
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        web_fail "${command_name} not found. ${install_hint}"
    fi
}

web_check_env_configuration() {
    local env_file="${PROJECT_ROOT}/.env"
    local example_file="${PROJECT_ROOT}/.env.example"
    local missing=()
    local name

    echo "Checking local environment configuration..."

    if [[ ! -f "${env_file}" ]]; then
        web_warn ".env not found. Copy ${example_file} to .env and fill in model configuration."
        echo "         cp .env.example .env"
        return 0
    fi

    local required_vars=(
        "AGENTFACTORY_MODEL_BASE_URL"
        "AGENTFACTORY_MODEL_API_KEY"
        "AGENTFACTORY_MAIN_MODEL"
        "AGENTFACTORY_TASK_MODEL"
        "AGENTFACTORY_COMPRESSION_MODEL"
        "AGENTFACTORY_EMBEDDING_BASE_URL"
        "AGENTFACTORY_EMBEDDING_API_KEY"
        "AGENTFACTORY_EMBEDDING_MODEL"
        "AGENTFACTORY_RESOURCE_MASTER_KEY"
    )

    for name in "${required_vars[@]}"; do
        if [[ -z "$(web_env_file_value "${env_file}" "${name}")" ]]; then
            missing+=("${name}")
        fi
    done

    if (( ${#missing[@]} == 0 )); then
        echo ".env looks configured"
        return 0
    fi

    web_warn ".env exists but the following model settings are empty:"
    for name in "${missing[@]}"; do
        echo "         - ${name}"
    done
    echo "         The services can still start, but model calls/RAG may fail until these are filled."
}

web_env_file_value() {
    local env_file="$1"
    local name="$2"
    local line
    line="$(grep -E "^[[:space:]]*${name}[[:space:]]*=" "${env_file}" | tail -n 1 || true)"
    if [[ -z "${line}" ]]; then
        return 0
    fi
    line="${line#*=}"
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    line="${line%\"}"
    line="${line#\"}"
    line="${line%\'}"
    line="${line#\'}"
    printf '%s' "${line}"
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
        elif [[ ! -x "node_modules/.bin/vite" ]]; then
            echo "node_modules exists but required frontend binaries are missing; running npm install..."
            npm install
        else
            echo "node_modules already exists"
        fi
    )
}

web_ensure_builtin_web_search_mcp() {
    if [[ "${AGENTFACTORY_SKIP_WEB_SEARCH_MCP_SETUP:-0}" == "1" ]]; then
        echo "Skipping built-in web search MCP setup because AGENTFACTORY_SKIP_WEB_SEARCH_MCP_SETUP=1"
        return
    fi

    web_require_command "git" "Install Git first."
    web_require_command "node" "Install Node.js first."
    web_require_command "npm" "Install npm first."

    local previous_revision=""
    local current_revision=""
    local needs_build=0
    if [[ -d "${WEB_SEARCH_MCP_DIR}/.git" ]]; then
        echo "Updating built-in web search MCP..."
        previous_revision="$(git -C "${WEB_SEARCH_MCP_DIR}" rev-parse HEAD)"
        git -C "${WEB_SEARCH_MCP_DIR}" fetch --quiet origin
        git -C "${WEB_SEARCH_MCP_DIR}" pull --ff-only --quiet
    elif [[ -e "${WEB_SEARCH_MCP_DIR}" ]]; then
        web_fail "web search MCP directory exists but is not a Git checkout: ${WEB_SEARCH_MCP_DIR}"
    else
        echo "Cloning built-in web search MCP..."
        mkdir -p "$(dirname "${WEB_SEARCH_MCP_DIR}")"
        git clone --quiet "${WEB_SEARCH_MCP_REPOSITORY}" "${WEB_SEARCH_MCP_DIR}"
    fi

    current_revision="$(git -C "${WEB_SEARCH_MCP_DIR}" rev-parse HEAD)"
    if [[ ! -d "${WEB_SEARCH_MCP_DIR}/node_modules" || "${previous_revision}" != "${current_revision}" ]]; then
        echo "Installing built-in web search MCP dependencies..."
        (
            cd "${WEB_SEARCH_MCP_DIR}"
            if [[ -f "package-lock.json" ]]; then
                npm ci
            else
                npm install
            fi
        )
        needs_build=1
    fi

    if [[ ! -f "${WEB_SEARCH_MCP_DIR}/dist/index.js" || "${previous_revision}" != "${current_revision}" ]]; then
        needs_build=1
    fi
    if (( needs_build == 1 )); then
        echo "Building built-in web search MCP..."
        (cd "${WEB_SEARCH_MCP_DIR}" && npm run build)
    else
        echo "Built-in web search MCP is ready"
    fi
}

web_ensure_runtime_image() {
    if [[ "${AGENTFACTORY_SKIP_DOCKER_IMAGE_CHECK:-0}" == "1" ]]; then
        echo "Skipping Docker runtime image check because AGENTFACTORY_SKIP_DOCKER_IMAGE_CHECK=1"
        return
    fi

    web_require_command "docker" "Install Docker Desktop and ensure docker is on PATH: https://www.docker.com/products/docker-desktop/"
    [[ -f "${RUNTIME_DOCKERFILE}" ]] || web_fail "runtime Dockerfile not found: ${RUNTIME_DOCKERFILE}"

    echo "Checking Docker daemon..."
    docker info >/dev/null || web_fail "Docker daemon is not available. Start Docker Desktop first, then run ./start.sh again."

    echo "Checking Docker runtime image: ${RUNTIME_IMAGE}"
    local source_digest
    source_digest="$(web_runtime_source_digest)"
    if docker image inspect "${RUNTIME_IMAGE}" >/dev/null 2>&1; then
        local image_digest
        image_digest="$(docker image inspect "${RUNTIME_IMAGE}" --format "{{ index .Config.Labels \"${RUNTIME_SOURCE_DIGEST_LABEL}\" }}" 2>/dev/null || true)"
        if [[ "${image_digest}" == "${source_digest}" ]]; then
            echo "Docker runtime image exists and is up to date: ${RUNTIME_IMAGE}"
            return
        fi
        echo "Docker runtime image is stale; rebuilding ${RUNTIME_IMAGE}"
    else
        echo "Docker runtime image missing; building ${RUNTIME_IMAGE} from ${RUNTIME_DOCKERFILE}..."
    fi

    web_build_runtime_image "${source_digest}"
}

web_runtime_source_digest() {
    "${PYTHON_BIN}" - "${PROJECT_ROOT}" "${RUNTIME_DOCKERFILE}" <<'PY'
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys

project_root = Path(sys.argv[1]).resolve()
dockerfile = Path(sys.argv[2]).resolve()
inputs = [
    dockerfile,
    project_root / "pyproject.toml",
    project_root / "uv.lock",
]
roots = [
    project_root / "agent_factory",
    project_root / "docker" / "agent-runtime",
]
ignored_dirs = {"__pycache__", ".mypy_cache", ".ruff_cache"}
ignored_suffixes = {".pyc", ".pyo"}

digest = hashlib.sha256()


def add_file(path: Path) -> None:
    if not path.is_file() or path.suffix in ignored_suffixes:
        return
    rel = path.relative_to(project_root).as_posix()
    digest.update(rel.encode("utf-8"))
    digest.update(b"\0")
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    digest.update(b"\0")


for path in inputs:
    add_file(path)

for root in roots:
    if not root.exists():
        continue
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in ignored_dirs)
        for filename in sorted(filenames):
            add_file(Path(current_root) / filename)

print(digest.hexdigest())
PY
}

web_build_runtime_image() {
    local source_digest="$1"
    local build_args=()
    local build_network="${AGENTFACTORY_DOCKER_BUILD_NETWORK:-host}"
    if [[ -n "${AGENTFACTORY_PYTHON_BASE_IMAGE:-}" ]]; then
        build_args+=(--build-arg "PYTHON_BASE_IMAGE=${AGENTFACTORY_PYTHON_BASE_IMAGE}")
    fi
    if [[ -n "${AGENTFACTORY_DEBIAN_MIRROR:-}" ]]; then
        build_args+=(--build-arg "DEBIAN_MIRROR=${AGENTFACTORY_DEBIAN_MIRROR}")
    fi
    if [[ -n "${AGENTFACTORY_DEBIAN_SECURITY_MIRROR:-}" ]]; then
        build_args+=(--build-arg "DEBIAN_SECURITY_MIRROR=${AGENTFACTORY_DEBIAN_SECURITY_MIRROR}")
    fi
    if [[ -n "${AGENTFACTORY_PYPI_INDEX_URL:-}" ]]; then
        build_args+=(--build-arg "PYPI_INDEX_URL=${AGENTFACTORY_PYPI_INDEX_URL}")
    fi

    local docker_build=(
        docker build
        --network "${build_network}"
        -t "${RUNTIME_IMAGE}"
        --label "${RUNTIME_SOURCE_DIGEST_LABEL}=${source_digest}"
    )
    if (( ${#build_args[@]} > 0 )); then
        docker_build+=("${build_args[@]}")
    fi
    docker_build+=(-f "${RUNTIME_DOCKERFILE}" .)

    (
        cd "${PROJECT_ROOT}"
        "${docker_build[@]}"
    )
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
