from __future__ import annotations

import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

from agent_factory.context_system.assembly import assemble_context_frame
from agent_factory.context_system.compression import maybe_compress_messages
from agent_factory.context_system.runtime import ContextSystemRuntime
from agent_factory.context_system.schema import (
    AssemblyPolicy,
    CompressionPolicy,
    ContextCandidate,
    ContextContractConfig,
    ContextQuery,
)
from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.observability import ObservabilityManager
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.wrappers.system_context import SYSTEM_CONTEXT_PREPARE_WRAPPER
from agent_factory.runtime_protocol.messages import has_complete_tool_call_history


class ContextSystemTest(unittest.TestCase):
    def test_context_contract_rejects_unknown_profile_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ContextContractConfig.model_validate(
                {
                    "enabled": True,
                    "default_policy": {},
                    "profile": "unsupported",
                }
            )

    def test_assembly_dedupes_and_respects_budget(self) -> None:
        candidates = [
            _candidate("a", "memory", "same fact", 0.9, 20),
            _candidate("b", "memory", "same fact", 0.8, 20),
            _candidate("c", "resources", "resource detail", 0.7, 20),
        ]
        frame = assemble_context_frame(
            node_id="answer",
            query=ContextQuery(node_id="answer", impl="cognitive.answer", text="query"),
            candidates=candidates,
            policy=AssemblyPolicy(max_items_total=2, max_tokens_total=100),
        )

        self.assertEqual([item.candidate_id for item in frame.items], ["a", "c"])
        self.assertIn("Use only what is relevant", frame.text)

    def test_compression_writes_summary_message_and_keeps_tool_pairs(self) -> None:
        messages = [
            HumanMessage(content="hello"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "ls", "args": {}}]),
            ToolMessage(content="ok", tool_call_id="call_1"),
            HumanMessage(content="more context" * 800),
            AIMessage(content="answer" * 800),
            HumanMessage(content="latest"),
        ]
        with patch("agent_factory.context_system.compression.get_compression_model", return_value=_FakeModel()), patch(
            "agent_factory.context_system.compression.get_compression_model_settings",
            return_value=_FakeSettings(),
        ):
            compressed, report = maybe_compress_messages(
                messages=messages,
                policy=CompressionPolicy(trigger_token_threshold=1000, keep_recent_messages=2),
                node_id="answer",
            )

        self.assertEqual(report.status, "completed")
        self.assertTrue(any(isinstance(message, SystemMessage) for message in compressed))
        self.assertTrue(has_complete_tool_call_history(compressed))

    def test_system_wrapper_skips_non_cognitive_nodes(self) -> None:
        state = RuntimeState()
        context = NodeExecutionContext(
            node_id="tool_exec",
            impl="operational.tool_call",
            services=RuntimeServices(observability_manager=ObservabilityManager()),
            emit_event=lambda _payload: None,
            graph_messages=[HumanMessage(content="hi")],
        )

        updated, patch = SYSTEM_CONTEXT_PREPARE_WRAPPER.before(state=state, context=context)

        self.assertIs(updated, state)
        self.assertEqual(patch, {})

    def test_runtime_injects_context_frame_without_message_changes_under_threshold(self) -> None:
        runtime = ContextSystemRuntime()
        state = RuntimeState()
        state.conversation.current_user_input = "what resources exist?"
        result = runtime.prepare_before_model_call(
            state=state,
            node_id="answer",
            impl="cognitive.answer",
            messages=[HumanMessage(content="what resources exist?")],
            services=RuntimeServices(observability_manager=ObservabilityManager()),
            resources={"support_contact": "runtime-fixture"},
        )

        self.assertFalse(result.messages_changed)
        self.assertIsNotNone(result.frame)
        self.assertIn("llm_context_frame", result.state.context.model_context)


class _FakeSettings:
    max_tokens = 512


class _FakeModel:
    def bind(self, **_kwargs):
        return self

    def invoke(self, _messages):
        return AIMessage(content="summary of older conversation")


def _candidate(candidate_id: str, source_id: str, content: str, score: float, tokens: int) -> ContextCandidate:
    return ContextCandidate(
        candidate_id=candidate_id,
        source_id=source_id,
        kind="memory" if source_id == "memory" else "resource",
        content=content,
        score=score,
        token_estimate=tokens,
    )


if __name__ == "__main__":
    unittest.main()
