from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent_factory.factory_graph.schemas import PackageBuildDecision, PackageMaterializationPlan
from agent_factory.factory_graph.stage_subgraphs.package_generation import run_package_generation_subgraph


class PackageGenerationTest(unittest.TestCase):
    def test_generates_complete_package_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decision(_valid_decision())

                self.assertEqual(result["status"], "running")
                self.assertEqual(result["current_stage"], "package_generation")
                package = result["package_generation"]
                self.assertEqual(package["status"], "complete")
                self.assertTrue(Path(package["manifest_path"]).exists())
                self.assertTrue(Path(package["report_path"]).exists())
                self.assertTrue(Path(package["package_root"], "tools", "ledger_lookup", "tool.py").exists())
                self.assertEqual(package["validation_report"]["status"], "valid")

    def test_rejects_path_escape(self) -> None:
        decision = _valid_decision()
        data = decision.model_dump(mode="json")
        data["generated_files"][0]["path"] = "../escape.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decision(PackageBuildDecision.model_validate(data))

                self.assertEqual(result["status"], "failed")
                self.assertIn("path", result["errors"][0]["message"])

    def test_rejects_python_syntax_error(self) -> None:
        decision = _valid_decision()
        data = decision.model_dump(mode="json")
        for item in data["generated_files"]:
            if item["path"] == "tools/ledger_lookup/tool.py":
                item["content"] = "def run(:\n    pass\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decision(PackageBuildDecision.model_validate(data))

                self.assertEqual(result["status"], "failed")
                self.assertIn("Python syntax invalid", result["errors"][0]["message"])

    def test_rejects_extra_undeclared_generated_file(self) -> None:
        data = _valid_decision().model_dump(mode="json")
        data["generated_files"].append(
            _file("tools/ledger_lookup/extra.py", "VALUE = 1\n", "python", "tool", "ledger_lookup")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decision(PackageBuildDecision.model_validate(data))

                self.assertEqual(result["status"], "failed")
                self.assertIn("not declared", result["errors"][0]["message"])

    def test_python_syntax_error_can_be_fixed_by_revision_round(self) -> None:
        invalid = _valid_decision().model_dump(mode="json")
        for item in invalid["generated_files"]:
            if item["path"] == "tools/ledger_lookup/tool.py":
                item["content"] = "def run(:\n    pass\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions(
                    [
                        PackageBuildDecision.model_validate(invalid),
                        _valid_decision(),
                    ]
                )

                self.assertEqual(result["status"], "running")
                self.assertEqual(result["package_generation"]["status"], "complete")
                self.assertEqual(result["package_generation"]["validation_report"]["status"], "valid")


class _FakeModel:
    def bind_tools(self, _tools):
        return self

    def bind(self, **_kwargs):
        return self

    def invoke(self, _prompt_value):
        return AIMessage(content="package draft ready")


def _run_with_decision(decision: PackageBuildDecision):
    return _run_with_decisions([decision, decision, decision])


def _run_with_decisions(decisions: list[PackageBuildDecision]):
    queue = list(decisions)

    def fake_call_structured_model(**_kwargs):
        if not queue:
            raise AssertionError("unexpected package decision call")
        return queue.pop(0)

    with patch("agent_factory.factory_graph.stage_subgraphs.package_generation.get_main_model", return_value=_FakeModel()):
        with patch(
            "agent_factory.factory_graph.stage_subgraphs.package_generation.call_structured_model",
            side_effect=fake_call_structured_model,
        ):
            return run_package_generation_subgraph(_base_state())


def _valid_decision() -> PackageBuildDecision:
    files = [
        _file("tools/ledger_lookup/tool.py", _tool_code(), "python", "tool", "ledger_lookup"),
        _file("tools/ledger_lookup/README.md", "# ledger_lookup\n\nReads ledger data through resources.\n", "markdown", "tool", "ledger_lookup"),
    ]
    return PackageBuildDecision(
        action="package_ready",
        generated_files=files,
        revision_notes=["test package"],
    )


