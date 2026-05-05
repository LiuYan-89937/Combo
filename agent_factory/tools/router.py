from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field

from agent_factory.factory.web_search import FactoryWebSearchService
from agent_factory.core.types import JsonDumpMixin
from agent_factory.package import PackageLoader
from agent_factory.specs import BuiltinCapabilitySpec, GeneratedToolDraftSpec, RiskLevel
from agent_factory.tools.web import execute_browser_fetch, execute_web_search


class ToolInvocation(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    invocation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    tool_call_id: str | None = None
    tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False
    dry_run: bool = False


class ToolResultEnvelope(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    invocation_id: str
    tool_call_id: str | None = None
    tool_id: str
    status: Literal["completed", "failed", "interrupted", "needs_configuration", "blocked"]
    output: dict[str, Any] | None = None
    error: str | None = None
    observation_summary: str | None = None
    raw_output_ref: str | None = None
    redaction_report: dict[str, Any] = Field(default_factory=dict)
    interrupt_type: str | None = None
    approval_required: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "completed"


ToolResult = ToolResultEnvelope


class PolicyDecision(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    status: Literal["allow", "interrupt", "block"] = "allow"
    reason: str | None = None
    approval_required: bool = False


class PolicyEngine:
    """Central runtime policy gate for generated and builtin tools."""

    def evaluate(
        self,
        invocation: ToolInvocation,
        tool: GeneratedToolDraftSpec | BuiltinCapabilitySpec,
    ) -> PolicyDecision:
        if isinstance(tool, BuiltinCapabilitySpec):
            if tool.approval_required and not invocation.approved:
                return PolicyDecision(
                    status="interrupt",
                    reason="Builtin capability requires human confirmation.",
                    approval_required=True,
                )
            return PolicyDecision()
        if _requires_confirmation(tool) and not invocation.approved:
            return PolicyDecision(
                status="interrupt",
                reason="Tool requires human confirmation.",
                approval_required=True,
            )
        return PolicyDecision()


class ToolRouter:
    def __init__(self, package_path: str | Path, *, loader: PackageLoader | None = None) -> None:
        self.package_path = Path(package_path)
        self.loader = loader or PackageLoader()
        package = self.loader.load_full_package(self.package_path)
        self.tools_spec = package.tools
        self.tools: dict[str, GeneratedToolDraftSpec] = {
            tool.tool_id: tool for tool in package.generated_tools
        }
        self.builtin_capabilities: dict[str, BuiltinCapabilitySpec] = {
            capability.id: capability
            for capability in package.tools.builtin_capabilities
            if capability.exposure == "exposed"
        }
        self.policy_engine = PolicyEngine()

    def route(self, invocation: ToolInvocation) -> ToolResultEnvelope | GeneratedToolDraftSpec | BuiltinCapabilitySpec:
        tool = self.tools.get(invocation.tool_id)
        if tool is None:
            capability = self.builtin_capabilities.get(invocation.tool_id)
            if capability is not None:
                decision = self.policy_engine.evaluate(invocation, capability)
                if decision.status == "interrupt":
                    return _policy_interrupt(invocation, decision)
                if decision.status == "block":
                    return _policy_block(invocation, decision)
                return capability
            return ToolResultEnvelope(
                invocation_id=invocation.invocation_id,
                tool_call_id=invocation.tool_call_id,
                tool_id=invocation.tool_id,
                status="blocked",
                error=f"Unknown tool: {invocation.tool_id}",
                observation_summary=f"Tool blocked: unknown tool {invocation.tool_id}.",
            )
        if tool.status == "draft" and not self.tools_spec.allow_draft_execution:
            if _safe_mock_tool(tool) and _tool_tests_passed(self.package_path, tool.tool_id):
                return tool
            if invocation.approved:
                if _tool_tests_passed(self.package_path, tool.tool_id):
                    return tool
                return _policy_block(
                    invocation,
                    PolicyDecision(
                        status="block",
                        reason=(
                            "Draft generated tool cannot execute because its generated tests "
                            "have not passed."
                        ),
                    ),
                )
            return _policy_interrupt(
                invocation,
                PolicyDecision(
                    status="interrupt",
                    reason="Draft generated tool requires approval before execution.",
                    approval_required=True,
                ),
            )
        decision = self.policy_engine.evaluate(invocation, tool)
        if decision.status == "interrupt":
            return _policy_interrupt(invocation, decision)
        if decision.status == "block":
            return _policy_block(invocation, decision)
        return tool


class ToolExecutor:
    def __init__(
        self,
        *,
        web_search_service: FactoryWebSearchService | None = None,
        env_file: str | Path | None = None,
    ) -> None:
        self.web_search_service = web_search_service
        self.env_file = Path(env_file) if env_file is not None else None

    def execute(
        self,
        package_path: str | Path,
        tool: GeneratedToolDraftSpec | BuiltinCapabilitySpec,
        invocation: ToolInvocation,
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> ToolResultEnvelope:
        if isinstance(tool, BuiltinCapabilitySpec):
            return self._execute_builtin(tool, invocation)
        implementation_path = Path(package_path) / tool.implementation.path
        if not implementation_path.exists():
            return ToolResultEnvelope(
                invocation_id=invocation.invocation_id,
                tool_call_id=invocation.tool_call_id,
                tool_id=invocation.tool_id,
                status="failed",
                error=f"Tool implementation not found: {tool.implementation.path}",
                observation_summary=f"Tool implementation not found: {tool.implementation.path}",
            )
        try:
            module = _load_module(implementation_path)
            func = getattr(module, tool.implementation.entrypoint)
            output = func(invocation.arguments, runtime_context or {})
            if not isinstance(output, dict):
                return ToolResultEnvelope(
                    invocation_id=invocation.invocation_id,
                    tool_call_id=invocation.tool_call_id,
                    tool_id=invocation.tool_id,
                    status="failed",
                    error="Tool output must be a mapping.",
                    observation_summary="Tool output must be a mapping.",
                )
            if output.get("status") == "needs_configuration":
                return ToolResultEnvelope(
                    invocation_id=invocation.invocation_id,
                    tool_call_id=invocation.tool_call_id,
                    tool_id=invocation.tool_id,
                    status="needs_configuration",
                    output=output,
                    approval_required=_requires_confirmation(tool),
                    observation_summary=json.dumps(output, ensure_ascii=False),
                    redaction_report={"redacted": True},
                )
            if output.get("status") == "not_implemented":
                return ToolResultEnvelope(
                    invocation_id=invocation.invocation_id,
                    tool_call_id=invocation.tool_call_id,
                    tool_id=invocation.tool_id,
                    status="failed",
                    output=output,
                    error="Generated tool is still a placeholder implementation.",
                    observation_summary="Generated tool is still a placeholder implementation.",
                )
            return ToolResultEnvelope(
                invocation_id=invocation.invocation_id,
                tool_call_id=invocation.tool_call_id,
                tool_id=invocation.tool_id,
                status="completed",
                output=output,
                approval_required=_requires_confirmation(tool),
                observation_summary=json.dumps(output, ensure_ascii=False),
                redaction_report={"redacted": True},
            )
        except Exception as error:
            return ToolResultEnvelope(
                invocation_id=invocation.invocation_id,
                tool_call_id=invocation.tool_call_id,
                tool_id=invocation.tool_id,
                status="failed",
                error=str(error),
                observation_summary=f"Tool failed: {type(error).__name__}: {error}",
            )

    def _execute_builtin(
        self,
        capability: BuiltinCapabilitySpec,
        invocation: ToolInvocation,
    ) -> ToolResultEnvelope:
        try:
            if capability.type == "web_search":
                output = execute_web_search(
                    capability,
                    invocation.arguments,
                    env_file=self.env_file,
                    service=self.web_search_service,
                )
            elif capability.type == "browser_fetch":
                output = execute_browser_fetch(
                    capability,
                    invocation.arguments,
                    env_file=self.env_file,
                )
            else:
                raise RuntimeError(f"Unsupported builtin capability: {capability.type}")
            return ToolResultEnvelope(
                invocation_id=invocation.invocation_id,
                tool_call_id=invocation.tool_call_id,
                tool_id=invocation.tool_id,
                status="completed",
                output=output,
                approval_required=capability.approval_required,
                observation_summary=json.dumps(output, ensure_ascii=False),
                redaction_report={"redacted": True},
            )
        except Exception as error:
            return ToolResultEnvelope(
                invocation_id=invocation.invocation_id,
                tool_call_id=invocation.tool_call_id,
                tool_id=invocation.tool_id,
                status="failed",
                error=str(error),
                observation_summary=f"Builtin capability failed: {type(error).__name__}: {error}",
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


def _policy_interrupt(invocation: ToolInvocation, decision: PolicyDecision) -> ToolResultEnvelope:
    return ToolResultEnvelope(
        invocation_id=invocation.invocation_id,
        tool_call_id=invocation.tool_call_id,
        tool_id=invocation.tool_id,
        status="interrupted",
        interrupt_type="human_confirm",
        approval_required=decision.approval_required,
        error=decision.reason,
        observation_summary=decision.reason,
    )


def _policy_block(invocation: ToolInvocation, decision: PolicyDecision) -> ToolResultEnvelope:
    return ToolResultEnvelope(
        invocation_id=invocation.invocation_id,
        tool_call_id=invocation.tool_call_id,
        tool_id=invocation.tool_id,
        status="blocked",
        error=decision.reason,
        observation_summary=decision.reason,
    )


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
