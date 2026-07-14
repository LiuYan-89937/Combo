from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final


class ToolCallingConfigurationError(ValueError):
    """Raised when a local chat model lacks a configured vLLM tool parser."""


@dataclass(frozen=True, slots=True)
class VllmToolCallingSupport:
    model_type: str
    parser: str


_VLLM_TOOL_CALLING_SUPPORT: Final[dict[str, VllmToolCallingSupport]] = {
    "qwen3": VllmToolCallingSupport(model_type="qwen3", parser="qwen3_xml"),
    "qwen3_moe": VllmToolCallingSupport(model_type="qwen3_moe", parser="qwen3_xml"),
    "qwen3_coder": VllmToolCallingSupport(model_type="qwen3_coder", parser="qwen3_coder"),
}


def resolve_vllm_tool_call_parser(
    model_path: Path,
    *,
    tool_calling_enabled: bool,
) -> str | None:
    """Return the vLLM parser required for a tool-enabled local model.

    The model's Transformers ``config.json`` is the source of its architecture
    identity, keeping parser selection independent from artifact display names
    and filesystem layout.
    """
    if not tool_calling_enabled:
        return None

    model_type = _model_type(model_path)
    support = _VLLM_TOOL_CALLING_SUPPORT.get(model_type)
    if support is None:
        supported_model_types = ", ".join(sorted(_VLLM_TOOL_CALLING_SUPPORT))
        raise ToolCallingConfigurationError(
            "tool calling is enabled, but this model has no registered vLLM tool parser "
            f"(model_type={model_type or 'unknown'}; supported: {supported_model_types})"
        )
    return support.parser


def _model_type(model_path: Path) -> str:
    config_path = model_path / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolCallingConfigurationError(
            f"cannot read local model config for tool calling: {config_path}"
        ) from exc
    if not isinstance(config, dict):
        raise ToolCallingConfigurationError(
            f"local model config for tool calling must be a JSON object: {config_path}"
        )
    return str(config.get("model_type") or "").strip().lower()
