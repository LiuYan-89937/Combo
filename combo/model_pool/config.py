from __future__ import annotations

import os
from pathlib import Path

from combo.paths import combo_data_path, resolve_project_path


MODEL_POOL_STORE_PATH_ENV = "COMBO_MODEL_POOL_STORE_PATH"
MODEL_POOL_STORE_READ_ONLY_ENV = "COMBO_MODEL_POOL_STORE_READ_ONLY"


def default_model_pool_store_path() -> Path:
    return combo_data_path("model_pool", "models.sqlite")


def default_model_usage_store_path() -> Path:
    return combo_data_path("model_pool", "usage.sqlite")


def resolve_model_pool_store_path(value: str | Path | None = None) -> Path:
    configured = value if value is not None else os.getenv(MODEL_POOL_STORE_PATH_ENV)
    if configured:
        return resolve_project_path(configured)
    return default_model_pool_store_path()


def model_pool_store_read_only(value: str | None = None) -> bool:
    configured = value if value is not None else os.getenv(MODEL_POOL_STORE_READ_ONLY_ENV)
    return str(configured or "").strip().lower() in {"1", "true", "yes", "on"}
