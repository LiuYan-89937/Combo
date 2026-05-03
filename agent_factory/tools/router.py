from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.package import PackageLoader
from agent_factory.specs import GeneratedToolDraftSpec, RiskLevel


class ToolInvocation(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    invocation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False
    dry_run: bool = False


class ToolResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    invocation_id: str
    tool_id: str
    status: Literal["completed", "failed", "interrupted", "skipped"]
    output: dict[str, Any] | None = None
    error: str | None = None
    interrupt_type: str | None = None
    approval_required: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "completed"


class ToolRouter:
    def __init__(self, package_path: str | Path, *, loader: PackageLoader | None = None) -> None:
        self.package_path = Path(package_path)
        self.loader = loader or PackageLoader()
        package = self.loader.load_full_package(self.package_path)
        self.tools_spec = package.tools
        self.tools: dict[str, GeneratedToolDraftSpec] = {
            tool.tool_id: tool for tool in package.generated_tools
        }

    def route(self, invocation: ToolInvocation) -> ToolResult | GeneratedToolDraftSpec:
        tool = self.tools.get(invocation.tool_id)
        if tool is None:
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status="failed",
                error=f"Unknown tool: {invocation.tool_id}",
            )
        if tool.status == "draft" and not self.tools_spec.allow_draft_execution:
            if _safe_mock_tool(tool) and _tool_tests_passed(self.package_path, tool.tool_id):
                return tool
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status="interrupted",
                interrupt_type="human_confirm",
                approval_required=True,
                error="Draft generated tool requires approval before execution.",
            )
        if _requires_confirmation(tool) and not invocation.approved:
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status="interrupted",
                interrupt_type="human_confirm",
                approval_required=True,
                error="Tool requires human confirmation.",
            )
        return tool


class ToolExecutor:
    def execute(
        self,
        package_path: str | Path,
        tool: GeneratedToolDraftSpec,
        invocation: ToolInvocation,
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> ToolResult:
        implementation_path = Path(package_path) / tool.implementation.path
        if not implementation_path.exists():
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status="failed",
                error=f"Tool implementation not found: {tool.implementation.path}",
            )
        try:
            module = _load_module(implementation_path)
            func = getattr(module, tool.implementation.entrypoint)
            output = func(invocation.arguments, runtime_context or {})
            if not isinstance(output, dict):
                return ToolResult(
                    invocation_id=invocation.invocation_id,
                    tool_id=invocation.tool_id,
                    status="failed",
                    error="Tool output must be a mapping.",
                )
            if output.get("status") == "not_implemented":
                return ToolResult(
                    invocation_id=invocation.invocation_id,
                    tool_id=invocation.tool_id,
                    status="failed",
                    output=output,
                    error="Generated tool is still a placeholder implementation.",
                )
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status="completed",
                output=output,
                approval_required=_requires_confirmation(tool),
            )
        except Exception as error:
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status="failed",
                error=str(error),
            )


def _load_module(path: Path) -> Any:
    module_dir = str(path.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location(f"agent_factory_generated_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _requires_confirmation(tool: GeneratedToolDraftSpec) -> bool:
    return tool.approval.required or tool.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}


def _safe_mock_tool(tool: GeneratedToolDraftSpec) -> bool:
    return tool.risk_level == RiskLevel.LOW and not tool.approval.required


def _tool_tests_passed(package_path: Path, tool_id: str | None = None) -> bool:
    report_path = package_path / "generated" / "reports" / "tool_tests.json"
    if not report_path.exists():
        return False
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if tool_id:
        per_tool = data.get("per_tool_status")
        if isinstance(per_tool, dict) and tool_id in per_tool:
            return per_tool.get(tool_id) == "passed"
    return data.get("status") == "passed"
