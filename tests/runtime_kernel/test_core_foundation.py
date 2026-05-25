from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage
from pydantic import BaseModel

from agent_factory.artifact_system import ArtifactStore, ReportStore
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_contracts.contribution import RuntimeContribution, RuntimeContributionMerger
from agent_factory.runtime_contracts.schema import (
    NodeProviderContract,
    REQUIRED_AGENT_PACKAGE_CONTRACTS,
    StateContract,
)
from agent_factory.runtime_kernel.bindings import BindingSet
from agent_factory.runtime_kernel.bookmarks import InMemoryBookmarkStore
from agent_factory.runtime_kernel.kernel.facade import RuntimeKernelFacade
from agent_factory.runtime_kernel.model_operations import ModelOperationService
from agent_factory.runtime_kernel.node_providers import NodeProviderRegistry, PackageNodeProviderFactory, StaticNodeProvider
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.patterns.schema import (
    GraphPatternSpec,
    PatternIOContractSpec,
    PatternNodeSpec,
    PatternTerminationSpec,
)
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.state_contracts import PackageStateManager, StateNamespaceSpec


class RuntimeKernelCoreFoundationTest(unittest.TestCase):
    def test_package_state_defaults_to_serializable_object(self) -> None:
        state = RuntimeState()

        self.assertEqual(state.package_state, {})
        self.assertEqual(RuntimeState.model_validate(state.model_dump(mode="json")).package_state, {})

    def test_state_contract_validates_namespace_permissions_and_schema(self) -> None:
        spec = StateNamespaceSpec(
            namespace="workflow",
            schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            initial_state={"value": "initial"},
            writable_node_ids=frozenset({"writer"}),
        )
        manager = PackageStateManager([spec])

        self.assertEqual(manager.initial_state(), {"workflow": {"value": "initial"}})
        manager.validate_patch(node_id="writer", patch={"workflow": {"value": "updated"}})
        with self.assertRaises(Exception):
            manager.validate_patch(node_id="other", patch={"workflow": {"value": "updated"}})
        with self.assertRaises(Exception):
            manager.validate_patch(node_id="writer", patch={"unknown": {}})
        with self.assertRaises(Exception):
            manager.validate_patch(node_id="writer", patch={"workflow": {"value": 1}})

    def test_node_provider_conflicts_are_detected_by_contribution_merger(self) -> None:
        first = StaticNodeProvider(provider_id="first", nodes=(_StateWriterNode(),))
        second = StaticNodeProvider(provider_id="second", nodes=(_StateWriterNode(),))

        with self.assertRaises(Exception):
            RuntimeContributionMerger(base_services=_facade().instance.services).merge(
                [
                    RuntimeContribution(node_providers=[first]),
                    RuntimeContribution(node_providers=[second]),
                ]
            )

    def test_node_provider_implementation_can_write_declared_package_state(self) -> None:
        facade = _facade()
        provider = StaticNodeProvider(provider_id="test_provider", nodes=(_StateWriterNode(),))
        facade.register_node_providers([provider])
        facade.instance.pattern_registry.register(_package_state_pattern())
        spec = StateNamespaceSpec(
            namespace="workflow",
            schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            initial_state={"value": "initial"},
            writable_node_ids=frozenset({"writer"}),
        )
        compiled = facade.compile(
            pattern_id="package_state_test",
            bindings=BindingSet(),
            node_providers=[provider],
            state_contracts=[spec],
        )

        with tempfile.TemporaryDirectory() as session_root:
            result = facade.run(compiled, user_input="hello", session_config={"session_root": session_root})
        bookmarks = compiled.services.bookmark_store.list(thread_id=result.runtime_config.session_config["thread_id"])

        self.assertEqual(result.package_state, {"workflow": {"value": "ok"}})
        self.assertEqual([bookmark.position for bookmark in bookmarks], ["entry", "completion"])

    def test_package_state_is_restored_from_checkpoint_between_turns(self) -> None:
        facade = _facade()
        provider = StaticNodeProvider(provider_id="counter_provider", nodes=(_StateCounterNode(),))
        facade.register_node_providers([provider])
        facade.instance.pattern_registry.register(_package_state_counter_pattern())
        spec = StateNamespaceSpec(
            namespace="workflow",
            schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
                "additionalProperties": False,
            },
            initial_state={"count": 0},
            writable_node_ids=frozenset({"counter"}),
        )
        compiled = facade.compile(
            pattern_id="package_state_counter_test",
            bindings=BindingSet(),
            node_providers=[provider],
            state_contracts=[spec],
        )

        with tempfile.TemporaryDirectory() as session_root:
            first = facade.run(compiled, user_input="first", session_config={"session_root": session_root})
            second = facade.run(
                compiled,
                user_input="second",
                session_config={
                    "session_root": session_root,
                    "session_id": first.runtime_config.session_config["session_id"],
                },
            )

        self.assertEqual(first.package_state, {"workflow": {"count": 1}})
        self.assertEqual(second.package_state, {"workflow": {"count": 2}})

    def test_core_foundation_contracts_are_registered_and_required(self) -> None:
        registry = default_runtime_contract_registry(node_provider_registry=NodeProviderRegistry())

        self.assertIn("node_provider@node_provider_contract.v0", registry.known_contracts())
        self.assertIn("state@state_contract.v0", registry.known_contracts())
        self.assertIn("artifact@artifact_contract.v0", registry.known_contracts())
        self.assertIn("knowledge@knowledge_contract.v0", registry.known_contracts())
        self.assertIn("node_provider", REQUIRED_AGENT_PACKAGE_CONTRACTS)
        self.assertIn("state", REQUIRED_AGENT_PACKAGE_CONTRACTS)
        self.assertIn("artifact", REQUIRED_AGENT_PACKAGE_CONTRACTS)
        self.assertIn("knowledge", REQUIRED_AGENT_PACKAGE_CONTRACTS)

    def test_state_contract_rejects_unsafe_package_paths(self) -> None:
        payload = {
            "type": "state",
            "version": "state_contract.v0",
            "config": {
                "namespace": "workflow",
                "schema_path": "/tmp/schema.json",
                "initial_state_path": "state/initial.json",
                "writable_node_ids": ["writer"],
            },
        }

        with self.assertRaises(Exception):
            StateContract.model_validate(payload)

        payload["config"]["schema_path"] = "../schema.json"
        with self.assertRaises(Exception):
            StateContract.model_validate(payload)

    def test_node_provider_contract_rejects_unknown_provider_id(self) -> None:
        registry = default_runtime_contract_registry(node_provider_registry=NodeProviderRegistry())
        contract = NodeProviderContract.model_validate(
            {
                "type": "node_provider",
                "version": "node_provider_contract.v0",
                "config": {"providers": [{"provider_id": "missing_provider", "config": {}}]},
            }
        )

        with self.assertRaises(Exception):
            registry.builder_for(contract).build(contract, None)

    def test_model_operation_structured_json_uses_single_kernel_service(self) -> None:
        class Decision(BaseModel):
            answer: str

        service = ModelOperationService(model=_FakeModel())

        text_result = service.text(state=RuntimeState())
        structured_result = service.structured_json(output_model=Decision, state=RuntimeState())

        self.assertEqual(text_result.final_answer, "hello")
        self.assertEqual(structured_result.answer, "ok")

    def test_model_operation_structured_json_repairs_from_validator_observation(self) -> None:
        class Decision(BaseModel):
            answer: str

        model = _RepairingFakeModel()
        events: list[dict] = []
        service = ModelOperationService(model=model)

        result = service.structured_json(
            output_model=Decision,
            state=RuntimeState(),
            max_attempts=2,
            emit_event=events.append,
        )

        self.assertEqual(result.answer, "fixed")
        self.assertEqual(len(model.calls), 2)
        self.assertIn("Validation observation", model.calls[1][-1].content)
        self.assertEqual([event["event_type"] for event in events], [
            "model_call_started",
            "model_call_failed",
            "model_call_started",
            "model_call_completed",
        ])

    def test_model_operation_binding_rejects_invalid_payload(self) -> None:
        with self.assertRaises(Exception):
            BindingSet.model_validate(
                {
                    "node_bindings": [
                        {
                            "binding_id": "bad",
                            "binding_type": "model_operation",
                            "target": {"node_id": "structured", "impl": "cognitive.structured"},
                            "payload": {
                                "operation": "invalid",
                                "output_schema": {"type": "object"},
                                "write_target": {"section": "context"},
                            },
                        }
                    ]
                }
            )

    def test_cognitive_structured_node_writes_validated_package_state(self) -> None:
        facade = _facade()
        facade.instance.services.model_operation_service = ModelOperationService(model=_FakeModel())
        facade.instance.pattern_registry.register(_structured_output_pattern())
        spec = StateNamespaceSpec(
            namespace="workflow",
            schema={
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                        "additionalProperties": False,
                    }
                },
                "required": ["decision"],
                "additionalProperties": False,
            },
            initial_state={"decision": {"answer": "initial"}},
            writable_node_ids=frozenset({"structured"}),
        )
        compiled = facade.compile(
            pattern_id="structured_output_test",
            bindings=_structured_output_bindings(),
            state_contracts=[spec],
        )

        with tempfile.TemporaryDirectory() as session_root:
            result = facade.run(compiled, user_input="decide", session_config={"session_root": session_root})

        self.assertEqual(result.package_state["workflow"]["decision"], {"answer": "ok"})

    def test_package_node_provider_loads_package_local_node(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            node_dir = root / "nodes" / "echo"
            node_dir.mkdir(parents=True)
            (node_dir / "node.py").write_text(
                "def run(input, context):\n"
                "    return {'package_state': {'workflow': {'value': context.package_state['workflow']['value'] + '-node'}}}\n",
                encoding="utf-8",
            )
            (node_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "version": "package_node.v0",
                        "impl_id": "package.echo",
                        "node_type": "operational",
                        "entrypoint": "node.py:run",
                        "input_schema": {"type": "object", "additionalProperties": True},
                        "output_schema": {"type": "object", "additionalProperties": True},
                        "readable_sections": ["package_state"],
                        "writable_sections": ["package_state"],
                        "required_services": [],
                        "tool_access": [],
                        "description": "Echo package state.",
                    }
                ),
                encoding="utf-8",
            )

            provider = PackageNodeProviderFactory().build(package_root=root, config={"roots": ["nodes"]})
            implementation = provider.implementations()[0]

        self.assertEqual(implementation.impl_id, "package.echo")
        self.assertEqual(implementation.writable_sections, {"package_state"})

    def test_artifact_and_report_stores_write_index_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "artifacts"
            store = ArtifactStore(
                root=root,
                index_path=root / "index.jsonl",
                allowed_kinds=["report", "trace"],
            )
            report_store = ReportStore(artifact_store=store)

            report = report_store.write_report(report_id="run_1", payload={"status": "ok"})
            trace = store.write_text(kind="trace", relative_path="traces/run_1.txt", content="trace")

            self.assertTrue(Path(report["path"]).is_file())
            self.assertTrue(Path(trace["path"]).is_file())
            self.assertEqual(len((root / "index.jsonl").read_text(encoding="utf-8").splitlines()), 2)
            with self.assertRaises(ValueError):
                store.write_text(kind="secret", relative_path="secret.txt", content="no")


