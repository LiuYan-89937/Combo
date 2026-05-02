from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.package import PackageLoader
from agent_factory.specs import ContextSpec


class ContextBundle(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    visible_to_model: list[str] = Field(default_factory=list)
    visible_to_tools: dict[str, Any] = Field(default_factory=dict)
    hidden: dict[str, Any] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)


class ContextManager:
    def __init__(self, loader: PackageLoader | None = None) -> None:
        self.loader = loader or PackageLoader()

    def compile(
        self,
        package_path: str | Path,
        *,
        session_context: dict[str, Any] | None = None,
    ) -> ContextBundle:
        package = self.loader.load_full_package(package_path)
        context_spec: ContextSpec = package.context
        session_context = session_context or {}
        bundle = ContextBundle()

        for source in context_spec.sources[: context_spec.max_visible_items]:
            bundle.source_ids.append(source.id)
            content = source.content or _content_from_ref(Path(package_path), source.ref)
            if content and source.visible_to_model:
                bundle.visible_to_model.append(_redact_text(content, context_spec.redact_fields))
            if source.visible_to_tools:
                bundle.visible_to_tools[source.id] = _redact_value(
                    {"content": content, "ref": source.ref},
                    context_spec.redact_fields,
                )
            for field in source.hidden_from_model:
                if field in session_context:
                    bundle.hidden[field] = "[HIDDEN]"

        for key, value in session_context.items():
            if key in context_spec.redact_fields:
                bundle.hidden[key] = "[HIDDEN]"
            else:
                bundle.visible_to_tools[key] = value
        return bundle


def _content_from_ref(package_path: Path, ref: str | None) -> str | None:
    if not ref:
        return None
    path = package_path / ref
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    return None


def _redact_value(value: Any, fields: list[str]) -> Any:
    sensitive = {field.lower() for field in fields}
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in sensitive else _redact_value(item, fields)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, fields) for item in value]
    if isinstance(value, str):
        return _redact_text(value, fields)
    return value


def _redact_text(value: str, fields: list[str]) -> str:
    redacted = value
    for field in fields:
        redacted = re.sub(
            rf"(?i)({re.escape(field)})\s*[:=]\s*[^\s,;]+",
            rf"\1=[REDACTED]",
            redacted,
        )
    return redacted
