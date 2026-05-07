from __future__ import annotations

import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from langchain_openai import ChatOpenAI

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.models import (
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
                "AGENTFACTORY_LLM_MAX_OUTPUT_TOKENS": "2048",
                "AGENTFACTORY_LLM_THINKING": "enabled",
                "AGENTFACTORY_TASK_MODEL": "task-model",
                "AGENTFACTORY_TASK_TEMPERATURE": "0",
                "AGENTFACTORY_TASK_MAX_OUTPUT_TOKENS": "512",
                "AGENTFACTORY_TASK_THINKING": "disabled",
                "UNRELATED_MODEL": "ignored-model",
                "UNRELATED_API_KEY": "ignored-key",
                "UNRELATED_BASE_URL": "https://ignored.example/v1",
            },
            clear=True,
        ):
            reset_chat_models()
            main_settings = get_main_model_settings()
            task_settings = get_task_model_settings()
            main_model = get_main_model()
            task_model = get_task_model()

        self.assertEqual(main_settings.model, "main-model")
        self.assertEqual(main_settings.api_key, "shared-key")
        self.assertEqual(main_settings.base_url, "https://openai-compatible.example/v1")
        self.assertEqual(main_settings.temperature, 0.2)
        self.assertEqual(main_settings.max_tokens, 2048)
        self.assertEqual(main_settings.thinking, "enabled")
        self.assertEqual(task_settings.model, "task-model")
        self.assertEqual(task_settings.api_key, "shared-key")
        self.assertEqual(task_settings.base_url, "https://openai-compatible.example/v1")
        self.assertEqual(task_settings.temperature, 0)
        self.assertEqual(task_settings.max_tokens, 512)
        self.assertEqual(task_settings.thinking, "disabled")
        self.assertIsInstance(main_model, ChatOpenAI)
        self.assertIsInstance(task_model, ChatOpenAI)
        self.assertEqual(main_model.extra_body, {"thinking": {"type": "enabled"}})
        self.assertEqual(task_model.extra_body, {"thinking": {"type": "disabled"}})

    def test_returns_none_when_model_is_not_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            reset_chat_models()
            self.assertIsNone(get_main_model())
            self.assertIsNone(get_task_model())

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


if __name__ == "__main__":
    unittest.main()
