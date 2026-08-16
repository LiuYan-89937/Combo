from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

from combo.model_pool import ModelPoolStore
from combo.model_pool.resolver import resolve_available_chat_model
from combo.runtime_kernel.model_operations import prepare_structured_output_invocation


class ToolTranscriptionParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str = "string"
    description: str
    required: bool = True

    @field_validator("name", "description")
    @classmethod
    def _text_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("transcription parameter text must not be empty")
        return text

    @field_validator("type")
    @classmethod
    def _type_is_supported(cls, value: str) -> str:
        text = str(value or "").strip().lower()
        return text if text in {"string", "integer", "number", "boolean", "object", "array"} else "string"


class ToolTranscriptionContextParameter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    type: str = "string"
    value: str = ""

    @field_validator("name")
    @classmethod
    def _name_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("transcription context key must not be empty")
        return text

    @field_validator("type")
    @classmethod
    def _type_is_supported(cls, value: str) -> str:
        text = str(value or "").strip().lower()
        if text not in {"string", "integer", "number", "boolean", "object", "array"}:
            return "string"
        return text


class ToolTranscriptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,127}$")
    model_alias: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    display_name: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    parameters: list[ToolTranscriptionParameter] = Field(default_factory=list)
    context_parameters: list[ToolTranscriptionContextParameter] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    runtime_policy: dict[str, Any] = Field(
        default_factory=lambda: {
            "approval": "inherit",
            "risk_level": "low",
            "allow_parallel_calls": True,
            "max_parallel_calls": 1,
            "timeout_seconds": 300,
            "output_projection": "compress",
            "output_max_model_chars": 50_000,
            "retain_raw_output": True,
        }
    )
    main_source: str

    @field_validator("display_name", "description", "main_source")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("transcription result text must not be empty")
        return text


def transcribe_tool_source(
    source: str,
    *,
    filename: str,
    store: ModelPoolStore,
) -> ToolTranscriptionResult:
    """Convert a Python script into a ToolPackage draft without executing it."""

    normalized_source = str(source or "")
    if not normalized_source.strip():
        raise ValueError("Python script must not be empty")
    if len(normalized_source.encode("utf-8")) > 1_000_000:
        raise ValueError("Python script exceeds the transcription limit")
    resolved = resolve_available_chat_model("task", store=store)
    if resolved is None:
        raise RuntimeError("task_model_not_configured")
    invocation = prepare_structured_output_invocation(
        model=resolved.model,
        output_model=ToolTranscriptionResult,
        messages=[
            SystemMessage(
                content=(
                    "Rewrite the supplied Python script into a Combo ToolPackage draft. "
                    "Do not execute the script and do not claim that its behavior was tested. "
                    "Return only the requested structured object. Keep the useful behavior in "
                    "main_source, define exactly def run(arguments, context), and return a JSON "
                    "object. Infer model-callable parameters from the script. Put user-supplied "
                    "configuration such as an API key or base URL in context_parameters as key, "
                    "type, and an empty value; workspace_path, package_path, and resources_path "
                    "are always available at runtime and must not be declared. Never invent API "
                    "keys or secrets. Infer every non-standard-library Python dependency "
                    "required by main_source and return installable PyPI distribution names, "
                    "not import module names. For example, `from docx import Document` "
                    "requires `python-docx`, `from PIL` requires `pillow`, and `import yaml` "
                    "requires `PyYAML`; do not include standard-library modules. Use "
                    "lowercase kebab-case for name and lowercase snake_case for model_alias."
                )
            ),
            HumanMessage(
                content=json.dumps(
                    {
                        "filename": filename,
                        "source": normalized_source,
                    },
                    ensure_ascii=False,
                )
            ),
        ],
        model_metadata=resolved.settings.metadata(),
        config_tags=["tool-package-transcription"],
    )
    result = invocation.model.invoke(
        list(invocation.messages),
        config={"metadata": {"operation": "tool_package_transcription", "task_model_profile_id": resolved.profile_id}},
    )
    if isinstance(result, ToolTranscriptionResult):
        return result
    return ToolTranscriptionResult.model_validate(result)
