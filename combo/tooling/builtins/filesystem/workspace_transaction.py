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

from combo.tooling.builtins.filesystem.common import (
    assert_not_protected_write_path,
    filesystem_boundary,
    resolve_path,
    require_filesystem_runtime,
    require_file_locks,
)
from combo.tooling.builtins.filesystem.text_changes import text_change_summary
DEFAULT_TRANSACTION_TTL_SECONDS = 600
SUPPORTED_OPERATION_TYPES = frozenset({"create", "write", "replace", "move", "copy", "delete"})


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    exists: bool
    content_hash: str | None
    mode: int | None


@dataclass(frozen=True, slots=True)
class VirtualFile:
    content: bytes
    mode: int | None


@dataclass(frozen=True, slots=True)
class WorkspaceTransactionPlan:
    transaction_id: str
    workspace_root: Path
    created_at: str
    expires_at: str
    operations: tuple[dict[str, Any], ...]
    snapshots: dict[str, FileSnapshot]
    final_files: dict[str, VirtualFile | None]
    affected_files: tuple[dict[str, Any], ...]


class WorkspaceTransactionStore:
    def __init__(self, *, ttl_seconds: int) -> None:
        if ttl_seconds < 60:
            raise ValueError("workspace transaction TTL must be at least 60 seconds")
        self.ttl_seconds = ttl_seconds
        self._plans: dict[str, WorkspaceTransactionPlan] = {}
        self._lock = RLock()

    def put(self, plan: WorkspaceTransactionPlan) -> None:
        with self._lock:
            self._discard_expired()
            self._plans[plan.transaction_id] = plan

    def get(self, transaction_id: str) -> WorkspaceTransactionPlan:
        with self._lock:
            self._discard_expired()
            plan = self._plans.get(transaction_id)
            if plan is None:
                raise ValueError("transaction_id is unknown or expired; generate a new preview")
            return plan

    def remove(self, transaction_id: str) -> None:
        with self._lock:
            self._plans.pop(transaction_id, None)

    def commit_lock(self) -> RLock:
        return self._lock

    def _discard_expired(self) -> None:
        now = datetime.now(UTC)
        expired = [
            transaction_id
            for transaction_id, plan in self._plans.items()
            if datetime.fromisoformat(plan.expires_at) <= now
        ]
        for transaction_id in expired:
            self._plans.pop(transaction_id, None)


