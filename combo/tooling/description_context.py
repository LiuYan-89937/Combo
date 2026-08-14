from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool

from combo.tooling.spec import ToolDescriptionContextConfig


def contextualize_tool_descriptions(
    tools: Iterable[BaseTool],
    *,
    now: datetime | None = None,
) -> list[BaseTool]:
    reference_time = now or datetime.now(UTC)
    return [
        _contextualized_tool(tool, reference_time=reference_time)
        for tool in tools
    ]


def _contextualized_tool(tool: BaseTool, *, reference_time: datetime) -> BaseTool:
    metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
    combo_metadata = metadata.get("combo")
    if not isinstance(combo_metadata, dict):
        return tool
    raw_context = combo_metadata.get("description_context")
    if not isinstance(raw_context, dict):
        return tool
    context = ToolDescriptionContextConfig.model_validate(raw_context)
    if not context.current_date:
        return tool
    base_description = str(combo_metadata.get("base_description") or tool.description).strip()
    local_time = reference_time.astimezone(ZoneInfo(context.timezone))
    time_reference = (
        "Runtime date reference: "
        f"the current date is {local_time:%Y-%m-%d}, "
        f"which is {local_time:%A}, in timezone {context.timezone}. "
        "Resolve relative date expressions such as today, tomorrow, and the next N days "
        "against this reference, and use explicit calendar dates in search queries when relevant. "
        "Do not invent or assume a different current date."
    )
    description = f"{base_description}\n\n{time_reference}" if base_description else time_reference
    return tool.model_copy(update={"description": description})
