from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_contracts.contribution import (
    RuntimeContribution,
    RuntimeContributionMergeError,
    RuntimeContributionMerger,
)
from agent_factory.runtime_contracts.registry import RuntimeContractRegistryError
from agent_factory.runtime_contracts.schema import AgentPackageManifest
from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_render import RenderManifest
from agent_factory.tooling.builtins import get_always_available_system_tool_ids, get_builtin_tool_ids


class RuntimeContractsTest(unittest.TestCase):
    def test_manifest_rejects_path_escape(self) -> None:
        with self.assertRaises(ValueError):
            AgentPackageManifest(
                factory_run_id="run_1",
                assembly_spec_path="../assembly_spec.json",
                render_manifest_path="render_manifest.json",
                resources_path="resources.json",
                sandbox_contract_path="sandbox_contract.json",
                contracts={"session": "contracts/session.json"},
            )

    def test_unknown_contract_type_fails_registry_parse(self) -> None:
        registry = default_runtime_contract_registry()
        with self.assertRaises(RuntimeContractRegistryError):
            registry.parse({"type": "unknown", "version": "unknown.v0", "enabled": True, "config": {}})

    def test_disabled_memory_contract_does_not_contribute_memory_services(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = _write_package(Path(temp_dir), memory_enabled=False)
            package = AgentPackageLoader().load_path(package_path)
            result = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=_base_services(),
            )

            self.assertIsNone(result.services.memory_store)
            self.assertIsNone(result.services.memory_system)
            self.assertIsNotNone(result.services.checkpointer)
            self.assertIsNotNone(result.services.tool_registry)
            self.assertEqual(result.session_config["checkpointer_backend"], "memory")
            self.assertEqual(result.system_wrappers, ["observability.render_node", "system.context_prepare"])
            self.assertIsNotNone(result.services.context_system)

    def test_enabled_memory_contract_contributes_memory_system_service(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = _write_package(Path(temp_dir), memory_enabled=True)
            package = AgentPackageLoader().load_path(package_path)
            result = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=_base_services(),
            )

            self.assertEqual(
                result.system_wrappers,
                ["observability.render_node", "system.context_prepare"],
            )
            self.assertIsNotNone(result.services.memory_store)
            self.assertIsNotNone(result.services.memory_system)
            self.assertIsNotNone(result.services.context_system)

    def test_model_contract_contributes_configured_model_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = _write_package(Path(temp_dir), model_config={"role": "task"})
            package = AgentPackageLoader().load_path(package_path)
            result = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=_base_services(),
            )

            self.assertEqual(getattr(result.services.model_service, "model_role"), "task")
            self.assertEqual(getattr(result.services.model_operation_service, "model_role"), "task")

    def test_enabled_scheduler_contract_contributes_scheduler_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = _write_package(Path(temp_dir), scheduler_enabled=True)
            package = AgentPackageLoader().load_path(package_path)
            result = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=_base_services(),
            )

            self.assertIsNotNone(result.services.scheduler_store)
            self.assertIsNotNone(result.services.scheduler_runtime)
            self.assertNotIn("scheduler_runtime", result.resources)
            self.assertNotIn("scheduler_runtime", result.services.runtime_resources)
            self.assertIs(result.tool_runtime_resources["scheduler_runtime"], result.services.scheduler_runtime)
            self.assertIs(result.services.tool_runtime_resources["scheduler_runtime"], result.services.scheduler_runtime)
            self.assertTrue(result.background_workers)

            result.services.scheduler_runtime.create_job(
                {
                    "job_id": "job_1",
                    "schedule_type": "interval",
                    "schedule_expr": "60",
                    "target": {"target_type": "script_run", "payload": {"command": "echo hello"}},
                }
            )
            tool_result = result.services.tool_registry.execute(
                "scheduler",
                {"action": "list"},
                state=RuntimeState(),
            )
            self.assertEqual(tool_result.status, "completed")
            self.assertEqual(tool_result.output["output"]["jobs"][0]["job_id"], "job_1")

    def test_enabled_knowledge_contract_contributes_runtime_and_system_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = _write_package(Path(temp_dir), memory_enabled=False)
            package = AgentPackageLoader().load_path(package_path)
            result = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=_base_services(),
            )

            self.assertIsNotNone(result.services.knowledge_runtime)
            self.assertIs(result.tool_runtime_resources["knowledge_runtime"], result.services.knowledge_runtime)
            self.assertIs(result.services.tool_runtime_resources["knowledge_runtime"], result.services.knowledge_runtime)
            self.assertIn("knowledge", result.services.tool_registry.list_tool_ids())
            self.assertIn("knowledge", result.services.tool_registry.system_tool_ids())

    def test_runtime_resources_must_be_json_serializable(self) -> None:
        with self.assertRaises(RuntimeContributionMergeError) as context:
            RuntimeContributionMerger(base_services=_base_services()).merge(
                [
                    RuntimeContribution(
                        render_manifest=RenderManifest(graph_id="test_graph"),
                        resources={"bad_runtime_object": object()},
                    )
                ]
            )

        self.assertIn("bad_runtime_object", str(context.exception))

    def test_tools_contract_loads_instance_extensions_outside_package_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "package"
            extension_root = root / "agent_runtime" / "extensions"
            skill_root = extension_root / "skills" / "writer"
            skill_root.mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(
                "---\n"
                "name: writer\n"
                "description: Writing helper.\n"
                "---\n"
                "# Writer\n",
                encoding="utf-8",
            )
            _write_json(
                extension_root / "enabled_skills.json",
                {
                    "version": "enabled_skills.v0",
                    "skills": [{"skill_id": "writer", "path": "skills/writer"}],
                },
            )
            package_path = _write_package(
                package_root,
                memory_enabled=False,
                tools_config={
                    "package_tools_enabled": False,
                    "instance_extensions_enabled": True,
                    "instance_extension_root": str(extension_root),
                },
            )
            package = AgentPackageLoader().load_path(package_path)
            result = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=_base_services(),
            )

            expected_system_tools = sorted([tool_id for tool_id in get_builtin_tool_ids() if tool_id != "scheduler"] + ["skill"])
            self.assertEqual(result.services.tool_registry.list_tool_ids(), expected_system_tools)
            self.assertEqual(result.services.tool_registry.system_tool_ids(), expected_system_tools)

    def test_tools_contract_can_limit_builtin_tool_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = _write_package(
                Path(temp_dir),
                tools_config={
                    "builtin_tools_enabled": True,
                    "builtin_tool_ids": ["ls", "read"],
                    "builtin_workspace_root": "/workdir",
                    "package_tools_enabled": False,
                    "instance_extensions_enabled": False,
                },
            )
            package = AgentPackageLoader().load_path(package_path)
            result = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=_base_services(),
            )

            expected_tools = sorted(["ls", "read", *get_always_available_system_tool_ids()])
            self.assertEqual(result.services.tool_registry.list_tool_ids(), expected_tools)
            self.assertEqual(result.services.tool_registry.system_tool_ids(), expected_tools)

    def test_tools_contract_rejects_unknown_builtin_tool_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = _write_package(
                Path(temp_dir),
                tools_config={
                    "builtin_tools_enabled": True,
                    "builtin_tool_ids": ["not_a_tool"],
                    "package_tools_enabled": False,
                    "instance_extensions_enabled": False,
                },
            )
            package = AgentPackageLoader().load_path(package_path)

            with self.assertRaises(ValueError) as context:
                RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                    package,
                    base_services=_base_services(),
                )

            self.assertIn("unknown builtin tool ids", str(context.exception))

    def test_missing_required_contract_fails_manifest_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = _write_package(Path(temp_dir), include_tools_contract=False)

            with self.assertRaises(ValueError) as context:
                AgentPackageLoader().load_path(package_path)

            self.assertIn("tools", str(context.exception))