def preview_transaction(
    operations: list[dict[str, Any]],
    resources: dict[str, Any],
) -> dict[str, Any]:
    root, allow_external = filesystem_boundary(resources)
    snapshots: dict[str, FileSnapshot] = {}
    original_files: dict[str, VirtualFile | None] = {}
    virtual_files: dict[str, VirtualFile | None] = {}
    normalized_operations: list[dict[str, Any]] = []

    def current_file(path_value: str) -> tuple[str, Path, VirtualFile | None]:
        target = resolve_path(path=path_value, root=root, allow_external=allow_external)
        try:
            relative = target.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(
                "workspace transactions only support paths inside the configured workspace root"
            ) from exc
        assert_not_protected_write_path(target, root=root, resources=resources)
        if relative not in snapshots:
            snapshot, file_value = _snapshot_file(target)
            snapshots[relative] = snapshot
            original_files[relative] = file_value
            virtual_files[relative] = file_value
        return relative, target, virtual_files[relative]

    for index, raw_operation in enumerate(operations):
        operation = _normalized_operation(raw_operation, index=index)
        operation_type = operation["type"]
        if operation_type in {"create", "write", "replace", "delete"}:
            relative, _target, existing = current_file(operation["path"])
            _validate_expected_hash(operation, existing, key="expected_hash", operation_index=index)
            if operation_type == "create":
                if existing is not None:
                    raise FileExistsError(f"operations[{index}].path already exists: {relative}")
                virtual_files[relative] = VirtualFile(
                    content=operation["content"].encode("utf-8"),
                    mode=None,
                )
            elif operation_type == "write":
                virtual_files[relative] = VirtualFile(
                    content=operation["content"].encode("utf-8"),
                    mode=existing.mode if existing is not None else None,
                )
            elif operation_type == "replace":
                if existing is None:
                    raise FileNotFoundError(relative)
                virtual_files[relative] = VirtualFile(
                    content=_replace_text(existing.content, operation, operation_index=index),
                    mode=existing.mode,
                )
            else:
                if existing is None:
                    raise FileNotFoundError(relative)
                virtual_files[relative] = None
            operation["path"] = relative
        else:
            source_relative, _source, source_value = current_file(operation["source_path"])
            destination_relative, _destination, destination_value = current_file(operation["destination_path"])
            if source_relative == destination_relative:
                raise ValueError(f"operations[{index}] source and destination must differ")
            _validate_expected_hash(operation, source_value, key="expected_hash", operation_index=index)
            if source_value is None:
                raise FileNotFoundError(source_relative)
            if destination_value is not None and not operation["overwrite"]:
                raise FileExistsError(f"operations[{index}].destination_path already exists: {destination_relative}")
            virtual_files[destination_relative] = VirtualFile(
                content=source_value.content,
                mode=source_value.mode,
            )
            if operation_type == "move":
                virtual_files[source_relative] = None
            operation["source_path"] = source_relative
            operation["destination_path"] = destination_relative
        normalized_operations.append(operation)

    final_files = {
        path: value
        for path, value in virtual_files.items()
        if not _same_virtual_file(original_files[path], value)
    }
    if not final_files:
        raise ValueError("transaction does not produce any workspace changes")
    affected_files = tuple(
        _affected_file_record(
            path,
            before=original_files[path],
            after=final_files[path],
        )
        for path in sorted(final_files)
    )
    now = datetime.now(UTC)
    transaction_id = uuid4().hex
    store = _store(resources)
    plan = WorkspaceTransactionPlan(
        transaction_id=transaction_id,
        workspace_root=root,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=store.ttl_seconds)).isoformat(),
        operations=tuple(normalized_operations),
        snapshots=snapshots,
        final_files=final_files,
        affected_files=affected_files,
    )
    store.put(plan)
    return _plan_payload(plan, status="preview_ready")


def commit_transaction(transaction_id: str, resources: dict[str, Any]) -> dict[str, Any]:
    root, _allow_external = filesystem_boundary(resources)
    store = _store(resources)
    with store.commit_lock():
        plan = store.get(transaction_id)
        if plan.workspace_root != root:
            raise ValueError("transaction belongs to a different workspace")
        try:
            targets = tuple(plan.workspace_root / relative for relative in plan.snapshots)
            with require_file_locks(resources).acquire(targets):
                _validate_commit_targets(plan, resources=resources)
                _validate_snapshots(plan)
                _apply_transaction(plan)
        finally:
            store.remove(transaction_id)
    return _plan_payload(plan, status="committed")


def _normalized_operation(value: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"operations[{index}] must be an object")
    operation_type = str(value.get("type") or "").strip()
    if operation_type not in SUPPORTED_OPERATION_TYPES:
        raise ValueError(
            f"operations[{index}].type must be one of {sorted(SUPPORTED_OPERATION_TYPES)}"
        )
    operation: dict[str, Any] = {"type": operation_type}
    if operation_type in {"create", "write", "replace", "delete"}:
        operation["path"] = _required_text(value, "path", index=index)
    else:
        operation["source_path"] = _required_text(value, "source_path", index=index)
        operation["destination_path"] = _required_text(value, "destination_path", index=index)
        operation["overwrite"] = bool(value.get("overwrite", False))
    if operation_type in {"create", "write"}:
        operation["content"] = _string_value(value, "content", index=index)
    if operation_type == "replace":
        operation["old_text"] = _required_text(value, "old_text", index=index)
        operation["new_text"] = _string_value(value, "new_text", index=index)
        operation["replace_all"] = bool(value.get("replace_all", False))
    expected_hash = str(value.get("expected_hash") or "").strip()
    if expected_hash:
        operation["expected_hash"] = expected_hash
    return operation


