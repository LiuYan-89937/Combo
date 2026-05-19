from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime

from agent_factory.tooling.execution_context import tool_call_context


ToolEventCallback = Callable[[dict[str, Any]], None]


class AgentFactoryToolNode:
    """Thin adapter around LangGraph's native ToolNode.

    The adapter keeps ToolNode as the execution primitive while adding
    AgentFactory's shared concerns at the boundary: ordered batching for
    non-concurrent tools, permission observations, tool-call events, and
    normalized ToolMessage observations.
    """

    def __init__(
        self,
        tools: Sequence[BaseTool],
        *,
        node_id: str,
        name: str | None = None,
        messages_key: str = "messages",
        allowed_tool_ids: set[str] | None = None,
        known_tool_ids: set[str] | None = None,
        emit_event: ToolEventCallback | None = None,
        stream_events: bool = False,
    ) -> None:
        self.node_id = node_id
        self.messages_key = messages_key
        self.allowed_tool_ids = set(allowed_tool_ids) if allowed_tool_ids is not None else None
        self.known_tool_ids = set(known_tool_ids or {tool.name for tool in tools})
        self.emit_event = emit_event
        self.stream_events = stream_events
        self._concurrent_by_name = {tool.name: _tool_concurrent(tool) for tool in tools}
        self._tool_node = ToolNode(
            list(tools),
            name=name or node_id,
            messages_key=messages_key,
            wrap_tool_call=self._wrap_tool_call,
        )

    def __call__(
        self,
        state: Mapping[str, Any],
        config: RunnableConfig = None,
        runtime: Runtime = None,
    ) -> dict[str, list[ToolMessage]]:
        return self.invoke(state, config=config, runtime=runtime)

    def invoke(
        self,
        state: Mapping[str, Any],
        config: RunnableConfig = None,
        runtime: Runtime = None,
    ) -> dict[str, list[ToolMessage]]:
        messages = list(state.get(self.messages_key) or [])
        ai_message, tool_calls = latest_ai_tool_calls(messages)
        if ai_message is None or not tool_calls:
            return {self.messages_key: []}
        outputs: list[ToolMessage] = []
        for batch in _tool_call_batches(tool_calls, self._concurrent_by_name):
            batch_state = dict(state)
            batch_state[self.messages_key] = _replace_latest_ai_tool_calls(messages, ai_message, batch)
            raw_output = self._invoke_native_tool_node(batch_state, config=config, runtime=runtime)
            outputs.extend(_messages_from_tool_node_output(raw_output, self.messages_key))
        return {self.messages_key: outputs}

    def _invoke_native_tool_node(
        self,
        state: Mapping[str, Any],
        *,
        config: RunnableConfig,
        runtime: Runtime,
    ) -> Any:
        return self._tool_node.invoke(state, config, runtime=runtime or Runtime())

    def _wrap_tool_call(self, request: ToolCallRequest, execute: Callable[[ToolCallRequest], Any]) -> Any:
        tool_call = dict(request.tool_call)
        tool_id = str(tool_call.get("name") or "")
        tool_call_id = str(tool_call.get("id") or tool_id)
        arguments = dict(tool_call.get("args") or {})
        if self.allowed_tool_ids is not None and tool_id not in self.allowed_tool_ids:
            message = "Tool is not visible to this node."
            payload = _observation_payload(
                status="tool_not_allowed",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                message=message,
                arguments=arguments,
                retryable=False,
            )
            self._emit(
                {
                    "event_type": "tool_failed",
                    "tool_id": tool_id,
                    "tool_call_id": tool_call_id,
                    "arguments": arguments,
                    "status": "failed",
                    "error": message,
                    "observation": payload,
                    "message": message,
                }
            )
            return _tool_message(tool_id=tool_id, tool_call_id=tool_call_id, payload=payload, status="error")
        self._emit(
            {
                "event_type": "tool_started",
                "tool_id": tool_id,
                "tool_call_id": tool_call_id,
                "arguments": arguments,
                "status": "running",
            }
        )
        with tool_call_context(tool_id=tool_id, tool_call_id=tool_call_id):
            result = execute(request)
        if isinstance(result, ToolMessage):
            normalized = _normalize_tool_message(
                result,
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                arguments=arguments,
            )
            event_type = "tool_completed" if _observation_completed(normalized) else "tool_failed"
            self._emit(
                {
                    "event_type": event_type,
                    "tool_id": tool_id,
                    "tool_call_id": tool_call_id,
                    "arguments": arguments,
                    "status": "completed" if event_type == "tool_completed" else "failed",
                    "result": normalized,
                    "output": normalized.get("output"),
                    "observation": normalized,
                    "error": None if event_type == "tool_completed" else normalized.get("message"),
                    "message": str(normalized.get("message") or ""),
                }
            )
            return _tool_message(
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                payload=normalized,
                status="success" if event_type == "tool_completed" else "error",
            )
        self._emit(
            {
                "event_type": "tool_completed",
                "tool_id": tool_id,
                "tool_call_id": tool_call_id,
                "arguments": arguments,
                "status": "completed",
                "message": "Tool returned a LangGraph command.",
            }
        )
        return result

    def _emit(self, payload: dict[str, Any]) -> None:
        if self.emit_event is not None:
            self.emit_event(payload)
        if self.stream_events:
            from agent_factory.runtime_kernel.observability.tool_events import emit_runtime_tool_activity

            emit_runtime_tool_activity(payload, node_id=self.node_id)


