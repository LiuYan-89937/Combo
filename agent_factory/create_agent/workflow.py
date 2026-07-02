from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from agent_factory.create_agent.models import CreateAgentAction, CreateAgentPublishDecision, PackageValidationReport
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
    publish_confirmation_response: dict[str, Any]
    graph_kind: str
    evolution_context: dict[str, Any]
    runtime_main_model_profile_id: str
    done: bool
    final_answer: str


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
                "publish_confirmation_response": {},
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
            "publish_confirmation_response": {},
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
        answer = interrupt(
            {
                "type": "create_agent_publish_confirmation",
                "presentation": "assistant_dialogue",
                "resume_kind": "confirmation",
                "title": "发布前确认",
                "message": _publish_confirmation_text(workspace, report),
                "options": [
                    {
                        "id": "publish",
                        "label": "发布",
                        "description": "发布已通过最终校验的 AgentPackage。",
                    },
                    {
                        "id": "save_draft",
                        "label": "保存草稿",
                        "description": "保留当前工作区，不发布。",
                    },
                    {
                        "id": "message",
                        "label": "输入",
                        "description": "输入问题、调整意见或其他自然语言内容。",
                    },
                ],
                "workspace_path": str(workspace.root),
                "validation": report.to_digest().model_dump(mode="json"),
            }
        )
        publish_decision = _publish_decision_from_resume(answer)
        workspace.write_publish_decision(
            CreateAgentPublishDecision(
                decision=publish_decision,
                input_text=_resume_text(answer),
                package_fingerprint=package_fingerprint(workspace.root),
                validation_scope=report.validation_scope,
                validation_status=report.status,
            )
        )
        resume_text = _publish_resume_text(answer, decision=publish_decision)
        publish_response = {
            "decision": publish_decision,
            "input_text": _resume_text(answer),
            "instruction": (
                "User explicitly approved publish."
                if publish_decision == "approve"
                else "Publish is still pending. Treat input_text as the user's latest message, not as an automatic modification request."
            ),
        }
        return {
            "validation": report.to_digest().model_dump(mode="json"),
            "messages": [HumanMessage(content=resume_text)],
            "publish_confirmation_response": publish_response,
            "done": False,
        }

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
            "Set focus explicitly with create_agent_stage(action='set_focus', focus_id='validation_publish', reason=...), "
            "then run create_agent_validate(scope='full_static', reason=...)."
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


def _publish_decision_from_resume(value: Any) -> str:
    if isinstance(value, dict):
        decision = str(value.get("decision") or "").strip().lower()
        if decision in {"approve", "publish"}:
            return "approve"
        text = _resume_text(value).strip().lower()
    return "approve" if text in {"确认", "确认发布", "发布", "approve", "approved", "yes", "y", "ok"} else "pending"


def _publish_resume_text(value: Any, *, decision: str) -> str:
    text = _resume_text(value)
    if decision == "approve":
        return f"用户已明确确认发布 AgentPackage。确认内容：{text}"
    return (
        "用户在发布确认阶段回复了一条消息，但尚未明确确认发布。"
        f"请把下面内容作为用户最新消息处理，而不是自动当作修改需求：{text}\n"
        "如果这是问题或质疑，先基于当前 AgentPackage 状态回答；"
        "如果这是修改要求，再进入制造修改和校验；"
        "如果用户随后明确确认发布，再调用 create_agent_publish。"
    )


def _operation_prompt(messages: list[BaseMessage]) -> tuple[dict[str, Any], list[BaseMessage]]:
    if messages and isinstance(messages[0], SystemMessage):
        return {"template": str(messages[0].content or "")}, messages[1:]
    return {}, messages


def _publish_confirmation_text(workspace: CreateAgentWorkspace, report: PackageValidationReport) -> str:
    return (
        "AgentPackage 已通过最终静态校验。\n\n"
        f"- Workspace: {workspace.root}\n"
        f"- Validation: {report.validation_scope} / {report.status}\n"
        f"- Summary: {report.summary}\n\n"
        "如果还需要调整，请直接用自然语言说明要改哪里；"
        "如果确认发布，请直接回复确认发布。"
    )
