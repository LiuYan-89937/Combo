from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT_ENV = "COMBO_PROJECT_ROOT"
DATA_ROOT_ENV = "COMBO_DATA_ROOT"


def project_root() -> Path:
    configured = os.getenv(PROJECT_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "combo").is_dir():
            return candidate
    return current


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return project_root() / path


def combo_data_root() -> Path:
    configured = os.getenv(DATA_ROOT_ENV)
    data_root = Path(configured).expanduser().resolve() if configured else project_root()
    return data_root / ".combo"


def combo_data_path(*parts: str) -> Path:
    return combo_data_root().joinpath(*parts)
