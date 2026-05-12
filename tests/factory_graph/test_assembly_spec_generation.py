from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
                self.assertTrue(Path(result["assembly_spec_draft_path"]).exists())
                self.assertTrue(Path(result["assembly_validation_report_path"]).exists())

    def test_validation_observation_drives_revision(self) -> None:
        first = _valid_draft()
        first["tools"] = [{"id": "unknown_tool"}]
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
        "tools": [
            {
                "id": "ledger_lookup",
                "name": "Ledger lookup",
                "description": "Look up ledger entries.",
            }
        ],
        "output": {"format": "markdown", "citations_required": False},
        "metadata": {
            "factory_run_id": "run_1",
            "resource_file_path": ".agentfactory/resources/run_1/factory_resources.json",
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
        "graph_behavior_plan": {"nodes": [{"node_id": "answer"}]},
        "node_strategy_plan": {},
        "tool_capability_plan": {
            "tool_capabilities": [
                {
                    "capability_id": "ledger_lookup",
                    "name": "Ledger lookup",
                    "description": "Look up ledger entries.",
                    "required_by_node_ids": ["answer"],
                    "visible_to_node_ids": ["answer"],
                    "implementation_status": "needs_generation",
                }
            ]
        },
        "resource_condition_plan": {
            "status": "complete",
            "resource_file_path": ".agentfactory/resources/run_1/factory_resources.json",
            "resources": {},
        },
        "stage_log": [],
        "errors": [],
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
