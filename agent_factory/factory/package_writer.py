from __future__ import annotations

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
    services: list[dict[str, Any]] = []
    for resource in resource_contracts.resources:
        if resource.type not in {"external_api", "http_endpoint", "realtime_data"}:
            continue
        details = resource.details
        condition = details.get("condition") if isinstance(details.get("condition"), dict) else {}
        tool_id = str(details.get("tool_id") or condition.get("condition_id") or resource.id)
        research_results = details.get("web_research_results")
        docs: list[dict[str, str]] = []
        if isinstance(research_results, list):
            docs = [
                {
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "snippet": str(item.get("snippet") or ""),
                }
                for item in research_results
                if isinstance(item, dict) and item.get("url")
            ][:5]
        services.append(
            {
                "id": resource.id,
                "resource_ref": resource.id,
                "tool_id": tool_id.split(".")[0],
                "type": resource.type,
                "status": "needs_user_configuration",
                "provider": "",
                "base_url": "",
                "docs": docs,
                "auth": {
                    "type": "api_key",
                    "env_var": "",
                    "credential_ref": "",
                    "send_as": "header",
                    "header_name": "",
                },
                "endpoints": [
                    {
                        "id": "",
                        "method": "GET",
                        "path": "",
                        "purpose": "",
                        "query_params": {},
                        "response_schema": {},
                    }
                ],
                "test_fixture": {
                    "request": {},
                    "response": {},
                },
                "allowed_operations": [],
                "forbidden_operations": [
                    "do_not_log_secrets",
                    "do_not_store_api_keys_in_agent_package",
                    "do_not_call_unlisted_endpoints",
                ],
                "notes": [
                    str(condition.get("description") or "External service configuration is required."),
                    "Fill this file before running the Agent against the real service.",
                ],
            }
        )
    if not services:
        return None
    return {
        "schema_version": "0.1",
        "kind": "ExternalConfigTemplate",
        "status": "needs_user_configuration",
        "instructions": [
            "Fill provider, base_url, auth.env_var or auth.credential_ref, endpoints, and test_fixture.",
            "Do not write real API keys into this file; store secrets in .env or a secret manager and reference the env var name.",
            "Factory generated this template from resource_contracts.yaml and web research evidence.",
        ],
        "services": services,
    }
