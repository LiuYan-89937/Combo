#!/usr/bin/env bash
# Build the macOS desktop application from repository sources.

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "${PROJECT_ROOT}/src-tauri"
cargo tauri build
