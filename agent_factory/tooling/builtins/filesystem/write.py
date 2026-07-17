from __future__ import annotations

from hashlib import sha256
from tempfile import NamedTemporaryFile
from typing import Any

from agent_factory.tooling.builtins.filesystem.common import (
    assert_not_protected_write_path,
    filesystem_boundary,
    path_risk_result,
    required_string,
    resolve_path,
    write_focus_facts,
)
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


FOCUS_EVIDENCE_KEY = "focus"


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return ToolRiskResult.model_validate(
        path_risk_result(arguments, context, default_action="ask", sensitive_action="ask")
    ).model_dump(mode="json")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    path = required_string(arguments, "path")
    content = arguments.get("content")
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    create_dirs = bool(arguments.get("create_dirs", True))
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(path=path, root=root, allow_external=allow_external)
    assert_not_protected_write_path(target, root=root, resources=resources)
    existed = target.exists()
    before_hash = None
    if existed:
        if not target.is_file():
            raise IsADirectoryError(str(target))
        before_hash = sha256(target.read_bytes()).hexdigest()
    if not target.parent.exists():
        if not create_dirs:
            raise FileNotFoundError(str(target.parent))
        target.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = content.encode("utf-8")
    _atomic_write(target, content_bytes)
    output = {
        "path": str(target),
        "created": not existed,
        "bytes_written": len(content_bytes),
        "before_hash": before_hash,
        "after_hash": sha256(content_bytes).hexdigest(),
    }
    evidence = _write_evidence(target, root=root, resources=resources)
    return tool_envelope(output, evidence=evidence)


def _write_evidence(target, *, root, resources: dict[str, Any]) -> dict[str, Any]:
    return {FOCUS_EVIDENCE_KEY: write_focus_facts(target, root=root, resources=resources)}


def _atomic_write(target, content: bytes) -> None:
    with NamedTemporaryFile("wb", delete=False, dir=str(target.parent)) as handle:
        temp_path = target.parent / handle.name
        handle.write(content)
    temp_path.replace(target)
