from __future__ import annotations

from dataclasses import dataclass, replace
import base64
import json
import logging
import re
import struct
from threading import Event, RLock
from time import perf_counter
from typing import Any, Callable

from jsonschema import Draft202012Validator
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from combo.computer_use.host import ComputerHostClient
from combo.dynamic_runtime.model_service import RuntimeModelResolver
from combo.models.chat_model import create_chat_model_from_settings
from combo.runtime_kernel.model_operations.tool_calls import (
    bind_tools,
    tool_calls_from_response,
)
from combo.runtime_protocol import RuntimeInstance
from combo.tooling.execution_context import (
    RuntimeToolExecutionCancelled,
    execute_with_runtime_cancellation,
    register_runtime_tool_cancellation,
    runtime_terminal_cancellation_requested,
    runtime_tool_interruption_requested,
)

_logger = logging.getLogger(__name__)
ComputerUseProgressObserver = Callable[[dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class ComputerUseResult:
    status: str
    summary: str
    steps: int
    model_calls: int
    total_tokens: int
    verification: str = "model_assessed"

    def payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "steps": self.steps,
            "model_calls": self.model_calls,
            "total_tokens": self.total_tokens,
            "verification": self.verification,
        }


class ComputerUseCoordinator:
    """Own the high-speed vision/action loop without entering the ordinary tool loop."""

    def __init__(
        self, *, model_resolver: RuntimeModelResolver, host: ComputerHostClient | None
    ) -> None:
        self._model_resolver = model_resolver
        self._host = host
        self._activity_lock = RLock()
        self._active_request_id: str | None = None
        self._active_host: ComputerHostClient | None = None

    @classmethod
    def from_environment(
        cls, *, model_resolver: RuntimeModelResolver
    ) -> "ComputerUseCoordinator":
        return cls(
            model_resolver=model_resolver, host=ComputerHostClient.from_environment()
        )

    def for_runtime(self, instance: RuntimeInstance) -> "RuntimeComputerUse":
        return RuntimeComputerUse(
            coordinator=self,
            instance=instance,
        )

    def close(self) -> None:
        with self._activity_lock:
            host = self._active_host
        if host is not None:
            host.cancel_session()

    def _run(
        self,
        *,
        instance: RuntimeInstance,
        goal: str,
        on_progress: ComputerUseProgressObserver | None = None,
    ) -> ComputerUseResult:
        request_id = instance.request.request_id
        if self._host is None:
            raise RuntimeError("Computer Use requires the desktop native host")
        host = self._host.new_session(request_id)
        cancelled = host.cancellation_event
        with self._activity_lock:
            if self._active_host is not None:
                _logger.info(
                    "Computer use request=%s phase=session_superseded replacement=%s",
                    self._active_request_id,
                    request_id,
                )
                self._active_host.cancel_session()
            self._active_request_id = request_id
            self._active_host = host

        def release_activity() -> None:
            with self._activity_lock:
                if self._active_host is host:
                    self._active_host = None
                    self._active_request_id = None

        def cancel_active_session() -> None:
            cancelled.set()
            try:
                host.cancel_session()
            except Exception:
                _logger.exception(
                    "Computer use request=%s native cancellation failed", request_id
                )
            finally:
                release_activity()
                _publish_progress(
                    on_progress,
                    phase="cancelled",
                    message="Computer Use session was cancelled.",
                )

        unregister_cancellation = lambda: None
        try:
            unregister_cancellation = register_runtime_tool_cancellation(
                cancel_active_session
            )
            _ensure_not_cancelled(cancelled, host, None)
            return self._run_exclusive(
                instance=instance,
                goal=goal,
                on_progress=on_progress,
                cancelled=cancelled,
                host=host,
            )
        except Exception:
            if cancelled.is_set() or host.cancel_requested:
                raise RuntimeToolExecutionCancelled(
                    "Computer Use execution was cancelled."
                ) from None
            raise
        finally:
            try:
                unregister_cancellation()
            finally:
                try:
                    host.close()
                finally:
                    release_activity()

    def _run_exclusive(
        self,
        *,
        instance: RuntimeInstance,
        goal: str,
        on_progress: ComputerUseProgressObserver | None,
        cancelled: Event,
        host: ComputerHostClient,
    ) -> ComputerUseResult:
        if not goal.strip():
            raise ValueError("computer_use goal must not be empty")
        frozen = instance.request.policy_snapshot.model
        resolved = self._model_resolver.resolve_chat_model(
            operation="computer_use",
            profile_id=frozen.profile_id,
            expected_profile_revision=frozen.profile_revision,
            expected_credential_revision=frozen.credential_revision,
            reasoning_intensity=1,
        )
        model = create_chat_model_from_settings(
            replace(resolved.settings, role="computer_use")
        )
        if model is None:
            raise RuntimeError("Computer Use model is unavailable")
        _ensure_not_cancelled(cancelled, host, None)
        session = host.start()
        callback = UsageMetadataCallbackHandler()
        calls = steps = 0
        last_states: dict[str, str] = {}
        try:
            _ensure_not_cancelled(cancelled, host, session)
            catalog = host.tools(session)
            definitions = {tool["name"]: tool for tool in catalog["tools"]}
            validators = {
                name: Draft202012Validator(tool["inputSchema"])
                for name, tool in definitions.items()
            }
            bound = bind_tools(
                model,
                [
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool["description"],
                            "parameters": tool["inputSchema"],
                        },
                    }
                    for tool in definitions.values()
                ],
            )
            messages: list[Any] = [
                SystemMessage(content=catalog["instructions"]),
                HumanMessage(content=goal),
            ]
            # Same upstream discovery operation, in the same persistent engine session.
            inventory = host.call(session, "list_apps", {})
            messages.append(
                HumanMessage(
                    content="Available applications:\n" + _result_text(inventory)
                )
            )
            while True:
                _ensure_not_cancelled(cancelled, host, session)
                _publish_progress(
                    on_progress,
                    phase="analyzing",
                    message="Planning from the upstream application state.",
                    step=steps,
                )
                started = perf_counter()
                response = execute_with_runtime_cancellation(
                    lambda: bound.invoke(
                        messages,
                        config={
                            "callbacks": [callback],
                            "tags": ["computer-use"],
                            "metadata": {
                                "operation": "computer_use",
                                "request_id": instance.request.request_id,
                            },
                        },
                    ),
                    timeout_seconds=None,
                    cancellation_event=cancelled,
                )
                calls += 1
                _ensure_not_cancelled(cancelled, host, session)
                tool_calls = tool_calls_from_response(response)
                _logger.info(
                    "Computer use request=%s decision=%s phase=model_decision elapsed_ms=%.1f tool_calls=%s",
                    instance.request.request_id,
                    calls,
                    (perf_counter() - started) * 1000,
                    len(tool_calls),
                )
                if not tool_calls:
                    summary = _message_text(response.content)
                    _logger.info(
                        "Computer use request=%s phase=finished verification=model_assessed",
                        instance.request.request_id,
                    )
                    return ComputerUseResult(
                        "finished", summary, steps, calls, _usage_total(callback)
                    )
                # Preserve provider reasoning, but normalize tool call envelopes once.
                extra = {
                    key: value
                    for key, value in response.additional_kwargs.items()
                    if key not in {"tool_calls", "invalid_tool_calls"}
                }
                messages.append(
                    AIMessage(
                        content=response.content,
                        tool_calls=tool_calls,
                        additional_kwargs=extra,
                    )
                )
                images: list[dict[str, Any]] = []
                invalid_ids = {
                    item.get("id")
                    for item in getattr(response, "invalid_tool_calls", []) or []
                }
                for call in tool_calls:
                    _ensure_not_cancelled(cancelled, host, session)
                    name, arguments = call["name"], call["args"]
                    errors = (
                        list(validators[name].iter_errors(arguments))
                        if name in validators
                        else []
                    )
                    if name not in definitions or call["id"] in invalid_ids or errors:
                        detail = (
                            "; ".join(error.message for error in errors)
                            or "Unknown operation or invalid arguments"
                        )
                        result = {
                            "isError": True,
                            "content": [{"type": "text", "text": detail}],
                        }
                    else:
                        app = str(arguments.get("app") or "")
                        index = arguments.get("element_index")
                        label = _element_description(last_states.get(app, ""), index)
                        log_args = {
                            key: value
                            for key, value in arguments.items()
                            if key not in {"text", "value"}
                        }
                        for key in ("text", "value"):
                            if key in arguments:
                                log_args[key + "_length"] = len(str(arguments[key]))
                        _logger.info(
                            "Computer use request=%s step=%s phase=action_proposed tool=%s arguments=%s target=%s",
                            instance.request.request_id,
                            steps + 1,
                            name,
                            json.dumps(log_args, ensure_ascii=False),
                            label,
                        )
                        _publish_progress(
                            on_progress,
                            phase="acting",
                            message=f"{name}: {label or app}",
                            step=steps + 1,
                            operation=_operation_progress(call, steps + 1, "running"),
                        )
                        started = perf_counter()
                        result = host.call(session, name, arguments)
                        _ensure_not_cancelled(cancelled, host, session)
                        steps += 1
                        if result.get("input_result"):
                            _logger.info(
                                "Computer use request=%s step=%s phase=input_result tool=%s details=%s",
                                instance.request.request_id,
                                steps,
                                name,
                                json.dumps(result["input_result"], ensure_ascii=False),
                            )
                        if result.get("diagnostics"):
                            _logger.info(
                                "Computer use request=%s step=%s phase=native_diagnostics tool=%s details=%s",
                                instance.request.request_id,
                                steps,
                                name,
                                json.dumps(result["diagnostics"], ensure_ascii=False),
                            )
                        if result.get("isError"):
                            error_text = _result_text(result)
                            # Native errors can echo arguments; keep submitted text private.
                            for key in ("text", "value"):
                                submitted = arguments.get(key)
                                if isinstance(submitted, str) and submitted:
                                    error_text = error_text.replace(
                                        submitted, "[redacted]"
                                    )
                            _logger.error(
                                "Computer use request=%s step=%s phase=action_error tool=%s tool_call_id=%s app=%s element_index=%s error=%s",
                                instance.request.request_id,
                                steps,
                                name,
                                call["id"],
                                app,
                                index,
                                json.dumps(error_text, ensure_ascii=False),
                            )
                        _ensure_not_cancelled(cancelled, host, session)
                        text = _result_text(result)
                        if app and not result.get("isError"):
                            last_states[app] = text
                        _logger.info(
                            "Computer use request=%s step=%s phase=action_result tool=%s is_error=%s elapsed_ms=%.1f",
                            instance.request.request_id,
                            steps,
                            name,
                            bool(result.get("isError")),
                            (perf_counter() - started) * 1000,
                        )
                        _publish_state(on_progress, app, result, steps)
                        _publish_progress(
                            on_progress,
                            phase="action_effect",
                            step=steps,
                            operation=_operation_progress(
                                call,
                                steps,
                                "failed" if result.get("isError") else "returned",
                                result,
                            ),
                        )
                    messages.append(
                        ToolMessage(
                            content=_result_text(result),
                            tool_call_id=call["id"],
                            name=name,
                            status="error" if result.get("isError") else "success",
                        )
                    )
                    if resolved.settings.multimodal:
                        images.extend(_result_images(result))
                # Tool responses remain text; screenshots enter a supported image message.
                if images:
                    messages.append(
                        HumanMessage(
                            content=[
                                {
                                    "type": "text",
                                    "text": "Screenshots returned by the preceding operations, in operation order.",
                                },
                                *images,
                            ]
                        )
                    )
        finally:
            try:
                host.stop(session)
            except Exception:
                _logger.exception("Computer use session cleanup failed")


