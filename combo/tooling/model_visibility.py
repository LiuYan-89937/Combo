from __future__ import annotations

from collections.abc import Iterable

from langchain_core.tools import BaseTool

IMAGE_INPUT_REQUIRED_TOOL_IDS = frozenset({"browser_screenshot"})


def tools_visible_to_model(
    tools: Iterable[BaseTool],
    *,
    image_input_enabled: bool,
) -> list[BaseTool]:
    candidates = list(tools)
    if image_input_enabled:
        return candidates
    return [tool for tool in candidates if tool.name not in IMAGE_INPUT_REQUIRED_TOOL_IDS]
