from __future__ import annotations

from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand
from agent_factory.factory_graph.frontend_bridge.runtime_adapter import (
    FactoryRuntimeAdapter,
    _can_commit_session_messages,
)
from agent_factory.factory_graph.session import FactorySessionConfig, FactorySessionManager
from agent_factory.scheduler_system import SchedulerContractConfig, SchedulerRuntime


class FakeApp:
    def __init__(self, snapshots=None) -> None:
        self.snapshots = snapshots or []

    def get_state_history(self, config):
        return iter(self.snapshots)


class FrontendBridgeRerunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.events = []
        self.manager = FactorySessionManager(FactorySessionConfig(root=Path(self.temp_dir.name)))
        self.record = self.manager.create()
        self.adapter = FactoryRuntimeAdapter(
            emit=self.events.append,
            session_manager=self.manager,
            checkpointer=object(),
        )
        self.adapter.session_record = self.record

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_rerun_from_stage_requires_create_agent_mode(self) -> None:
        self.adapter.mode = "chat"
        self.adapter.rerun_from_stage(
            FactoryFrontendCommand(
                type="rerun_from_stage",
                payload={"stage_id": "resource_and_condition_planning"},
            )
        )

        self.assertEqual(self.events[-1].event_type, "error")
        self.assertIn("create_agent", self.events[-1].message)

    def test_rerun_from_stage_rejects_unknown_stage(self) -> None:
        self.adapter.mode = "create_agent"
        self.adapter.rerun_from_stage(
            FactoryFrontendCommand(
                type="rerun_from_stage",
                payload={"stage_id": "not_a_stage"},
            )
        )

        self.assertEqual(self.events[-1].event_type, "error")
        self.assertIn("unknown stage_id", self.events[-1].message)

    def test_rerun_from_stage_rejects_pending_interrupt(self) -> None:
        self.adapter.mode = "create_agent"
        self.adapter.pending_run = SimpleNamespace()
        self.adapter.rerun_from_stage(
            FactoryFrontendCommand(
                type="rerun_from_stage",
                payload={"stage_id": "resource_and_condition_planning"},
            )
        )

        self.assertEqual(self.events[-1].event_type, "error")
        self.assertIn("interrupt", self.events[-1].message)

    def test_rerun_from_stage_reports_missing_checkpoint(self) -> None:
        self.adapter.mode = "create_agent"
        with patch(
            "agent_factory.factory_graph.frontend_bridge.runtime_adapter.build_factory_graph",
            return_value=FakeApp(snapshots=[]),
        ):
            self.adapter.rerun_from_stage(
                FactoryFrontendCommand(
                    type="rerun_from_stage",
                    payload={"stage_id": "resource_and_condition_planning"},
                )
            )

        self.assertEqual(self.events[-1].event_type, "error")
        self.assertIn("no checkpoint found", self.events[-1].message)

    def test_rerun_from_stage_streams_from_matching_snapshot(self) -> None:
        self.adapter.mode = "create_agent"
        snapshot = SimpleNamespace(
            next=("resource_and_condition_planning",),
            config={"configurable": {"thread_id": "thread-a", "checkpoint_id": "checkpoint-a"}},
            values={"current_stage": "tool_capability_planning"},
        )
        stream_calls = []

        def fake_stream_run(**kwargs):
            stream_calls.append(kwargs)

        with (
            patch(
                "agent_factory.factory_graph.frontend_bridge.runtime_adapter.build_factory_graph",
                return_value=FakeApp(snapshots=[snapshot]),
            ),
            patch.object(FactoryRuntimeAdapter, "_stream_run", side_effect=lambda **kwargs: fake_stream_run(**kwargs)),
        ):
            self.adapter.rerun_from_stage(
                FactoryFrontendCommand(
                    type="rerun_from_stage",
                    payload={"stage_id": "resource_and_condition_planning"},
                )
            )

        self.assertEqual(len(stream_calls), 1)
        self.assertIsNone(stream_calls[0]["stream_input"])
        self.assertEqual(stream_calls[0]["config"], snapshot.config)
        self.assertEqual(stream_calls[0]["initial_final_state"], snapshot.values)
        self.assertEqual(
            stream_calls[0]["run_started_payload"]["rerun_from_stage"],
            "resource_and_condition_planning",
        )

    def test_scheduler_manage_lists_jobs_without_model_tool_call(self) -> None:
        scheduler_runtime = SchedulerRuntime(
            config=SchedulerContractConfig(store_path=str(Path(self.temp_dir.name) / "scheduler.sqlite")),
            owner_type="factory",
            owner_id="test",
        )
        scheduler_runtime.create_job(
            {
                "job_id": "daily_status",
                "schedule_type": "interval",
                "schedule_expr": "60",
                "target": {"target_type": "graph_run", "payload": {"message": "hello"}},
            }
        )
        self.adapter.scheduler_runtime = scheduler_runtime

        self.adapter.scheduler_manage(FactoryFrontendCommand(type="scheduler_manage", payload={"action": "list"}))

        self.assertEqual(self.events[-1].event_type, "scheduler_jobs_listed")
        self.assertEqual(self.events[-1].payload["payload"]["count"], 1)
        self.assertEqual(self.events[-1].payload["payload"]["jobs"][0]["job_id"], "daily_status")

    def test_scheduler_manage_deletes_job_without_model_tool_call(self) -> None:
        scheduler_runtime = SchedulerRuntime(
            config=SchedulerContractConfig(store_path=str(Path(self.temp_dir.name) / "scheduler.sqlite")),
            owner_type="factory",
            owner_id="test",
            event_sink=self.adapter._emit_scheduler_event,
        )
        scheduler_runtime.create_job(
            {
                "job_id": "delete_me",
                "schedule_type": "interval",
                "schedule_expr": "60",
                "target": {"target_type": "graph_run", "payload": {"message": "hello"}},
            }
        )
        self.adapter.scheduler_runtime = scheduler_runtime

        self.adapter.scheduler_manage(
            FactoryFrontendCommand(type="scheduler_manage", payload={"action": "delete", "job_id": "delete_me"})
        )

        self.assertIsNone(scheduler_runtime.store.get_job("delete_me"))
        self.assertEqual(self.events[-1].event_type, "scheduler_job_deleted")

    def test_session_messages_do_not_commit_failed_runs(self) -> None:
        self.assertFalse(
            _can_commit_session_messages(
                {
                    "status": "failed",
                    "messages": [HumanMessage(content="创建一个 agent")],
                }
            )
        )
        self.assertFalse(
            _can_commit_session_messages(
                {
                    "status": "blocked",
                    "messages": [HumanMessage(content="创建一个 agent")],
                }
            )
        )

    def test_session_messages_do_not_commit_incomplete_tool_call_history(self) -> None:
        self.assertFalse(
            _can_commit_session_messages(
                {
                    "status": "running",
                    "messages": [
                        HumanMessage(content="创建一个 agent"),
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "shell_run",
                                    "args": {"command": ["pwd"]},
                                    "id": "call_incomplete",
                                }
                            ],
                        ),
                    ],
                }
            )
        )

    def test_session_messages_can_commit_complete_tool_call_history(self) -> None:
        self.assertTrue(
            _can_commit_session_messages(
                {
                    "status": "running",
                    "messages": [
                        HumanMessage(content="创建一个 agent"),
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "shell_cwd",
                                    "args": {},
                                    "id": "call_complete",
                                }
                            ],
                        ),
                        ToolMessage(content="{}", name="shell_cwd", tool_call_id="call_complete"),
                    ],
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
