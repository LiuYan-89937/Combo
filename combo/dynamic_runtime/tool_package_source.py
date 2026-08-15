from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ruamel.yaml import YAML

from combo.dynamic_runtime.capability_blob_store import CapabilityBlobStore
from combo.dynamic_runtime.capability_definitions import (
    CapabilityPlatform,
    ToolDefinition,
    ToolEffect,
    ToolImplementation,
    ToolLoopPolicy,
    ToolRuntimePolicy,
    RuntimeResourceName,
)
from combo.dynamic_runtime.content_media import media_type_for_path
from combo.environment_system.python_requirements import normalize_python_requirements
from combo.runtime_protocol import CapabilityContent, CapabilityDraft, CapabilityTrustLevel


_PACKAGE_NAME = re.compile(r"^[a-z][a-z0-9-]{1,127}$")
_MODEL_ALIAS = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ToolPackagePermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval: Literal["inherit", "allow", "ask", "deny"] = "inherit"
    risk_level: Literal["low", "medium", "high"] = "low"
    effects: tuple[ToolEffect, ...] = ("read",)
    read_only: bool = True
    sensitive_argument_paths: tuple[str, ...] = ()


class ToolPackageExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_parallel_calls: bool = True
    max_parallel_calls: int = Field(default=1, ge=1, le=128)
    timeout_seconds: float = Field(default=300.0, gt=0, le=3600)
    output_projection: Literal["compress", "passthrough"] = "compress"
    output_max_model_chars: int = Field(default=50_000, ge=1_000, le=1_000_000)
    retain_raw_output: bool = True

    @model_validator(mode="after")
    def _parallel_limit_matches_switch(self) -> "ToolPackageExecution":
        if not self.allow_parallel_calls and self.max_parallel_calls != 1:
            raise ValueError("non-parallel ToolPackage must use max_parallel_calls=1")
        return self


class ToolPackageRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platforms: tuple[CapabilityPlatform, ...] = ("any",)
    required_input_modalities: tuple[Literal["text", "image", "audio", "video"], ...] = ("text",)
    output_modalities: tuple[Literal["text", "image", "audio", "video", "file", "structured"], ...] = (
        "structured",
    )
    platform_resources: tuple[RuntimeResourceName, ...] = ()
    system_available: bool = False


class ToolPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["tool_package.v1"] = "tool_package.v1"
    name: str
    model_alias: str
    display_name: str | None = None
    description: str
    keywords: tuple[str, ...] = ()
    entrypoint: str = "main:run"
    schema_error_guidance: str = ""
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    permissions: ToolPackagePermissions = Field(default_factory=ToolPackagePermissions)
    execution: ToolPackageExecution = Field(default_factory=ToolPackageExecution)
    loop_policy: ToolLoopPolicy = Field(default_factory=ToolLoopPolicy)
    runtime: ToolPackageRuntime = Field(default_factory=ToolPackageRuntime)

    @field_validator("name")
    @classmethod
    def _name_is_portable(cls, value: str) -> str:
        text = str(value or "").strip()
        if not _PACKAGE_NAME.fullmatch(text):
            raise ValueError("ToolPackage name must use lowercase kebab-case")
        return text

    @field_validator("model_alias")
    @classmethod
    def _model_alias_is_valid(cls, value: str) -> str:
        text = str(value or "").strip()
        if not _MODEL_ALIAS.fullmatch(text):
            raise ValueError("ToolPackage model_alias must use lowercase snake_case")
        return text

    @field_validator("description")
    @classmethod
    def _description_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("ToolPackage description must not be empty")
        return text

    @field_validator("display_name")
    @classmethod
    def _optional_display_name(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("entrypoint")
    @classmethod
    def _entrypoint_is_local_python(cls, value: str) -> str:
        text = str(value or "").strip()
        if text.count(":") != 1:
            raise ValueError("ToolPackage entrypoint must use '<module>:<callable>'")
        module, function = text.split(":", 1)
        if not module or not function or not all(part.isidentifier() for part in module.split(".")) or not function.isidentifier():
            raise ValueError("ToolPackage entrypoint must reference a local Python module and callable")
        return text

    @field_validator("keywords")
    @classmethod
    def _keywords_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(value or "").strip() for value in values)
        if any(not value for value in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("ToolPackage keywords must be non-empty and unique")
        return normalized


@dataclass(frozen=True, slots=True)
class ToolSourceRoot:
    root_id: str
    path: Path
    trust_level: CapabilityTrustLevel

    def __post_init__(self) -> None:
        root_id = str(self.root_id or "").strip()
        if not _PACKAGE_NAME.fullmatch(root_id):
            raise ValueError("tool source root_id must use lowercase kebab-case")
        object.__setattr__(self, "root_id", root_id)
        object.__setattr__(self, "path", Path(self.path).expanduser().resolve())


@dataclass(frozen=True, slots=True)
class FileSystemToolSourceConfig:
    roots: tuple[ToolSourceRoot, ...]
    publisher_principal_id: str
    source_prefix: str
    maximum_file_bytes: int
    maximum_tool_bytes: int

    def __post_init__(self) -> None:
        if not self.roots or len({item.root_id for item in self.roots}) != len(self.roots):
            raise ValueError("filesystem tool source requires unique source roots")
        if not str(self.publisher_principal_id or "").strip() or not str(self.source_prefix or "").strip():
            raise ValueError("filesystem tool source requires publisher and source prefix")
        if self.maximum_file_bytes < 1 or self.maximum_tool_bytes < self.maximum_file_bytes:
            raise ValueError("filesystem tool source byte limits are invalid")


class FileSystemToolCapabilitySource:
    """Load one immutable, model-callable ToolPackage from each child directory."""

    def __init__(self, *, config: FileSystemToolSourceConfig, blobs: CapabilityBlobStore) -> None:
        self._config = config
        self._blobs = blobs

    def drafts(self) -> tuple[CapabilityDraft, ...]:
        drafts: list[CapabilityDraft] = []
        identities: set[str] = set()
        for source_root in self._config.roots:
            if not source_root.path.is_dir():
                raise FileNotFoundError(f"configured tool source root is unavailable: {source_root.path}")
            for directory in sorted(source_root.path.iterdir(), key=lambda item: item.name):
                if directory.name.startswith(".") or not directory.is_dir() or directory.is_symlink():
                    continue
                manifest_path = directory / "TOOL.yaml"
                if not manifest_path.is_file() or manifest_path.is_symlink():
                    continue
                draft = self._draft(source_root, directory, manifest_path)
                if draft.capability_id in identities:
                    raise ValueError(f"duplicate tool capability identity: {draft.capability_id}")
                identities.add(draft.capability_id)
                drafts.append(draft)
        return tuple(drafts)

    def _draft(self, source_root: ToolSourceRoot, directory: Path, manifest_path: Path) -> CapabilityDraft:
        manifest_bytes = self._read_bounded(manifest_path)
        manifest = _parse_manifest(manifest_bytes, manifest_path)
        if source_root.trust_level != "builtin" and (
            manifest.runtime.platform_resources or manifest.runtime.system_available
        ):
            raise ValueError("local ToolPackages cannot request trusted platform resources or system availability")
        if directory.name != manifest.name:
            raise ValueError(f"ToolPackage directory and manifest name differ: {directory.name} != {manifest.name}")
        entry_module, entry_function = manifest.entrypoint.split(":", 1)
        entry_path = directory.joinpath(*entry_module.split(".")).with_suffix(".py")
        if not entry_path.is_file() or entry_path.is_symlink():
            raise ValueError(f"ToolPackage entrypoint module is unavailable: {entry_path}")
        _validate_entrypoint_contract(entry_path, entry_function)

        files = []
        portable_paths: set[str] = set()
        total_bytes = 0
        for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_dir():
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"ToolPackage content must be a regular non-symlink file: {path}")
            content = self._read_bounded(path)
            total_bytes += len(content)
            if total_bytes > self._config.maximum_tool_bytes:
                raise ValueError(f"ToolPackage exceeds configured byte limit: {directory}")
            logical_path = path.relative_to(directory).as_posix()
            portable = logical_path.casefold()
            if portable in portable_paths:
                raise ValueError(f"ToolPackage has a cross-platform path collision: {directory}")
            portable_paths.add(portable)
            files.append(
                self._blobs.put_tool_package_file(
                    logical_path=logical_path,
                    media_type=media_type_for_path(path, content=content),
                    content=content,
                )
            )
        required_paths = {"TOOL.yaml", "main.py"}
        if not required_paths.issubset({item.logical_path for item in files}):
            raise ValueError("ToolPackage requires TOOL.yaml and main.py at its root")
        requirements = _requirements(directory / "requirements.txt")
        package_digest = _package_digest(files)
        permissions = manifest.permissions
        execution = manifest.execution
        definition = ToolDefinition(
            model_alias=manifest.model_alias,
            model_description=manifest.description,
            schema_error_guidance=manifest.schema_error_guidance,
            input_schema=manifest.input_schema,
            output_schema=manifest.output_schema,
            implementation=ToolImplementation(
                kind="python_package",
                entrypoint=manifest.entrypoint,
                package_digest=package_digest,
                package_files=tuple(files),
                python_requirements=tuple(requirements),
                package_runtime="isolated",
            ),
            runtime_policy=ToolRuntimePolicy(
                approval=permissions.approval,
                risk_level=permissions.risk_level,
                allow_parallel_calls=execution.allow_parallel_calls,
                max_parallel_calls=execution.max_parallel_calls,
                serialization_key=None if execution.allow_parallel_calls else manifest.model_alias,
                timeout_seconds=execution.timeout_seconds,
                output_projection=execution.output_projection,
                output_max_model_chars=execution.output_max_model_chars,
                retain_raw_output=execution.retain_raw_output,
            ),
            loop_policy=manifest.loop_policy,
            runtime_resources=manifest.runtime.platform_resources,
            effects=permissions.effects,
            read_only=permissions.read_only,
            system_available=manifest.runtime.system_available,
            required_input_modalities=manifest.runtime.required_input_modalities,
            output_modalities=manifest.runtime.output_modalities,
            platforms=manifest.runtime.platforms,
            sensitive_argument_paths=permissions.sensitive_argument_paths,
        )
        return CapabilityDraft(
            capability_id=f"tool://{source_root.root_id}/{manifest.name}",
            kind="tool",
            draft_revision=1,
            namespace=f"{source_root.root_id}.{manifest.name}",
            resolved_version=package_digest,
            source_uri=f"{self._config.source_prefix}{source_root.root_id}/{manifest.name}/{package_digest}",
            trust_level=source_root.trust_level,
            content=CapabilityContent(
                display_name=manifest.display_name or manifest.name,
                description=manifest.description,
                keywords=tuple(dict.fromkeys((manifest.name, manifest.model_alias, *manifest.keywords))),
                definition_schema="tool_definition.v2",
                definition=definition.model_dump(mode="json"),
            ),
            updated_by_principal_id=self._config.publisher_principal_id,
        )

    def _read_bounded(self, path: Path) -> bytes:
        size = path.stat().st_size
        if size > self._config.maximum_file_bytes:
            raise ValueError(f"ToolPackage file exceeds configured byte limit: {path}")
        content = path.read_bytes()
        if len(content) != size:
            raise RuntimeError(f"ToolPackage file changed while being imported: {path}")
        return content


