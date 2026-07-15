#!/usr/bin/env bash

set -euo pipefail

COMMAND="${1:-}"
CONFIG_FILE="${2:-}"

if [[ -z "${COMMAND}" || -z "${CONFIG_FILE}" || ! -r "${CONFIG_FILE}" ]]; then
    echo "Usage: remote_runtime.sh <prepare-host|bootstrap|up|down|restart|status|doctor|logs|models|build-llama> <config-file>" >&2
    exit 2
fi

set -a
# shellcheck disable=SC1090
source "${CONFIG_FILE}"
set +a

required_config=(
    REMOTE_PROJECT_ROOT REMOTE_STATE_ROOT REMOTE_MODEL_ROOT REMOTE_LLAMA_CPP_DIR
    PYPI_INDEX_URL HF_ENDPOINT CHAT_MODEL_REPOSITORY CHAT_MODEL_REVISION
    CHAT_MODEL_FILENAME CHAT_MODEL_SHA256 CHAT_MMPROJ_FILENAME CHAT_MMPROJ_SHA256
    EMBEDDING_MODEL_ID EMBEDDING_MODEL_REVISION CHAT_PROFILE_ID CHAT_SERVED_MODEL_NAME
    CHAT_CONTEXT_SIZE CHAT_MAX_OUTPUT_TOKENS CHAT_COMPRESSION_THRESHOLD CHAT_GPU_LAYERS
    CHAT_PARALLEL_SLOTS CHAT_CACHE_TYPE_K CHAT_CACHE_TYPE_V EMBEDDING_PROFILE_ID
    EMBEDDING_SERVED_MODEL_NAME EMBEDDING_DIMENSIONS REMOTE_CHAT_PORT
    REMOTE_EMBEDDING_PORT REMOTE_TELEMETRY_PORT
)
for name in "${required_config[@]}"; do
    if [[ -z "${!name:-}" ]]; then
        echo "Missing deployment setting: ${name}" >&2
        exit 2
    fi
done

VENV_DIR="${REMOTE_STATE_ROOT}/venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
MODEL_POOL_STORE="${REMOTE_STATE_ROOT}/model_pool/factory.sqlite"
PID_FILE="${REMOTE_STATE_ROOT}/inference-node.pid"
LOG_FILE="${REMOTE_STATE_ROOT}/logs/inference-node.log"
EMBEDDING_PATH_FILE="${REMOTE_STATE_ROOT}/embedding-model-path"
LLAMA_SERVER_BIN="${REMOTE_LLAMA_CPP_DIR}/build/bin/llama-server"
CHAT_MODEL_PATH="${REMOTE_MODEL_ROOT}/gguf/${CHAT_MODEL_FILENAME}"
CHAT_MMPROJ_PATH="${REMOTE_MODEL_ROOT}/gguf/${CHAT_MMPROJ_FILENAME}"

log() {
    printf '[remote] %s\n' "$*"
}

