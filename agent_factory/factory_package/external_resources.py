from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_factory.factory_package.constants import RESOURCE_RESOLUTION_NODE_ID
from agent_factory.factory_package.model_call import FactoryModelCallError, call_structured_model
from agent_factory.factory_package.schemas import (
    CapabilityContractOutput,
    ExternalResourceDiscoveryQuery,
    ExternalResourceDiscoveryResult,
    ExternalResourceResolutionDraft,
    ResourceFact,
    ResourceResolutionReport,
)
from agent_factory.prompts import PromptId, output_json_schema
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


RESOURCE_FIELD_UI_EXTENSION = "x-agentfactory-ui"
_SCHEMA_HINT_KEYS = {"default", "examples"}
_PLACEHOLDER_PREFIX = "__AF_RESOURCE_VALUE_"
_PLACEHOLDER_PATTERN = re.compile(r"__AF_RESOURCE_VALUE_\d+__")
_CONNECTION_STRING_PATTERN = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp|smtp|s3)://[^\s\"'，。；]+",
    re.IGNORECASE,
)
_URL_PATTERN = re.compile(r"https?://[^\s\"'，。；]+", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_LOCAL_PATH_PATTERN = re.compile(r"(?<![\w])(?:~|/(?:Users|home|private|var|tmp|opt|Volumes))/[^\s\"'，。；]+")
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(?:api[_\s-]?key|apikey|token|secret|password|passwd|pwd|密钥|密码)"
    r"\s*(?:是|为|=|:)?\s*([A-Za-z0-9_./+=:@-]{8,})"
)


@dataclass(frozen=True, slots=True)
class _RedactedResourceValue:
    placeholder: str
    value: str
    kind: str
    secret: bool


@dataclass(frozen=True, slots=True)
class _PreprocessedResourceAnswer:
    text: str
    values: list[_RedactedResourceValue] = field(default_factory=list)


def build_resource_resolution_request(capability_contract: CapabilityContractOutput) -> dict[str, Any]:
    requirements = []
    for item in capability_contract.resources_required:
        if not item.required:
            continue
        value_schema = item.value_schema if isinstance(item.value_schema, dict) else {}
        requirements.append(
            {
                "resource_id": item.resource_id,
                "description": item.description,
                "required": item.required,
                "expected_shape": item.expected_shape,
                "value_schema": _sanitize_resource_value_schema(value_schema),
                "default_value": None,
                "secret_fields": item.secret_fields,
                "resolution_strategy": list(item.resolution_strategy),
                "used_by": item.used_by,
            }
        )
    sandbox_requirements = []
    for item in capability_contract.sandbox_requirements:
        if not item.network_required and not item.mounts_required:
            continue
        sandbox_requirements.append(
            {
                "requirement_id": item.requirement_id,
                "description": item.description,
                "network_required": item.network_required,
                "mounts_required": item.mounts_required,
            }
        )
    if not requirements and not sandbox_requirements:
        return {}
    return {
        "resources": requirements,
        "sandbox_requirements": sandbox_requirements,
    }


def build_external_resource_collection_payload(
    request: dict[str, Any],
    *,
    missing_questions: list[str] | None = None,
    reason_notes: list[str] | None = None,
    prior_answer: str = "",
) -> dict[str, Any]:
    return _external_resource_collection_payload(
        request,
        missing_questions=missing_questions,
        reason_notes=reason_notes,
        prior_answer=prior_answer,
    )


def build_external_resource_confirmation_payload(
    *,
    resource_request: dict[str, Any],
    draft: ExternalResourceResolutionDraft,
    validation: dict[str, Any],
) -> dict[str, Any]:
    return _external_resource_confirmation_payload(
        resource_request=resource_request,
        draft=draft,
        validation=validation,
    )


def normalize_external_resource_collection_resume(resume_payload: Any) -> dict[str, Any]:
    return _normalize_external_resource_collection_resume(resume_payload)


def normalize_external_resource_confirmation_resume(resume_payload: Any) -> dict[str, Any]:
    return _normalize_external_resource_confirmation_resume(resume_payload)


def parse_external_resource_answer(
    *,
    resource_request: dict[str, Any],
    answer_text: str,
    namespace_state: dict[str, Any],
    confirmed_facts: dict[str, Any],
) -> ExternalResourceResolutionDraft:
    confirmed = resource_facts_to_draft(confirmed_facts)
    draft = _resolve_external_resource_answer(
        resource_request=resource_request,
        answer_text=answer_text,
        namespace_state=namespace_state,
        confirmed_fact=confirmed,
    )
    draft = _merge_external_resource_resolution(confirmed, draft)
    return _normalize_external_resource_resolution(resource_request, draft)


def resource_answer_privacy_report(answer_text: str) -> dict[str, Any]:
    preprocessed = _preprocess_resource_answer(answer_text)
    return {
        "redacted_value_count": len(preprocessed.values),
        "redacted_kinds": sorted({item.kind for item in preprocessed.values}),
        "secret_redacted_count": sum(1 for item in preprocessed.values if item.secret),
    }


def run_external_resource_discovery_for_draft(
    *,
    draft: ExternalResourceResolutionDraft,
    resource_request: dict[str, Any],
    answer_text: str,
    namespace_state: dict[str, Any],
    context: NodeExecutionContext | None,
    state: RuntimeState | None,
) -> ExternalResourceResolutionDraft:
    discovery_results = _run_external_resource_discovery(
        queries=list(draft.discovery_queries),
        context=context,
        state=state,
    )
    if not discovery_results:
        return draft
    discovered_delta = _resolve_external_resource_answer(
        resource_request=resource_request,
        answer_text=_discovery_answer_text(answer_text=answer_text, results=discovery_results),
        namespace_state=namespace_state,
        confirmed_fact=draft,
    )
    merged = _merge_external_resource_resolution(draft, discovered_delta)
    return merged.model_copy(
        update={
            "evidence_refs": [
                *list(merged.evidence_refs),
                *_discovery_evidence_refs(discovery_results),
            ],
            "discovery_results": [
                *list(merged.discovery_results),
                *discovery_results,
            ],
            "notes": _dedupe_resource_questions(
                [
                    *list(merged.notes),
                    *_discovery_notes(discovery_results),
                ]
            ),
        },
        deep=True,
    )


