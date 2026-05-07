from __future__ import annotations

from typing import Annotated, Any, TypedDict
import operator

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent_factory.factory_graph.tool_approval import (
    FACTORY_TOOL_APPROVAL_NODE,
    approve_tool_calls,
    route_after_tool_approval,
)
from agent_factory.factory_graph.tools import (
    get_factory_graph_tools,
    get_factory_model_tools,
    get_factory_protected_tool_ids,
)
from agent_factory.models import get_task_model, get_task_model_settings
from agent_factory.prompts import PromptId, get_prompt


FACTORY_CHAT_MODEL_NODE = "chat_model"
FACTORY_CHAT_TOOLS_NODE = "chat_tools"


class FactoryChatState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], operator.add]
    status: str
    protected_tool_ids: list[str]
    tool_approval: dict[str, Any]
    errors: Annotated[list[dict[str, Any]], operator.add]


def build_factory_chat_graph(
    *,
    tools: list[BaseTool] | None = None,
    enable_interrupts: bool = False,
    checkpointer: BaseCheckpointSaver | None = None,
):
    graph = StateGraph(FactoryChatState)
    graph.add_node(FACTORY_CHAT_MODEL_NODE, _chat_model_node)
    graph.add_node(FACTORY_TOOL_APPROVAL_NODE, approve_tool_calls)
    graph.add_node(
        FACTORY_CHAT_TOOLS_NODE,
        ToolNode(tools or get_factory_graph_tools(), name=FACTORY_CHAT_TOOLS_NODE),
    )
    graph.add_edge(START, FACTORY_CHAT_MODEL_NODE)
    graph.add_conditional_edges(
        FACTORY_CHAT_MODEL_NODE,
        _route_after_chat_model,
        {
            FACTORY_TOOL_APPROVAL_NODE: FACTORY_TOOL_APPROVAL_NODE,
            END: END,
        },
    )
    graph.add_conditional_edges(
        FACTORY_TOOL_APPROVAL_NODE,
        _route_after_tool_approval,
        {
            FACTORY_CHAT_TOOLS_NODE: FACTORY_CHAT_TOOLS_NODE,
            FACTORY_CHAT_MODEL_NODE: FACTORY_CHAT_MODEL_NODE,
        },
    )
    graph.add_edge(FACTORY_CHAT_TOOLS_NODE, FACTORY_CHAT_MODEL_NODE)
    resolved_checkpointer = checkpointer if checkpointer is not None else _default_checkpointer(enable_interrupts)
    return graph.compile(checkpointer=resolved_checkpointer)


def _chat_model_node(state: FactoryChatState) -> dict[str, Any]:
    task_model = get_task_model()
    task_settings = get_task_model_settings()
    if task_model is None:
        return _model_error("task model is not configured")
    try:
        prompt_value = get_prompt(PromptId.FACTORY_CHAT).invoke(
            {"messages": state.get("messages", [])}
        )
        chat_model = task_model.bind_tools(get_factory_model_tools())
        if task_settings.max_tokens is not None:
            chat_model = chat_model.bind(max_tokens=task_settings.max_tokens)
        response = chat_model.invoke(prompt_value)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        return {
            "messages": [response],
            "status": "running" if response.tool_calls else "answered",
        }
    except Exception as exc:
        return _model_error(f"{type(exc).__name__}: {exc}")


def _route_after_chat_model(state: FactoryChatState) -> str:
    if state.get("status") == "failed":
        return END
    messages = state.get("messages") or []
    if messages and getattr(messages[-1], "tool_calls", None):
        return FACTORY_TOOL_APPROVAL_NODE
    return END


def _route_after_tool_approval(state: FactoryChatState) -> str:
    return route_after_tool_approval(
        state,
        approved=FACTORY_CHAT_TOOLS_NODE,
        denied=FACTORY_CHAT_MODEL_NODE,
    )


def _model_error(message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "messages": [AIMessage(content=f"模型调用失败：{message}")],
        "errors": [{"where": FACTORY_CHAT_MODEL_NODE, "message": message}],
    }


def initial_factory_chat_state(messages: list[BaseMessage]) -> FactoryChatState:
    return {
        "messages": messages,
        "status": "running",
        "protected_tool_ids": get_factory_protected_tool_ids(),
        "errors": [],
    }


def _default_checkpointer(enable_interrupts: bool) -> BaseCheckpointSaver | None:
    if not enable_interrupts:
        return None
    return InMemorySaver()
