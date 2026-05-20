from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from agent_factory.runtime_kernel.adapters import InMemoryToolRegistry, ScriptedModelService
from agent_factory.runtime_kernel.bindings import BindingSet, RuntimeServices
from agent_factory.runtime_kernel.context import ContextEngine
from agent_factory.runtime_kernel.execution import ExecutionController
from agent_factory.runtime_kernel.kernel.facade import RuntimeKernelFacade
from agent_factory.runtime_protocol.messages import has_complete_tool_call_history, incomplete_tool_call_ids
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.nodes.standard.answer import CognitiveAnswerNode
from agent_factory.runtime_kernel.nodes.standard.tool_call import OperationalToolCallNode
from agent_factory.runtime_kernel.patterns.compiler import _must_repair_tool_protocol
from agent_factory.runtime_kernel.patterns.schema import PatternNodeSpec
from agent_factory.runtime_kernel.knowledge import KnowledgeEngine
from agent_factory.runtime_kernel.observability import ObservabilityManager
from agent_factory.runtime_kernel.persistence import (
    LangGraphCheckpointerConfig,
    LangGraphCheckpointerFactory,
    LangGraphStoreConfig,
    LangGraphStoreFactory,
    MemoryRecord,
)
from agent_factory.runtime_kernel.policy import PolicyEngine
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager
from agent_factory.runtime_kernel.state import RuntimeGraphState
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.types import ModelInvocationResult, ToolExecutionResult
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.spec import ToolSpec
from agent_factory.memory_system import MemorySystemConfig, MemorySystemRuntime
from agent_factory.memory_system.config import MemoryBackgroundConfig
from agent_factory.memory_system.schema import MemoryWriteReport