def validate_external_resource_draft(
    *,
    resource_request: dict[str, Any],
    draft: ExternalResourceResolutionDraft,
) -> dict[str, Any]:
    return _validate_external_resource_resolution(resource_request, draft)


def resource_facts_to_draft(facts: dict[str, Any]) -> ExternalResourceResolutionDraft:
    resources: dict[str, Any] = {}
    sandbox: dict[str, Any] = {}
    notes: list[str] = []
    for key, raw_fact in facts.items():
        fact = raw_fact if isinstance(raw_fact, dict) else {}
        status = str(fact.get("status") or "")
        if status in {"missing", "declined", "optional_empty"}:
            continue
        value = fact.get("value")
        if not _has_resource_value(value):
            continue
        parts = str(key).split(".")
        if len(parts) >= 2 and parts[0] == "sandbox":
            _assign_nested(sandbox, parts[1], parts[2:], value)
        else:
            _assign_nested(resources, parts[0], parts[1:], value)
        if fact.get("source"):
            notes.append(f"{key}: {fact.get('source')}")
    return ExternalResourceResolutionDraft(
        decision="resolved",
        resources=resources,
        sandbox=sandbox,
        notes=_dedupe_resource_questions(notes),
    )


def _assign_nested(target: dict[str, Any], root_key: str, path: list[str], value: Any) -> None:
    key = str(root_key).strip()
    if not key:
        return
    if not path:
        target[key] = _json_safe_resource_value(value)
        return
    current = target.setdefault(key, {})
    if not isinstance(current, dict):
        current = {}
        target[key] = current
    for part in path[:-1]:
        part_key = str(part)
        next_value = current.setdefault(part_key, {})
        if not isinstance(next_value, dict):
            next_value = {}
            current[part_key] = next_value
        current = next_value
    current[str(path[-1])] = _json_safe_resource_value(value)


def _merge_external_resource_resolution(
    base: ExternalResourceResolutionDraft,
    delta: ExternalResourceResolutionDraft,
) -> ExternalResourceResolutionDraft:
    if delta.decision == "skip":
        return delta
    return ExternalResourceResolutionDraft(
        decision=delta.decision,
        resources=_deep_merge_resource_values(base.resources, delta.resources),
        sandbox=_deep_merge_resource_values(base.sandbox, delta.sandbox),
        discovery_queries=list(delta.discovery_queries),
        discovery_results=[*list(base.discovery_results), *list(delta.discovery_results)],
        evidence_refs=[*list(base.evidence_refs), *list(delta.evidence_refs)],
        missing_questions=list(delta.missing_questions),
        notes=_dedupe_resource_questions([*base.notes, *delta.notes]),
    )


def _normalize_external_resource_resolution(
    request: dict[str, Any],
    draft: ExternalResourceResolutionDraft,
) -> ExternalResourceResolutionDraft:
    resources = dict(draft.resources)
    for item in list(request.get("resources") or []):
        resource_id = str(item.get("resource_id") or "").strip()
        if not resource_id or resource_id not in resources:
            continue
        schema = item.get("value_schema") if isinstance(item.get("value_schema"), dict) else {}
        resources[resource_id] = _normalize_value_for_schema(resources[resource_id], schema, required=True)
        if resources[resource_id] is _MISSING_RESOURCE_VALUE or not _has_resource_value(resources[resource_id]):
            resources.pop(resource_id, None)
    return draft.model_copy(update={"resources": resources}, deep=True)


def _normalize_value_for_schema(value: Any, schema: dict[str, Any], *, required: bool) -> Any:
    if value is None:
        return None if required or _schema_accepts_null(schema) else _MISSING_RESOURCE_VALUE
    if isinstance(value, str) and not value.strip():
        return value if required else _MISSING_RESOURCE_VALUE
    if isinstance(value, list) and not value:
        return value if required else _MISSING_RESOURCE_VALUE
    schema_type = schema.get("type")
    if isinstance(value, dict) and (schema_type == "object" or "properties" in schema):
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required_props = {str(item) for item in list(schema.get("required") or [])}
        normalized: dict[str, Any] = {}
        for key, child_value in value.items():
            key_text = str(key)
            child_schema = properties.get(key_text) if isinstance(properties.get(key_text), dict) else {}
            child_required = key_text in required_props
            next_value = _normalize_value_for_schema(child_value, child_schema, required=child_required)
            if next_value is not _MISSING_RESOURCE_VALUE:
                normalized[key_text] = next_value
        if not normalized and not required:
            return _MISSING_RESOURCE_VALUE
        return normalized
    return value


_MISSING_RESOURCE_VALUE = object()


def _schema_accepts_null(schema: dict[str, Any]) -> bool:
    schema_type = schema.get("type")
    if schema_type == "null":
        return True
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    for key in ("anyOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list) and any(
            isinstance(option, dict) and _schema_accepts_null(option) for option in options
        ):
            return True
    return False


def _deep_merge_resource_values(base: Any, delta: Any) -> Any:
    if isinstance(base, dict) and isinstance(delta, dict):
        merged = {key: _json_safe_resource_value(value) for key, value in base.items()}
        for key, value in delta.items():
            merged[str(key)] = _deep_merge_resource_values(merged.get(str(key)), value)
        return merged
    return _json_safe_resource_value(delta)


