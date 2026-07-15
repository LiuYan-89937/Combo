from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.models import get_main_model
from agent_factory.models.message_layout import system_messages_first
from agent_factory.model_pool.runtime_override import resolve_runtime_main_chat_model_from_state
from agent_factory.runtime_attachments import format_attachments_for_model
from agent_factory.runtime_kernel.model_operations import ModelOperationService
from agent_factory.runtime_kernel.observability.node_events import langgraph_model_event_sink
from agent_factory.tooling.langgraph_node import build_tool_node_runner, latest_ai_tool_calls


class CreateAgentAssistState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    workspace_path: str
    runtime_attachments: list[dict[str, Any]]
    runtime_main_model_profile_id: str
    runtime_reasoning_intensity: int | None
    done: bool
    final_answer: str
    tool_rounds: int


@dataclass(slots=True)
class CreateAgentAssistWorkflow:
    tools: list[BaseTool]
    model: Any | None = None

    def compile(self, *, checkpointer: Any | None = None):
        graph = StateGraph(CreateAgentAssistState)
        graph.add_node("assistant", self._assistant)
        graph.add_node("tools", self._tools)
        graph.set_entry_point("assistant")
        graph.add_conditional_edges(
            "assistant",
            self._route_after_assistant,
            {"tools": "tools", "end": END},
        )
        graph.add_conditional_edges(
            "tools",
            self._route_after_tools,
            {"assistant": "assistant", "end": END},
        )
        return graph.compile(checkpointer=checkpointer)

    def _assistant(self, state: CreateAgentAssistState) -> dict[str, Any]:
        runtime_model = resolve_runtime_main_chat_model_from_state(state)
        model = runtime_model.model if runtime_model is not None else self.model or get_main_model()
        if model is None:
            raise RuntimeError("main model is not configured for create-agent assist")
        messages = _messages_with_system(state, self.tools)
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
            emit_event=langgraph_model_event_sink("create_agent_assist"),
            node_id="create_agent_assist",
        )
        response = result.ai_message if isinstance(result.ai_message, BaseMessage) else AIMessage(content=result.assistant_draft or "")
        return {
            "messages": [response],
            "done": not bool(getattr(response, "tool_calls", None)),
            "final_answer": _message_text(response),
        }

    def _tools(self, state: CreateAgentAssistState) -> dict[str, Any]:
        tool_node = build_tool_node_runner(
            self.tools,
            node_id="create_agent_assist_tools",
            messages_key="messages",
            emit_event=_emit_tool_activity,
        )
        result = tool_node.invoke(state)
        rounds = int(state.get("tool_rounds") or 0) + 1
        return {
            **result,
            "tool_rounds": rounds,
            "done": False,
        }

    def _route_after_assistant(self, state: CreateAgentAssistState) -> Literal["tools", "end"]:
        _ai_message, tool_calls = latest_ai_tool_calls(state.get("messages") or [])
        return "tools" if tool_calls else "end"

    def _route_after_tools(self, state: CreateAgentAssistState) -> Literal["assistant", "end"]:
        return "assistant"


def _messages_with_system(state: CreateAgentAssistState, tools: list[BaseTool]) -> list[BaseMessage]:
    workspace = CreateAgentWorkspace(state["workspace_path"])
    attachments = format_attachments_for_model(state.get("runtime_attachments"))
    system = SystemMessage(
        content="\n\n".join(
            item
            for item in [
                "你是 FastAgentFactory 的 /create-agent 辅助模式。",
                "当前图只用于问答、查看 workspace、解释已有状态；不能创建、修改、验证或推进 AgentPackage。",
                "如果用户要求创建、继续、修复、验证或制造 AgentPackage，说明该请求需要进入 manufacture graph，而不是在辅助模式中执行。",
                "如果用户询问当前工作区，直接说明 workspace path；package 文件若存在，位于 workspace 根目录。",
                "所有文件查看行为都必须通过已绑定只读工具和 Gateway 完成。",
                attachments,
                f"Workspace: {workspace.root}",
                f"Package manifest: {workspace.package_manifest_path()}",
                f"Package manifest exists: {workspace.package_manifest_path().exists()}",
                f"Read-only assist tools: {', '.join(tool.name for tool in tools) if tools else 'none'}",
            ]
            if item
        )
    )
    return system_messages_first([system, *list(state.get("messages") or [])])


def _operation_prompt(messages: list[BaseMessage]) -> tuple[dict[str, Any], list[BaseMessage]]:
    if messages and isinstance(messages[0], SystemMessage):
        return {"template": str(messages[0].content or "")}, messages[1:]
    return {}, messages


def _emit_tool_activity(payload: dict[str, Any]) -> None:
    writer = get_stream_writer()
    writer({"type": "tool_activity", "payload": {"events": [payload]}})


def _message_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(content or "")