@dataclass(frozen=True, slots=True)
class RuntimeComputerUse:
    coordinator: ComputerUseCoordinator
    instance: RuntimeInstance

    def run(
        self,
        *,
        goal: str,
        on_progress: ComputerUseProgressObserver | None = None,
    ) -> dict[str, Any]:
        return self.coordinator._run(
            instance=self.instance,
            goal=goal,
            on_progress=on_progress,
        ).payload()


def _ensure_not_cancelled(
    cancelled: Event,
    host: ComputerHostClient | None,
    session_id: str | None,
) -> None:
    if not (
        cancelled.is_set()
        or runtime_terminal_cancellation_requested()
        or runtime_tool_interruption_requested()
    ):
        return
    cancelled.set()
    if host is not None and session_id is not None:
        try:
            host.cancel_session(session_id)
        except Exception:
            _logger.exception("Computer use native cancellation failed")
    raise RuntimeToolExecutionCancelled("Computer Use execution was cancelled.")


def _publish_progress(
    observer: ComputerUseProgressObserver | None, **payload: Any
) -> None:
    if observer:
        observer(payload)


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        str(part.get("text", ""))
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    )


def _result_text(result: dict[str, Any]) -> str:
    return _message_text(result.get("content", []))


def _result_images(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{part['mimeType']};base64,{part['data']}"},
        }
        for part in result.get("content", [])
        if part.get("type") == "image"
    ]


