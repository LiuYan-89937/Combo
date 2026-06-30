#!/usr/bin/env bash
# Configure and verify the FastAgentFactory web frontend environment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/runtime_env.sh"

web_require_project_root
cd "${PROJECT_ROOT}"

echo "FastAgentFactory Web Frontend Environment Check"
echo "=================================================="
echo ""

echo "1. Project root"
echo "   ${PROJECT_ROOT}"
echo ""

echo "2. Python backend dependencies"
web_sync_python_dependencies
"${PYTHON_BIN}" --version
echo ""

echo "3. Frontend dependencies"
web_sync_frontend_dependencies
node --version
npm --version
echo ""

echo "4. Docker runtime image"
web_ensure_runtime_image
echo ""

echo "5. Port status"
web_print_port_status 8000
web_print_port_status 3000
echo ""

echo "6. Critical files"
FILES=(
    "pyproject.toml"
    "uv.lock"
    "docker/agent-runtime/Dockerfile"
    "web_frontend/backend/event_api_server.py"
    "web_frontend/frontend/package.json"
    "web_frontend/frontend/src/main.ts"
    "web_frontend/frontend/src/App.vue"
    "web_frontend/frontend/src/style.css"
)

for file in "${FILES[@]}"; do
    if [[ -f "${file}" ]]; then
        echo "   OK ${file}"
    else
        echo "   MISSING ${file}"
        exit 1
    fi
done

echo ""
echo "=================================================="
echo "Environment is ready."
echo ""
echo "Start all services:"
echo "  ./web_frontend/start.sh"
echo ""
echo "Or start separately:"
echo "  ./web_frontend/start_backend.sh"
echo "  cd web_frontend/frontend && npm run dev"
