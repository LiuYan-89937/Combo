from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from agent_factory.factory_graph.schemas import AssemblyReactDecision
from agent_factory.factory_graph.stage_subgraphs.assembly_spec_generation import (
    run_assembly_spec_generation_subgraph,
)


class AssemblySpecGenerationTest(unittest.TestCase):
    def test_generates_validated_assembly_spec_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([_decision(_valid_draft())])

                self.assertEqual(result["status"], "running")
                self.assertEqual(result["current_stage"], "assembly_spec_generation")
                self.assertEqual(result["assembly_spec"]["runtime"]["pattern_id"], "react_agent")
                self.assertEqual(result["assembly_validation_report"]["status"], "valid")
                self.assertEqual(result["assembly_validation_report"]["attempts"][0]["status"], "valid")
                self.assertEqual(result["assembly_spec"]["harness"], [])
                self.assertGreater(len(result["assembly_spec"]["bindings"]["node_bindings"]), 0)
                self.assertIn(
                    "prompt",
                    {item["binding_type"] for item in result["assembly_spec"]["bindings"]["node_bindings"]},
                )
                self.assertTrue(Path(result["assembly_spec_draft_path"]).exists())
                self.assertTrue(Path(result["package_materialization_plan_path"]).exists())
                self.assertTrue(Path(result["assembly_validation_report_path"]).exists())
                plan = result["package_materialization_plan"]
                plan_paths = {item["path"] for item in plan["files"]}
                self.assertIn("bindings/services.json", plan_paths)
                self.assertIn("bindings/node_bindings.json", plan_paths)
                self.assertIn("bindings/hooks.json", plan_paths)
                self.assertIn("sandbox_contract.json", plan_paths)
                self.assertIn("session.json", plan_paths)
                self.assertIn("memory/store.json", plan_paths)
                self.assertEqual(plan["tools"][0]["manifest"]["input_schema"], {"type": "object"})

    def test_validation_observation_drives_revision(self) -> None:
        first = _valid_draft()
        first["tools"] = [
            {
                "id": "unknown_tool",
                "description": "Unknown tool.",
                "entrypoint": "tools/unknown_tool/tool.py:run",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "resources": {},
                "risk_level": "low",
                "risk_evaluator": {},
                "concurrent": True,
            }
        ]
        second = _valid_draft()
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([_decision(first), _decision(second)])

                attempts = result["assembly_validation_report"]["attempts"]
                self.assertEqual(result["status"], "running")
                self.assertEqual(len(attempts), 2)
                self.assertEqual(attempts[0]["status"], "invalid")
                self.assertIn("tools[].id must come from tool_capability_plan", attempts[0]["errors"][0])
                self.assertEqual(attempts[1]["status"], "valid")

    def test_fails_after_max_revision_rounds(self) -> None:
        invalid = _valid_draft()
        invalid["runtime"]["pattern_id"] = "wrong_pattern"
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([_decision(invalid), _decision(invalid), _decision(invalid)])

                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["graph_control"]["action"], "end")
                self.assertEqual(result["assembly_validation_report"]["status"], "failed")
                self.assertEqual(len(result["assembly_validation_report"]["attempts"]), 3)
                self.assertTrue(Path(result["assembly_validation_report_path"]).exists())
                self.assertNotIn("assembly_spec", result)

    def test_rejects_missing_industrial_bindings(self) -> None:
        invalid = _valid_draft()
        invalid["bindings"]["node_bindings"] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([_decision(invalid), _decision(invalid), _decision(invalid)])

                self.assertEqual(result["status"], "failed")
                self.assertIn("bindings.node_bindings", result["assembly_validation_report"]["final_error"])

    def test_standard_binding_payload_rejects_extra_fields_at_schema_boundary(self) -> None:
        invalid = _valid_draft()
        invalid["bindings"]["node_bindings"][0]["payload"]["unexpected"] = "not allowed"

        with self.assertRaises(ValidationError) as context:
            AssemblyReactDecision(action="draft_ready", draft=invalid, revision_notes=["invalid"])

        self.assertIn("unexpected", str(context.exception))
        self.assertIn("Extra inputs are not permitted", str(context.exception))

    def test_custom_binding_payload_keeps_explicit_extension_config(self) -> None:
        draft = _valid_draft()
        draft["bindings"]["node_bindings"].append(
            {
                "binding_id": "answer_vendor_extension",
                "binding_type": "custom",
                "target": {"node_id": "answer", "impl": "cognitive.answer"},
                "payload": {
                    "extension_id": "vendor.answer.trace_hint",
                    "schema_version": "v0",
                    "purpose": "Attach vendor-specific tracing hints without changing standard prompt semantics.",
                    "config": {"trace_level": "summary"},
                },
            }
        )

        decision = AssemblyReactDecision(action="draft_ready", draft=draft, revision_notes=["valid custom"])

        payload = decision.draft.bindings.node_bindings[-1].payload.model_dump(mode="json")
        self.assertEqual(payload["extension_id"], "vendor.answer.trace_hint")
        self.assertEqual(payload["config"]["trace_level"], "summary")


