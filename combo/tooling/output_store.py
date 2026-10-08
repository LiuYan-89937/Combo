from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from combo.tooling.output_compressor import compress_tool_output
from combo.tooling.envelope import tool_envelope
from combo.tooling.execution_context import current_tool_output_session_id
from combo.tooling.targets import select_target
from combo.tooling.spec import ToolOutputCompressionActionConfig, ToolOutputCompressionConfig


TOOL_OUTPUT_STORE_RESOURCE = "tool_output_store"
DEFAULT_TOOL_OUTPUT_MAX_MODEL_CHARS = 12000
_OUTPUT_ID_RE = re.compile(r"^toolout_[a-f0-9]{32}$")


@dataclass(frozen=True, slots=True)
class ToolOutputPolicy:
    max_model_chars: int = DEFAULT_TOOL_OUTPUT_MAX_MODEL_CHARS

    def __post_init__(self) -> None:
        if self.max_model_chars < 1_000:
            raise ValueError("tool output model projection limit must be at least 1000 characters")


@dataclass(frozen=True, slots=True)
class ToolOutputProjection:
    output: dict[str, Any]
    output_ref: dict[str, Any] | None = None
    output_summary: str | None = None
    output_truncated: bool = False


class ToolOutputStore:
    """Filesystem-backed, session-scoped store for full tool outputs."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def records_dir(self) -> Path:
        session_id = current_tool_output_session_id() or "unscoped"
        records_dir = self.root / "sessions" / session_id / "records"
        records_dir.mkdir(parents=True, exist_ok=True)
        return records_dir

    def write_output(
        self,
        *,
        tool_id: str,
        tool_call_id: str | None,
        output: dict[str, Any],
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        output_id = f"toolout_{uuid4().hex}"
        text = _json_text(output)
        created_at = datetime.now(UTC).isoformat()
        record = {
            "type": "tool_output_record",
            "id": output_id,
            "tool_id": tool_id,
            "arguments": dict(arguments or {}),
            "tool_call_id": tool_call_id or "",
            "created_at": created_at,
            "size_chars": len(text),
            "output": output,
        }
        path = self._record_path(output_id)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(_json_text(record), encoding="utf-8")
        tmp_path.replace(path)
        return {
            "type": "tool_output_ref",
            "id": output_id,
            "tool_id": tool_id,
            "arguments": dict(arguments or {}),
            "tool_call_id": tool_call_id or "",
            "created_at": created_at,
            "size_chars": len(text),
        }

    def describe(self, output_id: str) -> dict[str, Any]:
        record = self._read_record(output_id)
        return {
            "type": "tool_output_ref",
            "id": record["id"],
            "tool_id": record["tool_id"],
            "arguments": dict(record.get("arguments") or {}),
            "tool_call_id": record.get("tool_call_id", ""),
            "created_at": record["created_at"],
            "size_chars": record["size_chars"],
        }

    def list_outputs(self, *, limit: int | None = 20) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for path in self.records_dir.glob("toolout_*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict) or record.get("type") != "tool_output_record":
                continue
            refs.append(
                {
                    "type": "tool_output_ref",
                    "id": str(record.get("id") or ""),
                    "tool_id": str(record.get("tool_id") or ""),
                    "arguments": dict(record.get("arguments") or {}),
                    "tool_call_id": str(record.get("tool_call_id") or ""),
                    "created_at": str(record.get("created_at") or ""),
                    "size_chars": int(record.get("size_chars") or 0),
                }
            )
        refs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return refs if limit is None else refs[: max(limit, 0)]

    def resolve_target(self, selector: dict[str, Any]) -> str:
        target = select_target(self.list_outputs(limit=None), selector=selector, describe=_output_target, kind="tool output")
        return str(target["id"])

    def read(
        self,
        *,
        output_id: str,
        path: str | None = None,
        offset: int = 0,
        limit: int = DEFAULT_TOOL_OUTPUT_MAX_MODEL_CHARS,
    ) -> dict[str, Any]:
        record = self._read_record(output_id)
        selected = _select_path(record["output"], path)
        text = _json_text(selected) if not isinstance(selected, str) else selected
        start = max(offset, 0)
        safe_limit = max(limit, 1)
        end = min(start + safe_limit, len(text))
        return {
            "output_id": output_id,
            "path": path or "",
            "offset": start,
            "limit": safe_limit,
            "total_chars": len(text),
            "content": text[start:end],
            "truncated": end < len(text),
        }

    def _read_record(self, output_id: str) -> dict[str, Any]:
        path = self._record_path(output_id)
        if not path.is_file():
            raise FileNotFoundError(f"unknown tool output id: {output_id}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("type") != "tool_output_record":
            raise ValueError(f"invalid tool output record: {output_id}")
        return record

    def _record_path(self, output_id: str) -> Path:
        if not _OUTPUT_ID_RE.fullmatch(output_id):
            raise ValueError("output_id must be a tool output id")
        return self.records_dir / f"{output_id}.json"


def project_tool_output(
    *,
    output: dict[str, Any],
    tool_id: str,
    tool_call_id: str | None,
    arguments: dict[str, Any] | None = None,
    store: ToolOutputStore | None,
    policy: ToolOutputPolicy,
    compression_model: Any | None = None,
    compression_config: ToolOutputCompressionConfig | None = None,
) -> ToolOutputProjection:
    effective_max_chars = (
        compression_config.max_model_chars
        if compression_config is not None and compression_config.max_model_chars is not None
        else policy.max_model_chars
    )
    raw_text = _json_text(output)
    if len(raw_text) <= effective_max_chars:
        return ToolOutputProjection(output=output)
    output_ref = (
        store.write_output(tool_id=tool_id, tool_call_id=tool_call_id, output=output, arguments=arguments)
        if store is not None
        else None
    )
    # Use LLM compression when available, fallback to structural truncation
    compression = compress_tool_output(
        output,
        tool_id=tool_id,
        arguments=arguments or {},
        max_chars=effective_max_chars,
        model=compression_model,
        config=_compression_config_for_arguments(compression_config, arguments or {}),
    )
    target = _output_target(output_ref) if output_ref else None
    compacted: dict[str, Any] = {
        "compressed_output": compression.compressed_output,
        "source": target,
        "raw_output_read_hint": _raw_output_read_hint(target),
        "_tool_output_compacted": {
            "original_chars": compression.original_chars,
            "compressed_chars": compression.compressed_chars,
            "model_visible_limit_chars": effective_max_chars,
            "compression_method": compression.method,
            "source": target,
        },
    }
    summary = "Tool output exceeded the model-visible limit; a compressed observation was returned."
    if output_ref is not None:
        summary += " Read the full output with tool_output using its source business fields."
    return ToolOutputProjection(
        output=compacted,
        output_ref=output_ref,
        output_summary=summary,
        output_truncated=True,
    )


def _compression_config_for_arguments(
    config: ToolOutputCompressionConfig | None,
    arguments: dict[str, Any],
) -> ToolOutputCompressionActionConfig | None:
    if config is None:
        return None
    action_key = str(config.action_argument or "action")
    action = str(arguments.get(action_key) or "").strip().lower()
    if action:
        return config.actions.get(action)
    if len(config.actions) == 1:
        return next(iter(config.actions.values()))
    return None


def _output_target(ref: dict[str, Any]) -> dict[str, Any]:
    return {"tool": ref["tool_id"], "arguments": dict(ref.get("arguments") or {}), "created_at": ref["created_at"]}


def _raw_output_read_hint(target: dict[str, Any] | None) -> str:
    if target is None:
        return ""
    return "Read the retained result with tool_output action=read and output=" + _json_text(target)


def run_tool_output(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    store = resources.get(TOOL_OUTPUT_STORE_RESOURCE)
    if not isinstance(store, ToolOutputStore):
        raise ValueError("tool_output_store resource is not configured")
    action = str(arguments.get("action") or "").strip()
    if action == "list":
        return tool_envelope({
            "action": action, "outputs": [
                {**_output_target(ref), "size_chars": ref["size_chars"]}
                for ref in store.list_outputs()
            ],
        })
    output_id = store.resolve_target(dict(arguments.get("output") or {}))
    if action == "describe":
        ref = store.describe(output_id)
        output = {**_output_target(ref), "size_chars": ref["size_chars"]}
    elif action == "read":
        output = store.read(
            output_id=output_id, path=_optional_string(arguments.get("path")),
            offset=_optional_int(arguments.get("offset"), default=0),
            limit=_optional_int(arguments.get("limit"), default=DEFAULT_TOOL_OUTPUT_MAX_MODEL_CHARS),
        )
        output.pop("output_id")
        output["source"] = _output_target(store.describe(output_id))
    else:
        raise ValueError(f"unsupported tool_output action: {action}")
    return tool_envelope({"action": action, "output": output})


def _select_path(value: Any, path: str | None) -> Any:
    if not path:
        return value
    current = value
    for part in path.split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current[part]
            continue
        if isinstance(current, list):
            current = current[int(part)]
            continue
        raise ValueError(f"path cannot descend into {type(current).__name__}: {part}")
    return current


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)
