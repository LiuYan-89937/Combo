from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage, HumanMessage

from agent_factory.runtime_kernel.adapters import InMemoryToolRegistry, ScriptedModelService
from agent_factory.runtime_kernel.bindings import BindingSet, RuntimeServices
from agent_factory.runtime_kernel.context import ContextEngine
from agent_factory.runtime_kernel.kernel.facade import RuntimeKernelFacade
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


class RuntimeKernelMemorySystemTest(unittest.TestCase):
    def test_runtime_graph_state_uses_messages_channel(self) -> None:
        self.assertIn("messages", RuntimeGraphState.__annotations__)
        self.assertIn("runtime", RuntimeGraphState.__annotations__)

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


def _runtime_services() -> RuntimeServices:
    return RuntimeServices(
        model_service=ScriptedModelService(),
        tool_registry=InMemoryToolRegistry(),
        memory_store=LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store,
        knowledge_engine=KnowledgeEngine(),
        context_engine=ContextEngine(),
        policy_engine=PolicyEngine(),
        observability_manager=ObservabilityManager(),
        checkpointer=LangGraphCheckpointerFactory().build(LangGraphCheckpointerConfig(backend="memory")).saver,
    )


def _runtime_facade() -> RuntimeKernelFacade:
    return RuntimeKernelFacade(
        checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
        memory_store_config=LangGraphStoreConfig(backend="memory"),
    )


if __name__ == "__main__":
    unittest.main()
