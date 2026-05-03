from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_factory.model import LLMRequest, MessageBuilder, ModelService
from agent_factory.specs import AgentPackagePrimitives, KnowledgeSource


LOCAL_RESOURCE_SUFFIXES = {
    ".csv",
    ".db",
    ".docx",
    ".duckdb",
    ".json",
    ".md",
    ".pdf",
    ".sqlite",
    ".sqlite3",
    ".tsv",
    ".txt",
    ".xls",
    ".xlsx",
    ".yaml",
    ".yml",
}


class ResourceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    ref: str
    kind: Literal["file", "directory"]
    suffix: str | None = None
    default_access_mode: Literal["read_only", "read_write"] = "read_only"


class ResourceBindingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    candidate_id: str
    source_id: str
    purpose: str
    visible_to_model: bool = False
    visible_to_tools: bool = True
    access_mode: Literal["read_only", "read_write"] = "read_only"
    sandbox_required: bool = True


class ResourceBindingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    bindings: list[ResourceBindingDecision] = Field(default_factory=list)


def bind_requirement_resources(
    primitives: AgentPackagePrimitives,
    requirement: str,
    *,
    start_path: str | Path | None = None,
    model_service: ModelService | None = None,
) -> AgentPackagePrimitives:
    """Attach local resources mentioned in the requirement to KnowledgeSpec.

    This is intentionally generic: it binds existing files/directories by path and lets
    downstream sandbox/runtime code infer concrete resource behavior from suffix/type.
    """

    candidates = discover_resource_candidates(requirement, start_path=start_path)
    if not candidates:
        return primitives

    updated = primitives.model_copy(deep=True)
    existing_refs = {
        _normalize_ref(source.ref)
        for source in updated.knowledge.sources
        if source.ref
    }
    existing_ids = {source.id for source in updated.knowledge.sources}

    binding_plan = _plan_resource_bindings(
        primitives,
        requirement,
        candidates,
        model_service=model_service,
    )
    candidates_by_id = {candidate.id: candidate for candidate in candidates}
    for decision in binding_plan.bindings:
        candidate = candidates_by_id.get(decision.candidate_id)
        if candidate is None:
            continue
        normalized_ref = _normalize_ref(candidate.ref)
        if normalized_ref in existing_refs:
            continue
        source_id = _unique_id(_safe_source_id(decision.source_id), existing_ids)
        existing_ids.add(source_id)
        existing_refs.add(normalized_ref)
        updated.knowledge.sources.append(
            KnowledgeSource(
                id=source_id,
                type=candidate.kind,
                ref=candidate.ref,
                visible_to_model=False if candidate.kind in {"file", "directory"} else decision.visible_to_model,
                visible_to_tools=decision.visible_to_tools,
                citation_required=False,
                access_mode=_safe_access_mode(
                    requested=decision.access_mode,
                    default=candidate.default_access_mode,
                ),
                sandbox_required=decision.sandbox_required,
            )
        )

    if updated.knowledge.sources and updated.knowledge.inject_as == "none":
        updated.knowledge.inject_as = "tool"
    return updated


def discover_resource_candidates(
    text: str,
    *,
    start_path: str | Path | None = None,
) -> list[ResourceCandidate]:
    return [
        ResourceCandidate(
            id=_resource_id(path),
            ref=str(path),
            kind="directory" if path.is_dir() else "file",
            suffix=path.suffix.lower() or None,
            default_access_mode=_access_mode_from_requirement(text),
        )
        for path in extract_local_resources(text, start_path=start_path)
    ]


def extract_local_resources(
    text: str,
    *,
    start_path: str | Path | None = None,
) -> list[Path]:
    root = Path(start_path or ".").resolve()
    seen: set[str] = set()
    resources: list[Path] = []
    for raw in _candidate_paths(text):
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = root / path
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not _looks_like_resource(resolved):
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        resources.append(resolved)
    return resources


def _plan_resource_bindings(
    primitives: AgentPackagePrimitives,
    requirement: str,
    candidates: list[ResourceCandidate],
    *,
    model_service: ModelService | None,
) -> ResourceBindingPlan:
    fallback = _fallback_binding_plan(candidates)
    if model_service is None or _provider_name(model_service) == "fake":
        return fallback
    request = _resource_binding_request(primitives, requirement, candidates)
    try:
        result = asyncio.run(
            model_service.generate_task_structured(
                request,
                schema=ResourceBindingPlan.model_json_schema(),
                schema_name="ResourceBindingPlan",
            )
        )
        if result.error:
            return fallback
        data = result.data
        if isinstance(data, list):
            data = {"bindings": data}
        plan = ResourceBindingPlan.model_validate(data)
    except (RuntimeError, ValidationError, TypeError, ValueError):
        return fallback
    valid_ids = {candidate.id for candidate in candidates}
    bindings = [
        binding for binding in plan.bindings if binding.candidate_id in valid_ids
    ]
    if not bindings:
        return fallback
    by_candidate = {binding.candidate_id: binding for binding in bindings}
    for fallback_binding in fallback.bindings:
        by_candidate.setdefault(fallback_binding.candidate_id, fallback_binding)
    return ResourceBindingPlan(bindings=list(by_candidate.values()))


