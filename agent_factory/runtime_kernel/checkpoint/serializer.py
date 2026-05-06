from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from agent_factory.runtime_kernel.checkpoint.schema import CheckpointRecord
from agent_factory.runtime_kernel.state import RuntimeState


class CheckpointSerializer:
    def to_record(
        self,
        *,
        state: RuntimeState,
        reason: str,
    ) -> CheckpointRecord:
        return CheckpointRecord(
            run_ref={
                "run_id": state.run.run_id,
                "agent_id": state.run.agent_id,
                "session_id": state.run.session_id,
                "pattern_id": state.run.pattern_id,
                "pattern_version": state.run.pattern_version,
            },
            execution_ref={
                "current_node": state.execution.current_node,
                "current_subgraph": state.execution.current_subgraph,
                "route_decision": state.execution.route_decision,
                "turn_count": state.execution.turn_count,
                "max_turns": state.execution.max_turns,
                "finished": state.execution.finished,
                "finish_status": state.execution.finish_status,
            },
            state_snapshot=state.model_dump(mode="json"),
            interrupt_snapshot={
                "interrupted": state.execution.interrupted or state.policy.interrupted,
                "interrupt_type": state.policy.interrupt_type,
                "interrupt_payload": state.execution.interrupt_payload,
                "approval_required": state.policy.approval_required,
                "resume_token": state.execution.resume_token or uuid4().hex,
            },
            observability_ref={
                "trace_id": state.observability.trace_id,
                "span_id": state.observability.span_stack[-1].get("span_id")
                if state.observability.span_stack
                else None,
                "event_offset": len(state.observability.events),
                "debug_refs": state.observability.debug_refs,
            },
            metadata={
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "created_by": "runtime_kernel",
            },
        )

    def from_record(self, record: CheckpointRecord) -> RuntimeState:
        return RuntimeState.model_validate(record.state_snapshot)
