from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter import FactoryRuntimeAdapter
from agent_factory.factory_graph.session import FactorySessionConfig, FactorySessionManager


class CreateAgentBridgeTest(unittest.TestCase):
    def test_create_agent_mode_uses_host_runtime_not_agent_package_runtime(self) -> None:
        with TemporaryDirectory() as tmp:
            events = []
            package_runtime = _FakeAgentPackageRuntime()
            create_agent_runtime = _FakeCreateAgentRuntime()
            adapter = FactoryRuntimeAdapter(
                emit=events.append,
                session_manager=FactorySessionManager(FactorySessionConfig(root=Path(tmp))),
                agent_package_runtime=package_runtime,
                create_agent_runtime=create_agent_runtime,
            )

            adapter.handle(FactoryFrontendCommand(type="start_session", request_id="start"))
            adapter.handle(FactoryFrontendCommand(type="set_mode", request_id="mode", mode="create_agent"))
            adapter.handle(FactoryFrontendCommand(type="send_message", request_id="send", message="build an agent"))

        self.assertEqual(package_runtime.stream_calls, [])
        self.assertEqual(len(create_agent_runtime.stream_calls), 1)
        mode_events = [item for item in events if item.event_type == "mode_changed"]
        self.assertEqual(mode_events[-1].payload["graph_id"], "create_agent_react")
        self.assertNotIn("package_id", mode_events[-1].payload)
        completed = [item for item in events if item.event_type == "run_completed"]
        self.assertEqual(completed[-1].graph_id, "create_agent_react")

    def test_create_agent_interrupt_resumes_host_runtime(self) -> None:
        with TemporaryDirectory() as tmp:
            events = []
            create_agent_runtime = _FakeCreateAgentRuntime(interrupt=True)
            adapter = FactoryRuntimeAdapter(
                emit=events.append,
                session_manager=FactorySessionManager(FactorySessionConfig(root=Path(tmp))),
                agent_package_runtime=_FakeAgentPackageRuntime(),
                create_agent_runtime=create_agent_runtime,
            )

            adapter.handle(FactoryFrontendCommand(type="start_session", request_id="start"))
            adapter.handle(FactoryFrontendCommand(type="set_mode", request_id="mode", mode="create_agent"))
            adapter.handle(FactoryFrontendCommand(type="send_message", request_id="send", message="build an agent"))
            adapter.handle(FactoryFrontendCommand(type="send_message", request_id="blocked", message="new message"))
            adapter.handle(
                FactoryFrontendCommand(
                    type="resume_interrupt",
                    request_id="resume",
                    payload={"answer": "continue"},
                )
            )

        self.assertEqual(len(create_agent_runtime.stream_calls), 1)
        self.assertEqual(len(create_agent_runtime.resume_calls), 1)
        errors = [item for item in events if item.event_type == "error"]
        self.assertEqual(errors[-1].message, "cannot send a new message while an interrupt is pending")


class _FakeAgentPackageRuntime:
    def __init__(self) -> None:
        self.stream_calls = []

    def set_emit(self, emit) -> None:
        self.emit = emit

    def stream(self, *args, **kwargs):
        self.stream_calls.append((args, kwargs))
        raise AssertionError("create-agent must not use AgentPackageRuntime.stream")

    def cancel_active_requests(self, *, reason: str) -> int:
        return 0


class _FakeCreateAgentRuntime:
    def __init__(self, *, interrupt: bool = False) -> None:
        self.interrupt = interrupt
        self.stream_calls = []
        self.resume_calls = []

    def stream(self, *, user_input: str, session_id: str | None, request_id: str | None):
        self.stream_calls.append(
            {"user_input": user_input, "session_id": session_id, "request_id": request_id}
        )
        events = [_frontend("run_started", session_id=session_id, request_id=request_id)]
        if self.interrupt:
            events.append(
                _frontend(
                    "interrupt_requested",
                    session_id=session_id,
                    request_id=request_id,
                    payload={"type": "create_agent_question", "message": "question"},
                )
            )
        else:
            events.append(_frontend("run_completed", session_id=session_id, request_id=request_id))
        return SimpleNamespace(session_id=session_id, events=iter(("frontend_event", item) for item in events))

    def resume_stream(self, *, session_id: str, resume_payload: dict, request_id: str | None):
        self.resume_calls.append(
            {"session_id": session_id, "resume_payload": resume_payload, "request_id": request_id}
        )
        return SimpleNamespace(
            session_id=session_id,
            events=iter(
                [
                    (
                        "frontend_event",
                        _frontend("run_completed", session_id=session_id, request_id=request_id),
                    )
                ]
            ),
        )


def _frontend(event_type: str, *, session_id: str | None, request_id: str | None, payload: dict | None = None):
    return event(
        event_type,  # type: ignore[arg-type]
        request_id=request_id,
        session_id=session_id,
        mode="create_agent",
        graph_id="create_agent_react",
        payload=payload or {},
    )


if __name__ == "__main__":
    unittest.main()
