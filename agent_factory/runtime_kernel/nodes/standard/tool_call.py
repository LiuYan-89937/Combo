from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


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
        pending = state.tools.pending_tool_call
        if not pending:
            return {"execution": {"current_node": context.node_id, "route_decision": "tool.completed"}}

        binding_payload = _first_binding_payload(context.bindings) or {}
        allowed = set(binding_payload.get("allowed_tool_ids") or [])
        tool_id = str(pending.get("tool_id") or "")
        if allowed and tool_id not in allowed:
            return {
                "tools": {
                    "tool_failures": [
                        {
                            "tool_id": tool_id,
                            "error": "tool_not_allowed",
                        }
                    ]
                },
                "policy": {
                    "blocked": True,
                    "block_reason": f"Tool not allowed: {tool_id}",
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": "policy.blocked",
                },
            }

        registry = context.services.tool_registry
        if registry is None:
            return {
                "tools": {
                    "tool_failures": [{"tool_id": tool_id, "error": "tool_registry_missing"}]
                },
                "execution": {"current_node": context.node_id, "route_decision": "tool.failed"},
            }

        context.emit_event({"event_type": "tool_started", "tool_id": tool_id})
        result = registry.execute(tool_id, dict(pending.get("arguments") or {}), state=state)
        if result.status == "interrupted":
            context.emit_event({"event_type": "interrupt_triggered", "phase": "tool", "tool_id": tool_id})
            return {
                "policy": {
                    "approval_required": True,
                    "interrupt_required": True,
                    "interrupted": True,
                    "interrupt_type": result.interrupt_type or "tool_interrupt",
                },
                "execution": {
                    "current_node": context.node_id,
                    "interrupted": True,
                    "route_decision": "tool.interrupted",
                },
            }
        if result.status == "failed":
            context.emit_event({"event_type": "tool_failed", "tool_id": tool_id, "error": result.error})
            failures = list(state.tools.tool_failures)
            failures.append(result.model_dump(mode="json"))
            return {
                "messages": [
                    ToolMessage(
                        content=str(result.error or "tool failed"),
                        tool_call_id=str(pending.get("tool_call_id") or tool_id),
                    )
                ],
                "tools": {
                    "tool_failures": failures,
                    "pending_tool_call": None,
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": "tool.failed",
                },
            }
        context.emit_event({"event_type": "tool_completed", "tool_id": tool_id})
        results = list(state.tools.tool_results)
        results.append(result.model_dump(mode="json"))
        return {
            "messages": [
                ToolMessage(
                    content=str(result.output),
                    tool_call_id=str(pending.get("tool_call_id") or tool_id),
                )
            ],
            "tools": {
                "tool_results": results,
                "last_tool_result": result.model_dump(mode="json"),
                "pending_tool_call": None,
            },
            "execution": {
                "current_node": context.node_id,
                "route_decision": "tool.completed",
            },
        }


def _first_binding_payload(bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bindings:
        return None
    return dict(bindings[0].get("payload") or {})