def _publish_state(
    observer: ComputerUseProgressObserver | None,
    app: str,
    result: dict[str, Any],
    steps: int,
) -> None:
    screenshot = None
    for part in result.get("content", []):
        if part.get("type") == "image" and part.get("mimeType") == "image/png":
            header = base64.b64decode(part["data"][:32])
            width, height = struct.unpack(">II", header[16:24])
            screenshot = {
                "data_url": f"data:image/png;base64,{part['data']}",
                "width": width,
                "height": height,
            }
    _publish_progress(
        observer,
        phase="action_effect",
        message=(
            "Upstream operation returned an error."
            if result.get("isError")
            else "Application state refreshed."
        ),
        step=steps,
        target={"application_id": app, "display_name": app, "window_state": {}},
        accessibility={
            "available": not bool(result.get("isError")),
            "application": app,
            "window_title": "",
            "text": _result_text(result),
            "error": _result_text(result) if result.get("isError") else None,
        },
        screenshot=screenshot,
        screenshot_error=None,
    )


def _element_description(state: str, index: Any) -> str:
    if index is None:
        return ""
    # Diagnostics only: use the upstream rendered line, never to resolve an action.
    match = re.search(r"(?m)^\s*" + re.escape(str(index)) + r"\s+([^\n]+)$", state)
    return match.group(1) if match else ""


