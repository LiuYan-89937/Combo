from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy
from agent_factory.factory_graph.frontend_bridge.agent_runtime_launcher import (
    AgentRuntimeLaunchError,
    DockerAgentRuntimeLauncher,
)
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
            request_policy=RuntimeRequestPolicy(timeout_seconds=10, heartbeat_seconds=0),
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

    def test_request_timeout_emits_terminal_run_failed(self) -> None:
        handle = AgentRuntimeContainerHandle(
            package_id="test_package",
            package_fingerprint="fingerprint",
            idle_timeout_seconds=0,
            request_policy=RuntimeRequestPolicy(timeout_seconds=1, heartbeat_seconds=0),
            command=[sys.executable, "-u", "-c", _BRIDGE_SCRIPT_NO_TERMINAL],
            emit=lambda _item: None,
        )
        try:
            events = list(handle.send({"type": "run_message", "request_id": "req_timeout", "payload": {}}))
        finally:
            handle.close()

        frontend_events = [item for mode, item in events if mode == "frontend_event"]
        self.assertEqual(frontend_events[-1].event_type, "run_failed")
        self.assertEqual(frontend_events[-1].payload["why"], "request_timeout")

    def test_request_heartbeat_emits_progress_before_completion(self) -> None:
        handle = AgentRuntimeContainerHandle(
            package_id="test_package",
            package_fingerprint="fingerprint",
            idle_timeout_seconds=0,
            request_policy=RuntimeRequestPolicy(timeout_seconds=5, heartbeat_seconds=1),
            command=[sys.executable, "-u", "-c", _BRIDGE_SCRIPT_DELAYED_COMPLETION],
            emit=lambda _item: None,
        )
        try:
            events = list(handle.send({"type": "run_message", "request_id": "req_heartbeat", "payload": {}}))
        finally:
            handle.close()

        event_types = [item.event_type for mode, item in events if mode == "frontend_event"]
        self.assertIn("node_progress", event_types)
        self.assertEqual(event_types[-1], "run_completed")

    def test_cancel_active_request_emits_terminal_run_failed(self) -> None:
        handle = AgentRuntimeContainerHandle(
            package_id="test_package",
            package_fingerprint="fingerprint",
            idle_timeout_seconds=0,
            request_policy=RuntimeRequestPolicy(timeout_seconds=10, heartbeat_seconds=0),
            command=[sys.executable, "-u", "-c", _BRIDGE_SCRIPT_NO_TERMINAL],
            emit=lambda _item: None,
        )
        events: list[tuple[str, object]] = []
        started = threading.Event()

        def consume() -> None:
            for item in handle.send({"type": "run_message", "request_id": "req_cancel", "payload": {}}):
                events.append(item)
                if item[0] == "frontend_event" and getattr(item[1], "event_type", None) == "run_started":
                    started.set()

        worker = threading.Thread(target=consume, daemon=True)
        worker.start()
        try:
            self.assertTrue(started.wait(timeout=3))
            self.assertEqual(handle.cancel_active_requests(reason="test_cancel"), 1)
            worker.join(timeout=3)
        finally:
            handle.close()

        frontend_events = [item for mode, item in events if mode == "frontend_event"]
        self.assertEqual(frontend_events[-1].event_type, "run_failed")
        self.assertEqual(frontend_events[-1].payload["why"], "request_cancelled")


class DockerAgentRuntimeLauncherMountTest(unittest.TestCase):
    def test_contract_mount_rejects_dangerous_host_path(self) -> None:
        launcher = DockerAgentRuntimeLauncher()

        with self.assertRaises(AgentRuntimeLaunchError) as context:
            launcher._mount_arg(
                {
                    "resource_id": "home",
                    "host_path": str(Path.home()),
                    "container_path": "/volumes/home",
                    "access": "read_only",
                }
            )

        self.assertEqual(context.exception.payload["where"], "sandbox.mounts")
        self.assertEqual(context.exception.payload["why"], "dangerous_host_path")

    def test_contract_mount_allows_safe_volume_path_without_explicit_resource_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            host_path = Path(temp_dir)
            mount = DockerAgentRuntimeLauncher()._mount_arg(
                {
                    "host_path": str(host_path),
                    "container_path": "/volumes/safe_resource/data",
                    "access": "read_only",
                }
            )

        self.assertTrue(mount.endswith(":/volumes/safe_resource/data:ro"))

    def test_contract_mount_rejects_disallowed_container_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(AgentRuntimeLaunchError) as context:
                DockerAgentRuntimeLauncher()._mount_arg(
                    {
                        "resource_id": "unsafe",
                        "host_path": temp_dir,
                        "container_path": "/etc/agent",
                        "access": "read_only",
                    }
                )

        self.assertEqual(context.exception.payload["where"], "sandbox.mounts")
        self.assertEqual(context.exception.payload["why"], "disallowed_container_path")


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


_BRIDGE_SCRIPT_NO_TERMINAL = r'''
import datetime
import json
import sys
import time
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


for line in sys.stdin:
    command = json.loads(line)
    request_id = command.get("request_id")
    emit("run_started", request_id=request_id)
    time.sleep(5)
'''


_BRIDGE_SCRIPT_DELAYED_COMPLETION = r'''
import datetime
import json
import sys
import time
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


for line in sys.stdin:
    command = json.loads(line)
    request_id = command.get("request_id")
    emit("run_started", request_id=request_id)
    time.sleep(1.3)
    emit("run_completed", request_id=request_id)
'''


if __name__ == "__main__":
    unittest.main()
