#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${FASTAGENTFACTORY_DEPLOY_CONFIG:-${PROJECT_ROOT}/deploy/deploy.env}"
CONFIG_EXAMPLE="${PROJECT_ROOT}/deploy/deploy.env.example"
REMOTE_CONTROLLER="${PROJECT_ROOT}/deploy/remote_runtime.sh"
COMMAND="${1:-up}"
shift $(( $# > 0 ? 1 : 0 ))
START_LOCAL_WEB=1
REMOTE_COMMAND_ARGS=()
for argument in "$@"; do
    case "${argument}" in
        --no-web) START_LOCAL_WEB=0 ;;
        *) REMOTE_COMMAND_ARGS+=("${argument}") ;;
    esac
done

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
source "${CONFIG_EXAMPLE}"
# shellcheck disable=SC1090
source "${CONFIG_FILE}"
set +a

required_config=(
    SSH_HOST SSH_PORT SSH_USER REMOTE_PROJECT_ROOT REMOTE_STATE_ROOT REMOTE_MODEL_ROOT
    REMOTE_LLAMA_SOURCE_ROOT REMOTE_LLAMA_RUNTIME_ROOT
    LOCAL_LLAMA_OFFICIAL_DIR LOCAL_LLAMA_AMD_DIR LOCAL_STABLE_DIFFUSION_CPP_DIR
    LLAMA_OFFICIAL_REVISION LLAMA_OFFICIAL_BUILD_NUMBER
    LLAMA_AMD_BASE_REVISION LLAMA_AMD_BASE_BUILD_NUMBER LLAMA_DEFAULT_IMPLEMENTATION
    REMOTE_STABLE_DIFFUSION_CPP_DIR STABLE_DIFFUSION_CPP_REVISION
    REMOTE_CA_BUNDLE REMOTE_REPAIR_CA_TRUST REMOTE_CA_PROBE_URL
    CHAT_MODEL_REPOSITORY CHAT_MODEL_REVISION CHAT_MODEL_FILENAME CHAT_MODEL_SHA256
    CHAT_MMPROJ_FILENAME CHAT_MMPROJ_SHA256 EMBEDDING_MODEL_ID EMBEDDING_MODEL_REVISION
    CHAT_PROFILE_ID CHAT_SERVED_MODEL_NAME CHAT_CONTEXT_SIZE CHAT_MAX_OUTPUT_TOKENS
    CHAT_COMPRESSION_THRESHOLD CHAT_GPU_LAYERS CHAT_PARALLEL_SLOTS CHAT_CACHE_TYPE_K
    CHAT_CACHE_TYPE_V EMBEDDING_PROFILE_ID EMBEDDING_SERVED_MODEL_NAME EMBEDDING_DIMENSIONS
    REMOTE_CHAT_PORT REMOTE_EMBEDDING_PORT REMOTE_TELEMETRY_PORT
    REMOTE_IMAGE_PORT LOCAL_CHAT_PORT LOCAL_EMBEDDING_PORT LOCAL_TELEMETRY_PORT LOCAL_IMAGE_PORT
    IMAGE_PROFILE_ID IMAGE_SERVED_MODEL_NAME IMAGE_MODEL_FILENAME IMAGE_VAE_FILENAME
    IMAGE_CLIP_L_FILENAME IMAGE_T5XXL_FILENAME
    REMOTE_INFERENCE_PYTHON_PACKAGES
)
for name in "${required_config[@]}"; do
    [[ -n "${!name:-}" ]] || fail "Missing deployment setting: ${name}"
done
[[ "${SSH_PORT}" =~ ^[0-9]+$ ]] || fail "SSH_PORT must be an integer"
(( SSH_PORT >= 1 && SSH_PORT <= 65535 )) || fail "SSH_PORT must be between 1 and 65535"
for name in LLAMA_OFFICIAL_BUILD_NUMBER LLAMA_AMD_BASE_BUILD_NUMBER; do
    [[ "${!name}" =~ ^[0-9]+$ ]] || fail "${name} must be a non-negative integer"
done
[[ "${REMOTE_REPAIR_CA_TRUST}" =~ ^[01]$ ]] \
    || fail "REMOTE_REPAIR_CA_TRUST must be 0 or 1"