def _run_with_decisions(decisions: list[AssemblyReactDecision]):
    queue = list(decisions)

    def fake_call_structured_model(**kwargs):
        if not queue:
            raise AssertionError("unexpected model call")
        return queue.pop(0)

    with patch(
        "agent_factory.factory_graph.stage_subgraphs.assembly_spec_generation.call_structured_model",
        side_effect=fake_call_structured_model,
    ):
        return run_assembly_spec_generation_subgraph(_base_state())


def _decision(draft: dict) -> AssemblyReactDecision:
    return AssemblyReactDecision(action="draft_ready", draft=draft, revision_notes=["test decision"])


def _valid_draft() -> dict:
    return {
        "agent": {
            "id": "ledger_agent",
            "name": "Ledger Agent",
            "description": "A CLI-first ledger assistant.",
        },
        "runtime": {"pattern_id": "react_agent"},
        "graph_overrides": {
            "node_wrappers": [
                {
                    "node_id": "answer",
                    "wrappers": [
                        {
                            "id": "context.prepare_model_context",
                            "phase": "before",
                            "config": {},
                        }
                    ],
                }
            ]
        },
        "bindings": _valid_bindings(),
        "tools": [
            {
                "id": "ledger_lookup",
                "description": "Look up ledger entries.",
                "entrypoint": "tools/ledger_lookup/tool.py:run",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "resources": {},
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
            "source_stage_ids": [
                "requirement_capture",
                "runtime_pattern_selection",
                "graph_behavior_planning",
                "node_strategy_planning",
                "tool_capability_planning",
                "resource_and_condition_planning",
            ],
            "tool_capability_ids": ["ledger_lookup"],
        },
    }


def _base_state() -> dict:
    return {
        "factory_run_id": "run_1",
        "status": "running",
        "requirement_brief": {"summary": "ledger assistant"},
        "refined_plan_text": "Build a ledger assistant.",
        "runtime_pattern_selection": {"selected_pattern_id": "react_agent"},
        "pattern_structure_summary": {"pattern_id": "react_agent"},
        "graph_behavior_plan": {
            "nodes": [
                {"node_id": "ingress", "node_type": "reserved", "impl": "ingress"},
                {"node_id": "knowledge_retrieve", "node_type": "operational", "impl": "operational.knowledge_retrieve"},
                {"node_id": "precheck", "node_type": "governance", "impl": "governance.precheck"},
                {"node_id": "approval_gate", "node_type": "governance", "impl": "governance.approval_gate"},
                {"node_id": "answer", "node_type": "cognitive", "impl": "cognitive.answer"},
                {"node_id": "tool_exec", "node_type": "operational", "impl": "operational.tool_call"},
                {"node_id": "postcheck", "node_type": "governance", "impl": "governance.postcheck"},
                {"node_id": "commit", "node_type": "terminal", "impl": "terminal.commit"},
                {"node_id": "finalize", "node_type": "reserved", "impl": "finalize"},
            ]
        },
        "node_strategy_plan": {},
        "tool_capability_plan": {
            "tool_capabilities": [
                {
                    "capability_id": "ledger_lookup",
                    "name": "Ledger lookup",
                    "description": "Look up ledger entries.",
                    "required_by_node_ids": ["answer"],
                    "visible_to_node_ids": ["answer"],
                    "input_contract": {"type": "object"},
                    "output_contract": {"type": "object"},
                    "implementation_status": "needs_generation",
                }
            ]
        },
        "resource_condition_plan": {
            "status": "complete",
            "resource_file_path": ".agentfactory/resources/run_1/factory_resources.json",
            "sandbox_contract_path": ".agentfactory/resources/run_1/sandbox_contract.json",
            "report_path": ".agentfactory/resources/run_1/resource_preparation_report.json",
            "resources": {},
            "sandbox_contract": {
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
            },
        },
        "stage_log": [],
        "errors": [],
    }


def _valid_bindings() -> dict:
    return {
        "services": [
            {"service_id": "main_model", "kind": "model_service", "required": True, "config": {}},
            {"service_id": "generated_tool_registry", "kind": "tool_registry", "required": True, "config": {}},
            {"service_id": "memory_store", "kind": "memory_store", "required": True, "config": {}},
            {"service_id": "knowledge_engine", "kind": "knowledge_engine", "required": True, "config": {}},
            {"service_id": "context_engine", "kind": "context_engine", "required": True, "config": {}},
            {"service_id": "policy_engine", "kind": "policy_engine", "required": True, "config": {}},
            {"service_id": "observability", "kind": "observability_manager", "required": True, "config": {}},
            {"service_id": "checkpointer", "kind": "checkpointer", "required": True, "config": {}},
        ],
        "node_bindings": [
            {
                "binding_id": "precheck_policy",
                "binding_type": "policy_profile",
                "target": {"node_id": "precheck", "impl": "governance.precheck"},
                "payload": {"profile_id": "policy.ledger.precheck", "rules": {"risk": "standard"}},
            },
            {
                "binding_id": "approval_gate_policy",
                "binding_type": "policy_profile",
                "target": {"node_id": "approval_gate", "impl": "governance.approval_gate"},
                "payload": {"profile_id": "policy.ledger.approval", "rules": {"approval_required": True}},
            },
            {
                "binding_id": "answer_prompt",
                "binding_type": "prompt",
                "target": {"node_id": "answer", "impl": "cognitive.answer"},
                "payload": {
                    "prompt_id": "prompt.ledger.answer",
                    "template": "You are a CLI-first ledger assistant. Use available context, tools, and policy constraints before answering.",
                    "variables": ["conversation", "model_context", "tool_context", "resource_contract"],
                },
            },
            {
                "binding_id": "tool_exec_access",
                "binding_type": "tool_access",
                "target": {"node_id": "tool_exec", "impl": "operational.tool_call"},
                "payload": {"allowed_tool_ids": ["ledger_lookup"], "approval_policy": "standard"},
            },
            {
                "binding_id": "postcheck_policy",
                "binding_type": "policy_profile",
                "target": {"node_id": "postcheck", "impl": "governance.postcheck"},
                "payload": {"profile_id": "policy.ledger.postcheck", "rules": {"validate_output": True}},
            },
            {
                "binding_id": "commit_output",
                "binding_type": "output_formatter",
                "target": {"node_id": "commit", "impl": "terminal.commit"},
                "payload": {"formatter_id": "formatter.ledger.markdown", "mode": "identity", "config": {"format": "markdown"}},
            },
            {
                "binding_id": "finalize_output",
                "binding_type": "output_formatter",
                "target": {"node_id": "finalize", "impl": "finalize"},
                "payload": {"formatter_id": "formatter.ledger.final", "mode": "identity", "config": {"format": "markdown"}},
            },
        ],
        "hooks": [],
    }


class _chdir:
    def __init__(self, path: str) -> None:
        self.path = path
        self.previous = os.getcwd()

    def __enter__(self):
        os.chdir(self.path)

    def __exit__(self, exc_type, exc, traceback):
        os.chdir(self.previous)


if __name__ == "__main__":
    unittest.main()
