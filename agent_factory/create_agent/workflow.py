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
from agent_factory.create_agent.prompt_builder import build_create_agent_messages, validation_repair_context
from agent_factory.create_agent.validation_gate import CreateAgentValidationGate, ValidationDecision
from agent_factory.create_agent.validation_gate import _package_fingerprint
from agent_factory.create_agent.validation_progress import validation_event_from_tool_calls
from agent_factory.create_agent.validator import CreateAgentPackageValidator
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.models import get_main_model
from agent_factory.runtime_kernel.model_operations import ModelOperationService
from agent_factory.tooling.builtins.resource_set.resource_set import ResourceSetStore
from agent_factory.tooling.langgraph_node import build_tool_node_runner, latest_ai_tool_calls


class CreateAgentGraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    request: str
    workspace_path: str
    iteration: int
    repair_context: str
    validation: dict[str, Any]
    validation_event: str
    publish_confirmation_response: dict[str, Any]
    done: bool
    final_answer: str


@dataclass(slots=True)
class CreateAgentWorkflow:
    tools: list[BaseTool]
    validator: CreateAgentPackageValidator
    model: Any | None = None
    resource_set_store: ResourceSetStore | None = None
    capability_inventory: dict[str, Any] | None = None

    def compile(self, *, checkpointer: Any | None = None):
        graph = StateGraph(CreateAgentGraphState)
        graph.add_node("supervisor", self._supervisor)
        graph.add_node("tools", self._tools)
        graph.add_node("validate", self._validate)
        graph.set_entry_point("supervisor")
        graph.add_conditional_edges(
            "supervisor",
            self._route_after_supervisor,
            {"tools": "tools", "validate": "validate"},
        )
        graph.add_conditional_edges(
            "tools",
            self._route_after_tools,
            {"supervisor": "supervisor", "validate": "validate"},
        )
        graph.add_conditional_edges(
            "validate",
            self._route_after_validate,
            {"supervisor": "supervisor", "end": END},
        )
        return graph.compile(checkpointer=checkpointer)

    def _supervisor(self, state: CreateAgentGraphState) -> dict[str, Any]:
        model = self.model or get_main_model()
        if model is None:
            raise RuntimeError("main model is not configured for create-agent")
        messages = build_create_agent_messages(
            state,
            self.tools,
            resource_set_store=self.resource_set_store,
            capability_inventory=self.capability_inventory or {},
        )
        prompt_binding, chat_messages = _operation_prompt(messages)
        result = ModelOperationService(role="main", model=model).tool_bound_chat(
            state=state,
            prompt_binding=prompt_binding,
            messages=chat_messages,
            tools=self.tools,
            node_id="create_agent_supervisor",
        )
        response = result.ai_message if isinstance(result.ai_message, BaseMessage) else AIMessage(content=result.assistant_draft or "")
        validation_event = "assistant_stopped" if not bool(getattr(response, "tool_calls", None)) else "none"
        return {
            "messages": [response],
            "iteration": int(state.get("iteration") or 0) + 1,
            "repair_context": "",
            "publish_confirmation_response": {},
            "validation_event": validation_event,
        }

    def _tools(self, state: CreateAgentGraphState) -> dict[str, Any]:
        _ai_message, tool_calls = latest_ai_tool_calls(state.get("messages") or [])
        tool_node = build_tool_node_runner(
            self.tools,
            node_id="create_agent_tools",
            messages_key="messages",
            emit_event=_emit_tool_activity,
        )
        result = tool_node.invoke(state)
        return {
            **result,
            "validation_event": validation_event_from_tool_calls(tool_calls),
        }

    def _validate(self, state: CreateAgentGraphState) -> dict[str, Any]:
        workspace = CreateAgentWorkspace(state["workspace_path"])
        publish_report = workspace.read_publish_report()
        if publish_report.get("status") == "available":
            package_id = str(publish_report.get("package_id") or "").strip()
            package_path = str(publish_report.get("package_path") or "").strip()
            return {
                "repair_context": "",
                "done": True,
                "final_answer": f"AgentPackage 已发布：{package_id} ({package_path})",
                "validation_event": "none",
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
                "repair_context": "",
                "done": False,
                "validation_event": "none",
            }
        active_stage = workspace.read_system_state().active_stage()
        force_full = action.action == "finalize" and active_stage is not None and active_stage.system_id == "validation_publish"
        report = CreateAgentValidationGate(self.validator).run(
            workspace,
            decision=ValidationDecision(force_full=force_full),
        )
        workspace.write_validation(report)
        if force_full:
            workspace.write_action(CreateAgentAction())
        system_state = workspace.read_system_state()
        if report.status == "passed" and force_full and system_state.all_done():
            answer = interrupt(
                {
                    "type": "create_agent_publish_confirmation",
                    "presentation": "assistant_dialogue",
                    "resume_kind": "confirmation",
                    "title": "发布前确认",
                    "message": _publish_confirmation_text(workspace, report),
                    "workspace_path": str(workspace.root),
                    "validation": report.to_digest().model_dump(mode="json"),
                }
            )
            publish_decision = _publish_decision_from_resume(answer)
            workspace.write_publish_decision(
                CreateAgentPublishDecision(
                    decision=publish_decision,
                    input_text=_resume_text(answer),
                    package_fingerprint=_package_fingerprint(workspace.root),
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
                "messages": [HumanMessage(content=resume_text)],
                "validation": report.to_digest().model_dump(mode="json"),
                "publish_confirmation_response": publish_response,
                "repair_context": "",
                "done": False,
                "validation_event": "none",
            }
        repair_context = validation_repair_context(workspace=workspace, report=report)
        return {
            "repair_context": repair_context,
            "validation": report.to_digest().model_dump(mode="json"),
            "done": False,
            "validation_event": "none",
        }

    def _route_after_supervisor(self, state: CreateAgentGraphState) -> Literal["tools", "validate"]:
        _ai_message, tool_calls = latest_ai_tool_calls(state.get("messages") or [])
        return "tools" if tool_calls else "validate"

    def _route_after_tools(self, state: CreateAgentGraphState) -> Literal["supervisor", "validate"]:
        return "validate" if state.get("validation_event") != "none" else "supervisor"

    def _route_after_validate(self, state: CreateAgentGraphState) -> Literal["supervisor", "end"]:
        return "end" if state.get("done") else "supervisor"


def _emit_tool_activity(payload: dict[str, Any]) -> None:
    writer = get_stream_writer()
    writer({"type": "tool_activity", "payload": {"events": [payload]}})


def _resume_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("input_text", "answer", "message"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        return str(value)
    return str(value or "").strip()


def _publish_decision_from_resume(value: Any) -> str:
    if isinstance(value, dict):
        decision = str(value.get("decision") or "").strip().lower()
        if decision == "approve":
            return "approve"
        return "pending"
    text = str(value or "").strip().lower()
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
