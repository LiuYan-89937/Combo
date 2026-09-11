"""原子文件写入：唯一实现处。

所有需要「要么完整写入、要么保持原样」的落盘都走这里，不再各处用
``tempfile.mkstemp`` + ``os.replace`` 自行拼装。

自行拼装的隐患：``mkstemp`` 建出的临时文件权限是 0600，直接 ``os.replace``
到目标路径会把目标原有的权限位一并覆盖掉；这里的实现会保留目标原有权限。
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
from tempfile import NamedTemporaryFile


def _original_mode(target: Path) -> int | None:
    """目标已存在时返回其权限位，否则返回 None。"""
    return stat.S_IMODE(target.stat().st_mode) if target.exists() else None


def _publish(temp_path: Path, target: Path, original_mode: int | None) -> None:
    if original_mode is not None:
        temp_path.chmod(original_mode)
    temp_path.replace(target)


def atomic_write_bytes(target: Path, content: bytes) -> None:
    """把 content 原子写入 target，并保留目标原有权限位。"""
    original_mode = _original_mode(target)
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile("wb", delete=False, dir=str(target.parent)) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _publish(temp_path, target, original_mode)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def atomic_write_text(target: Path, text: str, *, encoding: str = "utf-8") -> None:
    """把文本原子写入 target，并保留目标原有权限位。"""
    atomic_write_bytes(target, text.encode(encoding))


def atomic_write_file(target: Path, source: Path) -> None:
    """把 source 的内容原子写入 target，并保留目标原有权限位。"""
    original_mode = _original_mode(target)
    temp_path: Path | None = None
    try:
        with source.open("rb") as source_handle:
            with NamedTemporaryFile("wb", delete=False, dir=str(target.parent)) as target_handle:
                temp_path = Path(target_handle.name)
                shutil.copyfileobj(source_handle, target_handle)
                target_handle.flush()
                os.fsync(target_handle.fileno())
        _publish(temp_path, target, original_mode)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
