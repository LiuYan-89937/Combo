from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent_factory.factory_package.constants import STAGE_IDS
from agent_factory.factory_package.runtime_context import factory_package_node_context
from agent_factory.factory_package.stages import FACTORY_STAGE_HANDLERS
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.node_providers import StaticNodeProvider
from agent_factory.runtime_kernel.state import RuntimeState


FACTORY_MANUFACTURING_NAMESPACE = "factory_manufacturing"
FACTORY_NODE_PROVIDER_ID = "builtin.factory_manufacturing_nodes"


def factory_manufacturing_node_provider() -> StaticNodeProvider:
    return StaticNodeProvider(
        provider_id=FACTORY_NODE_PROVIDER_ID,
        nodes=tuple(FactoryManufacturingStageNode(stage_id) for stage_id in STAGE_IDS),
    )


@dataclass(frozen=True, slots=True)
class FactoryManufacturingStageNode:
    stage_id: str

    node_type = "cognitive"
    supports_interrupt = True
    supports_subgraph_slot = False
    writable_sections = {"package_state", "conversation", "execution", "observability"}

    @property
    def impl_id(self) -> str:
        return f"builtin.factory.{self.stage_id}"

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        handler = FACTORY_STAGE_HANDLERS[self.stage_id]
        namespace_state = _initial_stage_state(state)
        stage_state = {**namespace_state, "messages": list(context.graph_messages or [])}
        with factory_package_node_context(context):
            patch = dict(handler(stage_state) or {})
        next_namespace_state = _merge_stage_state(namespace_state, patch)
        execution_patch = _execution_patch(
            state=state,
            stage_id=self.stage_id,
            namespace_state=next_namespace_state,
        )
        result: dict[str, Any] = {
            "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_namespace_state},
            "execution": execution_patch,
        }
        if "messages" in patch:
            result["messages"] = patch["messages"]
        final_answer = _stage_final_answer(next_namespace_state)
        if final_answer:
            result["conversation"] = {"final_answer": final_answer}
        return result


def _initial_stage_state(state: RuntimeState) -> dict[str, Any]:
    existing = dict(state.package_state.get(FACTORY_MANUFACTURING_NAMESPACE) or {})
    if not existing.get("factory_run_id"):
        existing["factory_run_id"] = uuid4().hex
    if not existing.get("status"):
        existing["status"] = "running"
    current_input = (state.conversation.current_user_input or "").strip()
    if current_input and not existing.get("requirement"):
        existing["requirement"] = current_input
    if current_input and not existing.get("interaction_mode"):
        existing["interaction_mode"] = "create_agent"
    if "model_activity" not in existing:
        existing["model_activity"] = []
    if "stage_log" not in existing:
        existing["stage_log"] = []
    if "errors" not in existing:
        existing["errors"] = []
    return existing


def _merge_stage_state(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if key == "messages":
            continue
        if key in {"stage_log", "errors"} and isinstance(value, list):
            merged[key] = [*list(merged.get(key) or []), *value]
            continue
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(dict(merged[key]), value)
            continue
        merged[key] = value
    return merged


def _merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(current, value)
        else:
            merged[key] = value
    return merged


def _execution_patch(*, state: RuntimeState, stage_id: str, namespace_state: dict[str, Any]) -> dict[str, Any]:
    status = str(namespace_state.get("status") or "running")
    graph_control = namespace_state.get("graph_control") if isinstance(namespace_state.get("graph_control"), dict) else {}
    stop_after_stage = str(state.runtime_config.user_config.get("stop_after_stage") or "").strip()
    terminal = (
        status in {"failed", "blocked"}
        or graph_control.get("action") == "end"
        or bool(stop_after_stage and stop_after_stage == stage_id)
        or stage_id == STAGE_IDS[-1]
    )
    patch: dict[str, Any] = {
        "current_node": stage_id,
        "route_decision": "factory.continue",
    }
    if terminal:
        patch.update(
            {
                "finished": True,
                "finish_status": _finish_status(status),
                "route_decision": "execution.finished",
            }
        )
        if status == "failed":
            patch["last_error"] = _last_error(namespace_state) or "Factory package stage failed."
            patch["last_error_location"] = stage_id
    return patch


def _finish_status(status: str) -> str:
    if status == "failed":
        return "failed"
    if status == "blocked":
        return "blocked"
    return "completed"


def _last_error(namespace_state: dict[str, Any]) -> str | None:
    errors = namespace_state.get("errors")
    if isinstance(errors, list) and errors:
        item = errors[-1]
        if isinstance(item, dict):
            return str(item.get("message") or item)
        return str(item)
    return None


def _stage_final_answer(namespace_state: dict[str, Any]) -> str | None:
    factory_response = namespace_state.get("factory_response")
    if isinstance(factory_response, dict):
        text = factory_response.get("message") or factory_response.get("content")
        if text:
            return str(text)
    finalization_report = namespace_state.get("finalization_report")
    if isinstance(finalization_report, dict) and finalization_report.get("summary"):
        return str(finalization_report["summary"])
    return None