def _file(path: str, content, file_type: str, source_kind: str, source_id: str):
    return {
        "path": path,
        "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2),
        "file_type": file_type,
        "purpose": f"materialize {source_id}",
        "source_kind": source_kind,
        "source_id": source_id,
    }


def _tool_code() -> str:
    return (
        "from __future__ import annotations\n\n"
        "def run(arguments: dict, resources: dict) -> dict:\n"
        "    ledger_file = resources.get('ledger_file')\n"
        "    if not ledger_file:\n"
        "        return {'status': 'error', 'error': 'missing resource: ledger_file'}\n"
        "    return {'status': 'completed', 'ledger_file': ledger_file, 'arguments': arguments}\n"
        "\n\n"
        "def evaluate_risk(arguments: dict, context: dict) -> dict:\n"
        "    return {'risk_level': 'low', 'requires_approval': False, 'reason': 'read-only lookup'}\n"
    )


def _tool_manifest() -> dict:
    return {
        "id": "ledger_lookup",
        "description": "Look up ledger entries.",
        "entrypoint": "tools/ledger_lookup/tool.py:run",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "resources": {"ledger_file": "ledger_file"},
        "risk_level": "low",
        "risk_evaluator": {},
        "concurrent": True,
    }


def _agent_package_manifest() -> dict:
    return {
        "version": "agent_package.v0",
        "factory_run_id": "run_1",
        "agent": {"id": "ledger_agent"},
        "runtime": {"pattern_id": "react_agent"},
        "assembly_spec_path": "assembly_spec.json",
        "resources_path": "resources.json",
        "sandbox_contract_path": "sandbox_contract.json",
        "render_manifest_path": "render_manifest.json",
        "contracts": {
            "context": "contracts/context.json",
            "dependencies": "contracts/dependencies.json",
            "model": "contracts/model.json",
            "memory": "contracts/memory.json",
            "render": "contracts/render.json",
            "resources": "contracts/resources.json",
            "sandbox": "contracts/sandbox.json",
            "scheduler": "contracts/scheduler.json",
            "session": "contracts/session.json",
            "tools": "contracts/tools.json",
        },
        "bindings": {
            "services": "bindings/services.json",
            "node_bindings": "bindings/node_bindings.json",
            "hooks": "bindings/hooks.json",
        },
        "prompts": ["prompts/prompt.ledger.answer.md"],
        "tools": ["tools/ledger_lookup/manifest.json"],
        "policies": ["policies/policy.ledger.precheck.json"],
        "strategies": [],
        "formatters": ["formatters/formatter.ledger.final.json"],
    }


def _base_state() -> dict:
    return {
        "factory_run_id": "run_1",
        "status": "running",
        "assembly_spec": _assembly_spec(),
        "render_manifest": _render_manifest(),
        "package_materialization_plan": _materialization_plan(),
        "tool_capability_plan": {
            "tool_capabilities": [
                {
                    "capability_id": "ledger_lookup",
                    "name": "Ledger lookup",
                    "description": "Look up ledger entries.",
                    "input_contract": {"type": "object"},
                    "output_contract": {"type": "object"},
                    "approval_required": False,
                    "risk_notes": [],
                    "implementation_status": "needs_generation",
                }
            ]
        },
        "node_strategy_plan": {},
        "resource_condition_plan": {
            "status": "complete",
            "resource_file_path": ".agentfactory/resources/run_1/factory_resources.json",
            "sandbox_contract_path": ".agentfactory/resources/run_1/sandbox_contract.json",
            "report_path": ".agentfactory/resources/run_1/resource_preparation_report.json",
            "resources": {"ledger_file": "/tmp/ledger.json"},
            "sandbox_contract": _sandbox_contract(),
        },
        "stage_log": [],
        "errors": [],
    }