class RuntimeKernelMemorySystemTest(unittest.TestCase):
    def test_runtime_graph_state_uses_messages_channel(self) -> None:
        self.assertIn("messages", RuntimeGraphState.__annotations__)
        self.assertIn("runtime", RuntimeGraphState.__annotations__)
        self.assertNotIn("max_turns", RuntimeState().execution.model_dump())
        self.assertEqual(RuntimeState().execution.timeout_seconds, 0)

    def test_agent_session_manager_maps_session_to_thread_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AgentSessionManager(AgentSessionConfig(root=Path(temp_dir) / "sessions"))
            created = manager.create(agent_id="agent_a", first_user_input="hello")
            loaded = manager.load(created.session_id)
            manager.touch_turn(created.session_id, first_user_input="hello again")
            touched = manager.load(created.session_id)

            self.assertEqual(loaded.thread_id, created.thread_id)
            self.assertEqual(touched.turn_count, 1)
            self.assertEqual(touched.first_user_input, "hello")
            self.assertEqual(manager.list_sessions(agent_id="agent_a")[0].session_id, created.session_id)

    def test_same_session_restores_messages_by_thread_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            facade = _runtime_facade()
            services = _runtime_services()
            compiled = facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
            session_root = str(Path(temp_dir) / "sessions")

            first = facade.run(compiled, user_input="first turn", session_config={"session_root": session_root})
            second = facade.run(
                compiled,
                user_input="second turn",
                session_config={"session_root": session_root, "session_id": first.run.session_id},
            )
            snapshot = compiled.graph_app.get_state({"configurable": {"thread_id": first.runtime_config.session_config["thread_id"]}})
            messages = snapshot.values.get("messages") or []

            self.assertEqual(second.run.session_id, first.run.session_id)
            self.assertTrue(any(isinstance(message, HumanMessage) and message.content == "first turn" for message in messages))
            self.assertTrue(any(isinstance(message, AIMessage) and "Echo: first turn" in str(message.content) for message in messages))
            self.assertTrue(any(isinstance(message, HumanMessage) and message.content == "second turn" for message in messages))

    def test_different_sessions_keep_messages_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            facade = _runtime_facade()
            services = _runtime_services()
            compiled = facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
            session_root = str(Path(temp_dir) / "sessions")

            first = facade.run(compiled, user_input="alpha", session_config={"session_root": session_root})
            second = facade.run(compiled, user_input="beta", session_config={"session_root": session_root})
            first_snapshot = compiled.graph_app.get_state({"configurable": {"thread_id": first.runtime_config.session_config["thread_id"]}})
            second_snapshot = compiled.graph_app.get_state({"configurable": {"thread_id": second.runtime_config.session_config["thread_id"]}})
            first_messages = first_snapshot.values.get("messages") or []
            second_messages = second_snapshot.values.get("messages") or []

            self.assertNotEqual(first.run.session_id, second.run.session_id)
            self.assertTrue(any(isinstance(message, HumanMessage) and message.content == "alpha" for message in first_messages))
            self.assertFalse(any(isinstance(message, HumanMessage) and message.content == "beta" for message in first_messages))
            self.assertTrue(any(isinstance(message, HumanMessage) and message.content == "beta" for message in second_messages))

    def test_cross_session_memory_store_put_get_search_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LangGraphStoreFactory().build(
                LangGraphStoreConfig(backend="sqlite", path=Path(temp_dir) / "memory.sqlite")
            ).store
            namespace = ("memory", "agent", "agent_a")
            record = MemoryRecord(scope="agent", kind="preference", content="Prefer concise answers.")
            store.put(namespace, record.memory_id, record.model_dump(mode="json"))

            loaded = store.get(namespace, record.memory_id)
            found = store.search(("memory", "agent"), query="concise")
            store.delete(namespace, record.memory_id)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.value["content"], "Prefer concise answers.")
            self.assertEqual(found[0].key, record.memory_id)
            self.assertIsNone(store.get(namespace, record.memory_id))

    def test_factory_and_agent_memory_namespaces_are_isolated(self) -> None:
        store = LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store
        factory_record = MemoryRecord(scope="factory", kind="decision", content="Factory decision.")
        agent_record = MemoryRecord(scope="agent", kind="decision", content="Agent decision.")
        store.put(("memory", "factory", "project_a"), factory_record.memory_id, factory_record.model_dump(mode="json"))
        store.put(("memory", "agent", "agent_a"), agent_record.memory_id, agent_record.model_dump(mode="json"))

        factory_results = store.search(("memory", "factory"))
        agent_results = store.search(("memory", "agent"))

        self.assertEqual(len(factory_results), 1)
        self.assertEqual(factory_results[0].value["scope"], "factory")
        self.assertEqual(len(agent_results), 1)
        self.assertEqual(agent_results[0].value["scope"], "agent")

    def test_enabled_cross_session_memory_requires_base_store(self) -> None:
        facade = _runtime_facade()
        services = RuntimeServices(
            model_service=ScriptedModelService(),
            tool_registry=InMemoryToolRegistry(),
            memory_store=None,
            memory_system=MemorySystemRuntime(config=MemorySystemConfig(), store=None),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            policy_engine=PolicyEngine(),
            observability_manager=ObservabilityManager(),
            checkpointer=LangGraphCheckpointerFactory().build(LangGraphCheckpointerConfig(backend="memory")).saver,
        )

        with self.assertRaises(RuntimeError):
            facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)

    def test_cross_session_memory_is_optional_for_generated_agent_runtime(self) -> None:
        facade = _runtime_facade()
        services = RuntimeServices(
            model_service=ScriptedModelService(),
            tool_registry=InMemoryToolRegistry(),
            memory_store=None,
            memory_system=None,
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            policy_engine=PolicyEngine(),
            observability_manager=ObservabilityManager(),
            checkpointer=LangGraphCheckpointerFactory().build(LangGraphCheckpointerConfig(backend="memory")).saver,
        )

        compiled = facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)
        with tempfile.TemporaryDirectory() as session_root:
            result = facade.run(compiled, user_input="hello", session_config={"session_root": session_root})

        self.assertEqual(result.execution.finish_status, "completed")

    def test_agent_memory_write_uses_checkpoint_message_window(self) -> None:
        facade = _runtime_facade()
        writer = _CapturingMemoryWriter()
        memory_config = MemorySystemConfig(
            background=MemoryBackgroundConfig(write_interval_turns=2),
            injection_enabled=False,
        )
        services = RuntimeServices(
            model_service=ScriptedModelService(),
            tool_registry=InMemoryToolRegistry(),
            memory_store=LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store,
            memory_system=MemorySystemRuntime(
                config=memory_config,
                store=LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store,
                namespace=("memory", "agent", "agent_a"),
                writer=writer,
            ),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            policy_engine=PolicyEngine(),
            observability_manager=ObservabilityManager(),
            checkpointer=LangGraphCheckpointerFactory().build(LangGraphCheckpointerConfig(backend="memory")).saver,
        )
        compiled = facade.compile(pattern_id="react_agent", bindings=BindingSet(), services=services)

        with tempfile.TemporaryDirectory() as session_root:
            first = facade.run(compiled, user_input="first", session_config={"session_root": session_root})
            facade.run(
                compiled,
                user_input="second",
                session_config={"session_root": session_root, "session_id": first.run.session_id},
            )

        self.assertEqual(len(writer.jobs), 1)
        contents = [message.content for message in writer.jobs[0].segment.messages]
        self.assertIn("first", contents)
        self.assertTrue(any("Echo: first" in content for content in contents))
        self.assertIn("second", contents)


