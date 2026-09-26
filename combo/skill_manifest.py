from __future__ import annotations

from hashlib import sha256
from io import StringIO
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import unicodedata

from ruamel.yaml import YAML

from combo.file_atomic import atomic_write_text


SKILL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,127}$")


def normalize_staged_skill_package(directory: str | Path) -> Path:
    """Give a staged third-party Skill one portable protocol identity.

    The original front-matter name remains the default display name. Only the
    directory and manifest identity used by the runtime are normalized.
    """
    source = Path(directory).expanduser().resolve()
    manifest = source / "SKILL.md"
    if not source.is_dir() or not manifest.is_file():
        raise ValueError("Skill package must contain SKILL.md at its root")
    metadata, instructions = parse_skill_manifest(manifest.read_bytes())
    original_name = str(metadata.get("name") or source.name).strip()
    identity = _portable_skill_identity(original_name)
    normalized_metadata = dict(metadata)
    normalized_metadata["name"] = identity
    if not str(normalized_metadata.get("display_name") or "").strip():
        normalized_metadata["display_name"] = original_name
    write_skill_manifest(
        manifest,
        metadata=normalized_metadata,
        instructions=instructions,
    )
    target = source.parent / identity
    if target == source:
        return source
    if target.exists():
        if not os.path.samefile(source, target):
            raise FileExistsError(f"normalized Skill package already exists: {target}")
        descriptor, intermediate_name = tempfile.mkstemp(prefix=".skill-identity-", dir=source.parent)
        os.close(descriptor)
        intermediate = Path(intermediate_name)
        intermediate.unlink()
        os.replace(source, intermediate)
        try:
            os.replace(intermediate, target)
        except BaseException:
            os.replace(intermediate, source)
            raise
        return target
    os.replace(source, target)
    return target


def _portable_skill_identity(value: str) -> str:
    original = str(value or "").strip()
    if not original:
        raise ValueError("Skill name must not be empty")
    decomposed = unicodedata.normalize("NFKD", original)
    ascii_value = decomposed.encode("ascii", "ignore").decode("ascii")
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", ascii_value)
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", separated).strip("-").lower()
    if not normalized:
        normalized = f"skill-{sha256(original.encode('utf-8')).hexdigest()[:12]}"
    if normalized[0].isdigit():
        normalized = f"skill-{normalized}"
    if len(normalized) < 2:
        normalized = f"skill-{normalized}"
    normalized = normalized[:128].rstrip("-")
    if not SKILL_NAME_PATTERN.fullmatch(normalized):
        raise ValueError(f"Skill name cannot be normalized to lowercase kebab-case: {original}")
    return normalized


def write_skill_manifest(
    path: Path,
    *,
    metadata: dict[str, Any],
    instructions: str,
) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    stream = StringIO()
    yaml.dump(metadata, stream)
    atomic_write_text(path, f"---\n{stream.getvalue()}---\n\n{instructions.strip()}\n")


def parse_skill_manifest(content: bytes) -> tuple[dict[str, Any], str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SKILL.md must be valid UTF-8") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md requires YAML front matter")
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("SKILL.md YAML front matter is not closed") from exc
    yaml = YAML(typ="safe")
    loaded = yaml.load("\n".join(lines[1:closing])) or {}
    if not isinstance(loaded, dict):
        raise ValueError("SKILL.md front matter must be a mapping")
    body = "\n".join(lines[closing + 1 :]).strip()
    if not body:
        raise ValueError("SKILL.md instructions must not be empty")
    return {str(key): value for key, value in loaded.items()}, body
