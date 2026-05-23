from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.factory_package.constants import STAGE_IDS
from agent_factory.factory_package.nodes import factory_manufacturing_node_provider
from agent_factory.package_runtime import host_runtime_package_view, register_package_patterns
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig


class FactoryCreateAgentSystemPackageTest(unittest.TestCase):
    def test_system_package_manifest_contracts_and_pattern_are_loadable(self) -> None:
        package = AgentPackageLoader().load_path("SystemPackage/factory_create_agent/agent_package.json")

        self.assertEqual(package.assembly_spec.agent.id, "factory_create_agent")
        self.assertEqual(package.manifest.runtime.get("system_package"), True)
        self.assertEqual(package.manifest.runtime.get("execution_backend"), "host")
        self.assertEqual([pattern.pattern_id for pattern in package.patterns], ["factory_manufacturing"])
        self.assertEqual([node.id for node in package.patterns[0].nodes], list(STAGE_IDS))
        self.assertEqual(set(package.contracts), {
            "artifact",
            "context",
            "dependencies",
            "memory",
            "model",
            "node_provider",
            "render",
            "resources",
            "sandbox",
            "scheduler",
            "session",
            "state",
            "tools",
        })

    def test_factory_node_provider_covers_all_stage_impls(self) -> None:
        provider = factory_manufacturing_node_provider()
        impl_ids = [implementation.impl_id for implementation in provider.implementations()]

        self.assertEqual(
            impl_ids,
            [f"builtin.factory.{stage_id}" for stage_id in STAGE_IDS],
        )

    def test_system_package_compiles_through_runtime_contracts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = AgentPackageLoader().load_path("SystemPackage/factory_create_agent/agent_package.json")
            package = host_runtime_package_view(
                _test_runtime_contract_view(package, root),
                runtime_root=root / "runtime",
                artifacts_root=root / "artifacts",
                workdir_root=root / "workdir",
                extension_root=root / "extensions",
            )
            facade = RuntimeKernelFacade(
                checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
                memory_store_config=LangGraphStoreConfig(backend="memory"),
            )
            runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=facade.instance.services,
            )

            register_package_patterns(facade=facade, package=package, runtime_build=runtime_build)
            compiled = AgentAssemblyCompiler(facade=facade).compile(
                package.assembly_spec,
                runtime_build=runtime_build,
            )

            self.assertEqual(compiled.pattern_spec.pattern_id, "factory_create_agent__factory_manufacturing")
            self.assertEqual([node.id for node in compiled.pattern_spec.nodes], list(STAGE_IDS))


def _test_runtime_contract_view(package, root: Path):
    contracts = dict(package.contracts)
    contracts["session"] = {
        "type": "session",
        "version": "session_contract.v0",
        "enabled": True,
        "config": {
            "session_root": str(root / "sessions"),
            "checkpointer_backend": "memory",
            "checkpoint_path": str(root / "checkpoints" / "agent.sqlite"),
        },
    }
    contracts["memory"] = {
        "type": "memory",
        "version": "memory_contract.v0",
        "enabled": False,
        "config": {"memory_system": {"enabled": False}},
    }
    contracts["scheduler"] = {
        "type": "scheduler",
        "version": "scheduler_contract.v0",
        "enabled": False,
        "config": {"store_path": str(root / "scheduler.sqlite")},
    }
    contracts["artifact"] = {
        "type": "artifact",
        "version": "artifact_contract.v0",
        "enabled": True,
        "config": {
            "root": str(root / "artifacts"),
            "index_path": str(root / "artifacts" / "index.jsonl"),
            "allowed_kinds": ["report", "artifact"],
        },
    }
    contracts["tools"] = {
        "type": "tools",
        "version": "tools_contract.v0",
        "enabled": True,
        "config": {
            "builtin_tools_enabled": False,
            "package_tools_enabled": False,
            "instance_extensions_enabled": False,
        },
    }
    return replace(package, contracts=contracts)


if __name__ == "__main__":
    unittest.main()
