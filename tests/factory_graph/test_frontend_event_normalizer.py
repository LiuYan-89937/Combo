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
        normalizer.current_stage_id = "resource_and_condition_planning"

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
        self.assertEqual(tool_events[0].stage_id, "resource_and_condition_planning")
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
                    "stage_id": "requirement_capture",
                    "node_id": "requirement_capture",
                    "node_label": "需求捕获",
                    "node_kind": "llm_subgraph",
                    "severity": "info",
                    "payload": {"doing": "整理需求"},
                },
            }
        )

        node_events = [event for event in events if event.event_type == "node_started"]
        self.assertEqual(len(node_events), 1)
        self.assertEqual(node_events[0].protocol_version, "factory_frontend.v1")
        self.assertEqual(node_events[0].producer_type, "factory")
        self.assertEqual(node_events[0].node_label, "需求捕获")
        self.assertEqual(node_events[0].node_kind, "llm_subgraph")
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
                        "stage_id": "requirement_capture",
                        "node_id": "requirement_capture",
                        "node_label": "需求捕获",
                        "node_kind": "llm_subgraph",
                        "severity": "info",
                        "payload": {},
                    },
                }
            )
        normalizer.emit_update("requirement_capture", {"current_stage": "requirement_capture"})

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
        self.assertEqual(len(proposed), 1)
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0].payload["requests"][0]["tool_call_id"], "call-a")

    def test_model_stream_completes_between_repeated_model_node_calls(self) -> None:
        events = []
        normalizer = RuntimeEventNormalizer(
            emit=events.append,
            request_id="request-a",
            session_id="session-a",
            mode="chat",
            graph_id="factory_chat_graph",
        )

        normalizer.emit_message_chunk(
            (AIMessageChunk(content="before tool"), {"langgraph_node": "chat_model", "tags": []})
        )
        normalizer.emit_update(
            "chat_model",
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
            (AIMessageChunk(content="after tool"), {"langgraph_node": "chat_model", "tags": []})
        )
        normalizer.emit_update("chat_model", {"messages": [{"type": "AIMessage", "content": "after tool"}]})

        completed = [event for event in events if event.event_type == "model_message_completed"]
        self.assertEqual([event.payload["content"] for event in completed], ["before tool", "after tool"])
        self.assertEqual(len({event.payload["stream_id"] for event in completed}), 2)


if __name__ == "__main__":
    unittest.main()
