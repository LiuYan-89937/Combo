from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from agent_factory.paths import project_root
from agent_factory.runtime_contracts import AgentPackageLoader, LoadedAgentPackage


DEFAULT_AGENT_PACKAGE_ROOT = ".agentfactory/packages"
DEFAULT_SYSTEM_PACKAGE_ROOT = "SystemPackage"


@dataclass(slots=True)
class AgentPackageRepository:
    package_root: Path
    system_package_root: Path
    loader: AgentPackageLoader = field(default_factory=AgentPackageLoader)

    @classmethod
    def from_paths(
        cls,
        *,
        package_root: str | Path | None = None,
        system_package_root: str | Path | None = None,
    ) -> "AgentPackageRepository":
        return cls(
            package_root=Path(package_root).expanduser() if package_root else default_package_root(),
            system_package_root=(
                Path(system_package_root).expanduser()
                if system_package_root
                else default_system_package_root()
            ),
        )

    def manifest_paths(self) -> list[Path]:
        self.package_root.mkdir(parents=True, exist_ok=True)
        return sorted(self.package_root.glob("*/agent_package.json"))

    def load(self, package_id: str) -> LoadedAgentPackage:
        return self.loader.load_path(self.manifest_path(package_id))

    def load_manifest(self, manifest_path: Path) -> LoadedAgentPackage:
        return self.loader.load_path(manifest_path)

    def manifest_path(self, package_id: str) -> Path:
        return self.package_dir(package_id) / "agent_package.json"

    def package_dir(self, package_id: str, *, include_system_packages: bool = True) -> Path:
        if not package_id or "/" in package_id or "\\" in package_id or package_id in {".", ".."}:
            raise ValueError(f"invalid agent package id: {package_id}")
        user_target = safe_child(self.package_root, package_id, label="agent package")
        if user_target.exists() or not include_system_packages:
            return user_target
        system_target = safe_child(self.system_package_root, package_id, label="system package")
        if system_target.exists():
            return system_target
        return user_target

    def delete_user_package(self, package_id: str) -> dict[str, object]:
        target = self.package_dir(package_id, include_system_packages=False)
        if not target.exists():
            raise FileNotFoundError(f"agent package not found: {package_id}")
        shutil.rmtree(target)
        return {"package_id": package_id, "deleted": True}

    def export_user_package_archive(self, package_id: str) -> Path:
        target = self.package_dir(package_id, include_system_packages=False)
        manifest_path = target / "agent_package.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"agent package not found: {package_id}")
        archive_stem = safe_archive_stem(package_id)
        with tempfile.NamedTemporaryFile(prefix=f"{archive_stem}-", suffix=".zip", delete=False) as handle:
            archive_path = Path(handle.name)
        root_name = target.name
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in target.rglob("*") if item.is_file()):
                if path.is_symlink():
                    continue
                relative_path = Path(root_name) / path.relative_to(target)
                archive.write(path, relative_path.as_posix())
        return archive_path


def default_package_root() -> Path:
    return project_root() / DEFAULT_AGENT_PACKAGE_ROOT


def default_system_package_root() -> Path:
    return project_root() / DEFAULT_SYSTEM_PACKAGE_ROOT


def safe_child(root: Path, child_name: str, *, label: str) -> Path:
    resolved_root = root.resolve()
    target = (resolved_root / child_name).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes package root: {child_name}") from exc
    return target


def safe_archive_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return stem or "agent-package"
