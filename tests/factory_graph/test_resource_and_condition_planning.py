from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning import (
    RESOURCE_MODEL_NODE,
    _route_after_validation,
    _validate_ready_decision,
)


class ResourceAndConditionPlanningTest(unittest.TestCase):
    def test_docker_unavailable_blocks_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning._docker_blocking_errors",
                return_value=["docker_not_available: Docker CLI was not found"],
            ):
                result = _validate_ready_decision(
                    resource_draft={},
                    sandbox_contract_draft=_sandbox_contract(),
                    project_root=Path(temp_dir),
                )

        self.assertEqual(result.status, "blocked")
        self.assertIn("docker_not_available", result.errors[0])

    def test_rejects_unconverted_host_resource_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning._docker_blocking_errors",
                return_value=[],
            ), patch(
                "agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning._docker_image_error",
                return_value=None,
            ):
                result = _validate_ready_decision(
                    resource_draft={"audit_log": {"path": "/Users/liuyan/data/audit.log"}},
                    sandbox_contract_draft=_sandbox_contract(),
                    project_root=Path(temp_dir),
                )

        self.assertEqual(result.status, "needs_input")
        self.assertTrue(any("host absolute path" in item for item in result.errors))

    def test_rejects_host_loopback_resource_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning._docker_blocking_errors",
                return_value=[],
            ), patch(
                "agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning._docker_image_error",
                return_value=None,
            ):
                result = _validate_ready_decision(
                    resource_draft={"service": {"endpoint": "127.0.0.1:3306"}},
                    sandbox_contract_draft=_sandbox_contract(),
                    project_root=Path(temp_dir),
                )

        self.assertEqual(result.status, "needs_input")
        self.assertTrue(any("host loopback" in item for item in result.errors))

    def test_validates_sandbox_visible_resources_and_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            host_file = Path(temp_dir) / "audit.log"
            host_file.write_text("", encoding="utf-8")
            contract = _sandbox_contract()
            contract["mounts"] = [
                {
                    "resource_id": "audit_log",
                    "host_path": str(host_file),
                    "container_path": "/volumes/audit_log/audit.log",
                    "access": "read_write",
                    "purpose": "Provide audit log file to the generated agent.",
                    "authorization_source": "user_authorized",
                }
            ]
            contract["services"] = [
                {
                    "service_id": "db",
                    "kind": "host_port",
                    "endpoint": "host.docker.internal:3306",
                    "ports": [3306],
                    "purpose": "Access a host service from the sandbox.",
                }
            ]
            with patch(
                "agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning._docker_blocking_errors",
                return_value=[],
            ), patch(
                "agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning._docker_image_error",
                return_value=None,
            ):
                result = _validate_ready_decision(
                    resource_draft={
                        "audit_log": {"path": "/volumes/audit_log/audit.log"},
                        "db": {"endpoint": "host.docker.internal:3306"},
                    },
                    sandbox_contract_draft=contract,
                    project_root=Path(temp_dir),
                )

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.validated_resources["audit_log"]["path"], "/volumes/audit_log/audit.log")

    def test_continue_checking_routes_back_to_resource_model(self) -> None:
        route = _route_after_validation(
            {
                "resource_condition_plan": {
                    "status": "collecting",
                    "validation_result": {"status": "collecting"},
                }
            }
        )

        self.assertEqual(route, RESOURCE_MODEL_NODE)

    def test_rejects_invalid_volume_paths_after_schema_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            host_file = Path(temp_dir) / "volume-data"
            host_file.write_text("data", encoding="utf-8")
            contract = _sandbox_contract()
            contract["volumes"] = [
                {
                    "resource_id": "unsafe_volume",
                    "host_path": str(host_file),
                    "container_path": "/tmp/unsafe_volume",
                    "access": "read_only",
                    "purpose": "Invalid container path should be rejected.",
                    "authorization_source": "user_authorized",
                }
            ]
            with patch(
                "agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning._docker_blocking_errors",
                return_value=[],
            ), patch(
                "agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning._docker_image_error",
                return_value=None,
            ):
                result = _validate_ready_decision(
                    resource_draft={"unsafe_volume": {"path": "/tmp/unsafe_volume"}},
                    sandbox_contract_draft=contract,
                    project_root=Path(temp_dir),
                )

        self.assertEqual(result.status, "needs_input")
        self.assertTrue(any("volume unsafe_volume container_path" in item for item in result.errors))


def _sandbox_contract() -> dict:
    return {
        "version": "sandbox_contract.v0",
        "backend": "docker",
        "image": "python:3.12-slim",
        "workdir": "/workdir",
        "network_policy": {"mode": "default_allow"},
        "mounts": [],
        "services": [],
        "secrets": [],
        "env": {},
        "volumes": [],
    }
