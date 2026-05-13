from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
