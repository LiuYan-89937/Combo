from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import mimetypes
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any
from uuid import uuid4


ATTACHMENT_INPUT_DIR = "input_files"
ATTACHMENT_MARKER = "@"
ATTACHMENT_MAX_FILES_ENV = "AGENTFACTORY_ATTACHMENT_MAX_FILES"
ATTACHMENT_MAX_FILE_BYTES_ENV = "AGENTFACTORY_ATTACHMENT_MAX_FILE_BYTES"
ATTACHMENT_MAX_TOTAL_BYTES_ENV = "AGENTFACTORY_ATTACHMENT_MAX_TOTAL_BYTES"


class AttachmentImportError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        code: str = "external_attachment_import_failed",
    ) -> None:
        super().__init__(message)
        self.path = path
        self.code = code


@dataclass(frozen=True, slots=True)
class AttachmentImportPolicy:
    max_files: int | None = None
    max_file_bytes: int | None = None
    max_total_bytes: int | None = None

    @classmethod
    def from_env(cls) -> "AttachmentImportPolicy":
        return cls(
            max_files=_optional_positive_int_env(ATTACHMENT_MAX_FILES_ENV),
            max_file_bytes=_optional_positive_int_env(ATTACHMENT_MAX_FILE_BYTES_ENV),
            max_total_bytes=_optional_positive_int_env(ATTACHMENT_MAX_TOTAL_BYTES_ENV),
        )


@dataclass(frozen=True, slots=True)
class AttachmentMarker:
    start: int
    end: int
    path: str


@dataclass(frozen=True, slots=True)
class RuntimeAttachmentRef:
    attachment_id: str
    display_name: str
    source_kind: str
    runtime_path: str
    mime_type: str | None
    size_bytes: int
    sha256: str
    scope: str
    access: str
    imported_at: str

    def model_payload(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "display_name": self.display_name,
            "source_kind": self.source_kind,
            "path": self.runtime_path,
            "runtime_path": self.runtime_path,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "scope": self.scope,
            "access": self.access,
            "imported_at": self.imported_at,
        }


@dataclass(frozen=True, slots=True)
class _PreparedLocalAttachment:
    raw_path: str
    source: Path
    size_bytes: int


@dataclass(frozen=True, slots=True)
class _ImportedLocalAttachment:
    ref: RuntimeAttachmentRef
    target_dir: Path


@dataclass(frozen=True, slots=True)
class AttachmentImportResult:
    message: str
    attachments: list[dict[str, Any]]


def import_marked_attachments(
    message: str,
    *,
    storage_root: Path,
    runtime_path_root: str,
    base_dir: Path | None = None,
    scope: str = "run",
    policy: AttachmentImportPolicy | None = None,
) -> AttachmentImportResult:
    markers = parse_attachment_markers(message)
    if not markers:
        return AttachmentImportResult(message=message, attachments=[])
    resolved_policy = policy or AttachmentImportPolicy.from_env()
    prepared_sources = [
        _prepare_local_attachment_source(marker.path, base_dir=base_dir)
        for marker in markers
    ]
    _enforce_import_policy(prepared_sources, policy=resolved_policy)
    imported: list[_ImportedLocalAttachment] = []
    replacements: list[tuple[int, int, str]] = []
    try:
        for marker, prepared in zip(markers, prepared_sources):
            imported_item = _copy_prepared_local_attachment(
                prepared,
                storage_root=storage_root,
                runtime_path_root=runtime_path_root,
                scope=scope,
            )
            imported.append(imported_item)
            ref = imported_item.ref
            replacements.append(
                (
                    marker.start,
                    marker.end,
                    f"[uploaded attachment: {ref.display_name}, attachment_id={ref.attachment_id}]",
                )
            )
    except Exception:
        for imported_item in imported:
            shutil.rmtree(imported_item.target_dir, ignore_errors=True)
        raise
    return AttachmentImportResult(
        message=_replace_ranges(message, replacements),
        attachments=[imported_item.ref.model_payload() for imported_item in imported],
    )


def parse_attachment_markers(message: str) -> list[AttachmentMarker]:
    """Parse explicit @path@ attachment markers from a user message.

    The marker is a reserved upload action. Non-empty marker contents are
    always treated as file paths and validated during import instead of being
    inferred from natural-language shape.
    """
    markers: list[AttachmentMarker] = []
    index = 0
    while index < len(message):
        start = message.find(ATTACHMENT_MARKER, index)
        if start < 0:
            break
        end = message.find(ATTACHMENT_MARKER, start + 1)
        if end < 0:
            break
        raw = message[start + 1 : end].strip()
        if raw:
            markers.append(AttachmentMarker(start=start, end=end + 1, path=raw))
        index = end + 1
    return markers


