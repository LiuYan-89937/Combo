from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import os
from pathlib import Path
import shutil
import stat
from tempfile import mkdtemp
from threading import RLock
from typing import Any
from uuid import uuid4

from agent_factory.tooling.builtins.filesystem.common import (
    assert_not_protected_write_path,
    filesystem_boundary,
    resolve_path,
    write_focus_facts,
)
from agent_factory.tooling.builtins.filesystem.workspace_search import workspace_relative_path
from agent_factory.tooling.builtins.filesystem.text_changes import atomic_write_file


DEFAULT_STAGED_WRITE_TTL_SECONDS = 600


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    exists: bool
    content_hash: str | None
    size_bytes: int
    line_count: int
    mode: int | None


@dataclass(slots=True)
class StagedWrite:
    write_id: str
    workspace_root: Path
    target: Path
    staging_root: Path
    staging_file: Path
    snapshot: TargetSnapshot
    create_dirs: bool
    created_at: str
    expires_at: str
    bytes_written: int = 0
    chunk_count: int = 0


class StagedWriteStore:
    def __init__(self) -> None:
        self._writes: dict[str, StagedWrite] = {}
        self._lock = RLock()

    def create(
        self,
        *,
        root: Path,
        target: Path,
        snapshot: TargetSnapshot,
        create_dirs: bool,
    ) -> StagedWrite:
        with self._lock:
            self._discard_expired()
            now = datetime.now(UTC)
            staging_root = Path(mkdtemp(prefix="agentfactory-write-"))
            staged = StagedWrite(
                write_id=uuid4().hex,
                workspace_root=root,
                target=target,
                staging_root=staging_root,
                staging_file=staging_root / "content",
                snapshot=snapshot,
                create_dirs=create_dirs,
                created_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=_staged_write_ttl_seconds())).isoformat(),
            )
            staged.staging_file.touch()
            self._writes[staged.write_id] = staged
            return staged

    def get(self, write_id: str) -> StagedWrite:
        with self._lock:
            self._discard_expired()
            staged = self._writes.get(write_id)
            if staged is None:
                raise ValueError("write_id is unknown or expired; start a new staged write")
            return staged

    def append(self, write_id: str, content: str) -> StagedWrite:
        with self._lock:
            staged = self.get(write_id)
            content_bytes = content.encode("utf-8")
            with staged.staging_file.open("ab") as handle:
                handle.write(content_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            staged.bytes_written += len(content_bytes)
            staged.chunk_count += 1
            return staged

    def take(self, write_id: str) -> StagedWrite:
        with self._lock:
            staged = self.get(write_id)
            self._writes.pop(write_id, None)
            return staged

    def abort(self, write_id: str) -> StagedWrite:
        with self._lock:
            staged = self.get(write_id)
            self._writes.pop(write_id, None)
            _remove_staging(staged)
            return staged

    def _discard_expired(self) -> None:
        now = datetime.now(UTC)
        expired = [
            write_id
            for write_id, staged in self._writes.items()
            if datetime.fromisoformat(staged.expires_at) <= now
        ]
        for write_id in expired:
            staged = self._writes.pop(write_id)
            _remove_staging(staged)


STAGED_WRITE_STORE = StagedWriteStore()


def start_staged_write(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    path = _required_text(arguments, "path")
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(path=path, root=root, allow_external=allow_external)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("staged writes only support paths inside the configured workspace root") from exc
    assert_not_protected_write_path(target, root=root, resources=resources)
    snapshot = _snapshot(target)
    expected_hash = str(arguments.get("expected_hash") or "").strip()
    if expected_hash and expected_hash != snapshot.content_hash:
        raise ValueError("expected_hash does not match current file content")
    staged = STAGED_WRITE_STORE.create(
        root=root,
        target=target,
        snapshot=snapshot,
        create_dirs=bool(arguments.get("create_dirs", True)),
    )
    return {
        "action": "start",
        "status": "staging",
        "write_id": staged.write_id,
        "path": workspace_relative_path(target, workspace_root=root),
        "created_at": staged.created_at,
        "expires_at": staged.expires_at,
        "before_hash": snapshot.content_hash,
        "bytes_written": 0,
        "chunk_count": 0,
    }


def append_staged_write(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    write_id = _required_text(arguments, "write_id")
    content = arguments.get("content")
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    staged = STAGED_WRITE_STORE.get(write_id)
    _validate_workspace(staged, resources)
    staged = STAGED_WRITE_STORE.append(write_id, content)
    return {
        "action": "append",
        "status": "staging",
        "write_id": staged.write_id,
        "path": workspace_relative_path(staged.target, workspace_root=staged.workspace_root),
        "bytes_written": staged.bytes_written,
        "chunk_count": staged.chunk_count,
    }


def commit_staged_write(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    write_id = _required_text(arguments, "write_id")
    _validate_workspace(STAGED_WRITE_STORE.get(write_id), resources)
    staged = STAGED_WRITE_STORE.take(write_id)
    created_directories: list[Path] = []
    try:
        _validate_workspace(staged, resources)
        current = _snapshot(staged.target)
        if current != staged.snapshot:
            raise RuntimeError("target changed after staged write started; start a new staged write")
        if not staged.target.parent.exists():
            if not staged.create_dirs:
                raise FileNotFoundError(str(staged.target.parent))
            created_directories = _ensure_parent_directories(
                staged.target.parent,
                stop=staged.workspace_root,
            )
        after_hash, after_bytes, after_lines = _stream_file_metadata(staged.staging_file)
        atomic_write_file(staged.target, staged.staging_file)
        return {
            "action": "commit",
            "status": "committed",
            "write_id": staged.write_id,
            "path": workspace_relative_path(staged.target, workspace_root=staged.workspace_root),
            "created": not staged.snapshot.exists,
            "bytes_written": after_bytes,
            "chunk_count": staged.chunk_count,
            "before_hash": staged.snapshot.content_hash,
            "after_hash": after_hash,
            "change_summary": {
                "before_bytes": staged.snapshot.size_bytes,
                "after_bytes": after_bytes,
                "before_lines": staged.snapshot.line_count,
                "after_lines": after_lines,
                "added_lines": after_lines,
                "removed_lines": staged.snapshot.line_count,
            },
            "summary_kind": "full_replace",
            "focus": write_focus_facts(
                staged.target,
                root=staged.workspace_root,
                resources=resources,
            ),
        }
    except Exception:
        _remove_empty_directories(created_directories)
        raise
    finally:
        _remove_staging(staged)


def abort_staged_write(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    write_id = _required_text(arguments, "write_id")
    staged = STAGED_WRITE_STORE.get(write_id)
    _validate_workspace(staged, resources)
    staged = STAGED_WRITE_STORE.abort(write_id)
    return {
        "action": "abort",
        "status": "aborted",
        "write_id": staged.write_id,
        "path": workspace_relative_path(staged.target, workspace_root=staged.workspace_root),
        "bytes_written": staged.bytes_written,
        "chunk_count": staged.chunk_count,
    }


def _validate_workspace(staged: StagedWrite, resources: dict[str, Any]) -> None:
    root, _allow_external = filesystem_boundary(resources)
    if root != staged.workspace_root:
        raise ValueError("write_id belongs to a different workspace")
    assert_not_protected_write_path(staged.target, root=root, resources=resources)


def _snapshot(path: Path) -> TargetSnapshot:
    if not path.exists():
        return TargetSnapshot(False, None, 0, 0, None)
    if not path.is_file():
        raise IsADirectoryError(str(path))
    content_hash, size_bytes, line_count = _stream_file_metadata(path)
    return TargetSnapshot(
        True,
        content_hash,
        size_bytes,
        line_count,
        stat.S_IMODE(path.stat().st_mode),
    )


def _stream_file_metadata(path: Path) -> tuple[str, int, int]:
    digest = sha256()
    size_bytes = 0
    newline_count = 0
    last_byte: int | None = None
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size_bytes += len(chunk)
            newline_count += chunk.count(b"\n")
            last_byte = chunk[-1]
    line_count = newline_count + (1 if size_bytes and last_byte != ord("\n") else 0)
    return digest.hexdigest(), size_bytes, line_count


def _ensure_parent_directories(parent: Path, *, stop: Path) -> list[Path]:
    missing: list[Path] = []
    current = parent
    while current != stop and not current.exists():
        missing.append(current)
        current = current.parent
    parent.mkdir(parents=True, exist_ok=True)
    return missing


def _remove_empty_directories(directories: list[Path]) -> None:
    for directory in sorted(set(directories), key=lambda value: len(value.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def _remove_staging(staged: StagedWrite) -> None:
    shutil.rmtree(staged.staging_root, ignore_errors=True)


def _required_text(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _staged_write_ttl_seconds() -> int:
    raw = os.getenv("AGENTFACTORY_STAGED_WRITE_TTL_SECONDS")
    if not raw:
        return DEFAULT_STAGED_WRITE_TTL_SECONDS
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_STAGED_WRITE_TTL_SECONDS
