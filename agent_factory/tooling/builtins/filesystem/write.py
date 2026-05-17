from __future__ import annotations

from hashlib import sha256
from tempfile import NamedTemporaryFile
from typing import Any

from agent_factory.tooling.builtins.filesystem.common import filesystem_boundary, required_string, resolve_path


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    path = required_string(arguments, "path")
    content = arguments.get("content")
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    create_dirs = bool(arguments.get("create_dirs", False))
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(path=path, root=root, allow_external=allow_external)
    existed = target.exists()
    before_hash = None
    if existed:
        if not target.is_file():
            raise IsADirectoryError(str(target))
        before_hash = sha256(target.read_bytes()).hexdigest()
    if not target.parent.exists():
        if not create_dirs:
            raise FileNotFoundError(str(target.parent))
        target.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = content.encode("utf-8")
    _atomic_write(target, content_bytes)
    return {
        "path": str(target),
        "created": not existed,
        "bytes_written": len(content_bytes),
        "before_hash": before_hash,
        "after_hash": sha256(content_bytes).hexdigest(),
    }


def _atomic_write(target, content: bytes) -> None:
    with NamedTemporaryFile("wb", delete=False, dir=str(target.parent)) as handle:
        temp_path = target.parent / handle.name
        handle.write(content)
    temp_path.replace(target)