def import_local_attachment(
    raw_path: str,
    *,
    storage_root: Path,
    runtime_path_root: str,
    base_dir: Path | None = None,
    scope: str = "run",
    policy: AttachmentImportPolicy | None = None,
) -> RuntimeAttachmentRef:
    prepared = _prepare_local_attachment_source(raw_path, base_dir=base_dir)
    _enforce_import_policy([prepared], policy=policy or AttachmentImportPolicy.from_env())
    return _copy_prepared_local_attachment(
        prepared,
        storage_root=storage_root,
        runtime_path_root=runtime_path_root,
        scope=scope,
    ).ref


def _copy_prepared_local_attachment(
    prepared: _PreparedLocalAttachment,
    *,
    storage_root: Path,
    runtime_path_root: str,
    scope: str,
) -> _ImportedLocalAttachment:
    attachment_id = f"att_{uuid4().hex}"
    safe_name = _safe_filename(prepared.source.name)
    target_dir = storage_root / attachment_id
    target_dir.mkdir(parents=True, exist_ok=False)
    target = target_dir / safe_name
    try:
        shutil.copy2(prepared.source, target)
        digest = _file_sha256(target)
        size_bytes = target.stat().st_size
    except Exception as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise AttachmentImportError(
            f"attachment file could not be imported: {prepared.raw_path}: {exc}",
            path=prepared.raw_path,
        ) from exc
    runtime_path = _runtime_attachment_path(
        runtime_path_root=runtime_path_root,
        attachment_id=attachment_id,
        filename=safe_name,
    )
    mime_type, _ = mimetypes.guess_type(safe_name)
    return _ImportedLocalAttachment(
        ref=RuntimeAttachmentRef(
            attachment_id=attachment_id,
            display_name=safe_name,
            source_kind="local_path",
            runtime_path=runtime_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=digest,
            scope=scope,
            access="read_only",
            imported_at=datetime.now(UTC).isoformat(),
        ),
        target_dir=target_dir,
    )


def format_attachments_for_model(attachments: Any) -> str:
    if not isinstance(attachments, list) or not attachments:
        return ""
    lines = [
        "Runtime attachments available for this turn:",
        "Use the path field when calling tools. Do not use or infer original host file paths.",
    ]
    for item in attachments:
        if not isinstance(item, dict):
            continue
        attachment_id = str(item.get("attachment_id") or "").strip()
        path = str(item.get("path") or item.get("runtime_path") or "").strip()
        display_name = str(item.get("display_name") or "").strip()
        if not attachment_id or not path:
            continue
        parts = [
            f"id={attachment_id}",
            f"name={display_name or attachment_id}",
            f"path={path}",
        ]
        mime_type = str(item.get("mime_type") or "").strip()
        if mime_type:
            parts.append(f"mime={mime_type}")
        size_bytes = item.get("size_bytes")
        if isinstance(size_bytes, int):
            parts.append(f"size_bytes={size_bytes}")
        digest = str(item.get("sha256") or "").strip()
        if digest:
            parts.append(f"sha256={digest}")
        lines.append("- " + "; ".join(parts))
    return "\n".join(lines) if len(lines) > 2 else ""


def format_attachments_for_session_input(user_input: str | None, attachments: Any) -> str | None:
    text = str(user_input or "").strip()
    attachment_lines = _attachment_session_lines(attachments)
    if not attachment_lines:
        return text or None
    lines: list[str] = []
    if text:
        lines.append(text)
    lines.append("[runtime attachments]")
    lines.extend(attachment_lines)
    return "\n".join(lines).strip() or None


def _attachment_session_lines(attachments: Any) -> list[str]:
    if not isinstance(attachments, list):
        return []
    lines: list[str] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        attachment_id = str(item.get("attachment_id") or "").strip()
        path = str(item.get("path") or item.get("runtime_path") or "").strip()
        display_name = str(item.get("display_name") or "").strip()
        if not attachment_id or not path:
            continue
        parts = [
            f"name={display_name or attachment_id}",
            f"path={path}",
            f"id={attachment_id}",
        ]
        mime_type = str(item.get("mime_type") or "").strip()
        if mime_type:
            parts.append(f"mime={mime_type}")
        size_bytes = item.get("size_bytes")
        if isinstance(size_bytes, int):
            parts.append(f"size_bytes={size_bytes}")
        digest = str(item.get("sha256") or "").strip()
        if digest:
            parts.append(f"sha256={digest}")
        lines.append("- " + "; ".join(parts))
    return lines


def redact_attachment_markers(message: str) -> str:
    markers = parse_attachment_markers(message)
    if not markers:
        return message
    replacements = [
        (
            marker.start,
            marker.end,
            f"[uploaded attachment: {_display_name_from_raw_path(marker.path)}]",
        )
        for marker in markers
    ]
    return _replace_ranges(message, replacements)


