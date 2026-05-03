from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ModelConfigError(ValueError):
    """Raised when model configuration is missing or invalid."""


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _to_int(value: str | None, default: int) -> int:
    if _blank_to_none(value) is None:
        return default
    return int(value)  # type: ignore[arg-type]


def _to_float(value: str | None, default: float) -> float:
    if _blank_to_none(value) is None:
        return default
    return float(value)  # type: ignore[arg-type]


class ModelConfig(BaseModel):
    """Runtime-safe model configuration.

    Secrets are represented with ``SecretStr`` so repr/model_dump do not expose raw keys.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    provider: Literal["openai_compatible_chat", "fake"] = "openai_compatible_chat"
    base_url: str | None = None
    api_key: SecretStr | None = None
    model: str | None = None
    timeout_seconds: int = Field(default=60, ge=1)
    temperature: float = Field(default=0.2, ge=0)
    max_output_tokens: int = Field(default=2048, ge=1)
    thinking: Literal["enabled", "disabled"] | None = None

    @field_validator("base_url", mode="before")
    @classmethod
    def _normalize_base_url(cls, value: str | None) -> str | None:
        if value:
            return value.rstrip("/")
        return value

    @classmethod
    def from_env(
        cls,
        env_file: str | Path = ".env",
        environ: Mapping[str, str] | None = None,
        *,
        validate_required: bool = True,
    ) -> "ModelConfig":
        env_path = Path(env_file)
        file_values = _parse_env_file(env_path)
        runtime_values = dict(os.environ if environ is None else environ)
        values = {**file_values, **runtime_values}

        config = cls(
            provider=values.get("AGENTFACTORY_LLM_PROVIDER", "openai_compatible_chat"),
            base_url=_blank_to_none(values.get("AGENTFACTORY_OPENAI_BASE_URL")),
            api_key=(
                SecretStr(api_key)
                if (api_key := _blank_to_none(values.get("AGENTFACTORY_OPENAI_API_KEY")))
                else None
            ),
            model=_blank_to_none(values.get("AGENTFACTORY_OPENAI_MODEL")),
            timeout_seconds=_to_int(values.get("AGENTFACTORY_LLM_TIMEOUT_SECONDS"), 60),
            temperature=_to_float(values.get("AGENTFACTORY_LLM_TEMPERATURE"), 0.2),
            max_output_tokens=_to_int(values.get("AGENTFACTORY_LLM_MAX_OUTPUT_TOKENS"), 2048),
            thinking=_blank_to_none(values.get("AGENTFACTORY_LLM_THINKING")),
        )
        if validate_required:
            config.validate_required_fields()
        return config

    def validate_required_fields(self) -> None:
        if self.provider == "fake":
            return

        missing: list[str] = []
        if not self.base_url:
            missing.append("AGENTFACTORY_OPENAI_BASE_URL")
        if not self.api_key:
            missing.append("AGENTFACTORY_OPENAI_API_KEY")
        if not self.model:
            missing.append("AGENTFACTORY_OPENAI_MODEL")
        if missing:
            joined = ", ".join(missing)
            raise ModelConfigError(f"Missing required LLM configuration: {joined}")

    def safe_summary(self) -> dict[str, str | int | float | None]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key": "**********" if self.api_key else None,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "thinking": self.thinking,
        }