def _json_safe_resource_value(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return value


def _preprocess_resource_answer(answer_text: str) -> _PreprocessedResourceAnswer:
    text = str(answer_text or "")
    spans: list[tuple[int, int, str, bool]] = []
    for kind, pattern, secret in (
        ("connection_string", _CONNECTION_STRING_PATTERN, True),
        ("url", _URL_PATTERN, False),
        ("email", _EMAIL_PATTERN, False),
        ("path", _LOCAL_PATH_PATTERN, True),
    ):
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end(), kind, secret))
    for match in _SECRET_ASSIGNMENT_PATTERN.finditer(text):
        spans.append((match.start(1), match.end(1), "secret", True))
    selected: list[tuple[int, int, str, bool]] = []
    for start, end, kind, secret in sorted(spans, key=lambda item: (item[0], -(item[1] - item[0]))):
        if start >= end:
            continue
        if any(not (end <= used_start or start >= used_end) for used_start, used_end, _used_kind, _used_secret in selected):
            continue
        selected.append((start, end, kind, secret))
    if not selected:
        return _PreprocessedResourceAnswer(text=text)
    pieces: list[str] = []
    values: list[_RedactedResourceValue] = []
    cursor = 0
    for index, (start, end, kind, secret) in enumerate(selected, start=1):
        placeholder = f"{_PLACEHOLDER_PREFIX}{index}__"
        pieces.append(text[cursor:start])
        pieces.append(placeholder)
        values.append(
            _RedactedResourceValue(
                placeholder=placeholder,
                value=text[start:end],
                kind=kind,
                secret=secret,
            )
        )
        cursor = end
    pieces.append(text[cursor:])
    return _PreprocessedResourceAnswer(text="".join(pieces), values=values)


def _placeholder_manifest(preprocessed: _PreprocessedResourceAnswer) -> list[dict[str, Any]]:
    return [
        {
            "placeholder": item.placeholder,
            "kind": item.kind,
            "secret": item.secret,
        }
        for item in preprocessed.values
    ]


def _restore_resource_placeholders_in_draft(
    draft: ExternalResourceResolutionDraft,
    preprocessed: _PreprocessedResourceAnswer,
) -> ExternalResourceResolutionDraft:
    if not preprocessed.values:
        return draft
    replacements = {item.placeholder: item.value for item in preprocessed.values}
    return draft.model_copy(
        update={
            "resources": _restore_resource_placeholders(draft.resources, replacements),
            "sandbox": _restore_resource_placeholders(draft.sandbox, replacements),
            "notes": [_redact_resource_placeholders(str(item), replacements) for item in draft.notes],
        },
        deep=True,
    )


