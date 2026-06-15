from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_factory.runtime_contracts.builtins import (
    default_artifact_contract,
    default_context_contract,
    default_dependencies_contract,
    default_knowledge_contract,
    default_memory_contract,
    default_model_contract,
    default_node_provider_contract,
    default_render_contract,
    default_resources_contract,
    default_sandbox_contract,
    default_scheduler_contract,
    default_scheduler_seed_contract,
    default_session_contract,
    default_state_contract,
    default_tools_contract,
    default_trace_contract,
)
from agent_factory.runtime_contracts.schema import REQUIRED_AGENT_PACKAGE_CONTRACTS


OPTIONAL_BASE_CONTRACTS = ("scheduler_seed",)


def system_resources(system_id: str, *, include_example: bool = False) -> tuple[str, ...]:
    resources = [
        f"references/{system_id}.schema.json",
        f"references/{system_id}.repair_hints.md",
    ]
    if include_example:
        resources.insert(1, f"examples/{system_id}.capability.json")
    return tuple(resources)


@dataclass(frozen=True, slots=True)
class CreateAgentContractCatalogItem:
    contract_key: str
    path: str
    default_factory: Callable[[], Any]
    recommended_skill: str
    recommended_resources: tuple[str, ...]

    def default_payload(self) -> dict[str, Any]:
        contract = self.default_factory()
        return contract.model_dump(mode="json", by_alias=True, exclude_none=True)


def required_contract_paths() -> dict[str, str]:
    return {item.contract_key: item.path for item in required_contract_items()}


def base_contract_paths() -> dict[str, str]:
    keys = sorted({*REQUIRED_AGENT_PACKAGE_CONTRACTS, *OPTIONAL_BASE_CONTRACTS})
    return {key: contract_item(key).path for key in keys}


def required_contract_items() -> list[CreateAgentContractCatalogItem]:
    return [_CONTRACT_CATALOG[key] for key in sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS)]


def contract_item(contract_key: str) -> CreateAgentContractCatalogItem:
    try:
        return _CONTRACT_CATALOG[contract_key]
    except KeyError as exc:
        raise ValueError(f"unknown create-agent contract key: {contract_key}") from exc


def contract_skill(contract_key: str) -> str:
    return contract_item(contract_key).recommended_skill


def contract_resources(contract_key: str) -> list[str]:
    return list(contract_item(contract_key).recommended_resources)


def default_contract_payload(contract_key: str) -> dict[str, Any]:
    return contract_item(contract_key).default_payload()


def _item(
    contract_key: str,
    *,
    default_factory: Callable[[], Any],
    recommended_skill: str,
    recommended_resources: tuple[str, ...],
) -> CreateAgentContractCatalogItem:
    return CreateAgentContractCatalogItem(
        contract_key=contract_key,
        path=f"contracts/{contract_key}.json",
        default_factory=default_factory,
        recommended_skill=recommended_skill,
        recommended_resources=recommended_resources,
    )


_CONTRACT_CATALOG = {
    "artifact": _item(
        "artifact",
        default_factory=default_artifact_contract,
        recommended_skill="16-trace-artifact-system",
        recommended_resources=system_resources("trace_artifact_system"),
    ),
    "context": _item(
        "context",
        default_factory=default_context_contract,
        recommended_skill="06-context-system",
        recommended_resources=system_resources("context_system"),
    ),
    "dependencies": _item(
        "dependencies",
        default_factory=default_dependencies_contract,
        recommended_skill="02-model-system",
        recommended_resources=system_resources("model_system"),
    ),
    "knowledge": _item(
        "knowledge",
        default_factory=default_knowledge_contract,
        recommended_skill="08-knowledge-system",
        recommended_resources=system_resources("knowledge_system"),
    ),
    "memory": _item(
        "memory",
        default_factory=default_memory_contract,
        recommended_skill="07-memory-system",
        recommended_resources=system_resources("memory_system"),
    ),
    "model": _item(
        "model",
        default_factory=default_model_contract,
        recommended_skill="02-model-system",
        recommended_resources=system_resources("model_system"),
    ),
    "node_provider": _item(
        "node_provider",
        default_factory=default_node_provider_contract,
        recommended_skill="11-node-provider-system",
        recommended_resources=system_resources("node_provider_system"),
    ),
    "render": _item(
        "render",
        default_factory=default_render_contract,
        recommended_skill="13-render-event-system",
        recommended_resources=system_resources("render_event_system"),
    ),
    "resources": _item(
        "resources",
        default_factory=default_resources_contract,
        recommended_skill="05-resources-system",
        recommended_resources=system_resources("resources_system"),
    ),
    "sandbox": _item(
        "sandbox",
        default_factory=default_sandbox_contract,
        recommended_skill="02-model-system",
        recommended_resources=system_resources("model_system"),
    ),
    "scheduler": _item(
        "scheduler",
        default_factory=default_scheduler_contract,
        recommended_skill="14-scheduler-system",
        recommended_resources=system_resources("scheduler_system"),
    ),
    "scheduler_seed": _item(
        "scheduler_seed",
        default_factory=default_scheduler_seed_contract,
        recommended_skill="15-scheduler-seed-system",
        recommended_resources=system_resources("scheduler_seed_system", include_example=True),
    ),
    "session": _item(
        "session",
        default_factory=default_session_contract,
        recommended_skill="03-session-system",
        recommended_resources=system_resources("session_system"),
    ),
    "state": _item(
        "state",
        default_factory=default_state_contract,
        recommended_skill="04-state-system",
        recommended_resources=system_resources("state_system"),
    ),
    "tools": _item(
        "tools",
        default_factory=default_tools_contract,
        recommended_skill="09-tools-system",
        recommended_resources=system_resources("tools_system"),
    ),
    "trace": _item(
        "trace",
        default_factory=default_trace_contract,
        recommended_skill="16-trace-artifact-system",
        recommended_resources=system_resources("trace_artifact_system"),
    ),
}


_missing = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS - set(_CONTRACT_CATALOG))
if _missing:
    raise RuntimeError("create-agent contract catalog missing required contracts: " + ", ".join(_missing))
