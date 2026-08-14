from __future__ import annotations


MAIN_RUNTIME_ONLY_CAPABILITY_IDS = frozenset(
    {
        "tool://builtin/capability",
        "tool://builtin/delegate",
        "tool://builtin/delegation_status",
        "tool://builtin/knowledge",
        "tool://builtin/memory",
        "tool://builtin/scheduler",
        "tool://builtin/skillhub",
    }
)


def capability_is_delegatable(capability_id: str) -> bool:
    return str(capability_id or "").strip() not in MAIN_RUNTIME_ONLY_CAPABILITY_IDS
