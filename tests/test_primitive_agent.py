from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage

from agent_factory.agent import PrimitiveAgent, PrimitiveAgentError
from agent_factory.runtime.langchain_chat import ScriptedRuntimeChatModel
from tests.test_building_primitives import valid_primitives, write_package


class PrimitiveAgentTests(unittest.TestCase):
    def test_build_request_from_primitives(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                write_package(root, valid_primitives())
                chat_model = ScriptedRuntimeChatModel(
                    responses=['{"intent": "refund", "answer": "请提供订单号。"}']
                )
                agent = PrimitiveAgent.from_package(root, chat_model=chat_model)

                result = await agent.run(
                    "我要退款",
                    history=[AIMessage(content="你好，我是客服。")],
                    context_items=["退款规则：用户需要提供订单号。"],
                    metadata={"test": "primitive-agent"},
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.structured_data, {"intent": "refund", "answer": "请提供订单号。"})
            self.assertEqual(result.request.response_format, "json_object")
            self.assertEqual([message.type for message in result.request.messages], ["system", "ai", "system", "human"])
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
            chat_model = ScriptedRuntimeChatModel(responses=["ok"])

            with self.assertRaises(PrimitiveAgentError):
                PrimitiveAgent.from_package(root, chat_model=chat_model)


if __name__ == "__main__":
    unittest.main()
