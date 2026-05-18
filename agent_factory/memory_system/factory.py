from __future__ import annotations

from pathlib import Path
import os
from typing import Any

from agent_factory.memory_system.background import MemoryBackgroundWorker
from agent_factory.memory_system.config import (
    MemoryBackgroundConfig,
    MemoryStoreRuntimeConfig,
    MemorySystemConfig,
)
from agent_factory.memory_system.injection import default_factory_runtime, inject_factory_cross_session_memory
from agent_factory.memory_system.schema import MemoryWriteJob, MemoryWriteReport
from agent_factory.runtime_kernel.persistence import LangGraphStoreConfig, LangGraphStoreFactory


_FACTORY_MEMORY_RUNTIME = None
_FACTORY_MEMORY_WORKER: MemoryBackgroundWorker | None = None


def inject_factory_prompt_memory(*, stage_id: str, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        runtime = _factory_memory_runtime()
        updated, report = inject_factory_cross_session_memory(values=values, runtime=runtime, stage_id=stage_id)
    except Exception as exc:
        return values, {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    context_text = _memory_context_text(updated.get("cross_session_memory") or {})
    if context_text:
        updated["factory_operating_context"] = (
            str(updated.get("factory_operating_context") or "")
            + "\n\n跨会话记忆注入边界：\n"
            + context_text
        )
    return updated, report.model_dump(mode="json")


def _factory_memory_runtime():
    global _FACTORY_MEMORY_RUNTIME
    if _FACTORY_MEMORY_RUNTIME is not None:
        return _FACTORY_MEMORY_RUNTIME
    config = _factory_memory_config()
    handle = LangGraphStoreFactory().build(
        LangGraphStoreConfig(
            backend=config.store.backend,
            path=Path(config.store.path) if config.store.backend == "sqlite" else None,
        )
    )
    _FACTORY_MEMORY_RUNTIME = default_factory_runtime(project_id="default", config=config, store=handle.store)
    return _FACTORY_MEMORY_RUNTIME


def enqueue_factory_memory_write(
    *,
    source: dict[str, Any],
    message_range: dict[str, int],
    messages_delta: list[dict[str, Any]],
) -> MemoryWriteReport:
    runtime = _factory_memory_runtime()
    worker = _factory_memory_worker(runtime)
    job = MemoryWriteJob(
        scope="factory",
        namespace=tuple(runtime.namespace),
        source=source,
        message_range=message_range,
        messages_delta=messages_delta,
    )
    return worker.enqueue(job)


def _factory_memory_worker(runtime) -> MemoryBackgroundWorker:
    global _FACTORY_MEMORY_WORKER
    if _FACTORY_MEMORY_WORKER is not None:
        return _FACTORY_MEMORY_WORKER
    _FACTORY_MEMORY_WORKER = MemoryBackgroundWorker(store=runtime.store, config=runtime.config)
    _FACTORY_MEMORY_WORKER.start()
    runtime.writer = _FACTORY_MEMORY_WORKER
    return _FACTORY_MEMORY_WORKER


def _factory_memory_config() -> MemorySystemConfig:
    backend = os.getenv("AGENTFACTORY_MEMORY_STORE_BACKEND", "sqlite").strip().lower() or "sqlite"
    if backend not in {"sqlite", "memory"}:
        backend = "sqlite"
    path = os.getenv("AGENTFACTORY_MEMORY_STORE_PATH", ".agentfactory/memory/factory.sqlite")
    return MemorySystemConfig(
        store=MemoryStoreRuntimeConfig(backend=backend, path=path),
        background=MemoryBackgroundConfig(journal_root=".agentfactory/memory/jobs"),
    )


def _memory_context_text(pack: dict[str, Any]) -> str:
    items = list(pack.get("items") or [])
    if not items:
        return "本次未检索到可注入的跨会话记忆。"
    lines = [
        "以下是只读跨会话记忆，不写入 messages，不代表本轮用户新输入；仅在与当前阶段有关时参考。"
    ]
    for index, item in enumerate(items, start=1):
        kind = str(item.get("kind") or "fact")
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"{index}. [{kind}] {content}")
    return "\n".join(lines)
