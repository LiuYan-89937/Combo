from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from agent_factory.create_agent.models import CreateAgentAction, PackageValidationReport
from agent_factory.create_agent.prompt_builder import build_create_agent_messages, validation_repair_context
from agent_factory.create_agent.validation_gate import CreateAgentValidationGate, ValidationDecision
from agent_factory.create_agent.validation_progress import apply_system_validation_progress, stage_progress_summary, validation_event_from_tool_calls
from agent_factory.create_agent.validator import CreateAgentPackageValidator
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.models import get_main_model
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
        response = model.bind_tools(self.tools, tool_choice="auto").invoke(messages) if self.tools else model.invoke(messages)
        if not isinstance(response, BaseMessage):
            response = AIMessage(content=str(response))
        validation_event = "assistant_stopped" if not bool(getattr(response, "tool_calls", None)) else "none"
        return {
            "messages": [response],
            "iteration": int(state.get("iteration") or 0) + 1,
            "repair_context": "",
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
        force_full = action.action == "finalize" and active_stage is not None and active_stage.system_id == "final_validation"
        report = CreateAgentValidationGate(self.validator).run(
            workspace,
            decision=ValidationDecision(force_full=force_full),
        )
        workspace.write_validation(report)
        if force_full:
            workspace.write_action(CreateAgentAction())
        previous_system_state = workspace.read_system_state()
        system_state = apply_system_validation_progress(previous_system_state, report)
        workspace.write_system_state(system_state)
        progress_summary = stage_progress_summary(previous_system_state, system_state, report)
        done = report.status == "passed" and system_state.all_done()
        if done:
            return {
                "validation": report.to_digest().model_dump(mode="json"),
                "repair_context": "",
                "done": True,
                "final_answer": f"AgentPackage 制造完成并通过校验：{workspace.root}",
                "validation_event": "none",
            }
        repair_context = validation_repair_context(workspace=workspace, report=report, stage_progress=progress_summary)
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
