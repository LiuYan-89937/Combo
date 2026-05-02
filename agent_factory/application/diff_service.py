from __future__ import annotations

import difflib
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin


class PackageDiffEntry(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    path: str
    change_type: Literal["added", "modified", "deleted"]
    diff: str = ""


class PackageDiff(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    base_path: Path
    target_path: Path
    entries: list[PackageDiffEntry] = Field(default_factory=list)


class DiffService:
    def diff(self, base_path: Path, target_path: Path) -> PackageDiff:
        base_files = _file_map(base_path)
        target_files = _file_map(target_path)
        entries: list[PackageDiffEntry] = []
        for relative in sorted(set(base_files) | set(target_files)):
            if relative not in base_files:
                entries.append(PackageDiffEntry(path=relative, change_type="added"))
            elif relative not in target_files:
                entries.append(PackageDiffEntry(path=relative, change_type="deleted"))
            elif base_files[relative] != target_files[relative]:
                entries.append(
                    PackageDiffEntry(
                        path=relative,
                        change_type="modified",
                        diff="\n".join(
                            difflib.unified_diff(
                                base_files[relative].splitlines(),
                                target_files[relative].splitlines(),
                                fromfile=f"a/{relative}",
                                tofile=f"b/{relative}",
                                lineterm="",
                            )
                        ),
                    )
                )
        return PackageDiff(base_path=base_path, target_path=target_path, entries=entries)


def _file_map(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if "__pycache__" in path.parts:
            continue
        values[str(path.relative_to(root))] = path.read_text(encoding="utf-8", errors="replace")
    return values
