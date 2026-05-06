from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from agent_factory.runtime_kernel import BindingSet, RuntimeKernelFacade, RuntimeServices, RuntimeState
from agent_factory.runtime_kernel.adapters import InMemoryToolRegistry, ScriptedModelService
from agent_factory.runtime_kernel.bindings.schema import (
    NodeBinding,
    NodeBindingTarget,
    PolicyProfileBindingPayload,
    PromptBindingPayload,
    ToolAccessBindingPayload,
)
from agent_factory.runtime_kernel.checkpoint import FilesystemCheckpointManager
from agent_factory.runtime_kernel.context import ContextEngine
from agent_factory.runtime_kernel.harness import FixtureBundle, HarnessBridge, HarnessScenario
from agent_factory.runtime_kernel.knowledge import KnowledgeEngine
from agent_factory.runtime_kernel.memory import InMemoryMemoryEngine
from agent_factory.runtime_kernel.patterns import PatternRegistry, PatternValidator
from agent_factory.runtime_kernel.patterns.loader import PatternLoader
from agent_factory.runtime_kernel.policy import PolicyEngine
from agent_factory.runtime_kernel.state import dump_messages, load_messages
from agent_factory.runtime_kernel.types import ModelInvocationResult, PolicyDecision, ToolExecutionResult


class SequencedPolicyEngine:
    def __init__(self, decisions: list[PolicyDecision]) -> None:
        self.decisions = list(decisions)

    def evaluate_precheck(self, *, state, binding=None):
        if self.decisions:
            return self.decisions.pop(0)
        return PolicyDecision(status="allowed")

    def evaluate_postcheck(self, *, state, binding=None):
        if self.decisions:
            return self.decisions.pop(0)
        return PolicyDecision(status="allowed")


class RuntimeKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="runtime-kernel-tests-"))
        self.facade = RuntimeKernelFacade()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_message_roundtrip(self) -> None:
        messages = [
            HumanMessage(content="hello"),
            AIMessage(content="world", tool_calls=[{"id": "t1", "name": "lookup", "args": {"q": "x"}, "type": "tool_call"}]),
        ]
        records = dump_messages(messages)
        loaded = load_messages(records)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].content, "hello")
        self.assertEqual(loaded[1].content, "world")

    def test_runtime_state_json_roundtrip(self) -> None:
        state = RuntimeState()
        data = state.model_dump(mode="json")
        restored = RuntimeState.model_validate(data)
        self.assertEqual(restored.schema_version, state.schema_version)
        self.assertEqual(restored.run.run_id, state.run.run_id)

    def test_runtime_state_checkpoint_roundtrip(self) -> None:
        state = RuntimeState()
        state.conversation.current_user_input = "hello"
        serializer = self.facade.instance.controller.checkpoint_serializer
        record = serializer.to_record(state=state, reason="test")
        restored = serializer.from_record(record)
        self.assertEqual(restored.conversation.current_user_input, "hello")

    def test_pattern_registry_loads_builtins(self) -> None:
        builtins_dir = Path("agent_factory/runtime_kernel/patterns/builtins")
        registry = PatternRegistry(builtins_dir=builtins_dir)
        self.assertEqual(
            registry.list_pattern_ids(),
            ["clarification_loop_v1", "clarify_then_act", "react_agent"],
        )

    def test_pattern_validator_rejects_invalid_subgraph(self) -> None:
        loader = PatternLoader()
        spec = loader.load_path("agent_factory/runtime_kernel/patterns/builtins/react_agent.yaml")
        spec.nodes[1].type = "sub_graph"
        validator = PatternValidator()
        with self.assertRaises(Exception):
            validator.validate(spec, known_patterns={"react_agent"})

    def test_pattern_validator_rejects_invalid_required_capability(self) -> None:
        loader = PatternLoader()
        spec = loader.load_path("agent_factory/runtime_kernel/patterns/builtins/react_agent.yaml")
        spec.constraints.required_capabilities = ["unknown_capability"]
        validator = PatternValidator()
        with self.assertRaises(Exception):
            validator.validate(spec, known_patterns={"react_agent", "clarification_loop_v1", "clarify_then_act"})

    def test_pattern_validator_rejects_invalid_interrupt_point(self) -> None:
        loader = PatternLoader()
        spec = loader.load_path("agent_factory/runtime_kernel/patterns/builtins/react_agent.yaml")
        spec.interrupt_points = ["answer"]
        validator = PatternValidator()
        with self.assertRaises(Exception):
            validator.validate(spec, known_patterns={"react_agent", "clarification_loop_v1", "clarify_then_act"})

    def test_compile_react_agent(self) -> None:
        compiled = self.facade.compile(pattern_id="react_agent")
        self.assertEqual(compiled.pattern_spec.pattern_id, "react_agent")
        self.assertIn("answer", compiled.node_runners)

    def test_compile_subgraph_parent_pattern(self) -> None:
        compiled = self.facade.compile(pattern_id="clarify_then_act")
        self.assertEqual(compiled.pattern_spec.pattern_id, "clarify_then_act")
        self.assertIn("clarify_loop", compiled.node_runners)

    def test_direct_answer_path(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[ModelInvocationResult(assistant_draft="draft", final_answer="final", requests_tool=False)]
            ),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine([PolicyDecision(status="allowed")]),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        bindings = BindingSet(
            node_bindings=[
                NodeBinding(
                    binding_id="prompt-answer",
                    binding_type="prompt",
                    target=NodeBindingTarget(node_id="answer", impl="cognitive.answer"),
                    payload=PromptBindingPayload(
                        prompt_id="prompt.answer.default",
                        template="Answer the user.",
                        variables=["conversation"],
                    ).model_dump(mode="json"),
                ),
                NodeBinding(
                    binding_id="policy-precheck",
                    binding_type="policy_profile",
                    target=NodeBindingTarget(node_id="precheck", impl="governance.precheck"),
                    payload=PolicyProfileBindingPayload(profile_id="default").model_dump(mode="json"),
                ),
            ]
        )
        compiled = self.facade.compile(pattern_id="react_agent", bindings=bindings, services=services)
        result = self.facade.run(compiled, user_input="hello")
        self.assertEqual(result.execution.finish_status, "completed")
        self.assertEqual(result.conversation.final_answer, "final")
        self.assertTrue(result.memory.write_applied)
        event_types = [item["event_type"] for item in result.observability.events]
        self.assertIn("route_selected", event_types)
        self.assertTrue(result.context.assembly_log)
        summary = services.observability_manager.summary_for(result.run.run_id)
        self.assertIsNotNone(summary)
        self.assertGreaterEqual(summary.node_count, 1)

    def test_tool_path(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[
                    ModelInvocationResult(
                        assistant_draft="need tool",
                        requests_tool=True,
                        tool_name="lookup",
                        tool_arguments={"id": "A-1"},
                    ),
                    ModelInvocationResult(assistant_draft="done", final_answer="order found", requests_tool=False),
                ]
            ),
            tool_registry=InMemoryToolRegistry(
                tools={
                    "lookup": lambda arguments, state: ToolExecutionResult(
                        status="completed",
                        output={"tool_id": "lookup", "id": arguments["id"]},
                    )
                }
            ),
            policy_engine=SequencedPolicyEngine([PolicyDecision(status="allowed")]),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        bindings = BindingSet(
            node_bindings=[
                NodeBinding(
                    binding_id="tool-access",
                    binding_type="tool_access",
                    target=NodeBindingTarget(node_id="tool_exec", impl="operational.tool_call"),
                    payload=ToolAccessBindingPayload(allowed_tool_ids=["lookup"]).model_dump(mode="json"),
                )
            ]
        )
        compiled = self.facade.compile(pattern_id="react_agent", bindings=bindings, services=services)
        result = self.facade.run(compiled, user_input="find order")
        self.assertEqual(result.execution.finish_status, "completed")
        self.assertEqual(result.conversation.final_answer, "order found")
        self.assertEqual(result.tools.last_tool_result["output"]["tool_id"], "lookup")
        event_types = [item["event_type"] for item in result.observability.events]
        self.assertIn("tool_started", event_types)
        self.assertIn("tool_completed", event_types)
        self.assertTrue(result.memory.write_applied)

    def test_interrupt_and_resume(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[ModelInvocationResult(assistant_draft="after resume", final_answer="approved", requests_tool=False)]
            ),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine(
                [
                    PolicyDecision(
                        status="interrupted",
                        reason="approval required",
                        approval_required=True,
                        interrupt_required=True,
                        interrupt_type="approval_required",
                    ),
                    PolicyDecision(status="allowed"),
                ]
            ),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        compiled = self.facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
        interrupted = self.facade.run(compiled, user_input="sensitive action")
        self.assertEqual(interrupted.execution.finish_status, "interrupted")
        debug_refs = interrupted.observability.debug_refs
        self.assertTrue(debug_refs)
        checkpoint_id = debug_refs[-1]["checkpoint_id"]
        resumed = self.facade.resume(compiled, checkpoint_id=checkpoint_id)
        self.assertEqual(resumed.execution.finish_status, "completed")
        self.assertEqual(resumed.conversation.final_answer, "approved")
        event_types = [item["event_type"] for item in resumed.observability.events]
        self.assertIn("resume_completed", event_types)
        self.assertIn("checkpoint_operation", event_types)

    def test_clarify_then_act_need_more_input_path(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=PolicyEngine(),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        bindings = BindingSet()
        compiled = self.facade.compile(pattern_id="clarify_then_act", bindings=bindings, services=services)
        result = self.facade.run(compiled, user_input="短问题")
        self.assertEqual(result.execution.finish_status, "completed")
        self.assertTrue(result.conversation.clarification_question or result.conversation.final_answer)
        event_types = [item["event_type"] for item in result.observability.events]
        self.assertIn("subgraph_entered", event_types)
        self.assertIn("subgraph_exited", event_types)
        self.assertIn("route_selected", event_types)

    def test_harness_bridge_supports_path_context_and_checkpoint_assertions(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[ModelInvocationResult(assistant_draft="draft", final_answer="final", requests_tool=False)]
            ),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine([PolicyDecision(status="allowed")]),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        bridge = HarnessBridge(facade=self.facade)
        scenario = HarnessScenario(
            scenario_id="basic",
            input_text="hello",
            assertions=[
                {"type": "path_contains", "expected_node_ids": ["ingress", "precheck", "answer", "finalize"]},
                {"type": "context_built", "context_key": "current_user_input"},
                {"type": "final_answer", "expected": "final"},
            ],
        )
        result = bridge.run_scenario(
            pattern_id="react_agent",
            bindings=BindingSet(),
            services=services,
            fixture=FixtureBundle(),
            scenario=scenario,
        )
        self.assertEqual(result.status, "passed")
        self.assertIsNotNone(result.trace_summary)

    def test_harness_bridge_supports_policy_and_checkpoint_assertions(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[ModelInvocationResult(assistant_draft="draft", final_answer="approved", requests_tool=False)]
            ),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine(
                [
                    PolicyDecision(
                        status="interrupted",
                        reason="approval required",
                        approval_required=True,
                        interrupt_required=True,
                        interrupt_type="approval_required",
                    ),
                    PolicyDecision(status="allowed"),
                ]
            ),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        bridge = HarnessBridge(facade=self.facade)
        scenario = HarnessScenario(
            scenario_id="resume-check",
            input_text="approval text",
            resume_after_interrupt=True,
            assertions=[
                {"type": "checkpoint_created"},
                {"type": "resume_event"},
            ],
        )
        result = bridge.run_scenario(
            pattern_id="react_agent",
            bindings=BindingSet(),
            services=services,
            fixture=FixtureBundle(
                model_service=services.model_service,
                tool_registry=services.tool_registry,
                policy_engine=services.policy_engine,
                memory_engine=services.memory_engine,
                knowledge_engine=services.knowledge_engine,
            ),
            scenario=scenario,
        )
        self.assertEqual(result.status, "passed")
        self.assertTrue(any(item["type"] == "checkpoint_created" for item in result.assertion_results))


if __name__ == "__main__":
    unittest.main()
