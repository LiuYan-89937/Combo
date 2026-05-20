from __future__ import annotations

import json
import sys
import threading
import unittest

from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentRuntimeContainerHandle


class AgentRuntimeContainerHandleTest(unittest.TestCase):
    def test_background_events_are_emitted_without_waiting_for_next_command(self) -> None:
        received = []
        background_event = threading.Event()

        def emit(item):
            received.append(item)
            background_event.set()

        handle = AgentRuntimeContainerHandle(
            package_id="test_package",
            package_fingerprint="fingerprint",
            idle_timeout_seconds=0,
            command=[sys.executable, "-u", "-c", _BRIDGE_SCRIPT],
            emit=emit,
        )
        try:
            self.assertTrue(background_event.wait(timeout=3))
            self.assertEqual(received[0].event_type, "scheduler_feedback_completed")
            self.assertIsNone(received[0].request_id)

            events = list(handle.send({"type": "run_message", "request_id": "req_1", "payload": {}}))
            request_events = [item.event_type for mode, item in events if mode == "frontend_event"]
            self.assertEqual(request_events, ["run_started", "run_completed"])
            self.assertEqual([item.event_type for item in received], ["scheduler_feedback_completed"])
        finally:
            handle.close()


_BRIDGE_SCRIPT = r'''
import datetime
import json
import sys
import uuid


def emit(event_type, request_id=None, payload=None):
    sys.stdout.write(json.dumps({
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "request_id": request_id,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "mode": "agent_package",
        "producer_type": "agent_runtime",
        "payload": payload or {},
    }, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


emit("scheduler_feedback_completed", payload={"job_id": "job_1", "summary": "done"})
for line in sys.stdin:
    command = json.loads(line)
    if command.get("type") == "shutdown":
        break
    request_id = command.get("request_id")
    emit("run_started", request_id=request_id)
    emit("run_completed", request_id=request_id)
'''


if __name__ == "__main__":
    unittest.main()
