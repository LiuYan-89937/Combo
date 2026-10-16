from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from collections.abc import Iterator


_LEGACY_UPLOAD_ID = re.compile(r"^[a-f0-9]{32}$")
_TIMED_UPLOAD_ID = re.compile(r"^(\d{4}-\d{2}-\d{2})t(\d{2}-\d{2}-\d{2}-\d{3}(?:-\d+)?)$")


def reserve_attachment_directory(root: Path) -> Path:
    """Allocate a local-time date/millisecond directory, atomically disambiguating collisions."""
    now = datetime.now().astimezone()
    day = root / now.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    clock = now.strftime("%H-%M-%S-%f")[:-3]
    sequence = 0
    while True:
        candidate = day / (clock if sequence == 0 else f"{clock}-{sequence}")
        try:
            candidate.mkdir()
        except FileExistsError:
            sequence += 1
            continue
        return candidate


def upload_id_for_directory(entry: Path) -> str:
    if _LEGACY_UPLOAD_ID.fullmatch(entry.name):
        return entry.name
    return f"{entry.parent.name}t{entry.name}"


def upload_directory(root: Path, attachment_id: str) -> Path:
    normalized = attachment_id.strip().lower()
    if _LEGACY_UPLOAD_ID.fullmatch(normalized):
        return root / normalized
    match = _TIMED_UPLOAD_ID.fullmatch(normalized)
    if match is None:
        raise ValueError("invalid attachment_id")
    return root / match.group(1) / match.group(2)


def upload_metadata_path(root: Path, attachment_id: str) -> Path:
    """Keep new upload metadata outside the original filename's namespace."""
    entry = upload_directory(root, attachment_id)
    if _LEGACY_UPLOAD_ID.fullmatch(attachment_id.strip().lower()):
        return entry / "metadata.json"
    return entry.with_suffix(".json")


def attachment_upload_directories(root: Path) -> Iterator[Path]:
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if _LEGACY_UPLOAD_ID.fullmatch(entry.name):
            yield entry
        else:
            for child in entry.iterdir():
                if child.is_dir() and _TIMED_UPLOAD_ID.fullmatch(upload_id_for_directory(child)):
                    yield child
