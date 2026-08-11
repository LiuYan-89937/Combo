from __future__ import annotations

import json
from hashlib import sha256
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from agent_factory.paths import factory_artifact_path
from agent_factory.runtime_attachments import AttachmentImportPolicy
from agent_factory.runtime_protocol import AttachmentRevisionRef


ATTACHMENT_UPLOAD_TTL_SECONDS_ENV = "AGENTFACTORY_ATTACHMENT_UPLOAD_TTL_SECONDS"
DEFAULT_ATTACHMENT_UPLOAD_TTL_SECONDS = 24 * 60 * 60
_UPLOAD_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class AttachmentUploadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StagedAttachment:
    attachment_id: str
    name: str
    mime_type: str | None
    size_bytes: int
    path: Path
    principal_id: str
    content_digest: str

    def frontend_payload(self) -> dict[str, Any]:
        return {
            "kind": "file",
            "attachment_id": self.attachment_id,
            "name": self.name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "revision": 1,
            "content_digest": self.content_digest,
        }


class AttachmentUploadStore:
    """Stages browser uploads and resolves opaque IDs before runtime dispatch."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or factory_artifact_path("attachment_uploads")).resolve()
        self.ttl_seconds = _positive_int_env(
            ATTACHMENT_UPLOAD_TTL_SECONDS_ENV,
            DEFAULT_ATTACHMENT_UPLOAD_TTL_SECONDS,
        )

    async def stage(self, upload: UploadFile, *, principal_id: str) -> StagedAttachment:
        self.cleanup_expired()
        name = _safe_upload_name(upload.filename)
        attachment_id = uuid4().hex
        entry = self.root / attachment_id
        target = entry / name
        policy = AttachmentImportPolicy.from_env()
        entry.mkdir(parents=True, exist_ok=False)
        size_bytes = 0
        digest = sha256()
        try:
            with target.open("xb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size_bytes += len(chunk)
                    if policy.max_file_bytes is not None and size_bytes > policy.max_file_bytes:
                        raise AttachmentUploadError(
                            "attachment exceeds configured file size limit: "
                            f"{size_bytes} > {policy.max_file_bytes}"
                        )
                    handle.write(chunk)
                    digest.update(chunk)
            metadata = {
                "attachment_id": attachment_id,
                "name": name,
                "mime_type": str(upload.content_type or "").strip() or None,
                "size_bytes": size_bytes,
                "created_at": time.time(),
                "principal_id": _required_principal(principal_id),
                "content_digest": digest.hexdigest(),
            }
            (entry / "metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception:
            shutil.rmtree(entry, ignore_errors=True)
            raise
        return StagedAttachment(
            attachment_id=attachment_id,
            name=name,
            mime_type=str(upload.content_type or "").strip() or None,
            size_bytes=size_bytes,
            path=target,
            principal_id=_required_principal(principal_id),
            content_digest=digest.hexdigest(),
        )

    def stage_bytes(
        self,
        *,
        content: bytes,
        name: str,
        mime_type: str | None,
        principal_id: str,
    ) -> StagedAttachment:
        self.cleanup_expired()
        attachment_id = uuid4().hex
        safe_name = _safe_upload_name(name)
        entry = self.root / attachment_id
        target = entry / safe_name
        policy = AttachmentImportPolicy.from_env()
        if policy.max_file_bytes is not None and len(content) > policy.max_file_bytes:
            raise AttachmentUploadError("attachment exceeds configured file size limit")
        entry.mkdir(parents=True, exist_ok=False)
        digest = sha256(content).hexdigest()
        try:
            target.write_bytes(content)
            (entry / "metadata.json").write_text(json.dumps({
                "attachment_id": attachment_id,
                "name": safe_name,
                "mime_type": str(mime_type or "").strip() or None,
                "size_bytes": len(content),
                "created_at": time.time(),
                "principal_id": _required_principal(principal_id),
                "content_digest": digest,
            }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        except Exception:
            shutil.rmtree(entry, ignore_errors=True)
            raise
        return StagedAttachment(attachment_id, safe_name, str(mime_type or "").strip() or None, len(content), target, _required_principal(principal_id), digest)

    def resolve(self, attachment_id: str) -> StagedAttachment:
        normalized = str(attachment_id or "").strip().lower()
        if not _UPLOAD_ID_PATTERN.fullmatch(normalized):
            raise AttachmentUploadError("invalid attachment_id")
        entry = self.root / normalized
        metadata_path = entry / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise AttachmentUploadError(f"unknown or expired attachment_id: {normalized}") from exc
        name = _safe_upload_name(metadata.get("name"))
        target = (entry / name).resolve()
        if target.parent != entry.resolve() or not target.is_file():
            raise AttachmentUploadError(f"attachment payload is unavailable: {normalized}")
        return StagedAttachment(
            attachment_id=normalized,
            name=name,
            mime_type=str(metadata.get("mime_type") or "").strip() or None,
            size_bytes=target.stat().st_size,
            path=target,
            principal_id=_required_principal(metadata.get("principal_id")),
            content_digest=str(metadata.get("content_digest") or "").strip(),
        )

    def resolve_command_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(payload)
        attachments = resolved.get("attachments")
        if isinstance(attachments, list):
            resolved["attachments"] = [self._resolve_attachment_item(item) for item in attachments]
        user_config = resolved.get("user_config")
        if isinstance(user_config, dict) and isinstance(user_config.get("attachments"), list):
            resolved_user_config = dict(user_config)
            resolved_user_config["attachments"] = [
                self._resolve_attachment_item(item) for item in user_config["attachments"]
            ]
            resolved["user_config"] = resolved_user_config
        return resolved

    def cleanup_expired(self) -> None:
        if not self.root.is_dir():
            return
        threshold = time.time() - self.ttl_seconds
        for entry in self.root.iterdir():
            if not entry.is_dir():
                continue
            try:
                modified_at = entry.stat().st_mtime
            except OSError:
                continue
            if modified_at < threshold:
                shutil.rmtree(entry, ignore_errors=True)

    def _resolve_attachment_item(self, item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        attachment_id = str(item.get("attachment_id") or "").strip()
        if not attachment_id or item.get("content") is not None or item.get("path") is not None:
            return dict(item)
        staged = self.resolve(attachment_id)
        return {
            "kind": "file",
            "name": staged.name,
            "content": str(staged.path),
            "mime_type": staged.mime_type,
            "source_kind": str(item.get("source_kind") or "uploaded_file"),
        }


class StagedAttachmentLaunchResolver:
    def resolve(self, *, principal_id: str, reference: AttachmentRevisionRef) -> dict[str, Any]:
        if reference.revision != 1:
            raise AttachmentUploadError("staged attachment revision must be 1")
        staged = attachment_upload_store().resolve(reference.attachment_id)
        if staged.principal_id != principal_id:
            raise PermissionError("attachment does not belong to the runtime principal")
        if staged.content_digest != reference.content_digest:
            raise AttachmentUploadError("attachment content digest does not match")
        return {
            "kind": "file",
            "name": staged.name,
            "content": str(staged.path),
            "mime_type": staged.mime_type,
            "source_kind": "uploaded_file",
        }


_DEFAULT_ATTACHMENT_UPLOAD_STORE: AttachmentUploadStore | None = None


def attachment_upload_store() -> AttachmentUploadStore:
    global _DEFAULT_ATTACHMENT_UPLOAD_STORE
    if _DEFAULT_ATTACHMENT_UPLOAD_STORE is None:
        _DEFAULT_ATTACHMENT_UPLOAD_STORE = AttachmentUploadStore()
    return _DEFAULT_ATTACHMENT_UPLOAD_STORE


def _safe_upload_name(value: Any) -> str:
    name = Path(str(value or "attachment").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."} or "\x00" in name:
        raise AttachmentUploadError("attachment filename is invalid")
    return name


def _required_principal(value: Any) -> str:
    principal = str(value or "").strip()
    if not principal:
        raise AttachmentUploadError("attachment principal must not be empty")
    return principal


def _positive_int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value
