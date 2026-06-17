from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from pydantic import BaseModel, ConfigDict

from agent_factory.create_agent.models import PackageToolProbeRecord
from agent_factory.create_agent.validation_state import package_fingerprint
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.models import get_task_model
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE, ToolOutputStore
from agent_factory.tooling.providers import PackageToolProvider, ToolProviderContext
from agent_factory.tooling.gateway import ToolApprovalDecision
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_PROBE_TOOL_ID = "create_agent_probe_tool"
PROBE_MODEL_TIMEOUT_SECONDS_ENV = "AGENTFACTORY_CREATE_AGENT_PROBE_MODEL_TIMEOUT_SECONDS"
DEFAULT_PROBE_MODEL_TIMEOUT_SECONDS = 60.0
PROBE_ARGUMENT_TIMEOUT_SECONDS_ENV = "AGENTFACTORY_CREATE_AGENT_PROBE_ARGUMENT_TIMEOUT_SECONDS"
DEFAULT_PROBE_ARGUMENT_TIMEOUT_SECONDS = 20.0
PROBE_EVALUATION_TIMEOUT_SECONDS_ENV = "AGENTFACTORY_CREATE_AGENT_PROBE_EVALUATION_TIMEOUT_SECONDS"
DEFAULT_PROBE_EVALUATION_TIMEOUT_SECONDS = 8.0


class PackageToolProbeEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    probe_kind: str = "unknown"
    goal_satisfied: bool | None = None
    tool_returned_business_output: bool = False
    only_error_handling_verified: bool = False


class PackageToolProbeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any]
    summary: str = ""


def build_create_agent_probe_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_PROBE_TOOL_ID,
        description=(
            "Inspect package-owned tools generated in this create-agent workspace, then probe one generated tool by "
            "executing it through ToolExecutionGateway. Prefer call with explicit arguments; prompt can be supplied "
            "for user-facing context and optional argument inference. Final validation requires a fresh success-path probe."
        ),
        entrypoint="agent_factory.create_agent.probe_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["inspect", "call"]},
                "tool_id": {"type": "string", "default": ""},
                "prompt": {
                    "type": "string",
                    "default": "",
                    "description": "Business user prompt used as context for the probe and optional argument inference.",
                },
                "tool_goal": {
                    "type": "string",
                    "default": "",
                    "description": "Optional target scenario the final probe answer should satisfy.",
                },
                "arguments": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Optional concrete package tool arguments. If omitted, a short task-model call may infer arguments from prompt and tool schema.",
                },
                "probe_kind": {
                    "type": "string",
                    "enum": ["auto", "success_path", "error_path"],
                    "default": "auto",
                    "description": "Declare whether this probe is intended to exercise a successful business path or an error path. Use auto if unsure.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "tools": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "probe": {"type": "object", "additionalProperties": True},
                "diagnostics": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            },
            "required": ["action", "tools", "probe", "diagnostics"],
            "additionalProperties": False,
        },
        resources={
            "workspace": "create_agent_workspace",
        },
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.probe_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    action = str(arguments.get("action") or "").strip()
    if action == "inspect":
        return _inspect(workspace)
    if action == "call":
        return _call(
            workspace,
            tool_id=str(arguments.get("tool_id") or "").strip(),
            prompt=str(arguments.get("prompt") or "").strip(),
            tool_goal=str(arguments.get("tool_goal") or "").strip(),
            arguments=arguments.get("arguments") if isinstance(arguments.get("arguments"), dict) else None,
            requested_probe_kind=str(arguments.get("probe_kind") or "auto").strip(),
        )
    raise ValueError(f"unsupported probe action: {action}")


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action == "inspect":
        return ToolRiskResult(action="allow", risk_level="low").model_dump(mode="json")
    if action == "call":
        return ToolRiskResult(
            action="allow",
            risk_level="low",
            reasons=["create-agent probe calls generated package tools through ToolExecutionGateway"],
        ).model_dump(mode="json")
    return ToolRiskResult(action="deny", risk_level="low", reasons=["unknown probe action"]).model_dump(mode="json")


