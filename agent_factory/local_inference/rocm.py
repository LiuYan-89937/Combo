from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any


_ROCM_VERSION_PATHS = (
    Path("/opt/rocm/.info/version"),
    Path("/opt/rocm/.info/version-dev"),
)
_AMD_SMI_TIMEOUT_SECONDS = 5
_PLACEHOLDER_VALUES = {"", "n/a", "na", "none", "unknown"}


@dataclass(frozen=True, slots=True)
class RocmDeviceInfo:
    index: int
    name: str
    total_memory_bytes: int
    used_memory_bytes: int | None = None
    gpu_utilization_percent: float | None = None
    memory_activity_percent: float | None = None
    temperature_edge_celsius: float | None = None
    temperature_hotspot_celsius: float | None = None
    temperature_memory_celsius: float | None = None
    power_watts: float | None = None
    architecture: str = ""
    pci_bus: str = ""
    pci_device_id: str = ""
    vram_type: str = ""
    compute_units: int | None = None


@dataclass(frozen=True, slots=True)
class RocmRuntimeInfo:
    available: bool
    torch_version: str
    hip_version: str
    rocm_version: str
    device_count: int
    devices: tuple[RocmDeviceInfo, ...]
    telemetry_source: str = ""
    error: str = ""

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def inspect_rocm_runtime(*, require_available: bool = False) -> RocmRuntimeInfo:
    rocm_version = _read_rocm_version()
    try:
        import torch
    except ImportError as exc:
        info = RocmRuntimeInfo(
            available=False,
            torch_version="",
            hip_version="",
            rocm_version=rocm_version,
            device_count=0,
            devices=(),
            error="PyTorch is not installed",
        )
        return _require(info, require_available=require_available, cause=exc)

    hip_version = str(getattr(torch.version, "hip", "") or "")
    torch_version = str(getattr(torch, "__version__", "") or "")
    if not hip_version:
        info = RocmRuntimeInfo(
            available=False,
            torch_version=torch_version,
            hip_version="",
            rocm_version=rocm_version,
            device_count=0,
            devices=(),
            error="PyTorch is not a ROCm build",
        )
        return _require(info, require_available=require_available)
    if not torch.cuda.is_available():
        info = RocmRuntimeInfo(
            available=False,
            torch_version=torch_version,
            hip_version=hip_version,
            rocm_version=rocm_version,
            device_count=0,
            devices=(),
            error="ROCm device is not available",
        )
        return _require(info, require_available=require_available)

    static_devices = _amd_smi_devices(
        "static",
        "--asic",
        "--bus",
        "--vram",
    )
    metric_devices = _amd_smi_devices(
        "metric",
        "--usage",
        "--power",
        "--temperature",
        "--mem-usage",
    )

    devices: list[RocmDeviceInfo] = []
    for index in range(torch.cuda.device_count()):
        properties = torch.cuda.get_device_properties(index)
        static = static_devices.get(index, {})
        metrics = metric_devices.get(index, {})
        asic = _mapping(static.get("asic"))
        bus = _mapping(static.get("bus"))
        vram = _mapping(static.get("vram"))

        architecture = _text(asic.get("target_graphics_version"))
        pci_bus = _text(bus.get("bdf"))
        pci_device_id = _text(asic.get("device_id"))
        torch_name = _text(getattr(properties, "name", ""))
        name = _device_name(
            market_name=_text(asic.get("market_name")),
            torch_name=torch_name,
            pci_bus=pci_bus,
            pci_device_id=pci_device_id,
            architecture=architecture,
        )
        total_memory_bytes = int(getattr(properties, "total_memory", 0) or 0)
        if total_memory_bytes <= 0:
            total_memory_bytes = _memory_bytes(metrics, "mem_usage", "total_vram") or 0

        devices.append(
            RocmDeviceInfo(
                index=index,
                name=name,
                total_memory_bytes=total_memory_bytes,
                used_memory_bytes=_memory_bytes(metrics, "mem_usage", "used_vram"),
                gpu_utilization_percent=_number(metrics, "usage", "gfx_activity"),
                memory_activity_percent=_number(metrics, "usage", "umc_activity"),
                temperature_edge_celsius=_number(metrics, "temperature", "edge"),
                temperature_hotspot_celsius=_number(metrics, "temperature", "hotspot"),
                temperature_memory_celsius=_number(metrics, "temperature", "mem"),
                power_watts=_number(metrics, "power", "socket_power"),
                architecture=architecture,
                pci_bus=pci_bus,
                pci_device_id=pci_device_id,
                vram_type=_text(vram.get("type")),
                compute_units=_integer(asic.get("num_compute_units")),
            )
        )

    info = RocmRuntimeInfo(
        available=True,
        torch_version=torch_version,
        hip_version=hip_version,
        rocm_version=rocm_version,
        device_count=len(devices),
        devices=tuple(devices),
        telemetry_source="amd-smi" if static_devices or metric_devices else "torch",
    )
    return _require(info, require_available=require_available)


def _read_rocm_version() -> str:
    for path in _ROCM_VERSION_PATHS:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value.splitlines()[0].strip()
    return ""


def _amd_smi_devices(command: str, *arguments: str) -> dict[int, dict[str, Any]]:
    try:
        result = subprocess.run(
            ["amd-smi", command, *arguments, "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_AMD_SMI_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return {}
    raw_devices = payload.get("gpu_data") if isinstance(payload, dict) else None
    if not isinstance(raw_devices, list):
        return {}
    devices: dict[int, dict[str, Any]] = {}
    for raw_device in raw_devices:
        if not isinstance(raw_device, dict):
            continue
        index = _integer(raw_device.get("gpu"))
        if index is not None:
            devices[index] = raw_device
    return devices


def _device_name(
    *,
    market_name: str,
    torch_name: str,
    pci_bus: str,
    pci_device_id: str,
    architecture: str,
) -> str:
    if _usable_name(market_name):
        return market_name
    if _usable_name(torch_name):
        return torch_name
    pci_name = _lspci_name(pci_bus)
    if pci_name:
        return pci_name
    identity = [value for value in (pci_device_id, architecture) if value]
    return " · ".join(("AMD GPU", *identity))


def _usable_name(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized not in _PLACEHOLDER_VALUES and re.fullmatch(r"0x[0-9a-f]+", normalized) is None


def _lspci_name(pci_bus: str) -> str:
    if not pci_bus:
        return ""
    try:
        result = subprocess.run(
            ["lspci", "-s", pci_bus, "-nn"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_AMD_SMI_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    description = result.stdout.strip().partition(": ")[2]
    description = re.sub(r"\s+\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\].*$", "", description).strip()
    if not description or re.search(r"\bDevice\b", description):
        return ""
    return description


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in _PLACEHOLDER_VALUES else text


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(payload: dict[str, Any], *path: str) -> float | None:
    value: object = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _memory_bytes(payload: dict[str, Any], *path: str) -> int | None:
    value: object = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if not isinstance(value, dict):
        return None
    amount = _number(value)
    if amount is None:
        return None
    unit = _text(value.get("unit")).lower()
    multipliers = {
        "b": 1,
        "kb": 1024,
        "mb": 1024**2,
        "gb": 1024**3,
        "tb": 1024**4,
    }
    multiplier = multipliers.get(unit)
    return int(amount * multiplier) if multiplier is not None else None


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