fail() {
    printf '[remote] ERROR: %s\n' "$*" >&2
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

prepare_host() {
    local missing=()
    local command_name
    for command_name in git curl cmake ninja g++ python3 rsync sha256sum; do
        command_exists "${command_name}" || missing+=("${command_name}")
    done
    if (( ${#missing[@]} > 0 )); then
        [[ "${REMOTE_INSTALL_BUILD_TOOLS:-1}" == "1" ]] \
            || fail "Missing build commands: ${missing[*]}. Set REMOTE_INSTALL_BUILD_TOOLS=1 or install them manually."
        command_exists apt-get || fail "Missing build commands and apt-get is unavailable: ${missing[*]}"
        log "Installing ordinary build tools only; ROCm, GPU drivers and PyTorch will not be changed"
        export DEBIAN_FRONTEND=noninteractive
        apt-get -o Acquire::Retries=5 update
        apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
            build-essential ca-certificates cmake curl git ninja-build python3-pip python3-venv rsync
    fi
    mkdir -p \
        "${REMOTE_PROJECT_ROOT}" \
        "${REMOTE_STATE_ROOT}/logs" \
        "${REMOTE_STATE_ROOT}/model_pool" \
        "${REMOTE_MODEL_ROOT}/gguf" \
        "${REMOTE_MODEL_ROOT}/modelscope" \
        "${REMOTE_LLAMA_CPP_DIR}"
}

doctor() {
    log "Host: $(hostname)"
    log "Disk"
    df -h "${REMOTE_PROJECT_ROOT}" "${REMOTE_MODEL_ROOT}" | awk 'NR == 1 || !seen[$1]++'
    log "ROCm GPU"
    if command_exists rocminfo; then
        rocminfo 2>/dev/null | grep -E 'Marketing Name|Name:' | head -n 8 || true
    else
        echo "rocminfo: not installed"
    fi
    if command_exists rocm-smi; then
        rocm-smi --showproductname --showmeminfo vram --showuse 2>/dev/null || true
    else
        echo "rocm-smi: not installed"
    fi
    log "PyTorch HIP"
    python3 - <<'PY'
try:
    import torch
    print(f"torch={torch.__version__}")
    print(f"hip={torch.version.hip}")
    print(f"gpu_available={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        print(f"gpu={torch.cuda.get_device_name(0)}")
        print(f"vram_gib={props.total_memory / 1024 ** 3:.2f}")
except Exception as exc:
    print(f"torch_probe_error={type(exc).__name__}: {exc}")
PY
    log "llama.cpp"
    if [[ -x "${LLAMA_SERVER_BIN}" ]]; then
        "${LLAMA_SERVER_BIN}" --version | head -n 1
    else
        echo "llama-server: not built"
    fi
}

prepare_python() {
    [[ -f "${REMOTE_PROJECT_ROOT}/pyproject.toml" ]] || fail "Project is not synchronized to ${REMOTE_PROJECT_ROOT}"
    if [[ ! -x "${PYTHON_BIN}" ]]; then
        log "Creating ROCm-compatible Python environment with system site packages"
        python3 -m venv --system-site-packages "${VENV_DIR}"
    fi
    local dependency_digest
    dependency_digest="$(sha256sum "${REMOTE_PROJECT_ROOT}/pyproject.toml" "${REMOTE_PROJECT_ROOT}/uv.lock" | sha256sum | awk '{print $1}')"
    local marker="${REMOTE_STATE_ROOT}/python-dependencies.sha256"
    if [[ -f "${marker}" ]] \
        && [[ "$(<"${marker}")" == "${dependency_digest}" ]] \
        && "${PYTHON_BIN}" -c 'import fastapi, modelscope, sentence_transformers, torch; assert torch.version.hip' >/dev/null 2>&1; then
        log "Python dependencies are ready"
        return
    fi
    log "Installing project, ModelScope and Embedding dependencies without replacing the ROCm base runtime"
    "${PYTHON_BIN}" -m pip install --index-url "${PYPI_INDEX_URL}" --upgrade pip
    "${PYTHON_BIN}" -m pip install \
        --index-url "${PYPI_INDEX_URL}" \
        --upgrade-strategy only-if-needed \
        -e "${REMOTE_PROJECT_ROOT}[web]" \
        'modelscope>=1.25,<2' \
        'sentence-transformers>=3,<6' \
        'transformers>=4.51,<6'
    "${PYTHON_BIN}" -c 'import torch; assert torch.version.hip, "The base image must provide ROCm PyTorch"'
    printf '%s\n' "${dependency_digest}" > "${marker}"
}

build_llama() {
    [[ -f "${REMOTE_LLAMA_CPP_DIR}/CMakeLists.txt" ]] \
        || fail "llama.cpp source is not synchronized to ${REMOTE_LLAMA_CPP_DIR}"
    log "Configuring llama.cpp with GGML_HIP=ON"
    cmake \
        -S "${REMOTE_LLAMA_CPP_DIR}" \
        -B "${REMOTE_LLAMA_CPP_DIR}/build" \
        -G Ninja \
        -DGGML_HIP=ON \
        -DGGML_NATIVE=ON \
        -DLLAMA_CURL=OFF \
        -DCMAKE_BUILD_TYPE=Release
    log "Building llama-server"
    cmake --build "${REMOTE_LLAMA_CPP_DIR}/build" --target llama-server --parallel "$(nproc)"
    [[ -x "${LLAMA_SERVER_BIN}" ]] || fail "llama-server build did not produce ${LLAMA_SERVER_BIN}"
    "${LLAMA_SERVER_BIN}" --version | head -n 1
}

download_file() {
    local url="$1"
    local destination="$2"
    local checksum="$3"
    local checksum_marker="${destination}.sha256"
    if [[ -f "${destination}" && -f "${checksum_marker}" && "$(<"${checksum_marker}")" == "${checksum}" ]]; then
        log "Using verified model file: ${destination}"
        return
    fi
    if [[ -f "${destination}" ]] && printf '%s  %s\n' "${checksum}" "${destination}" | sha256sum --check --status; then
        printf '%s\n' "${checksum}" > "${checksum_marker}"
        log "Verified existing model file: ${destination}"
        return
    fi
    log "Downloading $(basename "${destination}") with resume support"
    curl \
        --fail \
        --location \
        --retry 10 \
        --retry-all-errors \
        --continue-at - \
        --output "${destination}" \
        "${url}"
    printf '%s  %s\n' "${checksum}" "${destination}" | sha256sum --check --status \
        || fail "Checksum mismatch: ${destination}"
    printf '%s\n' "${checksum}" > "${checksum_marker}"
}

download_models() {
    prepare_python
    local model_base_url="${HF_ENDPOINT%/}/${CHAT_MODEL_REPOSITORY}/resolve/${CHAT_MODEL_REVISION}"
    download_file "${model_base_url}/${CHAT_MODEL_FILENAME}?download=true" "${CHAT_MODEL_PATH}" "${CHAT_MODEL_SHA256}"
    download_file "${model_base_url}/${CHAT_MMPROJ_FILENAME}?download=true" "${CHAT_MMPROJ_PATH}" "${CHAT_MMPROJ_SHA256}"
    log "Downloading or reusing ModelScope embedding model: ${EMBEDDING_MODEL_ID}"
    local embedding_path
    embedding_path="$(
        AGENTFACTORY_MODEL_ROOT="${REMOTE_MODEL_ROOT}" \
        "${PYTHON_BIN}" -m agent_factory.model_pool.download \
            "${EMBEDDING_MODEL_ID}" \
            --revision "${EMBEDDING_MODEL_REVISION}" \
        | tail -n 1
    )"
    [[ -d "${embedding_path}" ]] || fail "Embedding download did not return a model directory: ${embedding_path}"
    printf '%s\n' "${embedding_path}" > "${EMBEDDING_PATH_FILE}"
}

boolean_flag() {
    local enabled="$1"
    local name="$2"
    if [[ "${enabled}" == "1" ]]; then
        printf -- '--%s' "${name}"
    else
        printf -- '--no-%s' "${name}"
    fi
}

configure_profiles() {
    [[ -f "${EMBEDDING_PATH_FILE}" ]] || fail "Embedding model path is missing; run models first"
    local embedding_path
    embedding_path="$(<"${EMBEDDING_PATH_FILE}")"
    AGENTFACTORY_MODEL_ROOT="${REMOTE_MODEL_ROOT}" \
    "${PYTHON_BIN}" "${REMOTE_PROJECT_ROOT}/deploy/configure_model_pool.py" \
        --mode node \
        --store-path "${MODEL_POOL_STORE}" \
        --chat-profile-id "${CHAT_PROFILE_ID}" \
        --chat-served-model-name "${CHAT_SERVED_MODEL_NAME}" \
        --chat-model-path "${CHAT_MODEL_PATH}" \
        --chat-mmproj-path "${CHAT_MMPROJ_PATH}" \
        --chat-revision "${CHAT_MODEL_REVISION}" \
        --chat-checksum "${CHAT_MODEL_SHA256}" \
        --context-size "${CHAT_CONTEXT_SIZE}" \
        --max-output-tokens "${CHAT_MAX_OUTPUT_TOKENS}" \
        --compression-threshold "${CHAT_COMPRESSION_THRESHOLD}" \
        --gpu-layers "${CHAT_GPU_LAYERS}" \
        --parallel-slots "${CHAT_PARALLEL_SLOTS}" \
        --cache-type-k "${CHAT_CACHE_TYPE_K}" \
        --cache-type-v "${CHAT_CACHE_TYPE_V}" \
        "$(boolean_flag "${CHAT_FLASH_ATTENTION:-1}" flash-attention)" \
        "$(boolean_flag "${CHAT_REASONING_SUPPORTED:-1}" reasoning-supported)" \
        --embedding-profile-id "${EMBEDDING_PROFILE_ID}" \
        --embedding-served-model-name "${EMBEDDING_SERVED_MODEL_NAME}" \
        --embedding-model-path "${embedding_path}" \
        --embedding-revision "${EMBEDDING_MODEL_REVISION}" \
        --embedding-dimensions "${EMBEDDING_DIMENSIONS}" \
        "$(boolean_flag "${EMBEDDING_TRUST_REMOTE_CODE:-0}" embedding-trust-remote-code)"
}

node_environment() {
    export AGENTFACTORY_MODEL_ROOT="${REMOTE_MODEL_ROOT}"
    export AGENTFACTORY_MODEL_POOL_STORE_PATH="${MODEL_POOL_STORE}"
    export AGENTFACTORY_LLAMA_SERVER_PATH="${LLAMA_SERVER_BIN}"
    export AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT="http://127.0.0.1:${REMOTE_CHAT_PORT}/v1"
    export AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT="http://127.0.0.1:${REMOTE_EMBEDDING_PORT}"
    export AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT="http://127.0.0.1:${REMOTE_TELEMETRY_PORT}"
}

node_running() {
    [[ -f "${PID_FILE}" ]] || return 1
    local pid
    pid="$(<"${PID_FILE}")"
    [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" >/dev/null 2>&1
}

start_node() {
    prepare_python
    [[ -x "${LLAMA_SERVER_BIN}" ]] || fail "llama-server is not built"
    [[ -f "${MODEL_POOL_STORE}" ]] || fail "Model pool is not configured"
    if node_running; then
        log "Inference node is already running with PID $(<"${PID_FILE}")"
        return
    fi
    rm -f "${PID_FILE}"
    node_environment
    log "Starting inference control node on 127.0.0.1:${REMOTE_TELEMETRY_PORT}"
    nohup "${PYTHON_BIN}" -m agent_factory.local_inference.node_server \
        --host 127.0.0.1 \
        --port "${REMOTE_TELEMETRY_PORT}" \
        >> "${LOG_FILE}" 2>&1 < /dev/null &
    printf '%s\n' "$!" > "${PID_FILE}"
}

stop_node() {
    if ! node_running; then
        rm -f "${PID_FILE}"
        log "Inference node is not running"
        return
    fi
    local pid
    pid="$(<"${PID_FILE}")"
    log "Stopping inference node PID ${pid}"
    kill "${pid}"
    local attempt
    for attempt in {1..30}; do
        kill -0 "${pid}" >/dev/null 2>&1 || break
        sleep 1
    done
    if kill -0 "${pid}" >/dev/null 2>&1; then
        kill -TERM "${pid}" >/dev/null 2>&1 || true
    fi
    rm -f "${PID_FILE}"
}

wait_ready() {
    local health_url="http://127.0.0.1:${REMOTE_TELEMETRY_PORT}/health"
    local runtime_url="http://127.0.0.1:${REMOTE_TELEMETRY_PORT}/runtimes"
    local attempt
    for attempt in {1..120}; do
        if ! node_running; then
            tail -n 80 "${LOG_FILE}" 2>/dev/null || true
            fail "Inference node exited during startup"
        fi
        if curl --fail --silent --max-time 3 "${health_url}" >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    curl --fail --silent --max-time 3 "${health_url}" >/dev/null \
        || fail "Inference control endpoint did not become healthy"
    log "Control endpoint is healthy; waiting for Chat and Embedding profiles"
    for attempt in {1..900}; do
        if curl --fail --silent --max-time 5 "${runtime_url}" \
            | "${PYTHON_BIN}" -c '
import json
import sys

payload = json.load(sys.stdin)
states = {item.get("kind"): item.get("phase") for item in payload.get("runtimes", [])}
raise SystemExit(0 if states.get("chat") == states.get("embedding") == "ready" else 1)
' \
        then
            log "Chat and Embedding runtimes are ready"
            return
        fi
        sleep 1
    done
    tail -n 120 "${LOG_FILE}" 2>/dev/null || true
    fail "Model loading did not finish within 900 seconds"
}

status() {
    if node_running; then
        log "Inference node PID $(<"${PID_FILE}") is running"
    else
        log "Inference node is stopped"
    fi
    local base_url="http://127.0.0.1:${REMOTE_TELEMETRY_PORT}"
    curl --fail --silent --show-error --max-time 10 "${base_url}/runtime/software" || true
    echo
    curl --fail --silent --show-error --max-time 10 "${base_url}/runtime/rocm" || true
    echo
    curl --fail --silent --show-error --max-time 10 "${base_url}/runtimes" || true
    echo
}

bootstrap() {
    prepare_host
    doctor
    prepare_python
    build_llama
    download_models
    configure_profiles
    stop_node
    start_node
    wait_ready
    status
}

case "${COMMAND}" in
    prepare-host) prepare_host ;;
    bootstrap) bootstrap ;;
    up) start_node; wait_ready; status ;;
    down) stop_node ;;
    restart) stop_node; start_node; wait_ready; status ;;
    status) status ;;
    doctor) doctor ;;
    logs) tail -n 200 "${LOG_FILE}" 2>/dev/null || true ;;
    models) download_models; configure_profiles ;;
    build-llama) build_llama ;;
    *) fail "Unsupported command: ${COMMAND}" ;;
esac
