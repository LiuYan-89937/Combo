from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from combo.dynamic_runtime.capability_blob_store import CapabilityBlobStore
from combo.dynamic_runtime.content_media import media_type_for_path
from combo.dynamic_runtime.capability_definitions import (
    SkillContentKind,
    SkillContentRef,
    SkillDefinition,
)
from combo.dynamic_runtime.filesystem_source_cache import (
    CapabilityDraftSource,
    FileSystemCapabilityDraftCache,
)
from combo.runtime_protocol import CapabilityContent, CapabilityDraft, CapabilityTrustLevel
from combo.skill_manifest import SKILL_NAME_PATTERN, parse_skill_manifest


SKILL_DRAFT_CACHE_NAMESPACE = "filesystem-skill.v1"


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
        cache: FileSystemCapabilityDraftCache | None = None,
    ) -> None:
        self._config = config
        self._blobs = blobs
        self._cache = cache

    def drafts(self) -> tuple[CapabilityDraft, ...]:
        sources: list[CapabilityDraftSource] = []
        for source_root in self._config.roots:
            if not source_root.path.is_dir():
                raise FileNotFoundError(f"configured skill source root is unavailable: {source_root.path}")
            for directory in sorted(source_root.path.iterdir(), key=lambda item: item.name):
                if directory.name.startswith(".") or not directory.is_dir() or directory.is_symlink():
                    continue
                manifest = directory / "SKILL.md"
                if not manifest.is_file() or manifest.is_symlink():
                    continue
                sources.append(CapabilityDraftSource(
                    cache_key=(
                        f"{self._config.source_prefix}|{source_root.root_id}|"
                        f"{source_root.trust_level}|{directory.name}"
                    ),
                    directory=directory,
                    build=lambda root=source_root, folder=directory, path=manifest: self._draft(
                        root,
                        folder,
                        path,
                    ),
                ))
        drafts = self._cache.resolve(tuple(sources)) if self._cache is not None else tuple(
            source.build() for source in sources
        )
        identities = [draft.capability_id for draft in drafts]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate skill capability identity")
        return tuple(
            draft.model_copy(
                update={"updated_by_principal_id": self._config.publisher_principal_id}
            )
            for draft in drafts
        )

    def _draft(
        self,
        source_root: SkillSourceRoot,
        directory: Path,
        manifest: Path,
    ) -> CapabilityDraft:
        raw_manifest = self._read_bounded(manifest)
        metadata, instructions = parse_skill_manifest(raw_manifest)
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
                    media_type=media_type_for_path(path, content=content),
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


def _content_kind(logical_path: str) -> SkillContentKind:
    root = logical_path.partition("/")[0]
    kinds: dict[str, SkillContentKind] = {
        "templates": "template",
        "examples": "example",
        "assets": "asset",
        "scripts": "script",
    }
    return kinds.get(root, "reference")


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
