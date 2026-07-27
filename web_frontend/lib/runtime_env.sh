#!/usr/bin/env bash
# Shared environment helpers for FastAgentFactory web frontend scripts.

WEB_FRONTEND_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_FRONTEND_DIR="$(cd "${WEB_FRONTEND_LIB_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${WEB_FRONTEND_DIR}/.." && pwd)"
FRONTEND_DIR="${WEB_FRONTEND_DIR}/frontend"
PROJECT_ENV_FILE="${PROJECT_ROOT}/.env"
DEPLOY_DEFAULTS_FILE="${PROJECT_ROOT}/deploy/defaults.env"

if [[ -f "${PROJECT_ENV_FILE}" ]]; then
    [[ -r "${DEPLOY_DEFAULTS_FILE}" ]] || {
        echo "ERROR: Deployment defaults are missing: ${DEPLOY_DEFAULTS_FILE}" >&2
        return 1 2>/dev/null || exit 1
    }
    # Deployment defaults remain internal shell values; only explicit user
    # configuration and the derived runtime contract are exported.
    # shellcheck disable=SC1090
    source "${DEPLOY_DEFAULTS_FILE}"
    set -a
    # shellcheck disable=SC1090
    source "${PROJECT_ENV_FILE}"
    set +a

    AGENTFACTORY_INFERENCE_RUNTIME_MODE="${AGENTFACTORY_INFERENCE_RUNTIME_MODE:-external}"
    if [[ "${DEPLOY_TARGET:-ssh}" == "local" ]]; then
        AGENTFACTORY_INFERENCE_CONNECTION_MODE="${AGENTFACTORY_INFERENCE_CONNECTION_MODE:-direct}"
        inference_chat_port="${REMOTE_CHAT_PORT}"
        inference_embedding_port="${REMOTE_EMBEDDING_PORT}"
        inference_telemetry_port="${REMOTE_TELEMETRY_PORT}"
        inference_image_port="${REMOTE_IMAGE_PORT}"
    else
        AGENTFACTORY_INFERENCE_CONNECTION_MODE="${AGENTFACTORY_INFERENCE_CONNECTION_MODE:-ssh}"
        inference_chat_port="${LOCAL_CHAT_PORT}"
        inference_embedding_port="${LOCAL_EMBEDDING_PORT}"
        inference_telemetry_port="${LOCAL_TELEMETRY_PORT}"
        inference_image_port="${LOCAL_IMAGE_PORT}"
    fi
    AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT="${AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT:-http://127.0.0.1:${inference_chat_port}/v1}"
    AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT="${AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT:-http://127.0.0.1:${inference_embedding_port}}"
    AGENTFACTORY_LOCAL_IMAGE_ENDPOINT="${AGENTFACTORY_LOCAL_IMAGE_ENDPOINT:-http://127.0.0.1:${inference_image_port}/v1}"
    AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT="${AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT:-http://127.0.0.1:${inference_telemetry_port}}"
    AGENTFACTORY_INFERENCE_SSH_HOST="${AGENTFACTORY_INFERENCE_SSH_HOST:-${SSH_HOST:-}}"
    AGENTFACTORY_INFERENCE_SSH_PORT="${AGENTFACTORY_INFERENCE_SSH_PORT:-${SSH_PORT:-}}"
    AGENTFACTORY_INFERENCE_SSH_USER="${AGENTFACTORY_INFERENCE_SSH_USER:-${SSH_USER:-}}"
    AGENTFACTORY_INFERENCE_SSH_KEY="${AGENTFACTORY_INFERENCE_SSH_KEY:-${SSH_KEY:-}}"
    AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT="${AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT:-${LOCAL_CHAT_PORT}}"
    AGENTFACTORY_INFERENCE_SSH_CHAT_REMOTE_PORT="${AGENTFACTORY_INFERENCE_SSH_CHAT_REMOTE_PORT:-${REMOTE_CHAT_PORT}}"
    AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT="${AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT:-${LOCAL_EMBEDDING_PORT}}"
    AGENTFACTORY_INFERENCE_SSH_EMBEDDING_REMOTE_PORT="${AGENTFACTORY_INFERENCE_SSH_EMBEDDING_REMOTE_PORT:-${REMOTE_EMBEDDING_PORT}}"
    AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT="${AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT:-${LOCAL_TELEMETRY_PORT}}"
    AGENTFACTORY_INFERENCE_SSH_TELEMETRY_REMOTE_PORT="${AGENTFACTORY_INFERENCE_SSH_TELEMETRY_REMOTE_PORT:-${REMOTE_TELEMETRY_PORT}}"
    AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT="${AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT:-${LOCAL_IMAGE_PORT}}"
    AGENTFACTORY_INFERENCE_SSH_IMAGE_REMOTE_PORT="${AGENTFACTORY_INFERENCE_SSH_IMAGE_REMOTE_PORT:-${REMOTE_IMAGE_PORT}}"
    export AGENTFACTORY_INFERENCE_RUNTIME_MODE AGENTFACTORY_INFERENCE_CONNECTION_MODE
    export AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT
    export AGENTFACTORY_LOCAL_IMAGE_ENDPOINT AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT
    export AGENTFACTORY_INFERENCE_SSH_HOST AGENTFACTORY_INFERENCE_SSH_PORT
    export AGENTFACTORY_INFERENCE_SSH_USER AGENTFACTORY_INFERENCE_SSH_KEY
    export AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT AGENTFACTORY_INFERENCE_SSH_CHAT_REMOTE_PORT
    export AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT AGENTFACTORY_INFERENCE_SSH_EMBEDDING_REMOTE_PORT
    export AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT AGENTFACTORY_INFERENCE_SSH_TELEMETRY_REMOTE_PORT
    export AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT AGENTFACTORY_INFERENCE_SSH_IMAGE_REMOTE_PORT
fi

PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
WEB_SEARCH_MCP_DIR="${AGENTFACTORY_WEB_SEARCH_MCP_DIR:-${PROJECT_ROOT}/.agentfactory/mcp/web_search}"
WEB_SEARCH_MCP_REPOSITORY="${AGENTFACTORY_WEB_SEARCH_MCP_REPOSITORY:-https://github.com/LiuYan-89937/BigOpenLLMSearch.git}"
INFERENCE_SSH_TUNNEL_PID=""

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

web_validate_port() {
    local name="$1"
    local value="$2"
    if [[ ! "${value}" =~ ^[0-9]+$ ]] || (( value < 1 || value > 65535 )); then
        web_fail "${name} must be an integer between 1 and 65535"
    fi
}

web_require_available_local_port() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
        web_fail "Local port ${port} is already in use; stop its listener or choose another SSH local port in .env"
    fi
}

