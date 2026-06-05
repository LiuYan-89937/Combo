"""Smoke test for manufactured AgentPackages.

Runs the agent in-process with task_model to verify it produces useful output.
Uses the exact same runtime path as Docker container execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.models import get_task_model, get_compression_model
from agent_factory.package_runtime import register_package_patterns
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.model_operations import ModelOperationService
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig
from agent_factory.runtime_protocol.completion import runtime_completed


SMOKE_TEST_TIMEOUT_SECONDS = 30
DEFAULT_TEST_INPUT = "Hello, please introduce yourself and demonstrate your capabilities."


@dataclass(frozen=True, slots=True)
class SmokeTestResult:
    passed: bool
    test_input: str
    final_answer: str | None = None
    tool_calls_observed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    quality_score: float = 0.0


def run_smoke_test(
    package_root: Path,
    *,
    test_input: str | None = None,
) -> SmokeTestResult:
    """Run the manufactured agent with task_model to verify it works.

    Uses the same runtime path as PackageRuntimeCore.ensure_compiled():
    - AgentPackageLoader → RuntimeBuildPlanner → AgentAssemblyCompiler → facade.run
    - model_operation_service replaced with task_model
    - checkpointer/store = memory (ephemeral)
    """
    root = Path(package_root).resolve()
    effective_input = test_input or _derive_test_input(root)

    # Check task_model availability
    task_model = get_task_model()
    if task_model is None:
        # Cannot run smoke test without a model — pass with warning
        return SmokeTestResult(
            passed=True,
            test_input=effective_input,
            errors=["smoke_test skipped: task_model not configured"],
        )

    # Load package (same path as runtime)
    package = AgentPackageLoader().load_path(root / "agent_package.json")

    # Build runtime (same path as PackageRuntimeCore.ensure_compiled)
    facade = RuntimeKernelFacade(
        checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
        memory_store_config=LangGraphStoreConfig(backend="memory"),
    )
    runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
        package,
        base_services=facade.instance.services,
    )

    # Register patterns and compile
    register_package_patterns(facade=facade, package=package, runtime_build=runtime_build)
    compiled = AgentAssemblyCompiler(facade=facade).compile(
        package.assembly_spec,
        runtime_build=runtime_build,
    )

    facade.instance.services.model_operation_service = ModelOperationService(role="task", model=task_model)

    # Run one turn
    try:
        final_state = facade.run(
            compiled,
            user_input=effective_input,
            session_config={"timeout_seconds": SMOKE_TEST_TIMEOUT_SECONDS},
        )
    except Exception as exc:
        return SmokeTestResult(
            passed=False,
            test_input=effective_input,
            errors=[f"Runtime crashed: {type(exc).__name__}: {exc}"],
        )

    # Analyze result
    if not runtime_completed(final_state):
        error_msg = getattr(final_state.execution, "last_error", None) or "Runtime did not complete"
        return SmokeTestResult(
            passed=False,
            test_input=effective_input,
            errors=[f"Runtime failed: {error_msg}"],
        )

    final_answer = getattr(final_state.conversation, "final_answer", None) or ""
    tool_calls = _extract_tool_calls(final_state)

    errors: list[str] = []
    if not final_answer.strip():
        errors.append("Agent produced no final_answer")

    # Quality scoring (optional, requires compression_model)
    quality_score = 0.5  # default neutral
    if final_answer.strip():
        quality_score = _score_quality(effective_input, final_answer)
        if quality_score < 0.3:
            errors.append(f"Output quality too low (score={quality_score:.2f}): response appears empty or irrelevant")

    passed = len(errors) == 0
    return SmokeTestResult(
        passed=passed,
        test_input=effective_input,
        final_answer=final_answer if final_answer.strip() else None,
        tool_calls_observed=tool_calls,
        errors=errors,
        quality_score=quality_score,
    )


def _derive_test_input(package_root: Path) -> str:
    """Derive a test input from the user's original manufacturing request."""
    request_path = package_root / ".factory" / "request.txt"
    if request_path.exists():
        request = request_path.read_text(encoding="utf-8").strip()
        if request:
            # Turn the manufacturing request into a usage request
            return f"Based on your capabilities, help me with: {request[:200]}"
    return DEFAULT_TEST_INPUT


def _extract_tool_calls(final_state: Any) -> list[str]:
    """Extract tool call names from the final state."""
    tool_calls: list[str] = []
    tools_state = getattr(final_state, "tools", None)
    if tools_state is None:
        return tool_calls
    results = getattr(tools_state, "tool_results", None) or []
    for result in results:
        if isinstance(result, dict):
            tool_id = result.get("tool_id") or result.get("name") or ""
            if tool_id:
                tool_calls.append(str(tool_id))
    return tool_calls


def _score_quality(test_input: str, final_answer: str) -> float:
    """Score the quality of the agent's response using compression_model."""
    model = get_compression_model()
    if model is None:
        # No scoring model available, give benefit of the doubt
        return 0.7 if len(final_answer.strip()) > 20 else 0.3

    try:
        response = model.invoke([
            SystemMessage(content=(
                "You are a quality evaluator. Score the agent's response from 0.0 to 1.0.\n"
                "0.0 = completely empty, irrelevant, or broken\n"
                "0.5 = generic/shallow but somewhat relevant\n"
                "1.0 = specific, actionable, and directly addresses the request\n"
                "Reply with ONLY a number between 0.0 and 1.0, nothing else."
            )),
            HumanMessage(content=f"User request: {test_input}\n\nAgent response: {final_answer[:1000]}"),
        ])
        score_text = str(response.content or "").strip()
        return max(0.0, min(1.0, float(score_text)))
    except Exception:
        # Scoring failed, use heuristic
        return 0.7 if len(final_answer.strip()) > 50 else 0.4
