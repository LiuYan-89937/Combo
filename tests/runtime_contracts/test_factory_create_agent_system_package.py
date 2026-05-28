from __future__ import annotations

import json
from pathlib import Path
import unittest

from agent_factory.factory_package.constants import (
    CAPABILITY_CONTRACT_NODE_ID,
    PACKAGE_BUILD_NODE_ID,
    PRODUCT_BRIEF_NODE_ID,
    RUNTIME_DESIGN_NODE_ID,
    SCHEDULER_PREPARATION_NODE_ID,
)
from agent_factory.factory_package.nodes import factory_manufacturing_node_provider


PACKAGE_ROOT = Path("SystemPackage/factory_create_agent")


class FactoryCreateAgentSystemPackageTest(unittest.TestCase):
    def test_factory_provider_exposes_current_manufacturing_nodes_only(self) -> None:
        provider = factory_manufacturing_node_provider()
        impl_ids = [node.impl_id for node in provider.nodes]

        self.assertEqual(
            impl_ids,
            [
                f"builtin.factory.{PRODUCT_BRIEF_NODE_ID}",
                f"builtin.factory.{RUNTIME_DESIGN_NODE_ID}",
                f"builtin.factory.{CAPABILITY_CONTRACT_NODE_ID}",
                f"builtin.factory.{SCHEDULER_PREPARATION_NODE_ID}",
                f"builtin.factory.{PACKAGE_BUILD_NODE_ID}",
            ],
        )

    def test_state_contract_writes_only_current_manufacturing_nodes(self) -> None:
        contract = json.loads((PACKAGE_ROOT / "contracts/state.json").read_text(encoding="utf-8"))

        self.assertEqual(
            contract["config"]["writable_node_ids"],
            [
                PRODUCT_BRIEF_NODE_ID,
                RUNTIME_DESIGN_NODE_ID,
                CAPABILITY_CONTRACT_NODE_ID,
                SCHEDULER_PREPARATION_NODE_ID,
                PACKAGE_BUILD_NODE_ID,
            ],
        )

    def test_system_package_has_no_cleared_manufacturing_domains(self) -> None:
        package_files = [
            PACKAGE_ROOT / "patterns/factory_manufacturing.yaml",
            PACKAGE_ROOT / "contracts/state.json",
            PACKAGE_ROOT / "render_manifest.json",
            PACKAGE_ROOT / "state/factory_manufacturing.schema.json",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in package_files)

        cleared_domains = ["_".join(("resource", "resolution")), "_".join(("tool", "manufacturing"))]
        for domain in cleared_domains:
            self.assertNotIn(domain, combined)


if __name__ == "__main__":
    unittest.main()
