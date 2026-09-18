from __future__ import annotations

from hashlib import sha256
from typing import Any

from combo.tooling.builtins.filesystem.common import (
    assert_not_protected_write_path,
    filesystem_allowed_roots,
    filesystem_boundary,
    path_risk_result,
    require_file_locks,
    required_string,
    resolve_path,
    write_focus_facts,
)
from combo.file_atomic import atomic_write_bytes
from combo.tooling.builtins.filesystem.text_changes import text_change_summary
from combo.tooling.builtins.filesystem.text_replacement import TextReplacementError, replace_exact_text
from combo.tooling.envelope import tool_envelope, tool_failure
from combo.tooling.spec import ToolRiskResult


FOCUS_EVIDENCE_KEY = "focus"


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return ToolRiskResult.model_validate(
        path_risk_result(arguments, context, default_action="ask", sensitive_action="ask")
    ).model_dump(mode="json")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    path = required_string(arguments, "path")
    old_text = arguments.get("old_text")
    if not isinstance(old_text, str) or not old_text:
        raise ValueError("old_text must be a non-empty string")
    new_text = arguments.get("new_text")
    if not isinstance(new_text, str):
        raise ValueError("new_text must be a string")
    replace_all = bool(arguments.get("replace_all", False))
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(
        path=path,
        root=root,
        allow_external=allow_external,
        allowed_roots=filesystem_allowed_roots(resources),
    )
    assert_not_protected_write_path(target, root=root, resources=resources)
    with require_file_locks(resources).acquire((target,)):
        if not target.exists():
            raise FileNotFoundError(str(target))
        if not target.is_file():
            raise IsADirectoryError(str(target))
        raw = target.read_bytes()
        current_hash = sha256(raw).hexdigest()
        failure_context = {
            "path": str(target), "applied": False,
        }
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"file is not valid utf-8 text: {target}") from exc
        try:
            updated, replacements = replace_exact_text(content, old_text, new_text, replace_all=replace_all)
        except TextReplacementError as exc:
            return tool_failure(
                f"{target}: {exc}. No changes were written.",
                output={**failure_context, "code": exc.code, "match_count": exc.match_count},
            )
        updated_bytes = updated.encode("utf-8")
        atomic_write_bytes(target, updated_bytes)
    output = {
        "path": str(target),
        "replacements": replacements,
        "before_hash": current_hash,
        "after_hash": sha256(updated_bytes).hexdigest(),
        "change_summary": text_change_summary(content, updated),
    }
    return tool_envelope(
        output,
        evidence={FOCUS_EVIDENCE_KEY: write_focus_facts(target, root=root, resources=resources)},
    )
