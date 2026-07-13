from __future__ import annotations

import os

from agent_factory.models.image_generation.protocol import ImageGenerationSettings


IMAGE_MODEL_PROVIDER_ENV = "AGENTFACTORY_IMAGE_MODEL_PROVIDER"
IMAGE_MODEL_ENV = "AGENTFACTORY_IMAGE_MODEL"
IMAGE_MODEL_API_KEY_ENV = "AGENTFACTORY_IMAGE_MODEL_API_KEY"
IMAGE_MODEL_BASE_URL_ENV = "AGENTFACTORY_IMAGE_MODEL_BASE_URL"
IMAGE_MODEL_TIMEOUT_SECONDS_ENV = "AGENTFACTORY_IMAGE_MODEL_TIMEOUT_SECONDS"


def get_image_generation_model_settings() -> ImageGenerationSettings | None:
    values = {
        "provider": _env_text(IMAGE_MODEL_PROVIDER_ENV),
        "model": _env_text(IMAGE_MODEL_ENV),
        "api_key": _env_text(IMAGE_MODEL_API_KEY_ENV),
        "base_url": _env_text(IMAGE_MODEL_BASE_URL_ENV),
    }
    if not any(values.values()):
        return None
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(
            "image model env configuration is incomplete; missing: "
            + ", ".join(missing)
        )
    return ImageGenerationSettings(
        provider=values["provider"] or "",
        model=values["model"] or "",
        api_key=values["api_key"] or "",
        base_url=values["base_url"] or "",
        source="env",
        timeout_seconds=_env_timeout(IMAGE_MODEL_TIMEOUT_SECONDS_ENV),
    )


def _env_text(name: str) -> str:
    return str(os.getenv(name) or "").strip()


def _env_timeout(name: str) -> float | None:
    value = _env_text(name)
    if not value:
        return None
    try:
        timeout = float(value)
    except ValueError:
        raise ValueError(f"{name} must be a positive number") from None
    if timeout <= 0:
        raise ValueError(f"{name} must be a positive number")
    return timeout
