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
from agent_factory.create_agent.validation_gate import CreateAgentValidationGate, ValidationDecision
from agent_factory.create_agent.validator import CreateAgentPackageValidator
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.models import get_main_model
from agent_factory.tooling.langgraph_node import build_tool_node_runner, latest_ai_tool_calls


class CreateAgentGraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    request: str
    workspace_path: str
    iteration: int
    repair_context: str
    validation: dict[str, Any]
    done: bool
    final_answer: str


@dataclass(slots=True)
class CreateAgentWorkflow:
    tools: list[BaseTool]
    validator: CreateAgentPackageValidator
    model: Any | None = None

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
        graph.add_edge("tools", "validate")
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
        messages = _messages_with_system(state, self.tools)
        response = model.bind_tools(self.tools, tool_choice="auto").invoke(messages) if self.tools else model.invoke(messages)
        if not isinstance(response, BaseMessage):
            response = AIMessage(content=str(response))
        return {
            "messages": [response],
            "iteration": int(state.get("iteration") or 0) + 1,
            "repair_context": "",
        }

    def _tools(self, state: CreateAgentGraphState) -> dict[str, Any]:
        tool_node = build_tool_node_runner(
            self.tools,
            node_id="create_agent_tools",
            messages_key="messages",
            emit_event=_emit_tool_activity,
        )
        return tool_node.invoke(state)

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
                "validation": previous_report.model_dump(mode="json"),
                "repair_context": "",
                "done": False,
            }
        force_full = action.action == "finalize"
        report = CreateAgentValidationGate(self.validator).run(
            workspace,
            decision=ValidationDecision(force_full=force_full),
        )
        workspace.write_validation(report)
        if force_full:
            workspace.write_action(CreateAgentAction())
        todo = workspace.read_todo()
        if report.status != "passed":
            todo = todo.upsert_repair_items(report.issues)
            workspace.write_todo(todo)
        done = report.status == "passed" and todo.all_required_done()
        if done:
            return {
                "validation": report.model_dump(mode="json"),
                "repair_context": "",
                "done": True,
                "final_answer": f"AgentPackage 制造完成并通过校验：{workspace.root}",
            }
        repair_context = _repair_context(workspace=workspace, report=report)
        return {
            "repair_context": repair_context,
            "validation": report.model_dump(mode="json"),
            "done": False,
        }

    def _route_after_supervisor(self, state: CreateAgentGraphState) -> Literal["tools", "validate"]:
        _ai_message, tool_calls = latest_ai_tool_calls(state.get("messages") or [])
        return "tools" if tool_calls else "validate"

    def _route_after_validate(self, state: CreateAgentGraphState) -> Literal["supervisor", "end"]:
        return "end" if state.get("done") else "supervisor"


def _messages_with_system(state: CreateAgentGraphState, tools: list[BaseTool]) -> list[BaseMessage]:
    workspace = CreateAgentWorkspace(state["workspace_path"])
    repair_context = str(state.get("repair_context") or "").strip()
    system_sections = [
        "你是 FastAgentFactory 的 create-agent 文件制造 ReAct agent。",
        "你不运行 RuntimeKernel SystemPackage 制造流程；你的职责是在工作区直接制造一个 RuntimeKernel AgentPackage。",
        "所有文件读写、搜索、MCP、skill 和 shell 行为都必须通过已绑定工具完成。",
        (
            "必须通过 create_agent_todo 维护制造 todo；不要直接写 .factory/todo.json。"
            "todo 未全部完成或 package 校验未通过时，必须继续制造或修复。"
        ),
        (
            "需要用户补充资源或决策时，必须调用 create_agent_control(action=ask_user, message=...)；"
            "不要直接写 .factory/action.json，不要输出表单。"
        ),
        "不要硬编码业务资源。用户提供的信息优先；公开信息可通过已绑定工具发现；secret 只能由用户提供。",
        "最终出厂条件只有两个：Package validation passed，并且所有 required todo 都是 done。",
        (
            "制造 skill 必须通过内置 skill gateway 渐进加载：先用 skill list/search/describe "
            "按当前 todo 选择指引，再用 skill load/read_resource 按需加载正文或资源；"
            "不要假定未加载的 skill 内容。"
        ),
        f"Bound tools: {', '.join(tool.name for tool in tools) if tools else 'none'}",
        workspace.context_summary(),
    ]
    if repair_context:
        system_sections.append(
            "Hidden repair context from the latest package/todo validation gate. "
            "Use it to continue the ReAct repair loop; do not repeat it verbatim to the user.\n\n"
            f"{repair_context}"
        )
    system = SystemMessage(
        content="\n\n".join(system_sections)
    )
    return [system, *list(state.get("messages") or [])]


def _repair_context(*, workspace: CreateAgentWorkspace, report: Any) -> str:
    return (
        "Package validation/todo gate is not complete. Continue the ReAct loop.\n"
        "Use create_agent_todo to inspect or update todos, read .factory/validation.json, then update package files through tools.\n\n"
        f"{workspace.context_summary()}\n\n"
        f"Validation report:\n{report.model_dump_json(indent=2)}"
    )


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
