from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from agent_factory.create_agent.models import CreateAgentAction, PackageValidationReport
from agent_factory.create_agent.output_safety import looks_like_internal_observation_text
from agent_factory.create_agent.prompt_builder import build_create_agent_prompt
from agent_factory.create_agent.validation_state import package_fingerprint
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.models import get_main_model
from agent_factory.model_pool.runtime_override import resolve_runtime_main_chat_model_from_state
from agent_factory.runtime_kernel.model_operations import ModelOperationService
from agent_factory.tooling.langgraph_node import build_tool_node_runner, latest_ai_tool_calls


class CreateAgentGraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    request: str
    workspace_path: str
    runtime_attachments: list[dict[str, Any]]
    iteration: int
    validation: dict[str, Any]
    graph_kind: str
    evolution_context: dict[str, Any]
    runtime_main_model_profile_id: str
    done: bool
    final_answer: str
    publish_ready: dict[str, Any]


@dataclass(slots=True)
class CreateAgentWorkflow:
    tools: list[BaseTool]
    model: Any | None = None
    capability_inventory: dict[str, Any] | None = None
    workflow_kind: Literal["manufacture", "evolution"] = "manufacture"

    def compile(self, *, checkpointer: Any | None = None):
        graph = StateGraph(CreateAgentGraphState)
        graph.add_node("supervisor", self._supervisor)
        graph.add_node("tools", self._tools)
        graph.add_node("control_gate", self._control_gate)
        graph.set_entry_point("supervisor")
        graph.add_conditional_edges(
            "supervisor",
            self._route_after_supervisor,
            {"tools": "tools", "control_gate": "control_gate"},
        )
        graph.add_conditional_edges(
            "tools",
            self._route_after_tools,
            {"supervisor": "supervisor", "control_gate": "control_gate"},
        )
        graph.add_conditional_edges(
            "control_gate",
            self._route_after_control_gate,
            {"supervisor": "supervisor", "end": END},
        )
        return graph.compile(checkpointer=checkpointer)

    def _supervisor(self, state: CreateAgentGraphState) -> dict[str, Any]:
        _ai_message, unresolved_tool_calls = latest_ai_tool_calls(state.get("messages") or [])
        if unresolved_tool_calls:
            return {
                "done": False,
            }
        runtime_model = resolve_runtime_main_chat_model_from_state(state)
        model = runtime_model.model if runtime_model is not None else self.model or get_main_model()
        if model is None:
            raise RuntimeError("main model is not configured for create-agent")
        if self.workflow_kind == "evolution":
            from agent_factory.evolution.prompt_builder import build_evolution_prompt

            prompt_payload = build_evolution_prompt(
                state,
                self.tools,
                capability_inventory=self.capability_inventory or {},
            )
            node_id = "evolution_supervisor"
        else:
            prompt_payload = build_create_agent_prompt(
                state,
                self.tools,
                capability_inventory=self.capability_inventory or {},
            )
            node_id = "create_agent_supervisor"
        messages = prompt_payload.messages
        prompt_binding, chat_messages = _operation_prompt(messages)
        result = ModelOperationService(
            role="main",
            model=model,
            settings=runtime_model.settings if runtime_model is not None else None,
        ).tool_bound_chat(
            state=state,
            prompt_binding=prompt_binding,
            messages=chat_messages,
            tools=self.tools,
            node_id=node_id,
        )
        _emit_model_cache_metrics(
            state=state,
            workspace=CreateAgentWorkspace(state["workspace_path"]),
            metadata=result.metadata,
            prompt_diagnostics=prompt_payload.diagnostics,
        )
        response = result.ai_message if isinstance(result.ai_message, BaseMessage) else AIMessage(content=result.assistant_draft or "")
        return {
            "messages": [response],
            "iteration": int(state.get("iteration") or 0) + 1,
        }

    def _tools(self, state: CreateAgentGraphState) -> dict[str, Any]:
        tool_node = build_tool_node_runner(
            self.tools,
            node_id="create_agent_tools",
            messages_key="messages",
            emit_event=_emit_tool_activity,
        )
        result = tool_node.invoke(state)
        return result

    def _control_gate(self, state: CreateAgentGraphState) -> dict[str, Any]:
        workspace = CreateAgentWorkspace(state["workspace_path"])
        if self.workflow_kind == "evolution":
            return self._evolution_control_gate(state, workspace)
        publish_report = workspace.read_publish_report()
        if publish_report.get("status") == "available":
            package_id = str(publish_report.get("package_id") or "").strip()
            package_path = str(publish_report.get("package_path") or "").strip()
            return {
                "done": True,
                "final_answer": f"AgentPackage 已发布：{package_id} ({package_path})",
            }
        action = workspace.read_action()
        if action.action == "ask_user":
            ready_report = workspace.read_validation()
            if not _publish_readiness_error(workspace=workspace, report=ready_report):
                workspace.write_action(CreateAgentAction())
                return _publish_ready_result(workspace, ready_report)
            answer = interrupt(
                {
                    "type": "create_agent_question",
                    "presentation": "assistant_dialogue",
                    "resume_kind": "answer",
                    "title": "补充制造信息",
                    "message": action.message or "请补充制造这个 AgentPackage 所需的信息。",
                    "workspace_path": str(workspace.root),
                    "resource_facts": [fact.model_dump(mode="json") for fact in action.resource_facts],
                }
            )
            workspace.write_action(CreateAgentAction())
            previous_report = workspace.read_validation() or PackageValidationReport(
                package_root=str(workspace.root),
                validation_scope="workspace_hygiene",
                skipped=True,
                summary="Validation skipped while waiting for user input.",
            )
            return {
                "messages": [HumanMessage(content=_resume_text(answer))],
                "validation": previous_report.to_digest().model_dump(mode="json"),
                "done": False,
            }
        if action.action != "finalize":
            return {"done": False}
        report = workspace.read_validation()
        ready_error = _publish_readiness_error(workspace=workspace, report=report)
        if ready_error:
            workspace.write_action(CreateAgentAction())
            return {
                "messages": [SystemMessage(content=ready_error)],
                "done": False,
            }
        workspace.write_action(CreateAgentAction())
        return _publish_ready_result(workspace, report)

    def _evolution_control_gate(self, state: CreateAgentGraphState, workspace: CreateAgentWorkspace) -> dict[str, Any]:
        action = workspace.read_action()
        if action.action == "ask_user":
            answer = interrupt(
                {
                    "type": "agent_evolution_question",
                    "presentation": "assistant_dialogue",
                    "resume_kind": "answer",
                    "title": "补充进化信息",
                    "message": action.message or "请补充进化这个已发布 AgentPackage 所需的信息。",
                    "workspace_path": str(workspace.root),
                    "resource_facts": [fact.model_dump(mode="json") for fact in action.resource_facts],
                }
            )
            workspace.write_action(CreateAgentAction())
            previous_report = workspace.read_validation() or PackageValidationReport(
                package_root=str(workspace.root),
                validation_scope="workspace_hygiene",
                skipped=True,
                summary="Validation skipped while waiting for user input.",
            )
            return {
                "messages": [HumanMessage(content=_resume_text(answer))],
                "validation": previous_report.to_digest().model_dump(mode="json"),
                "done": False,
            }
        if action.action != "finalize":
            return {"done": False}
        report = workspace.read_validation()
        ready_error = _evolution_publish_readiness_error(workspace=workspace, report=report)
        if ready_error:
            workspace.write_action(CreateAgentAction())
            return {
                "messages": [SystemMessage(content=ready_error)],
                "done": False,
            }
        final_answer = _evolution_final_answer(action.message)
        workspace.write_action(CreateAgentAction())
        return {
            "validation": report.to_digest().model_dump(mode="json"),
            "done": True,
            "final_answer": final_answer,
        }

    def _route_after_supervisor(self, state: CreateAgentGraphState) -> Literal["tools", "control_gate"]:
        _ai_message, tool_calls = latest_ai_tool_calls(state.get("messages") or [])
        return "tools" if tool_calls else "control_gate"

    def _route_after_tools(self, state: CreateAgentGraphState) -> Literal["supervisor", "control_gate"]:
        _ai_message, tool_calls = latest_ai_tool_calls(state.get("messages") or [])
        return "control_gate" if _has_control_action(tool_calls) else "supervisor"

    def _route_after_control_gate(self, state: CreateAgentGraphState) -> Literal["supervisor", "end"]:
        return "end" if state.get("done") else "supervisor"


