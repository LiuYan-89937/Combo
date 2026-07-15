from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


BenchmarkRunStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]
BenchmarkSampleStatus = Literal["completed", "failed"]


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


class BenchmarkImplementation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    revision: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("label", "revision")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        return str(value or "").strip()


class BenchmarkRunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    profile_id: str
    prompt: str
    max_output_tokens: int = Field(default=256, ge=1, le=32768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int = Field(default=42, ge=0)
    warmup_iterations: int = Field(default=1, ge=0, le=10)
    measured_iterations: int = Field(default=3, ge=1, le=50)
    telemetry_interval_ms: int = Field(default=250, ge=100, le=2000)
    implementation: BenchmarkImplementation = Field(default_factory=BenchmarkImplementation)

    @field_validator("name", "profile_id", "prompt")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text


class BenchmarkTelemetryPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    elapsed_ms: float = Field(ge=0)
    used_memory_bytes: int | None = Field(default=None, ge=0)
    gpu_utilization_percent: float | None = None
    memory_activity_percent: float | None = None
    power_watts: float | None = None
    temperature_celsius: float | None = None


class BenchmarkSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_index: int = Field(ge=0)
    warmup: bool = False
    status: BenchmarkSampleStatus = "completed"
    started_at: str = Field(default_factory=utc_now_text)
    ttft_ms: float | None = Field(default=None, ge=0)
    end_to_end_ms: float | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    cache_tokens: int | None = Field(default=None, ge=0)
    prompt_ms: float | None = Field(default=None, ge=0)
    decode_ms: float | None = Field(default=None, ge=0)
    prompt_tokens_per_second: float | None = Field(default=None, ge=0)
    decode_tokens_per_second: float | None = Field(default=None, ge=0)
    peak_vram_bytes: int | None = Field(default=None, ge=0)
    average_gpu_utilization_percent: float | None = None
    peak_gpu_utilization_percent: float | None = None
    average_power_watts: float | None = None
    peak_power_watts: float | None = None
    peak_temperature_celsius: float | None = None
    output_text: str = ""
    finish_reason: str = ""
    telemetry: list[BenchmarkTelemetryPoint] = Field(default_factory=list)
    error: str = ""


class BenchmarkMetricStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=1)
    mean: float
    minimum: float
    maximum: float
    p50: float
    p95: float
    standard_deviation: float = Field(ge=0)


class BenchmarkSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measured_samples: int = Field(ge=0)
    successful_samples: int = Field(ge=0)
    ttft_ms: BenchmarkMetricStats | None = None
    end_to_end_ms: BenchmarkMetricStats | None = None
    prompt_tokens_per_second: BenchmarkMetricStats | None = None
    decode_tokens_per_second: BenchmarkMetricStats | None = None
    peak_vram_bytes: BenchmarkMetricStats | None = None
    average_gpu_utilization_percent: BenchmarkMetricStats | None = None
    peak_gpu_utilization_percent: BenchmarkMetricStats | None = None
    average_power_watts: BenchmarkMetricStats | None = None
    peak_power_watts: BenchmarkMetricStats | None = None


class BenchmarkRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: BenchmarkRunStatus = "queued"
    spec: BenchmarkRunSpec
    progress_completed: int = Field(default=0, ge=0)
    progress_total: int = Field(default=0, ge=0)
    environment: dict[str, Any] = Field(default_factory=dict)
    samples: list[BenchmarkSample] = Field(default_factory=list)
    summary: BenchmarkSummary | None = None
    error: str = ""
    created_at: str = Field(default_factory=utc_now_text)
    started_at: str = ""
    completed_at: str = ""
    updated_at: str = Field(default_factory=utc_now_text)
