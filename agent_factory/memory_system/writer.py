from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from langgraph.store.base import BaseStore

from agent_factory.memory_system.schema import (
    MemoryExtractionAction,
    MemoryExtractionDecision,
    MemoryWriteJob,
    MemoryWriteReport,
)


class MemoryWriteError(RuntimeError):
    pass


class MemoryStoreWriter:
    def __init__(self, store: BaseStore) -> None:
        self.store = store

    def apply(self, *, job: MemoryWriteJob, decision: MemoryExtractionDecision) -> MemoryWriteReport:
        started = perf_counter()
        counts = {"add": 0, "update": 0, "delete": 0, "noop": 0}
        try:
            for action in decision.actions:
                self._apply_action(job=job, action=action)
                counts[action.action] = counts.get(action.action, 0) + 1
            status = "noop" if not decision.actions or counts.get("noop", 0) == len(decision.actions) else "completed"
            return MemoryWriteReport(
                job_id=job.job_id,
                status=status,
                namespace=job.namespace,
                action_counts=counts,
                duration_ms=int((perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return MemoryWriteReport(
                job_id=job.job_id,
                status="failed",
                namespace=job.namespace,
                action_counts=counts,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((perf_counter() - started) * 1000),
            )

    def _apply_action(self, *, job: MemoryWriteJob, action: MemoryExtractionAction) -> None:
        if action.action == "noop":
            return
        if action.action == "delete":
            if not action.merge_target_id:
                raise MemoryWriteError("delete action requires merge_target_id")
            self.store.delete(job.namespace, action.merge_target_id)
            return
        if action.action == "update":
            if not action.merge_target_id:
                raise MemoryWriteError("update action requires merge_target_id")
            existing = self.store.get(job.namespace, action.merge_target_id)
            if existing is None:
                raise MemoryWriteError(f"cannot update missing memory: {action.merge_target_id}")
            value = dict(existing.value or {})
            value["content"] = action.content or str(value.get("content") or "")
            value["kind"] = action.kind or str(value.get("kind") or "fact")
            value["metadata"] = {**dict(value.get("metadata") or {}), **_metadata(action)}
            value["updated_at"] = datetime.now(UTC).isoformat()
            self.store.put(job.namespace, action.merge_target_id, value)
            return
        if action.action == "add":
            if not action.kind:
                raise MemoryWriteError("add action requires kind")
            if not action.content.strip():
                raise MemoryWriteError("add action requires content")
            now = datetime.now(UTC).isoformat()
            memory_id = uuid4().hex
            record = {
                "memory_id": memory_id,
                "scope": job.scope,
                "kind": action.kind,
                "content": action.content.strip(),
                "metadata": _metadata(action),
                "source": job.source,
                "created_at": now,
                "updated_at": now,
            }
            self.store.put(job.namespace, memory_id, record)
            return
        raise MemoryWriteError(f"unsupported memory action: {action.action}")


def _metadata(action: MemoryExtractionAction) -> dict[str, Any]:
    return {
        **dict(action.metadata or {}),
        "importance": action.importance,
        "confidence": action.confidence,
        "reason": action.reason,
    }