class RuntimeKernelToolPermissionTest(unittest.TestCase):
    def test_answer_node_routes_tools_from_model_tool_calls(self) -> None:
        state = RuntimeState()
        events: list[dict] = []
        context = NodeExecutionContext(
            node_id="answer",
            impl="cognitive.answer",
            services=RuntimeServices(model_service=_ToolCallingModelService()),
            emit_event=events.append,
        )

        patch = CognitiveAnswerNode().execute(state, context)

        self.assertEqual(patch["execution"]["route_decision"], "model.requests_tool")
        self.assertIsInstance(patch["messages"][0], AIMessage)
        self.assertEqual(patch["messages"][0].tool_calls[0]["name"], "ls")
        self.assertEqual(events, [])

    def test_tool_node_returns_tool_messages_when_registry_is_missing(self) -> None:
        state = RuntimeState()
        context = NodeExecutionContext(
            node_id="tool_exec",
            impl="operational.tool_call",
            services=RuntimeServices(tool_registry=None),
            emit_event=lambda _event: None,
            graph_messages=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "ls", "args": {"path": "."}, "id": "call_ls"}],
                )
            ],
        )

        patch = OperationalToolCallNode().execute(state, context)

        self.assertEqual(patch["execution"]["route_decision"], "tool.failed")
        self.assertIsInstance(patch["messages"][0], ToolMessage)
        self.assertEqual(patch["messages"][0].tool_call_id, "call_ls")
        self.assertIn("tool_registry_missing", patch["messages"][0].content)

    def test_system_tool_executes_even_when_business_tool_binding_is_restricted(self) -> None:
        state = RuntimeState()
        registry = _SystemToolRegistry(system_tool_ids=["ls"])
        events: list[dict] = []
        context = NodeExecutionContext(
            node_id="tool_exec",
            impl="operational.tool_call",
            bindings=[
                {
                    "binding_type": "tool_access",
                    "payload": {"allowed_tool_ids": ["business_tool"]},
                }
            ],
            services=RuntimeServices(tool_registry=registry),
            emit_event=events.append,
            graph_messages=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "ls", "args": {"path": "."}, "id": "call_ls"}],
                )
            ],
        )

        patch = OperationalToolCallNode().execute(state, context)

        self.assertEqual(patch["execution"]["route_decision"], "tool.completed")
        self.assertEqual(patch["tools"]["tool_failures"], [])
        self.assertIsInstance(patch["messages"][0], ToolMessage)
        self.assertEqual(patch["messages"][0].tool_call_id, "call_ls")
        self.assertEqual(registry.calls, [("ls", {"path": "."})])

    def test_non_system_tool_is_blocked_by_business_tool_binding(self) -> None:
        state = RuntimeState()
        registry = _SystemToolRegistry(system_tool_ids=["ls"])
        context = NodeExecutionContext(
            node_id="tool_exec",
            impl="operational.tool_call",
            bindings=[
                {
                    "binding_type": "tool_access",
                    "payload": {"allowed_tool_ids": ["business_tool"]},
                }
            ],
            services=RuntimeServices(tool_registry=registry),
            emit_event=lambda _event: None,
            graph_messages=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "other_tool", "args": {}, "id": "call_other"}],
                )
            ],
        )

        patch = OperationalToolCallNode().execute(state, context)

        self.assertEqual(patch["execution"]["route_decision"], "policy.blocked")
        self.assertEqual(patch["policy"]["blocked"], True)
        self.assertIsInstance(patch["messages"][0], ToolMessage)
        self.assertEqual(patch["messages"][0].tool_call_id, "call_other")
        self.assertEqual(registry.calls, [])

    def test_tool_approval_interrupt_originates_from_tool_exec_node(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tool = _compiled_high_risk_tool(root)
            services = _runtime_services(
                model_service=_ToolCallingModelService(tool_id="approval_tool"),
                tool_registry=InMemoryToolRegistry(
                    {"approval_tool": lambda _arguments, _state: {"status": "completed"}},
                    model_tools={"approval_tool": tool},
                    system_tool_ids=["approval_tool"],
                ),
            )
            facade = _runtime_facade()
            bindings = BindingSet.model_validate(
                {
                    "node_bindings": [
                        {
                            "binding_id": "tool_exec_access",
                            "binding_type": "tool_access",
                            "target": {"node_id": "tool_exec", "impl": "operational.tool_call"},
                            "payload": {"allowed_tool_ids": ["approval_tool"]},
                        }
                    ]
                }
            )
            compiled = facade.compile(pattern_id="react_agent", bindings=bindings, services=services)
            run_context = facade.prepare_run_context(
                compiled,
                user_input="call tool",
                session_config={"session_root": str(root / "sessions")},
            )

            tool_events: list[dict] = []
            interrupt_payload = None
            for stream_mode, chunk in facade.instance.controller.stream(
                compiled,
                run_context.state,
                thread_id=run_context.thread_id,
            ):
                if stream_mode == "custom" and isinstance(chunk, dict) and chunk.get("type") == "tool_activity":
                    tool_events.extend(chunk.get("payload", {}).get("events", []))
                if isinstance(chunk, dict) and chunk.get("__interrupt__"):
                    interrupt_payload = getattr(chunk["__interrupt__"][0], "value", None)
                    break

            self.assertEqual(interrupt_payload["type"], "tool_approval")
            self.assertTrue(tool_events)
            self.assertEqual({event["node_id"] for event in tool_events}, {"tool_exec"})
            snapshot = compiled.graph_app.get_state({"configurable": {"thread_id": run_context.thread_id}})
            self.assertTrue(getattr(snapshot, "interrupts", None))

    def test_controller_rejects_incomplete_tool_call_final_state(self) -> None:
        state = RuntimeState()
        result = ExecutionController()._final_state_from_raw(
            {
                "runtime": state.model_dump(mode="python"),
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[{"name": "approval_tool", "args": {}, "id": "call_missing"}],
                    )
                ],
            }
        )

        self.assertEqual(result.execution.finish_status, "failed")
        self.assertIn("call_missing", result.execution.last_error or "")

    def test_message_protocol_validation_handles_serialized_messages(self) -> None:
        serialized = [
            {"type": "human", "content": "use tool"},
            {
                "type": "ai",
                "content": "",
                "tool_calls": [{"name": "ls", "args": {}, "id": "call_serialized"}],
            },
        ]
        completed = [
            *serialized,
            {"type": "tool", "tool_call_id": "call_serialized", "content": "{}"},
        ]

        self.assertEqual(incomplete_tool_call_ids(serialized), ["call_serialized"])
        self.assertFalse(has_complete_tool_call_history(serialized))
        self.assertEqual(incomplete_tool_call_ids(completed), [])
        self.assertTrue(has_complete_tool_call_history(completed))

    def test_timeout_cannot_preempt_pending_tool_protocol_repair(self) -> None:
        tool_node = PatternNodeSpec(id="tool_exec", type="operational", impl="operational.tool_call")
        answer_node = PatternNodeSpec(id="answer", type="cognitive", impl="cognitive.answer")
        raw_state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "ls", "args": {}, "id": "call_pending"}],
                )
            ]
        }

        self.assertTrue(_must_repair_tool_protocol(tool_node, raw_state))
        self.assertFalse(_must_repair_tool_protocol(answer_node, raw_state))