def _usage_total(callback: UsageMetadataCallbackHandler) -> int:
    return sum(
        int(usage.get("total_tokens") or 0)
        for usage in callback.usage_metadata.values()
    )


def _operation_progress(
    call: dict[str, Any], step: int, status: str, result: dict[str, Any] | None = None
) -> dict[str, Any]:
    arguments = call["args"]
    error_code = None
    verified = False
    if result is not None:
        text = _result_text(result)
        match = (
            re.search(r"\[((?:input|observation|click)\.[a-z_]+)\]", text)
            if result.get("isError")
            else None
        )
        error_code = (
            match.group(1)
            if match
            else ("native_error" if result.get("isError") else None)
        )
        verified = result.get("input_result", {}).get(
            "verification"
        ) == "value_verified" or (
            not result.get("isError")
            and any(
                item.get("type") == "text"
                and item.get("text", "").startswith("Input result: value_verified.")
                for item in result.get("content", [])
            )
        )
    return {
        "id": call["id"],
        "step": step,
        "tool": call["name"],
        "app": str(arguments.get("app") or ""),
        "status": status,
        "element_index": arguments.get("element_index"),
        "x": arguments.get("x"),
        "y": arguments.get("y"),
        "text_length": (
            len(str(arguments.get("text", arguments.get("value", ""))))
            if call["name"] in {"type_text", "set_value"}
            else None
        ),
        "key": arguments.get("key"),
        "action": arguments.get("action"),
        "error_code": error_code,
        "value_verified": verified,
        "input_verification": (result or {})
        .get("input_result", {})
        .get("verification"),
    }