class _StateWriterNode:
    impl_id = "test.package_state_writer"
    node_type = "operational"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"package_state"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict:
        return {"package_state": {"workflow": {"value": "ok"}}}


class _StateCounterNode:
    impl_id = "test.package_state_counter"
    node_type = "operational"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"package_state"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict:
        current = dict(state.package_state.get("workflow") or {})
        return {"package_state": {"workflow": {"count": int(current.get("count") or 0) + 1}}}


class _FakeStructuredModel:
    def __init__(self, output_model: type[BaseModel]) -> None:
        self.output_model = output_model

    def invoke(self, _messages):
        return self.output_model(answer="ok")


class _FakeModel:
    def invoke(self, _messages):
        return AIMessage(content="hello")

    def with_structured_output(self, output_model: type[BaseModel]):
        return _FakeStructuredModel(output_model)


class _RepairingStructuredModel:
    def __init__(self, parent: "_RepairingFakeModel", output_model: type[BaseModel]) -> None:
        self.parent = parent
        self.output_model = output_model

    def invoke(self, messages):
        self.parent.calls.append(list(messages))
        if any("Validation observation" in str(getattr(message, "content", "")) for message in messages):
            return self.output_model(answer="fixed")
        return {"unexpected": "shape"}


class _RepairingFakeModel:
    def __init__(self) -> None:
        self.calls: list[list] = []

    def with_structured_output(self, output_model: type[BaseModel]):
        return _RepairingStructuredModel(self, output_model)