def _emit_tool_activity(payload: dict[str, Any]) -> None:
    writer = get_stream_writer()
    writer({"type": "tool_activity", "payload": {"events": [payload]}})


def _emit_model_cache_metrics(
    *,
    state: CreateAgentGraphState,
    workspace: CreateAgentWorkspace,
    metadata: dict[str, Any],
    prompt_diagnostics: dict[str, Any],
) -> None:
    usage = metadata.get("usage_metadata") if isinstance(metadata.get("usage_metadata"), dict) else {}
    input_tokens = _usage_int(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_int(usage, "output_tokens", "completion_tokens")
    cached_input_tokens = _cached_input_tokens(usage)
    hit_ratio = None
    if input_tokens and cached_input_tokens is not None:
        hit_ratio = round(float(cached_input_tokens) / float(input_tokens), 6)
    active = workspace.read_system_state().active_stage()
    graph_kind = str(state.get("graph_kind") or "manufacture")
    evolution_context = state.get("evolution_context") if isinstance(state.get("evolution_context"), dict) else {}
    agent_id = "agent_evolution" if graph_kind == "evolution" else "create_agent"
    agent_name = "进化 Agent" if graph_kind == "evolution" else "制造 Agent"
    payload = {
        "version": "create_agent_model_cache_metrics.v0",
        "node_id": "create_agent_supervisor",
        "iteration": int(state.get("iteration") or 0) + 1,
        "active_focus_id": active.system_id if active else None,
        "active_focus_status": active.status.value if active else None,
        "provider_cache": {
            "available": cached_input_tokens is not None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "hit_ratio": hit_ratio,
            "source": "usage_metadata.input_token_details.cache_read" if cached_input_tokens is not None else None,
        },
        "prompt_diagnostics": prompt_diagnostics,
        "model": metadata.get("model"),
        "provider": metadata.get("provider"),
        "provider_display_name": metadata.get("provider_display_name"),
        "model_profile_id": metadata.get("model_profile_id"),
        "model_role": metadata.get("model_role"),
        "model_source": metadata.get("model_source"),
        "agent_id": agent_id,
        "agent_name": agent_name,
        "package_id": evolution_context.get("package_id") if graph_kind == "evolution" else None,
        "session_id": state.get("session_id"),
        "run_id": state.get("request_id"),
        "tool_count": metadata.get("tool_count"),
    }
    writer = get_stream_writer()
    writer({"type": "create_agent_model_cache", "payload": payload})


def _usage_int(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def _cached_input_tokens(usage: dict[str, Any]) -> int | None:
    details = usage.get("input_token_details")
    if isinstance(details, dict):
        value = details.get("cache_read")
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def _has_control_action(tool_calls: list[dict[str, Any]]) -> bool:
    return any(str(call.get("name") or "") == "create_agent_control" for call in tool_calls)


def _publish_readiness_error(*, workspace: CreateAgentWorkspace, report: PackageValidationReport | None) -> str:
    active = workspace.read_system_state().active_stage()
    if active is None or active.system_id != "validation_publish":
        return (
            "Finalize blocked: active focus must be validation_publish. "
            "Run create_agent_validate(scope='full_static', reason=...) after implementation is complete; "
            "a passed full_static validation synchronizes validation_publish readiness."
        )
    if report is None:
        return "Finalize blocked: no validation report exists. Call create_agent_validate(scope='full_static', reason=...) first."
    if report.status != "passed":
        return (
            f"Finalize blocked: latest validation status is {report.status}. "
            "Repair from the create_agent_validate observation, then call create_agent_validate(scope='full_static', reason=...) again."
        )
    validation_state = workspace.read_validation_state()
    if validation_state is None:
        return "Finalize blocked: validation fingerprint state is missing. Call create_agent_validate(scope='full_static', reason=...) again."
    if validation_state.validation_scope != "full_static" or report.validation_scope != "full_static":
        return "Finalize blocked: latest validation must be full_static. Call create_agent_validate(scope='full_static', reason=...) first."
    if validation_state.package_fingerprint != package_fingerprint(workspace.root):
        return "Finalize blocked: package files changed after validation. Call create_agent_validate(scope='full_static', reason=...) again."
    return ""


def _evolution_publish_readiness_error(*, workspace: CreateAgentWorkspace, report: PackageValidationReport | None) -> str:
    if report is None:
        return "Finalize blocked: no validation report exists. Call create_agent_validate(scope='full_static', reason=...) first."
    if report.status != "passed":
        return (
            f"Finalize blocked: latest validation status is {report.status}. "
            "Repair from the create_agent_validate observation, then call create_agent_validate(scope='full_static', reason=...) again."
        )
    validation_state = workspace.read_validation_state()
    if validation_state is None:
        return "Finalize blocked: validation fingerprint state is missing. Call create_agent_validate(scope='full_static', reason=...) again."
    if validation_state.validation_scope != "full_static" or report.validation_scope != "full_static":
        return "Finalize blocked: latest validation must be full_static. Call create_agent_validate(scope='full_static', reason=...) first."
    if validation_state.package_fingerprint != package_fingerprint(workspace.root):
        return "Finalize blocked: package files changed after validation. Call create_agent_validate(scope='full_static', reason=...) again."
    return ""


def _resume_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("input_text", "answer", "message"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        return str(value)
    return str(value or "").strip()


def _evolution_final_answer(message: str) -> str:
    text = str(message or "").strip()
    if text and not looks_like_internal_observation_text(text):
        return text
    return "AgentPackage 进化已通过 full_static validation，变更已完成并自动发布。"


def _operation_prompt(messages: list[BaseMessage]) -> tuple[dict[str, Any], list[BaseMessage]]:
    if messages and isinstance(messages[0], SystemMessage):
        return {"template": str(messages[0].content or "")}, messages[1:]
    return {}, messages


def _publish_ready_text(workspace: CreateAgentWorkspace, report: PackageValidationReport) -> str:
    return (
        "AgentPackage 已完成制造并通过最终静态校验。\n\n"
        f"- Workspace: {workspace.root}\n"
        f"- Validation: {report.validation_scope} / {report.status}\n"
        f"- Summary: {report.summary}\n\n"
        "当前包已进入待发布状态。发布只由用户在界面中点击发布按钮执行，制造 Agent 不再参与物理发布。"
    )


def _publish_ready_payload(workspace: CreateAgentWorkspace, report: PackageValidationReport) -> dict[str, Any]:
    return {
        "version": "agent_package_publish_report.v0",
        "status": "ready",
        "source_workspace": str(workspace.root),
        "message": _publish_ready_text(workspace, report),
        "validation": report.to_digest().model_dump(mode="json"),
        "package_fingerprint": package_fingerprint(workspace.root),
    }


def _publish_ready_result(workspace: CreateAgentWorkspace, report: PackageValidationReport) -> dict[str, Any]:
    publish_ready = _publish_ready_payload(workspace, report)
    workspace.write_publish_report(publish_ready)
    return {
        "validation": report.to_digest().model_dump(mode="json"),
        "publish_ready": publish_ready,
        "done": True,
        "final_answer": _publish_ready_text(workspace, report),
    }
