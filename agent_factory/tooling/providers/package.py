from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_factory.tooling.providers.base import ToolProviderContext, ToolProviderResult, diagnostic
from agent_factory.tooling.spec import ToolSpec


class PackageToolProvider:
    provider_id = "package"

    def discover(self, context: ToolProviderContext) -> ToolProviderResult:
        if context.package_root is None:
            return ToolProviderResult(
                diagnostics=[diagnostic(self.provider_id, "warning", "package_root is not configured")]
            )
        package_root = context.package_root.resolve()
        tools_root = package_root / "tools"
        if not tools_root.exists():
            return ToolProviderResult()
        result = ToolProviderResult()
        for manifest_path in sorted(tools_root.glob("*/manifest.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                payload["entrypoint"] = normalize_python_entrypoint(str(payload.get("entrypoint") or ""))
                result.tool_specs.append(ToolSpec.model_validate(payload))
            except Exception as exc:
                result.diagnostics.append(
                    diagnostic(
                        self.provider_id,
                        "error",
                        "failed to load package tool manifest",
                        manifest_path=str(manifest_path),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return result


def normalize_python_entrypoint(entrypoint: str) -> str:
    if entrypoint.startswith(("python:", "python-import:", "mcp:")):
        return entrypoint
    if _looks_like_package_path(entrypoint):
        return f"python:{entrypoint}"
    return f"python-import:{entrypoint}"


def _looks_like_package_path(entrypoint: str) -> bool:
    target = entrypoint.rsplit(":", 1)[0] if ":" in entrypoint else entrypoint
    return target.endswith(".py") or "/" in target or target.startswith(".")