def build_tool_node_runner(
    tools: Sequence[BaseTool],
    *,
    node_id: str,
    name: str | None = None,
    messages_key: str = "messages",
    allowed_tool_ids: set[str] | None = None,
    known_tool_ids: set[str] | None = None,
    emit_event: ToolEventCallback | None = None,
    stream_events: bool = False,
) -> AgentFactoryToolNode:
    return AgentFactoryToolNode(
        tools,
        node_id=node_id,
        name=name,
        messages_key=messages_key,
        allowed_tool_ids=allowed_tool_ids,
        known_tool_ids=known_tool_ids,
        emit_event=emit_event,
        stream_events=stream_events,
    )


def latest_ai_tool_calls(messages: Sequence[Any]) -> tuple[AIMessage | None, list[dict[str, Any]]]:
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        calls = getattr(message, "tool_calls", None) or []
        return message, [_normalize_tool_call(item, index=index) for index, item in enumerate(calls)]
    return None, []


def tool_messages_to_runtime_patch(
    messages: Sequence[ToolMessage],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str]:
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    policy_patch: dict[str, Any] = {}
    route_decision = "tool.completed"
    for message in messages:
        payload = _parse_tool_message_content(message.content)
        if not isinstance(payload, dict):
            payload = _observation_payload(
                status="completed" if getattr(message, "status", "success") != "error" else "execution_failed",
                tool_id=str(message.name or ""),
                tool_call_id=str(message.tool_call_id or ""),
                message=str(message.content),
                arguments={},
                output={"value": message.content},
                retryable=getattr(message, "status", "success") == "error",
            )
        if _observation_completed(payload):
            results.append(payload)
            continue
        failures.append(payload)
        if payload.get("status") == "tool_not_allowed":
            route_decision = "policy.blocked"
            policy_patch = {
                "blocked": True,
                "block_reason": str(payload.get("message") or "Tool is not visible to this node."),
            }
        elif route_decision == "tool.completed":
            route_decision = "tool.failed"
    return results, failures, policy_patch, route_decision


def tool_observation_message(
    *,
    status: str,
    tool_id: str,
    tool_call_id: str,
    message: str,
    arguments: dict[str, Any],
    retryable: bool,
) -> ToolMessage:
    return _tool_message(
        tool_id=tool_id,
        tool_call_id=tool_call_id,
        status="success" if status == "completed" else "error",
        payload=_observation_payload(
            status=status,
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            message=message,
            arguments=arguments,
            retryable=retryable,
        ),
    )


