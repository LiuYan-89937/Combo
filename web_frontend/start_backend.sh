#!/usr/bin/env bash
# Start only the FastAgentFactory web backend.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/runtime_env.sh"

web_require_project_root
cd "${PROJECT_ROOT}"

echo "FastAgentFactory Web Backend"
echo ""
echo "This starts the FastAPI Event/API bridge only."
echo "Run the frontend separately with:"
echo "  cd web_frontend/frontend && npm run dev"
echo ""

web_sync_python_dependencies
web_ensure_runtime_image

echo ""
echo "Starting Event/API bridge on http://localhost:8000"
echo "SSE endpoint: http://localhost:8000/events"
echo "Health check: http://localhost:8000/health"
echo ""

exec "${PYTHON_BIN}" web_frontend/backend/event_api_server.py