def _runtime_services(
    *,
    model_service=None,
    tool_registry=None,
) -> RuntimeServices:
    return RuntimeServices(
        model_service=model_service or ScriptedModelService(),
        tool_registry=tool_registry or InMemoryToolRegistry(),
        memory_store=LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store,
        knowledge_engine=KnowledgeEngine(),
        context_engine=ContextEngine(),
        policy_engine=PolicyEngine(),
        observability_manager=ObservabilityManager(),
        checkpointer=LangGraphCheckpointerFactory().build(LangGraphCheckpointerConfig(backend="memory")).saver,
    )


class _CapturingMemoryWriter:
    def __init__(self) -> None:
        self.jobs = []

    def enqueue(self, job):
        self.jobs.append(job)
        return MemoryWriteReport(job_id=job.job_id, status="queued", namespace=job.namespace)


class _SystemToolRegistry:
    def __init__(self, *, system_tool_ids: list[str]) -> None:
        self._system_tool_ids = list(system_tool_ids)
        self.calls: list[tuple[str, dict]] = []
        self._model_tools = {
            "ls": StructuredTool.from_function(
                func=self._ls,
                name="ls",
                description="List files.",
            ),
            "other_tool": StructuredTool.from_function(
                func=self._other_tool,
                name="other_tool",
                description="Other tool.",
            ),
        }

    def list_tool_ids(self) -> list[str]:
        return sorted(self._model_tools)

    def system_tool_ids(self) -> list[str]:
        return list(self._system_tool_ids)

    def model_tools(self, tool_ids: list[str] | set[str] | None = None):
        if tool_ids is None:
            return list(self._model_tools.values())
        selected = set(tool_ids)
        return [tool for tool_id, tool in self._model_tools.items() if tool_id in selected]

    def execute(self, tool_id: str, arguments: dict, *, state) -> ToolExecutionResult:
        self.calls.append((tool_id, dict(arguments)))
        return ToolExecutionResult(
            status="completed",
            output={"tool_id": tool_id, "arguments": dict(arguments)},
            observation_summary="ok",
        )

    def _ls(self, path: str = ".") -> dict:
        self.calls.append(("ls", {"path": path}))
        return {"type": "tool_observation", "status": "completed", "tool_id": "ls", "message": "ok", "output": {"path": path}}

    def _other_tool(self) -> dict:
        self.calls.append(("other_tool", {}))
        return {"type": "tool_observation", "status": "completed", "tool_id": "other_tool", "message": "ok", "output": {}}