def safe_attachment_scope_id(value: str | None, *, fallback: str = "run") -> str:
    text = str(value or "").strip()
    chars = [char if char.isalnum() or char in {"_", ".", "-"} else "_" for char in text]
    cleaned = "".join(chars).strip("._-")
    return cleaned or fallback


def merge_attachments_into_user_config(user_config: Any, attachments: Any) -> dict[str, Any]:
    result = dict(user_config or {}) if isinstance(user_config, dict) else {}
    existing = (
        [dict(item) for item in result.get("attachments") if isinstance(item, dict)]
        if isinstance(result.get("attachments"), list)
        else []
    )
    payload = (
        [dict(item) for item in attachments if isinstance(item, dict)]
        if isinstance(attachments, list)
        else []
    )
    merged = [*existing, *payload]
    if merged:
        result["attachments"] = merged
    return result


def attachment_import_error_payload(
    exc: AttachmentImportError,
    *,
    where: str = "runtime_attachments",
) -> dict[str, Any]:
    return {
        "where": where,
        "why": exc.code,
        "message": str(exc),
        "path": exc.path,
        "suggested_action": (
            "Use @/absolute/or/relative/file/path@ with an existing file, "
            "or remove the attachment marker."
        ),
    }


def _prepare_local_attachment_source(
    raw_path: str,
    *,
    base_dir: Path | None,
) -> _PreparedLocalAttachment:
    _validate_raw_attachment_path(raw_path)
    source = _resolve_source(raw_path, base_dir=base_dir)
    if not source.exists():
        raise AttachmentImportError(f"attachment file does not exist: {raw_path}", path=raw_path)
    if not source.is_file():
        raise AttachmentImportError(f"attachment path must be a file: {raw_path}", path=raw_path)
    try:
        size_bytes = source.stat().st_size
    except OSError as exc:
        raise AttachmentImportError(
            f"attachment file cannot be inspected: {raw_path}: {exc}",
            path=raw_path,
        ) from exc
    return _PreparedLocalAttachment(raw_path=raw_path, source=source, size_bytes=size_bytes)


def _enforce_import_policy(
    prepared_sources: list[_PreparedLocalAttachment],
    *,
    policy: AttachmentImportPolicy,
) -> None:
    if policy.max_files is not None and len(prepared_sources) > policy.max_files:
        raise AttachmentImportError(
            "attachment count exceeds configured limit: "
            f"{len(prepared_sources)} > {policy.max_files}",
            code="external_attachment_limit_exceeded",
        )
    total_bytes = sum(source.size_bytes for source in prepared_sources)
    if policy.max_total_bytes is not None and total_bytes > policy.max_total_bytes:
        raise AttachmentImportError(
            "attachment total size exceeds configured limit: "
            f"{total_bytes} > {policy.max_total_bytes}",
            code="external_attachment_limit_exceeded",
        )
    for source in prepared_sources:
        if policy.max_file_bytes is not None and source.size_bytes > policy.max_file_bytes:
            raise AttachmentImportError(
                "attachment file exceeds configured size limit: "
                f"{source.size_bytes} > {policy.max_file_bytes}",
                path=source.raw_path,
                code="external_attachment_limit_exceeded",
            )


def _resolve_source(raw_path: str, *, base_dir: Path | None) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        root = base_dir or Path.cwd()
        candidate = root / candidate
    return candidate.resolve(strict=False)


def _validate_raw_attachment_path(raw_path: str) -> None:
    if not raw_path.strip():
        raise AttachmentImportError(
            "attachment marker path cannot be empty",
            path=raw_path,
            code="invalid_external_attachment_marker",
        )
    if any(char in raw_path for char in ("\n", "\r", "\0")):
        raise AttachmentImportError(
            "attachment marker must contain one filesystem path",
            path=raw_path,
            code="invalid_external_attachment_marker",
        )


def _safe_filename(value: str) -> str:
    cleaned = "".join(
        "_" if char in {"/", "\\"} or not char.isprintable() else char
        for char in value
    ).strip()
    return cleaned or "attachment"


def _display_name_from_raw_path(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    return _safe_filename(normalized.rsplit("/", 1)[-1])


def _optional_positive_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _runtime_attachment_path(*, runtime_path_root: str, attachment_id: str, filename: str) -> str:
    return str(PurePosixPath(runtime_path_root) / attachment_id / filename)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace_ranges(message: str, replacements: list[tuple[int, int, str]]) -> str:
    if not replacements:
        return message
    result: list[str] = []
    cursor = 0
    for start, end, value in sorted(replacements, key=lambda item: item[0]):
        result.append(message[cursor:start])
        result.append(value)
        cursor = end
    result.append(message[cursor:])
    return "".join(result)
