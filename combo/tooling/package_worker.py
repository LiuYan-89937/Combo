from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import sys
from typing import Any

from combo.tooling.envelope import is_tool_envelope, tool_envelope


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        package_root = Path(str(request["package_root"])).resolve()
        module_name, function_name = str(request["entrypoint"]).split(":", 1)
        module_path = package_root.joinpath(*module_name.split(".")).with_suffix(".py").resolve()
        if package_root not in module_path.parents or not module_path.is_file():
            raise ValueError("ToolPackage entrypoint resolves outside the package")
        spec = importlib.util.spec_from_file_location(
            f"combo_tool_package_{request['package_digest']}",
            module_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load ToolPackage entrypoint: {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(package_root))
        spec.loader.exec_module(module)
        entrypoint = getattr(module, function_name, None)
        if not callable(entrypoint):
            raise TypeError(f"ToolPackage entrypoint is not callable: {request['entrypoint']}")
        if request.get("operation") == "validate_import":
            response = {"validated": True}
        else:
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = entrypoint(dict(request.get("arguments") or {}), dict(request.get("context") or {}))
            if not isinstance(result, dict):
                raise TypeError("ToolPackage run(arguments, context) must return a JSON object")
            response = result if is_tool_envelope(result) else tool_envelope(
                result,
                evidence=_captured_output(stdout.getvalue(), stderr.getvalue()),
            )
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    except BaseException as exc:
        response = {
            "worker_error": {
                "type": type(exc).__name__,
                "message": str(exc),
            }
        }
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(encoded)
    return 0 if "worker_error" not in response else 1


def _captured_output(stdout: str, stderr: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    if stdout:
        output["stdout"] = stdout[-16_000:]
    if stderr:
        output["stderr"] = stderr[-16_000:]
    return {"tool_package_process": output} if output else {}


if __name__ == "__main__":
    raise SystemExit(main())