def _inspect(workspace: CreateAgentWorkspace) -> dict[str, Any]:
    discovery = _discover(workspace)
    state = workspace.read_tool_probe_state()
    latest = state.latest_by_tool()
    tools = []
    current_digest = _package_digest(workspace.root)
    for spec in discovery.tool_specs:
        record = latest.get(spec.id)
        tools.append(
            {
                "tool_id": spec.id,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "risk_level": spec.risk_level,
                "last_probe": _probe_record_summary(record, current_digest=current_digest) if record else None,
            }
        )
    return tool_envelope(
        {
            "action": "inspect",
            "tools": tools,
            "probe": {
                "required": bool(tools),
                "current_package_digest": current_digest,
                "guidance": "Call each generated package tool once with realistic arguments before final validation. Prompt and tool_goal provide human-readable context.",
                "publish_gate": "A probe that only verifies error handling is not sufficient for publish readiness.",
                "input_mode": "direct_tool_execution_with_optional_prompt_to_arguments",
            },
            "diagnostics": [_diagnostic_payload(item) for item in discovery.diagnostics],
        },
        summary=f"Discovered {len(tools)} package tool(s) for probe.",
    )


def _call(
    workspace: CreateAgentWorkspace,
    *,
    tool_id: str,
    prompt: str,
    tool_goal: str,
    arguments: dict[str, Any] | None,
    requested_probe_kind: str,
) -> dict[str, Any]:
    if not tool_id:
        raise ValueError("tool_id is required for probe call")
    discovery = _discover(workspace)
    specs = {spec.id: spec for spec in discovery.tool_specs}
    spec = specs.get(tool_id)
    if spec is None:
        raise ValueError(f"package tool is not available for probe: {tool_id}")
    _emit_probe_progress(
        f"开始工具探测：目标工具 {tool_id}。",
        {"tool_id": tool_id, "prompt": prompt},
    )
    before = package_fingerprint(workspace.root)
    direct_probe = _run_direct_probe(
        workspace=workspace,
        spec=spec,
        prompt=prompt,
        tool_goal=tool_goal,
        arguments=arguments,
        requested_probe_kind=requested_probe_kind,
    )
    after = package_fingerprint(workspace.root)
    record = _record_from_direct_probe(
        workspace=workspace,
        spec=spec,
        tool_id=tool_id,
        prompt=prompt,
        tool_goal=tool_goal,
        direct_probe=direct_probe,
    )
    state = workspace.read_tool_probe_state()
    state.records.append(record)
    state = state.model_copy(update={"updated_at": datetime.now(UTC).isoformat()})
    workspace.write_tool_probe_state(state)
    changed_files = _changed_files(before, after)
    transcript = _probe_transcript(direct_probe=direct_probe, record=record)
    _emit_probe_progress(
        f"工具探测完成：{tool_id} -> {record.status}。",
        {
            "tool_id": tool_id,
            "status": record.status,
            "evaluation": record.evaluation,
            "transcript": transcript,
        },
    )
    return tool_envelope(
        {
            "action": "call",
            "tools": [_tool_summary(spec)],
            "probe": {
                "tool_id": tool_id,
                "status": record.status,
                "observation_status": record.observation_status,
                "execution_status": record.execution_status,
                "contract_status": record.contract_status,
                "message": record.message,
                "prompt": record.prompt,
                "tool_goal": record.tool_goal,
                "probe_kind": record.probe_kind,
                "goal_satisfied": record.goal_satisfied,
                "tool_returned_business_output": record.tool_returned_business_output,
                "only_error_handling_verified": record.only_error_handling_verified,
                "arguments": record.arguments,
                "tool_calls": record.tool_calls,
                "output_summary": record.output_summary,
                "observation_output": record.observation_output,
                "final_answer": record.final_answer,
                "summary": record.summary,
                "evaluator": record.evaluator,
                "evaluation": record.evaluation,
                "transcript": transcript,
                "errors": record.errors,
                "changed_files": changed_files,
                "package_digest": record.package_digest,
            },
            "diagnostics": [_diagnostic_payload(item) for item in discovery.diagnostics],
        },
        evidence={
            "package_tool_probe": {
                "tool_id": tool_id,
                "status": record.status,
                "changed_files": changed_files,
            }
        },
        summary=_probe_summary(record),
    )


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _discover(workspace: CreateAgentWorkspace):
    return PackageToolProvider().discover(ToolProviderContext(package_root=workspace.root))


