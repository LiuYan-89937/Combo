#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${FASTAGENTFACTORY_DEPLOY_CONFIG:-${PROJECT_ROOT}/deploy/deploy.env}"
CONFIG_EXAMPLE="${PROJECT_ROOT}/deploy/deploy.env.example"
REMOTE_CONTROLLER="${PROJECT_ROOT}/deploy/remote_runtime.sh"
COMMAND="${1:-up}"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

log() {
    printf '[deploy] %s\n' "$*"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 is required. $2"
}

[[ -r "${CONFIG_FILE}" ]] \
    || fail "Deployment config is missing. Run: cp ${CONFIG_EXAMPLE} ${CONFIG_FILE}"

set -a
# shellcheck disable=SC1090
source "${CONFIG_FILE}"
set +a

required_config=(
    SSH_HOST SSH_PORT SSH_USER REMOTE_PROJECT_ROOT REMOTE_STATE_ROOT REMOTE_MODEL_ROOT
    REMOTE_LLAMA_CPP_DIR LOCAL_LLAMA_CPP_DIR LLAMA_CPP_REPOSITORY LLAMA_CPP_REVISION
    CHAT_PROFILE_ID CHAT_SERVED_MODEL_NAME CHAT_CONTEXT_SIZE CHAT_MAX_OUTPUT_TOKENS
    CHAT_COMPRESSION_THRESHOLD CHAT_GPU_LAYERS CHAT_PARALLEL_SLOTS CHAT_CACHE_TYPE_K
    CHAT_CACHE_TYPE_V EMBEDDING_PROFILE_ID EMBEDDING_SERVED_MODEL_NAME EMBEDDING_DIMENSIONS
    REMOTE_CHAT_PORT REMOTE_EMBEDDING_PORT REMOTE_TELEMETRY_PORT
    LOCAL_CHAT_PORT LOCAL_EMBEDDING_PORT LOCAL_TELEMETRY_PORT
)
for name in "${required_config[@]}"; do
    [[ -n "${!name:-}" ]] || fail "Missing deployment setting: ${name}"
done
[[ "${SSH_PORT}" =~ ^[0-9]+$ ]] || fail "SSH_PORT must be an integer"

require_command ssh "Install the OpenSSH client."
require_command scp "Install the OpenSSH client."

SSH_ARGS=(
    -o BatchMode=yes
    -o ConnectTimeout=15
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=3
    -o StrictHostKeyChecking=accept-new
    -p "${SSH_PORT}"
)
SCP_ARGS=(
    -o BatchMode=yes
    -o ConnectTimeout=15
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=3
    -o StrictHostKeyChecking=accept-new
    -P "${SSH_PORT}"
)
RSYNC_SSH=(
    ssh
    -o BatchMode=yes
    -o ConnectTimeout=15
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=3
    -o StrictHostKeyChecking=accept-new
    -p "${SSH_PORT}"
)

if [[ -n "${SSH_KEY:-}" ]]; then
    if [[ "${SSH_KEY}" == "~/"* ]]; then
        SSH_KEY="${HOME}/${SSH_KEY#\~/}"
    fi
    [[ -r "${SSH_KEY}" ]] || fail "SSH private key is not readable: ${SSH_KEY}"
    SSH_ARGS+=(-i "${SSH_KEY}")
    SCP_ARGS+=(-i "${SSH_KEY}")
    RSYNC_SSH+=(-i "${SSH_KEY}")
fi