for name in LOCAL_CHAT_PORT LOCAL_EMBEDDING_PORT LOCAL_TELEMETRY_PORT LOCAL_IMAGE_PORT; do
    [[ "${!name}" =~ ^[0-9]+$ ]] && (( ${!name} >= 1 && ${!name} <= 65535 )) \
        || fail "${name} must be an integer between 1 and 65535"
done
[[ "${LOCAL_CHAT_PORT}" != "${LOCAL_EMBEDDING_PORT}" \
    && "${LOCAL_CHAT_PORT}" != "${LOCAL_TELEMETRY_PORT}" \
    && "${LOCAL_CHAT_PORT}" != "${LOCAL_IMAGE_PORT}" \
    && "${LOCAL_EMBEDDING_PORT}" != "${LOCAL_TELEMETRY_PORT}" \
    && "${LOCAL_EMBEDDING_PORT}" != "${LOCAL_IMAGE_PORT}" \
    && "${LOCAL_TELEMETRY_PORT}" != "${LOCAL_IMAGE_PORT}" ]] \
    || fail "Local inference ports must be different"

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
LOCAL_LLAMA_OFFICIAL_PATH="${LOCAL_LLAMA_OFFICIAL_DIR}"
if [[ "${LOCAL_LLAMA_OFFICIAL_PATH}" != /* ]]; then
    LOCAL_LLAMA_OFFICIAL_PATH="${PROJECT_ROOT}/${LOCAL_LLAMA_OFFICIAL_PATH}"
fi
LOCAL_LLAMA_AMD_PATH="${LOCAL_LLAMA_AMD_DIR}"
if [[ "${LOCAL_LLAMA_AMD_PATH}" != /* ]]; then
    LOCAL_LLAMA_AMD_PATH="${PROJECT_ROOT}/${LOCAL_LLAMA_AMD_PATH}"
fi
LOCAL_LLAMA_COMMON_PATH="${PROJECT_ROOT}/vendor/llama.cpp-common"
LOCAL_STABLE_DIFFUSION_CPP_PATH="${LOCAL_STABLE_DIFFUSION_CPP_DIR}"
if [[ "${LOCAL_STABLE_DIFFUSION_CPP_PATH}" != /* ]]; then
    LOCAL_STABLE_DIFFUSION_CPP_PATH="${PROJECT_ROOT}/${LOCAL_STABLE_DIFFUSION_CPP_PATH}"
fi
ssh_run() {
    ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "$@"
}

upload_controller() {
    scp "${SCP_ARGS[@]}" "${REMOTE_CONTROLLER}" "${CONFIG_EXAMPLE}" "${CONFIG_FILE}" \
        "${SSH_TARGET}:/tmp/"
    ssh_run chmod 700 /tmp/remote_runtime.sh
    ssh_run chmod 600 /tmp/"$(basename "${CONFIG_FILE}")"
}

remote_command() {
    local command_name="$1"
    shift
    ssh_run /tmp/remote_runtime.sh "${command_name}" /tmp/"$(basename "${CONFIG_FILE}")" "$@"
}

validate_llama_source_tree() {
    local implementation="$1"
    local source_dir="$2"
    local required_file
    for required_file in \
        CMakeLists.txt \
        cmake/build-info.cmake \
        common/CMakeLists.txt \
        common/build-info.cpp.in \
        common/build-info.h \
        .fastagentfactory-kernel-catalog.json; do
        [[ -f "${source_dir}/${required_file}" ]] \
            || fail "Bundled ${implementation} llama.cpp source is incomplete: ${source_dir}/${required_file}"
    done
}

validate_stable_diffusion_source_tree() {
    local source_dir="$1"
    local required_file
    for required_file in \
        CMakeLists.txt \
        ggml/CMakeLists.txt \
        thirdparty/libwebm/build/cxx_flags.cmake \
        thirdparty/libwebm/build/msvc_runtime.cmake \
        thirdparty/libwebm/build/x86-mingw-gcc.cmake \
        thirdparty/libwebm/build/x86_64-mingw-gcc.cmake \
        .fastagentfactory-revision; do
        [[ -f "${source_dir}/${required_file}" ]] \
            || fail "Bundled stable-diffusion.cpp source is incomplete: ${source_dir}/${required_file}"
    done
    [[ "$(<"${source_dir}/.fastagentfactory-revision")" == "${STABLE_DIFFUSION_CPP_REVISION}" ]] \
        || fail "Bundled stable-diffusion.cpp revision does not match STABLE_DIFFUSION_CPP_REVISION"
}

prepare_local_sources() {
    validate_llama_source_tree official "${LOCAL_LLAMA_OFFICIAL_PATH}"
    validate_llama_source_tree amd "${LOCAL_LLAMA_AMD_PATH}"
    [[ -f "${LOCAL_LLAMA_COMMON_PATH}/fastagentfactory-operator-trace.h" \
        && -f "${LOCAL_LLAMA_COMMON_PATH}/fastagentfactory-operator-trace.cpp" ]] \
        || fail "Bundled shared llama.cpp operator trace source is incomplete: ${LOCAL_LLAMA_COMMON_PATH}"
    validate_stable_diffusion_source_tree "${LOCAL_STABLE_DIFFUSION_CPP_PATH}"
}

sync_sources() {
    require_command rsync "Install rsync on the local development machine."
    local rsync_transport
    printf -v rsync_transport '%q ' "${RSYNC_SSH[@]}"
    log "Synchronizing minimal inference runtime to ${SSH_TARGET}:${REMOTE_PROJECT_ROOT}"
    rsync -az --delete --delete-excluded --prune-empty-dirs \
        -e "${rsync_transport% }" \
        --include '/agent_factory/' \
        --include '/agent_factory/__init__.py' \
        --include '/agent_factory/warnings.py' \
        --include '/agent_factory/env.py' \
        --include '/agent_factory/paths.py' \
        --include '/agent_factory/local_inference/' \
        --exclude '/agent_factory/local_inference/__init__.py' \
        --include '/agent_factory/local_inference/*.py' \
        --include '/agent_factory/model_pool/' \
        --exclude '/agent_factory/model_pool/__init__.py' \
        --include '/agent_factory/model_pool/config.py' \
        --include '/agent_factory/model_pool/schema.py' \
        --include '/agent_factory/model_pool/store.py' \
        --include '/agent_factory/model_pool/storage.py' \
        --include '/agent_factory/model_pool/download.py' \
        --include '/agent_factory/models/' \
        --exclude '/agent_factory/models/__init__.py' \
        --include '/agent_factory/models/protocol.py' \
        --include '/deploy/' \
        --include '/deploy/configure_model_pool.py' \
        --include '/deploy/kernel-catalogs/' \
        --include '/deploy/kernel-catalogs/*.json' \
        --exclude '*' \
        "${PROJECT_ROOT}/" "${SSH_TARGET}:${REMOTE_PROJECT_ROOT}/"

    log "Synchronizing bundled official llama.cpp source"
    rsync -az --delete \
        -e "${rsync_transport% }" \
        --exclude 'build*/' \
        "${LOCAL_LLAMA_OFFICIAL_PATH}/" "${SSH_TARGET}:${REMOTE_LLAMA_SOURCE_ROOT}/official/"
    log "Synchronizing bundled AMD llama.cpp source"
    rsync -az --delete \
        -e "${rsync_transport% }" \
        --exclude 'build*/' \
        "${LOCAL_LLAMA_AMD_PATH}/" "${SSH_TARGET}:${REMOTE_LLAMA_SOURCE_ROOT}/amd/"
    log "Synchronizing shared llama.cpp operator trace source"
    rsync -az --delete \
        -e "${rsync_transport% }" \
        "${LOCAL_LLAMA_COMMON_PATH}/" "${SSH_TARGET}:${REMOTE_LLAMA_SOURCE_ROOT}/llama.cpp-common/"
    log "Synchronizing bundled stable-diffusion.cpp source"
    rsync -az --delete \
        -e "${rsync_transport% }" \
        --exclude '.git/' \
        --exclude '/build*/' \
        "${LOCAL_STABLE_DIFFUSION_CPP_PATH}/" "${SSH_TARGET}:${REMOTE_STABLE_DIFFUSION_CPP_DIR}/"
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
        --telemetry-remote-port "${REMOTE_TELEMETRY_PORT}" \
        --image-local-port "${LOCAL_IMAGE_PORT}" \
        --image-remote-port "${REMOTE_IMAGE_PORT}"
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
        --prune-unconfigured-models \
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
        "$(boolean_argument "${EMBEDDING_TRUST_REMOTE_CODE:-0}" embedding-trust-remote-code)" \
        --image-profile-id "${IMAGE_PROFILE_ID}" \
        --image-served-model-name "${IMAGE_SERVED_MODEL_NAME}" \
        --image-vae-path "${REMOTE_MODEL_ROOT}/image/flux1-dev-q4_0/${IMAGE_VAE_FILENAME}" \
        --image-clip-l-path "${REMOTE_MODEL_ROOT}/image/flux1-dev-q4_0/${IMAGE_CLIP_L_FILENAME}" \
        --image-t5xxl-path "${REMOTE_MODEL_ROOT}/image/flux1-dev-q4_0/${IMAGE_T5XXL_FILENAME}" \
        "$(boolean_argument "${IMAGE_ENABLED:-0}" image-enabled)" \
        "$(boolean_argument "${IMAGE_DIFFUSION_FLASH_ATTENTION:-1}" image-diffusion-flash-attention)" \
        "$(boolean_argument "${IMAGE_EAGER_LOAD:-1}" image-eager-load)" \
        "$(boolean_argument "${IMAGE_CLIP_ON_CPU:-1}" image-clip-on-cpu)" \
        "$(boolean_argument "${IMAGE_VAE_TILING:-1}" image-vae-tiling)" \
        --image-default-width "${IMAGE_DEFAULT_WIDTH:-768}" \
        --image-default-height "${IMAGE_DEFAULT_HEIGHT:-768}" \
        --image-default-steps "${IMAGE_DEFAULT_STEPS:-20}" \
        --image-default-cfg-scale "${IMAGE_DEFAULT_CFG_SCALE:-1.0}" \
        --image-residency-policy "${IMAGE_RESIDENCY_POLICY:-exclusive}" \
        --image-timeout-seconds "${IMAGE_TIMEOUT_SECONDS:-900}"
}

check_bootstrap_prerequisites() {
    require_command git "Install Git first."
    require_command python3 "Install Python 3.11 or newer."
    require_command rsync "Install rsync on the local development machine."
    require_command uv "Install uv from https://docs.astral.sh/uv/."
}

check_web_prerequisites() {
    require_command node "Install Node.js 18 or newer."
    require_command npm "Install npm."
    require_command docker "Install Docker Desktop or Docker Engine."
    docker info >/dev/null 2>&1 || fail "Docker is installed but the daemon is not running"
}

bootstrap() {
    check_bootstrap_prerequisites
    log "Checking SSH connectivity"
    ssh_run true
    prepare_local_sources
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
        if [[ "${START_LOCAL_WEB}" == "1" ]]; then
            check_web_prerequisites
        fi
        bootstrap
        if [[ "${START_LOCAL_WEB}" == "1" ]]; then
            log "Starting the local Web application and SSH tunnel"
            exec "${PROJECT_ROOT}/start.sh"
        fi
        log "Remote inference deployment is ready; local Web startup was skipped"
        ;;
    bootstrap)
        bootstrap
        ;;
    sync)
        prepare_local_sources
        upload_controller
        remote_command prepare-host
        sync_sources
        ;;
    models|image-models|build-llama|build-sd|switch-llama|list-llama-builds|rollback-llama|restart|down|status|doctor|logs)
        upload_controller
        if (( ${#REMOTE_COMMAND_ARGS[@]} > 0 )); then
            remote_command "${COMMAND}" "${REMOTE_COMMAND_ARGS[@]}"
        else
            remote_command "${COMMAND}"
        fi
        ;;
    *)
        fail "Unsupported command: ${COMMAND}. Use up, bootstrap, sync, models, image-models, build-llama, build-sd, switch-llama, list-llama-builds, rollback-llama, restart, down, status, doctor, or logs."
        ;;
esac
