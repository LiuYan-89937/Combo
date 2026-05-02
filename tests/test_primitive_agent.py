from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agent_factory.agent import PrimitiveAgent, PrimitiveAgentError
from agent_factory.model import FakeModelAdapter, ModelConfig, ModelService
from tests.test_building_primitives import valid_primitives, write_package


class PrimitiveAgentTests(unittest.TestCase):
    def test_build_request_from_primitives(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                write_package(root, valid_primitives())
                service = ModelService.with_adapter(
                    ModelConfig(provider="fake"),
                    FakeModelAdapter([{"intent": "refund", "answer": "请提供订单号。"}]),
                )
                agent = PrimitiveAgent.from_package(root, model_service=service)

                result = await agent.run(
                    "我要退款",
                    history=[("assistant", "你好，我是客服。")],
                    context_items=["退款规则：用户需要提供订单号。"],
                    metadata={"test": "primitive-agent"},
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.structured_data, {"intent": "refund", "answer": "请提供订单号。"})
            self.assertEqual(result.request.response_format, "json_object")
            self.assertEqual([message.role for message in result.request.messages], ["system", "assistant", "system", "user"])
            self.assertIn("Persona: 温和、专业的客服 Agent", result.request.messages[0].content)
            self.assertIn("Output contract: return valid json_object", result.request.messages[0].content)
            self.assertEqual(result.request.metadata["agent_name"], "customer-service-agent")

        asyncio.run(run())

    def test_from_package_rejects_invalid_primitives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data = valid_primitives()
            data.pop("guardrails.yaml")
            write_package(root, data)
            service = ModelService.with_adapter(ModelConfig(provider="fake"), FakeModelAdapter(["ok"]))

            with self.assertRaises(PrimitiveAgentError):
                PrimitiveAgent.from_package(root, model_service=service)


if __name__ == "__main__":
    unittest.main()