def _materialization_plan() -> dict:
    return PackageMaterializationPlan(
        factory_run_id="run_1",
        package_root=".agentfactory/packages/run_1",
        manifest_contract=_agent_package_manifest(),
        files=[
            {"path": "agent_package.json", "file_type": "json", "source_kind": "manifest", "source_id": "agent_package", "generation_mode": "system_generated", "contract_source": "manifest_contract", "required": True},
            {"path": "assembly_spec.json", "file_type": "json", "source_kind": "assembly", "source_id": "assembly_spec", "generation_mode": "system_generated", "contract_source": "assembly_spec", "required": True},
            {"path": "resources.json", "file_type": "json", "source_kind": "manifest", "source_id": "resources", "generation_mode": "system_generated", "contract_source": "resource_condition_plan.resources", "required": True},
            {"path": "sandbox_contract.json", "file_type": "json", "source_kind": "manifest", "source_id": "sandbox_contract", "generation_mode": "system_generated", "contract_source": "resource_condition_plan.sandbox_contract", "required": True},
            {"path": "render_manifest.json", "file_type": "json", "source_kind": "manifest", "source_id": "render_manifest", "generation_mode": "system_generated", "contract_source": "render_manifest", "required": True},
            {"path": "package_report.json", "file_type": "json", "source_kind": "manifest", "source_id": "package_report", "generation_mode": "system_generated", "contract_source": "package_validation_report", "required": True},
            {"path": "bindings/services.json", "file_type": "json", "source_kind": "binding", "source_id": "services", "generation_mode": "system_generated", "contract_source": "assembly_spec.bindings.services", "required": True},
            {"path": "bindings/node_bindings.json", "file_type": "json", "source_kind": "binding", "source_id": "node_bindings", "generation_mode": "system_generated", "contract_source": "assembly_spec.bindings.node_bindings", "required": True},
            {"path": "bindings/hooks.json", "file_type": "json", "source_kind": "binding", "source_id": "hooks", "generation_mode": "system_generated", "contract_source": "assembly_spec.bindings.hooks", "required": True},
            {"path": "contracts/context.json", "file_type": "json", "source_kind": "contract", "source_id": "context", "generation_mode": "system_generated", "contract_source": "runtime_contract:context", "required": True},
            {"path": "contracts/dependencies.json", "file_type": "json", "source_kind": "contract", "source_id": "dependencies", "generation_mode": "system_generated", "contract_source": "runtime_contract:dependencies", "required": True},
            {"path": "contracts/model.json", "file_type": "json", "source_kind": "contract", "source_id": "model", "generation_mode": "system_generated", "contract_source": "runtime_contract:model", "required": True},
            {"path": "contracts/memory.json", "file_type": "json", "source_kind": "contract", "source_id": "memory", "generation_mode": "system_generated", "contract_source": "runtime_contract:memory", "required": True},
            {"path": "contracts/render.json", "file_type": "json", "source_kind": "contract", "source_id": "render", "generation_mode": "system_generated", "contract_source": "runtime_contract:render", "required": True},
            {"path": "contracts/resources.json", "file_type": "json", "source_kind": "contract", "source_id": "resources", "generation_mode": "system_generated", "contract_source": "runtime_contract:resources", "required": True},
            {"path": "contracts/sandbox.json", "file_type": "json", "source_kind": "contract", "source_id": "sandbox", "generation_mode": "system_generated", "contract_source": "runtime_contract:sandbox", "required": True},
            {"path": "contracts/scheduler.json", "file_type": "json", "source_kind": "contract", "source_id": "scheduler", "generation_mode": "system_generated", "contract_source": "runtime_contract:scheduler", "required": True},
            {"path": "contracts/session.json", "file_type": "json", "source_kind": "contract", "source_id": "session", "generation_mode": "system_generated", "contract_source": "runtime_contract:session", "required": True},
            {"path": "contracts/tools.json", "file_type": "json", "source_kind": "contract", "source_id": "tools", "generation_mode": "system_generated", "contract_source": "runtime_contract:tools", "required": True},
            {"path": "prompts/prompt.ledger.answer.md", "file_type": "markdown", "source_kind": "prompt", "source_id": "prompt.ledger.answer", "generation_mode": "system_generated", "contract_source": "binding:answer_prompt", "required": True},
            {"path": "policies/policy.ledger.precheck.json", "file_type": "json", "source_kind": "policy", "source_id": "policy.ledger.precheck", "generation_mode": "system_generated", "contract_source": "binding:precheck_policy", "required": True},
            {"path": "formatters/formatter.ledger.final.json", "file_type": "json", "source_kind": "formatter", "source_id": "formatter.ledger.final", "generation_mode": "system_generated", "contract_source": "binding:final_output", "required": True},
            {"path": "tools/ledger_lookup/manifest.json", "file_type": "json", "source_kind": "tool", "source_id": "ledger_lookup", "generation_mode": "system_generated", "contract_source": "tool_capability:ledger_lookup", "required": True},
            {"path": "tools/ledger_lookup/tool.py", "file_type": "python", "source_kind": "tool", "source_id": "ledger_lookup", "generation_mode": "model_generated", "contract_source": "tool_capability:ledger_lookup+resources", "required": True},
            {"path": "tools/ledger_lookup/README.md", "file_type": "markdown", "source_kind": "tool", "source_id": "ledger_lookup", "generation_mode": "model_generated", "contract_source": "tool_capability:ledger_lookup+resources", "required": True},
        ],
        tools=[
            {
                "tool_id": "ledger_lookup",
                "manifest_path": "tools/ledger_lookup/manifest.json",
                "code_path": "tools/ledger_lookup/tool.py",
                "readme_path": "tools/ledger_lookup/README.md",
                "manifest": _tool_manifest(),
            }
        ],
        contracts=_contracts(),
    ).model_dump(mode="json")


