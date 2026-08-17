from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


SKILLHUB_MANIFEST_URL = (
    "https://skillhub-1388575217.cos.ap-guangzhou.myqcloud.com/version.json"
)
SKILLHUB_DISTRIBUTION_HOSTS = frozenset(
    {"skillhub-1388575217.cos.ap-guangzhou.myqcloud.com"}
)
SKILLHUB_DISTRIBUTION_FILES = (
    "skills_store_cli.py",
    "skills_upgrade.py",
    "version.json",
    "metadata.json",
)
MAX_MANIFEST_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_DISTRIBUTION_FILE_BYTES = 8 * 1024 * 1024
_VERSION = re.compile(r"^[0-9][0-9A-Za-z.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def install_skillhub_cli(*, home: Path | None = None) -> dict[str, Any]:
    manifest = _download_manifest()
    archive = _download(
        _trusted_distribution_url(manifest.get("zip_url")),
        maximum_bytes=MAX_ARCHIVE_BYTES,
    )
    _verify_archive_digest(archive, manifest.get("sha256"))
    files = _distribution_files(archive)
    version = _distribution_version(files["version.json"], manifest.get("version"))

    install_root = (home or Path.home()).expanduser().resolve() / ".skillhub"
    _install_distribution_files(install_root, files)
    _initialize_config(install_root, files["metadata.json"])
    return {
        "version": version,
        "cli_path": str((install_root / "skills_store_cli.py").resolve()),
    }


def _download_manifest() -> dict[str, Any]:
    payload = _download(SKILLHUB_MANIFEST_URL, maximum_bytes=MAX_MANIFEST_BYTES)
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("SkillHub distribution manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("SkillHub distribution manifest must be an object")
    return manifest


def _download(url: str, *, maximum_bytes: int) -> bytes:
    request = Request(url, headers={"User-Agent": "Combo-SkillHub-Installer/1"})
    try:
        with closing(urlopen(request, timeout=30)) as response:
            _trusted_distribution_url(response.geturl())
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > maximum_bytes:
                raise RuntimeError("SkillHub distribution exceeds the download limit")
            payload = response.read(maximum_bytes + 1)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"SkillHub distribution download failed: {exc}") from exc
    if len(payload) > maximum_bytes:
        raise RuntimeError("SkillHub distribution exceeds the download limit")
    return payload


def _trusted_distribution_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in SKILLHUB_DISTRIBUTION_HOSTS:
        raise RuntimeError("SkillHub distribution URL is not trusted")
    return url


def _verify_archive_digest(archive: bytes, value: Any) -> None:
    digest = str(value or "").strip()
    if not digest:
        return
    if not _SHA256.fullmatch(digest) or sha256(archive).hexdigest() != digest.lower():
        raise RuntimeError("SkillHub distribution checksum validation failed")


def _distribution_files(archive: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as bundle:
            for filename in SKILLHUB_DISTRIBUTION_FILES:
                member = bundle.getmember(f"cli/{filename}")
                if not member.isfile() or member.size > MAX_DISTRIBUTION_FILE_BYTES:
                    raise RuntimeError(f"SkillHub distribution file is invalid: {filename}")
                source = bundle.extractfile(member)
                if source is None:
                    raise RuntimeError(f"SkillHub distribution file is missing: {filename}")
                files[filename] = source.read()
    except (KeyError, tarfile.TarError) as exc:
        raise RuntimeError("SkillHub distribution archive is invalid") from exc

    for filename in ("skills_store_cli.py", "skills_upgrade.py"):
        try:
            source = files[filename].decode("utf-8")
            compile(source, filename, "exec")
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise RuntimeError(f"SkillHub Python source is invalid: {filename}") from exc
    for filename in ("version.json", "metadata.json"):
        try:
            value = json.loads(files[filename].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"SkillHub JSON metadata is invalid: {filename}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"SkillHub JSON metadata must be an object: {filename}")
    return files


def _distribution_version(version_file: bytes, manifest_version: Any) -> str:
    value = json.loads(version_file.decode("utf-8")).get("version")
    version = str(value or "").strip()
    expected = str(manifest_version or "").strip()
    if not _VERSION.fullmatch(version) or (expected and expected != version):
        raise RuntimeError("SkillHub distribution version is inconsistent")
    return version


def _install_distribution_files(install_root: Path, files: dict[str, bytes]) -> None:
    install_root.parent.mkdir(parents=True, exist_ok=True)
    if install_root.exists():
        if install_root.is_symlink() or not install_root.is_dir():
            raise RuntimeError(f"SkillHub installation root is invalid: {install_root}")
    else:
        install_root.mkdir()
    with tempfile.TemporaryDirectory(
        prefix=".skillhub-cli-install-",
        dir=install_root.parent,
    ) as temporary_directory:
        transaction_root = Path(temporary_directory)
        staged_root = transaction_root / "staged"
        backup_root = transaction_root / "backup"
        staged_root.mkdir()
        backup_root.mkdir()
        for filename, payload in files.items():
            (staged_root / filename).write_bytes(payload)

        installed: list[str] = []
        backed_up: list[str] = []
        try:
            for filename in SKILLHUB_DISTRIBUTION_FILES:
                target = install_root / filename
                if target.exists():
                    if not target.is_file() or target.is_symlink():
                        raise RuntimeError(f"SkillHub installation target is invalid: {target}")
                    os.replace(target, backup_root / filename)
                    backed_up.append(filename)
                os.replace(staged_root / filename, target)
                installed.append(filename)
        except BaseException:
            for filename in installed:
                target = install_root / filename
                if target.exists():
                    target.unlink()
            for filename in backed_up:
                os.replace(backup_root / filename, install_root / filename)
            raise


def _initialize_config(install_root: Path, metadata_file: bytes) -> None:
    config_path = install_root / "config.json"
    if config_path.exists():
        return
    metadata = json.loads(metadata_file.decode("utf-8"))
    update_url = _trusted_distribution_url(metadata.get("self_update_manifest_url"))
    payload = {
        "self_update_url": update_url,
        "client_id": str(uuid4()),
    }
    temporary = config_path.with_name(f".{config_path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, config_path)