web_expand_home_path() {
    local path="$1"
    if [[ "${path}" == "~/"* ]]; then
        printf '%s' "${HOME}/${path#\~/}"
        return
    fi
    printf '%s' "${path}"
}

web_start_inference_ssh_tunnel() {
    if [[ "${AGENTFACTORY_INFERENCE_RUNTIME_MODE:-managed}" != "external" ]]; then
        return
    fi

    web_require_command "curl" "Install curl first."

    local connection_mode="${AGENTFACTORY_INFERENCE_CONNECTION_MODE:-}"
    if [[ -z "${connection_mode}" ]]; then
        if [[ -n "${AGENTFACTORY_INFERENCE_SSH_HOST:-}" ]]; then
            connection_mode="ssh"
        else
            connection_mode="direct"
        fi
    fi
    if [[ "${connection_mode}" != "direct" && "${connection_mode}" != "ssh" ]]; then
        web_fail "AGENTFACTORY_INFERENCE_CONNECTION_MODE must be direct or ssh"
    fi

    local endpoint_names=(
        AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT
        AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT
        AGENTFACTORY_LOCAL_IMAGE_ENDPOINT
        AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT
    )
    local name
    for name in "${endpoint_names[@]}"; do
        if [[ -z "${!name:-}" ]]; then
            web_fail "${name} is required when AGENTFACTORY_INFERENCE_RUNTIME_MODE=external"
        fi
    done
    if [[ "${connection_mode}" == "direct" ]]; then
        if web_check_inference_node; then
            echo "Direct inference control endpoint is reachable"
            return
        fi
        web_fail "Direct inference control endpoint validation failed"
    fi

    web_require_command "ssh" "Install the OpenSSH client first."

    local required_names=(
        AGENTFACTORY_INFERENCE_SSH_HOST
        AGENTFACTORY_INFERENCE_SSH_PORT
        AGENTFACTORY_INFERENCE_SSH_USER
        AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT
        AGENTFACTORY_INFERENCE_SSH_CHAT_REMOTE_PORT
        AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT
        AGENTFACTORY_INFERENCE_SSH_EMBEDDING_REMOTE_PORT
        AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT
        AGENTFACTORY_INFERENCE_SSH_TELEMETRY_REMOTE_PORT
        AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT
        AGENTFACTORY_INFERENCE_SSH_IMAGE_REMOTE_PORT
    )
    for name in "${required_names[@]}"; do
        if [[ -z "${!name:-}" ]]; then
            web_fail "${name} is required when AGENTFACTORY_INFERENCE_RUNTIME_MODE=external"
        fi
    done

    web_validate_port "AGENTFACTORY_INFERENCE_SSH_PORT" "${AGENTFACTORY_INFERENCE_SSH_PORT}"
    web_validate_port "AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT" "${AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT}"
    web_validate_port "AGENTFACTORY_INFERENCE_SSH_CHAT_REMOTE_PORT" "${AGENTFACTORY_INFERENCE_SSH_CHAT_REMOTE_PORT}"
    web_validate_port "AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT" "${AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT}"
    web_validate_port "AGENTFACTORY_INFERENCE_SSH_EMBEDDING_REMOTE_PORT" "${AGENTFACTORY_INFERENCE_SSH_EMBEDDING_REMOTE_PORT}"
    web_validate_port "AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT" "${AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT}"
    web_validate_port "AGENTFACTORY_INFERENCE_SSH_TELEMETRY_REMOTE_PORT" "${AGENTFACTORY_INFERENCE_SSH_TELEMETRY_REMOTE_PORT}"
    web_validate_port "AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT" "${AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT}"
    web_validate_port "AGENTFACTORY_INFERENCE_SSH_IMAGE_REMOTE_PORT" "${AGENTFACTORY_INFERENCE_SSH_IMAGE_REMOTE_PORT}"
    if [[ "${AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT}" == "${AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT}" \
        || "${AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT}" == "${AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT}" \
        || "${AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT}" == "${AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT}" \
        || "${AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT}" == "${AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT}" \
        || "${AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT}" == "${AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT}" \
        || "${AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT}" == "${AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT}" ]]; then
        web_fail "Chat, embedding, telemetry, and image SSH local ports must be different"
    fi

    web_require_available_local_port "${AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT}"
    web_require_available_local_port "${AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT}"
    web_require_available_local_port "${AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT}"
    web_require_available_local_port "${AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT}"

    local ssh_key="${AGENTFACTORY_INFERENCE_SSH_KEY:-}"
    local ssh_command=(
        ssh -N
        -o BatchMode=yes
        -o ExitOnForwardFailure=yes
        -o ServerAliveInterval=30
        -o ServerAliveCountMax=3
        -p "${AGENTFACTORY_INFERENCE_SSH_PORT}"
        -L "${AGENTFACTORY_INFERENCE_SSH_CHAT_LOCAL_PORT}:127.0.0.1:${AGENTFACTORY_INFERENCE_SSH_CHAT_REMOTE_PORT}"
        -L "${AGENTFACTORY_INFERENCE_SSH_EMBEDDING_LOCAL_PORT}:127.0.0.1:${AGENTFACTORY_INFERENCE_SSH_EMBEDDING_REMOTE_PORT}"
        -L "${AGENTFACTORY_INFERENCE_SSH_TELEMETRY_LOCAL_PORT}:127.0.0.1:${AGENTFACTORY_INFERENCE_SSH_TELEMETRY_REMOTE_PORT}"
        -L "${AGENTFACTORY_INFERENCE_SSH_IMAGE_LOCAL_PORT}:127.0.0.1:${AGENTFACTORY_INFERENCE_SSH_IMAGE_REMOTE_PORT}"
    )
    if [[ -n "${ssh_key}" ]]; then
        ssh_key="$(web_expand_home_path "${ssh_key}")"
        [[ -r "${ssh_key}" ]] || web_fail "SSH private key is not readable: ${ssh_key}"
        ssh_command+=(-i "${ssh_key}")
    fi
    ssh_command+=("${AGENTFACTORY_INFERENCE_SSH_USER}@${AGENTFACTORY_INFERENCE_SSH_HOST}")

    echo "Opening SSH tunnel to external inference host..."
    "${ssh_command[@]}" &
    INFERENCE_SSH_TUNNEL_PID=$!

    local attempt
    for attempt in {1..20}; do
        if ! kill -0 "${INFERENCE_SSH_TUNNEL_PID}" >/dev/null 2>&1; then
            wait "${INFERENCE_SSH_TUNNEL_PID}" 2>/dev/null || true
            INFERENCE_SSH_TUNNEL_PID=""
            web_fail "SSH tunnel exited before the inference control endpoint became available"
        fi
        if web_check_inference_node; then
            echo "External inference control endpoint is reachable"
            return
        fi
        sleep 0.5
    done

    web_stop_inference_ssh_tunnel
    web_fail "SSH tunnel opened, but the inference control endpoint validation failed"
}

