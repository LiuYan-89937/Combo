from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from agent_factory.create_agent.validator import ValidationScope
from agent_factory.create_agent.workspace import CreateAgentWorkspace


def package_fingerprint(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    fingerprint: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if _ignore_path(relative):
            continue
        fingerprint[relative] = sha256(path.read_bytes()).hexdigest()
    return fingerprint


def changed_files(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    paths = set(previous) | set(current)
    return sorted(path for path in paths if previous.get(path) != current.get(path))


def tool_probe_digest(workspace: CreateAgentWorkspace) -> str:
    path = workspace.tool_probe_path
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "unreadable"
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def validation_scope_for_focus(validation_focus: str) -> ValidationScope:
    if validation_focus in {"full_static", "assembly_compile", "package_shape", "python_syntax", "runtime_contract_build"}:
        return validation_focus
    if validation_focus in {
        "runtime_contract_build_subset",
        "tools_contract_validate",
        "render_manifest_validate",
        "scheduler_seed_validate",
    }:
        return "runtime_contract_build"
    if validation_focus == "package_tool_syntax_and_binding":
        return "python_syntax"
    return "workspace_hygiene"


def _ignore_path(relative: str) -> bool:
    parts = relative.split("/")
    return (
        not relative
        or parts[0] == ".factory"
        or "__pycache__" in parts
        or relative.endswith(".pyc")
        or relative == ".DS_Store"
    )