def _assembly_spec() -> dict:
    return {
        "agent": {"id": "ledger_agent", "name": "Ledger Agent", "description": "A ledger assistant."},
        "runtime": {"pattern_id": "react_agent"},
        "bindings": {
            "services": [
                {"service_id": "main_model", "kind": "model_service", "required": True, "config": {}},
                {"service_id": "generated_tool_registry", "kind": "tool_registry", "required": True, "config": {}},
                {"service_id": "memory_store", "kind": "memory_store", "required": True, "config": {}},
                {"service_id": "memory_system", "kind": "memory_system", "required": True, "config": {}},
                {"service_id": "knowledge_engine", "kind": "knowledge_engine", "required": True, "config": {}},
                {"service_id": "context_engine", "kind": "context_engine", "required": True, "config": {}},
                {"service_id": "policy_engine", "kind": "policy_engine", "required": True, "config": {}},
                {"service_id": "observability", "kind": "observability_manager", "required": True, "config": {}},
                {"service_id": "checkpointer", "kind": "checkpointer", "required": True, "config": {}},
            ],
            "node_bindings": [
                {
                    "binding_id": "answer_prompt",
                    "binding_type": "prompt",
                    "target": {"node_id": "answer", "impl": "cognitive.answer"},
                    "payload": {
                        "prompt_id": "prompt.ledger.answer",
                        "template": "Answer using ledger context.",
                        "variables": ["conversation"],
                    },
                },
                {
                    "binding_id": "tool_access",
                    "binding_type": "tool_access",
                    "target": {"node_id": "tool_exec", "impl": "operational.tool_call"},
                    "payload": {"allowed_tool_ids": ["ledger_lookup"], "approval_policy": "standard"},
                },
                {
                    "binding_id": "precheck_policy",
                    "binding_type": "policy_profile",
                    "target": {"node_id": "precheck", "impl": "governance.precheck"},
                    "payload": {"profile_id": "policy.ledger.precheck", "rules": {}},
                },
                {
                    "binding_id": "final_output",
                    "binding_type": "output_formatter",
                    "target": {"node_id": "finalize", "impl": "finalize"},
                    "payload": {"formatter_id": "formatter.ledger.final", "mode": "identity", "config": {}},
                },
            ],
            "hooks": [],
        },
        "tools": [
            {
                "id": "ledger_lookup",
                "description": "Look up ledger entries.",
                "entrypoint": "tools/ledger_lookup/tool.py:run",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "resources": {"ledger_file": "ledger_file"},
                "risk_level": "low",
                "risk_evaluator": {},
                "concurrent": True,
            }
        ],
        "output": {"format": "markdown", "citations_required": False},
        "metadata": {
            "factory_run_id": "run_1",
            "resource_file_path": ".agentfactory/resources/run_1/factory_resources.json",
            "sandbox_contract_path": ".agentfactory/resources/run_1/sandbox_contract.json",
            "resource_preparation_report_path": ".agentfactory/resources/run_1/resource_preparation_report.json",
        },
    }


