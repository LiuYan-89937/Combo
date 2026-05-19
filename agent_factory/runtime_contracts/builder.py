from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from agent_factory.runtime_contracts.contribution import RuntimeBuildResult, RuntimeContributionMerger
from agent_factory.runtime_contracts.loader import LoadedAgentPackage
from agent_factory.runtime_contracts.registry import RuntimeContractRegistry
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
        missing = sorted({"render", "resources", "sandbox", "session", "tools"} - set(package.contracts))
        if missing:
            raise ValueError("agent package missing required runtime contracts: " + ", ".join(missing))
        context = RuntimeBuildContext(
            package_root=package.package_root,
            package=package,
            resources=_resource_values(package.resources),
            sandbox_contract=package.sandbox_contract,
        )
        contracts = [self.registry.parse(payload) for payload in package.contracts.values()]
        contributions = []
        for contract in contracts:
            if not bool(getattr(contract, "enabled", True)):
                continue
            contributions.append(self.registry.builder_for(contract).build(contract, context))
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
