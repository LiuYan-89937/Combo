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
from agent_factory.tooling.langgraph_node import build_tool_node_runner, latest_ai_tool_calls


class CreateAgentAssistState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    workspace_path: str
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
        model = self.model or get_main_model()
        if model is None:
            raise RuntimeError("main model is not configured for create-agent assist")
        messages = _messages_with_system(state, self.tools)
        response = model.bind_tools(self.tools, tool_choice="auto").invoke(messages) if self.tools else model.invoke(messages)
        if not isinstance(response, BaseMessage):
            response = AIMessage(content=str(response))
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
    system = SystemMessage(
        content="\n\n".join(
            [
                "你是 FastAgentFactory 的 /create-agent 辅助模式。",
                "当前用户请求不是制造 AgentPackage。像 chat 一样回答，必要时通过已绑定工具读取或操作当前 create-agent 工作区。",
                "不要启动制造循环，不要创建 repair todo，不要运行 package validator，除非用户明确要求制造、修复或验证 AgentPackage。",
                "如果用户询问当前工作区，直接说明 workspace path；package 文件若存在，位于 workspace 根目录。",
                "所有文件、skill、MCP 和 shell 行为都必须通过已绑定工具和 Gateway 完成。",
                f"Workspace: {workspace.root}",
                f"Package manifest: {workspace.package_manifest_path()}",
                f"Package manifest exists: {workspace.package_manifest_path().exists()}",
                f"Bound tools: {', '.join(tool.name for tool in tools) if tools else 'none'}",
            ]
        )
    )
    return [system, *list(state.get("messages") or [])]


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