def _base_services() -> RuntimeServices:
    return RuntimeServices(
        model_service=object(),
        model_operation_service=object(),
        context_engine=object(),
        policy_engine=object(),
        observability_manager=object(),
    )


def _write_package(
    root: Path,
    *,
    memory_enabled: bool = False,
    include_tools_contract: bool = True,
    tools_config: dict | None = None,
    model_config: dict | None = None,
    scheduler_enabled: bool = False,
) -> Path:
    _write_json(root / "assembly_spec.json", _assembly_spec())
    _write_json(root / "render_manifest.json", _render_manifest())
    _write_json(root / "resources.json", {"version": "factory_resources.v0", "resources": {}})
    _write_json(root / "sandbox_contract.json", {"version": "sandbox_contract.v0", "backend": "docker"})
    contracts = {
        "artifact": "contracts/artifact.json",
        "context": "contracts/context.json",
        "dependencies": "contracts/dependencies.json",
        "knowledge": "contracts/knowledge.json",
        "model": "contracts/model.json",
        "node_provider": "contracts/node_provider.json",
        "render": "contracts/render.json",
        "resources": "contracts/resources.json",
        "sandbox": "contracts/sandbox.json",
        "scheduler": "contracts/scheduler.json",
        "session": "contracts/session.json",
        "state": "contracts/state.json",
        "trace": "contracts/trace.json",
    }
    if include_tools_contract:
        contracts["tools"] = "contracts/tools.json"
    contracts["memory"] = "contracts/memory.json"
    _write_json(root / "contracts/render.json", {"type": "render", "version": "render_contract.v0", "enabled": True, "config": {}})
    _write_json(root / "contracts/context.json", {"type": "context", "version": "context_contract.v0", "enabled": True, "config": {}})
    _write_json(
        root / "contracts/knowledge.json",
        {
            "type": "knowledge",
            "version": "knowledge_contract.v0",
            "enabled": True,
            "config": {
                "root": str(root / ".agent_runtime" / "knowledge"),
                "catalog_path": str(root / ".agent_runtime" / "knowledge" / "catalog" / "knowledge.sqlite"),
                "rag_store": {
                    "backend": "memory",
                    "path": str(root / ".agent_runtime" / "knowledge" / "catalog" / "knowledge_store.sqlite"),
                    "namespace_prefix": ["knowledge"],
                    "index_fields": ["content", "title", "summary"],
                },
            },
        },
    )
    _write_json(root / "contracts/resources.json", {"type": "resources", "version": "resources_contract.v0", "enabled": True, "config": {}})
    _write_json(root / "contracts/sandbox.json", {"type": "sandbox", "version": "sandbox_contract.v0", "enabled": True, "config": {}})
    _write_json(root / "contracts/state.json", {"type": "state", "version": "state_contract.v0", "enabled": False, "config": {}})
    _write_json(root / "contracts/node_provider.json", {"type": "node_provider", "version": "node_provider_contract.v0", "enabled": True, "config": {}})
    _write_json(root / "contracts/artifact.json", {"type": "artifact", "version": "artifact_contract.v0", "enabled": True, "config": {}})
    _write_json(
        root / "contracts/scheduler.json",
        {
            "type": "scheduler",
            "version": "scheduler_contract.v0",
            "enabled": scheduler_enabled,
            "config": {"store_path": str(root / ".agent_runtime" / "scheduler" / "agent.sqlite")},
        },
    )
    _write_json(root / "contracts/dependencies.json", {"type": "dependencies", "version": "dependencies_contract.v0", "enabled": True, "config": {}})
    _write_json(root / "contracts/model.json", {"type": "model", "version": "model_contract.v0", "enabled": True, "config": model_config or {}})
    _write_json(root / "contracts/trace.json", {"type": "trace", "version": "trace_contract.v0", "enabled": True, "config": {"root": str(root / ".agent_runtime" / "trace")}})
    _write_json(
        root / "contracts/session.json",
        {
            "type": "session",
            "version": "session_contract.v0",
            "enabled": True,
            "config": {"session_root": ".agent_runtime/sessions", "checkpointer_backend": "memory", "checkpoint_path": ".agent_runtime/checkpoints/agent.sqlite"},
        },
    )
    if include_tools_contract:
        _write_json(
            root / "contracts/tools.json",
            {
                "type": "tools",
                "version": "tools_contract.v0",
                "enabled": True,
                "config": tools_config or {"package_tools_enabled": False, "instance_extensions_enabled": False},
            },
        )
    _write_json(
        root / "contracts/memory.json",
        {
            "type": "memory",
            "version": "memory_contract.v0",
            "enabled": memory_enabled,
            "config": {"memory_system": _memory_system_config(enabled=memory_enabled)},
        },
    )
    _write_json(
        root / "agent_package.json",
        {
            "version": "agent_package.v0",
            "factory_run_id": "run_1",
            "agent": {"id": "test_agent"},
            "runtime": {"pattern_id": "react_agent"},
            "assembly_spec_path": "assembly_spec.json",
            "render_manifest_path": "render_manifest.json",
            "resources_path": "resources.json",
            "sandbox_contract_path": "sandbox_contract.json",
            "contracts": contracts,
        },
    )
    return root / "agent_package.json"


