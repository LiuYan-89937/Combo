from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil

from agent_factory.paths import project_root, system_package_root
from agent_factory.runtime_contracts import AgentPackageLoader, LoadedAgentPackage


DEFAULT_AGENT_PACKAGE_ROOT = ".agentfactory/packages"


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
        self.system_package_root.mkdir(parents=True, exist_ok=True)
        paths_by_package_id: dict[str, Path] = {}
        for path in sorted(self.system_package_root.glob("*/agent_package.json")):
            paths_by_package_id[path.parent.name] = path
        for path in sorted(self.package_root.glob("*/agent_package.json")):
            paths_by_package_id[path.parent.name] = path
        return sorted(paths_by_package_id.values())

    def load(self, package_id: str) -> LoadedAgentPackage:
        return self.loader.load_path(self.manifest_path(package_id))

    def load_manifest(self, manifest_path: Path) -> LoadedAgentPackage:
        return self.loader.load_path(manifest_path)

    def manifest_path(self, package_id: str) -> Path:
        return self.package_dir(package_id) / "agent_package.json"

    def package_origin(self, manifest_path: Path) -> str:
        try:
            manifest_path.resolve().relative_to(self.system_package_root.resolve())
        except ValueError:
            return "user"
        return "system"

    def package_capabilities(self, manifest_path: Path) -> dict[str, bool]:
        user_managed = self.package_origin(manifest_path) == "user"
        return {"deletable": user_managed, "exportable": False}

    def package_dir(self, package_id: str, *, include_system_packages: bool = True) -> Path:
        if not package_id or "/" in package_id or "\\" in package_id or package_id in {".", ".."}:
            raise ValueError(f"invalid agent package id: {package_id}")
        user_target = safe_child(self.package_root, package_id, label="agent package")
        if user_target.exists() or not include_system_packages:
            return user_target
        system_target = safe_child(self.system_package_root, package_id, label="system package")
        return system_target if system_target.exists() else user_target

    def delete_user_package(self, package_id: str) -> dict[str, object]:
        target = self.package_dir(package_id, include_system_packages=False)
        if not target.exists():
            system_target = safe_child(self.system_package_root, package_id, label="system package")
            if system_target.exists():
                raise ValueError(f"built-in agent package cannot be deleted: {package_id}")
            raise FileNotFoundError(f"agent package not found: {package_id}")
        shutil.rmtree(target)
        return {"package_id": package_id, "deleted": True}


def default_package_root() -> Path:
    return project_root() / DEFAULT_AGENT_PACKAGE_ROOT


def default_system_package_root() -> Path:
    return system_package_root()


def safe_child(root: Path, child_name: str, *, label: str) -> Path:
    resolved_root = root.resolve()
    target = (resolved_root / child_name).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes package root: {child_name}") from exc
    return target
