from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VllmLaunchConfig:
    model_path: Path
    tokenizer_path: Path | None
    served_model_name: str
    host: str
    port: int
    dtype: str
    tensor_parallel_size: int
    max_model_len: int | None = None
    quantization: str | None = None
    gpu_memory_utilization: float | None = None
    trust_remote_code: bool = False

    def validate(self) -> None:
        if not self.model_path.is_dir():
            raise ValueError(f"local model directory does not exist: {self.model_path}")
        if self.tokenizer_path is not None and not self.tokenizer_path.is_dir():
            raise ValueError(f"local tokenizer directory does not exist: {self.tokenizer_path}")
        if not self.served_model_name.strip():
            raise ValueError("served_model_name is required")
        if not 1 <= self.port <= 65535:
            raise ValueError("vLLM port must be between 1 and 65535")
        if self.tensor_parallel_size < 1:
            raise ValueError("tensor_parallel_size must be at least one")
        if self.max_model_len is not None and self.max_model_len < 1:
            raise ValueError("max_model_len must be positive")
        if self.gpu_memory_utilization is not None and not 0 < self.gpu_memory_utilization <= 1:
            raise ValueError("gpu_memory_utilization must be in (0, 1]")


def build_vllm_command(config: VllmLaunchConfig) -> list[str]:
    config.validate()
    command = [
        "python",
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        str(config.model_path.resolve()),
        "--served-model-name",
        config.served_model_name,
        "--host",
        config.host,
        "--port",
        str(config.port),
        "--dtype",
        config.dtype,
        "--tensor-parallel-size",
        str(config.tensor_parallel_size),
    ]
    if config.tokenizer_path is not None:
        command.extend(["--tokenizer", str(config.tokenizer_path.resolve())])
    if config.max_model_len is not None:
        command.extend(["--max-model-len", str(config.max_model_len)])
    if config.quantization:
        command.extend(["--quantization", config.quantization])
    if config.gpu_memory_utilization is not None:
        command.extend(["--gpu-memory-utilization", str(config.gpu_memory_utilization)])
    if config.trust_remote_code:
        command.append("--trust-remote-code")
    return command
