from __future__ import annotations

import json
from pathlib import Path
import unittest

from agent_factory.factory_package.constants import (
    CREATE_AGENT_ENTRY_NODE_ID,
    CREATE_AGENT_NODE_PROVIDER_ID,
    CREATE_AGENT_STATE_NAMESPACE,
)
from agent_factory.factory_package.nodes import factory_create_agent_entry_node_provider


PACKAGE_ROOT = Path("SystemPackage/factory_create_agent")


class FactoryCreateAgentSystemPackageTest(unittest.TestCase):
    def test_provider_exposes_only_create_agent_entry_node(self) -> None:
        provider = factory_create_agent_entry_node_provider()
        impl_ids = [node.impl_id for node in provider.nodes]

        self.assertEqual(provider.provider_id, CREATE_AGENT_NODE_PROVIDER_ID)
        self.assertEqual(impl_ids, [f"builtin.factory.{CREATE_AGENT_ENTRY_NODE_ID}"])

    def test_state_contract_writes_only_entry_node(self) -> None:
        contract = json.loads((PACKAGE_ROOT / "contracts/state.json").read_text(encoding="utf-8"))

        self.assertEqual(contract["config"]["namespace"], CREATE_AGENT_STATE_NAMESPACE)
        self.assertEqual(contract["config"]["writable_node_ids"], [CREATE_AGENT_ENTRY_NODE_ID])
        self.assertEqual(contract["config"]["schema_path"], "state/create_agent_entry.schema.json")
        self.assertEqual(contract["config"]["initial_state_path"], "state/create_agent_entry.initial.json")

    def test_system_package_uses_placeholder_pattern(self) -> None:
        package = json.loads((PACKAGE_ROOT / "agent_package.json").read_text(encoding="utf-8"))
        assembly = json.loads((PACKAGE_ROOT / "assembly_spec.json").read_text(encoding="utf-8"))
        render = json.loads((PACKAGE_ROOT / "render_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(package["patterns"], ["patterns/create_agent_entry.yaml"])
        self.assertEqual(assembly["runtime"]["pattern_id"], "create_agent_entry")
        self.assertEqual(render["graph_id"], "create_agent_entry")
        self.assertEqual(set(render["nodes"]), {CREATE_AGENT_ENTRY_NODE_ID})

    def test_placeholder_pattern_has_no_manufacturing_domains(self) -> None:
        pattern = (PACKAGE_ROOT / "patterns/create_agent_entry.yaml").read_text(encoding="utf-8")

        self.assertIn("entry_node: create_agent_entry", pattern)
        self.assertIn("impl: builtin.factory.create_agent_entry", pattern)
        old_nodes = [
            "_".join(parts)
            for parts in (
                ("product", "brief"),
                ("runtime", "design"),
                ("capability", "contract"),
                ("capability", "realization"),
                ("scheduler", "preparation"),
                ("package", "build"),
            )
        ]
        for old_node in old_nodes:
            self.assertNotIn(old_node, pattern)


if __name__ == "__main__":
    unittest.main()
