from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from agent_factory.package import PackageValidator
from agent_factory.specs import (
    AgentPackagePrimitives,
    EnvironmentProbeReport,
    ReadinessReport,
    ResourceContractsSpec,
)


PRIMITIVE_FILE_MAP = {
    "instructions": "instructions.yaml",
    "output": "output.yaml",
    "conversation": "conversation.yaml",
    "run_context": "run_context.yaml",
    "toolsets": "toolsets.yaml",
    "knowledge": "knowledge.yaml",
    "guardrails": "guardrails.yaml",
    "handoffs": "handoffs.yaml",
    "observability": "observability.yaml",
}


class PackageWriter:
    def __init__(self, validator: PackageValidator | None = None) -> None:
        self.validator = validator or PackageValidator()
        self.yaml = YAML()
        self.yaml.default_flow_style = False

    def write_primitives(
        self,
        output_dir: str | Path,
        primitives: AgentPackagePrimitives,
    ):
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        dumped = primitives.model_dump(mode="json", by_alias=True, exclude_none=True)
        for field_name, filename in PRIMITIVE_FILE_MAP.items():
            with (root / filename).open("w", encoding="utf-8") as handle:
                self.yaml.dump(dumped[field_name], handle)
        return self.validator.validate_primitives(root)

    def write_condition_specs(
        self,
        output_dir: str | Path,
        *,
        environment: EnvironmentProbeReport,
        resource_contracts: ResourceContractsSpec,
        readiness: ReadinessReport,
    ) -> None:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        files = {
            "environment.yaml": environment,
            "resource_contracts.yaml": resource_contracts,
            "readiness.yaml": readiness,
        }
        for filename, model in files.items():
            with (root / filename).open("w", encoding="utf-8") as handle:
                self.yaml.dump(
                    model.model_dump(mode="json", by_alias=True, exclude_none=True),
                    handle,
                )
        external_config = _external_config_template(resource_contracts)
        if external_config is not None:
            with (root / "external_config.yaml").open("w", encoding="utf-8") as handle:
                self.yaml.dump(external_config, handle)


def _external_config_template(resource_contracts: ResourceContractsSpec) -> dict[str, Any] | None:
    values: dict[str, str] = {}
    required_keys: list[str] = []
    secret_keys: list[str] = []
    sources: list[str] = []
    resource_refs: list[str] = []
    tool_refs: list[str] = []
    for resource in resource_contracts.resources:
        if resource.type not in {"external_api", "http_endpoint", "realtime_data"}:
            continue
        details = resource.details
        condition = details.get("condition") if isinstance(details.get("condition"), dict) else {}
        tool_id = str(details.get("tool_id") or condition.get("condition_id") or resource.id)
        brief = _research_brief_from_details(details)
        service_id, service_name = _external_service_identity(resource, details, condition)
        if brief:
            brief_data = brief.get("brief") if isinstance(brief.get("brief"), dict) else brief
            if isinstance(brief_data, dict):
                service_id = str(brief_data.get("service_id") or service_id)
                service_name = str(brief_data.get("service_name") or service_name)
                for source in brief_data.get("sources", []) or []:
                    if isinstance(source, dict) and source.get("url"):
                        source_url = str(source["url"])
                        if source_url not in sources:
                            sources.append(source_url)
                for field in brief_data.get("recommended_config_fields", []) or []:
                    if isinstance(field, dict) and field.get("key"):
                        key = _env_key(str(field["key"]))
                        values.setdefault(key, str(field.get("value") or ""))
                        if field.get("required", True) and key not in required_keys:
                            required_keys.append(key)
                        if field.get("secret") and key not in secret_keys:
                            secret_keys.append(key)
        compact_tool_id = tool_id.split(".")[0]
        if compact_tool_id and compact_tool_id not in tool_refs:
            tool_refs.append(compact_tool_id)
        if resource.id not in resource_refs:
            resource_refs.append(resource.id)
    if not values and not sources and not resource_refs:
        return None
    values = _drop_generic_external_service_keys(values)
    required_keys = [key for key in required_keys if key in values]
    secret_keys = [key for key in secret_keys if key in values]
    missing_required = [key for key in required_keys if not values.get(key)]
    return {
        "schema_version": "0.1",
        "kind": "ExternalResourceConfig",
        "status": "needs_user_configuration" if missing_required or not values else "ready",
        "instructions": [
            "This file is intentionally env-like: one key maps to one value.",
            "Do not paste real secrets here; use a .env key or secret-manager reference.",
            "Tools must return status=needs_configuration until required values are completed.",
        ],
        "values": dict(sorted(values.items())),
        "required_keys": sorted(required_keys),
        "secret_keys": sorted(secret_keys),
        "source_urls": sources[:5],
        "resource_refs": resource_refs,
        "tool_refs": tool_refs,
    }


def _external_service_identity(
    resource: object,
    details: dict[str, Any],
    condition: dict[str, Any],
) -> tuple[str, str]:
    text = " ".join(
        [
            str(getattr(resource, "id", "")),
            str(getattr(resource, "description", "")),
            str(getattr(resource, "ref", "")),
            str(details),
            str(condition),
        ]
    )
    name = _service_name_from_research(details) or "external_service"
    return _safe_field_key(name), name


def _drop_generic_external_service_keys(values: dict[str, str]) -> dict[str, str]:
    if not any(not key.startswith("EXTERNAL_SERVICE_") for key in values):
        return values
    return {key: value for key, value in values.items() if not key.startswith("EXTERNAL_SERVICE_")}


def _research_brief_from_details(details: dict[str, Any]) -> dict[str, Any] | None:
    brief = details.get("research_brief")
    if isinstance(brief, dict):
        return brief
    return None


def _service_name_from_research(details: dict[str, Any]) -> str | None:
    research_results = details.get("web_research_results")
    if not isinstance(research_results, list):
        return None
    for item in research_results:
        if not isinstance(item, dict):
            continue
        text = f"{item.get('title') or ''} {item.get('snippet') or ''}".strip()
        if text:
            match = re.search(r"([\w\u4e00-\u9fff-]{2,30})(?:\s*(?:API|接口|开发者|文档))", text)
            if match:
                return match.group(1).strip("-_ ")
    return None


def _safe_field_key(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    return key or "external_service"


def _env_key(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", _safe_field_key(value)).strip("_").upper()
    return key or "EXTERNAL_RESOURCE"
