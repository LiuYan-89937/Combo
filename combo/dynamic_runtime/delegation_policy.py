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

TEMPORARY_RUNTIME_ONLY_CAPABILITY_IDS = frozenset(
    {"tool://builtin/ask_usr"}
)

MAIN_RUNTIME_EXCLUDED_CAPABILITY_IDS = (
    MAIN_RUNTIME_ONLY_CAPABILITY_IDS | TEMPORARY_RUNTIME_ONLY_CAPABILITY_IDS
)


def capability_is_delegatable(capability_id: str) -> bool:
    return str(capability_id or "").strip() not in MAIN_RUNTIME_EXCLUDED_CAPABILITY_IDS
