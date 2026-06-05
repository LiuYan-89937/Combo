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
    default_session_contract,
    default_state_contract,
    default_tools_contract,
    default_trace_contract,
)
from agent_factory.runtime_contracts.schema import REQUIRED_AGENT_PACKAGE_CONTRACTS


RUNTIME_INDEX_RESOURCES = (
    "references/runtime_contract_index.repair_hints.md",
    "examples/runtime_contract_index.minimal.json",
)


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
        recommended_skill="14-render-and-events",
        recommended_resources=RUNTIME_INDEX_RESOURCES,
    ),
    "context": _item(
        "context",
        default_factory=default_context_contract,
        recommended_skill="03-context-contract",
        recommended_resources=(
            "references/context_contract.schema.json",
            "examples/context_contract.minimal.json",
            "references/context_contract.repair_hints.md",
        ),
    ),
    "dependencies": _item(
        "dependencies",
        default_factory=default_dependencies_contract,
        recommended_skill="02-runtime-contract-index",
        recommended_resources=RUNTIME_INDEX_RESOURCES,
    ),
    "knowledge": _item(
        "knowledge",
        default_factory=default_knowledge_contract,
        recommended_skill="05-knowledge-contract",
        recommended_resources=(
            "references/knowledge_contract.schema.json",
            "examples/knowledge_contract.minimal.json",
            "references/knowledge_contract.repair_hints.md",
        ),
    ),
    "memory": _item(
        "memory",
        default_factory=default_memory_contract,
        recommended_skill="04-memory-contract",
        recommended_resources=(
            "references/memory_contract.schema.json",
            "examples/memory_contract.minimal.json",
            "references/memory_contract.repair_hints.md",
        ),
    ),
    "model": _item(
        "model",
        default_factory=default_model_contract,
        recommended_skill="02-runtime-contract-index",
        recommended_resources=RUNTIME_INDEX_RESOURCES,
    ),
    "node_provider": _item(
        "node_provider",
        default_factory=default_node_provider_contract,
        recommended_skill="10-package-nodes",
        recommended_resources=RUNTIME_INDEX_RESOURCES,
    ),
    "render": _item(
        "render",
        default_factory=default_render_contract,
        recommended_skill="14-render-and-events",
        recommended_resources=RUNTIME_INDEX_RESOURCES,
    ),
    "resources": _item(
        "resources",
        default_factory=default_resources_contract,
        recommended_skill="07-state-resources-contract",
        recommended_resources=(
            "references/resources_contract.schema.json",
            "examples/resources_contract.minimal.json",
            "references/state_resources.repair_hints.md",
        ),
    ),
    "sandbox": _item(
        "sandbox",
        default_factory=default_sandbox_contract,
        recommended_skill="02-runtime-contract-index",
        recommended_resources=RUNTIME_INDEX_RESOURCES,
    ),
    "scheduler": _item(
        "scheduler",
        default_factory=default_scheduler_contract,
        recommended_skill="11-scheduler-contract",
        recommended_resources=(
            "references/scheduler_contract.schema.json",
            "examples/scheduler_contract.minimal.json",
            "references/scheduler_contract.repair_hints.md",
        ),
    ),
    "session": _item(
        "session",
        default_factory=default_session_contract,
        recommended_skill="16-session-contract",
        recommended_resources=(
            "references/session_contract.schema.json",
            "examples/session_contract.minimal.json",
            "references/session_contract.repair_hints.md",
        ),
    ),
    "state": _item(
        "state",
        default_factory=default_state_contract,
        recommended_skill="07-state-resources-contract",
        recommended_resources=(
            "references/state_contract.schema.json",
            "examples/state_contract.minimal.json",
            "references/state_resources.repair_hints.md",
        ),
    ),
    "tools": _item(
        "tools",
        default_factory=default_tools_contract,
        recommended_skill="08-tools-contract",
        recommended_resources=(
            "references/tools_contract.schema.json",
            "examples/tools_contract.minimal.json",
            "references/tools_contract.repair_hints.md",
        ),
    ),
    "trace": _item(
        "trace",
        default_factory=default_trace_contract,
        recommended_skill="06-trace-contract",
        recommended_resources=(
            "references/trace_contract.schema.json",
            "examples/trace_contract.minimal.json",
            "references/trace_contract.repair_hints.md",
        ),
    ),
}


_missing = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS - set(_CONTRACT_CATALOG))
if _missing:
    raise RuntimeError("create-agent contract catalog missing required contracts: " + ", ".join(_missing))
