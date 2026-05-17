from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent_factory.factory_graph.sandbox_runtime import PreparedSandbox, HarnessExecutionResult
from agent_factory.factory_graph.schemas import (
    ArtifactManifestEntry,
    HarnessContractDecision,
    HarnessReportError,
)
from agent_factory.factory_graph.stage_subgraphs.harness_generation_and_test import (
    run_harness_generation_and_test_subgraph,
)


class HarnessGenerationAndTestTest(unittest.TestCase):
    def test_docker_missing_blocks_without_local_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([_valid_decision()], docker_path=None)

                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["harness_report"]["status"], "blocked")
                self.assertEqual(result["harness_report"]["errors"][0]["why"], "docker_not_available")
                self.assertEqual(result["harness_report"]["sandbox_backend"], "docker")
                self.assertTrue(Path(result["harness_generation"]["report_path"]).exists())

    def test_rejects_broad_host_mount(self) -> None:
        invalid = _valid_decision().model_dump(mode="json")
        invalid["host_interaction"]["volumes"].append(
            {
                "resource_id": "unsafe_home",
                "host_path": str(Path.home()),
                "container_path": "/volumes/unsafe_home",
                "access": "read_only",
                "purpose": "unsafe broad host path",
                "authorization_source": "user_authorized",
            }
        )
        decision = HarnessContractDecision.model_validate(invalid)
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([decision, decision, decision], docker_path="/usr/bin/docker")

                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["harness_report"]["status"], "failed")
                self.assertIn("invalid_mount", {item["why"] for item in result["harness_report"]["errors"]})

    def test_rejects_package_mount_when_not_read_only(self) -> None:
        invalid = _valid_decision().model_dump(mode="json")
        invalid["host_interaction"]["mounts"][0]["access"] = "read_write"
        decision = HarnessContractDecision.model_validate(invalid)
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([decision, decision, decision], docker_path="/usr/bin/docker")

                self.assertEqual(result["status"], "failed")
                self.assertIn("invalid_mount_access", {item["why"] for item in result["harness_report"]["errors"]})

    def test_rejects_localhost_for_host_service(self) -> None:
        invalid = _valid_decision().model_dump(mode="json")
        invalid["runtime_environment"]["network_policy"] = {"mode": "declared_services", "allowed_hosts": ["localhost"]}
        invalid["host_interaction"]["services"] = [
            {
                "service_id": "db",
                "kind": "host_port",
                "endpoint": "localhost:3306",
                "ports": [3306],
                "health_check": {},
            }
        ]
        decision = HarnessContractDecision.model_validate(invalid)
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([decision, decision, decision], docker_path="/usr/bin/docker")

                self.assertEqual(result["status"], "failed")
                self.assertIn("invalid_host_endpoint", {item["why"] for item in result["harness_report"]["errors"]})

    def test_validation_observation_allows_revision_before_docker_prepare(self) -> None:
        invalid = _valid_decision().model_dump(mode="json")
        invalid["runtime_environment"]["network_policy"] = {"mode": "declared_services", "allowed_hosts": []}
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions(
                    [HarnessContractDecision.model_validate(invalid), _valid_decision()],
                    docker_path=None,
                )

                self.assertEqual(result["harness_revision_attempt"], 2)
                self.assertEqual(result["harness_report"]["status"], "blocked")
                self.assertEqual(result["harness_report"]["errors"][0]["why"], "docker_not_available")

    def test_default_network_allows_dependency_install_contract(self) -> None:
        decision = _valid_decision(python_requirements=["requests>=2"])
        runtime = _FakeRuntime([HarnessExecutionResult(status="passed")])
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([decision], runtime=runtime)

                self.assertEqual(result["status"], "running")
                self.assertEqual(result["harness_report"]["status"], "passed")
                self.assertEqual(runtime.run_count, 1)

    def test_dependency_install_requires_declared_network_access(self) -> None:
        decision = _valid_decision(python_requirements=["requests>=2"], network_mode="none")
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([decision, decision, decision], docker_path="/usr/bin/docker")

                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["harness_report"]["status"], "failed")
                self.assertIn("network_policy_invalid", {item["why"] for item in result["harness_report"]["errors"]})

    def test_dependency_failure_observation_allows_contract_revision_and_rerun(self) -> None:
        first = _valid_decision()
        second = _valid_decision(
            python_requirements=["missing-package>=1"],
            network_mode="declared_services",
            allowed_hosts=["pypi.org", "files.pythonhosted.org"],
        )
        runtime = _FakeRuntime(
            [
                HarnessExecutionResult(
                    status="failed",
                    errors=[
                        HarnessReportError(
                            where="tool_test.ledger_lookup",
                            why="dependency_missing",
                            message="Tool dependency is missing: No module named 'missing_package'",
                            evidence={"missing_dependency": "missing_package"},
                        )
                    ],
                ),
                HarnessExecutionResult(status="passed"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([first, second], runtime=runtime)

                self.assertEqual(result["status"], "running")
                self.assertEqual(result["harness_revision_attempt"], 2)
                self.assertEqual(result["harness_report"]["status"], "passed")
                self.assertEqual(runtime.run_count, 2)

    def test_tool_code_failure_is_reported_for_repair_without_revision_loop(self) -> None:
        runtime = _FakeRuntime(
            [
                HarnessExecutionResult(
                    status="failed",
                    errors=[
                        HarnessReportError(
                            where="tool_test.ledger_lookup",
                            why="tool_compile_failed",
                            message="Tool code failed to compile.",
                            evidence={},
                        )
                    ],
                )
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with _chdir(temp_dir):
                result = _run_with_decisions([_valid_decision()], runtime=runtime)

                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["harness_report"]["status"], "failed")
                self.assertEqual(result["harness_revision_attempt"], 1)
                self.assertEqual(runtime.run_count, 1)


class _FakeModel:
    def bind_tools(self, _tools):
        return self

    def bind(self, **_kwargs):
        return self

    def invoke(self, _prompt_value):
        return AIMessage(content="harness contracts ready")


def _run_with_decisions(
    decisions: list[HarnessContractDecision],
    *,
    docker_path: str | None = None,
    runtime: object | None = None,
):
    queue = list(decisions)

    def fake_call_structured_model(**_kwargs):
        if not queue:
            raise AssertionError("unexpected harness decision call")
        return queue.pop(0)

    with patch("agent_factory.factory_graph.stage_subgraphs.harness_generation_and_test.get_main_model", return_value=_FakeModel()):
        with patch(
            "agent_factory.factory_graph.stage_subgraphs.harness_generation_and_test.call_structured_model",
            side_effect=fake_call_structured_model,
        ):
            if runtime is not None:
                with patch("agent_factory.factory_graph.stage_subgraphs.harness_generation_and_test.runtime_for_backend", return_value=runtime):
                    return run_harness_generation_and_test_subgraph(_base_state())
            with patch("agent_factory.factory_graph.sandbox_runtime.shutil.which", return_value=docker_path):
                return run_harness_generation_and_test_subgraph(_base_state())


def _valid_decision(
    *,
    python_requirements: list[str] | None = None,
    network_mode: str = "default_allow",
    allowed_hosts: list[str] | None = None,
) -> HarnessContractDecision:
    return HarnessContractDecision.model_validate(
        {
            "action": "contracts_ready",
            "runtime_environment": {
                "backend": "docker",
                "image": "python:3.11-slim",
                "workdir": "/workdir",
                "network_policy": {"mode": network_mode, "allowed_hosts": allowed_hosts or []},
                "limits": {"timeout_seconds": 120, "memory_mb": 512, "cpu": 1},
                "env_policy": {"allowed": [], "injected": {}},
                "dependency_policy": {"install_mode": "sandbox_only", "allow_runtime_install": False},
            },
            "host_interaction": {
                "mounts": [
                    {
                        "resource_id": "agent_package",
                        "host_path": ".agentfactory/packages/run_1",
                        "container_path": "/package",
                        "access": "read_only",
                        "purpose": "AgentPackage draft",
                        "authorization_source": "system_required",
                    },
                    {
                        "resource_id": "resources",
                        "host_path": ".agentfactory/packages/run_1",
                        "container_path": "/resources",
                        "access": "read_only",
                        "purpose": "Generated resources file directory",
                        "authorization_source": "system_required",
                    },
                    {
                        "resource_id": "artifacts",
                        "host_path": ".agentfactory/harness/run_1/artifacts",
                        "container_path": "/artifacts",
                        "access": "read_write",
                        "purpose": "Harness artifacts",
                        "authorization_source": "system_required",
                    },
                    {
                        "resource_id": "workdir",
                        "host_path": ".agentfactory/harness/run_1/artifacts/workdir",
                        "container_path": "/workdir",
                        "access": "read_write",
                        "purpose": "Sandbox temporary workdir",
                        "authorization_source": "system_required",
                    },
                ],
                "volumes": [],
                "services": [],
                "secrets": [],
                "host_tool_proxies": [],
            },
            "dependency_plan": {
                "python_requirements": python_requirements or [],
                "system_packages": [],
                "install_mode": "sandbox_only",
            },
            "execution_plan": {
                "scenarios": [],
                "tool_tests": [],
                "runtime_assertions": [],
                "timeout_policy": {"timeout_seconds": 120, "memory_mb": 512, "cpu": 1},
            },
            "revision_notes": ["test"],
            "blocked_reason": "",
        }
    )


class _FakeRuntime:
    def __init__(self, results: list[HarnessExecutionResult]) -> None:
        self.results = list(results)
        self.run_count = 0

    def prepare(self, **kwargs):
        return PreparedSandbox(
            runtime_environment=kwargs["runtime_environment"],
            host_interaction=kwargs["host_interaction"],
            dependency_plan=kwargs["dependency_plan"],
            package_root=str(kwargs["package_root"]),
            resources_path=str(kwargs["resources_path"]),
            artifacts_root=str(kwargs["artifacts_root"]),
            workdir_host_path=str(Path(kwargs["artifacts_root"]) / "workdir"),
        )

    def run(self, *, sandbox, plan):
        self.run_count += 1
        if not self.results:
            raise AssertionError("unexpected sandbox run")
        return self.results.pop(0)

    def collect_artifacts(self, *, sandbox):
        return [ArtifactManifestEntry(path="sandbox_result.json", bytes=2)]

    def cleanup(self, *, sandbox):
        return None


def _base_state() -> dict:
    return {
        "factory_run_id": "run_1",
        "status": "running",
        "assembly_spec": {"agent": {"id": "ledger_agent"}, "runtime": {"pattern_id": "react_agent"}},
        "package_materialization_plan": {"version": "package_materialization.v0", "factory_run_id": "run_1"},
        "package_generation": {
            "status": "complete",
            "package_root": ".agentfactory/packages/run_1",
            "manifest_path": ".agentfactory/packages/run_1/agent_package.json",
            "report_path": ".agentfactory/packages/run_1/package_report.json",
        },
        "resource_condition_plan": {
            "status": "complete",
            "resources": {"ledger_file": "/tmp/ledger.json"},
        },
        "stage_log": [],
        "errors": [],
    }


class _chdir:
    def __init__(self, path: str):
        self.path = path
        self.old = os.getcwd()

    def __enter__(self):
        os.chdir(self.path)
        Path(".agentfactory/packages/run_1").mkdir(parents=True, exist_ok=True)
        Path(".agentfactory/packages/run_1/resources.json").write_text(
            '{"version":"factory_resources.v0","resources":{"ledger_file":"/tmp/ledger.json"}}',
            encoding="utf-8",
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        os.chdir(self.old)
