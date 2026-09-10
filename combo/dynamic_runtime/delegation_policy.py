from __future__ import annotations


COMPUTER_USE_CAPABILITY_ID = "tool://builtin/computer_use"

MAIN_RUNTIME_ONLY_CAPABILITY_IDS = frozenset(
    {
        "tool://builtin/capability",
        "tool://builtin/capability_invoke",
        "tool://builtin/delegate",
        "tool://builtin/delegate_continue",
        "tool://builtin/delegate_message",
        "tool://builtin/delegation_status",
        "tool://builtin/knowledge",
        "tool://builtin/memory",
        "tool://builtin/mcp_installer",
        "tool://builtin/scheduler",
        "tool://builtin/skill_installer",
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


def computer_use_excluded_capability_ids(enabled: bool) -> frozenset[str]:
    """Hide Computer Use from every runtime role until the user turns it on."""
    if enabled:
        return frozenset()
    return frozenset({COMPUTER_USE_CAPABILITY_ID})
