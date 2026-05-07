from __future__ import annotations

from typing import Annotated, Any, TypedDict
import operator

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent_factory.factory_graph.tools import get_factory_graph_tools, get_factory_model_tools
from agent_factory.models import get_task_model, get_task_model_settings
from agent_factory.prompts import PromptId, get_prompt


FACTORY_CHAT_MODEL_NODE = "chat_model"
FACTORY_CHAT_TOOLS_NODE = "chat_tools"


class FactoryChatState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], operator.add]
    status: str
    errors: Annotated[list[dict[str, Any]], operator.add]


def build_factory_chat_graph(*, tools: list[BaseTool] | None = None):
    graph = StateGraph(FactoryChatState)
    graph.add_node(FACTORY_CHAT_MODEL_NODE, _chat_model_node)
    graph.add_node(
        FACTORY_CHAT_TOOLS_NODE,
        ToolNode(tools or get_factory_graph_tools(), name=FACTORY_CHAT_TOOLS_NODE),
    )
    graph.add_edge(START, FACTORY_CHAT_MODEL_NODE)
    graph.add_conditional_edges(
        FACTORY_CHAT_MODEL_NODE,
        _route_after_chat_model,
        {
            FACTORY_CHAT_TOOLS_NODE: FACTORY_CHAT_TOOLS_NODE,
            END: END,
        },
    )
    graph.add_edge(FACTORY_CHAT_TOOLS_NODE, FACTORY_CHAT_MODEL_NODE)
    return graph.compile()


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
        return FACTORY_CHAT_TOOLS_NODE
    return END


def _model_error(message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "messages": [AIMessage(content=f"模型调用失败：{message}")],
        "errors": [{"where": FACTORY_CHAT_MODEL_NODE, "message": message}],
    }
