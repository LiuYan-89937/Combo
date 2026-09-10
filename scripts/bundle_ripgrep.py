#!/usr/bin/env python3
"""Install the pinned ripgrep executable used by Combo's filesystem search tool."""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import shutil
import tarfile
from urllib.request import Request, urlopen
import zipfile


RIPGREP_VERSION = "14.1.1"
TARGETS = {
    "macos-arm64": {
        "archive": f"ripgrep-{RIPGREP_VERSION}-aarch64-apple-darwin.tar.gz",
        "sha256": "24ad76777745fbff131c8fbc466742b011f925bfa4fffa2ded6def23b5b937be",
        "member": f"ripgrep-{RIPGREP_VERSION}-aarch64-apple-darwin/rg",
        "executable": "rg",
    },
    "windows-x64": {
        "archive": f"ripgrep-{RIPGREP_VERSION}-x86_64-pc-windows-msvc.zip",
        "sha256": "d0f534024c42afd6cb4d38907c25cd2b249b79bbe6cc1dbee8e3e37c2b6e25a1",
        "member": f"ripgrep-{RIPGREP_VERSION}-x86_64-pc-windows-msvc/rg.exe",
        "executable": "rg.exe",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=tuple(TARGETS), required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    project_root = args.project_root.expanduser().resolve()
    specification = TARGETS[args.target]
    archive_name = str(specification["archive"])
    archive_path = project_root / "build" / "ripgrep-downloads" / archive_name
    destination = (
        project_root / "src-tauri" / "resources" / "ripgrep" / str(specification["executable"])
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)

    expected_hash = str(specification["sha256"])
    if not _has_hash(archive_path, expected_hash):
        _download(
            f"https://github.com/BurntSushi/ripgrep/releases/download/{RIPGREP_VERSION}/{archive_name}",
            archive_path,
        )
    if not _has_hash(archive_path, expected_hash):
        raise RuntimeError(f"ripgrep archive checksum mismatch: {archive_path}")

    temporary = destination.with_suffix(destination.suffix + ".new")
    _extract_member(archive_path, str(specification["member"]), temporary)
    temporary.chmod(0o755)
    temporary.replace(destination)
    print(f"Bundled ripgrep {RIPGREP_VERSION}: {destination}")


def _download(url: str, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".download")
    request = Request(url, headers={"User-Agent": "Combo-build"})
    with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output)
    temporary.replace(destination)


def _has_hash(path: Path, expected: str) -> bool:
    if not path.is_file():
        return False
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def _extract_member(archive_path: Path, member_name: str, destination: Path) -> None:
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive, archive.open(member_name) as source:
            with destination.open("wb") as output:
                shutil.copyfileobj(source, output)
        return
    with tarfile.open(archive_path, mode="r:gz") as archive:
        member = archive.getmember(member_name)
        source = archive.extractfile(member)
        if source is None or not member.isfile():
            raise RuntimeError(f"ripgrep archive member is not a regular file: {member_name}")
        with source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)


if __name__ == "__main__":
    main()