class _ToolCallingModelService:
    def __init__(self, *, tool_id: str = "ls") -> None:
        self.tool_id = tool_id

    def generate(self, **_kwargs) -> ModelInvocationResult:
        arguments = {"path": "."} if self.tool_id == "ls" else {}
        ai_message = AIMessage(
            content="",
            tool_calls=[{"name": self.tool_id, "args": arguments, "id": f"call_{self.tool_id}"}],
        )
        return ModelInvocationResult(
            ai_message=ai_message,
            assistant_draft="",
            tool_calls=list(ai_message.tool_calls),
        )


def _compiled_high_risk_tool(root: Path):
    package_tool = root / "tools" / "approval_tool" / "tool.py"
    package_tool.parent.mkdir(parents=True)
    package_tool.write_text(
        "def run(arguments: dict, resources: dict) -> dict:\n"
        "    return {'status': 'completed'}\n",
        encoding="utf-8",
    )
    spec = ToolSpec(
        id="approval_tool",
        description="Approval test tool.",
        entrypoint="tools/approval_tool/tool.py:run",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
        risk_level="high",
    )
    return ToolCompiler(package_root=root).compile(spec)


def _runtime_facade() -> RuntimeKernelFacade:
    return RuntimeKernelFacade(
        checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
        memory_store_config=LangGraphStoreConfig(backend="memory"),
    )


if __name__ == "__main__":
    unittest.main()