def _facade() -> RuntimeKernelFacade:
    facade = RuntimeKernelFacade(
        checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
        memory_store_config=LangGraphStoreConfig(backend="memory"),
    )
    facade.instance.services.bookmark_store = InMemoryBookmarkStore()
    return facade


def _package_state_pattern() -> GraphPatternSpec:
    return GraphPatternSpec(
        pattern_id="package_state_test",
        kind="main",
        embeddable=False,
        version=1,
        name="Package State Test",
        description="Test package_state writes through provider nodes.",
        entry_node="writer",
        nodes=[
            PatternNodeSpec(
                id="writer",
                type="operational",
                impl="test.package_state_writer",
            )
        ],
        termination=PatternTerminationSpec(success_nodes=["writer"]),
        input_contract=PatternIOContractSpec(readable_sections=["package_state"], writable_sections=[]),
        output_contract=PatternIOContractSpec(readable_sections=[], writable_sections=["package_state"]),
    )


def _package_state_counter_pattern() -> GraphPatternSpec:
    return GraphPatternSpec(
        pattern_id="package_state_counter_test",
        kind="main",
        embeddable=False,
        version=1,
        name="Package State Counter Test",
        description="Test package_state restore between turns.",
        entry_node="counter",
        nodes=[
            PatternNodeSpec(
                id="counter",
                type="operational",
                impl="test.package_state_counter",
            )
        ],
        termination=PatternTerminationSpec(success_nodes=["counter"]),
        input_contract=PatternIOContractSpec(readable_sections=["package_state"], writable_sections=[]),
        output_contract=PatternIOContractSpec(readable_sections=[], writable_sections=["package_state"]),
    )


