from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock


@dataclass(slots=True)
class _FileLockEntry:
    lock: RLock
    references: int = 0


class WorkspaceFileLockManager:
    """Coordinate cooperative workspace writes at canonical file-path granularity."""

    def __init__(self) -> None:
        self._entries: dict[Path, _FileLockEntry] = {}
        self._registry_lock = RLock()

    @contextmanager
    def acquire(self, paths: Iterable[Path]) -> Iterator[tuple[Path, ...]]:
        canonical_paths = _canonical_paths(paths)
        if not canonical_paths:
            raise ValueError("file lock acquisition requires at least one path")
        entries = self._retain(canonical_paths)
        acquired: list[_FileLockEntry] = []
        try:
            for entry in entries:
                entry.lock.acquire()
                acquired.append(entry)
            yield canonical_paths
        finally:
            for entry in reversed(acquired):
                entry.lock.release()
            self._release(canonical_paths, entries)

    def _retain(self, paths: tuple[Path, ...]) -> tuple[_FileLockEntry, ...]:
        with self._registry_lock:
            entries = []
            for path in paths:
                entry = self._entries.get(path)
                if entry is None:
                    entry = _FileLockEntry(lock=RLock())
                    self._entries[path] = entry
                entry.references += 1
                entries.append(entry)
            return tuple(entries)

    def _release(
        self,
        paths: tuple[Path, ...],
        entries: tuple[_FileLockEntry, ...],
    ) -> None:
        with self._registry_lock:
            for path, entry in zip(paths, entries, strict=True):
                current = self._entries.get(path)
                if current is not entry:
                    raise RuntimeError("workspace file lock registry identity changed")
                entry.references -= 1
                if entry.references < 0:
                    raise RuntimeError("workspace file lock reference count underflow")
                if entry.references == 0:
                    self._entries.pop(path)


def _canonical_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    unique = {
        Path(path).expanduser().resolve(strict=False)
        for path in paths
    }
    return tuple(sorted(unique, key=lambda path: str(path)))
