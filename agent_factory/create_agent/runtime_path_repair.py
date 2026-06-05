from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from agent_factory.create_agent.contract_catalog import default_contract_payload


RUNTIME_CONTRACT_PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "artifact": ("config.root", "config.index_path"),
    "knowledge": ("config.root", "config.catalog_path", "config.rag_store.path"),
    "memory": (
        "config.memory_system.store.path",
        "config.memory_system.background.journal_root",
    ),
    "scheduler": ("config.store_path",),
    "session": ("config.session_root", "config.checkpoint_path"),
    "tools": ("config.instance_extension_root",),
    "trace": ("config.root",),
}


@dataclass(frozen=True, slots=True)
class RuntimePathRepair:
    contract_key: str
    target_file: str
    field_path: str
    current_value: str
    replacement_value: str

    def to_input(self) -> dict[str, str]:
        return {
            "contract_key": self.contract_key,
            "target_file": self.target_file,
            "field_path": self.field_path,
            "current_value": self.current_value,
            "replacement_value": self.replacement_value,
        }


def find_runtime_path_repairs(
    *,
    package_root: Path,
    contract_paths: dict[str, str],
    contracts: dict[str, dict[str, Any]],
) -> list[RuntimePathRepair]:
    repairs: list[RuntimePathRepair] = []
    for contract_key, fields in sorted(RUNTIME_CONTRACT_PATH_FIELDS.items()):
        payload = contracts.get(contract_key)
        target_file = contract_paths.get(contract_key, f"contracts/{contract_key}.json")
        if not isinstance(payload, dict):
            continue
        default_payload = default_contract_payload(contract_key)
        for field_path in fields:
            current = _get_path(payload, field_path)
            if not isinstance(current, str) or _resolves_inside(package_root, current):
                continue
            replacement = _get_path(default_payload, field_path)
            if not isinstance(replacement, str) or not _resolves_inside(package_root, replacement):
                raise ValueError(f"default runtime path is invalid for {contract_key}.{field_path}: {replacement!r}")
            repairs.append(
                RuntimePathRepair(
                    contract_key=contract_key,
                    target_file=target_file,
                    field_path=field_path,
                    current_value=current,
                    replacement_value=replacement,
                )
            )
    return repairs


def apply_runtime_path_repairs(package_root: Path, repairs: list[RuntimePathRepair]) -> list[str]:
    changed: list[str] = []
    by_file: dict[str, list[RuntimePathRepair]] = {}
    for repair in repairs:
        by_file.setdefault(repair.target_file, []).append(repair)
    for relative_path, file_repairs in sorted(by_file.items()):
        path = _package_file(package_root, relative_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"contract file must contain a JSON object: {relative_path}")
        updated = False
        for repair in file_repairs:
            current = _get_path(payload, repair.field_path)
            if current != repair.replacement_value:
                _set_path(payload, repair.field_path, repair.replacement_value)
                updated = True
        if updated:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            changed.append(relative_path)
    return changed


def runtime_path_repairs_from_inputs(inputs: dict[str, Any]) -> list[RuntimePathRepair]:
    raw_repairs = inputs.get("repairs")
    if isinstance(raw_repairs, list):
        return [_repair_from_input(item) for item in raw_repairs]
    return [_repair_from_input(inputs)]


def _repair_from_input(value: Any) -> RuntimePathRepair:
    if not isinstance(value, dict):
        raise ValueError("runtime path repair input must be an object")
    return RuntimePathRepair(
        contract_key=_required_text(value, "contract_key"),
        target_file=_required_text(value, "target_file"),
        field_path=_required_text(value, "field_path"),
        current_value=_required_text(value, "current_value"),
        replacement_value=_required_text(value, "replacement_value"),
    )


def _resolves_inside(package_root: Path, value: str) -> bool:
    raw = value.strip()
    if not raw:
        return False
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = package_root / candidate
    try:
        candidate.resolve().relative_to(package_root.resolve())
    except ValueError:
        return False
    return True


def _get_path(payload: dict[str, Any], field_path: str) -> Any:
    value: Any = payload
    for part in field_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _set_path(payload: dict[str, Any], field_path: str, replacement: str) -> None:
    value: dict[str, Any] = payload
    parts = field_path.split(".")
    for part in parts[:-1]:
        child = value.get(part)
        if not isinstance(child, dict):
            child = {}
            value[part] = child
        value = child
    value[parts[-1]] = replacement


def _package_file(package_root: Path, relative_path: str) -> Path:
    path = (package_root / relative_path).resolve()
    try:
        path.relative_to(package_root.resolve())
    except ValueError as exc:
        raise ValueError(f"runtime path repair target escapes package root: {relative_path}") from exc
    return path


def _required_text(value: dict[str, Any], key: str) -> str:
    text = str(value.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text