def _structured_output_pattern() -> GraphPatternSpec:
    return GraphPatternSpec(
        pattern_id="structured_output_test",
        kind="main",
        embeddable=False,
        version=1,
        name="Structured Output Test",
        description="Test structured model output writes package state.",
        entry_node="structured",
        nodes=[
            PatternNodeSpec(
                id="structured",
                type="cognitive",
                impl="cognitive.structured",
            )
        ],
        termination=PatternTerminationSpec(success_nodes=["structured"]),
        input_contract=PatternIOContractSpec(readable_sections=["package_state"], writable_sections=[]),
        output_contract=PatternIOContractSpec(readable_sections=[], writable_sections=["package_state"]),
    )


def _structured_output_bindings() -> BindingSet:
    return BindingSet.model_validate(
        {
            "node_bindings": [
                {
                    "binding_id": "structured_model_operation",
                    "binding_type": "model_operation",
                    "target": {"node_id": "structured", "impl": "cognitive.structured"},
                    "payload": {
                        "operation": "structured_json",
                        "model_role": "main",
                        "output_schema": {
                            "type": "object",
                            "properties": {"answer": {"type": "string"}},
                            "required": ["answer"],
                            "additionalProperties": False,
                        },
                        "write_target": {
                            "section": "package_state",
                            "namespace": "workflow",
                            "path": ["decision"],
                        },
                        "max_attempts": 1,
                    },
                }
            ]
        }
    )


if __name__ == "__main__":
    unittest.main()
