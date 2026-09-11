"""Verify that a steered user message carries its attachments into the model input.

Run with: .venv/bin/python scripts/verify_steering_attachments.py
"""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from combo.dynamic_runtime.run_control import RuntimeInputInjection
from combo.runtime_kernel.fixed_runner import (
    _apply_steered_inputs,
    _injected_messages,
)
from combo.runtime_kernel.model_inputs import build_runtime_model_input
from combo.runtime_kernel.state.schema import RuntimeState


def main() -> None:
    try:
        _verify_model_input()
        _verify_handler_wiring()
    finally:
        Path("tmp/steering-attachment.png").unlink(missing_ok=True)
    print("steering attachment verification passed")


class _FakeCommands:
    def __init__(self, payload, receipt) -> None:
        self._payload = payload
        self._receipt = receipt

    def message_command_payload(self, **_kwargs):
        return self._payload, self._receipt

    def complete_queued_as_steering(self, **_kwargs):
        return self._receipt


class _FakeRuntimeInstances:
    def __init__(self, instance) -> None:
        self._instance = instance

    def active_main_for_session(self, **_kwargs):
        return self._instance


class _FakeRunControls:
    def __init__(self) -> None:
        self.injections = []

    def submit_input(self, *, runtime_instance_id, injection, on_checkpointed=None):
        self.injections.append((runtime_instance_id, injection))
        return True

    def request_tool_interrupt(self, **_kwargs):
        return True

    def request_generation_interrupt(self, **_kwargs):
        return True

    def revoke_input(self, **_kwargs):
        return None


class _FakeAttachmentResolver:
    def __init__(self) -> None:
        self.calls = []

    def resolve_runtime_attachments(self, **kwargs):
        self.calls.append(kwargs)
        return (
            {
                "attachment_id": "att-steer",
                "display_name": "chart.png",
                "path": ".combo/attachments/run-1/chart.png",
                "runtime_path": ".combo/attachments/run-1/chart.png",
                "mime_type": "image/png",
            },
        )


def _verify_handler_wiring() -> None:
    """The steer command must hand the queued attachments to the active runtime."""
    import asyncio

    from combo.dynamic_runtime.steering import SteerRuntimeCommandHandler
    from combo.runtime_protocol import (
        AttachmentRevisionRef,
        CommandEnvelope,
        CommandReceipt,
        SteerRuntimeRequestPayload,
    )
    from combo.runtime_protocol.commands import SendMessagePayload

    reference = AttachmentRevisionRef(
        attachment_id="att-steer",
        revision=1,
        content_digest="digest",
    )
    message = SendMessagePayload(
        message_id="msg-queued",
        content="改成表格",
        attachments=(reference,),
    )
    receipt = CommandReceipt.model_validate(
        {
            "command_id": "cmd-queued",
            "client_instance_id": "client",
            "principal_id": "principal",
            "session_id": "session-1",
            "status": "queued",
            "receipt_revision": 1,
            "updated_at": "2026-09-11T00:00:00Z",
        }
    )
    instance = SimpleNamespace(
        runtime_instance_id="run-1",
        request=SimpleNamespace(workspace_id="workspace-1"),
    )
    controls = _FakeRunControls()
    attachments = _FakeAttachmentResolver()
    handler = SteerRuntimeCommandHandler(
        commands=_FakeCommands(message, receipt),
        runtime_instances=_FakeRuntimeInstances(instance),
        run_controls=controls,
        attachments=attachments,
    )
    envelope = CommandEnvelope(
        protocol_version="1",
        command_id="cmd-steer",
        client_instance_id="client",
        principal_id="principal",
        session_id="session-1",
        payload=SteerRuntimeRequestPayload(queued_command_id="cmd-queued"),
    )
    outcome = asyncio.run(handler.handle(envelope, receipt))
    assert outcome.status == "completed", outcome
    assert attachments.calls and attachments.calls[0]["runtime_instance_id"] == "run-1", attachments.calls
    assert attachments.calls[0]["references"] == (reference,), attachments.calls
    assert controls.injections, "the active runtime received no injection"
    injected = controls.injections[0][1]
    assert injected.content == "改成表格", injected.content
    assert [item["attachment_id"] for item in injected.attachments] == ["att-steer"], injected.attachments


