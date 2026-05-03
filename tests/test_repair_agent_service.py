from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ruamel.yaml import YAML

from agent_factory.application import (
    CreateAgentRequest,
    CreateAgentService,
    RepairAgentRequest,
    RepairAgentService,
    RunAgentService,
    RunAgentServiceRequest,
)
from tests.test_factory_agent import service_with_responses, valid_primitives_payload


class RepairAgentServiceTests(unittest.TestCase):
    def test_repair_context_binary_ref_and_rerun_same_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
            binary_path = root / "customer_ops.sqlite3"
            binary_path.write_bytes(b"SQLite format 3\x00\x8d\x00not utf8")
            _append_binary_context_source(package_path, binary_path)

            failed = RunAgentService(
                model_service=service_with_responses(["不会执行到模型"])
            ).run_agent(
                RunAgentServiceRequest(
                    target=str(package_path),
                    user_input="现在数据库有什么内容",
                )
            )
            self.assertFalse(failed.ok)
            self.assertIn("utf-8", failed.result.error.message)

            repaired = RepairAgentService(
                model_service=service_with_responses(["现在可以读取工具资源描述。"])
            ).repair_agent(
                RepairAgentRequest(
                    target=str(package_path),
                    user_input="现在数据库有什么内容",
                )
            )

            self.assertEqual(repaired.status, "repaired", repaired.reason)
            self.assertIsNotNone(repaired.candidate_path)
            self.assertEqual(repaired.rerun_result.status, "completed")
            self.assertEqual(repaired.validation_report.ok, True)
            context = YAML(typ="safe").load((repaired.candidate_path / "context.yaml").read_text())
            source = next(item for item in context["sources"] if item["id"] == "customer_ops_db")
            self.assertIsNone(source["ref"])
            self.assertIn(str(binary_path), source["content"])
            self.assertFalse(source["visible_to_model"])
            self.assertTrue(source["visible_to_tools"])


def _generated_package(start_path: Path) -> Path:
    service = CreateAgentService(model_service=service_with_responses([valid_primitives_payload()]))
    result = service.create_agent(
        CreateAgentRequest(prompt="创建客服 Agent", start_path=start_path, stream=False)
    )
    assert result.output_path is not None
    return result.output_path


def _append_binary_context_source(package_path: Path, binary_path: Path) -> None:
    yaml = YAML()
    path = package_path / "context.yaml"
    data = yaml.load(path.read_text(encoding="utf-8"))
    data.setdefault("sources", []).append(
        {
            "id": "customer_ops_db",
            "type": "static",
            "content": None,
            "ref": str(binary_path),
            "visible_to_model": False,
            "visible_to_tools": True,
            "hidden_from_model": [],
        }
    )
    with path.open("w", encoding="utf-8") as file:
        yaml.dump(data, file)


if __name__ == "__main__":
    unittest.main()
