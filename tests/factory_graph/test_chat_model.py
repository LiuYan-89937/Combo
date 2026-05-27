from __future__ import annotations

import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.models import (
    get_compression_model,
    get_compression_model_settings,
    get_main_model,
    get_main_model_settings,
    get_task_model,
    get_task_model_settings,
    reset_chat_models,
)


class ChatModelTest(unittest.TestCase):
    def tearDown(self) -> None:
        reset_chat_models()

    def test_uses_only_agentfactory_env_fields(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AGENTFACTORY_OPENAI_MODEL": "main-model",
                "AGENTFACTORY_OPENAI_API_KEY": "shared-key",
                "AGENTFACTORY_OPENAI_BASE_URL": "https://openai-compatible.example/v1",
                "AGENTFACTORY_LLM_TEMPERATURE": "0.2",
                "AGENTFACTORY_LLM_THINKING": "enabled",
                "AGENTFACTORY_TASK_MODEL": "task-model",
                "AGENTFACTORY_TASK_TEMPERATURE": "0",
                "AGENTFACTORY_TASK_THINKING": "disabled",
                "AGENTFACTORY_COMPRESSION_BASE_URL": "https://compression.example/v1",
                "AGENTFACTORY_COMPRESSION_API_KEY": "compression-key",
                "AGENTFACTORY_COMPRESSION_MODEL": "compression-model",
                "AGENTFACTORY_COMPRESSION_TEMPERATURE": "0.1",
                "AGENTFACTORY_COMPRESSION_TIMEOUT_SECONDS": "120",
                "AGENTFACTORY_COMPRESSION_THINKING": "disabled",
                "UNRELATED_MODEL": "ignored-model",
                "UNRELATED_API_KEY": "ignored-key",
                "UNRELATED_BASE_URL": "https://ignored.example/v1",
            },
            clear=True,
        ):
            reset_chat_models()
            main_settings = get_main_model_settings()
            task_settings = get_task_model_settings()
            compression_settings = get_compression_model_settings()
            main_model = get_main_model()
            task_model = get_task_model()
            compression_model = get_compression_model()

        self.assertEqual(main_settings.model, "main-model")
        self.assertEqual(main_settings.api_key, "shared-key")
        self.assertEqual(main_settings.base_url, "https://openai-compatible.example/v1")
        self.assertEqual(main_settings.temperature, 0.2)
        self.assertEqual(main_settings.thinking, "enabled")
        self.assertEqual(task_settings.model, "task-model")
        self.assertEqual(task_settings.api_key, "shared-key")
        self.assertEqual(task_settings.base_url, "https://openai-compatible.example/v1")
        self.assertEqual(task_settings.temperature, 0)
        self.assertEqual(task_settings.thinking, "disabled")
        self.assertEqual(compression_settings.model, "compression-model")
        self.assertEqual(compression_settings.api_key, "compression-key")
        self.assertEqual(compression_settings.base_url, "https://compression.example/v1")
        self.assertEqual(compression_settings.temperature, 0.1)
        self.assertEqual(compression_settings.timeout_seconds, 120)
        self.assertEqual(compression_settings.thinking, "disabled")
        self.assertIsInstance(main_model, ChatOpenAI)
        self.assertIsInstance(task_model, ChatOpenAI)
        self.assertIsInstance(compression_model, ChatOpenAI)
        self.assertIsNone(main_model.max_tokens)
        self.assertIsNone(task_model.max_tokens)
        self.assertIsNone(compression_model.max_tokens)
        self.assertEqual(main_model.extra_body, {"thinking": {"type": "enabled"}})
        self.assertEqual(task_model.extra_body, {"thinking": {"type": "disabled"}})
        self.assertEqual(compression_model.extra_body, {"thinking": {"type": "disabled"}})

    def test_returns_none_when_model_is_not_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            reset_chat_models()
            self.assertIsNone(get_main_model())
            self.assertIsNone(get_task_model())
            self.assertIsNone(get_compression_model())

    def test_does_not_fallback_to_standard_openai_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AGENTFACTORY_TASK_MODEL": "task-model",
                "OPENAI_API_KEY": "ignored-key",
                "OPENAI_BASE_URL": "https://ignored.example/v1",
            },
            clear=True,
        ):
            reset_chat_models()
            self.assertFalse(get_task_model_settings().available)
            self.assertIsNone(get_task_model())

    def test_dotenv_loader_uses_agentfactory_fields_without_overriding_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv_path = Path(temp_dir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        "AGENTFACTORY_OPENAI_MODEL=env-file-main",
                        "AGENTFACTORY_OPENAI_API_KEY=env-file-key",
                        "AGENTFACTORY_OPENAI_BASE_URL=https://env-file.example/v1",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"AGENTFACTORY_OPENAI_MODEL": "already-set-main"},
                clear=True,
            ):
                loaded = load_agentfactory_dotenv(dotenv_path)

                self.assertEqual(loaded, dotenv_path)
                self.assertEqual(os.environ["AGENTFACTORY_OPENAI_MODEL"], "already-set-main")
                self.assertEqual(os.environ["AGENTFACTORY_OPENAI_API_KEY"], "env-file-key")
                self.assertEqual(
                    os.environ["AGENTFACTORY_OPENAI_BASE_URL"],
                    "https://env-file.example/v1",
                )

    def test_invalid_thinking_value_is_ignored(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AGENTFACTORY_OPENAI_MODEL": "main-model",
                "AGENTFACTORY_OPENAI_API_KEY": "shared-key",
                "AGENTFACTORY_OPENAI_BASE_URL": "https://openai-compatible.example/v1",
                "AGENTFACTORY_LLM_THINKING": "maybe",
            },
            clear=True,
        ):
            reset_chat_models()
            settings = get_main_model_settings()
            model = get_main_model()

        self.assertIsNone(settings.thinking)
        self.assertIsInstance(model, ChatOpenAI)
        self.assertIsNone(model.extra_body)

    def test_thinking_response_preserves_reasoning_content(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AGENTFACTORY_OPENAI_MODEL": "main-model",
                "AGENTFACTORY_OPENAI_API_KEY": "shared-key",
                "AGENTFACTORY_OPENAI_BASE_URL": "https://openai-compatible.example/v1",
                "AGENTFACTORY_LLM_THINKING": "enabled",
            },
            clear=True,
        ):
            reset_chat_models()
            model = get_main_model()

        result = model._create_chat_result(
            {
                "model": "main-model",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": "internal reasoning",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
        )

        message = result.generations[0].message
        self.assertEqual(message.additional_kwargs["reasoning_content"], "internal reasoning")

    def test_thinking_payload_passes_reasoning_content_back(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AGENTFACTORY_OPENAI_MODEL": "main-model",
                "AGENTFACTORY_OPENAI_API_KEY": "shared-key",
                "AGENTFACTORY_OPENAI_BASE_URL": "https://openai-compatible.example/v1",
                "AGENTFACTORY_LLM_THINKING": "enabled",
            },
            clear=True,
        ):
            reset_chat_models()
            model = get_main_model()

        payload = model._get_request_payload(
            [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "call_1", "name": "lookup", "args": {}, "type": "tool_call"}],
                    additional_kwargs={"reasoning_content": "internal reasoning"},
                ),
                ToolMessage(content="{}", tool_call_id="call_1", name="lookup"),
            ]
        )

        assistant_messages = [
            message for message in payload["messages"]
            if message.get("role") == "assistant"
        ]
        self.assertEqual(assistant_messages[0]["reasoning_content"], "internal reasoning")


if __name__ == "__main__":
    unittest.main()
