from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT_ENV = "AGENTFACTORY_PROJECT_ROOT"
DATA_ROOT_ENV = "AGENTFACTORY_DATA_ROOT"


def project_root() -> Path:
    configured = os.getenv(PROJECT_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "agent_factory").is_dir():
            return candidate
    return current


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return project_root() / path


def factory_artifact_root() -> Path:
    configured = os.getenv(DATA_ROOT_ENV)
    data_root = Path(configured).expanduser().resolve() if configured else project_root()
    return data_root / ".agentfactory"


def factory_artifact_path(*parts: str) -> Path:
    return factory_artifact_root().joinpath(*parts)
