from __future__ import annotations

import importlib.util
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from agent_factory.specs import (
    AgentPackagePrimitives,
    EnvironmentProbe,
    EnvironmentProbeReport,
    Metadata,
    PreconditionSpec,
    ReadinessIssue,
    ReadinessOption,
    ReadinessReport,
    ResourceContract,
    ResourceContractsSpec,
    ShellCapabilitySpec,
    SQLiteColumnContract,
    SQLiteTableContract,
)
from agent_factory.tools.shell import ControlledShellRunner


LOCAL_RESOURCE_PATTERN = re.compile(r"(?:/|~|\./|\../)[^\s，。；：、'\"]+")


class EnvironmentProbeRunner:
    """Build resource-level readiness facts before tool code is generated."""

    def __init__(self, *, shell_runner: ControlledShellRunner | None = None) -> None:
        self.shell_runner = shell_runner or ControlledShellRunner(
            allowed_commands={"sqlite3", "python", "python3"},
            timeout_seconds=5,
        )

    def probe(
        self,
        primitives: AgentPackagePrimitives,
        *,
        requirement: str,
        start_path: str | Path | None = None,
    ) -> tuple[EnvironmentProbeReport, ResourceContractsSpec, ReadinessReport]:
        metadata = _metadata(primitives, "environment")
        resource_metadata = _metadata(primitives, "resource-contracts")
        readiness_metadata = _metadata(primitives, "readiness")
        resource_inputs = _resource_inputs(primitives, requirement, start_path=start_path)
        contracts = [
            self._probe_resource(source_id, ref, access_mode)
            for source_id, ref, access_mode in resource_inputs
        ]
        preconditions = _preconditions_from_contracts(contracts)
        probes = [
            EnvironmentProbe(
                id="python.sqlite3",
                type="python_module_available",
                status="passed" if importlib.util.find_spec("sqlite3") is not None else "failed",
                message="Python sqlite3 module availability.",
            )
        ]
        sqlite3_path = shutil.which("sqlite3")
        probes.append(
            EnvironmentProbe(
                id="cli.sqlite3",
                type="cli_available",
                status="passed" if sqlite3_path else "skipped",
                message="sqlite3 CLI is optional; Python sqlite3 is the primary probe/runtime.",
                details={"path": sqlite3_path} if sqlite3_path else {},
            )
        )
        if sqlite3_path:
            result = self.shell_runner.run([sqlite3_path, "--version"])
            probes.append(
                EnvironmentProbe(
                    id="cli.sqlite3.version",
                    type="cli_version",
                    status="passed" if result.ok else "failed",
                    message=result.stdout.strip() or result.stderr.strip() or result.error,
                    details={"return_code": result.return_code},
                )
            )
        resource_contracts = ResourceContractsSpec(
            schema_version="0.1",
            metadata=resource_metadata,
            resources=contracts,
        )
        readiness = _readiness_from_contracts(readiness_metadata, contracts, preconditions)
        report = EnvironmentProbeReport(
            schema_version="0.1",
            metadata=metadata,
            preconditions=preconditions,
            probes=probes,
            shell_capabilities=[
                ShellCapabilitySpec(
                    id="shell.command",
                    allowed_commands=["sqlite3", "python", "python3"],
                    proposal_only=True,
                    approval_required=True,
                    sandbox_required=True,
                    timeout_seconds=10,
                )
            ],
        )
        return report, resource_contracts, readiness

    def _probe_resource(
        self,
        source_id: str,
        ref: str,
        access_mode: str,
    ) -> ResourceContract:
        path = Path(ref).expanduser()
        resource_type = _resource_type(path)
        if not path.exists():
            return ResourceContract(
                id=source_id,
                type=resource_type,
                ref=str(path),
                exists=False,
                status="missing",
                access_mode=_access_mode(access_mode),
                details={"reason": "resource path does not exist"},
            )
        if path.is_dir():
            return ResourceContract(
                id=source_id,
                type="directory",
                ref=str(path),
                exists=True,
                status="ready" if path.is_dir() else "error",
                access_mode=_access_mode(access_mode),
                details={
                    "readable": _can_read(path),
                    "writable": _can_write(path),
                },
            )
        if resource_type == "sqlite":
            return self._probe_sqlite(source_id, path, access_mode)
        return ResourceContract(
            id=source_id,
            type=resource_type,
            ref=str(path),
            exists=True,
            status="ready" if _can_read(path) else "inaccessible",
            access_mode=_access_mode(access_mode),
            details={
                "readable": _can_read(path),
                "writable": _can_write(path.parent),
                "size_bytes": path.stat().st_size if path.exists() else None,
            },
        )

    def _probe_sqlite(self, source_id: str, path: Path, access_mode: str) -> ResourceContract:
        details: dict[str, Any] = {
            "readable": _can_read(path),
            "writable": _can_write(path.parent),
            "sandbox_copyable": _can_copy_to_sandbox(path),
        }
        tables: list[SQLiteTableContract] = []
        status = "ready"
        try:
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
                rows = conn.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
                details["tables"] = [row[0] for row in rows]
                for table_name, create_sql in rows:
                    columns = conn.execute(f"PRAGMA table_info({ _quote_identifier(table_name) })").fetchall()
                    column_contracts = [
                        SQLiteColumnContract(
                            name=str(column[1]),
                            type=str(column[2] or ""),
                            not_null=bool(column[3]),
                            default=None if column[4] is None else str(column[4]),
                            primary_key=bool(column[5]),
                        )
                        for column in columns
                    ]
                    primary_keys = [column.name for column in column_contracts if column.primary_key]
                    required_columns = [
                        column.name
                        for column in column_contracts
                        if column.not_null and not column.primary_key and column.default is None
                    ]
                    tables.append(
                        SQLiteTableContract(
                            name=str(table_name),
                            columns=column_contracts,
                            primary_keys=primary_keys,
                            required_columns=required_columns,
                            check_constraints=_extract_check_constraints(str(create_sql or "")),
                        )
                    )
        except sqlite3.Error as error:
            status = "error"
            details["error"] = str(error)
        return ResourceContract(
            id=source_id,
            type="sqlite",
            ref=str(path),
            exists=True,
            status=status,  # type: ignore[arg-type]
            access_mode=_access_mode(access_mode),
            details=details,
            sqlite_tables=tables,
        )


