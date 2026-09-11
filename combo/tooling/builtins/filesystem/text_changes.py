from __future__ import annotations

from difflib import SequenceMatcher


def text_change_summary(before: str, after: str) -> dict[str, int]:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    added_lines = 0
    removed_lines = 0
    matcher = SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for operation, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if operation in {"replace", "delete"}:
            removed_lines += before_end - before_start
        if operation in {"replace", "insert"}:
            added_lines += after_end - after_start
    return {
        "before_bytes": len(before.encode("utf-8")),
        "after_bytes": len(after.encode("utf-8")),
        "before_lines": len(before_lines),
        "after_lines": len(after_lines),
        "added_lines": added_lines,
        "removed_lines": removed_lines,
    }
