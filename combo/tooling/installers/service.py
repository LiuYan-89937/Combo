from __future__ import annotations

import base64
from collections.abc import Callable
import os
from pathlib import Path
import shutil
import tempfile
from threading import RLock
from typing import Any

from combo.dynamic_runtime.mcp_gateway import MCPGateway
from combo.dynamic_runtime.skill_source import normalize_staged_skill_package
from combo.tooling.installers.mcp_config import normalize_mcp_server_config


SkillValidator = Callable[[Path], None]
ChangePublisher = Callable[[], None]


class SkillPackageInstaller:
    """Validate and atomically publish Skill package trees from any source adapter."""

    def __init__(self, *, skills_dir: str | Path) -> None:
        self.skills_dir = Path(skills_dir).expanduser().resolve()
        self._validator: SkillValidator | None = None
        self._publisher: ChangePublisher | None = None
        self._lock = RLock()

    def bind(self, *, validator: SkillValidator, publisher: ChangePublisher) -> None:
        if self._validator is not None or self._publisher is not None:
            raise RuntimeError("Skill package installer is already bound")
        self._validator = validator
        self._publisher = publisher

    def install_package(self, package: dict[str, Any]) -> dict[str, Any]:
        files = package.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("Skill package.files must be a non-empty array")
        self.skills_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".skill-package-", dir=self.skills_dir.parent) as temporary:
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

    def publish_changes(self) -> None:
        _, publisher = self._bound_operations()
        publisher()

    def install_directory(
        self,
        source: str | Path,
        *,
        source_name: str,
        replace_existing: bool,
    ) -> dict[str, Any]:
        validator, publisher = self._bound_operations()
        with self._lock:
            normalized = normalize_staged_skill_package(source)
            _require_regular_tree(normalized)
            validator(normalized.parent)
            target = self.skills_dir / normalized.name
            if target.exists() and not replace_existing:
                raise FileExistsError(f"Skill is already installed: {normalized.name}")
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            backup = self.skills_dir.parent / f".{normalized.name}.skill-install-backup"
            if backup.exists():
                raise RuntimeError(f"stale Skill installation backup exists: {backup}")
            if target.exists():
                os.replace(target, backup)
            try:
                shutil.copytree(normalized, target, symlinks=False)
                publisher()
            except BaseException:
                shutil.rmtree(target, ignore_errors=True)
                if backup.exists():
                    os.replace(backup, target)
                publisher()
                raise
            shutil.rmtree(backup, ignore_errors=True)
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

    def _bound_operations(self) -> tuple[SkillValidator, ChangePublisher]:
        if self._validator is None or self._publisher is None:
            raise RuntimeError("Skill package installer is not bound")
        return self._validator, self._publisher


class CapabilityInstallerService:
    """Main-runtime facade for durable Skill and MCP capability installation."""

    def __init__(
        self,
        *,
        skill_packages: SkillPackageInstaller,
        mcp_gateway: MCPGateway,
        refresh_capability_search: ChangePublisher,
    ) -> None:
        self._skill_packages = skill_packages
        self._mcp_gateway = mcp_gateway
        self._refresh_capability_search = refresh_capability_search

    def install_skill(self, package: dict[str, Any]) -> dict[str, Any]:
        return self._skill_packages.install_package(package)

    def install_mcp(self, config: object) -> dict[str, Any]:
        server = normalize_mcp_server_config(config)
        self._mcp_gateway.add_server(
            server,
            expected_registry_digest=self._mcp_gateway.registry_digest(),
        )
        self._refresh_capability_search()
        installed = self._mcp_gateway.server(str(server["server_id"]))
        return {
            "message": f"MCP server installed: {installed.server_id}",
            "installed_server": {
                "server_id": installed.server_id,
                "display_name": str(installed.raw_config.get("display_name") or installed.server_id),
                "tool_count": len(installed.tools),
                "resource_count": len(installed.catalog.resources),
                "resource_template_count": len(installed.catalog.resource_templates),
                "prompt_count": len(installed.catalog.prompts),
            },
            "restart_required": False,
        }


def _require_regular_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Skill package contains a symbolic link: {path.relative_to(root)}")
        if not path.is_file() and not path.is_dir():
            raise ValueError(f"Skill package contains an unsupported entry: {path.relative_to(root)}")