def _snapshot_file(path: Path) -> tuple[FileSnapshot, VirtualFile | None]:
    if not path.exists():
        return FileSnapshot(False, None, None), None
    if not path.is_file():
        raise IsADirectoryError(str(path))
    content = path.read_bytes()
    mode = stat.S_IMODE(path.stat().st_mode)
    return (
        FileSnapshot(True, sha256(content).hexdigest(), mode),
        VirtualFile(content=content, mode=mode),
    )


def _validate_expected_hash(
    operation: dict[str, Any],
    file_value: VirtualFile | None,
    *,
    key: str,
    operation_index: int,
) -> None:
    expected = str(operation.get(key) or "").strip()
    if not expected:
        return
    actual = sha256(file_value.content).hexdigest() if file_value is not None else None
    if actual != expected:
        raise ValueError(
            f"operations[{operation_index}].{key} does not match current file content"
        )


def _replace_text(content: bytes, operation: dict[str, Any], *, operation_index: int) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"operations[{operation_index}] target is not valid utf-8 text") from exc
    old_text = operation["old_text"]
    count = text.count(old_text)
    if count == 0:
        raise ValueError(f"operations[{operation_index}].old_text was not found")
    if not operation["replace_all"] and count != 1:
        raise ValueError(
            f"operations[{operation_index}].old_text matched {count} times; "
            "set replace_all=true or provide a more specific old_text"
        )
    updated = (
        text.replace(old_text, operation["new_text"])
        if operation["replace_all"]
        else text.replace(old_text, operation["new_text"], 1)
    )
    operation["replacements"] = count if operation["replace_all"] else 1
    return updated.encode("utf-8")


def _validate_snapshots(plan: WorkspaceTransactionPlan) -> None:
    stale_paths: list[str] = []
    for relative, expected in plan.snapshots.items():
        current, _file_value = _snapshot_file(plan.workspace_root / relative)
        if (
            current.exists != expected.exists
            or current.content_hash != expected.content_hash
            or current.mode != expected.mode
        ):
            stale_paths.append(relative)
    if stale_paths:
        raise RuntimeError(
            "workspace changed after preview; create a new transaction preview. stale_paths="
            + ", ".join(sorted(stale_paths))
        )


def _validate_commit_targets(
    plan: WorkspaceTransactionPlan,
    *,
    resources: dict[str, Any],
) -> None:
    for relative in plan.final_files:
        target = resolve_path(
            path=relative,
            root=plan.workspace_root,
            allow_external=False,
        )
        assert_not_protected_write_path(
            target,
            root=plan.workspace_root,
            resources=resources,
        )


