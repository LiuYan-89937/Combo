from __future__ import annotations

from typing import Any

class RuntimeToolExecutionCancelled(RuntimeError):
    pass


class RuntimeToolExecutionTimedOut(TimeoutError):
    pass


class RuntimeModelGenerationInterrupted(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        partial_text: str = "",
        reasoning_content: str = "",
        partial_tool_calls: tuple[dict[str, Any], ...] = (),
        stream_id: str = "",
        input_injections: tuple[Any, ...] = (),
    ) -> None:
        super().__init__(message)
        self.partial_text = str(partial_text or "")
        self.reasoning_content = str(reasoning_content or "")
        self.partial_tool_calls = tuple(
            dict(call)
            for call in (partial_tool_calls or ())
            if isinstance(call, dict)
        )
        self.stream_id = str(stream_id or "").strip()
        self.input_injections = tuple(input_injections or ())