def _tool_call_batches(
    tool_calls: Sequence[dict[str, Any]],
    concurrent_by_name: Mapping[str, bool],
) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for call in tool_calls:
        tool_id = str(call.get("name") or "")
        if concurrent_by_name.get(tool_id, True):
            current.append(call)
            continue
        if current:
            batches.append(current)
            current = []
        batches.append([call])
    if current:
        batches.append(current)
    return batches


def _replace_latest_ai_tool_calls(
    messages: Sequence[Any],
    target: AIMessage,
    tool_calls: Sequence[dict[str, Any]],
) -> list[Any]:
    replaced = list(messages)
    for index in range(len(replaced) - 1, -1, -1):
        if replaced[index] is not target:
            continue
        replaced[index] = AIMessage(
            content=target.content,
            additional_kwargs=dict(target.additional_kwargs),
            response_metadata=dict(target.response_metadata),
            name=target.name,
            id=target.id,
            tool_calls=[dict(item) for item in tool_calls],
        )
        break
    return replaced


def _messages_from_tool_node_output(output: Any, messages_key: str) -> list[ToolMessage]:
    if isinstance(output, dict):
        candidates = output.get(messages_key) or []
    elif isinstance(output, list):
        candidates = output
    else:
        candidates = []
    return [item for item in candidates if isinstance(item, ToolMessage)]


def _tool_concurrent(tool: BaseTool) -> bool:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return True
    agent_factory = metadata.get("agent_factory")
    if not isinstance(agent_factory, dict):
        return True
    return bool(agent_factory.get("concurrent", True))


def _normalize_tool_call(item: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    name = str(item.get("name") or item.get("tool_id") or "")
    args = item.get("args") or item.get("arguments") or {}
    return {
        "name": name,
        "args": dict(args) if isinstance(args, dict) else {},
        "id": str(item.get("id") or item.get("tool_call_id") or f"call_{index}_{name}"),
        "type": "tool_call",
    }


def _normalize_tool_message(
    message: ToolMessage,
    *,
    tool_id: str,
    tool_call_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    payload = _parse_tool_message_content(message.content)
    if not isinstance(payload, dict):
        return _observation_payload(
            status="completed" if getattr(message, "status", "success") != "error" else "execution_failed",
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            message=str(message.content),
            arguments=arguments,
            output={"value": message.content},
            retryable=getattr(message, "status", "success") == "error",
        )
    if payload.get("type") != "tool_observation":
        return _observation_payload(
            status=str(payload.get("status") or "completed"),
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            message=str(payload.get("message") or "Tool execution completed."),
            arguments=arguments,
            output=payload,
            retryable=False,
        )
    payload = dict(payload)
    payload["tool_id"] = str(payload.get("tool_id") or tool_id)
    payload["tool_call_id"] = str(payload.get("tool_call_id") or tool_call_id)
    if not isinstance(payload.get("arguments"), dict):
        payload["arguments"] = arguments
    return payload


def _parse_tool_message_content(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    return content


def _observation_completed(payload: dict[str, Any]) -> bool:
    if payload.get("status") != "completed":
        return False
    if payload.get("type") == "tool_observation":
        return True
    return True


def _tool_message(*, tool_id: str, tool_call_id: str, payload: dict[str, Any], status: str = "success") -> ToolMessage:
    return ToolMessage(
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        name=tool_id,
        tool_call_id=tool_call_id,
        status=status,  # type: ignore[arg-type]
    )


def _observation_payload(
    *,
    status: str,
    tool_id: str,
    tool_call_id: str,
    message: str,
    arguments: dict[str, Any],
    retryable: bool,
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "tool_observation",
        "status": status,
        "tool_id": tool_id,
        "tool_call_id": tool_call_id,
        "message": message,
        "retryable": retryable,
        "arguments": arguments,
        "output": output,
        "errors": [] if status == "completed" else [message],
    }
