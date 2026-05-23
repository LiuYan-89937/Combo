from __future__ import annotations

from typing import Any

from langchain_core.messages import RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from agent_factory.context_system.events import emit_context_event
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


CONTEXT_PREPARE_SYSTEM_WRAPPER_ID = "system.context_prepare"


class ContextPrepareSystemWrapper:
    wrapper_id = CONTEXT_PREPARE_SYSTEM_WRAPPER_ID
    before_stage = "pre_execute"

    def before(self, *, state: RuntimeState, context: NodeExecutionContext) -> tuple[RuntimeState, dict[str, Any]]:
        if not context.impl.startswith("cognitive."):
            return state, {}
        runtime = getattr(context.services, "context_system", None)
        if runtime is None:
            return state, {}
        emit_context_event(
            services=context.services,
            state=state,
            event_type="context_compression_started",
            node_id=context.node_id,
            payload={"node_id": context.node_id, "status": "started"},
        )
        result = runtime.prepare_before_model_call(
            state=state,
            node_id=context.node_id,
            impl=context.impl,
            messages=list(context.graph_messages or []),
            services=context.services,
            resources=getattr(context.services, "runtime_resources", {}) or {},
        )
        context.graph_messages = list(result.messages)
        patch: dict[str, Any] = {"context": result.state.context.model_dump(mode="json")}
        if result.messages_changed:
            patch["messages"] = [RemoveMessage(id=REMOVE_ALL_MESSAGES), *result.messages]
        return result.state, patch


SYSTEM_CONTEXT_PREPARE_WRAPPER = ContextPrepareSystemWrapper()