def _parse_manifest(content: bytes, path: Path) -> ToolPackageManifest:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"TOOL.yaml must be UTF-8: {path}") from exc
    document = YAML(typ="safe").load(text)
    if not isinstance(document, dict):
        raise ValueError(f"TOOL.yaml must contain a mapping: {path}")
    return ToolPackageManifest.model_validate(document)


def _validate_entrypoint_contract(path: Path, function_name: str) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise ValueError(f"ToolPackage entrypoint is not valid UTF-8 Python: {path}: {exc}") from exc
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    ]
    if len(matches) != 1:
        raise ValueError(f"ToolPackage entrypoint must define exactly one {function_name} function")
    function = matches[0]
    positional = [*function.args.posonlyargs, *function.args.args]
    if (
        [item.arg for item in positional] != ["arguments", "context"]
        or function.args.vararg is not None
        or function.args.kwarg is not None
        or function.args.kwonlyargs
    ):
        raise ValueError("ToolPackage entrypoint must use run(arguments, context)")
    if isinstance(function, ast.AsyncFunctionDef):
        raise ValueError("ToolPackage entrypoint must be synchronous; async execution is managed by the runtime")


def _requirements(path: Path) -> list[str]:
    if not path.exists():
        return []
    if not path.is_file() or path.is_symlink():
        raise ValueError("requirements.txt must be a regular file")
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            values.append(value)
    return normalize_python_requirements(values)


def _package_digest(files: list[object]) -> str:
    payload = [
        {
            "logical_path": item.logical_path,
            "content_digest": item.content_digest,
            "size_bytes": item.size_bytes,
        }
        for item in sorted(files, key=lambda item: item.logical_path)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()
