from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from agent_factory.model.config import ModelConfig
from agent_factory.model.types import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    ModelError,
    TokenUsage,
    ToolCallProposal,
)


class FakeModelAdapter:
    """Deterministic adapter for tests and AgentHarness fixtures."""

    provider = "fake"

    def __init__(self, responses: Sequence[str | dict[str, Any] | LLMResponse] | None = None):
        self._responses = list(responses or [""])
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        response = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(response, LLMResponse):
            return response
        if isinstance(response, dict):
            content = json.dumps(response, ensure_ascii=False)
        else:
            content = response
        return LLMResponse(content=content, provider=self.provider, model="fake")

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        response = await self.generate(request)
        yield LLMStreamEvent(type="started")
        if response.error:
            yield LLMStreamEvent(type="error", error=response.error, response=response)
            return
        if response.content:
            yield LLMStreamEvent(type="delta", delta=response.content)
        yield LLMStreamEvent(type="completed", response=response)


class OpenAICompatibleChatAdapter:
    """OpenAI-compatible Chat Completions adapter.

    This is the only layer that knows HTTP details for the provider.
    """

    provider = "openai_compatible_chat"

    def __init__(self, config: ModelConfig, client: httpx.AsyncClient | None = None):
        config.validate_required_fields()
        self.config = config
        self._client = client

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload = self._build_payload(request, stream=False)
        try:
            if self._client is not None:
                response = await self._client.post(
                    self._chat_completions_url(),
                    headers=self._headers(),
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                    response = await client.post(
                        self._chat_completions_url(),
                        headers=self._headers(),
                        json=payload,
                    )
            if response.status_code >= 400:
                return self._error_response(
                    "provider_http_error",
                    f"Provider returned HTTP {response.status_code}.",
                    status_code=response.status_code,
                    retryable=response.status_code >= 500,
                )
            return self._parse_response(response.json())
        except httpx.TimeoutException:
            return self._error_response(
                "provider_timeout",
                "Provider request timed out.",
                retryable=True,
            )
        except httpx.HTTPError:
            return self._error_response(
                "provider_network_error",
                "Provider request failed due to a network error.",
                retryable=True,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._error_response(
                "provider_response_error",
                "Provider response could not be parsed.",
            )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        payload = self._build_payload(request, stream=True)
        yield LLMStreamEvent(type="started")
        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        finish_reason: str | None = None
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                async with client.stream(
                    "POST",
                    self._chat_completions_url(),
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        error = ModelError(
                            type="provider_http_error",
                            message=f"Provider returned HTTP {response.status_code}.",
                            status_code=response.status_code,
                            retryable=response.status_code >= 500,
                        )
                        yield LLMStreamEvent(type="error", error=error)
                        return
                    async for line in response.aiter_lines():
                        event = self._parse_stream_line(line)
                        if event:
                            if event.type == "delta" and event.delta:
                                if event.metadata.get("delta_kind") == "reasoning":
                                    reasoning_chunks.append(event.delta)
                                else:
                                    content_chunks.append(event.delta)
                            if event.metadata.get("finish_reason"):
                                finish_reason = str(event.metadata["finish_reason"])
                            if event.type == "completed":
                                event.response = LLMResponse(
                                    content="".join(content_chunks),
                                    provider=self.provider,
                                    model=self.config.model,
                                    finish_reason=finish_reason,
                                )
                                if reasoning_chunks:
                                    event.metadata["reasoning_content"] = "".join(reasoning_chunks)
                            yield event
        except httpx.TimeoutException:
            yield LLMStreamEvent(
                type="error",
                error=ModelError(
                    type="provider_timeout",
                    message="Provider request timed out.",
                    retryable=True,
                ),
            )
        except httpx.HTTPError:
            yield LLMStreamEvent(
                type="error",
                error=ModelError(
                    type="provider_network_error",
                    message="Provider request failed due to a network error.",
                    retryable=True,
                ),
            )

    def _build_payload(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [self._message_to_payload(message) for message in request.messages],
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self.config.temperature
            ),
            "max_tokens": (
                request.max_output_tokens
                if request.max_output_tokens is not None
                else self.config.max_output_tokens
            ),
            "stream": stream,
        }
        if request.response_format == "json_schema" and request.json_schema:
            if self._uses_deepseek_json_object_mode():
                payload["response_format"] = {"type": "json_object"}
            else:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.json_schema_name or "structured_output",
                        "schema": request.json_schema,
                        "strict": request.json_schema_strict,
                    },
                }
        elif request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        if self._uses_deepseek_json_object_mode():
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

    def _uses_deepseek_json_object_mode(self) -> bool:
        base_url = (self.config.base_url or "").lower()
        model = (self.config.model or "").lower()
        return "api.deepseek.com" in base_url or model.startswith("deepseek")

    @staticmethod
    def _message_to_payload(message: LLMMessage) -> dict[str, str]:
        payload = {"role": message.role, "content": message.content}
        if message.name:
            payload["name"] = message.name
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        return payload

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        choice = data["choices"][0]
        message = choice.get("message", {})
        usage_data = data.get("usage") or {}
        return LLMResponse(
            content=message.get("content") or "",
            provider=self.provider,
            model=data.get("model") or self.config.model,
            finish_reason=choice.get("finish_reason"),
            usage=TokenUsage(
                prompt_tokens=usage_data.get("prompt_tokens"),
                completion_tokens=usage_data.get("completion_tokens"),
                total_tokens=usage_data.get("total_tokens"),
            ),
            tool_call_proposals=self._parse_tool_calls(message.get("tool_calls") or []),
        )

    def _parse_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[ToolCallProposal]:
        proposals: list[ToolCallProposal] = []
        for index, tool_call in enumerate(tool_calls):
            function = tool_call.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict):
                    arguments = {"value": arguments}
            except json.JSONDecodeError:
                arguments = {"_raw_arguments": raw_arguments}
            proposals.append(
                ToolCallProposal(
                    id=tool_call.get("id") or f"tool_call_{index}",
                    name=function.get("name") or "unknown_tool",
                    arguments=arguments,
                    raw=tool_call,
                )
            )
        return proposals

    def _parse_stream_line(self, line: str) -> LLMStreamEvent | None:
        stripped = line.strip()
        if not stripped or not stripped.startswith("data:"):
            return None
        data = stripped.removeprefix("data:").strip()
        if data == "[DONE]":
            return LLMStreamEvent(type="completed")
        try:
            payload = json.loads(data)
            choice = payload["choices"][0]
            delta = choice.get("delta", {})
            content = delta.get("content")
            reasoning_content = delta.get("reasoning_content")
            finish_reason = choice.get("finish_reason")
        except (json.JSONDecodeError, KeyError, TypeError):
            return LLMStreamEvent(
                type="error",
                error=ModelError(
                    type="provider_stream_parse_error",
                    message="Provider stream event could not be parsed.",
                ),
            )
        if content:
            return LLMStreamEvent(
                type="delta",
                delta=content,
                metadata={"delta_kind": "content", "finish_reason": finish_reason},
            )
        if reasoning_content:
            return LLMStreamEvent(
                type="delta",
                delta=reasoning_content,
                metadata={"delta_kind": "reasoning", "finish_reason": finish_reason},
            )
        if finish_reason:
            return LLMStreamEvent(type="delta", metadata={"finish_reason": finish_reason})
        return None

    def _error_response(
        self,
        error_type: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> LLMResponse:
        return LLMResponse(
            provider=self.provider,
            model=self.config.model,
            error=ModelError(
                type=error_type,
                message=message,
                status_code=status_code,
                retryable=retryable,
            ),
        )