web_check_inference_node() {
    local telemetry_endpoint="${AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT%/}"
    curl --fail --silent --show-error --max-time 2 "${telemetry_endpoint}/health" >/dev/null 2>&1 \
        && curl --fail --silent --show-error --max-time 2 "${telemetry_endpoint}/models" >/dev/null 2>&1 \
        && curl --fail --silent --show-error --max-time 2 "${telemetry_endpoint}/runtime/rocm" >/dev/null 2>&1
}

web_stop_inference_ssh_tunnel() {
    if [[ -z "${INFERENCE_SSH_TUNNEL_PID}" ]]; then
        return
    fi
    if kill -0 "${INFERENCE_SSH_TUNNEL_PID}" >/dev/null 2>&1; then
        echo "Stopping inference SSH tunnel..."
        kill "${INFERENCE_SSH_TUNNEL_PID}" >/dev/null 2>&1 || true
        wait "${INFERENCE_SSH_TUNNEL_PID}" 2>/dev/null || true
    fi
    INFERENCE_SSH_TUNNEL_PID=""
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
        "AGENTFACTORY_RESOURCE_MASTER_KEY"
    )

    for name in "${required_vars[@]}"; do
        if [[ -z "$(web_env_file_value "${env_file}" "${name}")" ]]; then
            missing+=("${name}")
        fi
    done

    if [[ -n "$(web_env_file_value "${env_file}" "TAVILY_API_KEY")" ]]; then
        echo "Tavily is configured for the built-in web search MCP"
    else
        web_warn "TAVILY_API_KEY is empty; built-in web search will use SearXNG, then DuckDuckGo if needed"
    fi

    if (( ${#missing[@]} == 0 )); then
        echo ".env looks configured"
        return 0
    fi

    web_warn ".env exists but the following required settings are empty:"
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
        echo "Skipping built-in web search MCP setup"
        return
    fi

    web_require_command "git" "Install Git first."
    web_require_command "node" "Install Node.js first."
    web_require_command "npm" "Install npm first."

    local previous_revision=""
    local current_revision=""
    local needs_build=0
    if [[ -d "${WEB_SEARCH_MCP_DIR}/.git" ]]; then
        previous_revision="$(git -C "${WEB_SEARCH_MCP_DIR}" rev-parse HEAD)"
        if [[ "${AGENTFACTORY_UPDATE_WEB_SEARCH_MCP:-0}" == "1" ]]; then
            echo "Updating built-in web search MCP..."
            git -C "${WEB_SEARCH_MCP_DIR}" fetch --quiet origin
            git -C "${WEB_SEARCH_MCP_DIR}" pull --ff-only --quiet
        else
            echo "Using installed built-in web search MCP"
        fi
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
