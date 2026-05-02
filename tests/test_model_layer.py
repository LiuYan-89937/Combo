from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from agent_factory.model import (
    AIMessage,
    AssistantMessage,
    ChatPromptTemplate,
    FakeModelAdapter,
    HumanMessage,
    LLMMessage,
    LLMRequest,
    MessageBuilder,
    MessageFactory,
    MessagesPlaceholder,
    ModelConfig,
    ModelConfigError,
    ModelService,
    OpenAICompatibleChatAdapter,
    PromptTemplate,
    SystemMessage,
    ToolMessage,
    UserMessage,
    messages_to_request,
    normalize_messages,
)


class ModelLayerTests(unittest.TestCase):
    def test_env_loading_reports_missing_required_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "AGENTFACTORY_LLM_PROVIDER=openai_compatible_chat",
                        "AGENTFACTORY_OPENAI_BASE_URL=",
                        "AGENTFACTORY_OPENAI_API_KEY=",
                        "AGENTFACTORY_OPENAI_MODEL=",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ModelConfigError) as context:
                ModelConfig.from_env(env_file=env_file, environ={})

            message = str(context.exception)
            self.assertIn("AGENTFACTORY_OPENAI_BASE_URL", message)
            self.assertIn("AGENTFACTORY_OPENAI_API_KEY", message)
            self.assertIn("AGENTFACTORY_OPENAI_MODEL", message)

    def test_model_config_masks_api_key(self) -> None:
        config = ModelConfig(
            provider="openai_compatible_chat",
            base_url="https://example.test/v1",
            api_key="sk-secret-value",
            model="test-model",
        )

        self.assertNotIn("sk-secret-value", repr(config))
        self.assertNotIn("sk-secret-value", str(config.model_dump()))
        self.assertEqual(config.safe_summary()["api_key"], "**********")

    def test_fake_adapter_and_structured_output(self) -> None:
        async def run() -> None:
            config = ModelConfig(provider="fake")
            adapter = FakeModelAdapter([{"intent": "refund", "confidence": 0.9}])
            service = ModelService.with_adapter(config, adapter)
            result = await service.generate_structured(
                LLMRequest(messages=[LLMMessage(role="user", content="我要退款")])
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data, {"intent": "refund", "confidence": 0.9})
            self.assertEqual(adapter.requests[0].response_format, "json_object")

        asyncio.run(run())

    def test_message_factory_and_builder_create_requests(self) -> None:
        request = (
            MessageBuilder.start()
            .system("You are a customer service agent.")
            .history(
                [
                    MessageFactory.user("我要退款"),
                    ("assistant", "我可以帮你查询退款规则。"),
                    {"role": "user", "content": "订单 123"},
                ]
            )
            .request(response_format="json_object", metadata={"case_id": "case-001"})
        )

        self.assertEqual([message.role for message in request.messages], ["system", "user", "assistant", "user"])
        self.assertEqual(request.response_format, "json_object")
        self.assertEqual(request.metadata, {"case_id": "case-001"})

    def test_direct_message_classes_can_build_requests(self) -> None:
        request = LLMRequest(
            messages=[
                SystemMessage(content="You are a customer service agent."),
                HumanMessage(content="我要退款"),
                AIMessage(content="请提供订单号。"),
                UserMessage(content="订单 123"),
                AssistantMessage(content="我来查询。"),
                ToolMessage(content='{"status": "shipping"}', tool_call_id="call-001"),
            ]
        )

        self.assertEqual(
            [message.role for message in request.messages],
            ["system", "user", "assistant", "user", "assistant", "tool"],
        )
        self.assertEqual(request.messages[-1].tool_call_id, "call-001")

    def test_normalize_messages_and_messages_to_request(self) -> None:
        messages = normalize_messages(
            [
                "hello",
                ("assistant", "hi"),
                {"role": "system", "content": "be concise"},
            ]
        )
        request = messages_to_request(messages, temperature=0.1)

        self.assertEqual([message.role for message in messages], ["user", "assistant", "system"])
        self.assertEqual(request.temperature, 0.1)
        self.assertEqual(request.messages[0].content, "hello")

    def test_prompt_template_detects_missing_variables(self) -> None:
        template = PromptTemplate.from_template("Hello {name}, order {order_id}")

        self.assertEqual(template.format(name="Liu", order_id="123"), "Hello Liu, order 123")
        with self.assertRaises(ValueError) as context:
            template.format(name="Liu")
        self.assertIn("order_id", str(context.exception))

    def test_chat_prompt_template_renders_history_and_request(self) -> None:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "你是客服 Agent，回答风格：{style}"),
                MessagesPlaceholder(variable_name="history", optional=True),
                ("user", "用户问题：{question}"),
            ]
        )

        request = prompt.request(
            style="简洁",
            question="我要退款",
            history=[("assistant", "你好，我是客服。")],
            response_format="json_object",
        )

        self.assertEqual([message.role for message in request.messages], ["system", "assistant", "user"])
        self.assertEqual(request.messages[0].content, "你是客服 Agent，回答风格：简洁")
        self.assertEqual(request.messages[-1].content, "用户问题：我要退款")
        self.assertEqual(request.response_format, "json_object")

    def test_invalid_structured_output_returns_model_error(self) -> None:
        async def run() -> None:
            config = ModelConfig(provider="fake")
            adapter = FakeModelAdapter(["not json"])
            service = ModelService.with_adapter(config, adapter)
            result = await service.generate_structured(
                LLMRequest(messages=[LLMMessage(role="user", content="hello")])
            )

            self.assertFalse(result.ok)
            self.assertIsNotNone(result.error)
            self.assertEqual(result.error.type, "structured_output_parse_error")

        asyncio.run(run())

    def test_openai_compatible_adapter_builds_chat_completions_payload(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["authorization"] = request.headers.get("Authorization")
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "model": "test-model",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": '{"ok": true}'},
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 3,
                        "total_tokens": 13,
                    },
                },
            )

        async def run() -> None:
            config = ModelConfig(
                provider="openai_compatible_chat",
                base_url="https://example.test/v1/",
                api_key="sk-test-key",
                model="test-model",
                temperature=0.1,
                max_output_tokens=128,
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = OpenAICompatibleChatAdapter(config, client=client)
                response = await adapter.generate(
                    LLMRequest(
                        messages=[LLMMessage(role="user", content="hello")],
                        response_format="json_object",
                    )
                )

            self.assertTrue(response.ok)
            self.assertEqual(response.content, '{"ok": true}')
            self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
            self.assertEqual(captured["authorization"], "Bearer sk-test-key")
            self.assertEqual(
                captured["payload"],
                {
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "temperature": 0.1,
                    "max_tokens": 128,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                },
            )

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
