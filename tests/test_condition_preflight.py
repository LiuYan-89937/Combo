from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from agent_factory.factory.environment import EnvironmentProbeRunner
from agent_factory.factory.package_artifacts import PackageArtifactGenerator
from agent_factory.factory.package_writer import PackageWriter
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.factory_runtime.production import FactoryProductionRuntime
from agent_factory.tools import ControlledShellRunner
from agent_factory.tools.router import ToolInvocation, ToolRouter
from tests.test_factory_agent import (
    service_with_responses,
    valid_primitives_payload,
)


class ConditionPreflightTests(unittest.TestCase):
    def test_sqlite_probe_discovers_schema_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "customer_ops.sqlite3"
            _create_sqlite_fixture(db_path)
            primitives = _sqlite_primitives(db_path)

            _environment, contracts, readiness = EnvironmentProbeRunner().probe(
                primitives,
                requirement=f"管理本地 SQLite 数据库 {db_path}",
                start_path=tmpdir,
            )

            self.assertEqual(readiness.status, "ready")
            resource = contracts.resources[0]
            self.assertEqual(resource.type, "sqlite")
            self.assertEqual(resource.status, "ready")
            table = resource.sqlite_tables[0]
            self.assertEqual(table.name, "customer_tickets")
            self.assertIn("ticket_id", table.primary_keys)
            self.assertIn("created_at", table.required_columns)
            self.assertIn("updated_at", table.required_columns)
            self.assertTrue(table.check_constraints)

    def test_missing_resource_returns_needs_user_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.sqlite3"
            primitives = _sqlite_primitives(missing)

            _environment, contracts, readiness = EnvironmentProbeRunner().probe(
                primitives,
                requirement=f"管理本地 SQLite 数据库 {missing}",
                start_path=tmpdir,
            )

            self.assertEqual(contracts.resources[0].status, "missing")
            self.assertEqual(readiness.status, "needs_user_input")
            self.assertIn("replace_resource_path", {option.id for option in readiness.options})

    def test_controlled_shell_runner_rejects_non_allowlisted_command(self) -> None:
        runner = ControlledShellRunner(allowed_commands={"sqlite3"})

        result = runner.run(["rm", "-rf", "/tmp/nope"])

        self.assertEqual(result.status, "rejected")
        self.assertIn("not allowlisted", result.error or "")

    def test_factory_graph_writes_condition_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()])
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "completed", state.error)
            assert state.package_path is not None
            self.assertTrue((state.package_path / "environment.yaml").exists())
            self.assertTrue((state.package_path / "resource_contracts.yaml").exists())
            self.assertTrue((state.package_path / "readiness.yaml").exists())
            self.assertIn("plan_capability_preconditions", state.stage_history)
            self.assertIn("probe_environment", state.stage_history)

    def test_low_risk_tool_can_run_when_its_own_test_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = _two_tool_primitives()
            package_path = root / "package"
            PackageWriter().write_primitives(package_path, primitives)
            generator = PackageArtifactGenerator()
            generator.generate_tool_scripts(package_path, primitives)
            generator.generate_mcp_bindings(package_path, primitives)
            generator.generate_harness_scenarios(package_path, primitives)
            generator.generate_package_specs(package_path, primitives)
            reports = package_path / "generated" / "reports"
            reports.mkdir(parents=True, exist_ok=True)
            (reports / "tool_tests.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "per_tool_status": {
                            "order_query": "passed",
                            "generic_lookup": "failed",
                        },
                    }
                ),
                encoding="utf-8",
            )

            route = ToolRouter(package_path).route(
                ToolInvocation(tool_id="order_query", arguments={"query": "订单 123"})
            )

            self.assertFalse(hasattr(route, "interrupt_type"))
            self.assertEqual(route.tool_id, "order_query")


def _create_sqlite_fixture(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            """
            CREATE TABLE customer_tickets (
              ticket_id TEXT PRIMARY KEY,
              customer_name TEXT NOT NULL,
              channel TEXT NOT NULL,
              title TEXT NOT NULL,
              description TEXT NOT NULL,
              status TEXT NOT NULL CHECK (status IN ('open', 'pending', 'resolved', 'closed')),
              priority TEXT NOT NULL,
              assignee TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )


def _sqlite_primitives(db_path: Path):
    payload = valid_primitives_payload()
    payload["knowledge"]["sources"] = [
        {
            "id": "customer_ops_sqlite",
            "type": "file",
            "ref": str(db_path),
            "visible_to_model": False,
            "visible_to_tools": True,
            "access_mode": "read_write",
            "sandbox_required": True,
        }
    ]
    payload["knowledge"]["inject_as"] = "tool"
    return PackageWriter().validator.loader.load_primitives(_write_primitives_payload(payload))


def _two_tool_primitives():
    payload = valid_primitives_payload()
    payload["toolsets"]["toolsets"][0]["exposed_tools"] = ["order_query", "generic_lookup"]
    return PackageWriter().validator.loader.load_primitives(_write_primitives_payload(payload))


def _write_primitives_payload(payload: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    primitives = __import__("agent_factory.specs", fromlist=["AgentPackagePrimitives"]).AgentPackagePrimitives.model_validate(payload)
    PackageWriter().write_primitives(root, primitives)
    return root


if __name__ == "__main__":
    unittest.main()
