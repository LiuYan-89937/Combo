from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import AbstractSet, Any, Callable, Iterator, Literal, Mapping
from uuid import uuid4

from pydantic import JsonValue

from combo.dynamic_runtime.tool_context_resources import ToolContextResources
from combo.file_atomic import atomic_write_text
from combo.file_lock import exclusive_file_lock
from combo.runtime_protocol import CapabilityRevision


@dataclass(frozen=True, slots=True)
class SourcePackagePublication:
    """Durable source-swap marker shared by Skill and ToolPackage publishing."""

    operation_id: str
    family: Literal["skill", "tool"]
    capability_id: str
    kind: Literal["create", "replace", "delete"]
    target_name: str
    backup_name: str | None
    phase: Literal["publishing", "committed"] = "publishing"

    @classmethod
    @contextmanager
    def staging(cls, root: Path, family: Literal["skill", "tool"]) -> Iterator[Path]:
        """Own preparation and publication under the same cross-process lock."""
        with cls.locked(root, family):
            area = _staging_path(root, family)
            if area.is_symlink():
                raise RuntimeError(f"package staging path must not be a symbolic link: {area}")
            area.mkdir(parents=True, exist_ok=True)
            workspace = Path(tempfile.mkdtemp(dir=area))
            try:
                yield workspace
            finally:
                shutil.rmtree(workspace)

    @staticmethod
    @contextmanager
    def locked(root: Path, family: Literal["skill", "tool"]) -> Iterator[None]:
        with exclusive_file_lock(root / f".{family}-package.lock"):
            yield

    @classmethod
    def recover_source(
        cls,
        root: Path,
        family: Literal["skill", "tool"],
        resources: ToolContextResources | None,
        *,
        on_retired: Callable[[AbstractSet[str]], None],
    ) -> None:
        with cls.locked(root, family):
            pending = cls.pending(root, family)
            if pending is not None:
                pending.recover(root, resources, on_retired=on_retired)
            area = _staging_path(root, family)
            if area.is_symlink():
                raise RuntimeError(f"package staging path must not be a symbolic link: {area}")
            if area.exists():
                shutil.rmtree(area)

    @classmethod
    def begin(
        cls,
        root: Path,
        *,
        family: Literal["skill", "tool"],
        capability_id: str,
        kind: Literal["create", "replace", "delete"],
        target: Path,
        backup: Path | None = None,
    ) -> SourcePackagePublication:
        if target.parent != root or (backup is not None and backup.parent != root):
            raise ValueError("package publication paths must belong to the source root")
        if (kind == "create") != (backup is None):
            raise ValueError("package publication backup does not match its operation")
        if marker_path(root, family).exists():
            raise RuntimeError("an unfinished package publication must be recovered first")
        publication = cls(uuid4().hex, family, capability_id, kind, target.name, backup.name if backup else None)
        _write_marker(root, publication)
        return publication

    @classmethod
    def publish_skill(
        cls,
        *,
        source_root: Path,
        kind: Literal["create", "replace", "delete"],
        staged: Path | None,
        target: Path,
        capability_id: str,
        content_digest: str | None,
        backup: Path | None,
        expected_content_digest: str | None,
        active_revision: Callable[[str], CapabilityRevision | None],
        synchronize: Callable[[], None],
        on_retired: Callable[[AbstractSet[str]], None],
    ) -> None:
        if (kind == "delete") != (staged is None):
            raise ValueError("Skill publication inputs do not match its operation")
        previous = active_revision(capability_id)
        if kind == "create":
            if previous is not None or target.exists():
                raise RuntimeError("skill_already_exists")
        elif previous is None or previous.content_digest != expected_content_digest:
            raise RuntimeError("skill_revision_conflict")
        elif not target.is_dir():
            raise RuntimeError("Skill source is unavailable")
        publication = cls.begin(
            source_root,
            family="skill",
            capability_id=capability_id,
            kind=kind,
            target=target,
            backup=backup,
        )
        try:
            if backup is not None:
                os.replace(target, backup)
            if staged is not None:
                os.replace(staged, target)
            publication.flush_source(source_root)
            synchronize()
            active = active_revision(capability_id)
            if staged is None:
                if active is not None:
                    raise RuntimeError("retired Skill capability is still active")
            elif active is None or active.content_digest != content_digest:
                raise RuntimeError("published Skill revision differs from the validated source")
            publication.mark_committed(source_root)
        except BaseException:
            current = cls.pending(source_root, "skill")
            committed = current is not None and current.phase == "committed"
            publication.recover(source_root, None, on_retired=on_retired)
            if not committed:
                synchronize()
            raise
        else:
            publication.recover(source_root, None, on_retired=on_retired)

    @classmethod
    def publish_tool(
        cls,
        *,
        source_root: Path,
        kind: Literal["create", "replace", "delete"],
        staged: Path | None,
        target: Path,
        capability_id: str,
        content_digest: str | None,
        expected_content_digest: str | None,
        context_schema: Mapping[str, Any],
        values: Mapping[str, JsonValue],
        backup: Path | None,
        previous_revision: int | None,
        previous_context_schema: Mapping[str, Any] | None,
        resources: ToolContextResources,
        active_revision: Callable[[str], CapabilityRevision | None],
        synchronize: Callable[[], None],
        on_retired: Callable[[AbstractSet[str]], None],
    ) -> None:
        if (kind == "delete") != (staged is None):
            raise ValueError("ToolPackage publication inputs do not match its operation")
        previous = active_revision(capability_id)
        if kind == "create":
            if previous is not None or target.exists():
                raise RuntimeError("tool_already_exists")
        elif previous is None or previous.content_digest != expected_content_digest:
            raise RuntimeError("tool_revision_conflict")
        elif not target.is_dir():
            raise RuntimeError("ToolPackage source is unavailable")
        elif previous_revision != previous.revision:
            raise RuntimeError("tool_revision_conflict")
        publication = cls.begin(
            source_root,
            family="tool",
            capability_id=capability_id,
            kind=kind,
            target=target,
            backup=backup,
        )
        try:
            resources.stage_publication(
                operation_id=publication.operation_id,
                values=values,
                context_schema=context_schema,
            )
            if backup is not None:
                os.replace(target, backup)
            if staged is not None:
                os.replace(staged, target)
            publication.flush_source(source_root)
            synchronize()
            active = active_revision(capability_id)
            if staged is None:
                if active is not None:
                    raise RuntimeError("retired ToolPackage capability is still active")
                if previous_revision is None:
                    raise RuntimeError("retired ToolPackage revision is missing")
                committed_revision = previous_revision
            elif active is None or active.content_digest != content_digest:
                raise RuntimeError("published ToolPackage revision differs from the validated source")
            else:
                committed_revision = active.revision
            resources.commit_publication(
                operation_id=publication.operation_id,
                capability_id=capability_id,
                revision=committed_revision,
                context_schema=context_schema,
                previous_revision=previous_revision,
                previous_context_schema=previous_context_schema,
            )
        except BaseException:
            committed = resources.publication_state(publication.operation_id) == "committed"
            publication.recover(source_root, resources, on_retired=on_retired)
            if not committed:
                synchronize()
            raise
        else:
            publication.recover(source_root, resources, on_retired=on_retired)

    @classmethod
    def pending(cls, root: Path, family: Literal["skill", "tool"]) -> SourcePackagePublication | None:
        path = marker_path(root, family)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("package publication marker must be an object")
        publication = cls(
            operation_id=str(data["operation_id"]),
            family=data["family"],
            capability_id=str(data["capability_id"]),
            kind=data["kind"],
            target_name=str(data["target_name"]),
            backup_name=str(data["backup_name"]) if data["backup_name"] is not None else None,
            phase=data["phase"],
        )
        if publication.family != family:
            raise ValueError("package publication family does not match its source")
        if publication.kind not in {"create", "replace", "delete"}:
            raise ValueError("package publication kind is invalid")
        if publication.kind in {"replace", "delete"} and publication.backup_name is None:
            raise ValueError("package publication backup is missing")
        if publication.phase not in {"publishing", "committed"}:
            raise ValueError("package publication phase is invalid")
        publication._paths(root)
        if (
            not publication.capability_id.startswith(f"{family}://")
            or not publication.capability_id.endswith(f"/{publication.target_name}")
        ):
            raise ValueError("package publication identity does not match its source")
        return publication

    def mark_committed(self, root: Path) -> None:
        current = self.pending(root, self.family)
        if current is None or current.operation_id != self.operation_id:
            raise RuntimeError("package publication marker changed before commit")
        _write_marker(root, replace(current, phase="committed"))

    def recover(
        self,
        root: Path,
        resources: ToolContextResources | None,
        *,
        on_retired: Callable[[AbstractSet[str]], None],
    ) -> None:
        current = self.pending(root, self.family)
        if current is None or current.operation_id != self.operation_id:
            raise RuntimeError("package publication marker changed during recovery")
        target, backup = self._paths(root)
        if self.family == "tool":
            if resources is None:
                raise RuntimeError("ToolPackage publication requires resource state")
            state = resources.publication_state(self.operation_id)
        else:
            if resources is not None:
                raise RuntimeError("Skill publication has no resource state")
            state = None
        if current.phase == "committed" and state == "prepared":
            raise RuntimeError("package publication marker conflicts with staged resources")
        if state == "committed" or current.phase == "committed":
            if self.kind == "delete":
                if target.exists():
                    raise RuntimeError("retired package source is still present")
            elif not target.is_dir():
                raise RuntimeError("committed package source is missing")
            if current.phase != "committed":
                _write_marker(root, replace(current, phase="committed"))
            if backup is not None and backup.exists():
                shutil.rmtree(backup)
            if self.kind == "delete":
                on_retired({self.capability_id})
            if state == "committed" and resources is not None:
                resources.release_publication(self.operation_id)
        elif state in {None, "prepared"}:
            if self.kind == "create":
                if target.exists():
                    shutil.rmtree(target)
            elif backup is not None and backup.exists():
                if target.exists():
                    shutil.rmtree(target)
                os.replace(backup, target)
            elif not target.is_dir():
                raise RuntimeError("unfinished package replacement lost its source and backup")
            if resources is not None:
                resources.discard_publication(self.operation_id)
        else:
            raise RuntimeError("package resource publication state is invalid")
        marker_path(root, self.family).unlink()
        _sync_directory(root)

    @staticmethod
    def flush_source(root: Path) -> None:
        _sync_directory(root)

    def _paths(self, root: Path) -> tuple[Path, Path | None]:
        names = [self.target_name]
        if self.backup_name is not None:
            names.append(self.backup_name)
        if any(name in {"", ".", ".."} or Path(name).name != name for name in names):
            raise ValueError("package publication marker contains an invalid path")
        return root / self.target_name, root / self.backup_name if self.backup_name else None


def marker_path(root: Path, family: Literal["skill", "tool"]) -> Path:
    return root / f".{family}-package-publication.json"


def _staging_path(root: Path, family: Literal["skill", "tool"]) -> Path:
    return root / f".{family}-package-staging"


def _write_marker(root: Path, publication: SourcePackagePublication) -> None:
    path = marker_path(root, publication.family)
    document = {
        "operation_id": publication.operation_id,
        "family": publication.family,
        "capability_id": publication.capability_id,
        "kind": publication.kind,
        "target_name": publication.target_name,
        "backup_name": publication.backup_name,
        "phase": publication.phase,
    }
    atomic_write_text(path, json.dumps(document, separators=(",", ":")))
    _sync_directory(root)


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