def _resource_inputs(
    primitives: AgentPackagePrimitives,
    requirement: str,
    *,
    start_path: str | Path | None,
) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    values: list[tuple[str, str, str]] = []
    for source in primitives.knowledge.sources:
        if not source.ref:
            continue
        key = str(Path(source.ref).expanduser())
        seen.add(key)
        values.append((source.id, source.ref, source.access_mode))
    root = Path(start_path or ".").resolve()
    for raw in LOCAL_RESOURCE_PATTERN.findall(requirement):
        ref = raw.rstrip(".,;:，。；：、)")
        path = Path(ref).expanduser()
        if not path.is_absolute():
            path = root / path
        key = str(path)
        if key in seen:
            continue
        if not _looks_like_resource_reference(path):
            continue
        seen.add(key)
        values.append((_resource_id(path), str(path), _access_mode_from_requirement(requirement)))
    return values


def _preconditions_from_contracts(contracts: list[ResourceContract]) -> list[PreconditionSpec]:
    preconditions: list[PreconditionSpec] = []
    for resource in contracts:
        preconditions.append(
            PreconditionSpec(
                id=f"{resource.id}.exists",
                type="resource_exists",
                description=f"Resource exists: {resource.ref}",
                status="passed" if resource.exists else "failed",
                resource_ref=resource.id,
            )
        )
        if resource.exists:
            preconditions.append(
                PreconditionSpec(
                    id=f"{resource.id}.readable",
                    type="resource_readable",
                    description=f"Resource is readable: {resource.ref}",
                    status="passed" if resource.status in {"ready", "unsupported"} else "failed",
                    resource_ref=resource.id,
                    details=resource.details,
                )
            )
        if resource.type == "sqlite":
            preconditions.append(
                PreconditionSpec(
                    id=f"{resource.id}.sqlite_openable",
                    type="sqlite_openable",
                    description=f"SQLite database can be opened: {resource.ref}",
                    status="passed" if resource.status == "ready" else "failed",
                    resource_ref=resource.id,
                    details=resource.details,
                )
            )
            preconditions.append(
                PreconditionSpec(
                    id=f"{resource.id}.sqlite_schema",
                    type="sqlite_schema_available",
                    description=f"SQLite schema is available: {resource.ref}",
                    status="passed" if resource.sqlite_tables else "failed",
                    resource_ref=resource.id,
                )
            )
            preconditions.append(
                PreconditionSpec(
                    id=f"{resource.id}.sandbox_copyable",
                    type="sandbox_copyable",
                    description=f"SQLite database can be copied into tool-test sandbox: {resource.ref}",
                    status="passed" if resource.details.get("sandbox_copyable") else "failed",
                    resource_ref=resource.id,
                )
            )
    return preconditions