SSH_TARGET="${SSH_USER}@${SSH_HOST}"
LOCAL_LLAMA_PATH="${LOCAL_LLAMA_CPP_DIR}"
if [[ "${LOCAL_LLAMA_PATH}" != /* ]]; then
    LOCAL_LLAMA_PATH="${PROJECT_ROOT}/${LOCAL_LLAMA_PATH}"
fi

ssh_run() {
    ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "$@"
}

upload_controller() {
    scp "${SCP_ARGS[@]}" "${REMOTE_CONTROLLER}" "${CONFIG_FILE}" \
        "${SSH_TARGET}:/tmp/"
    ssh_run chmod 700 /tmp/remote_runtime.sh
}

remote_command() {
    local command_name="$1"
    ssh_run /tmp/remote_runtime.sh "${command_name}" /tmp/"$(basename "${CONFIG_FILE}")"
}

prepare_local_llama() {
    require_command git "Install Git first."
    if [[ ! -d "${LOCAL_LLAMA_PATH}/.git" ]]; then
        if [[ -e "${LOCAL_LLAMA_PATH}" ]]; then
            fail "LOCAL_LLAMA_CPP_DIR exists but is not a Git checkout: ${LOCAL_LLAMA_PATH}"
        fi
        log "Cloning the editable llama.cpp source to ${LOCAL_LLAMA_PATH}"
        mkdir -p "$(dirname "${LOCAL_LLAMA_PATH}")"
        git clone "${LLAMA_CPP_REPOSITORY}" "${LOCAL_LLAMA_PATH}"
    fi

    local current_revision
    current_revision="$(git -C "${LOCAL_LLAMA_PATH}" rev-parse HEAD)"
    if [[ -n "$(git -C "${LOCAL_LLAMA_PATH}" status --porcelain)" ]]; then
        log "llama.cpp contains local operator changes; keeping the current working tree at ${current_revision}"
        return
    fi
    if [[ "${current_revision}" != "${LLAMA_CPP_REVISION}" ]]; then
        log "Checking out pinned llama.cpp revision ${LLAMA_CPP_REVISION}"
        git -C "${LOCAL_LLAMA_PATH}" fetch "${LLAMA_CPP_REPOSITORY}" "${LLAMA_CPP_REVISION}"
        git -C "${LOCAL_LLAMA_PATH}" checkout --detach "${LLAMA_CPP_REVISION}"
    else
        log "llama.cpp source is pinned at ${current_revision}"
    fi
}

sync_sources() {
    require_command rsync "Install rsync on the local development machine."
    local rsync_transport
    printf -v rsync_transport '%q ' "${RSYNC_SSH[@]}"
    log "Synchronizing FastAgentFactory to ${SSH_TARGET}:${REMOTE_PROJECT_ROOT}"
    rsync -az --delete \
        -e "${rsync_transport% }" \
        --exclude '.agentfactory/' \
        --exclude '.agent_runtime/' \
        --exclude '.deploy/' \
        --exclude '.env' \
        --exclude '.venv/' \
        --exclude 'node_modules/' \
        --exclude 'vendor/llama.cpp/' \
        "${PROJECT_ROOT}/" "${SSH_TARGET}:${REMOTE_PROJECT_ROOT}/"

    log "Synchronizing editable llama.cpp source to ${REMOTE_LLAMA_CPP_DIR}"
    rsync -az --delete \
        -e "${rsync_transport% }" \
        --exclude 'build/' \
        "${LOCAL_LLAMA_PATH}/" "${SSH_TARGET}:${REMOTE_LLAMA_CPP_DIR}/"
}

configure_local_env() {
    python3 "${PROJECT_ROOT}/deploy/configure_local_env.py" \
        --env-file "${PROJECT_ROOT}/.env" \
        --example-file "${PROJECT_ROOT}/.env.example" \
        --ssh-host "${SSH_HOST}" \
        --ssh-port "${SSH_PORT}" \
        --ssh-user "${SSH_USER}" \
        --ssh-key "${SSH_KEY:-}" \
        --chat-local-port "${LOCAL_CHAT_PORT}" \
        --chat-remote-port "${REMOTE_CHAT_PORT}" \
        --embedding-local-port "${LOCAL_EMBEDDING_PORT}" \
        --embedding-remote-port "${REMOTE_EMBEDDING_PORT}" \
        --telemetry-local-port "${LOCAL_TELEMETRY_PORT}" \
        --telemetry-remote-port "${REMOTE_TELEMETRY_PORT}"
}

boolean_argument() {
    local enabled="$1"
    local name="$2"
    if [[ "${enabled}" == "1" ]]; then
        printf -- '--%s' "${name}"
    else
        printf -- '--no-%s' "${name}"
    fi
}

configure_local_profiles() {
    require_command uv "Install uv from https://docs.astral.sh/uv/."
    log "Preparing local Python environment"
    (cd "${PROJECT_ROOT}" && uv sync --extra web)
    local python_bin="${PROJECT_ROOT}/.venv/bin/python"
    [[ -x "${python_bin}" ]] || fail "Local Python environment was not created"
    "${python_bin}" "${PROJECT_ROOT}/deploy/configure_model_pool.py" \
        --mode client \
        --store-path "${PROJECT_ROOT}/.agentfactory/model_pool/factory.sqlite" \
        --chat-profile-id "${CHAT_PROFILE_ID}" \
        --chat-served-model-name "${CHAT_SERVED_MODEL_NAME}" \
        --chat-mmproj-path "${REMOTE_MODEL_ROOT}/gguf/${CHAT_MMPROJ_FILENAME}" \
        --chat-revision "${CHAT_MODEL_REVISION}" \
        --chat-checksum "${CHAT_MODEL_SHA256}" \
        --context-size "${CHAT_CONTEXT_SIZE}" \
        --max-output-tokens "${CHAT_MAX_OUTPUT_TOKENS}" \
        --compression-threshold "${CHAT_COMPRESSION_THRESHOLD}" \
        --gpu-layers "${CHAT_GPU_LAYERS}" \
        --parallel-slots "${CHAT_PARALLEL_SLOTS}" \
        --cache-type-k "${CHAT_CACHE_TYPE_K}" \
        --cache-type-v "${CHAT_CACHE_TYPE_V}" \
        "$(boolean_argument "${CHAT_FLASH_ATTENTION:-1}" flash-attention)" \
        "$(boolean_argument "${CHAT_REASONING_SUPPORTED:-1}" reasoning-supported)" \
        --embedding-profile-id "${EMBEDDING_PROFILE_ID}" \
        --embedding-served-model-name "${EMBEDDING_SERVED_MODEL_NAME}" \
        --embedding-revision "${EMBEDDING_MODEL_REVISION}" \
        --embedding-dimensions "${EMBEDDING_DIMENSIONS}" \
        "$(boolean_argument "${EMBEDDING_TRUST_REMOTE_CODE:-0}" embedding-trust-remote-code)"
}

bootstrap() {
    require_command python3 "Install Python 3.11 or newer."
    log "Checking SSH connectivity"
    ssh_run true
    prepare_local_llama
    upload_controller
    remote_command prepare-host
    sync_sources
    upload_controller
    remote_command bootstrap
    configure_local_env
    configure_local_profiles
    log "Deployment bootstrap completed"
}

case "${COMMAND}" in
    up)
        bootstrap
        log "Starting the local Web application and SSH tunnel"
        exec "${PROJECT_ROOT}/start.sh"
        ;;
    bootstrap)
        bootstrap
        ;;
    sync)
        prepare_local_llama
        upload_controller
        remote_command prepare-host
        sync_sources
        ;;
    models|build-llama|restart|down|status|doctor|logs)
        upload_controller
        remote_command "${COMMAND}"
        ;;
    *)
        fail "Unsupported command: ${COMMAND}. Use up, bootstrap, sync, models, build-llama, restart, down, status, doctor, or logs."
        ;;
esac
