#!/usr/bin/env bash

set -euo pipefail

base_url="${INFERENCE_CONTROL_BASE_URL:-http://127.0.0.1:18004}"
export NO_PROXY="${NO_PROXY:+${NO_PROXY},}127.0.0.1,localhost"
export no_proxy="${no_proxy:+${no_proxy},}127.0.0.1,localhost"

printf '=== AMD llama.cpp implementation ===\n'
curl --fail --silent --show-error "${base_url}/runtime/llama" |
  jq '{active, display_name: .active_build.display_name, custom_kernels: .active_build.custom_kernels, build_options: .active_build.build_options}'

printf '\n=== Radeon and ROCm telemetry ===\n'
curl --fail --silent --show-error "${base_url}/runtime/rocm" |
  jq '{rocm_version, hip_version, torch_version, devices: [.devices[] | {name, architecture, total_vram_gib: (.total_memory_bytes / 1073741824 | floor), used_vram_gib: (.used_memory_bytes / 1073741824 | floor), gpu_utilization_percent}]}'

printf '\n=== Live inference slots ===\n'
curl --fail --silent --show-error "${base_url}/slots" |
  jq '[.[] | {slot: .id, context_tokens: .n_ctx, speculative_decoding: .speculative, processing: .is_processing}]'
