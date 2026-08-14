from __future__ import annotations

from hashlib import sha256
from typing import Any

from combo.tooling.builtins.filesystem.common import (
    assert_not_protected_write_path,
    filesystem_allowed_roots,
    filesystem_boundary,
    filesystem_mounts,
    path_risk_result,
    require_file_locks,
    required_string,
    resolve_path,
    write_focus_facts,
)
from combo.tooling.envelope import tool_envelope
from combo.tooling.spec import ToolRiskResult
from combo.tooling.builtins.filesystem.text_changes import (
    atomic_write_bytes,
    text_change_summary,
)
from combo.tooling.builtins.filesystem.staged_write import (
    abort_staged_write,
    append_staged_write,
    commit_staged_write,
    start_staged_write,
)
from combo.tooling.builtins.filesystem.workspace_search import workspace_relative_path


FOCUS_EVIDENCE_KEY = "focus"


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action == "start":
        return ToolRiskResult.model_validate(
            path_risk_result(arguments, context, default_action="allow", sensitive_action="ask")
        ).model_dump(mode="json")
    if action in {"append", "abort"}:
        return ToolRiskResult(
            action="allow",
            risk_level="low",
            reasons=[f"{action} only changes or removes an uncommitted staged write"],
            facts={"write_id": str(arguments.get("write_id") or "")},
        ).model_dump(mode="json")
    if action == "commit":
        return ToolRiskResult(
            action="ask",
            risk_level="medium",
            reasons=["committing a staged write atomically replaces the target workspace file"],
            facts={"write_id": str(arguments.get("write_id") or "")},
        ).model_dump(mode="json")
    return ToolRiskResult.model_validate(
        path_risk_result(arguments, context, default_action="ask", sensitive_action="ask")
    ).model_dump(mode="json")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action == "start":
        return tool_envelope(start_staged_write(arguments, resources))
    if action == "append":
        return tool_envelope(append_staged_write(arguments, resources))
    if action == "commit":
        result = commit_staged_write(arguments, resources)
        focus = result.pop(FOCUS_EVIDENCE_KEY, None)
        return tool_envelope(result, evidence={FOCUS_EVIDENCE_KEY: focus} if focus else {})
    if action == "abort":
        return tool_envelope(abort_staged_write(arguments, resources))
    if action != "write_once":
        raise ValueError("action must be write_once, start, append, commit, or abort")
    path = required_string(arguments, "path")
    content = arguments.get("content")
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    create_dirs = bool(arguments.get("create_dirs", True))
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(
        path=path,
        root=root,
        allow_external=allow_external,
        allowed_roots=filesystem_allowed_roots(resources),
    )
    assert_not_protected_write_path(target, root=root, resources=resources)
    with require_file_locks(resources).acquire((target,)):
        existed = target.exists()
        before_hash = None
        before_content = ""
        if existed:
            if not target.is_file():
                raise IsADirectoryError(str(target))
            before_bytes = target.read_bytes()
            before_hash = sha256(before_bytes).hexdigest()
            try:
                before_content = before_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"existing file is not valid utf-8 text: {target}") from exc
        if not target.parent.exists():
            if not create_dirs:
                raise FileNotFoundError(str(target.parent))
            target.parent.mkdir(parents=True, exist_ok=True)
        content_bytes = content.encode("utf-8")
        atomic_write_bytes(target, content_bytes)
    output = {
        "path": workspace_relative_path(
            target,
            workspace_root=root,
            mounts=filesystem_mounts(resources),
        ),
        "created": not existed,
        "bytes_written": len(content_bytes),
        "before_hash": before_hash,
        "after_hash": sha256(content_bytes).hexdigest(),
        "change_summary": text_change_summary(before_content, content),
    }
    evidence = _write_evidence(target, root=root, resources=resources)
    return tool_envelope(output, evidence=evidence)


def _write_evidence(target, *, root, resources: dict[str, Any]) -> dict[str, Any]:
    return {FOCUS_EVIDENCE_KEY: write_focus_facts(target, root=root, resources=resources)}
