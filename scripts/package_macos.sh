#!/usr/bin/env bash
#
# Build a self-contained macOS application and create a verified ad-hoc-signed DMG.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAURI_DIR="${PROJECT_ROOT}/src-tauri"
CONFIG_PATH="${TAURI_DIR}/tauri.conf.json"
PYTHON_RUNTIME="${TAURI_DIR}/resources/python/bin/python3"
FRONTEND_DIR="${PROJECT_ROOT}/web_frontend/frontend"
DEFAULT_UPDATER_KEY="${HOME}/.combo/updater/combo.key"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

[[ "$(uname -s)" == "Darwin" ]] || fail "This script must run on macOS."

for command_name in python3 npm cargo file codesign hdiutil otool shasum; do
    require_command "${command_name}"
done

[[ -f "${CONFIG_PATH}" ]] || fail "Tauri configuration not found: ${CONFIG_PATH}"
[[ -f "${FRONTEND_DIR}/package-lock.json" ]] || fail "Frontend lockfile is required."
BUILD_UPDATER_ARTIFACTS=true
if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" && -f "${DEFAULT_UPDATER_KEY}" ]]; then
    export TAURI_SIGNING_PRIVATE_KEY="${DEFAULT_UPDATER_KEY}"
fi
if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
    BUILD_UPDATER_ARTIFACTS=false
    echo "Updater signing key is unavailable; building the DMG without updater artifacts."
else
    export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}"
fi

if ! cargo tauri --version >/dev/null 2>&1; then
    echo "Installing Tauri CLI 2..."
    cargo install tauri-cli --version '^2.0.0' --locked
fi
cargo tauri --version >/dev/null 2>&1 || fail "Tauri CLI is unavailable after installation."

IFS=$'\t' read -r PRODUCT_NAME PRODUCT_VERSION < <(
    python3 - "${CONFIG_PATH}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as config_file:
    config = json.load(config_file)
print(config["productName"], config["version"], sep="\t")
PY
)

HOST_ARCH="$(uname -m)"
case "${HOST_ARCH}" in
    arm64)
        EXPECTED_PYTHON_ARCH="arm64"
        DMG_ARCH="aarch64"
        RELEASE_ARCH="aarch64"
        ;;
    *)
        fail "Combo macOS packages support Apple Silicon only; current host: ${HOST_ARCH}"
        ;;
esac

echo "Preparing frontend dependencies..."
npm --prefix "${FRONTEND_DIR}" ci

echo "Preparing bundled Python runtime..."
python3 "${PROJECT_ROOT}/scripts/bundle_python.py"
[[ -x "${PYTHON_RUNTIME}" ]] || fail "Bundled Python executable not found: ${PYTHON_RUNTIME}"
"${PYTHON_RUNTIME}" "${PROJECT_ROOT}/scripts/generate_icons.py"

PYTHON_FILE_INFO="$(file "${PYTHON_RUNTIME}")"
if [[ "${PYTHON_FILE_INFO}" != *"${EXPECTED_PYTHON_ARCH}"* ]]; then
    fail "Bundled Python architecture does not match ${HOST_ARCH}: ${PYTHON_FILE_INFO}"
fi

echo "Building macOS application..."
(
    cd "${TAURI_DIR}"
    if [[ "${BUILD_UPDATER_ARTIFACTS}" == true ]]; then
        cargo tauri build --bundles app
    else
        cargo tauri build --bundles app --config '{"bundle":{"createUpdaterArtifacts":false}}'
    fi
)

APP_PATH="${TAURI_DIR}/target/release/bundle/macos/${PRODUCT_NAME}.app"
[[ -d "${APP_PATH}" ]] || fail "Application bundle not found: ${APP_PATH}"

APP_EXECUTABLE_NAME="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "${APP_PATH}/Contents/Info.plist")"
APP_EXECUTABLE="${APP_PATH}/Contents/MacOS/${APP_EXECUTABLE_NAME}"
[[ -x "${APP_EXECUTABLE}" ]] || fail "Application executable not found: ${APP_EXECUTABLE}"

INVALID_DYNAMIC_LIBRARIES="$(
    otool -L "${APP_EXECUTABLE}" \
        | tail -n +2 \
        | awk '{ print $1 }' \
        | grep -Ev '^(/System/Library/|/usr/lib/|@executable_path/|@loader_path/|@rpath/)' \
        || true
)"
if [[ -n "${INVALID_DYNAMIC_LIBRARIES}" ]]; then
    fail "Application links to non-system libraries outside its bundle:${INVALID_DYNAMIC_LIBRARIES//$'\n'/$'\n  '}"
fi

echo "Verifying application signature..."
codesign --verify --deep --strict "${APP_PATH}"

if [[ "${BUILD_UPDATER_ARTIFACTS}" == true ]]; then
    GENERATED_UPDATER_PATH="${APP_PATH}.tar.gz"
    GENERATED_UPDATER_SIGNATURE_PATH="${GENERATED_UPDATER_PATH}.sig"
    [[ -f "${GENERATED_UPDATER_PATH}" ]] || fail "Updater bundle not found: ${GENERATED_UPDATER_PATH}"
    [[ -f "${GENERATED_UPDATER_SIGNATURE_PATH}" ]] || fail "Updater signature not found: ${GENERATED_UPDATER_SIGNATURE_PATH}"

    UPDATER_DIR="$(dirname "${GENERATED_UPDATER_PATH}")"
    UPDATER_PATH="${UPDATER_DIR}/${PRODUCT_NAME}_${PRODUCT_VERSION}_${RELEASE_ARCH}.app.tar.gz"
    UPDATER_SIGNATURE_PATH="${UPDATER_PATH}.sig"
    mv -f "${GENERATED_UPDATER_PATH}" "${UPDATER_PATH}"
    mv -f "${GENERATED_UPDATER_SIGNATURE_PATH}" "${UPDATER_SIGNATURE_PATH}"
fi

DMG_DIR="${TAURI_DIR}/target/release/bundle/dmg"
DMG_PATH="${DMG_DIR}/${PRODUCT_NAME}_${PRODUCT_VERSION}_${DMG_ARCH}.dmg"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/combo-dmg.XXXXXX")"

cleanup() {
    rm -rf "${STAGING_DIR}"
}
trap cleanup EXIT

cp -R "${APP_PATH}" "${STAGING_DIR}/"
ln -s /Applications "${STAGING_DIR}/Applications"
mkdir -p "${DMG_DIR}"

echo "Creating disk image..."
hdiutil create \
    -volname "${PRODUCT_NAME}" \
    -srcfolder "${STAGING_DIR}" \
    -format UDZO \
    -ov \
    "${DMG_PATH}"

hdiutil verify "${DMG_PATH}"

echo
echo "Package created:"
echo "  ${DMG_PATH}"
shasum -a 256 "${DMG_PATH}"
if [[ "${BUILD_UPDATER_ARTIFACTS}" == true ]]; then
    echo "  ${UPDATER_PATH}"
    echo "  ${UPDATER_SIGNATURE_PATH}"
fi