def _verify_model_input() -> None:
    image_path = Path("tmp/steering-attachment.png")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
        )
    )

    state = RuntimeState.model_validate(
        {
            "run": {
                "run_id": "run-1",
                "runtime_instance_id": "run-1",
                "session_id": "session-1",
                "workspace_id": "workspace-1",
                "strategy": "react",
            },
            "runtime_config": {
                "system_prompt": "system",
                "locale": "zh-CN",
                "attachments": [
                    {
                        "attachment_id": "att-original",
                        "display_name": "brief.txt",
                        "path": "brief.txt",
                        "runtime_path": "brief.txt",
                        "mime_type": "text/plain",
                        "extracted_text": "原始需求正文",
                    }
                ],
            },
            "conversation": {
                "current_user_input": "先看这份简报",
                "current_user_input_id": "msg-original",
            },
        }
    )

    injection = RuntimeInputInjection(
        injection_id="cmd-steer-1",
        role="user",
        content="改成表格，参考这张图",
        attachments=(
            {
                "attachment_id": "att-steer",
                "display_name": "chart.png",
                "path": "chart.png",
                "runtime_path": "chart.png",
                "mime_type": "image/png",
            },
        ),
    )

    messages = [
        HumanMessage(id="msg-original", content="先看这份简报"),
        AIMessage(id="ai-1", content="", tool_calls=[{"id": "call-1", "name": "rg", "args": {}}]),
        ToolMessage(id="tool-1", content="ok", tool_call_id="call-1"),
    ]

    injected = _injected_messages((injection,))
    assert injected, "steered input produced no message"
    _apply_steered_inputs(state, (injection,))

    assert state.conversation.current_user_input == "改成表格，参考这张图", state.conversation.current_user_input
    attachment_ids = [item["attachment_id"] for item in state.runtime_config.attachments]
    assert attachment_ids == ["att-original", "att-steer"], attachment_ids

    envelope = build_runtime_model_input(
        state=state,
        system_prompt="system",
        messages=[*messages, *injected],
        tools=[],
        workspace_path_resolver=lambda value: image_path.resolve() if value == "chart.png" else Path(value),
        image_input_enabled=True,
    )

    steered = [
        message
        for message in envelope.messages
        if isinstance(message, HumanMessage) and message.id == "cmd-steer-1"
    ]
    assert len(steered) == 1, "steered message missing from the model input"
    content = steered[0].content
    assert isinstance(content, list), f"steered content is not multimodal: {content!r}"
    text = "\n".join(
        str(block.get("text") or "") for block in content if isinstance(block, dict) and block.get("type") == "text"
    )
    assert "改成表格，参考这张图" in text, text
    assert "chart.png" in text, text
    images = [block for block in content if isinstance(block, dict) and block.get("type") == "image"]
    assert images, f"steered message has no image block: {content!r}"

    original = [
        message
        for message in envelope.messages
        if isinstance(message, HumanMessage) and message.id == "msg-original"
    ]
    assert original, "original user message missing"

    # An attachment-only steer must still be injected.
    attachment_only = RuntimeInputInjection(
        injection_id="cmd-steer-2",
        role="user",
        content="",
        attachments=({"attachment_id": "att-2", "display_name": "a.png", "path": "chart.png", "mime_type": "image/png"},),
    )
    assert _injected_messages((attachment_only,)), "attachment-only steer produced no message"

    # Plain text steering keeps the previous behaviour.
    text_only = RuntimeInputInjection(injection_id="cmd-steer-3", role="user", content="继续")
    assert len(_injected_messages((text_only,))) == 1


if __name__ == "__main__":
    main()
