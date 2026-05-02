from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_factory.core import EventStatus, FactoryEvent
from agent_factory.factory_runtime import (
    FactoryConfig,
    FactoryMemoryRecord,
    FactoryMemoryStore,
    FactoryRunContext,
    FactoryToolRegistry,
    FactoryTraceStore,
    FactoryWorkspace,
)


class FactoryRuntimeTests(unittest.TestCase):
    def test_workspace_ensure_creates_config_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = FactoryWorkspace.discover(tmpdir)
            config = workspace.ensure()

            self.assertIsInstance(config, FactoryConfig)
            self.assertTrue(workspace.config_path.exists())
            self.assertTrue(workspace.resolve(config.storage.drafts_dir).is_dir())
            self.assertTrue(workspace.resolve("memory").is_dir())
            self.assertTrue(workspace.resolve("traces").is_dir())

    def test_workspace_ensure_is_idempotent_and_loads_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = FactoryWorkspace.discover(tmpdir)
            workspace.ensure()
            original = workspace.config_path.read_text(encoding="utf-8")

            loaded = workspace.ensure()

            self.assertEqual(workspace.config_path.read_text(encoding="utf-8"), original)
            self.assertEqual(loaded.kind, "FactoryConfig")

    def test_factory_config_loads_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            FactoryConfig.default(workspace_name="Demo").save(path)

            config = FactoryConfig.load(path)

            self.assertEqual(config.workspace_name, "Demo")
            self.assertEqual(config.storage.backend, "filesystem")

    def test_memory_store_appends_reads_and_redacts_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "memory" / "factory_memory.jsonl"
            store = FactoryMemoryStore(path)
            store.append(
                FactoryMemoryRecord(
                    run_id="run-001",
                    type="test",
                    summary="secret test",
                    payload={"api_key": "sk-secret", "safe": "ok"},
                )
            )

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("sk-secret", raw)
            records = store.list_recent()
            self.assertEqual(records[0].payload["api_key"], "[REDACTED]")
            self.assertEqual(records[0].payload["safe"], "ok")

    def test_trace_store_appends_events_and_redacts_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "traces" / "factory_runs.jsonl"
            store = FactoryTraceStore(path)
            store.append_event(
                FactoryEvent(
                    run_id="run-001",
                    stage="test",
                    status=EventStatus.COMPLETED,
                    title="Trace test",
                    payload={"authorization": "Bearer secret", "safe": "ok"},
                )
            )

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("Bearer secret", raw)
            events = store.list_events()
            self.assertEqual(events[0]["payload"]["authorization"], "[REDACTED]")

    def test_factory_run_context_uses_isolated_factory_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)

            self.assertTrue(str(context.memory_path).endswith(".agentfactory/memory/factory_memory.jsonl"))
            self.assertTrue(str(context.trace_path).endswith(".agentfactory/traces/factory_runs.jsonl"))
            self.assertTrue(context.drafts_path.is_dir())

    def test_factory_tool_registry_declares_internal_tools(self) -> None:
        tools = {tool.id for tool in FactoryToolRegistry().list_tools()}

        self.assertIn("model.generate_structured", tools)
        self.assertIn("package.write_primitives", tools)
        self.assertIn("trace.record", tools)
        self.assertIn("memory.append", tools)


if __name__ == "__main__":
    unittest.main()
