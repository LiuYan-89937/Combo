from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator
from langgraph.types import interrupt

from agent_factory.factory_package.constants import TOOL_MANUFACTURING_NODE_ID
from agent_factory.factory_package.model_call import FactoryModelCallError, call_structured_model
from agent_factory.factory_package.schemas import CapabilityContractOutput, ExternalResourceResolutionDraft
from agent_factory.prompts import PromptId, output_json_schema


RESOURCE_FIELD_UI_EXTENSION = "x-agentfactory-ui"


def _external_resource_request(capability_contract: CapabilityContractOutput) -> dict[str, Any]:
    requirements = []
    for item in capability_contract.resources_required:
        if not item.required:
            continue
        requirements.append(
            {
                "resource_id": item.resource_id,
                "description": item.description,
                "required": item.required,
                "expected_shape": item.expected_shape,
                "value_schema": item.value_schema,
                "default_value": item.default_value,
                "secret_fields": item.secret_fields,
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


def _collect_external_resource_submission(
    *,
    resource_request: dict[str, Any],
    namespace_state: dict[str, Any],
) -> dict[str, Any]:
    raw_answer = _normalize_external_resource_collection_resume(
        interrupt(_external_resource_collection_payload(resource_request))
    )
    if raw_answer["decision"] in {"skip", "cancel"}:
        return _resource_submission_skipped(raw_answer.get("answer") or "user skipped external resources")

    draft = _resolve_external_resource_answer(
        resource_request=resource_request,
        answer_text=str(raw_answer.get("answer") or ""),
        namespace_state=namespace_state,
    )
    validation = _validate_external_resource_resolution(resource_request, draft)
    if draft.decision == "needs_clarification" or validation["missing_questions"]:
        follow_up = _normalize_external_resource_collection_resume(
            interrupt(
                _external_resource_collection_payload(
                    resource_request,
                    missing_questions=[*draft.missing_questions, *validation["missing_questions"]],
                    prior_answer=str(raw_answer.get("answer") or ""),
                )
            )
        )
        if follow_up["decision"] in {"skip", "cancel"}:
            return _resource_submission_skipped(follow_up.get("answer") or "user skipped external resources")
        combined_answer = "\n".join(
            part for part in [str(raw_answer.get("answer") or ""), str(follow_up.get("answer") or "")] if part.strip()
        )
        draft = _resolve_external_resource_answer(
            resource_request=resource_request,
            answer_text=combined_answer,
            namespace_state=namespace_state,
        )
        validation = _validate_external_resource_resolution(resource_request, draft)

    if validation["errors"]:
        raise FactoryModelCallError("external resource answer failed validation: " + "; ".join(validation["errors"]))
    if validation["missing_questions"] and draft.decision != "skip":
        raise FactoryModelCallError(
            "external resource answer is still missing required values: "
            + "; ".join(validation["missing_questions"])
        )

    confirmation_payload = _external_resource_confirmation_payload(
        resource_request=resource_request,
        draft=draft,
        validation=validation,
    )
    confirmation = _normalize_external_resource_confirmation_resume(interrupt(confirmation_payload))
    if confirmation["decision"] == "approve":
        return _resource_submission_from_draft(draft)
    if confirmation["decision"] == "skip":
        return _resource_submission_skipped(str(confirmation.get("note") or "user skipped external resources"))
    if confirmation["decision"] == "revise":
        revised_text = str(confirmation.get("revision_text") or "").strip()
        if not revised_text:
            raise FactoryModelCallError("external resource revision is empty")
        revised_draft = _resolve_external_resource_answer(
            resource_request=resource_request,
            answer_text=revised_text,
            namespace_state=namespace_state,
        )
        revised_validation = _validate_external_resource_resolution(resource_request, revised_draft)
        if revised_validation["errors"] or revised_validation["missing_questions"]:
            raise FactoryModelCallError(
                "external resource revision failed validation: "
                + "; ".join([*revised_validation["errors"], *revised_validation["missing_questions"]])
            )
        approve_revised = _normalize_external_resource_confirmation_resume(
            interrupt(
                _external_resource_confirmation_payload(
                    resource_request=resource_request,
                    draft=revised_draft,
                    validation=revised_validation,
                )
            )
        )
        if approve_revised["decision"] == "approve":
            return _resource_submission_from_draft(revised_draft)
        return _resource_submission_skipped(str(approve_revised.get("note") or "user did not approve resources"))
    raise FactoryModelCallError(f"unsupported external resource confirmation decision: {confirmation['decision']}")


def _resolve_external_resource_answer(
    *,
    resource_request: dict[str, Any],
    answer_text: str,
    namespace_state: dict[str, Any],
) -> ExternalResourceResolutionDraft:
    product_brief = json.dumps(dict(namespace_state.get("product_brief") or {}), ensure_ascii=False, indent=2)
    runtime_design = json.dumps(dict(namespace_state.get("runtime_design") or {}), ensure_ascii=False, indent=2)
    capability_contract = json.dumps(dict(namespace_state.get("capability_contract") or {}), ensure_ascii=False, indent=2)
    return call_structured_model(
        stage_id=TOOL_MANUFACTURING_NODE_ID,
        prompt_id=PromptId.EXTERNAL_RESOURCE_RESOLUTION,
        output_model=ExternalResourceResolutionDraft,
        values={
            "product_brief": product_brief,
            "runtime_design": runtime_design,
            "capability_contract": capability_contract,
            "resource_request": json.dumps(resource_request, ensure_ascii=False, indent=2),
            "resource_questions": json.dumps(_external_resource_questions(resource_request), ensure_ascii=False, indent=2),
            "user_answer": answer_text,
            "output_json_schema": output_json_schema(ExternalResourceResolutionDraft),
        },
    )


def _external_resource_collection_payload(
    request: dict[str, Any],
    *,
    missing_questions: list[str] | None = None,
    prior_answer: str = "",
) -> dict[str, Any]:
    questions = _dedupe_resource_questions(missing_questions or _external_resource_questions(request))
    return {
        "type": "resource_collection",
        "node_id": TOOL_MANUFACTURING_NODE_ID,
        "title": "补充外部资源",
        "message": "还差几项外部资源，补上后我继续制造工具。可以直接一句话回答；不想提供的就说暂不提供。",
        "questions": questions,
        "prior_answer": prior_answer,
        "resource_request": request,
    }


def _external_resource_questions(request: dict[str, Any]) -> list[str]:
    questions: list[str] = []
    for field in _external_resource_fields(request):
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
        "node_id": TOOL_MANUFACTURING_NODE_ID,
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
                        fallback="是否允许制造阶段联网测试？",
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
        "missing_questions": _dedupe_resource_questions([*missing_questions, *draft.missing_questions]),
    }


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


def _resource_submission_from_draft(draft: ExternalResourceResolutionDraft) -> dict[str, Any]:
    return {
        "type": "resource_collection_result",
        "decision": draft.decision,
        "resources": draft.resources,
        "sandbox": draft.sandbox,
        "notes": draft.notes,
    }


def _resource_submission_skipped(note: str) -> dict[str, Any]:
    return {
        "type": "resource_collection_result",
        "decision": "skip",
        "resources": {},
        "sandbox": {},
        "note": note,
    }


def _external_resource_fields(request: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for item in list(request.get("resources") or []):
        resource_id = str(item.get("resource_id") or "").strip()
        if not resource_id:
            continue
        value_schema = item.get("value_schema") if isinstance(item.get("value_schema"), dict) else {}
        secret_fields = [str(value) for value in list(item.get("secret_fields") or [])]
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
                        "required": bool(item.get("required", True)) and prop in required_props,
                        "secret": _field_is_secret(key, secret_fields, schema=schema),
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
                        "required": bool(item.get("required", True)),
                        "secret": True,
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
                "required": bool(item.get("required", True)),
                "secret": False,
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
                    "question": "是否允许制造阶段联网测试？",
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
