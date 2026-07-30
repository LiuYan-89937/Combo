from __future__ import annotations

import os
from pathlib import Path


class WorkspaceDirectoryBrowser:
    def __init__(self, roots: tuple[Path, ...] | None = None) -> None:
        self.roots = roots or _configured_roots()

    def root_views(self) -> list[dict[str, str]]:
        return [
            {"name": root.name or str(root), "path": str(root)}
            for root in self.roots
        ]

    def list_directories(self, path: str) -> dict[str, object]:
        current = self.resolve(path)
        directories: list[dict[str, str]] = []
        for child in sorted(current.iterdir(), key=lambda item: item.name.casefold()):
            try:
                if child.is_dir():
                    directories.append({"name": child.name, "path": str(child.resolve())})
            except OSError:
                continue
        parent = current.parent
        return {
            "path": str(current),
            "parent": str(parent) if self._is_allowed(parent) else None,
            "directories": directories,
        }

    def resolve(self, value: str) -> Path:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("directory path must not be empty")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise ValueError("directory path must be absolute")
        resolved = candidate.resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"workspace directory not found: {resolved}")
        if not self._is_allowed(resolved):
            raise PermissionError(f"workspace directory is outside configured roots: {resolved}")
        return resolved

    def _is_allowed(self, path: Path) -> bool:
        resolved = path.expanduser().resolve()
        return any(_is_relative_to(resolved, root) for root in self.roots)


def _configured_roots() -> tuple[Path, ...]:
    home = Path.home().resolve()
    if not home.is_dir():
        raise RuntimeError(f"local home directory is unavailable: {home}")
    roots = [home]
    if os.name == "nt":
        roots.extend(_windows_drive_roots())
    else:
        roots.extend(_wsl_windows_mounts())
    return tuple(dict.fromkeys(roots))


def _windows_drive_roots() -> list[Path]:
    import ctypes

    drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
    if drive_mask == 0:
        return []
    roots: list[Path] = []
    for index in range(26):
        if not drive_mask & (1 << index):
            continue
        root = Path(f"{chr(ord('A') + index)}:\\")
        if root.is_dir():
            roots.append(root.resolve())
    return roots


def _wsl_windows_mounts() -> list[Path]:
    if not os.getenv("WSL_DISTRO_NAME"):
        return []
    mounts_path = Path("/proc/mounts")
    if not mounts_path.is_file():
        return []
    roots: list[Path] = []
    for line in mounts_path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[2] != "9p":
            continue
        options = set(fields[3].split(","))
        if not any(option.startswith("aname=drvfs") for option in options):
            continue
        mount = Path(_decode_mount_field(fields[1])).resolve()
        if mount.is_dir():
            roots.append(mount)
    return roots


def _decode_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
