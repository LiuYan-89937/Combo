from __future__ import annotations

import unittest

from langchain_core.messages import AIMessageChunk

from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer


class FrontendEventNormalizerTest(unittest.TestCase):
    def test_custom_tool_activity_event_emits_standard_tool_completion(self) -> None:
        events = []
        normalizer = RuntimeEventNormalizer(
            emit=events.append,
            request_id="request-a",
            session_id="session-a",
            mode="create_agent",
            graph_id="factory_graph",
        )
        normalizer.current_stage_id = "product_brief"

        normalizer.emit_custom_event(
            {
                "type": "tool_activity",
                "payload": {
                    "events": [
                        {
                            "event_type": "tool_call_completed",
                            "tool_call_id": "call-a",
                            "tool_name": "shell_cwd",
                            "message": {
                                "type": "ToolMessage",
                                "name": "shell_cwd",
                                "tool_call_id": "call-a",
                                "content": '{"cwd": "/tmp"}',
                            },
                        }
                    ]
                },
            }
        )

        tool_events = [event for event in events if event.event_type == "tool_call_completed"]
        self.assertEqual(len(tool_events), 1)
        self.assertEqual(tool_events[0].stage_id, "product_brief")
        self.assertEqual(tool_events[0].payload["tool_call_id"], "call-a")
        self.assertEqual(tool_events[0].payload["tool_name"], "shell_cwd")

    def test_runtime_render_event_preserves_node_render_fields(self) -> None:
        events = []
        normalizer = RuntimeEventNormalizer(
            emit=events.append,
            request_id="request-a",
            session_id="session-a",
            mode="create_agent",
            graph_id="factory_graph",
        )

        normalizer.emit_custom_event(
            {
                "type": "runtime_render_event",
                "payload": {
                    "protocol_version": "runtime_render.v1",
                    "event_type": "node_started",
                    "producer_type": "factory",
                    "graph_id": "factory_graph",
                    "stage_id": "product_brief",
                    "node_id": "product_brief",
                    "node_label": "Product Brief",
                    "node_kind": "factory_manufacturing_domain",
                    "severity": "info",
                    "payload": {"doing": "整理需求"},
                },
            }
        )

        node_events = [event for event in events if event.event_type == "node_started"]
        self.assertEqual(len(node_events), 1)
        self.assertEqual(node_events[0].protocol_version, "factory_frontend.v1")
        self.assertEqual(node_events[0].producer_type, "factory")
        self.assertEqual(node_events[0].node_label, "Product Brief")
        self.assertEqual(node_events[0].node_kind, "factory_manufacturing_domain")
        self.assertEqual(node_events[0].payload["doing"], "整理需求")
        self.assertEqual(node_events[0].payload["source_protocol_version"], "runtime_render.v1")

    def test_runtime_render_events_prevent_update_fallback_duplicates(self) -> None:
        events = []
        normalizer = RuntimeEventNormalizer(
            emit=events.append,
            request_id="request-a",
            session_id="session-a",
            mode="create_agent",
            graph_id="factory_graph",
        )

        for event_type in ("node_started", "node_completed"):
            normalizer.emit_custom_event(
                {
                    "type": "runtime_render_event",
                    "payload": {
                        "protocol_version": "runtime_render.v1",
                        "event_type": event_type,
                        "producer_type": "factory",
                        "graph_id": "factory_graph",
                        "stage_id": "product_brief",
                        "node_id": "product_brief",
                        "node_label": "Product Brief",
                        "node_kind": "factory_manufacturing_domain",
                        "severity": "info",
                        "payload": {},
                    },
                }
            )
        normalizer.emit_update("product_brief", {})

        self.assertEqual(len([event for event in events if event.event_type == "node_started"]), 1)
        self.assertEqual(len([event for event in events if event.event_type == "node_completed"]), 1)

    def test_tool_approval_reuses_existing_tool_call_without_duplicate_proposal(self) -> None:
        events = []
        normalizer = RuntimeEventNormalizer(
            emit=events.append,
            request_id="request-a",
            session_id="session-a",
            mode="create_agent",
            graph_id="factory_graph",
        )

        normalizer.emit_custom_event(
            {
                "type": "tool_activity",
                "payload": {
                    "events": [
                        {
                            "event_type": "tool_call_proposed",
                            "tool_call_id": "call-a",
                            "tool_id": "bash",
                            "arguments": {"command": ["pwd"]},
                        }
                    ]
                },
            }
        )
        normalizer.emit_interrupt(
            {
                "type": "tool_approval",
                "requests": [
                    {
                        "tool_name": "bash",
                        "args": {"command": ["pwd"]},
                    }
                ],
            }
        )

        proposed = [event for event in events if event.event_type == "tool_call_proposed"]
        approvals = [event for event in events if event.event_type == "tool_approval_requested"]
        generic_interrupts = [event for event in events if event.event_type == "interrupt_requested"]
        self.assertEqual(len(proposed), 1)
        self.assertEqual(len(approvals), 1)
        self.assertEqual(generic_interrupts, [])
        self.assertEqual(approvals[0].payload["requests"][0]["tool_call_id"], "call-a")

    def test_model_stream_completes_between_repeated_model_node_calls(self) -> None:
        events = []
        normalizer = RuntimeEventNormalizer(
            emit=events.append,
            request_id="request-a",
            session_id="session-a",
            mode="chat",
            graph_id="factory_chat_package",
        )

        normalizer.emit_message_chunk(
            (AIMessageChunk(content="before tool"), {"langgraph_node": "answer", "tags": []})
        )
        normalizer.emit_update(
            "answer",
            {
                "messages": [
                    {
                        "type": "AIMessage",
                        "content": "before tool",
                        "tool_calls": [
                            {"id": "call-a", "name": "skill", "args": {"action": "load", "name": "weather"}}
                        ],
                    }
                ]
            },
        )
        normalizer.emit_message_chunk(
            (AIMessageChunk(content="after tool"), {"langgraph_node": "answer", "tags": []})
        )
        normalizer.emit_update("answer", {"messages": [{"type": "AIMessage", "content": "after tool"}]})

        completed = [event for event in events if event.event_type == "model_message_completed"]
        self.assertEqual([event.payload["content"] for event in completed], ["before tool", "after tool"])
        self.assertEqual(len({event.payload["stream_id"] for event in completed}), 2)

    def test_context_prepare_and_skipped_compression_events_are_forwarded(self) -> None:
        events = []
        normalizer = RuntimeEventNormalizer(
            emit=events.append,
            request_id="request-a",
            session_id="session-a",
            mode="chat",
            graph_id="factory_chat_package",
        )

        for event_type in ("context_prepare_started", "context_prepare_completed", "context_compression_skipped"):
            normalizer.emit_custom_event(
                {
                    "type": "context_event",
                    "payload": {
                        "event_type": event_type,
                        "node_id": "answer",
                        "status": "skipped" if event_type.endswith("skipped") else "completed",
                    },
                }
            )

        self.assertEqual(
            [event.event_type for event in events],
            ["context_prepare_started", "context_prepare_completed", "context_compression_skipped"],
        )
        self.assertEqual(events[-1].node_id, "answer")

if __name__ == "__main__":
    unittest.main()
