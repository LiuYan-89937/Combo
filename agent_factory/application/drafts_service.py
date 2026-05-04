from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field
from ruamel.yaml import YAML

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.package import PackageLoadError, PackageLoader, PackageValidator
from agent_factory.specs import PackageManifest, ValidationReport


class DraftAgentSummary(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    id: str
    path: Path
    agent_id: str | None = None
    agent_name: str
    version: str | None = None
    status: str = "unknown"
    description: str | None = None
    updated_at: datetime
    validation_status: str = "unknown"
    verification_status: str = "unknown"
    tool_count: int = 0
    harness_scenario_count: int = 0

    @property
    def display_id(self) -> str:
        return _short_draft_id(self.id)


class DraftsListResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    workspace_path: Path
    drafts_path: Path
    drafts: list[DraftAgentSummary] = Field(default_factory=list)


class DraftAgentDetail(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    summary: DraftAgentSummary
    manifest: PackageManifest | None = None
    validation_report: ValidationReport | None = None
    persona: str | None = None
    goal: str | None = None
    boundaries: list[str] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list)
    mcp_binding_ids: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class DraftDeleteResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    id: str
    path: Path
    deleted: bool
    message: str


class DraftsService:
    def __init__(
        self,
        *,
        loader: PackageLoader | None = None,
        validator: PackageValidator | None = None,
    ) -> None:
        self.loader = loader or PackageLoader()
        self.validator = validator or PackageValidator()
        self.yaml = YAML(typ="safe")

    def list_drafts(self, *, start_path: str | Path | None = None) -> DraftsListResult:
        context = FactoryRunContext.create(start_path=start_path)
        drafts_path = context.drafts_path
        drafts_path.mkdir(parents=True, exist_ok=True)
        summaries = [
            self._summarize(path)
            for path in sorted(drafts_path.iterdir(), key=_mtime, reverse=True)
            if path.is_dir()
        ]
        return DraftsListResult(
            workspace_path=context.workspace_path,
            drafts_path=drafts_path,
            drafts=summaries,
        )

    def show_draft(
        self,
        identifier: str | Path | None = "latest",
        *,
        start_path: str | Path | None = None,
    ) -> DraftAgentDetail | None:
        path = self.resolve_draft(identifier, start_path=start_path)
        if path is None:
            return None
        summary = self._summarize(path)
        manifest: PackageManifest | None = None
        validation_report = self.validator.validate_full_package(path)
        persona: str | None = None
        goal: str | None = None
        boundaries: list[str] = []
        tool_ids: list[str] = []
        mcp_binding_ids: list[str] = []
        scenario_ids: list[str] = []

        try:
            package = self.loader.load_full_package(path)
            manifest = package.manifest
            persona = package.primitives.instructions.persona
            goal = package.primitives.instructions.goal
            boundaries = package.primitives.instructions.boundaries
            tool_ids = [tool.tool_id for tool in package.generated_tools]
            mcp_binding_ids = [binding.id for binding in package.mcp.bindings]
            scenario_ids = [scenario.id for scenario in package.harness.scenarios]
        except PackageLoadError:
            try:
                manifest = self.loader.load_manifest(path)
            except PackageLoadError:
                manifest = None

        return DraftAgentDetail(
            summary=summary,
            manifest=manifest,
            validation_report=validation_report,
            persona=persona,
            goal=goal,
            boundaries=boundaries,
            tool_ids=tool_ids,
            mcp_binding_ids=mcp_binding_ids,
            scenario_ids=scenario_ids,
            next_steps=[
                f"/drafts use {summary.display_id}",
                f"/run --input \"...\"",
                f"/validate {summary.display_id}",
                f"/test {summary.display_id}",
            ],
        )

    def resolve_draft(
        self,
        identifier: str | Path | None,
        *,
        start_path: str | Path | None = None,
    ) -> Path | None:
        if identifier is None or str(identifier).strip() in {"", "latest"}:
            result = self.list_drafts(start_path=start_path)
            return result.drafts[0].path if result.drafts else None

        raw = str(identifier).strip()
        candidate = Path(raw).expanduser()
        if candidate.exists():
            return candidate.resolve()

        result = self.list_drafts(start_path=start_path)
        for draft in result.drafts:
            if raw in {
                draft.id,
                draft.display_id,
                draft.path.name,
                draft.agent_id or "",
                draft.agent_name,
                str(draft.path),
            }:
                return draft.path
        return None

    def delete_draft(
        self,
        identifier: str | Path | None,
        *,
        confirmed: bool = False,
        start_path: str | Path | None = None,
    ) -> DraftDeleteResult | None:
        path = self.resolve_draft(identifier or "latest", start_path=start_path)
        if path is None:
            return None
        context = FactoryRunContext.create(start_path=start_path)
        drafts_path = context.drafts_path.resolve()
        resolved = path.resolve()
        if not _is_relative_to(resolved, drafts_path):
            raise ValueError("Refusing to delete a path outside the Factory drafts directory.")
        if not confirmed:
            return DraftDeleteResult(
                id=resolved.name,
                path=resolved,
                deleted=False,
                message="Deletion requires --yes.",
            )
        shutil.rmtree(resolved)
        return DraftDeleteResult(
            id=resolved.name,
            path=resolved,
            deleted=True,
            message="Draft deleted.",
        )

    def _summarize(self, path: Path) -> DraftAgentSummary:
        manifest: PackageManifest | None = None
        try:
            manifest = self.loader.load_manifest(path)
        except PackageLoadError:
            manifest = None

        report = self.validator.validate_full_package(path)
        verification_status = _verification_status(path)
        return DraftAgentSummary(
            id=path.name,
            path=path,
            agent_id=manifest.agent_id if manifest else None,
            agent_name=manifest.agent_name if manifest else path.name,
            version=manifest.version if manifest else None,
            status=manifest.status if manifest else "invalid",
            description=manifest.description if manifest else None,
            updated_at=datetime.fromtimestamp(_mtime(path), tz=timezone.utc),
            validation_status="passed" if report.ok else "failed",
            verification_status=verification_status,
            tool_count=len(list((path / "generated" / "draft_tools").glob("*.tool.yaml"))),
            harness_scenario_count=_harness_scenario_count(path, self.yaml),
        )


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def _verification_status(path: Path) -> str:
    report_path = path / "generated" / "reports" / "factory_verification.json"
    if not report_path.exists():
        return "missing"
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unreadable"
    return str(data.get("status") or "unknown")


def _harness_scenario_count(path: Path, yaml: YAML) -> int:
    harness_path = path / "harness.yaml"
    if not harness_path.exists():
        return 0
    try:
        data = yaml.load(harness_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return 0
    scenarios = data.get("scenarios")
    return len(scenarios) if isinstance(scenarios, list) else 0


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _short_draft_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return "draft"
    if len(normalized) <= 18:
        return normalized
    parts = [part for part in normalized.split("-") if part]
    if len(parts) >= 2:
        candidate = "-".join(parts[:2])
        suffix = normalized[-6:]
        compact = f"{candidate}-{suffix}"
        if len(compact) <= 24:
            return compact
    return f"{normalized[:12]}-{normalized[-6:]}"
