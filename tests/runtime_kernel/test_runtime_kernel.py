from __future__ import annotations

from datetime import datetime, timedelta, timezone
import shutil
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from agent_factory.assembly import AgentAssemblyCompiler, AgentAssemblyLoader, AgentAssemblyRunner, AgentAssemblySpec
from agent_factory.runtime_kernel import (
    BindingSet,
    NodeWrapper,
    RuntimeKernelFacade,
    RuntimeServices,
    RuntimeState,
    StrategySpec,
    wrap_node,
)
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
from agent_factory.runtime_render import default_node_render_spec


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


class RaisingModelService:
    def generate(self, *, state, prompt_binding=None):
        raise RuntimeError("model exploded")


@wrap_node("test.user_config_before", phases={"before"}, reads={"runtime_config"}, writes={"context"})
class UserConfigBeforeWrapper(NodeWrapper):
    def before(self, *, state, context, config):
        return {
            "context": {
                "model_context": {
                    **state.context.model_context,
                    "tone": state.runtime_config.user_config.get("tone"),
                    "wrapper_config": dict(config),
                },
                "assembly_log": [*state.context.assembly_log, f"test.user_config_before:{context.node_id}"],
            }
        }


@wrap_node("test.fail_before", phases={"before"}, reads={"runtime_config"}, writes={"execution"})
class FailBeforeWrapper(NodeWrapper):
    def before(self, *, state, context, config):
        raise RuntimeError("wrapper exploded")


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

    def test_memory_engine_uses_strategy_specs(self) -> None:
        engine = InMemoryMemoryEngine(
            strategies=[
                StrategySpec(
                    strategy_id="recall-one",
                    kind="memory.recall",
                    impl="memory.recall.latest",
                    config={"limit": 1},
                )
            ]
        )
        first = RuntimeState()
        first.run.session_id = "strategy-session"
        first.conversation.current_user_input = "first"
        first.conversation.final_answer = "one"
        engine.write(state=first)
        second = RuntimeState()
        second.run.session_id = "strategy-session"
        second.conversation.current_user_input = "second"
        second.conversation.final_answer = "two"
        engine.write(state=second)

        recalled = engine.recall(state=second, binding={"recall_strategy_id": "recall-one"})

        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0]["answer"], "two")
        self.assertEqual(second.memory.short_term_snapshot["strategy_id"], "recall-one")

    def test_memory_engine_rejects_unknown_strategy_id(self) -> None:
        engine = InMemoryMemoryEngine()
        with self.assertRaises(Exception):
            engine.recall(state=RuntimeState(), binding={"recall_strategy_id": "missing"})

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

    def test_graph_app_is_authoritative_execution_path(self) -> None:
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
        compiled = self.facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
        compiled.node_runners = {}
        result = self.facade.run(compiled, user_input="hello")
        self.assertEqual(result.execution.finish_status, "completed")
        self.assertEqual(result.conversation.final_answer, "final")

    def test_invalid_route_decision_fails_without_leaving_dsl_edges(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[
                    ModelInvocationResult(
                        assistant_draft="bad route",
                        final_answer="bad route",
                        route_decision="not.allowed",
                    )
                ]
            ),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine([PolicyDecision(status="allowed")]),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        compiled = self.facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
        result = self.facade.run(compiled, user_input="hello")
        self.assertEqual(result.execution.finish_status, "failed")
        self.assertIn("No next node resolved", result.execution.last_error or "")

    def test_tool_failed_route_returns_to_answer(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[
                    ModelInvocationResult(
                        assistant_draft="need tool",
                        requests_tool=True,
                        tool_name="lookup",
                        tool_arguments={"id": "A-1"},
                    ),
                    ModelInvocationResult(assistant_draft="done", final_answer="recovered", requests_tool=False),
                ]
            ),
            tool_registry=InMemoryToolRegistry(
                tools={
                    "lookup": lambda arguments, state: ToolExecutionResult(
                        status="failed",
                        error="temporary failure",
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
        self.assertEqual(result.conversation.final_answer, "recovered")
        event_types = [item["event_type"] for item in result.observability.events]
        self.assertIn("tool_proposed", event_types)
        self.assertIn("tool_failed", event_types)

    def test_tool_not_allowed_blocks_run(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[
                    ModelInvocationResult(
                        assistant_draft="need forbidden",
                        requests_tool=True,
                        tool_name="delete_all",
                        tool_arguments={"id": "A-1"},
                    )
                ]
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
                    binding_id="tool-access",
                    binding_type="tool_access",
                    target=NodeBindingTarget(node_id="tool_exec", impl="operational.tool_call"),
                    payload=ToolAccessBindingPayload(allowed_tool_ids=["lookup"]).model_dump(mode="json"),
                )
            ]
        )
        compiled = self.facade.compile(pattern_id="react_agent", bindings=bindings, services=services)
        result = self.facade.run(compiled, user_input="danger")
        self.assertEqual(result.execution.finish_status, "blocked")
        self.assertTrue(result.policy.blocked)

    def test_tool_interrupt_resume_continues_from_tool_node(self) -> None:
        calls = {"count": 0}

        def gated_tool(arguments, state):
            calls["count"] += 1
            if calls["count"] == 1:
                return ToolExecutionResult(status="interrupted", interrupt_type="approval_required")
            return ToolExecutionResult(status="completed", output={"tool_id": "lookup", "ok": True})

        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[
                    ModelInvocationResult(
                        assistant_draft="need tool",
                        requests_tool=True,
                        tool_name="lookup",
                        tool_arguments={"api_key": "secret-value"},
                    ),
                    ModelInvocationResult(assistant_draft="done", final_answer="approved tool", requests_tool=False),
                ]
            ),
            tool_registry=InMemoryToolRegistry(tools={"lookup": gated_tool}),
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
        interrupted = self.facade.run(compiled, user_input="find order")
        self.assertEqual(interrupted.execution.finish_status, "interrupted")
        proposed = [item for item in interrupted.observability.events if item["event_type"] == "tool_proposed"]
        self.assertEqual(proposed[-1]["payload"]["arguments"]["api_key"], "[REDACTED]")
        checkpoint_id = interrupted.observability.debug_refs[-1]["checkpoint_id"]
        resumed = self.facade.resume(compiled, checkpoint_id=checkpoint_id, resume_payload={"approved": True})
        self.assertEqual(resumed.execution.finish_status, "completed")
        self.assertEqual(resumed.conversation.final_answer, "approved tool")
        event_types = [item["event_type"] for item in resumed.observability.events]
        self.assertIn("resume_started", event_types)
        self.assertIn("resume_completed", event_types)

    def test_checkpoint_record_contains_v0_interrupt_and_observability_fields(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine(
                [
                    PolicyDecision(
                        status="interrupted",
                        reason="approval required",
                        approval_required=True,
                        interrupt_required=True,
                        interrupt_type="approval_required",
                    )
                ]
            ),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        compiled = self.facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
        interrupted = self.facade.run(compiled, user_input="needs approval")
        checkpoint_id = interrupted.observability.debug_refs[-1]["checkpoint_id"]
        record = services.checkpoint_manager.load(checkpoint_id)
        self.assertIn("interrupt_payload", record.interrupt_snapshot)
        self.assertIn("resume_token", record.interrupt_snapshot)
        self.assertIn("event_offset", record.observability_ref)
        self.assertEqual(record.observability_ref["trace_id"], interrupted.observability.trace_id)

    def test_execution_limits_fail_run(self) -> None:
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
        compiled = self.facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
        state = RuntimeState()
        state.run.pattern_id = "react_agent"
        state.conversation.current_user_input = "hello"
        state.execution.max_turns = 1
        result = self.facade.instance.controller.run(compiled, state)
        self.assertEqual(result.execution.finish_status, "failed")
        self.assertIn("max_turns", result.execution.last_error or "")

    def test_execution_timeout_fails_before_node_execution(self) -> None:
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
        compiled = self.facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
        state = RuntimeState()
        state.run.pattern_id = "react_agent"
        state.run.started_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        state.conversation.current_user_input = "hello"
        state.execution.timeout_seconds = 1
        result = self.facade.instance.controller.run(compiled, state)
        self.assertEqual(result.execution.finish_status, "failed")
        self.assertIn("timed out", result.execution.last_error or "")

    def test_subgraph_depth_limit_fails_parent_run(self) -> None:
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
        compiled = self.facade.compile(pattern_id="clarify_then_act", bindings=BindingSet(), services=services)
        state = RuntimeState()
        state.run.pattern_id = "clarify_then_act"
        state.conversation.current_user_input = "hello"
        state.execution.max_subgraph_depth = 0
        result = self.facade.instance.controller.run(compiled, state)
        self.assertEqual(result.execution.finish_status, "failed")
        self.assertIn("max_subgraph_depth", result.execution.last_error or "")

    def test_node_failure_is_reported_as_failed_state(self) -> None:
        services = RuntimeServices(
            model_service=RaisingModelService(),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine([PolicyDecision(status="allowed")]),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        compiled = self.facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
        result = self.facade.run(compiled, user_input="hello")
        self.assertEqual(result.execution.finish_status, "failed")
        event_types = [item["event_type"] for item in result.observability.events]
        self.assertIn("node_failed", event_types)

    def test_harness_new_assertions_and_final_state_snapshot(self) -> None:
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[ModelInvocationResult(assistant_draft="draft", final_answer="final with cite", requests_tool=False)]
            ),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine([PolicyDecision(status="allowed")]),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(documents=[{"id": "hello", "text": "hello", "source": "test"}]),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        bridge = HarnessBridge(facade=self.facade)
        scenario = HarnessScenario(
            scenario_id="new-assertions",
            input_text="hello",
            assertions=[
                {"type": "path_ordered", "expected_node_ids": ["ingress", "precheck", "answer"]},
                {"type": "output_contains", "expected": "final"},
                {"type": "citation_present"},
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
        self.assertEqual(result.final_state_snapshot["execution"]["finish_status"], "completed")

    def test_harness_records_simple_runtime_error(self) -> None:
        services = RuntimeServices(
            model_service=RaisingModelService(),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine([PolicyDecision(status="allowed")]),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        bridge = HarnessBridge(facade=self.facade)
        result = bridge.run_scenario(
            pattern_id="react_agent",
            bindings=BindingSet(),
            services=services,
            fixture=FixtureBundle(),
            scenario=HarnessScenario(scenario_id="runtime-error", input_text="hello"),
        )
        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error["location"], "answer")
        self.assertIn("model exploded", result.error["message"])

    def test_graph_dsl_node_wrappers_wrap_node_execution_and_read_user_config(self) -> None:
        facade = RuntimeKernelFacade(builtins_dir=self._write_wrapped_pattern("wrapped_simple"))
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[ModelInvocationResult(assistant_draft="draft", final_answer="final", requests_tool=False)]
            ),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=PolicyEngine(),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=facade.instance.services.observability_manager,
        )
        compiled = facade.compile(pattern_id="wrapped_simple", bindings=BindingSet(), services=services)
        result = facade.run(
            compiled,
            user_input="hello",
            user_config={"tone": "direct"},
        )

        self.assertEqual(result.execution.finish_status, "completed")
        self.assertEqual(result.context.model_context["tone"], "direct")
        self.assertEqual(result.context.model_context["wrapper_config"]["mode"], "test")
        event_types = [item["event_type"] for item in result.observability.events]
        self.assertIn("wrapper_started", event_types)
        self.assertIn("wrapper_completed", event_types)
        wrapper_events = [
            item for item in result.observability.events if item["payload"].get("wrapper_id") == "test.user_config_before"
        ]
        self.assertTrue(wrapper_events)

    def test_harness_reports_wrapper_error_location(self) -> None:
        facade = RuntimeKernelFacade(builtins_dir=self._write_wrapped_pattern("wrapped_failing", failing=True))
        services = RuntimeServices(
            model_service=ScriptedModelService(),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=PolicyEngine(),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=facade.instance.services.observability_manager,
        )
        bridge = HarnessBridge(facade=facade)

        result = bridge.run_scenario(
            pattern_id="wrapped_failing",
            bindings=BindingSet(),
            services=services,
            fixture=FixtureBundle(),
            scenario=HarnessScenario(scenario_id="wrapper-error", input_text="hello"),
        )

        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error["location"], "answer.before.test.fail_before")
        self.assertIn("wrapper exploded", result.error["message"])

    def test_agent_assembly_compiles_graph_overrides_and_runs(self) -> None:
        spec = AgentAssemblySpec.model_validate(
            {
                "agent": {"id": "assembly_test_agent"},
                "runtime": {
                    "pattern_id": "react_agent",
                    "user_config": {"tone": "precise", "preferences": "likes citations"},
                },
                "graph_overrides": {
                    "node_wrappers": [
                        {
                            "node_id": "answer",
                            "wrappers": [
                                {
                                    "id": "context.prepare_model_context",
                                    "phase": "before",
                                    "order": 10,
                                    "config": {"include_user_config": True, "include_user_profile": True},
                                }
                            ],
                        },
                        {
                            "node_id": "commit",
                            "wrappers": [
                                {
                                    "id": "memory.profile_merge",
                                    "phase": "after",
                                    "order": 10,
                                    "config": {"field": "preferences"},
                                }
                            ],
                        },
                    ]
                },
                "output": {"citations_required": True, "format": "markdown"},
                "metadata": {"render_manifest": self._render_manifest("assembly_test_agent")},
            }
        )
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
        compiler = AgentAssemblyCompiler(facade=self.facade)
        compiled = compiler.compile(spec, services=services)
        result = compiler.run(compiled, user_input="hello")

        self.assertEqual(compiled.pattern_spec.pattern_id, "assembly_test_agent__react_agent")
        self.assertEqual(result.execution.finish_status, "completed")
        self.assertEqual(result.context.model_context["user_config"]["tone"], "precise")
        self.assertEqual(result.memory.user_profile["preferences"], ["likes citations"])

    def test_agent_assembly_loader_loads_example(self) -> None:
        spec = AgentAssemblyLoader().load_path(
            "agent_factory/assembly/examples/investment_research_agent.yaml"
        )

        self.assertEqual(spec.agent.id, "investment_research_agent")
        self.assertEqual(spec.runtime.pattern_id, "react_agent")
        self.assertEqual(spec.graph_overrides.node_wrappers[0].node_id, "answer")

    def test_agent_assembly_rejects_unknown_wrapper_node(self) -> None:
        spec = AgentAssemblySpec.model_validate(
            {
                "agent": {"id": "bad_assembly"},
                "runtime": {"pattern_id": "react_agent"},
                "graph_overrides": {
                    "node_wrappers": [
                        {
                            "node_id": "missing_node",
                            "wrappers": [
                                {"id": "context.prepare_model_context", "phase": "before", "config": {}}
                            ],
                        }
                    ]
                },
                "metadata": {"render_manifest": self._render_manifest("bad_assembly")},
            }
        )
        compiler = AgentAssemblyCompiler(facade=self.facade)

        with self.assertRaises(Exception):
            compiler.compile(spec)

    def test_agent_assembly_runner_returns_harness_repair_report(self) -> None:
        spec = AgentAssemblySpec.model_validate(
            {
                "agent": {"id": "runner_agent"},
                "runtime": {"pattern_id": "react_agent"},
                "metadata": {"render_manifest": self._render_manifest("runner_agent")},
                "harness": [
                    {
                        "scenario_id": "passing",
                        "input_text": "hello",
                        "assertions": [{"type": "output_contains", "expected": "final"}],
                    },
                    {
                        "scenario_id": "failing",
                        "input_text": "hello",
                        "assertions": [{"type": "output_contains", "expected": "missing"}],
                    },
                ],
            }
        )
        services = RuntimeServices(
            model_service=ScriptedModelService(
                responses=[
                    ModelInvocationResult(assistant_draft="draft", final_answer="final", requests_tool=False),
                    ModelInvocationResult(assistant_draft="draft", final_answer="final", requests_tool=False),
                ]
            ),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine([PolicyDecision(status="allowed"), PolicyDecision(status="allowed")]),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        runner = AgentAssemblyRunner(compiler=AgentAssemblyCompiler(facade=self.facade))

        report = runner.run_spec(spec, services=services)

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.agent_id, "runner_agent")
        self.assertEqual(len(report.scenario_results), 2)
        self.assertEqual(report.errors[0]["location"], "harness.assertions")
        self.assertIn("output_contains", report.errors[0]["message"])

    def test_agent_assembly_runner_runs_example_path(self) -> None:
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
        runner = AgentAssemblyRunner(compiler=AgentAssemblyCompiler(facade=self.facade))

        report = runner.run_path(
            "agent_factory/assembly/examples/investment_research_agent.yaml",
            services=services,
        )

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.agent_id, "investment_research_agent")
        self.assertEqual(report.scenario_results[0]["final_state_snapshot"]["execution"]["finish_status"], "completed")

    def test_agent_assembly_runner_captures_runtime_invocation_failure(self) -> None:
        spec = AgentAssemblySpec.model_validate(
            {
                "agent": {"id": "invocation_agent"},
                "runtime": {"pattern_id": "react_agent"},
                "metadata": {"render_manifest": self._render_manifest("invocation_agent")},
            }
        )
        services = RuntimeServices(
            model_service=RaisingModelService(),
            tool_registry=InMemoryToolRegistry(),
            policy_engine=SequencedPolicyEngine([PolicyDecision(status="allowed")]),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            checkpoint_manager=FilesystemCheckpointManager(self.tmpdir / "checkpoints"),
            observability_manager=self.facade.instance.services.observability_manager,
        )
        runner = AgentAssemblyRunner(compiler=AgentAssemblyCompiler(facade=self.facade))
        compiled = runner.compiler.compile(spec, services=services)

        report = runner.run_invocation(compiled, user_input="hello")

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.errors[0]["location"], "answer")
        self.assertIn("model exploded", report.errors[0]["message"])
        result = report.scenario_results[0]
        self.assertEqual(result["scenario_id"], "runtime_invocation")
        self.assertEqual(result["final_state_snapshot"]["execution"]["finish_status"], "failed")
        self.assertTrue(any(item["event_type"] == "node_failed" for item in result["event_log"]))

    def test_observability_summary_tracks_pattern_and_node_latency(self) -> None:
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
        compiled = self.facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
        result = self.facade.run(compiled, user_input="hello")
        summary = services.observability_manager.summary_for(result.run.run_id)
        self.assertIsNotNone(summary)
        self.assertEqual(summary.pattern_id, "react_agent")
        self.assertGreaterEqual(summary.max_node_latency_ms, 0)

    def _write_wrapped_pattern(self, pattern_id: str, *, failing: bool = False) -> Path:
        pattern_dir = self.tmpdir / pattern_id
        pattern_dir.mkdir(parents=True, exist_ok=True)
        wrapper_id = "test.fail_before" if failing else "test.user_config_before"
        config = "{}" if failing else "{mode: test}"
        (pattern_dir / f"{pattern_id}.yaml").write_text(
            f"""
pattern_id: {pattern_id}
kind: main
embeddable: false
version: 1
name: Wrapped Simple
description: Simple wrapped runtime pattern.
entry_node: ingress
nodes:
  - id: ingress
    type: reserved
    impl: ingress
    wrappers:
      - id: console.node_trace
        phase: before
        order: 10
        config: {{}}
      - id: console.node_trace
        phase: after
        order: 10
        config: {{}}
  - id: answer
    type: cognitive
    impl: cognitive.answer
    wrappers:
      - id: {wrapper_id}
        phase: before
        order: 10
        config: {config}
  - id: finalize
    type: reserved
    impl: finalize
edges:
  - from: ingress
    to: answer
    when: always
  - from: answer
    to: finalize
    when: model.ready_to_answer
  - from: finalize
    to: finalize
    when: execution.finished
termination:
  success_nodes:
    - finalize
  failure_nodes: []
constraints:
  allowed_node_types:
    - reserved
    - cognitive
    - operational
    - governance
    - terminal
    - sub_graph
  required_capabilities: []
input_contract:
  readable_sections: []
  writable_sections: []
output_contract:
  readable_sections: []
  writable_sections: []
exit_routes: []
state_mode: shared
""".strip()
            + "\n",
            encoding="utf-8",
        )
        return pattern_dir

    def _render_manifest(self, agent_id: str, pattern_id: str = "react_agent") -> dict:
        pattern = self.facade.instance.pattern_registry.get(pattern_id)
        return {
            "version": "render_manifest.v0",
            "graph_id": f"{agent_id}__{pattern_id}",
            "producer_type": "agent",
            "nodes": {
                node.id: default_node_render_spec(
                    node_id=node.id,
                    node_type=node.type,
                    impl=node.impl,
                ).model_dump(mode="json")
                for node in pattern.nodes
            },
        }


if __name__ == "__main__":
    unittest.main()