def _fallback_binding_plan(candidates: list[ResourceCandidate]) -> ResourceBindingPlan:
    return ResourceBindingPlan(
        bindings=[
            ResourceBindingDecision(
                candidate_id=candidate.id,
                source_id=candidate.id,
                purpose=f"Runtime resource from requirement: {candidate.ref}",
                visible_to_model=False,
                visible_to_tools=True,
                access_mode=candidate.default_access_mode,
                sandbox_required=True,
            )
            for candidate in candidates
        ]
    )


def _resource_binding_request(
    primitives: AgentPackagePrimitives,
    requirement: str,
    candidates: list[ResourceCandidate],
) -> LLMRequest:
    tool_ids = [
        tool_id
        for toolset in primitives.toolsets.toolsets
        for tool_id in toolset.exposed_tools + toolset.hidden_tools
    ]
    return (
        MessageBuilder.start()
        .system(
            "You bind discovered local resources to an AgentPackage. This is a small planning task. "
            "Return exactly one JSON object matching ResourceBindingPlan. Never invent paths. "
            "Use only candidate_id values provided by the user message."
        )
        .user(
            "Plan semantic resource bindings for these discovered local resources.\n\n"
            f"Requirement:\n{requirement}\n\n"
            f"Agent goal: {primitives.instructions.goal}\n"
            f"Tool ids: {json.dumps(tool_ids, ensure_ascii=False)}\n\n"
            "Candidates:\n"
            f"{json.dumps([candidate.model_dump(mode='json') for candidate in candidates], ensure_ascii=False, indent=2)}\n\n"
            "Rules:\n"
            "- source_id must be stable snake_case.\n"
            "- Local files/directories should normally be visible_to_model=false and visible_to_tools=true.\n"
            "- access_mode must be read_write only when the requirement clearly asks to create/update/write/manage data.\n"
            "- sandbox_required should be true for local files/directories."
        )
        .request(
            response_format="json_schema",
            json_schema=ResourceBindingPlan.model_json_schema(),
            json_schema_name="ResourceBindingPlan",
            json_schema_strict=True,
            metadata={"phase": "resource_binding", "resource_count": len(candidates)},
        )
    )


def _candidate_paths(text: str) -> list[str]:
    candidates: list[str] = []
    candidates.extend(re.findall(r"(?P<quote>['\"])(?P<path>(?:/|~|\.)[^'\"]+)(?P=quote)", text))
    # The previous regex returns tuples because of the named quote group.
    normalized: list[str] = []
    for item in candidates:
        if isinstance(item, tuple):
            normalized.append(item[1])
        else:
            normalized.append(item)
    normalized.extend(
        match.group(0)
        for match in re.finditer(r"(?:/|~|\./|\../)[^\s，。；：、]+", text)
    )
    return [_strip_path_punctuation(value) for value in normalized if value.strip()]


def _strip_path_punctuation(value: str) -> str:
    return value.strip().rstrip(".,;:，。；：、)")


def _looks_like_resource(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        return True
    return path.suffix.lower() in LOCAL_RESOURCE_SUFFIXES


def _resource_id(path: Path) -> str:
    if path.is_dir():
        base = path.name
    else:
        suffix = path.suffix.lower().lstrip(".")
        stem = path.stem
        if suffix in {"sqlite", "sqlite3", "db", "duckdb"} and not stem.endswith("_sqlite"):
            base = f"{stem}_sqlite"
        else:
            base = f"{stem}_{suffix}" if suffix else stem
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", base).strip("_").lower()
    if not normalized:
        normalized = "resource"
    if normalized[0].isdigit():
        normalized = f"resource_{normalized}"
    return normalized


def _unique_id(base: str, existing: set[str]) -> str:
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def _safe_source_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not normalized:
        normalized = "resource"
    if normalized[0].isdigit():
        normalized = f"resource_{normalized}"
    return normalized


def _safe_access_mode(
    *,
    requested: Literal["read_only", "read_write"],
    default: Literal["read_only", "read_write"],
) -> Literal["read_only", "read_write"]:
    if default == "read_only":
        return "read_only"
    return requested


def _provider_name(model_service: ModelService) -> str:
    config = getattr(getattr(model_service, "router", None), "config", None)
    return str(getattr(config, "provider", "unknown"))


def _normalize_ref(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return value


def _access_mode_from_requirement(requirement: str) -> str:
    lowered = requirement.lower()
    write_markers = [
        "create",
        "update",
        "write",
        "delete",
        "close",
        "创建",
        "更新",
        "写入",
        "修改",
        "关闭",
        "删除",
        "管理",
    ]
    return "read_write" if any(marker in lowered for marker in write_markers) else "read_only"
