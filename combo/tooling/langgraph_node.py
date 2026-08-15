from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from combo.runtime_kernel.observability.tool_events import emit_runtime_tool_activity
from combo.runtime_protocol.messages import incomplete_tool_call_ids
from combo.tooling.builtins.ask_usr.specs import ASK_USR_TOOL_ID
from combo.tooling.execution_context import (
    current_tool_approval_override,
    tool_approval_override,
    tool_call_context,
)
from combo.tooling.gateway import (
    TRUST_TOOL_ACTIONS,
    parse_approval_decision,
)
from combo.tooling.redaction import redact_json_pointer_paths

ToolEventCallback = Callable[[dict[str, Any]], None]


class ComboToolNode:
    """Thin adapter around LangGraph's native ToolNode.

    The adapter keeps ToolNode as the execution primitive while adding
    Combo's shared concerns at the boundary: ordered batching for
    non-concurrent tools, permission observations, tool-call events, and
    normalized ToolMessage observations.
    """

    def __init__(
        self,
        tools: Sequence[BaseTool],
        *,
        node_id: str,
        name: str | None = None,
        messages_key: str = "messages",
        allowed_tool_ids: set[str] | None = None,
        known_tool_ids: set[str] | None = None,
        origin_node_id: str = "",
        origin_impl: str = "",
        emit_event: ToolEventCallback | None = None,
        stream_events: bool = False,
    ) -> None:
        self.node_id = node_id
        self.origin_node_id = origin_node_id
        self.origin_impl = origin_impl
        self.messages_key = messages_key
        self.allowed_tool_ids = set(allowed_tool_ids) if allowed_tool_ids is not None else None
        self.known_tool_ids = set(known_tool_ids or {tool.name for tool in tools})
        self.emit_event = emit_event
        self.stream_events = stream_events
        self._concurrent_by_name = {tool.name: _tool_concurrent(tool) for tool in tools}
        self._max_parallel_by_name = {
            tool.name: _tool_max_parallel_calls(tool) for tool in tools
        }
        self._serialization_key_by_name = {
            tool.name: _tool_serialization_key(tool)
            for tool in tools
        }
        self._approval_request_by_name = {tool.name: _tool_approval_request(tool) for tool in tools}
        self._trust_tool_by_name = {tool.name: _tool_trust_handler(tool) for tool in tools}
        self._sensitive_argument_paths_by_name = {
            tool.name: _tool_sensitive_argument_paths(tool) for tool in tools
        }
        self._tool_node = ToolNode(
            list(tools),
            name=name or node_id,
            messages_key=messages_key,
            wrap_tool_call=self._wrap_tool_call,
        )

    def __call__(
        self,
        state: Mapping[str, Any],
        config: RunnableConfig = None,
        runtime: Runtime = None,
    ) -> dict[str, list[ToolMessage]]:
        return self.invoke(state, config=config, runtime=runtime)

    def invoke(
        self,
        state: Mapping[str, Any],
        config: RunnableConfig = None,
        runtime: Runtime = None,
    ) -> dict[str, list[ToolMessage]]:
        messages = list(state.get(self.messages_key) or [])
        ai_message, tool_calls = latest_ai_tool_calls(messages)
        if ai_message is None or not tool_calls:
            return {self.messages_key: []}
        outputs: list[ToolMessage] = []
        invalid_calls, executable_calls = _partition_invalid_tool_calls(tool_calls)
        outputs.extend(_invalid_tool_call_messages(invalid_calls))
        for batch in _tool_call_batches(
            executable_calls,
            self._concurrent_by_name,
            self._max_parallel_by_name,
            self._serialization_key_by_name,
        ):
            interactive_calls, ordinary_calls = _split_ask_user_batch(batch)
            if interactive_calls:
                outputs.extend(self._ask_user_messages(interactive_calls, state=state))
            if not ordinary_calls:
                continue
            batch = ordinary_calls
            approval_requests = self._approval_requests_for_batch(batch, state=state)
            if approval_requests:
                decision = interrupt(_batch_approval_payload(approval_requests))
                parsed = parse_approval_decision(decision)
                if _is_trust_tool_decision(decision):
                    for request in approval_requests:
                        tool_name = str(request.get("tool_name") or "")
                        trust_tool = self._trust_tool_by_name.get(tool_name)
                        if trust_tool is not None:
                            trust_tool(tool_name)
                if parsed.action != "approve":
                    outputs.extend(_approval_rejection_messages(batch, parsed.action, parsed.revision_guidance))
                    continue
            batch_state = dict(state)
            batch_state[self.messages_key] = _replace_latest_ai_tool_calls(messages, ai_message, batch)
            approval_context = (
                tool_approval_override(reason="approved by batch tool approval")
                if approval_requests
                else nullcontext()
            )
            with approval_context:
                raw_output = self._invoke_native_tool_node(batch_state, config=config, runtime=runtime)
            outputs.extend(_messages_from_tool_node_output(raw_output, self.messages_key))
        return {self.messages_key: _complete_tool_message_set(tool_calls, outputs)}

    def _ask_user_messages(
        self,
        calls: Sequence[dict[str, Any]],
        *,
        state: Mapping[str, Any],
    ) -> list[ToolMessage]:
        if len(calls) != 1:
            raise RuntimeError("ask_usr must be invoked one question at a time")
        call = calls[0]
        tool_call_id = str(call.get("id") or ASK_USR_TOOL_ID)
        arguments = dict(call.get("args") or {})
        question = str(arguments.get("question") or "").strip()
        if not question:
            return [
                tool_observation_message(
                    status="invalid_arguments",
                    tool_id=ASK_USR_TOOL_ID,
                    tool_call_id=tool_call_id,
                    message="ask_usr requires a non-empty question.",
                    arguments=arguments,
                    retryable=True,
                )
            ]
        choices = _ask_user_choices(arguments.get("choices"))
        allow_free_text = arguments.get("allow_free_text", True) is not False
        public_arguments = self._public_arguments(ASK_USR_TOOL_ID, arguments)
        self._emit(
            {
                "event_type": "tool_proposed",
                "tool_id": ASK_USR_TOOL_ID,
                "tool_call_id": tool_call_id,
                "arguments": public_arguments,
                "status": "proposed",
            }
        )
        runtime_state = state.get("runtime") if isinstance(state, Mapping) else None
        run_state = runtime_state.get("run") if isinstance(runtime_state, Mapping) else {}
        with tool_call_context(
            tool_id=ASK_USR_TOOL_ID,
            tool_call_id=tool_call_id,
            origin_node_id=self.origin_node_id,
            origin_impl=self.origin_impl,
            event_sink=self._emit,
        ):
            response = interrupt(
                {
                    "type": "ask_user",
                    "question_id": tool_call_id,
                    "tool_call_id": tool_call_id,
                    "message": question,
                    "choices": choices,
                    "allow_free_text": allow_free_text,
                    "source_runtime_instance_id": (
                        str(run_state.get("runtime_instance_id") or "").strip()
                        if isinstance(run_state, Mapping)
                        else ""
                    ),
                }
            )
        answer = _ask_user_answer(response)
        self._emit(
            {
                "event_type": "tool_completed",
                "tool_id": ASK_USR_TOOL_ID,
                "tool_call_id": tool_call_id,
                "arguments": public_arguments,
                "status": "completed",
                "result": {"question_id": tool_call_id, "answer": answer},
                "output": {"question_id": tool_call_id, "answer": answer},
            }
        )
        return [
            tool_observation_message(
                status="completed",
                tool_id=ASK_USR_TOOL_ID,
                tool_call_id=tool_call_id,
                message="User answered the question.",
                arguments=arguments,
                output={"question_id": tool_call_id, "answer": answer},
                evidence={"interaction": "ask_user"},
                retryable=False,
            )
        ]

    def _approval_requests_for_batch(
        self,
        batch: Sequence[dict[str, Any]],
        *,
        state: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if current_tool_approval_override() is not None:
            return []
        requests: list[dict[str, Any]] = []
        for call in batch:
            tool_id = str(call.get("name") or "")
            if self.allowed_tool_ids is not None and tool_id not in self.allowed_tool_ids:
                continue
            approval_request = self._approval_request_by_name.get(tool_id)
            if approval_request is None:
                continue
            tool_call_id = str(call.get("id") or tool_id)
            with tool_call_context(
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                origin_node_id=self.origin_node_id,
                origin_impl=self.origin_impl,
            ):
                request = approval_request(dict(call.get("args") or {}), tool_call_id=tool_call_id)
            if isinstance(request, dict):
                requests.append(request)
        return requests

    def _invoke_native_tool_node(
        self,
        state: Mapping[str, Any],
        *,
        config: RunnableConfig,
        runtime: Runtime,
    ) -> Any:
        return self._tool_node.invoke(state, config, runtime=runtime or Runtime())

    def _wrap_tool_call(self, request: ToolCallRequest, execute: Callable[[ToolCallRequest], Any]) -> Any:
        tool_call = dict(request.tool_call)
        tool_id = str(tool_call.get("name") or "")
        tool_call_id = str(tool_call.get("id") or tool_id)
        arguments = dict(tool_call.get("args") or {})
        public_arguments = self._public_arguments(tool_id, arguments)
        if self.allowed_tool_ids is not None and tool_id not in self.allowed_tool_ids:
            message = "Tool is not visible to this node."
            payload = _observation_payload(
                status="tool_not_allowed",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                message=message,
                arguments=public_arguments,
                output={"visible_tool_ids": sorted(self.allowed_tool_ids)},
                retryable=True,
            )
            self._emit(
                {
                    "event_type": "tool_failed",
                    "tool_id": tool_id,
                    "tool_call_id": tool_call_id,
                    "arguments": public_arguments,
                    "status": "failed",
                    "error": message,
                    "observation": payload,
                    "message": message,
                }
            )
            return _tool_message(tool_id=tool_id, tool_call_id=tool_call_id, payload=payload, status="error")
        self._emit(
            {
                "event_type": "tool_proposed",
                "tool_id": tool_id,
                "tool_call_id": tool_call_id,
                "arguments": public_arguments,
                "status": "proposed",
            }
        )
        started_at = datetime.now(timezone.utc).isoformat()
        with tool_call_context(
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            origin_node_id=self.origin_node_id,
            origin_impl=self.origin_impl,
            event_sink=self._emit,
        ):
            result = execute(request)
        completed_at = datetime.now(timezone.utc).isoformat()
        if isinstance(result, ToolMessage):
            normalized = _normalize_tool_message(
                result,
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                arguments=public_arguments,
            )
            event_type = _tool_event_type(normalized)
            public_normalized = _public_tool_observation(normalized)
            self._emit(
                {
                    "event_type": event_type,
                    "tool_id": tool_id,
                    "tool_call_id": tool_call_id,
                    "arguments": public_arguments,
                    "status": "completed" if event_type in {"tool_completed", "tool_contract_invalid"} else "failed",
                    "result": public_normalized,
                    "output": public_normalized.get("output"),
                    "evidence": public_normalized.get("evidence") if isinstance(public_normalized.get("evidence"), dict) else {},
                    "execution_status": str(normalized.get("execution_status") or ""),
                    "contract_status": str(normalized.get("contract_status") or ""),
                    "observation": public_normalized,
                    "error": None if event_type in {"tool_completed", "tool_contract_invalid"} else normalized.get("message"),
                    "message": str(normalized.get("message") or ""),
                }
            )
            return _tool_message(
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                payload=normalized,
                status="success" if event_type in {"tool_completed", "tool_contract_invalid"} else "error",
                timing={"started_at": started_at, "completed_at": completed_at},
            )
        self._emit(
            {
                "event_type": "tool_completed",
                "tool_id": tool_id,
                "tool_call_id": tool_call_id,
                "arguments": public_arguments,
                "status": "completed",
                "message": "Tool returned a LangGraph command.",
            }
        )
        return result

    def _public_arguments(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        redacted = redact_json_pointer_paths(
            arguments,
            self._sensitive_argument_paths_by_name.get(tool_id, []),
        )
        return redacted if isinstance(redacted, dict) else {}

    def _emit(self, payload: dict[str, Any]) -> None:
        payload = {"node_id": self.node_id, **payload}
        if self.emit_event is not None:
            self.emit_event(payload)
        if self.stream_events:
            emit_runtime_tool_activity(payload, node_id=self.node_id)


def build_tool_node_runner(
    tools: Sequence[BaseTool],
    *,
    node_id: str,
    name: str | None = None,
    messages_key: str = "messages",
    allowed_tool_ids: set[str] | None = None,
    known_tool_ids: set[str] | None = None,
    origin_node_id: str = "",
    origin_impl: str = "",
    emit_event: ToolEventCallback | None = None,
    stream_events: bool = False,
) -> ComboToolNode:
    return ComboToolNode(
        tools,
        node_id=node_id,
        name=name,
        messages_key=messages_key,
        allowed_tool_ids=allowed_tool_ids,
        known_tool_ids=known_tool_ids,
        origin_node_id=origin_node_id,
        origin_impl=origin_impl,
        emit_event=emit_event,
        stream_events=stream_events,
    )


def _tool_approval_request(tool: BaseTool) -> Callable[..., dict[str, Any] | None] | None:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    combo = metadata.get("combo")
    if not isinstance(combo, dict):
        return None
    approval_request = combo.get("approval_request")
    return approval_request if callable(approval_request) else None


def _tool_trust_handler(tool: BaseTool) -> Callable[[str], None] | None:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    combo = metadata.get("combo")
    if not isinstance(combo, dict):
        return None
    trust_tool = combo.get("trust_tool")
    return trust_tool if callable(trust_tool) else None


def _tool_sensitive_argument_paths(tool: BaseTool) -> list[str]:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return []
    combo = metadata.get("combo")
    if not isinstance(combo, dict):
        return []
    paths = combo.get("sensitive_argument_paths")
    return [str(item) for item in paths] if isinstance(paths, list) else []


def _batch_approval_payload(requests: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "tool_approval",
        "message": "检测到需要人工确认的工具调用，请确认执行、拒绝、信任工具，或输入审查意见让模型重写工具调用。",
        "choices": {"approve": "-y", "deny": "-n", "trust_tool": "-t", "revise": "custom"},
        "requests": [dict(request) for request in requests],
    }


def _approval_rejection_messages(
    tool_calls: Sequence[dict[str, Any]],
    action: str,
    guidance: str,
) -> list[ToolMessage]:
    status = "revision_requested" if action == "revise" else "denied"
    message = "Human requested argument revision before execution." if action == "revise" else "Tool call denied by human review."
    if guidance:
        message = f"{message} {guidance}"
    return [
        tool_observation_message(
            status=status,
            tool_id=str(call.get("name") or ""),
            tool_call_id=str(call.get("id") or call.get("name") or ""),
            message=message,
            arguments=dict(call.get("args") or {}),
            retryable=True,
        )
        for call in tool_calls
    ]


def _is_trust_tool_decision(decision: Any) -> bool:
    if isinstance(decision, str):
        return decision.strip().lower() in TRUST_TOOL_ACTIONS or decision.strip().lower() in {"-t", "t", "trust me"}
    if isinstance(decision, dict):
        action = str(decision.get("action") or decision.get("choice") or "").strip().lower()
        if action in TRUST_TOOL_ACTIONS:
            return True
        return bool(decision.get("trust_tool") or decision.get("no_approval"))
    return False


def latest_ai_tool_calls(messages: Sequence[Any]) -> tuple[AIMessage | None, list[dict[str, Any]]]:
    following_tool_message_ids: set[str] = set()
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            tool_call_id = str(getattr(message, "tool_call_id", "") or "")
            if tool_call_id:
                following_tool_message_ids.add(tool_call_id)
            continue
        if not isinstance(message, AIMessage):
            continue
        normalized = _declared_ai_tool_calls(message)
        unresolved = [
            call
            for call in normalized
            if str(call.get("id") or "") and str(call.get("id") or "") not in following_tool_message_ids
        ]
        return message, unresolved
    return None, []


def latest_ai_declared_tool_calls(messages: Sequence[Any]) -> tuple[AIMessage | None, list[dict[str, Any]]]:
    """Return every tool call declared by the latest AI message, including completed calls."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message, _declared_ai_tool_calls(message)
    return None, []


def _declared_ai_tool_calls(message: AIMessage) -> list[dict[str, Any]]:
    calls = [
        *list(getattr(message, "tool_calls", None) or []),
        *list(getattr(message, "invalid_tool_calls", None) or []),
    ]
    origin_node_id = _message_origin_node_id(message)
    origin_impl = _message_origin_impl(message)
    return [
        _normalize_tool_call(item, index=index, origin_node_id=origin_node_id, origin_impl=origin_impl)
        for index, item in enumerate(calls)
    ]


def _partition_invalid_tool_calls(tool_calls: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    invalid: list[dict[str, Any]] = []
    executable: list[dict[str, Any]] = []
    for call in tool_calls:
        if call.get("invalid_tool_call"):
            invalid.append(dict(call))
        else:
            executable.append(dict(call))
    return invalid, executable


def _invalid_tool_call_messages(tool_calls: Sequence[dict[str, Any]]) -> list[ToolMessage]:
    messages: list[ToolMessage] = []
    for call in tool_calls:
        tool_id = str(call.get("name") or "")
        tool_call_id = str(call.get("id") or tool_id)
        raw_args = str(call.get("raw_args") or "")
        error = str(call.get("error") or "").strip()
        details = "The model emitted an invalid native tool call. Retry the same intent with valid JSON tool arguments."
        if error:
            details = f"{details} Parser error: {error}"
        messages.append(
            tool_observation_message(
                status="invalid_tool_call",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                message=details,
                arguments={"raw_args": raw_args} if raw_args else {},
                retryable=True,
                errors=[error] if error else [],
            )
        )
    return messages


def _complete_tool_message_set(
    tool_calls: Sequence[dict[str, Any]],
    messages: Sequence[ToolMessage],
) -> list[ToolMessage]:
    by_call_id: dict[str, ToolMessage] = {}
    for message in messages:
        tool_call_id = str(getattr(message, "tool_call_id", "") or "")
        if tool_call_id and tool_call_id not in by_call_id:
            by_call_id[tool_call_id] = message
    completed: list[ToolMessage] = []
    for call in tool_calls:
        tool_id = str(call.get("name") or "")
        tool_call_id = str(call.get("id") or tool_id)
        if tool_call_id in by_call_id:
            completed.append(by_call_id[tool_call_id])
            continue
        completed.append(
            tool_observation_message(
                status="execution_failed",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                message="ToolNode did not return an observation for this tool call.",
                arguments=dict(call.get("args") or {}),
                retryable=True,
            )
        )
    return completed


def tool_messages_to_runtime_patch(
    messages: Sequence[ToolMessage],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str]:
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    policy_patch: dict[str, Any] = {}
    route_decision = "tool.completed"
    for message in messages:
        payload = _parse_tool_message_content(message.content)
        if not isinstance(payload, dict):
            payload = _observation_payload(
                status="completed" if getattr(message, "status", "success") != "error" else "execution_failed",
                tool_id=str(message.name or ""),
                tool_call_id=str(message.tool_call_id or ""),
                message=str(message.content),
                arguments={},
                output={"value": message.content},
                retryable=getattr(message, "status", "success") == "error",
            )
        if _observation_completed(payload):
            results.append(payload)
            continue
        failures.append(payload)
        if route_decision == "tool.completed":
            route_decision = "tool.failed"
    return results, failures, policy_patch, route_decision


def tool_observation_message(
    *,
    status: str,
    tool_id: str,
    tool_call_id: str,
    message: str,
    arguments: dict[str, Any],
    retryable: bool,
    output: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    execution_status: str | None = None,
    contract_status: str | None = None,
    errors: list[str] | None = None,
) -> ToolMessage:
    return _tool_message(
        tool_id=tool_id,
        tool_call_id=tool_call_id,
        status="success" if status == "completed" else "error",
        payload=_observation_payload(
            status=status,
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            message=message,
            arguments=arguments,
            retryable=retryable,
            output=output,
            evidence=evidence,
            execution_status=execution_status,
            contract_status=contract_status,
            errors=errors,
        ),
    )


def _tool_call_batches(
    tool_calls: Sequence[dict[str, Any]],
    concurrent_by_name: Mapping[str, bool],
    max_parallel_by_name: Mapping[str, int],
    serialization_key_by_name: Mapping[str, str | None],
) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    batch_keys: list[set[str]] = []
    batch_counts: list[dict[str, int]] = []
    for call in tool_calls:
        tool_id = str(call.get("name") or "")
        serialization_key = serialization_key_by_name.get(tool_id)
        conflict_key = (
            serialization_key
            if serialization_key is not None
            else (None if concurrent_by_name.get(tool_id, True) else f"tool:{tool_id}")
        )
        maximum = max_parallel_by_name.get(tool_id, 1)
        for index, batch in enumerate(batches):
            if conflict_key is not None and conflict_key in batch_keys[index]:
                continue
            if batch_counts[index].get(tool_id, 0) >= maximum:
                continue
            batch.append(call)
            if conflict_key is not None:
                batch_keys[index].add(conflict_key)
            batch_counts[index][tool_id] = batch_counts[index].get(tool_id, 0) + 1
            break
        else:
            batches.append([call])
            batch_keys.append({conflict_key} if conflict_key is not None else set())
            batch_counts.append({tool_id: 1})
    return batches


def _replace_latest_ai_tool_calls(
    messages: Sequence[Any],
    target: AIMessage,
    tool_calls: Sequence[dict[str, Any]],
) -> list[Any]:
    replaced = list(messages)
    for index in range(len(replaced) - 1, -1, -1):
        if replaced[index] is not target:
            continue
        replaced[index] = AIMessage(
            content=target.content,
            additional_kwargs=dict(target.additional_kwargs),
            response_metadata=dict(target.response_metadata),
            name=target.name,
            id=target.id,
            tool_calls=[_langchain_tool_call(item) for item in tool_calls],
        )
        break
    return replaced


def _messages_from_tool_node_output(output: Any, messages_key: str) -> list[ToolMessage]:
    if isinstance(output, dict):
        candidates = output.get(messages_key) or []
    elif isinstance(output, list):
        candidates = output
    else:
        candidates = []
    return [item for item in candidates if isinstance(item, ToolMessage)]


def _tool_concurrent(tool: BaseTool) -> bool:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return True
    combo = metadata.get("combo")
    if not isinstance(combo, dict):
        return True
    return bool(combo.get("concurrent", True))


def _split_ask_user_batch(
    batch: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ask_calls = [call for call in batch if str(call.get("name") or "") == ASK_USR_TOOL_ID]
    if not ask_calls:
        return [], [dict(call) for call in batch]
    ordinary_calls = [
        dict(call)
        for call in batch
        if str(call.get("name") or "") != ASK_USR_TOOL_ID
    ]
    return [dict(call) for call in ask_calls], ordinary_calls


def _ask_user_choices(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    choices: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        option_value = str(item.get("value") or "").strip()
        label = str(item.get("label") or option_value).strip()
        if not option_value or not label:
            continue
        option = {"value": option_value, "label": label}
        description = str(item.get("description") or "").strip()
        if description:
            option["description"] = description
        choices.append(option)
    return choices


def _ask_user_answer(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("answer") or value.get("response") or value.get("value")
    answer = str(value or "").strip()
    if not answer:
        raise ValueError("ask_usr resume requires a non-empty answer")
    return answer


def _tool_serialization_key(tool: BaseTool) -> str | None:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    combo = metadata.get("combo")
    if not isinstance(combo, dict):
        return None
    value = str(combo.get("serialization_key") or "").strip()
    return value or None


def _tool_max_parallel_calls(tool: BaseTool) -> int:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return 1
    combo = metadata.get("combo")
    if not isinstance(combo, dict):
        return 1
    value = combo.get("max_parallel_calls", 1)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else 1


def _normalize_tool_call(
    item: Any,
    *,
    index: int,
    origin_node_id: str = "",
    origin_impl: str = "",
) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    name = str(item.get("name") or item.get("tool_id") or "")
    args = item.get("args") or item.get("arguments") or {}
    invalid = str(item.get("type") or "") == "invalid_tool_call"
    return {
        "name": name,
        "args": dict(args) if isinstance(args, dict) else {},
        "id": str(item.get("id") or item.get("tool_call_id") or f"call_{index}_{name}"),
        "type": "tool_call",
        "origin_node_id": str(item.get("origin_node_id") or origin_node_id or ""),
        "origin_impl": str(item.get("origin_impl") or origin_impl or ""),
        "invalid_tool_call": invalid,
        "raw_args": args if invalid and isinstance(args, str) else "",
        "error": str(item.get("error") or "") if invalid else "",
    }


def _message_origin_node_id(message: AIMessage) -> str:
    kwargs = getattr(message, "additional_kwargs", None)
    return str(kwargs.get("combo_origin_node_id") or "") if isinstance(kwargs, dict) else ""


def _message_origin_impl(message: AIMessage) -> str:
    kwargs = getattr(message, "additional_kwargs", None)
    return str(kwargs.get("combo_origin_impl") or "") if isinstance(kwargs, dict) else ""


def _langchain_tool_call(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(item.get("name") or ""),
        "args": dict(item.get("args") or {}),
        "id": str(item.get("id") or item.get("name") or ""),
        "type": "tool_call",
    }


def _normalize_tool_message(
    message: ToolMessage,
    *,
    tool_id: str,
    tool_call_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    payload = _parse_tool_message_content(message.content)
    if not isinstance(payload, dict):
        return _observation_payload(
            status="completed" if getattr(message, "status", "success") != "error" else "execution_failed",
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            message=str(message.content),
            arguments=arguments,
            output={"value": message.content},
            retryable=getattr(message, "status", "success") == "error",
        )
    if payload.get("type") != "tool_observation":
        return _observation_payload(
            status=str(payload.get("status") or "completed"),
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            message=str(payload.get("message") or "Tool execution completed."),
            arguments=arguments,
            output=payload,
            retryable=False,
        )
    payload = dict(payload)
    payload["tool_id"] = str(payload.get("tool_id") or tool_id)
    payload["tool_call_id"] = str(payload.get("tool_call_id") or tool_call_id)
    if not isinstance(payload.get("arguments"), dict):
        payload["arguments"] = arguments
    return payload


def _parse_tool_message_content(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                return _parse_tool_message_content(text)
    return content


def _observation_completed(payload: dict[str, Any]) -> bool:
    if payload.get("status") != "completed":
        return False
    if payload.get("type") == "tool_observation":
        return True
    return True


def _tool_event_type(payload: dict[str, Any]) -> str:
    if _observation_completed(payload):
        return "tool_completed"
    if payload.get("execution_status") == "completed" and payload.get("contract_status") == "invalid":
        return "tool_contract_invalid"
    return "tool_failed"


def _tool_message(
    *,
    tool_id: str,
    tool_call_id: str,
    payload: dict[str, Any],
    status: str = "success",
    timing: dict[str, str] | None = None,
) -> ToolMessage:
    public_payload, image = _tool_observation_image(payload)
    additional_kwargs: dict[str, Any] = {}
    if image is not None:
        image_path, mime_type = image
        additional_kwargs["combo_tool_image"] = {
            "path": image_path,
            "mime_type": mime_type,
        }
    if timing:
        additional_kwargs["combo_tool_timing"] = dict(timing)
    return ToolMessage(
        content=json.dumps(public_payload, ensure_ascii=False, sort_keys=True),
        name=tool_id,
        tool_call_id=tool_call_id,
        status=status,  # type: ignore[arg-type]
        additional_kwargs=additional_kwargs,
    )


def _public_tool_observation(payload: dict[str, Any]) -> dict[str, Any]:
    public_payload, _image = _tool_observation_image(payload)
    return public_payload


def _tool_observation_image(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, str] | None]:
    public_payload = deepcopy(payload)
    output = public_payload.get("output")
    if not isinstance(output, dict):
        return public_payload, None
    image_reference = output.pop("model_image", None)
    if not isinstance(image_reference, dict):
        return public_payload, None
    mime_type = image_reference.get("mime_type")
    image_path = image_reference.get("path")
    if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
        return public_payload, None
    if not isinstance(image_path, str) or not image_path:
        return public_payload, None
    return public_payload, (image_path, mime_type)


def _observation_payload(
    *,
    status: str,
    tool_id: str,
    tool_call_id: str,
    message: str,
    arguments: dict[str, Any],
    retryable: bool,
    output: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    execution_status: str | None = None,
    contract_status: str | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "tool_observation",
        "status": status,
        "tool_id": tool_id,
        "tool_call_id": tool_call_id,
        "message": message,
        "retryable": retryable,
        "arguments": arguments,
        "output": output,
        "evidence": evidence or {},
        "execution_status": execution_status or ("completed" if status == "completed" else "failed"),
        "contract_status": contract_status or "valid",
        "errors": errors if errors is not None else ([] if status == "completed" else [message]),
    }
