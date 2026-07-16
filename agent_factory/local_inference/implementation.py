from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


LlamaImplementationId = Literal["official", "amd"]
LLAMA_IMPLEMENTATION_IDS: tuple[LlamaImplementationId, ...] = ("official", "amd")


class LlamaImplementationBuild(BaseModel):
    model_config = ConfigDict(extra="forbid")

    implementation: LlamaImplementationId
    display_name: str
    source_revision: str
    source_sha256: str
    binary_path: str
    binary_sha256: str
    custom_kernels: bool = False
    optimization_status: Literal["baseline", "placeholder", "optimized"]
    build_options: dict[str, Any] = Field(default_factory=dict)
    built_at: str


class LlamaImplementationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    active: LlamaImplementationId | None = None
    active_build: LlamaImplementationBuild | None = None
    builds: list[LlamaImplementationBuild] = Field(default_factory=list)
    error: str = ""


def inspect_llama_implementations() -> LlamaImplementationStatus:
    configured_root = str(os.environ.get("AGENTFACTORY_LLAMA_IMPLEMENTATION_ROOT") or "").strip()
    if not configured_root:
        return LlamaImplementationStatus(error="llama.cpp implementation root is not configured")
    root = Path(configured_root).expanduser().resolve()
    try:
        builds = [
            build
            for implementation in LLAMA_IMPLEMENTATION_IDS
            if (build := _read_manifest(root, implementation)) is not None
        ]
        active = _read_active_implementation(root)
        active_build = next(
            (item for item in builds if item.implementation == active),
            None,
        )
        return LlamaImplementationStatus(
            available=active_build is not None,
            active=active,
            active_build=active_build,
            builds=builds,
            error="" if active_build is not None else "active llama.cpp build is unavailable",
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return LlamaImplementationStatus(error=f"{type(exc).__name__}: {exc}")


def _read_active_implementation(root: Path) -> LlamaImplementationId | None:
    path = root / "active-implementation"
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    if value not in LLAMA_IMPLEMENTATION_IDS:
        raise ValueError(f"unsupported active llama.cpp implementation: {value}")
    return value


def _read_manifest(
    root: Path,
    implementation: LlamaImplementationId,
) -> LlamaImplementationBuild | None:
    path = root / "builds" / implementation / "manifest.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return LlamaImplementationBuild.model_validate(payload)
