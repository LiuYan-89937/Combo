from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path
import tempfile
from typing import Any

from combo.skill_manifest import normalize_staged_skill_package


SkillPublisher = Callable[[Path, bool], str]
SkillRemover = Callable[[str], None]


class SkillPackageInstaller:
    """Prepare Skill packages and delegate publication to the runtime owner."""

    def __init__(self, *, skills_dir: str | Path) -> None:
        self.skills_dir = Path(skills_dir).expanduser().resolve()
        self._publisher: SkillPublisher | None = None
        self._remover: SkillRemover | None = None

    def bind(self, *, publisher: SkillPublisher, remover: SkillRemover) -> None:
        if self._publisher is not None or self._remover is not None:
            raise RuntimeError("Skill package installer is already bound")
        self._publisher = publisher
        self._remover = remover

    def install_package(self, package: dict[str, Any]) -> dict[str, Any]:
        files = package.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("Skill package.files must be a non-empty array")
        with tempfile.TemporaryDirectory(prefix="combo-skill-package-") as temporary:
            staging_root = Path(temporary)
            package_root = staging_root / "package"
            package_root.mkdir()
            portable_paths: set[str] = set()
            for raw_file in files:
                self._write_package_file(package_root, raw_file, portable_paths)
            return self.install_directory(
                package_root,
                source_name="agent_package",
                replace_existing=False,
            )

    def install_directory(
        self,
        source: str | Path,
        *,
        source_name: str,
        replace_existing: bool,
    ) -> dict[str, Any]:
        publisher, _ = self._bound_operations()
        normalized = normalize_staged_skill_package(source)
        _require_regular_tree(normalized)
        skill_name = publisher(normalized, replace_existing)
        target = self.skills_dir / skill_name
        return {
            "message": f"Skill installed: {target.name}",
            "installed_skill": {
                "skill_id": target.name,
                "path": str(target),
                "source": source_name,
                "enabled": True,
            },
            "restart_required": False,
        }

    def remove(self, skill_name: str) -> None:
        _, remover = self._bound_operations()
        remover(skill_name)

    def _write_package_file(
        self,
        package_root: Path,
        raw_file: object,
        portable_paths: set[str],
    ) -> None:
        if not isinstance(raw_file, dict):
            raise ValueError("Skill package file must be an object")
        raw_path = str(raw_file.get("path") or "").replace("\\", "/")
        relative = Path(raw_path)
        if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError(f"Skill package path is invalid: {raw_path or '<empty>'}")
        portable_path = relative.as_posix().casefold()
        if portable_path in portable_paths:
            raise ValueError(f"Skill package contains a cross-platform path collision: {raw_path}")
        portable_paths.add(portable_path)
        has_text = "content" in raw_file
        has_base64 = "content_base64" in raw_file
        if has_text == has_base64:
            raise ValueError(f"Skill package file requires exactly one content encoding: {raw_path}")
        if has_text:
            content = str(raw_file["content"]).encode("utf-8")
        else:
            try:
                content = base64.b64decode(str(raw_file["content_base64"]), validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Skill package file has invalid base64 content: {raw_path}") from exc
        destination = (package_root / relative).resolve()
        if package_root.resolve() not in destination.parents:
            raise ValueError(f"Skill package path escapes its root: {raw_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    def _bound_operations(self) -> tuple[SkillPublisher, SkillRemover]:
        if self._publisher is None or self._remover is None:
            raise RuntimeError("Skill package installer is not bound")
        return self._publisher, self._remover


def _require_regular_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Skill package contains a symbolic link: {path.relative_to(root)}")
        if not path.is_file() and not path.is_dir():
            raise ValueError(f"Skill package contains an unsupported entry: {path.relative_to(root)}")