def _restore_resource_placeholders(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        restored = value
        for placeholder, original in replacements.items():
            restored = restored.replace(placeholder, original)
        return restored
    if isinstance(value, list):
        return [_restore_resource_placeholders(item, replacements) for item in value]
    if isinstance(value, dict):
        return {str(key): _restore_resource_placeholders(item, replacements) for key, item in value.items()}
    return value


def _redact_resource_placeholders(value: str, replacements: dict[str, str]) -> str:
    redacted = value
    for placeholder in replacements:
        redacted = redacted.replace(placeholder, "[redacted]")
    return redacted


def _redact_declared_secret_paths(payload: dict[str, Any], resource_request: dict[str, Any]) -> dict[str, Any]:
    redacted = deepcopy(payload)
    for field in _external_resource_fields(resource_request):
        if not field.get("secret"):
            continue
        resource_id = str(field.get("resource_id") or "")
        if not resource_id:
            continue
        _set_nested_redacted(redacted.get("resources"), [resource_id, *list(field.get("path") or [])])
    return redacted


def _set_nested_redacted(root: Any, path: list[Any]) -> None:
    current = root
    for part in path[:-1]:
        if not isinstance(current, dict):
            return
        current = current.get(str(part))
    if isinstance(current, dict) and path:
        key = str(path[-1])
        if key in current and _has_resource_value(current.get(key)):
            current[key] = "[redacted]"


def _resolve_external_resource_answer(
    *,
    resource_request: dict[str, Any],
    answer_text: str,
    namespace_state: dict[str, Any],
    confirmed_fact: ExternalResourceResolutionDraft | None = None,
) -> ExternalResourceResolutionDraft:
    product_brief = json.dumps(dict(namespace_state.get("product_brief") or {}), ensure_ascii=False, indent=2)
    runtime_design = json.dumps(dict(namespace_state.get("runtime_design") or {}), ensure_ascii=False, indent=2)
    capability_contract = json.dumps(dict(namespace_state.get("capability_contract") or {}), ensure_ascii=False, indent=2)
    confirmed_payload = _redact_declared_secret_paths(
        confirmed_fact.model_dump(mode="json") if confirmed_fact is not None else {},
        resource_request,
    )
    preprocessed = _preprocess_resource_answer(answer_text)
    draft = call_structured_model(
        stage_id=RESOURCE_RESOLUTION_NODE_ID,
        prompt_id=PromptId.EXTERNAL_RESOURCE_RESOLUTION,
        output_model=ExternalResourceResolutionDraft,
        values={
            "product_brief": product_brief,
            "runtime_design": runtime_design,
            "capability_contract": capability_contract,
            "resource_request": json.dumps(resource_request, ensure_ascii=False, indent=2),
            "resource_questions": json.dumps(_external_resource_questions(resource_request), ensure_ascii=False, indent=2),
            "confirmed_resources": json.dumps(confirmed_payload, ensure_ascii=False, indent=2),
            "resource_answer_placeholders": json.dumps(_placeholder_manifest(preprocessed), ensure_ascii=False, indent=2),
            "user_answer": preprocessed.text,
            "output_json_schema": output_json_schema(ExternalResourceResolutionDraft),
        },
    )
    return _restore_resource_placeholders_in_draft(draft, preprocessed)


def _external_resource_collection_payload(
    request: dict[str, Any],
    *,
    missing_questions: list[str] | None = None,
    reason_notes: list[str] | None = None,
    prior_answer: str = "",
) -> dict[str, Any]:
    fields = _external_resource_fields(request)
    questions = _dedupe_resource_questions(missing_questions or _external_resource_questions(request))
    visible_fields = _resource_fields_for_questions(fields, questions) if missing_questions else fields
    return {
        "type": "resource_collection",
        "node_id": RESOURCE_RESOLUTION_NODE_ID,
        "title": "补充外部资源",
        "message": "请补充这个 Agent 可以使用的外部来源、账号或运行配置；未填写的内容会按暂不提供处理。",
        "questions": questions,
        "fields": [_resource_collection_field_payload(field) for field in visible_fields],
        "scope": "missing_fields" if missing_questions else "full_request",
        "reason_notes": _dedupe_resource_questions(reason_notes or []),
        "prior_answer": prior_answer,
        "resource_request": request,
    }


def _external_resource_questions(request: dict[str, Any]) -> list[str]:
    questions: list[str] = []
    for field in _external_resource_fields(request):
        if not field.get("required"):
            continue
        question = str(field.get("question") or "").strip()
        if question:
            questions.append(question)
    return _dedupe_resource_questions(questions)


def _dedupe_resource_questions(questions: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in questions:
        question = str(raw).strip()
        if not question or question in seen:
            continue
        result.append(question)
        seen.add(question)
    return result[:6]


def _resource_fields_for_questions(fields: list[dict[str, Any]], questions: list[str]) -> list[dict[str, Any]]:
    if not questions:
        return fields
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    normalized_questions = [_normalize_resource_match_text(question) for question in questions]
    for field in fields:
        key = str(field.get("key") or "")
        candidates = [
            key,
            str(field.get("title") or ""),
            str(field.get("question") or ""),
            str(field.get("description") or ""),
        ]
        normalized_candidates = [_normalize_resource_match_text(candidate) for candidate in candidates if candidate]
        if not any(
            _resource_text_matches(question, candidate)
            for question in normalized_questions
            for candidate in normalized_candidates
        ):
            continue
        if key not in seen:
            result.append(field)
            seen.add(key)
    return result


def _resource_text_matches(question: str, candidate: str) -> bool:
    return bool(question and candidate and (question in candidate or candidate in question))


def _normalize_resource_match_text(value: str) -> str:
    return "".join(str(value).lower().split())


def _normalize_external_resource_collection_resume(resume_payload: Any) -> dict[str, Any]:
    if isinstance(resume_payload, str):
        text = resume_payload.strip()
        return {"type": "resource_collection_answer", "decision": "submit", "answer": text}
    if not isinstance(resume_payload, dict):
        raise FactoryModelCallError("resource collection resume payload must be an object or text")
    decision = str(resume_payload.get("decision") or "submit")
    if decision in {"skip", "cancel"}:
        return {
            "type": "resource_collection_answer",
            "decision": decision,
            "answer": str(resume_payload.get("answer") or resume_payload.get("note") or "暂不提供"),
        }
    if str(resume_payload.get("type") or "") != "resource_collection_answer":
        raise FactoryModelCallError("resource collection resume payload must have type=resource_collection_answer")
    answer = str(resume_payload.get("answer") or "").strip()
    if not answer:
        raise FactoryModelCallError("resource collection answer must not be empty")
    return {"type": "resource_collection_answer", "decision": "submit", "answer": answer}


def _external_resource_confirmation_payload(
    *,
    resource_request: dict[str, Any],
    draft: ExternalResourceResolutionDraft,
    validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "resource_confirmation",
        "node_id": RESOURCE_RESOLUTION_NODE_ID,
        "title": "确认外部资源",
        "message": "我把你的回答整理成下面这些资源。确认后会继续制造工具。",
        "items": _external_resource_confirmation_items(resource_request, draft),
        "notes": list(draft.notes),
        "missing_questions": list(validation.get("missing_questions") or []),
    }


def _external_resource_confirmation_items(
    resource_request: dict[str, Any],
    draft: ExternalResourceResolutionDraft,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    source = "tool" if draft.evidence_refs or draft.discovery_results else "user"
    for field in _external_resource_fields(resource_request):
        resource_id = str(field.get("resource_id") or "")
        if resource_id:
            value = _nested_value(draft.resources.get(resource_id), list(field.get("path") or []))
        else:
            requirement_id = str(field.get("sandbox_requirement_id") or "sandbox")
            value = _nested_value(draft.sandbox.get(requirement_id), list(field.get("path") or []))
        items.append(
            {
                "key": field.get("key"),
                "title": field.get("title") or field.get("label") or field.get("key"),
                "required": bool(field.get("required")),
                "secret": bool(field.get("secret")),
                "value_summary": _resource_value_summary(value, secret=bool(field.get("secret"))),
                "status": _confirmation_item_status(value, required=bool(field.get("required"))),
                "source": source if _has_resource_value(value) else "system",
                "evidence_refs": list(draft.evidence_refs)[:3],
            }
        )
    return items


def _nested_value(root: Any, path: list[Any]) -> Any:
    current = root
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(str(part))
    return current


def _resource_value_summary(value: Any, *, secret: bool) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return "未提供"
    if secret:
        return "已提供"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list):
        return "、".join(str(item) for item in value[:4]) + (" ..." if len(value) > 4 else "")
    if isinstance(value, dict):
        keys = list(value)[:4]
        return "、".join(str(key) for key in keys) + (" ..." if len(value) > 4 else "")
    return str(value)


def _confirmation_item_status(value: Any, *, required: bool) -> str:
    if _has_resource_value(value):
        return "confirmed"
    return "missing" if required else "optional_empty"


def _normalize_external_resource_confirmation_resume(resume_payload: Any) -> dict[str, Any]:
    if isinstance(resume_payload, str):
        normalized = resume_payload.strip().lower()
        if normalized in {"y", "yes", "approve", "确认", "继续"}:
            return {"type": "resource_confirmation_result", "decision": "approve"}
        if normalized in {"n", "no", "skip", "暂不提供"}:
            return {"type": "resource_confirmation_result", "decision": "skip", "note": resume_payload}
        return {"type": "resource_confirmation_result", "decision": "revise", "revision_text": resume_payload}
    if not isinstance(resume_payload, dict):
        raise FactoryModelCallError("resource confirmation resume payload must be an object or text")
    decision = str(resume_payload.get("decision") or "approve")
    if decision not in {"approve", "revise", "skip"}:
        raise FactoryModelCallError(f"unsupported resource confirmation decision: {decision}")
    return {
        "type": "resource_confirmation_result",
        "decision": decision,
        "revision_text": str(resume_payload.get("revision_text") or ""),
        "note": str(resume_payload.get("note") or ""),
    }


def _validate_external_resource_resolution(
    request: dict[str, Any],
    draft: ExternalResourceResolutionDraft,
) -> dict[str, Any]:
    errors: list[str] = []
    missing_questions: list[str] = []
    fields = _external_resource_fields(request)
    if draft.decision == "skip":
        return {"errors": errors, "missing_questions": missing_questions}
    errors.extend(_resource_discovery_policy_errors(fields=fields, draft=draft))
    allowed_resource_ids = {
        str(item.get("resource_id") or "").strip()
        for item in list(request.get("resources") or [])
        if str(item.get("resource_id") or "").strip()
    }
    allowed_sandbox_ids = {
        str(item.get("requirement_id") or "sandbox").strip() or "sandbox"
        for item in list(request.get("sandbox_requirements") or [])
    }
    for resource_id in sorted(set(draft.resources) - allowed_resource_ids):
        errors.append(f"{resource_id}: resource is not declared by resource_request")
    for requirement_id in sorted(set(draft.sandbox) - allowed_sandbox_ids):
        errors.append(f"{requirement_id}: sandbox requirement is not declared by resource_request")
    for item in list(request.get("resources") or []):
        resource_id = str(item.get("resource_id") or "").strip()
        if not resource_id:
            continue
        required = bool(item.get("required", True))
        value = draft.resources.get(resource_id)
        if not _has_resource_value(value):
            if required:
                missing_questions.append(_resource_missing_question(item))
            continue
        schema = item.get("value_schema") if isinstance(item.get("value_schema"), dict) else {}
        if schema:
            schema_errors, schema_missing = _resource_schema_validation_issues(
                resource_id=resource_id,
                schema=schema,
                value=value,
                fields=fields,
            )
            errors.extend(schema_errors)
            missing_questions.extend(schema_missing)
    for item in list(request.get("sandbox_requirements") or []):
        requirement_id = str(item.get("requirement_id") or "sandbox").strip() or "sandbox"
        if item.get("network_required"):
            value = _nested_value(draft.sandbox.get(requirement_id), ["network_access"])
            if not isinstance(value, bool):
                missing_questions.append(
                    _field_question_for_path(
                        fields,
                        sandbox_requirement_id=requirement_id,
                        path=["network_access"],
                        fallback="是否允许制造阶段访问外部网络？",
                    )
                )
        for mount_id in list(item.get("mounts_required") or []):
            mount_key = str(mount_id).strip()
            if not mount_key:
                continue
            value = _nested_value(draft.sandbox.get(requirement_id), ["mounts", mount_key])
            if not _has_resource_value(value):
                missing_questions.append(
                    _field_question_for_path(
                        fields,
                        sandbox_requirement_id=requirement_id,
                        path=["mounts", mount_key],
                        fallback=f"请提供{_humanize_identifier(mount_key)}。",
                    )
                )
    return {
        "errors": errors,
        "missing_questions": _dedupe_resource_questions(missing_questions),
    }


def _resource_discovery_policy_errors(
    *,
    fields: list[dict[str, Any]],
    draft: ExternalResourceResolutionDraft,
) -> list[str]:
    errors: list[str] = []
    secret_keys = {str(field.get("key") or "") for field in fields if field.get("secret")}
    private_patterns = (_CONNECTION_STRING_PATTERN, _EMAIL_PATTERN, _LOCAL_PATH_PATTERN, _SECRET_ASSIGNMENT_PATTERN)
    for query in draft.discovery_queries:
        target_key = ".".join(
            part for part in [str(query.target_resource_id or ""), *[str(item) for item in query.target_path]] if part
        )
        if target_key in secret_keys or any(target_key.startswith(f"{key}.") for key in secret_keys):
            errors.append(f"{target_key}: secret resource fields must not be resolved through discovery")
        text = f"{query.question}\n{query.query}"
        if _PLACEHOLDER_PATTERN.search(text):
            errors.append(f"{target_key or query.target_resource_id}: discovery query contains redacted private value")
        if any(pattern.search(text) for pattern in private_patterns):
            errors.append(f"{target_key or query.target_resource_id}: discovery query contains private or secret-looking text")
    return errors


def _resource_schema_validation_issues(
    *,
    resource_id: str,
    schema: dict[str, Any],
    value: Any,
    fields: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    missing_questions: list[str] = []
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path)):
        if error.validator == "required":
            for path in _missing_required_paths(value, list(error.path), list(error.validator_value or [])):
                missing_questions.append(
                    _field_question_for_path(
                        fields,
                        resource_id=resource_id,
                        path=path,
                        fallback=f"请补充{_humanize_identifier(path[-1] if path else resource_id)}。",
                    )
                )
            continue
        path = ".".join(str(item) for item in error.path)
        location = f"{resource_id}.{path}" if path else resource_id
        errors.append(f"{location}: {error.message}")
    return errors, missing_questions


def _missing_required_paths(root: Any, base_path: list[Any], required_names: list[Any]) -> list[list[str]]:
    instance = _nested_value(root, base_path)
    if not isinstance(instance, dict):
        return [[str(item) for item in base_path]]
    missing: list[list[str]] = []
    for name in required_names:
        key = str(name)
        if not _has_resource_value(instance.get(key)):
            missing.append([*[str(item) for item in base_path], key])
    return missing


def _field_question_for_path(
    fields: list[dict[str, Any]],
    *,
    path: list[str],
    fallback: str,
    resource_id: str = "",
    sandbox_requirement_id: str = "",
) -> str:
    normalized_path = [str(item) for item in path]
    for field in fields:
        if resource_id and str(field.get("resource_id") or "") != resource_id:
            continue
        if sandbox_requirement_id and str(field.get("sandbox_requirement_id") or "") != sandbox_requirement_id:
            continue
        if [str(item) for item in list(field.get("path") or [])] == normalized_path:
            question = str(field.get("question") or "").strip()
            if question:
                return question
    return fallback


def _resource_missing_question(item: dict[str, Any]) -> str:
    value_schema = item.get("value_schema") if isinstance(item.get("value_schema"), dict) else {}
    title = _field_title(value_schema, fallback=str(item.get("resource_id") or "外部资源"))
    return f"请补充{title}。"


def _external_resource_fields(request: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for item in list(request.get("resources") or []):
        resource_id = str(item.get("resource_id") or "").strip()
        if not resource_id:
            continue
        value_schema = item.get("value_schema") if isinstance(item.get("value_schema"), dict) else {}
        secret_fields = [str(value) for value in list(item.get("secret_fields") or [])]
        resolution_strategy = [str(value) for value in list(item.get("resolution_strategy") or [])]
        properties = value_schema.get("properties") if isinstance(value_schema.get("properties"), dict) else {}
        required_props = {str(value) for value in list(value_schema.get("required") or [])}
        if properties:
            for prop_name, prop_schema in properties.items():
                prop = str(prop_name)
                schema = prop_schema if isinstance(prop_schema, dict) else {}
                key = f"{resource_id}.{prop}"
                title = _field_title(schema, fallback=prop)
                fields.append(
                    {
                        "key": key,
                        "resource_id": resource_id,
                        "path": [prop],
                        "title": title,
                        "question": _field_question(schema, title=title),
                        "description": _field_description(schema, fallback=str(item.get("description") or "")),
                        "placeholder": _field_placeholder(schema),
                        "input_kind": _field_input_kind(schema),
                        "required": bool(item.get("required", True)) and prop in required_props,
                        "secret": _field_is_secret(key, secret_fields, schema=schema),
                        "resolution_strategy": resolution_strategy,
                    }
                )
            for secret_path in secret_fields:
                key = f"{resource_id}.{secret_path}"
                if any(field.get("key") == key for field in fields):
                    continue
                title = _humanize_identifier(secret_path)
                fields.append(
                    {
                        "key": key,
                        "resource_id": resource_id,
                        "path": secret_path.split("."),
                        "title": title,
                        "question": f"请提供{title}。",
                        "description": str(item.get("description") or ""),
                        "placeholder": "",
                        "input_kind": "secret",
                        "required": bool(item.get("required", True))
                        and _schema_path_is_required(value_schema, secret_path.split(".")),
                        "secret": True,
                        "resolution_strategy": _dedupe_resource_strategy([*resolution_strategy, "secret"]),
                    }
                )
            continue
        title = _field_title(value_schema, fallback=resource_id)
        fields.append(
            {
                "key": resource_id,
                "resource_id": resource_id,
                "path": [],
                "title": title,
                "question": _field_question(value_schema, title=title),
                "description": _field_description(value_schema, fallback=str(item.get("description") or "")),
                "placeholder": _field_placeholder(value_schema),
                "input_kind": _field_input_kind(value_schema),
                "required": bool(item.get("required", True)),
                "secret": False,
                "resolution_strategy": resolution_strategy,
            }
        )
    for item in list(request.get("sandbox_requirements") or []):
        requirement_id = str(item.get("requirement_id") or "sandbox").strip() or "sandbox"
        if item.get("network_required"):
            fields.append(
                {
                    "key": f"sandbox.{requirement_id}",
                    "sandbox_requirement_id": requirement_id,
                    "path": ["network_access"],
                    "title": "允许外部网络访问",
                    "question": "是否允许制造阶段访问外部网络？",
                    "description": "允许后，工具制造可以用你提供的来源做连通性探测。",
                    "placeholder": "是 / 否",
                    "input_kind": "boolean",
                    "required": True,
                    "secret": False,
                }
            )
        for mount_id in list(item.get("mounts_required") or []):
            mount_key = str(mount_id).strip()
            if not mount_key:
                continue
            title = _humanize_identifier(mount_key)
            fields.append(
                {
                    "key": f"sandbox.{requirement_id}.mounts.{mount_key}",
                    "sandbox_requirement_id": requirement_id,
                    "path": ["mounts", mount_key],
                    "title": title,
                    "question": f"请提供{title}。",
                    "description": "需要在制造或运行时读取的本地路径。",
                    "placeholder": "",
                    "input_kind": "path",
                    "required": True,
                    "secret": False,
                }
            )
    return fields


def _has_resource_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | dict):
        return bool(value)
    return True


def _schema_ui(schema: dict[str, Any]) -> dict[str, Any]:
    value = schema.get(RESOURCE_FIELD_UI_EXTENSION)
    return value if isinstance(value, dict) else {}


def _sanitize_resource_value_schema(schema: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(schema)
    _strip_generated_schema_hints(sanitized)
    return sanitized


def _strip_generated_schema_hints(value: Any) -> None:
    if isinstance(value, dict):
        for key in list(value):
            if key in _SCHEMA_HINT_KEYS:
                value.pop(key, None)
        for child in value.values():
            _strip_generated_schema_hints(child)
    elif isinstance(value, list):
        for child in value:
            _strip_generated_schema_hints(child)


def _field_title(schema: dict[str, Any], *, fallback: str) -> str:
    ui = _schema_ui(schema)
    title = ui.get("title") or ui.get("label") or schema.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return _humanize_identifier(fallback)


def _field_question(schema: dict[str, Any], *, title: str) -> str:
    ui = _schema_ui(schema)
    question = ui.get("question")
    if isinstance(question, str) and question.strip():
        return question.strip()
    return f"请提供{title}。"


def _field_description(schema: dict[str, Any], *, fallback: str) -> str:
    ui = _schema_ui(schema)
    description = ui.get("help") or ui.get("description") or schema.get("description") or fallback
    return description.strip() if isinstance(description, str) else ""


def _field_placeholder(schema: dict[str, Any]) -> str:
    ui = _schema_ui(schema)
    placeholder = ui.get("placeholder")
    return placeholder.strip() if isinstance(placeholder, str) else ""


def _field_input_kind(schema: dict[str, Any]) -> str:
    ui = _schema_ui(schema)
    input_kind = ui.get("input_kind")
    if isinstance(input_kind, str) and input_kind.strip():
        return input_kind.strip()
    schema_type = schema.get("type")
    schema_format = schema.get("format")
    if schema_format == "uri":
        return "url"
    if schema_format in {"password", "secret"} or schema.get("writeOnly"):
        return "secret"
    if schema_type == "array":
        return "list"
    if schema_type == "object":
        return "object"
    if schema_type == "boolean":
        return "boolean"
    return "text"


def _schema_path_is_required(schema: dict[str, Any], path: list[str]) -> bool:
    if not path:
        return True
    current_schema = schema
    for index, part in enumerate(path):
        if not isinstance(current_schema, dict):
            return False
        required_props = {str(item) for item in list(current_schema.get("required") or [])}
        if str(part) not in required_props:
            return False
        if index == len(path) - 1:
            return True
        properties = current_schema.get("properties") if isinstance(current_schema.get("properties"), dict) else {}
        next_schema = properties.get(str(part))
        if not isinstance(next_schema, dict):
            return False
        current_schema = next_schema
    return True


def _resource_collection_field_payload(field: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": field.get("key"),
        "title": field.get("title") or field.get("key"),
        "question": field.get("question") or "",
        "description": field.get("description") or "",
        "placeholder": field.get("placeholder") or "",
        "input_kind": field.get("input_kind") or "text",
        "required": bool(field.get("required")),
        "secret": bool(field.get("secret")),
        "resolution_strategy": _dedupe_resource_strategy(list(field.get("resolution_strategy") or [])),
    }


def _humanize_identifier(value: str) -> str:
    cleaned = str(value).replace(".", " ").replace("_", " ").replace("-", " ").strip()
    return " ".join(part for part in cleaned.split() if part) or str(value)


def _field_is_secret(key: str, secret_fields: list[str], *, schema: dict[str, Any] | None = None) -> bool:
    normalized = key.lower()
    if any(normalized.endswith(str(item).lower()) for item in secret_fields):
        return True
    schema = schema or {}
    ui = _schema_ui(schema)
    return bool(ui.get("secret")) or bool(schema.get("writeOnly")) or schema.get("format") in {"password", "secret"}


def _dedupe_resource_strategy(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def commit_resource_facts_from_draft(
    *,
    resource_request: dict[str, Any],
    draft: ExternalResourceResolutionDraft,
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    if draft.decision == "skip":
        return facts
    resources = draft.resources
    sandbox = draft.sandbox
    evidence_refs = list(draft.evidence_refs)
    secret_fields = _secret_field_map(resource_request)
    used_by = _used_by_map(resource_request)
    for resource_id, value in resources.items():
        _flatten_resource_value(
            facts=facts,
            prefix=str(resource_id),
            value=value,
            secret_fields=secret_fields.get(str(resource_id), set()),
            evidence_refs=evidence_refs,
            required_by=used_by.get(str(resource_id), []),
            source="tool" if evidence_refs else "user",
            status="discovered" if evidence_refs else "confirmed",
        )
    for requirement_id, value in sandbox.items():
        _flatten_resource_value(
            facts=facts,
            prefix=f"sandbox.{requirement_id}",
            value=value,
            secret_fields=set(),
            evidence_refs=evidence_refs,
            required_by=[],
            source="user",
            status="confirmed",
        )
    return facts


def declined_resource_facts(*, resource_request: dict[str, Any], note: str = "") -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for field in _external_resource_fields(resource_request):
        key = str(field.get("key") or "")
        if not key:
            continue
        facts[key] = ResourceFact(
            key=key,
            value=None,
            secret=bool(field.get("secret")),
            status="declined",
            source="user",
            confidence=1.0,
            evidence_refs=[{"source": "user", "summary": note}] if note else [],
            required_by=[],
        ).model_dump(mode="json")
    return facts


def resource_resolution_report(
    *,
    draft: ExternalResourceResolutionDraft | None = None,
    facts: dict[str, Any] | None = None,
    status: str = "valid",
    missing_questions: list[str] | None = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> ResourceResolutionReport:
    return ResourceResolutionReport(
        status=status,  # type: ignore[arg-type]
        facts_count=len(dict(facts or {})),
        missing_questions=_dedupe_resource_questions(list(missing_questions or [])),
        discovery_results=list(draft.discovery_results) if draft is not None else [],
        errors=list(errors or []),
        warnings=list(warnings or []),
    )


def _flatten_resource_value(
    *,
    facts: dict[str, Any],
    prefix: str,
    value: Any,
    secret_fields: set[str],
    evidence_refs: list[dict[str, Any]],
    required_by: list[str],
    source: str,
    status: str,
) -> None:
    if isinstance(value, dict):
        if not value:
            facts[prefix] = ResourceFact(
                key=prefix,
                value={},
                status="optional_empty",
                source=source,  # type: ignore[arg-type]
                evidence_refs=evidence_refs,
                required_by=required_by,
            ).model_dump(mode="json")
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}"
            _flatten_resource_value(
                facts=facts,
                prefix=next_prefix,
                value=child,
                secret_fields=secret_fields,
                evidence_refs=evidence_refs,
                required_by=required_by,
                source=source,
                status=status,
            )
        return
    if isinstance(value, list) and not value:
        fact_status = "optional_empty"
    elif _has_resource_value(value):
        fact_status = status
    else:
        fact_status = "missing"
    facts[prefix] = ResourceFact(
        key=prefix,
        value=value,
        secret=_fact_key_is_secret(prefix, secret_fields),
        status=fact_status,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        evidence_refs=evidence_refs,
        required_by=required_by,
    ).model_dump(mode="json")


def _secret_field_map(resource_request: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for item in list(resource_request.get("resources") or []):
        resource_id = str(item.get("resource_id") or "")
        if resource_id:
            result[resource_id] = {str(value) for value in list(item.get("secret_fields") or [])}
    return result


def _used_by_map(resource_request: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in list(resource_request.get("resources") or []):
        resource_id = str(item.get("resource_id") or "")
        if resource_id:
            result[resource_id] = [str(value) for value in list(item.get("used_by") or []) if str(value).strip()]
    return result


def _fact_key_is_secret(key: str, secret_fields: set[str]) -> bool:
    normalized = key.lower()
    return any(normalized.endswith(str(item).lower()) for item in secret_fields)


def _run_external_resource_discovery(
    *,
    queries: list[ExternalResourceDiscoveryQuery],
    context: NodeExecutionContext | None,
    state: RuntimeState | None,
) -> list[ExternalResourceDiscoveryResult]:
    if not queries:
        return []
    registry = getattr(getattr(context, "services", None), "tool_registry", None)
    model_operation_service = getattr(getattr(context, "services", None), "model_operation_service", None)
    if context is None or registry is None or model_operation_service is None:
        return [
            ExternalResourceDiscoveryResult(query=query, status="unavailable", error="tool registry is not available")
            for query in queries
        ]
    tool_ids = _resource_discovery_tool_ids(registry)
    tools = list(registry.model_tools(tool_ids)) if tool_ids else []
    if not tools:
        return [
            ExternalResourceDiscoveryResult(query=query, status="unavailable", error="no discovery-capable tools are registered")
            for query in queries
        ]
    results: list[ExternalResourceDiscoveryResult] = []
    for query in queries:
        context.emit_event(
            {
                "event_type": "resource_discovery_started",
                "query": query.query,
                "target_resource_id": query.target_resource_id,
                "target_path": list(query.target_path),
            }
        )
        result = _run_single_resource_discovery(
            query=query,
            context=context,
            state=state,
            tools=tools,
            tool_ids=tool_ids,
        )
        context.emit_event(
            {
                "event_type": "resource_discovery_completed",
                "status": result.status,
                "tool_id": result.tool_id,
                "query": query.query,
                "error": result.error,
            }
        )
        results.append(result)
    return results


def _resource_discovery_tool_ids(registry: Any) -> list[str]:
    if not hasattr(registry, "system_tool_ids"):
        return []
    candidates = [str(item) for item in registry.system_tool_ids()]
    selected: list[str] = []
    for tool_id in candidates:
        normalized = tool_id.lower()
        if (
            "search" in normalized
            or "fetch" in normalized
            or "tavily" in normalized
            or normalized in {"knowledge", "skill"}
        ):
            selected.append(tool_id)
    return selected


def _run_single_resource_discovery(
    *,
    query: ExternalResourceDiscoveryQuery,
    context: NodeExecutionContext,
    state: RuntimeState | None,
    tools: list[Any],
    tool_ids: list[str],
) -> ExternalResourceDiscoveryResult:
    model_operation_service = context.services.model_operation_service
    registry = context.services.tool_registry
    if model_operation_service is None or registry is None:
        return ExternalResourceDiscoveryResult(query=query, status="unavailable", error="model operation or tool registry is unavailable")
    messages: list[Any] = [
        SystemMessage(
            content=(
                "You resolve public external resource facts for FastAgentFactory. "
                "Use only registered tools. Do not invent values. "
                "Return a concise Chinese summary with evidence URLs or tool result identifiers. "
                "Never ask for or expose secrets."
            )
        ),
        HumanMessage(
            content=json.dumps(
                {
                    "question": query.question,
                    "query": query.query,
                    "target_resource_id": query.target_resource_id,
                    "target_path": query.target_path,
                    "reason": query.reason,
                    "available_tool_ids": tool_ids,
                },
                ensure_ascii=False,
            )
        ),
    ]
    try:
        first = model_operation_service.tool_bound_chat(
            state=state,
            messages=messages,
            tools=tools,
            emit_event=context.emit_event,
            services=context.services,
            node_id=context.node_id,
        )
        if not first.tool_calls:
            return ExternalResourceDiscoveryResult(
                query=query,
                status="completed",
                summary=first.final_answer or first.assistant_draft or "",
                evidence_refs=[],
            )
        ai_message = first.ai_message if isinstance(first.ai_message, AIMessage) else AIMessage(content=first.assistant_draft or "", tool_calls=first.tool_calls)
        tool_messages: list[ToolMessage] = []
        evidence_refs: list[dict[str, Any]] = []
        tool_id = ""
        for call in first.tool_calls[:3]:
            call_id = str(call.get("id") or call.get("tool_call_id") or call.get("name") or "resource_discovery")
            tool_id = str(call.get("name") or "")
            args = call.get("args") if isinstance(call.get("args"), dict) else call.get("arguments")
            arguments = args if isinstance(args, dict) else {}
            execution = registry.execute(tool_id, arguments, state=state)
            payload = {
                "status": execution.status,
                "output": execution.output,
                "error": execution.error,
                "summary": execution.observation_summary,
            }
            evidence_refs.append(_resource_discovery_evidence_ref(tool_id=tool_id, status=execution.status, payload=payload))
            tool_messages.append(ToolMessage(content=json.dumps(payload, ensure_ascii=False), tool_call_id=call_id))
        final = model_operation_service.tool_bound_chat(
            state=state,
            messages=[*messages, ai_message, *tool_messages],
            tools=tools,
            emit_event=context.emit_event,
            services=context.services,
            node_id=context.node_id,
        )
        return ExternalResourceDiscoveryResult(
            query=query,
            status="completed",
            tool_id=tool_id,
            summary=final.final_answer or final.assistant_draft or "",
            evidence_refs=evidence_refs,
        )
    except Exception as exc:
        return ExternalResourceDiscoveryResult(
            query=query,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )


def _discovery_answer_text(*, answer_text: str, results: list[ExternalResourceDiscoveryResult]) -> str:
    return json.dumps(
        {
            "user_answer": answer_text,
            "system_discovery_results": [result.model_dump(mode="json") for result in results],
            "instruction": "Map only evidence-backed public facts into the declared resource schema. Keep unresolved items in missing_questions.",
        },
        ensure_ascii=False,
    )


def _discovery_evidence_refs(results: list[ExternalResourceDiscoveryResult]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for result in results:
        refs.extend(dict(item) for item in result.evidence_refs if isinstance(item, dict))
    return refs


def _discovery_notes(results: list[ExternalResourceDiscoveryResult]) -> list[str]:
    notes: list[str] = []
    for result in results:
        if result.status == "completed" and result.summary:
            notes.append(result.summary[:300])
        elif result.error:
            notes.append(result.error[:300])
    return notes


def _resource_discovery_evidence_ref(*, tool_id: str, status: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload_text = _short_json(payload, limit=1200)
    return {
        "source": "tool",
        "tool_id": tool_id,
        "status": status,
        "result_hash": hashlib.sha256(payload_text.encode("utf-8")).hexdigest()[:16],
        "urls": _extract_urls(payload_text)[:5],
        "summary": _short_json(payload, limit=300),
    }


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in _URL_PATTERN.finditer(text):
        value = match.group(0).rstrip(".,;，。；")
        if value in seen:
            continue
        urls.append(value)
        seen.add(value)
    return urls


def _short_json(value: Any, *, limit: int = 600) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
