from __future__ import annotations

from typing import Any

from agent_factory.model_pool.resolver import ResolvedChatModelProfile, resolve_chat_model_profile
from agent_factory.model_pool.schema import ModelProfileBinding


RUNTIME_MODEL_PROFILE_OVERRIDES_KEY = "model_profile_overrides"
RUNTIME_MAIN_MODEL_PROFILE_ID_KEY = "runtime_main_model_profile_id"


def main_model_profile_id_from_user_config(user_config: Any) -> str | None:
    if not isinstance(user_config, dict):
        return None
    overrides = user_config.get(RUNTIME_MODEL_PROFILE_OVERRIDES_KEY)
    if not isinstance(overrides, dict):
        return None
    profile_id = str(overrides.get("main") or "").strip()
    return profile_id or None


def runtime_main_model_profile_id_from_state(state: Any) -> str | None:
    if isinstance(state, dict):
        profile_id = str(state.get(RUNTIME_MAIN_MODEL_PROFILE_ID_KEY) or "").strip()
        return profile_id or None
    runtime_config = getattr(state, "runtime_config", None)
    user_config = getattr(runtime_config, "user_config", None)
    return main_model_profile_id_from_user_config(user_config)


def resolve_runtime_main_chat_model_from_state(state: Any) -> ResolvedChatModelProfile | None:
    profile_id = runtime_main_model_profile_id_from_state(state)
    if not profile_id:
        return None
    return resolve_runtime_main_chat_model(profile_id)


def resolve_runtime_main_chat_model(profile_id: str) -> ResolvedChatModelProfile:
    binding = ModelProfileBinding(
        profile_id=profile_id,
        selection_source="manual",
        reason="runtime main model override",
    )
    return resolve_chat_model_profile(binding, role="main")
