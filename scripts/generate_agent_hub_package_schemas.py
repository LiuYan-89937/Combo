from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.runtime_contracts.schema import (
    AgentPackageManifest,
    ContextContract,
    DependenciesContract,
    ModelContract,
    OPTIONAL_AGENT_PACKAGE_CONTRACTS,
    REQUIRED_AGENT_PACKAGE_CONTRACTS,
    ResourcesContract,
    SchedulerContract,
    SchedulerSeedContract,
    SUPPORTED_AGENT_PACKAGE_CONTRACTS,
    ToolsContract,
)


CONTRACT_MODELS = {
    "context": ContextContract,
    "dependencies": DependenciesContract,
    "model": ModelContract,
    "resources": ResourcesContract,
    "scheduler": SchedulerContract,
    "scheduler_seed": SchedulerSeedContract,
    "tools": ToolsContract,
}
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "services"
    / "agent_hub"
    / "agent_hub"
    / "agent_package_schemas.json"
)


def build_schema_bundle() -> dict[str, Any]:
    return {
        "version": "agenthub.package_schemas.v1",
        "required_contracts": sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS),
        "optional_contracts": sorted(OPTIONAL_AGENT_PACKAGE_CONTRACTS),
        "supported_contracts": sorted(SUPPORTED_AGENT_PACKAGE_CONTRACTS),
        "manifest": AgentPackageManifest.model_json_schema(mode="validation"),
        "assembly_spec": AgentAssemblySpec.model_json_schema(mode="validation"),
        "contracts": {
            contract_id: model.model_json_schema(mode="validation")
            for contract_id, model in sorted(CONTRACT_MODELS.items())
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the standalone AgentHub package validation schemas."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the committed schema bundle differs from the core contracts.",
    )
    arguments = parser.parse_args()
    content = json.dumps(
        build_schema_bundle(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if arguments.check:
        if not arguments.output.is_file() or arguments.output.read_text(encoding="utf-8") != content:
            raise SystemExit(
                "AgentHub package schemas are stale; run "
                "scripts/generate_agent_hub_package_schemas.py"
            )
        return
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
