from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.tooling.langgraph_node import (
    build_tool_node_runner,
    latest_ai_tool_calls,
    tool_observation_message,
    tool_messages_to_runtime_patch,
)


class OperationalToolCallNode:
    impl_id = "operational.tool_call"
    node_type = "operational"
    supports_interrupt = True
    supports_subgraph_slot = True
    writable_sections = {"tools", "policy", "execution", "observability"}

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        _ai_message, tool_calls = latest_ai_tool_calls(context.graph_messages)
        if not tool_calls:
            return {"execution": {"current_node": context.node_id, "route_decision": "tool.completed"}}

        registry = context.services.tool_registry
        if registry is None or not hasattr(registry, "model_tools"):
            messages = _tool_registry_missing_messages(tool_calls)
            _results, failures, _policy_patch, route_decision = tool_messages_to_runtime_patch(messages)
            return {
                "messages": messages,
                "tools": {
                    "tool_failures": [*state.tools.tool_failures, *failures],
                    "pending_tool_call": None,
                    "pending_tool_calls": [],
                },
                "execution": {"current_node": context.node_id, "route_decision": route_decision},
            }

        visible_tool_ids = _visible_tool_ids(context, registry)
        visible_tools = list(registry.model_tools(visible_tool_ids))
        runner = build_tool_node_runner(
            visible_tools,
            node_id=context.node_id,
            name=context.node_id,
            allowed_tool_ids=set(visible_tool_ids),
            known_tool_ids=set(registry.list_tool_ids()) if hasattr(registry, "list_tool_ids") else set(visible_tool_ids),
            emit_event=context.emit_event,
        )
        output = runner.invoke({"messages": context.graph_messages, "runtime": state.model_dump(mode="json")})
        messages = output.get("messages") or []
        results, failures, policy_patch, route_decision = tool_messages_to_runtime_patch(messages)
        patch: dict[str, Any] = {
            "messages": messages,
            "tools": {
                "tool_results": [*state.tools.tool_results, *results],
                "tool_failures": [*state.tools.tool_failures, *failures],
                "last_tool_result": results[-1] if results else state.tools.last_tool_result,
                "pending_tool_call": None,
                "pending_tool_calls": [],
            },
            "execution": {
                "current_node": context.node_id,
                "route_decision": route_decision,
            },
        }
        if policy_patch:
            patch["policy"] = policy_patch
        return patch


def _visible_tool_ids(context: NodeExecutionContext, registry: Any) -> list[str]:
    return _merge_tool_ids([*_allowed_tool_ids(context), *_system_tool_ids(registry)])


def _system_tool_ids(registry: Any) -> list[str]:
    if not hasattr(registry, "system_tool_ids"):
        return []
    return [str(item) for item in registry.system_tool_ids()]


def _allowed_tool_ids(context: NodeExecutionContext) -> list[str]:
    current_node_tool_ids = _tool_access_ids(context.bindings)
    if current_node_tool_ids:
        return current_node_tool_ids
    return _tool_access_ids(context.all_bindings)


def _tool_access_ids(bindings: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for binding in bindings:
        if binding.get("binding_type") != "tool_access":
            continue
        payload = dict(binding.get("payload") or {})
        for item in payload.get("allowed_tool_ids", []) or []:
            tool_id = str(item)
            if tool_id and tool_id not in seen:
                ids.append(tool_id)
                seen.add(tool_id)
    return ids


def _merge_tool_ids(tool_ids: list[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for tool_id in tool_ids:
        item = str(tool_id).strip()
        if item and item not in seen:
            items.append(item)
            seen.add(item)
    return items


def _tool_registry_missing_messages(tool_calls: list[dict[str, Any]]):
    messages = []
    for call in tool_calls:
        tool_id = str(call.get("name") or "")
        tool_call_id = str(call.get("id") or tool_id)
        messages.append(
            tool_observation_message(
                status="tool_registry_missing",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                message="tool registry missing",
                arguments=dict(call.get("args") or {}),
                retryable=False,
            )
        )
    return messages
