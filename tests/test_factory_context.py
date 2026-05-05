from __future__ import annotations

import unittest

from agent_factory.factory_context import (
    DecisionLedger,
    EvidenceStore,
    NodeContextCompiler,
    RequirementUnderstanding,
    apply_context_envelope,
)
from agent_factory.factory_runtime.production.state import FactoryProductionState
from agent_factory.model import MessageBuilder


class FactoryContextProtocolTests(unittest.TestCase):
    def test_compiler_exposes_only_context_contract_not_raw_state(self) -> None:
        state = FactoryProductionState(
            run_id="run-1",
            requirement="创建一个和风天气助手。QWEATHER_JWT=secret-value",
            requirement_understanding=RequirementUnderstanding(
                agent_name="和风天气助手",
                agent_type="weather",
                goal="按城市查询未来三天天气",
                explicit_requirements=["创建一个和风天气助手"],
            ),
        )
        ledger = DecisionLedger()
        ledger.append(
            stage="analyze_requirement",
            title="Requirement understanding",
            summary="按城市查询未来三天天气",
            artifact_type="RequirementUnderstanding",
            payload={"api_key": "secret-value", "safe": "ok"},
        )
        evidence = EvidenceStore()
        evidence.append(
            stage="factory_web_research",
            source="raw_webpage",
            summary="Raw fetched HTML",
            payload={"raw_webpage": "<html>noise</html>"},
            safe_for_prompt=False,
        )

        envelope = NodeContextCompiler().compile(
            stage="generate_tool_scripts",
            state=state,
            decision_ledger=ledger,
            evidence_store=evidence,
        )
        payload = envelope.safe_prompt_context()

        self.assertEqual(envelope.stage, "generate_tool_scripts")
        self.assertIn("ResourceContractSet", envelope.allowed_inputs)
        self.assertIn("raw_webpage", envelope.forbidden_inputs)
        self.assertNotIn("secret-value", str(payload))
        self.assertNotIn("raw_webpage", str(payload["evidence_refs"]))
        self.assertTrue(any(ref["artifact_type"] == "RequirementUnderstanding" for ref in payload["decision_refs"]))

    def test_stage_tool_policy_is_isolated(self) -> None:
        envelope = NodeContextCompiler().compile(
            stage="probe_environment",
            state=FactoryProductionState(run_id="run-2", requirement="检查本地 DB"),
            decision_ledger=DecisionLedger(),
            evidence_store=EvidenceStore(),
        )

        self.assertIn("file.stat", envelope.available_tools)
        self.assertIn("sqlite.schema.readonly", envelope.available_tools)
        self.assertNotIn("file.write", envelope.available_tools)
        self.assertNotIn("shell.unrestricted", envelope.available_tools)

    def test_llm_request_adapter_injects_envelope_contract(self) -> None:
        envelope = NodeContextCompiler().compile(
            stage="plan_primitives",
            state=FactoryProductionState(run_id="run-3", requirement="创建天气助手"),
            decision_ledger=DecisionLedger(),
            evidence_store=EvidenceStore(),
        )
        request = MessageBuilder.start().system("base").user("task").request(
            metadata={"operation": "create_agent_primitives"}
        )

        wrapped = apply_context_envelope(request, envelope)

        self.assertEqual(
            wrapped.metadata["factory_context_envelope"]["stage"],
            "plan_primitives",
        )
        self.assertIn("Factory Context Envelope", wrapped.messages[0].content)
        self.assertIn("forbidden_inputs", wrapped.messages[0].content)
        self.assertEqual(wrapped.messages[1].content, "base")


if __name__ == "__main__":
    unittest.main()
