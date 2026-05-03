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

    def test_structured_output_retries_empty_content(self) -> None:
        async def run() -> None:
            config = ModelConfig(provider="fake")
            adapter = FakeModelAdapter(["", {"ok": True}])
            service = ModelService.with_adapter(config, adapter)
            result = await service.generate_structured(
                LLMRequest(messages=[LLMMessage(role="user", content="return json")])
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data, {"ok": True})
            self.assertEqual(len(adapter.requests), 2)

        asyncio.run(run())

    def test_structured_output_empty_content_exhaustion_returns_error(self) -> None:
        async def run() -> None:
            config = ModelConfig(provider="fake")
            adapter = FakeModelAdapter(["", "", ""])
            service = ModelService.with_adapter(config, adapter)
            result = await service.generate_structured(
                LLMRequest(messages=[LLMMessage(role="user", content="return json")]),
                max_empty_content_retries=1,
            )

            self.assertFalse(result.ok)
            self.assertIsNotNone(result.error)
            self.assertEqual(result.error.type, "structured_output_empty_content")
            self.assertTrue(result.error.retryable)
            self.assertEqual(len(adapter.requests), 2)

        asyncio.run(run())

    def test_structured_output_extracts_json_from_markdown_fence(self) -> None:
        async def run() -> None:
            config = ModelConfig(provider="fake")
            adapter = FakeModelAdapter(['```json\n{"ok": true, "name": "小美"}\n```'])
            service = ModelService.with_adapter(config, adapter)
            result = await service.generate_structured(
                LLMRequest(messages=[LLMMessage(role="user", content="hello")])
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data, {"ok": True, "name": "小美"})

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

    def test_openai_compatible_adapter_builds_json_schema_payload(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
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
                },
            )

        async def run() -> None:
            config = ModelConfig(
                provider="openai_compatible_chat",
                base_url="https://example.test/v1",
                api_key="sk-test-key",
                model="test-model",
            )
            schema = {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            }
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = OpenAICompatibleChatAdapter(config, client=client)
                await adapter.generate(
                    LLMRequest(
                        messages=[LLMMessage(role="user", content="hello")],
                        response_format="json_schema",
                        json_schema=schema,
                        json_schema_name="TestSchema",
                    )
                )

            payload = captured["payload"]
            self.assertEqual(
                payload["response_format"],
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "TestSchema",
                        "schema": schema,
                        "strict": True,
                    },
                },
            )

        asyncio.run(run())

    def test_deepseek_adapter_uses_json_object_for_schema_requests(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "model": "deepseek-v4-pro",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": '{"ok": true}'},
                        }
                    ],
                },
            )

        async def run() -> None:
            config = ModelConfig(
                provider="openai_compatible_chat",
                base_url="https://api.deepseek.com",
                api_key="sk-test-key",
                model="deepseek-v4-pro",
            )
            schema = {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            }
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = OpenAICompatibleChatAdapter(config, client=client)
                await adapter.generate(
                    LLMRequest(
                        messages=[LLMMessage(role="user", content="return json")],
                        response_format="json_schema",
                        json_schema=schema,
                        json_schema_name="TestSchema",
                    )
                )

            payload = captured["payload"]
            self.assertEqual(payload["response_format"], {"type": "json_object"})
            self.assertEqual(payload["thinking"], {"type": "enabled"})
            self.assertNotIn("json_schema", payload["response_format"])

        asyncio.run(run())

    def test_request_can_override_model_and_thinking(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": '{"ok": true}'},
                        }
                    ],
                },
            )

        async def run() -> None:
            config = ModelConfig(
                provider="openai_compatible_chat",
                base_url="https://api.deepseek.com",
                api_key="sk-test-key",
                model="deepseek-v4-pro",
                thinking="enabled",
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = OpenAICompatibleChatAdapter(config, client=client)
                await adapter.generate(
                    LLMRequest(
                        messages=[LLMMessage(role="user", content="return json")],
                        model="deepseek-v4-flash",
                        thinking="disabled",
                        response_format="json_object",
                    )
                )

            payload = captured["payload"]
            self.assertEqual(payload["model"], "deepseek-v4-flash")
            self.assertEqual(payload["thinking"], {"type": "disabled"})

        asyncio.run(run())

    def test_model_config_loads_thinking_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "AGENTFACTORY_LLM_PROVIDER=openai_compatible_chat",
                        "AGENTFACTORY_OPENAI_BASE_URL=https://api.deepseek.com",
                        "AGENTFACTORY_OPENAI_API_KEY=sk-test-key",
                        "AGENTFACTORY_OPENAI_MODEL=deepseek-v4-pro",
                        "AGENTFACTORY_LLM_THINKING=enabled",
                        "AGENTFACTORY_TASK_MODEL=deepseek-v4-flash",
                        "AGENTFACTORY_TASK_TEMPERATURE=0.1",
                        "AGENTFACTORY_TASK_MAX_OUTPUT_TOKENS=1024",
                        "AGENTFACTORY_TASK_THINKING=disabled",
                    ]
                ),
                encoding="utf-8",
            )

            config = ModelConfig.from_env(env_file=env_file, environ={})

            self.assertEqual(config.thinking, "enabled")
            self.assertEqual(config.task_model, "deepseek-v4-flash")
            self.assertEqual(config.task_temperature, 0.1)
            self.assertEqual(config.task_max_output_tokens, 1024)
            self.assertEqual(config.task_thinking, "disabled")
            self.assertEqual(config.safe_summary()["thinking"], "enabled")
            self.assertEqual(config.safe_summary()["task_model"], "deepseek-v4-flash")

    def test_model_service_applies_task_model_to_structured_requests(self) -> None:
        async def run() -> None:
            config = ModelConfig(
                provider="fake",
                task_model="deepseek-v4-flash",
                task_temperature=0.1,
                task_max_output_tokens=1024,
                task_thinking="disabled",
            )
            adapter = FakeModelAdapter([{"ok": True}])
            service = ModelService.with_adapter(config, adapter)
            result = await service.generate_task_structured(
                LLMRequest(messages=[LLMMessage(role="user", content="return json")])
            )

            self.assertTrue(result.ok)
            request = adapter.requests[0]
            self.assertEqual(request.model, "deepseek-v4-flash")
            self.assertEqual(request.temperature, 0.1)
            self.assertEqual(request.max_output_tokens, 1024)
            self.assertEqual(request.thinking, "disabled")
            self.assertEqual(request.metadata["model_role"], "task")

        asyncio.run(run())

    def test_stream_structured_returns_json_and_emits_deltas(self) -> None:
        async def run() -> None:
            config = ModelConfig(provider="fake")
            adapter = FakeModelAdapter([{"ok": True}])
            service = ModelService.with_adapter(config, adapter)
            deltas: list[str] = []

            result = await service.stream_structured(
                LLMRequest(messages=[LLMMessage(role="user", content="return json")]),
                on_event=lambda event: deltas.append(event.delta or "")
                if event.type == "delta"
                else None,
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data, {"ok": True})
            self.assertTrue(any(delta for delta in deltas))

        asyncio.run(run())

    def test_deepseek_stream_parser_keeps_reasoning_delta_separate(self) -> None:
        config = ModelConfig(
            provider="openai_compatible_chat",
            base_url="https://api.deepseek.com",
            api_key="sk-test-key",
            model="deepseek-v4-pro",
        )
        adapter = OpenAICompatibleChatAdapter(config)

        reasoning = adapter._parse_stream_line(
            'data: {"choices":[{"delta":{"reasoning_content":"thinking"}}]}'
        )
        content = adapter._parse_stream_line(
            'data: {"choices":[{"delta":{"content":"{\\"ok\\":true}"}}]}'
        )

        self.assertIsNotNone(reasoning)
        self.assertEqual(reasoning.delta, "thinking")
        self.assertEqual(reasoning.metadata["delta_kind"], "reasoning")
        self.assertIsNotNone(content)
        self.assertEqual(content.delta, '{"ok":true}')
        self.assertEqual(content.metadata["delta_kind"], "content")


if __name__ == "__main__":
    unittest.main()
