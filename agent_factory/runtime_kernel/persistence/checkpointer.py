from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


LangGraphCheckpointerBackend = Literal["sqlite", "memory"]

_CHECKPOINTER_CONTEXTS: list[object] = []
_PERSISTENT_CHECKPOINTER_IDS: set[int] = set()


@dataclass(frozen=True, slots=True)
class LangGraphCheckpointerConfig:
    backend: LangGraphCheckpointerBackend = "sqlite"
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class LangGraphCheckpointerHandle:
    saver: Any
    backend: LangGraphCheckpointerBackend
    persistent: bool
    path: Path | None = None


class LangGraphCheckpointerFactory:
    def build(self, config: LangGraphCheckpointerConfig) -> LangGraphCheckpointerHandle:
        if config.backend == "memory":
            from langgraph.checkpoint.memory import InMemorySaver

            return LangGraphCheckpointerHandle(
                saver=InMemorySaver(),
                backend="memory",
                persistent=False,
                path=None,
            )
        if config.path is None:
            raise ValueError("SQLite checkpointer requires a checkpoint path.")
        return self._build_sqlite(config.path)

    def _build_sqlite(self, checkpoint_path: Path) -> LangGraphCheckpointerHandle:
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "SQLite checkpointer backend is configured, but langgraph-checkpoint-sqlite "
                "is not installed. Install the SQLite checkpointer package or select memory "
                "for a non-persistent debug run."
            ) from exc
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        saver = _enter_checkpointer_context(SqliteSaver.from_conn_string(str(checkpoint_path)))
        _PERSISTENT_CHECKPOINTER_IDS.add(id(saver))
        return LangGraphCheckpointerHandle(
            saver=saver,
            backend="sqlite",
            persistent=True,
            path=checkpoint_path,
        )


def is_checkpointer_persistent(checkpointer: object | None) -> bool:
    return id(checkpointer) in _PERSISTENT_CHECKPOINTER_IDS


def _enter_checkpointer_context(checkpointer: Any) -> Any:
    if hasattr(checkpointer, "__enter__"):
        _CHECKPOINTER_CONTEXTS.append(checkpointer)
        return checkpointer.__enter__()
    return checkpointer
