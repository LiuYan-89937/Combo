from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import unicodedata

from ruamel.yaml import YAML

from combo.dynamic_runtime.capability_blob_store import CapabilityBlobStore
from combo.dynamic_runtime.capability_definitions import (
    SKILL_NAME_PATTERN,
    SkillContentRef,
    SkillDefinition,
)
from combo.runtime_protocol import CapabilityContent, CapabilityDraft, CapabilityTrustLevel


def normalize_staged_skill_package(directory: str | Path) -> Path:
    """Give a staged third-party Skill one portable protocol identity.

    The original front-matter name remains the default display name. Only the
    directory and manifest identity used by the runtime are normalized.
    """
    source = Path(directory).expanduser().resolve()
    manifest = source / "SKILL.md"
    if not source.is_dir() or not manifest.is_file():
        raise ValueError("Skill package must contain SKILL.md at its root")
    metadata, instructions = _parse_skill_manifest(manifest.read_bytes())
    original_name = str(metadata.get("name") or source.name).strip()
    identity = _portable_skill_identity(original_name)
    normalized_metadata = dict(metadata)
    normalized_metadata["name"] = identity
    if not str(normalized_metadata.get("display_name") or "").strip():
        normalized_metadata["display_name"] = original_name
    _write_skill_manifest(
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


def _write_skill_manifest(
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
    descriptor, temporary_name = tempfile.mkstemp(prefix="skill-manifest-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(f"---\n{stream.getvalue()}---\n\n{instructions.strip()}\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class SkillSourceRoot:
    root_id: str
    path: Path
    trust_level: CapabilityTrustLevel

    def __post_init__(self) -> None:
        root_id = str(self.root_id or "").strip()
        if not SKILL_NAME_PATTERN.fullmatch(root_id):
            raise ValueError("skill source root_id must use lowercase kebab-case")
        object.__setattr__(self, "root_id", root_id)
        object.__setattr__(self, "path", Path(self.path).expanduser().resolve())


@dataclass(frozen=True, slots=True)
class FileSystemSkillSourceConfig:
    roots: tuple[SkillSourceRoot, ...]
    publisher_principal_id: str
    source_prefix: str
    maximum_file_bytes: int
    maximum_skill_bytes: int

    def __post_init__(self) -> None:
        if not self.roots:
            raise ValueError("filesystem skill source requires at least one root")
        if len({item.root_id for item in self.roots}) != len(self.roots):
            raise ValueError("filesystem skill source root IDs must be unique")
        if not str(self.publisher_principal_id or "").strip():
            raise ValueError("filesystem skill source requires a publisher principal")
        if not str(self.source_prefix or "").strip():
            raise ValueError("filesystem skill source requires a source prefix")
        if self.maximum_file_bytes < 1 or self.maximum_skill_bytes < self.maximum_file_bytes:
            raise ValueError("filesystem skill source byte limits are invalid")


class FileSystemSkillCapabilitySource:
    """Import explicit Skill roots into immutable metadata and content-addressed blobs."""

    def __init__(
        self,
        *,
        config: FileSystemSkillSourceConfig,
        blobs: CapabilityBlobStore,
    ) -> None:
        self._config = config
        self._blobs = blobs

    def drafts(self) -> tuple[CapabilityDraft, ...]:
        drafts: list[CapabilityDraft] = []
        identities: set[str] = set()
        for source_root in self._config.roots:
            if not source_root.path.is_dir():
                raise FileNotFoundError(f"configured skill source root is unavailable: {source_root.path}")
            for directory in sorted(source_root.path.iterdir(), key=lambda item: item.name):
                if directory.name.startswith(".") or not directory.is_dir() or directory.is_symlink():
                    continue
                manifest = directory / "SKILL.md"
                if not manifest.is_file() or manifest.is_symlink():
                    continue
                draft = self._draft(source_root, directory, manifest)
                if draft.capability_id in identities:
                    raise ValueError(f"duplicate skill capability identity: {draft.capability_id}")
                identities.add(draft.capability_id)
                drafts.append(draft)
        return tuple(drafts)

    def _draft(
        self,
        source_root: SkillSourceRoot,
        directory: Path,
        manifest: Path,
    ) -> CapabilityDraft:
        raw_manifest = self._read_bounded(manifest)
        metadata, instructions = _parse_skill_manifest(raw_manifest)
        name = str(metadata.get("name") or "").strip()
        description = str(metadata.get("description") or "").strip()
        if not SKILL_NAME_PATTERN.fullmatch(name):
            raise ValueError(f"skill name must use lowercase kebab-case: {manifest}")
        if directory.name != name:
            raise ValueError(f"skill directory and manifest name differ: {directory.name} != {name}")
        if not description:
            raise ValueError(f"skill description must not be empty: {manifest}")

        instruction_ref = self._blobs.put_skill_content(
            logical_path="SKILL.md",
            kind="instructions",
            media_type="text/markdown",
            content=instructions.encode("utf-8"),
        )
        contents: list[SkillContentRef] = []
        logical_paths: set[str] = {"skill.md"}
        total_bytes = len(raw_manifest)
        for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
            if path == manifest or path.is_dir():
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"skill content must be a regular non-symlink file: {path}")
            content = self._read_bounded(path)
            total_bytes += len(content)
            if total_bytes > self._config.maximum_skill_bytes:
                raise ValueError(f"skill content exceeds configured byte limit: {directory}")
            logical_path = path.relative_to(directory).as_posix()
            portable_path = logical_path.casefold()
            if portable_path in logical_paths:
                raise ValueError(f"skill content has a cross-platform path collision: {directory}")
            logical_paths.add(portable_path)
            contents.append(
                self._blobs.put_skill_content(
                    logical_path=logical_path,
                    kind=_content_kind(logical_path),
                    media_type=_media_type(path),
                    content=content,
                )
            )
        definition = SkillDefinition(
            name=name,
            display_name=str(metadata.get("display_name") or name).strip(),
            description=description,
            instructions=instruction_ref,
            contents=tuple(contents),
        )
        manifest_digest = _manifest_digest(definition)
        keywords = _keywords(metadata, name)
        return CapabilityDraft(
            capability_id=f"skill://{source_root.root_id}/{name}",
            kind="skill",
            draft_revision=1,
            namespace=f"{source_root.root_id}.{name}",
            resolved_version=manifest_digest,
            source_uri=(
                f"{self._config.source_prefix}{source_root.root_id}/{name}/{manifest_digest}"
            ),
            trust_level=source_root.trust_level,
            content=CapabilityContent(
                display_name=str(metadata.get("display_name") or name).strip(),
                description=description,
                keywords=keywords,
                definition_schema="skill_definition.v3",
                definition=definition.model_dump(mode="json"),
            ),
            updated_by_principal_id=self._config.publisher_principal_id,
        )

    def _read_bounded(self, path: Path) -> bytes:
        size = path.stat().st_size
        if size > self._config.maximum_file_bytes:
            raise ValueError(f"skill file exceeds configured byte limit: {path}")
        content = path.read_bytes()
        if len(content) != size:
            raise RuntimeError(f"skill file changed while it was being imported: {path}")
        return content


def _parse_skill_manifest(content: bytes) -> tuple[dict[str, Any], str]:
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


def _content_kind(logical_path: str) -> str:
    root = logical_path.partition("/")[0]
    return {
        "templates": "template",
        "examples": "example",
        "assets": "asset",
        "scripts": "script",
    }.get(root, "reference")


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _keywords(metadata: dict[str, Any], name: str) -> tuple[str, ...]:
    raw = metadata.get("keywords") or metadata.get("tags") or ()
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, (list, tuple)):
        raise ValueError("skill keywords must be an array of strings")
    return tuple(dict.fromkeys((name, *(str(item).strip() for item in raw if str(item).strip()))))


def _manifest_digest(definition: SkillDefinition) -> str:
    payload = json.dumps(
        definition.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()
