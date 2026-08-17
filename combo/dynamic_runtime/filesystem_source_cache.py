from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
from stat import S_ISDIR, S_ISLNK, S_ISREG
import tempfile
from threading import RLock

from combo.runtime_protocol import CapabilityDraft


_CACHE_SCHEMA_VERSION = 1
_CACHE_LOCK = RLock()


@dataclass(frozen=True, slots=True)
class CapabilityDraftSource:
    cache_key: str
    directory: Path
    build: Callable[[], CapabilityDraft]


class FileSystemCapabilityDraftCache:
    """Reuse validated filesystem capability drafts while source metadata is unchanged."""

    def __init__(self, *, path: Path, namespace: str) -> None:
        self._path = Path(path).expanduser().resolve()
        self._namespace = str(namespace or "").strip()
        if not self._namespace:
            raise ValueError("filesystem capability cache namespace must not be empty")

    def resolve(self, sources: tuple[CapabilityDraftSource, ...]) -> tuple[CapabilityDraft, ...]:
        with _CACHE_LOCK:
            current = self._load()
            cached_entries = current.get("entries") if isinstance(current.get("entries"), dict) else {}
            resolved: list[CapabilityDraft] = []
            next_entries: dict[str, object] = {}
            for source in sources:
                inventory = _directory_inventory(source.directory)
                cached = cached_entries.get(source.cache_key)
                draft = _cached_draft(cached, inventory)
                if draft is None:
                    draft = source.build()
                resolved.append(draft)
                next_entries[source.cache_key] = {
                    "inventory": inventory,
                    "draft": draft.model_dump(mode="json"),
                }
            next_document = {
                "schema_version": _CACHE_SCHEMA_VERSION,
                "namespace": self._namespace,
                "entries": next_entries,
            }
            if current != next_document:
                self._write(next_document)
            return tuple(resolved)

    def _load(self) -> dict[str, object]:
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(value, dict):
            return {}
        if value.get("schema_version") != _CACHE_SCHEMA_VERSION:
            return {}
        if value.get("namespace") != self._namespace:
            return {}
        return value

    def _write(self, document: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(document, output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)


def _cached_draft(value: object, inventory: list[dict[str, object]]) -> CapabilityDraft | None:
    if not isinstance(value, dict) or value.get("inventory") != inventory:
        return None
    try:
        return CapabilityDraft.model_validate(value.get("draft"))
    except (TypeError, ValueError):
        return None


def _directory_inventory(directory: Path) -> list[dict[str, object]]:
    root = Path(directory).expanduser().resolve()
    inventory: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        metadata = path.lstat()
        mode = metadata.st_mode
        kind = "file" if S_ISREG(mode) else "directory" if S_ISDIR(mode) else "symlink" if S_ISLNK(mode) else "other"
        inventory.append({
            "path": path.relative_to(root).as_posix(),
            "kind": kind,
            "size": metadata.st_size,
            "modified_ns": metadata.st_mtime_ns,
        })
    return inventory
