from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import time
from typing import Any

from agent_factory.agent_runtime_bridge.dependencies import ensure_dependencies
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.gateway import ToolApprovalDecision
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE, ToolOutputStore
from agent_factory.tooling.providers import PackageToolProvider, ToolProviderContext
from agent_factory.tooling.spec import ToolRiskResult, ToolSpec


PACKAGE_ROOT = Path("/package")
ARTIFACTS_ROOT = Path("/artifacts")
RUNTIME_ROOT = Path("/runtime")
WORKDIR_ROOT = Path("/workdir")


def main() -> int:
    try:
        request = _read_request()
        result = _run_probe(request)
    except Exception as exc:
        result = {
            "status": "failed",
            "phase": "probe_runner",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")
    return 0 if result.get("status") == "completed" else 1


def _read_request() -> dict[str, Any]:
    raw = sys.stdin.read()
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("probe request must be a JSON object")
    return payload


def _run_probe(request: dict[str, Any]) -> dict[str, Any]:
    started_at = time.monotonic()
    tool_id = str(request.get("tool_id") or "").strip()
    arguments = request.get("arguments") if isinstance(request.get("arguments"), dict) else {}
    if not tool_id:
        raise ValueError("tool_id is required")
    dependency_report = ensure_dependencies(PACKAGE_ROOT, ARTIFACTS_ROOT, runtime_root=RUNTIME_ROOT)
    if dependency_report.get("status") == "failed":
        return {
            "status": "failed",
            "phase": "sandbox_init",
            "tool_id": tool_id,
            "arguments": arguments,
            "dependency_report": dependency_report,
            "observation": {},
            "captured_stdout": "",
            "captured_stderr": "",
            "duration_ms": _duration_ms(started_at),
            "errors": ["sandbox dependency initialization failed"],
        }
    discovery = PackageToolProvider().discover(ToolProviderContext(package_root=PACKAGE_ROOT))
    specs = {spec.id: spec for spec in discovery.tool_specs}
    spec = specs.get(tool_id)
    if spec is None:
        return {
            "status": "failed",
            "phase": "tool_discovery",
            "tool_id": tool_id,
            "arguments": arguments,
            "dependency_report": dependency_report,
            "diagnostics": [_json_safe(item) for item in discovery.diagnostics],
            "observation": {},
            "captured_stdout": "",
            "captured_stderr": "",
            "duration_ms": _duration_ms(started_at),
            "errors": [f"package tool is not available: {tool_id}"],
        }
    try:
        compiler = ToolCompiler(
            package_root=PACKAGE_ROOT,
            resources=_probe_resources(),
            approval_handler=_approval_handler,
        )
        tool = compiler.compile(spec)
    except Exception as exc:
        return {
            "status": "failed",
            "phase": "tool_compile",
            "tool_id": tool_id,
            "arguments": arguments,
            "dependency_report": dependency_report,
            "diagnostics": [_json_safe(item) for item in discovery.diagnostics],
            "observation": {},
            "captured_stdout": "",
            "captured_stderr": "",
            "duration_ms": _duration_ms(started_at),
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            observation = tool.invoke(arguments)
    except Exception as exc:
        return {
            "status": "failed",
            "phase": "tool_execution",
            "tool_id": tool_id,
            "arguments": arguments,
            "dependency_report": dependency_report,
            "diagnostics": [_json_safe(item) for item in discovery.diagnostics],
            "observation": {},
            "captured_stdout": stdout.getvalue(),
            "captured_stderr": stderr.getvalue(),
            "duration_ms": _duration_ms(started_at),
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    observation_payload = observation if isinstance(observation, dict) else {"status": "invalid_output", "message": str(observation)}
    return {
        "status": "completed" if observation_payload.get("status") == "completed" else "failed",
        "phase": "tool_execution",
        "tool_id": tool_id,
        "arguments": arguments,
        "dependency_report": dependency_report,
        "diagnostics": [_json_safe(item) for item in discovery.diagnostics],
        "observation": observation_payload,
        "captured_stdout": stdout.getvalue(),
        "captured_stderr": stderr.getvalue(),
        "duration_ms": _duration_ms(started_at),
        "errors": [],
    }


def _probe_resources() -> dict[str, Any]:
    return {
        "package_root": str(PACKAGE_ROOT),
        "runtime_root": str(RUNTIME_ROOT),
        "artifacts_root": str(ARTIFACTS_ROOT),
        "workdir_root": str(WORKDIR_ROOT),
        "workspace_root": str(PACKAGE_ROOT),
        TOOL_OUTPUT_STORE_RESOURCE: ToolOutputStore(RUNTIME_ROOT / "tool_outputs"),
    }


def _approval_handler(spec: ToolSpec, arguments: dict[str, Any], risk: ToolRiskResult) -> ToolApprovalDecision:
    del spec, arguments, risk
    return ToolApprovalDecision(action="approve")


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _duration_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


if __name__ == "__main__":
    raise SystemExit(main())