def _run_direct_probe(
    *,
    workspace: CreateAgentWorkspace,
    spec: ToolSpec,
    prompt: str,
    tool_goal: str,
    arguments: dict[str, Any] | None,
    requested_probe_kind: str,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    resolved_arguments = dict(arguments or {})
    argument_summary = ""
    if not resolved_arguments:
        argument_result = _infer_probe_arguments(spec=spec, prompt=prompt, tool_goal=tool_goal)
        resolved_arguments = dict(argument_result.get("arguments") or {})
        argument_summary = str(argument_result.get("summary") or "")
        errors.extend(str(item) for item in argument_result.get("errors", []) if item)
    if not resolved_arguments and _schema_required_keys(spec.input_schema):
        errors.append("probe arguments are required but could not be inferred from prompt")
    _emit_probe_progress(
        f"工具探测输入：{spec.id} args={_one_line(json.dumps(resolved_arguments, ensure_ascii=False, sort_keys=True), 220)}",
        {"tool_id": spec.id, "arguments": resolved_arguments, "argument_summary": argument_summary},
    )
    try:
        compiler = ToolCompiler(
            package_root=workspace.root,
            resources=_probe_tool_resources(workspace),
            approval_handler=_probe_approval_handler,
        )
        tool = compiler.compile(spec)
    except Exception as exc:
        return {
            "prompt": prompt,
            "tool_goal": tool_goal,
            "requested_probe_kind": requested_probe_kind if requested_probe_kind in {"success_path", "error_path"} else "auto",
            "arguments": resolved_arguments,
            "status": "failed",
            "observation": {},
            "events": [],
            "errors": [*errors, f"package tool compile failed: {type(exc).__name__}: {exc}"],
        }
    try:
        observation = tool.invoke(resolved_arguments)
    except Exception as exc:
        return {
            "prompt": prompt,
            "tool_goal": tool_goal,
            "requested_probe_kind": requested_probe_kind if requested_probe_kind in {"success_path", "error_path"} else "auto",
            "arguments": resolved_arguments,
            "status": "failed",
            "observation": {},
            "events": [],
            "errors": [*errors, f"package tool execution raised: {type(exc).__name__}: {exc}"],
        }
    observation_payload = observation if isinstance(observation, dict) else {"status": "invalid_output", "message": str(observation)}
    events.append(
        {
            "event_type": "tool_completed" if observation_payload.get("status") == "completed" else "tool_failed",
            "tool_id": spec.id,
            "arguments": resolved_arguments,
            "observation": _json_preview(observation_payload, limit=8000),
        }
    )
    status = str(observation_payload.get("status") or "").strip()
    message = str(observation_payload.get("message") or "").strip()
    _emit_probe_progress(
        f"工具 observation：{spec.id} {status or '-'}" + (f" - {_one_line(message, 220)}" if message else ""),
        {"tool_id": spec.id, "status": status},
    )
    return {
        "prompt": prompt,
        "tool_goal": tool_goal,
        "requested_probe_kind": requested_probe_kind if requested_probe_kind in {"success_path", "error_path"} else "auto",
        "arguments": resolved_arguments,
        "status": "completed" if observation_payload.get("status") == "completed" and not errors else "failed",
        "observation": observation_payload,
        "events": _json_preview(events, limit=10000),
        "errors": errors,
    }


def _infer_probe_arguments(*, spec: ToolSpec, prompt: str, tool_goal: str) -> dict[str, Any]:
    if not prompt:
        return {"arguments": {}, "summary": "", "errors": ["probe arguments are missing and prompt is empty"]}
    model = get_task_model()
    if model is None:
        return {"arguments": {}, "summary": "", "errors": ["task_model is not configured for probe argument inference"]}
    model = _non_streaming_model(model)
    messages = [
        SystemMessage(
            content=(
                "Convert a business probe prompt into one JSON argument object for exactly one package tool. "
                "Return JSON only with fields arguments and summary. Do not execute the tool. "
                "Use the tool input_schema exactly; omit optional fields that are not needed."
            )
        ),
        HumanMessage(
            content=json.dumps(
                {
                    "tool": {
                        "id": spec.id,
                        "description": spec.description,
                        "input_schema": spec.input_schema,
                    },
                    "business_prompt": prompt,
                    "tool_goal": tool_goal,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        ),
    ]
    try:
        structured = model.with_structured_output(PackageToolProbeArguments, method="json_mode")
        result = _invoke_with_timeout(
            structured,
            messages,
            label="task_model probe argument inference",
            timeout=_probe_argument_timeout_seconds(),
        )
        parsed = result if isinstance(result, PackageToolProbeArguments) else PackageToolProbeArguments.model_validate(result)
        return {"arguments": parsed.arguments, "summary": parsed.summary, "errors": []}
    except Exception as exc:
        return {
            "arguments": {},
            "summary": "",
            "errors": [f"task_model probe argument inference failed: {type(exc).__name__}: {exc}"],
        }


def _probe_approval_handler(spec: ToolSpec, arguments: dict[str, Any], risk: ToolRiskResult) -> ToolApprovalDecision:
    del spec, arguments, risk
    return ToolApprovalDecision(action="approve")


def _probe_tool_resources(workspace: CreateAgentWorkspace) -> dict[str, Any]:
    runtime_root = workspace.factory_dir / "tool_probe_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    return {
        "package_root": str(workspace.root),
        "runtime_root": str(runtime_root),
        "workspace_root": str(workspace.root),
        TOOL_OUTPUT_STORE_RESOURCE: ToolOutputStore(workspace.tool_outputs_path),
    }


def _emit_probe_progress(message: str, payload: dict[str, Any] | None = None) -> None:
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer(
            {
                "type": "node_event",
                "payload": {
                    "event_type": "node_progress",
                    "node_id": "create_agent_probe_tool",
                    "node_label": "Package Tool Probe",
                    "node_kind": "tool_probe",
                    "message": message,
                    "payload": dict(payload or {}),
                },
            }
        )
    except Exception:
        return


def _probe_transcript(*, direct_probe: dict[str, Any], record: PackageToolProbeRecord) -> list[str]:
    lines = [f"业务测试 prompt：{direct_probe.get('prompt') or record.prompt}"]
    lines.append(
        "系统直接调用工具："
        f"{record.tool_id} args={_one_line(json.dumps(record.arguments, ensure_ascii=False, sort_keys=True), 240)}"
    )
    observation = direct_probe.get("observation") if isinstance(direct_probe.get("observation"), dict) else {}
    if observation:
        message = str(observation.get("message") or "").strip()
        output = observation.get("output")
        output_text = _one_line(json.dumps(output, ensure_ascii=False, sort_keys=True), 320) if output else ""
        lines.append(
            "工具返回："
            f"{record.tool_id} status={observation.get('status') or '-'}"
            + (f" message={_one_line(message, 180)}" if message else "")
            + (f" output={output_text}" if output_text else "")
        )
    evaluation = record.evaluation if isinstance(record.evaluation, dict) else {}
    if evaluation:
        lines.append(
            "小模型摘要："
            f"{_one_line(str(evaluation.get('summary') or ''), 240)}"
        )
    return lines


def _record_from_direct_probe(
    *,
    workspace: CreateAgentWorkspace,
    spec: ToolSpec,
    tool_id: str,
    prompt: str,
    tool_goal: str,
    direct_probe: dict[str, Any],
) -> PackageToolProbeRecord:
    observation = dict(direct_probe.get("observation") or {}) if isinstance(direct_probe.get("observation"), dict) else {}
    arguments = dict(direct_probe.get("arguments") or {}) if isinstance(direct_probe.get("arguments"), dict) else {}
    observation_status = str(observation.get("status") or "")
    execution_status = str(observation.get("execution_status") or "")
    contract_status = str(observation.get("contract_status") or "")
    errors = observation.get("errors")
    if not isinstance(errors, list):
        errors = []
    probe_errors = direct_probe.get("errors")
    if not isinstance(probe_errors, list):
        probe_errors = []
    output = observation.get("output")
    output_payload = output if isinstance(output, dict) else {}
    evaluation_payload = _evaluate_probe_observation(
        spec=spec,
        prompt=prompt,
        tool_goal=tool_goal,
        direct_probe=direct_probe,
    )
    probe_kind = _normalized_probe_kind(
        requested=direct_probe.get("requested_probe_kind"),
        evaluation=evaluation_payload,
        observation=observation,
        output_payload=output_payload,
    )
    tool_returned_business_output = _tool_returned_business_output(
        evaluation=evaluation_payload,
        output_payload=output_payload,
    )
    only_error_handling_verified = _only_error_handling_verified(
        evaluation=evaluation_payload,
        probe_kind=probe_kind,
        output_payload=output_payload,
        observation=observation,
    )
    evaluator = str(evaluation_payload.get("evaluator") or "")
    summary = str(evaluation_payload.get("summary") or "")
    goal_satisfied = evaluation_payload.get("goal_satisfied")
    goal_satisfied_value = goal_satisfied if isinstance(goal_satisfied, bool) else None
    final_answer = _probe_final_answer(spec=spec, observation=observation, summary=summary)
    tool_was_called = bool(observation)
    contract_passed = (
        tool_was_called
        and observation_status == "completed"
        and (not execution_status or execution_status == "completed")
        and (not contract_status or contract_status == "valid")
        and bool(final_answer)
    )
    return PackageToolProbeRecord(
        tool_id=tool_id,
        probe_kind=probe_kind,
        prompt=prompt,
        tool_goal=tool_goal,
        arguments=arguments,
        tool_calls=[
            {"tool_id": tool_id, "arguments": arguments}
        ],
        package_digest=_package_digest(workspace.root),
        status="passed" if contract_passed else "failed",
        observation_status=observation_status,
        execution_status=execution_status,
        contract_status=contract_status,
        message=str(observation.get("message") or "")[:500],
        output_summary=str(observation.get("output_summary") or "")[:500],
        observation_output=_probe_observation_output(output_payload=output_payload, direct_probe=direct_probe),
        final_answer=final_answer[:2000],
        summary=summary[:1000],
        goal_satisfied=goal_satisfied_value,
        tool_returned_business_output=tool_returned_business_output,
        only_error_handling_verified=only_error_handling_verified,
        evaluator=evaluator,
        evaluation=evaluation_payload,
        errors=[str(item)[:500] for item in [*probe_errors, *errors][:8]],
        probed_at=datetime.now(UTC).isoformat(),
    )


def _normalized_probe_kind(
    *,
    requested: Any,
    evaluation: dict[str, Any],
    observation: dict[str, Any],
    output_payload: dict[str, Any],
) -> str:
    value = str(evaluation.get("probe_kind") or "").strip()
    if value in {"success_path", "error_path"}:
        return value
    requested_value = str(requested or "").strip()
    if requested_value in {"success_path", "error_path"}:
        return requested_value
    return "error_path" if _output_contains_error(output_payload) or _observation_message_looks_error(observation) else "success_path"


def _tool_returned_business_output(*, evaluation: dict[str, Any], output_payload: dict[str, Any]) -> bool:
    value = evaluation.get("tool_returned_business_output")
    if isinstance(value, bool) and value and not _output_contains_error(output_payload):
        return True
    return _has_substantive_non_error_output(output_payload)


def _only_error_handling_verified(
    *,
    evaluation: dict[str, Any],
    probe_kind: str,
    output_payload: dict[str, Any],
    observation: dict[str, Any],
) -> bool:
    if _output_contains_error(output_payload) or _observation_message_looks_error(observation):
        return True
    value = evaluation.get("only_error_handling_verified")
    if isinstance(value, bool):
        return value
    if probe_kind == "error_path":
        return True
    return _output_contains_error(output_payload) or _observation_message_looks_error(observation)


def _output_contains_error(output_payload: dict[str, Any]) -> bool:
    for key, value in output_payload.items():
        key_text = str(key).lower()
        if key_text in {"error", "errors", "exception", "traceback"} and value:
            return True
    return False


def _observation_message_looks_error(observation: dict[str, Any]) -> bool:
    message = str(observation.get("message") or "").strip().lower()
    if not message:
        return False
    markers = ("error", "failed", "failure", "exception", "not found", "missing", "不存在", "失败", "错误")
    return any(marker in message for marker in markers)


def _has_substantive_non_error_output(output_payload: dict[str, Any]) -> bool:
    for key, value in output_payload.items():
        if str(key).lower() in {"error", "errors", "exception", "traceback"}:
            continue
        if value in ("", None, [], {}):
            continue
        return True
    return False


def _package_digest(root: Path) -> str:
    fingerprint = package_fingerprint(root)
    return sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _probe_observation_output(*, output_payload: dict[str, Any], direct_probe: dict[str, Any]) -> dict[str, Any]:
    if output_payload:
        return _json_preview(output_payload, limit=6000)
    return {
        "observation": _json_preview(direct_probe.get("observation", {}), limit=6000),
    }


def _probe_final_answer(*, spec: ToolSpec, observation: dict[str, Any], summary: str) -> str:
    output_summary = str(observation.get("output_summary") or "").strip()
    if output_summary:
        return output_summary
    output = observation.get("output") if isinstance(observation.get("output"), dict) else {}
    if output:
        return _one_line(json.dumps(output, ensure_ascii=False, sort_keys=True), 1800)
    if summary:
        return summary
    message = str(observation.get("message") or "").strip()
    return message or f"{spec.id} returned no user-facing output."


def _evaluate_probe_observation(
    *,
    spec: ToolSpec,
    prompt: str,
    tool_goal: str,
    direct_probe: dict[str, Any],
) -> dict[str, Any]:
    model = get_task_model()
    if model is None:
        return {
            "evaluator": "task_model",
            "evaluator_status": "not_configured",
            "summary": "Task model is not configured; direct tool observation is available for main-model review.",
        }
    observation = direct_probe.get("observation") if isinstance(direct_probe.get("observation"), dict) else {}
    evaluation_messages = [
        SystemMessage(
            content=(
                "You summarize a generated package tool probe from a direct ToolExecutionGateway observation. "
                "Return concise JSON only. The JSON must contain fields summary, probe_kind, goal_satisfied, "
                "tool_returned_business_output, and only_error_handling_verified. "
                "probe_kind must be success_path when the probe exercised the tool's intended successful business behavior, "
                "error_path when it only verified rejection/error handling, or unknown if unclear. "
                "The summary should say whether the final answer appears to satisfy the tool goal. "
                "If no tool goal is provided, summarize whether the final answer is useful for the business prompt."
            )
        ),
        HumanMessage(
            content=json.dumps(
                {
                    "tool": {
                        "id": spec.id,
                        "description": spec.description,
                        "input_schema": spec.input_schema,
                        "output_schema": spec.output_schema,
                    },
                    "business_prompt": prompt,
                    "tool_goal": tool_goal,
                    "arguments": direct_probe.get("arguments") if isinstance(direct_probe.get("arguments"), dict) else {},
                    "observation": _json_preview(observation, limit=12000),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        ),
    ]
    try:
        structured = model.with_structured_output(PackageToolProbeEvaluation, method="json_mode")
        result = _invoke_with_timeout(
            structured,
            evaluation_messages,
            label="task_model probe evaluation",
            timeout=_probe_evaluation_timeout_seconds(),
        )
        evaluation = result if isinstance(result, PackageToolProbeEvaluation) else PackageToolProbeEvaluation.model_validate(result)
        return {
            "evaluator": "task_model",
            "evaluator_status": "completed",
            **evaluation.model_dump(mode="json"),
        }
    except Exception as exc:
        return {
            "evaluator": "task_model",
            "evaluator_status": "failed",
            "summary": f"Task model probe summary failed and was skipped: {type(exc).__name__}: {exc}",
        }


def _probe_record_summary(record: PackageToolProbeRecord, *, current_digest: str) -> dict[str, Any]:
    return {
        "status": record.status,
        "stale": record.package_digest != current_digest,
        "probe_kind": record.probe_kind,
        "goal_satisfied": record.goal_satisfied,
        "tool_returned_business_output": record.tool_returned_business_output,
        "only_error_handling_verified": record.only_error_handling_verified,
        "observation_status": record.observation_status,
        "contract_status": record.contract_status,
        "message": record.message,
        "output_summary": record.output_summary,
        "arguments": record.arguments,
        "final_answer": record.final_answer,
        "summary": record.summary,
        "evaluator": record.evaluator,
        "evaluation": record.evaluation,
        "probed_at": record.probed_at,
    }


def _non_streaming_model(model: Any) -> Any:
    if hasattr(model, "model_copy"):
        try:
            return model.model_copy(update={"streaming": False})
        except Exception:
            pass
    return model


def _invoke_with_timeout(runnable: Any, input_value: Any, *, label: str, timeout: float | None = None) -> Any:
    timeout = timeout or _probe_model_timeout_seconds()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(runnable.invoke, input_value)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(f"{label} timed out after {timeout:g}s") from exc
    finally:
        if future.done():
            executor.shutdown(wait=False, cancel_futures=True)


def _probe_model_timeout_seconds() -> float:
    value = os.getenv(PROBE_MODEL_TIMEOUT_SECONDS_ENV)
    if value:
        try:
            parsed = float(value)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return DEFAULT_PROBE_MODEL_TIMEOUT_SECONDS


def _probe_argument_timeout_seconds() -> float:
    return _positive_float_env(PROBE_ARGUMENT_TIMEOUT_SECONDS_ENV, DEFAULT_PROBE_ARGUMENT_TIMEOUT_SECONDS)


def _probe_evaluation_timeout_seconds() -> float:
    return _positive_float_env(PROBE_EVALUATION_TIMEOUT_SECONDS_ENV, DEFAULT_PROBE_EVALUATION_TIMEOUT_SECONDS)


def _positive_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value:
        try:
            parsed = float(value)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return default


def _schema_required_keys(schema: dict[str, Any]) -> set[str]:
    required = schema.get("required") if isinstance(schema, dict) else []
    return {str(item) for item in required or [] if str(item)}


def _tool_summary(spec: ToolSpec) -> dict[str, Any]:
    return {
        "tool_id": spec.id,
        "description": spec.description,
        "input_schema": spec.input_schema,
        "risk_level": spec.risk_level,
    }


def _diagnostic_payload(item: Any) -> dict[str, Any]:
    return item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def _probe_summary(record: PackageToolProbeRecord) -> str:
    if record.summary:
        return f"Package tool probe {record.status}: {record.tool_id}. {record.summary}"
    if record.output_summary:
        return f"Package tool probe {record.status}: {record.tool_id}. {record.output_summary}"
    return f"Package tool probe {record.status}: {record.tool_id}. {record.message}"


def _json_preview(value: Any, *, limit: int) -> Any:
    normalized = _json_safe(value)
    text = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return normalized
    return {
        "truncated": True,
        "chars": len(text),
        "preview": text[:limit],
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _one_line(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."