def _apply_transaction(plan: WorkspaceTransactionPlan) -> None:
    staging_root = Path(mkdtemp(prefix=".combo-edit-", dir=str(plan.workspace_root)))
    backup_root = staging_root / "backups"
    prepared_root = staging_root / "prepared"
    created_directories: list[Path] = []
    try:
        for index, (relative, final_value) in enumerate(sorted(plan.final_files.items())):
            target = plan.workspace_root / relative
            if target.exists():
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            if final_value is not None:
                prepared = prepared_root / str(index)
                prepared.parent.mkdir(parents=True, exist_ok=True)
                prepared.write_bytes(final_value.content)
                if final_value.mode is not None:
                    prepared.chmod(final_value.mode)

        try:
            for relative in sorted(plan.final_files, key=lambda value: len(Path(value).parts), reverse=True):
                target = plan.workspace_root / relative
                if target.exists():
                    target.unlink()
            for index, (relative, final_value) in enumerate(sorted(plan.final_files.items())):
                if final_value is None:
                    continue
                target = plan.workspace_root / relative
                created_directories.extend(_ensure_parent_directories(target.parent, stop=plan.workspace_root))
                prepared = prepared_root / str(index)
                prepared.replace(target)
        except Exception as apply_error:
            try:
                _rollback_transaction(
                    plan,
                    backup_root=backup_root,
                    created_directories=created_directories,
                )
            except Exception as rollback_error:
                raise RuntimeError(
                    "workspace transaction apply failed and rollback was incomplete; "
                    f"apply_error={apply_error}; rollback_error={rollback_error}"
                ) from apply_error
            raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _rollback_transaction(
    plan: WorkspaceTransactionPlan,
    *,
    backup_root: Path,
    created_directories: list[Path],
) -> None:
    rollback_errors: list[str] = []
    for relative in sorted(plan.final_files, key=lambda value: len(Path(value).parts), reverse=True):
        target = plan.workspace_root / relative
        try:
            if target.exists():
                target.unlink()
            backup = backup_root / relative
            if backup.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
        except OSError as exc:
            rollback_errors.append(f"{relative}: {exc}")
    for directory in sorted(set(created_directories), key=lambda value: len(value.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    if rollback_errors:
        raise RuntimeError("workspace transaction rollback failed: " + "; ".join(rollback_errors))


def _ensure_parent_directories(parent: Path, *, stop: Path) -> list[Path]:
    missing: list[Path] = []
    current = parent
    while current != stop and not current.exists():
        missing.append(current)
        current = current.parent
    parent.mkdir(parents=True, exist_ok=True)
    return missing


def _affected_file_record(
    path: str,
    *,
    before: VirtualFile | None,
    after: VirtualFile | None,
) -> dict[str, Any]:
    if before is None:
        change_type = "created"
    elif after is None:
        change_type = "deleted"
    else:
        change_type = "modified"
    return {
        "path": path,
        "change_type": change_type,
        "before_hash": sha256(before.content).hexdigest() if before is not None else None,
        "after_hash": sha256(after.content).hexdigest() if after is not None else None,
        "change_summary": _content_change_summary(before, after),
    }


def _content_change_summary(
    before: VirtualFile | None,
    after: VirtualFile | None,
) -> dict[str, int]:
    before_content = before.content if before is not None else b""
    after_content = after.content if after is not None else b""
    try:
        return text_change_summary(
            before_content.decode("utf-8"),
            after_content.decode("utf-8"),
        )
    except UnicodeDecodeError:
        return {
            "before_bytes": len(before_content),
            "after_bytes": len(after_content),
            "before_lines": 0,
            "after_lines": 0,
            "added_lines": 0,
            "removed_lines": 0,
        }


def _same_virtual_file(left: VirtualFile | None, right: VirtualFile | None) -> bool:
    if left is None or right is None:
        return left is right
    return left.content == right.content


def _plan_payload(plan: WorkspaceTransactionPlan, *, status: str) -> dict[str, Any]:
    return {
        "transaction_id": plan.transaction_id,
        "status": status,
        "created_at": plan.created_at,
        "expires_at": plan.expires_at,
        "operations_count": len(plan.operations),
        "affected_files": [dict(item) for item in plan.affected_files],
    }


def _required_text(value: dict[str, Any], key: str, *, index: int) -> str:
    text = value.get(key)
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"operations[{index}].{key} must be a non-empty string")
    return text.strip()


def _string_value(value: dict[str, Any], key: str, *, index: int) -> str:
    text = value.get(key)
    if not isinstance(text, str):
        raise ValueError(f"operations[{index}].{key} must be a string")
    return text


def _store(resources: dict[str, Any]) -> WorkspaceTransactionStore:
    store = require_filesystem_runtime(resources).transaction_store
    if not isinstance(store, WorkspaceTransactionStore):
        raise RuntimeError("filesystem transaction store is not configured")
    return store
