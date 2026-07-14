from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RocmDeviceInfo:
    index: int
    name: str
    total_memory_bytes: int


@dataclass(frozen=True, slots=True)
class RocmRuntimeInfo:
    available: bool
    torch_version: str
    hip_version: str
    device_count: int
    devices: tuple[RocmDeviceInfo, ...]
    error: str = ""

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def inspect_rocm_runtime(*, require_available: bool = False) -> RocmRuntimeInfo:
    try:
        import torch
    except ImportError as exc:
        info = RocmRuntimeInfo(False, "", "", 0, (), "PyTorch is not installed")
        return _require(info, require_available=require_available, cause=exc)

    hip_version = str(getattr(torch.version, "hip", "") or "")
    torch_version = str(getattr(torch, "__version__", "") or "")
    if not hip_version:
        info = RocmRuntimeInfo(False, torch_version, "", 0, (), "PyTorch is not a ROCm build")
        return _require(info, require_available=require_available)
    if not torch.cuda.is_available():
        info = RocmRuntimeInfo(False, torch_version, hip_version, 0, (), "ROCm device is not available")
        return _require(info, require_available=require_available)

    devices: list[RocmDeviceInfo] = []
    for index in range(torch.cuda.device_count()):
        properties = torch.cuda.get_device_properties(index)
        devices.append(
            RocmDeviceInfo(
                index=index,
                name=str(properties.name),
                total_memory_bytes=int(properties.total_memory),
            )
        )
    info = RocmRuntimeInfo(True, torch_version, hip_version, len(devices), tuple(devices))
    return _require(info, require_available=require_available)


def _require(
    info: RocmRuntimeInfo,
    *,
    require_available: bool,
    cause: Exception | None = None,
) -> RocmRuntimeInfo:
    if require_available and not info.available:
        error = RuntimeError(info.error or "ROCm runtime is unavailable")
        if cause is not None:
            raise error from cause
        raise error
    return info
