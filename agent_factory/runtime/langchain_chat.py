from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, SecretStr

from agent_factory.runtime.types import RuntimeErrorInfo


class RuntimeModelConfigError(ValueError):
    pass


class RuntimeModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    provider: str = "openai_compatible_chat"
    base_url: str | None = None
    api_key: SecretStr | None = None
    model: str | None = None
    timeout_seconds: int = Field(default=60, ge=1)
    temperature: float = Field(default=0.2, ge=0)
    max_output_tokens: int = Field(default=2048, ge=1)
    thinking: str | None = None

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "RuntimeModelConfig":
        values = {**_read_env_file(Path(env_file)), **dict(os.environ)}
        api_key = _blank(values.get("AGENTFACTORY_OPENAI_API_KEY"))
        config = cls(
            provider=values.get("AGENTFACTORY_LLM_PROVIDER", "openai_compatible_chat"),
            base_url=_rstrip(_blank(values.get("AGENTFACTORY_OPENAI_BASE_URL"))),
            api_key=SecretStr(api_key) if api_key else None,
            model=_blank(values.get("AGENTFACTORY_OPENAI_MODEL")),
            timeout_seconds=_to_int(values.get("AGENTFACTORY_LLM_TIMEOUT_SECONDS"), 60),
            temperature=_to_float(values.get("AGENTFACTORY_LLM_TEMPERATURE"), 0.2),
            max_output_tokens=_to_int(values.get("AGENTFACTORY_LLM_MAX_OUTPUT_TOKENS"), 2048),
            thinking=_blank(values.get("AGENTFACTORY_LLM_THINKING")),
        )
        config.validate_required()
        return config

    def validate_required(self) -> None:
        if self.provider == "fake":
            return
        missing = [
            key
            for key, value in {
                "AGENTFACTORY_OPENAI_BASE_URL": self.base_url,
                "AGENTFACTORY_OPENAI_API_KEY": self.api_key,
                "AGENTFACTORY_OPENAI_MODEL": self.model,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeModelConfigError(
                "Missing required LLM configuration: " + ", ".join(missing)
            )


class RuntimeModelError(RuntimeError):
    def __init__(self, error: RuntimeErrorInfo):
        super().__init__(error.message)
        self.error = error


class RuntimeChatCallSpan(dict):
    pass


class OpenAICompatibleRuntimeChatModel(BaseChatModel):
    """LangChain-native chat model for AgentInstance runtime.

    Factory LLM utilities may still use the business-facing ModelService. The
    runtime graph speaks LangChain BaseMessage/AIMessage/ToolMessage directly so
    provider payloads preserve tool-call protocol state.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    config: RuntimeModelConfig
    tool_definitions: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    _last_span: RuntimeChatCallSpan | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "agentfactory_openai_compatible_langchain"

    @property
    def last_span(self) -> RuntimeChatCallSpan | None:
        return self._last_span

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        started = time.perf_counter()
        payload = self._build_payload(messages)
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.post(
                    self._chat_completions_url(),
                    headers=self._headers(),
                    json=payload,
                )
            duration_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                self._last_span = RuntimeChatCallSpan(
                    operation="model.generate",
                    provider=self.config.provider,
                    model=self.config.model,
                    status="failed",
                    attempt_count=1,
                    duration_ms=duration_ms,
                    error_type="provider_http_error",
                    retryable=response.status_code >= 500,
                    metadata=self.metadata,
                )
                raise RuntimeModelError(
                    RuntimeErrorInfo(
                        type="provider_http_error",
                        message=f"Provider returned HTTP {response.status_code}.",
                        status_code=response.status_code,
                        retryable=response.status_code >= 500,
                    )
                )
            message = self._parse_message(response.json())
            self._last_span = RuntimeChatCallSpan(
                operation="model.generate",
                provider=self.config.provider,
                model=self.config.model,
                status="completed",
                attempt_count=1,
                duration_ms=duration_ms,
                error_type=None,
                retryable=False,
                metadata=self.metadata,
            )
            return ChatResult(generations=[ChatGeneration(message=message)])
        except RuntimeModelError:
            raise
        except httpx.TimeoutException:
            self._last_span = self._failed_span(started, "provider_timeout", retryable=True)
            raise RuntimeModelError(
                RuntimeErrorInfo(
                    type="provider_timeout",
                    message="Provider request timed out.",
                    retryable=True,
                )
            ) from None
        except httpx.HTTPError:
            self._last_span = self._failed_span(started, "provider_network_error", retryable=True)
            raise RuntimeModelError(
                RuntimeErrorInfo(
                    type="provider_network_error",
                    message="Provider request failed due to a network error.",
                    retryable=True,
                )
            ) from None
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._last_span = self._failed_span(started, "provider_response_error")
            raise RuntimeModelError(
                RuntimeErrorInfo(
                    type="provider_response_error",
                    message="Provider response could not be parsed.",
                )
            ) from None

    def _failed_span(
        self,
        started: float,
        error_type: str,
        *,
        retryable: bool = False,
    ) -> RuntimeChatCallSpan:
        return RuntimeChatCallSpan(
            operation="model.generate",
            provider=self.config.provider,
            model=self.config.model,
            status="failed",
            attempt_count=1,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=error_type,
            retryable=retryable,
            metadata=self.metadata,
        )

    def _build_payload(self, messages: list[BaseMessage]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [_message_to_payload(message) for message in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            "stream": False,
        }
        if self.tool_definitions:
            payload["tools"] = list(self.tool_definitions)
            payload["tool_choice"] = "auto"
        if self._uses_deepseek():
            payload["thinking"] = {"type": self.config.thinking or "enabled"}
        return payload

    def _headers(self) -> dict[str, str]:
        assert self.config.api_key is not None
        return {
            "Authorization": f"Bearer {self.config.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    def _chat_completions_url(self) -> str:
        assert self.config.base_url is not None
        return f"{self.config.base_url}/chat/completions"

    def _uses_deepseek(self) -> bool:
        base_url = (self.config.base_url or "").lower()
        model = (self.config.model or "").lower()
        return "api.deepseek.com" in base_url or model.startswith("deepseek")

    def _parse_message(self, data: dict[str, Any]) -> AIMessage:
        message = data["choices"][0].get("message", {})
        return AIMessage(
            content=message.get("content") or "",
            tool_calls=[_raw_tool_call_to_langchain(item) for item in message.get("tool_calls") or []],
            response_metadata={"model": data.get("model") or self.config.model},
        )


class ScriptedRuntimeChatModel(BaseChatModel):
    """Small LangChain-native fake chat model for runtime tests."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    responses: list[str | AIMessage | dict[str, Any]] = Field(default_factory=list)
    requests: list[list[BaseMessage]] = Field(default_factory=list)
    _last_span: RuntimeChatCallSpan | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "agentfactory_scripted_runtime_chat"

    @property
    def last_span(self) -> RuntimeChatCallSpan | None:
        return self._last_span

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.requests.append(list(messages))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, AIMessage):
            message = response
        elif isinstance(response, dict):
            message = AIMessage(
                content=str(response.get("content") or ""),
                tool_calls=list(response.get("tool_calls") or []),
            )
        else:
            message = AIMessage(content=response)
        self._last_span = RuntimeChatCallSpan(
            operation="model.generate",
            provider="fake",
            model="fake",
            status="completed",
            attempt_count=1,
            duration_ms=0,
            error_type=None,
            retryable=False,
            metadata={},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def _message_to_payload(message: BaseMessage) -> dict[str, Any]:
    if isinstance(message, SystemMessage):
        return {"role": "system", "content": _content_to_text(message.content)}
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": _content_to_text(message.content)}
    if isinstance(message, ToolMessage):
        payload = {
            "role": "tool",
            "content": _content_to_text(message.content),
            "tool_call_id": message.tool_call_id,
        }
        if message.name:
            payload["name"] = message.name
        return payload
    if isinstance(message, AIMessage):
        payload = {"role": "assistant", "content": _content_to_text(message.content)}
        if message.tool_calls:
            payload["tool_calls"] = [_langchain_tool_call_to_openai(item) for item in message.tool_calls]
        return payload
    return {"role": "user", "content": _content_to_text(message.content)}


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _langchain_tool_call_to_openai(tool_call: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": tool_call.get("id"),
        "type": "function",
        "function": {
            "name": tool_call.get("name"),
            "arguments": json.dumps(tool_call.get("args") or {}, ensure_ascii=False),
        },
    }


def _raw_tool_call_to_langchain(tool_call: dict[str, Any]) -> dict[str, Any]:
    function = tool_call.get("function") or {}
    raw_args = function.get("arguments") or "{}"
    try:
        args = json.loads(raw_args)
        if not isinstance(args, dict):
            args = {"value": args}
    except json.JSONDecodeError:
        args = {"_raw_arguments": raw_args}
    return {
        "id": tool_call.get("id"),
        "name": function.get("name") or "unknown_tool",
        "args": args,
        "type": "tool_call",
    }


def build_runtime_chat_model(
    *,
    env_file: str | None,
    tool_definitions: Sequence[dict[str, Any]],
    metadata: dict[str, Any],
) -> BaseChatModel:
    config = RuntimeModelConfig.from_env(env_file or ".env")
    if config.provider == "fake":
        return ScriptedRuntimeChatModel(responses=[""])
    return OpenAICompatibleRuntimeChatModel(
        config=config,
        tool_definitions=list(tool_definitions),
        metadata=metadata,
    )


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _rstrip(value: str | None) -> str | None:
    return value.rstrip("/") if value else value


def _to_int(value: str | None, default: int) -> int:
    return int(value) if _blank(value) is not None else default


def _to_float(value: str | None, default: float) -> float:
    return float(value) if _blank(value) is not None else default