def _assembly_spec() -> dict:
    return {
        "agent": {"id": "test_agent"},
        "runtime": {"pattern_id": "react_agent"},
        "bindings": {"services": [], "node_bindings": [], "hooks": []},
        "tools": [],
        "metadata": {},
    }


def _render_manifest() -> dict:
    return {
        "version": "render_manifest.v0",
        "graph_id": "test_agent__react_agent",
        "producer_type": "agent",
        "nodes": {},
    }


def _memory_system_config(*, enabled: bool) -> dict:
    return {
        "version": "memory_system.v0",
        "enabled": enabled,
        "write_enabled": False,
        "injection_enabled": enabled,
        "store": {"backend": "memory", "path": ".agent_runtime/memory/agent.sqlite"},
        "ranking": {
            "max_items_total": 8,
            "max_tokens_total": 1200,
            "min_score": 0.55,
            "per_kind_limits": {"constraint": 3, "preference": 3, "decision": 2, "fact": 2, "artifact": 1},
        },
        "semantic_index": {"enabled": False, "fields": ["content"]},
        "background": {
            "journal_root": ".agent_runtime/memory/jobs",
            "max_pending_jobs": 32,
            "concurrency": 1,
            "queue_full_policy": "reject_new_when_full",
            "write_interval_turns": 3,
        },
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
