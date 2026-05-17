from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.config import get_stream_writer

from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.runtime_render import NodeRenderSpec, RuntimeRenderEvent
from agent_factory.runtime_render.schema import RuntimeRenderSeverity


FactoryStageRunner = Callable[[FactoryGraphState], dict[str, Any]]


def wrap_factory_node(
    *,
    node_id: str,
    runner: FactoryStageRunner,
    render_spec: NodeRenderSpec,
) -> FactoryStageRunner:
    def wrapped(state: FactoryGraphState) -> dict[str, Any]:
        _emit_node_event(
            event_type="node_started",
            render_spec=render_spec,
            severity="info",
            payload={
                "purpose": render_spec.purpose,
                "doing": render_spec.doing,
                "expected_output": render_spec.expected_output,
                "visible_to_user": render_spec.visible_to_user,
            },
        )
        try:
            patch = runner(state)
        except Exception as exc:
            _emit_node_event(
                event_type="node_failed",
                render_spec=render_spec,
                severity="error",
                message=f"{type(exc).__name__}: {exc}",
                payload={"error_summary": f"{type(exc).__name__}: {exc}"},
            )
            raise
        _emit_node_event(
            event_type="node_completed",
            render_spec=render_spec,
            severity="info",
            payload={"output_summary": _output_summary(node_id, patch)},
        )
        return patch

    return wrapped


def _emit_node_event(
    *,
    event_type: str,
    render_spec: NodeRenderSpec,
    severity: RuntimeRenderSeverity,
    payload: dict[str, Any],
    message: str | None = None,
) -> None:
    try:
        writer = get_stream_writer()
        event = RuntimeRenderEvent(
            event_type=event_type,  # type: ignore[arg-type]
            producer_type="factory",
            graph_id="factory_graph",
            stage_id=render_spec.node_id,
            node_id=render_spec.node_id,
            node_label=render_spec.label,
            node_kind=render_spec.kind,
            severity=severity,
            message=message,
            payload=payload,
        )
        writer({"type": "runtime_render_event", "payload": event.model_dump(mode="json")})
    except Exception:
        return


def _output_summary(node_id: str, patch: Any) -> str:
    if not isinstance(patch, dict):
        return "节点已完成。"
    stage_log = patch.get("stage_log") or []
    if isinstance(stage_log, list):
        for item in reversed(stage_log):
            if not isinstance(item, dict):
                continue
            if item.get("stage_id") not in {node_id, None, ""}:
                continue
            message = str(item.get("message") or "").strip()
            if message:
                return message
            status = str(item.get("status") or "").strip()
            if status:
                return f"阶段状态：{status}"
    status = str(patch.get("status") or "").strip()
    if status:
        return f"节点完成，状态：{status}"
    current_stage = str(patch.get("current_stage") or "").strip()
    if current_stage:
        return f"节点完成，当前阶段：{current_stage}"
    return "节点已完成。"