def _contracts() -> dict:
    return {
        "context": {"type": "context", "version": "context_contract.v0", "enabled": True, "config": {}},
        "dependencies": {"type": "dependencies", "version": "dependencies_contract.v0", "enabled": True, "config": {}},
        "model": {"type": "model", "version": "model_contract.v0", "enabled": True, "config": {}},
        "memory": {
            "type": "memory",
            "version": "memory_contract.v0",
            "enabled": True,
            "config": {"memory_system": _memory_system_config()},
        },
        "render": {"type": "render", "version": "render_contract.v0", "enabled": True, "config": {"manifest_path": "render_manifest.json"}},
        "resources": {"type": "resources", "version": "resources_contract.v0", "enabled": True, "config": {"resources_path": "resources.json"}},
        "sandbox": {"type": "sandbox", "version": "sandbox_contract.v0", "enabled": True, "config": {"sandbox_contract_path": "sandbox_contract.json"}},
        "scheduler": {"type": "scheduler", "version": "scheduler_contract.v0", "enabled": True, "config": {"store_path": ".agent_runtime/scheduler/agent.sqlite"}},
        "session": {
            "type": "session",
            "version": "session_contract.v0",
            "enabled": True,
            "config": {
                "session_root": ".agent_runtime/sessions",
                "checkpointer_backend": "sqlite",
                "checkpoint_path": ".agent_runtime/checkpoints/agent.sqlite",
            },
        },
        "tools": {"type": "tools", "version": "tools_contract.v0", "enabled": True, "config": {}},
    }


def _memory_system_config() -> dict:
    return {
        "version": "memory_system.v0",
        "enabled": True,
        "write_enabled": True,
        "injection_enabled": True,
        "store": {"backend": "sqlite", "path": ".agent_runtime/memory/agent.sqlite"},
        "ranking": {
            "max_items_total": 8,
            "max_tokens_total": 1200,
            "min_score": 0.55,
            "per_kind_limits": {
                "constraint": 3,
                "preference": 3,
                "decision": 2,
                "fact": 2,
                "artifact": 1,
            },
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


def _sandbox_contract() -> dict:
    return {
        "version": "sandbox_contract.v0",
        "backend": "docker",
        "image": "python:3.12-slim",
        "workdir": "/workdir",
        "network_policy": {"mode": "default_allow"},
        "mounts": [],
        "services": [],
        "secrets": [],
        "env": {},
        "volumes": [],
    }


def _render_manifest() -> dict:
    return {
        "version": "render_manifest.v0",
        "graph_id": "ledger_agent__react_agent",
        "producer_type": "agent",
        "nodes": {
            "answer": {
                "node_id": "answer",
                "label": "Answer",
                "kind": "cognitive",
                "purpose": "Answer ledger questions.",
                "doing": "Preparing an answer.",
                "expected_output": "Final answer state.",
                "visible_to_user": True,
            }
        },
    }


class _chdir:
    def __init__(self, path: str) -> None:
        self.path = path
        self.previous = os.getcwd()

    def __enter__(self):
        os.chdir(self.path)

    def __exit__(self, exc_type, exc, tb):
        os.chdir(self.previous)
