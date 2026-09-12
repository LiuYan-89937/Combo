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


SHARED_STATE_DIRNAMES: tuple[str, ...] = (
    "attachment_uploads",
    "capability_blobs",
    "dependency_pool",
    "dynamic_runtime",
    "extension_registry",
    "graph_store",
    "logs",
    "mcp_servers",
    "model_pool",
    "resources",
    "tool_outputs",
    "tool_package_runtime",
    "workspaces",
)


def combo_shared_state_paths() -> tuple[Path, ...]:
    """应用的共享状态条目：可以读，但不允许被通用文件工具改写。

    这里只登记数据根下的**具体条目**，而不是整个数据根——子 agent 的独立工作树就在
    ``<数据根>/worktrees`` 下面，把数据根整体标成只读会把工作树自己冻住。
    调用方还要按运行时 root 过滤掉会吞掉 root 的条目
    （``runtime_infrastructure.shared_state_read_only_paths``）。
    """
    root = combo_data_root()
    return tuple(root / name for name in SHARED_STATE_DIRNAMES)
