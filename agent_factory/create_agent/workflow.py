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
    validation_event: str
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
        messages = _messages_with_system(state, self.tools)
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
            "validation_event": _validation_event_from_tool_calls(tool_calls),
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
        force_full = action.action == "finalize"
        validation_event = str(state.get("validation_event") or "none")
        if validation_event == "explicit_validation" and workspace.read_validation() is not None and not force_full:
            report = workspace.read_validation()
            assert report is not None
        else:
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
                "validation": report.to_digest().model_dump(mode="json"),
                "repair_context": "",
                "done": True,
                "final_answer": f"AgentPackage 制造完成并通过校验：{workspace.root}",
                "validation_event": "none",
            }
        repair_context = _repair_context(workspace=workspace, report=report)
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


def _messages_with_system(state: CreateAgentGraphState, tools: list[BaseTool]) -> list[BaseMessage]:
    workspace = CreateAgentWorkspace(state["workspace_path"])
    repair_context = str(state.get("repair_context") or "").strip()
    system_sections = [
        "你是 FastAgentFactory 的 create-agent 文件制造 ReAct agent。",
        "你不运行 RuntimeKernel SystemPackage 制造流程；你的职责是在工作区直接制造一个 RuntimeKernel AgentPackage。",
        "所有文件读写、搜索、MCP、skill 和校验行为都必须通过已绑定工具完成。",
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
            "确定 active todo 的候选 skill；候选 skill 不等于允许全部加载。"
            "同一 active todo 默认只加载一个 primary skill 全文。"
            "skill load 必须携带 current_todo 和 reason；需要第二个 skill 时必须先 describe，"
            "并在 reason 里说明当前 primary skill 为什么不够。"
        ),
        (
            "写某类 package 文件前，必须优先通过 skill read_resource 读取对应 schema/minimal example/repair hints；"
            "不要通过项目源码 inspect 或 shell 推断 schema。"
        ),
        (
            "通用 bash 不在 create-agent 默认工具集中。需要校验时调用 create_agent_validate；"
            "Package validator observation 中的 recommended_skill/recommended_resources 是下一步修复入口。"
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
    digest = report.to_digest()
    issue_lines = [
        (
            f"- {issue.issue_id}: {issue.where}; files={issue.target_files}; "
            f"hint={issue.repair_hint}; skill={issue.recommended_skill}; resources={issue.recommended_resources}"
        )
        for issue in digest.issues
    ]
    return (
        "Package validation/todo gate is not complete. Continue the ReAct loop.\n"
        "Use create_agent_todo for the active working set. Full validation details are stored in .factory/validation.json; "
        "load only the recommended skill resources needed for the next repair.\n\n"
        f"{workspace.context_summary()}\n\n"
        f"Validation digest: {digest.status} | scope={digest.validation_scope} | {digest.summary}\n"
        + "\n".join(issue_lines)
    )


def _validation_event_from_tool_calls(tool_calls: list[dict[str, Any]]) -> str:
    tool_names = {str(call.get("name") or "") for call in tool_calls}
    if "create_agent_control" in tool_names:
        return "control"
    if "create_agent_validate" in tool_names:
        return "explicit_validation"
    if tool_names & {"write", "edit", "multi_edit"}:
        return "package_change"
    if "create_agent_todo" in tool_names:
        return "todo"
    return "none"


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
