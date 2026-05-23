from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from agent_factory.runtime_contracts.contribution import RuntimeBuildResult, RuntimeContributionMerger
from agent_factory.runtime_contracts.loader import LoadedAgentPackage
from agent_factory.runtime_contracts.registry import RuntimeContractRegistry
from agent_factory.runtime_contracts.schema import REQUIRED_AGENT_PACKAGE_CONTRACTS
from agent_factory.runtime_kernel.bindings import RuntimeServices


@dataclass(frozen=True, slots=True)
class RuntimeBuildContext:
    package_root: Path
    package: LoadedAgentPackage
    resources: dict[str, object]
    sandbox_contract: dict[str, object]


class RuntimeBuildPlanner:
    def __init__(self, *, registry: RuntimeContractRegistry) -> None:
        self.registry = registry

    def build(
        self,
        package: LoadedAgentPackage,
        *,
        base_services: RuntimeServices,
    ) -> RuntimeBuildResult:
        missing = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS - set(package.contracts))
        if missing:
            raise ValueError("agent package missing required runtime contracts: " + ", ".join(missing))
        context = RuntimeBuildContext(
            package_root=package.package_root,
            package=package,
            resources=_resource_values(package.resources),
            sandbox_contract=package.sandbox_contract,
        )
        contracts = sorted(
            [self.registry.parse(payload) for payload in package.contracts.values()],
            key=_contract_build_priority,
        )
        contributions = []
        build_resources = dict(context.resources)
        for contract in contracts:
            if not bool(getattr(contract, "enabled", True)):
                continue
            contract_context = RuntimeBuildContext(
                package_root=context.package_root,
                package=context.package,
                resources=build_resources,
                sandbox_contract=context.sandbox_contract,
            )
            contribution = self.registry.builder_for(contract).build(contract, contract_context)
            for key, value in contribution.resources.items():
                if key in build_resources and build_resources[key] != value:
                    raise ValueError(f"conflicting runtime build resource: {key}")
                build_resources[key] = value
            contributions.append(contribution)
        result = RuntimeContributionMerger(base_services=base_services).merge(contributions)
        result.contracts = {str(getattr(contract, "type")): _contract_dump(contract) for contract in contracts}
        return result


def _resource_values(payload: dict[str, object]) -> dict[str, object]:
    resources = payload.get("resources", payload)
    if not isinstance(resources, dict):
        raise ValueError("resources contract payload must contain a resources object")
    return dict(resources)


def _contract_dump(contract: BaseModel) -> dict[str, object]:
    return contract.model_dump(mode="json")


def _contract_build_priority(contract: BaseModel) -> tuple[int, str]:
    contract_type = str(getattr(contract, "type"))
    priority = {
        "session": 10,
        "resources": 20,
        "scheduler": 30,
        "tools": 40,
        "render": 50,
        "memory": 60,
        "context": 70,
        "model": 80,
        "sandbox": 80,
        "dependencies": 90,
    }
    return (priority.get(contract_type, 100), contract_type)