def _readiness_from_contracts(
    metadata: Metadata,
    contracts: list[ResourceContract],
    preconditions: list[PreconditionSpec],
) -> ReadinessReport:
    failed_required = [item for item in preconditions if item.required and item.status == "failed"]
    issues = [
        ReadinessIssue(
            code=item.type,
            message=item.description,
            severity="error",
            resource_id=item.resource_ref,
        )
        for item in failed_required
    ]
    if not failed_required:
        return ReadinessReport(schema_version="0.1", metadata=metadata, status="ready")
    has_missing = any(resource.status == "missing" for resource in contracts)
    options = [
        ReadinessOption(
            id="replace_resource_path",
            label="提供新的资源路径",
            description="用户提供一个已存在、可访问的本地资源路径。",
            action="replace_resource_path",
        ),
        ReadinessOption(
            id="generate_draft_only",
            label="只生成草稿",
            description="暂不执行工具测试，生成不可直接运行的草稿包。",
            action="generate_draft_only",
        ),
    ]
    if has_missing:
        options.insert(
            0,
            ReadinessOption(
                id="create_sample_resource",
                label="创建示例资源",
                description="由用户确认后创建示例数据库或文件，再继续生产。",
                action="create_sample_resource",
            ),
        )
    return ReadinessReport(
        schema_version="0.1",
        metadata=metadata,
        status="needs_user_input",
        issues=issues,
        options=options,
    )


def _metadata(primitives: AgentPackagePrimitives, suffix: str) -> Metadata:
    metadata = primitives.instructions.metadata
    return Metadata(
        name=f"{metadata.name}-{suffix}",
        version=metadata.version,
        description=metadata.description,
        owner=metadata.owner,
    )


def _resource_type(path: Path) -> str:
    if path.is_dir():
        return "directory"
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return "sqlite"
    if path.suffix:
        return "file"
    return "unknown"


def _access_mode(value: str) -> str:
    return "read_write" if value == "read_write" else "read_only"


def _access_mode_from_requirement(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in ("创建", "更新", "修改", "关闭", "写", "insert", "update", "create")):
        return "read_write"
    return "read_only"


def _looks_like_resource_reference(path: Path) -> bool:
    return path.suffix.lower() in {
        ".csv",
        ".db",
        ".duckdb",
        ".json",
        ".md",
        ".sqlite",
        ".sqlite3",
        ".tsv",
        ".txt",
        ".yaml",
        ".yml",
    } or path.exists()


def _resource_id(path: Path) -> str:
    stem = path.stem or path.name or "resource"
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"sqlite", "sqlite3", "db", "duckdb"} and not stem.endswith("_sqlite"):
        stem = f"{stem}_sqlite"
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", stem).strip("_").lower()
    if not normalized:
        normalized = "resource"
    if normalized[0].isdigit():
        normalized = f"resource_{normalized}"
    return normalized


def _can_read(path: Path) -> bool:
    try:
        if path.is_dir():
            next(path.iterdir(), None)
            return True
        with path.open("rb"):
            return True
    except OSError:
        return False


def _can_write(path: Path) -> bool:
    return path.exists() and path.is_dir()


def _can_copy_to_sandbox(path: Path) -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            shutil.copy2(path, Path(tmpdir) / path.name)
        return True
    except OSError:
        return False


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _extract_check_constraints(create_sql: str) -> list[str]:
    return [match.group(0) for match in re.finditer(r"CHECK\s*\([^)]+\)", create_sql, flags=re.IGNORECASE)]
