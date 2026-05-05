from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field
from ruamel.yaml import YAML

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime import FactoryRunContext, FactoryWorkspace
from agent_factory.model import ModelService
from agent_factory.package import PackageValidator
from agent_factory.registry import FilesystemRegistry
from agent_factory.runtime import AgentInstanceRuntime, AgentRunRequest, AgentRunResult
from agent_factory.specs import ValidationReport


class RepairPatchSummary(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    path: str
    action: str
    message: str


class RepairAgentRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    target: str
    user_input: str | None = None
    version: str | None = None
    session_id: str = "default"
    original_error: str | None = None
    rerun_after_repair: bool = True


class RepairAgentResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    target: str
    source_package_path: Path | None = None
    candidate_path: Path | None = None
    status: Literal["repaired", "not_needed", "not_repairable", "failed"]
    reason: str | None = None
    original_error: str | None = None
    patches: list[RepairPatchSummary] = Field(default_factory=list)
    validation_report: ValidationReport | None = None
    rerun_result: AgentRunResult | None = None
    next_steps: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "repaired"


class RepairAgentService:
    """Return-to-Factory repair loop for AgentPackage/runtime failures."""

    def __init__(
        self,
        *,
        model_service: ModelService | None = None,
        validator: PackageValidator | None = None,
        registry: FilesystemRegistry | None = None,
    ) -> None:
        self.model_service = model_service
        self.validator = validator or PackageValidator()
        self.registry = registry
        self.yaml = YAML()
        self.yaml.default_flow_style = False

    def repair_agent(self, request: RepairAgentRequest) -> RepairAgentResult:
        package_path = self._resolve_package(request.target, request.version)
        if package_path is None:
            return RepairAgentResult(
                target=request.target,
                status="failed",
                reason=f"AgentPackage or registry record not found: {request.target}",
            )

        original_error = request.original_error
        if request.user_input and original_error is None:
            original_run = self._run_package(package_path, request.user_input, request.session_id)
            if original_run.ok:
                return RepairAgentResult(
                    target=request.target,
                    source_package_path=package_path,
                    status="not_needed",
                    reason="The same input completed successfully; no repair is needed.",
                    rerun_result=original_run,
                    next_steps=[f"/run {package_path} --input \"...\""],
                )
            original_error = original_run.error.message if original_run.error else _last_error(original_run)

        if not _looks_like_context_decode_error(original_error or ""):
            return RepairAgentResult(
                target=request.target,
                source_package_path=package_path,
                status="not_repairable",
                reason="Factory does not have an automatic package-level repair for this error yet.",
                original_error=original_error,
                next_steps=[
                    f"/trace show --path {package_path}",
                    "Inspect the failed runtime trace and decide whether this is a package patch or framework capability gap.",
                ],
            )

        candidate_path = self._candidate_path(package_path)
        shutil.copytree(package_path, candidate_path)
        patches = self._repair_context_binary_refs(candidate_path)
        if not patches:
            return RepairAgentResult(
                target=request.target,
                source_package_path=package_path,
                candidate_path=candidate_path,
                status="not_repairable",
                reason="No repairable binary/tool-only context refs were found in context.yaml.",
                original_error=original_error,
            )

        validation_report = self.validator.validate_full_package(candidate_path)
        if not validation_report.ok:
            return RepairAgentResult(
                target=request.target,
                source_package_path=package_path,
                candidate_path=candidate_path,
                status="failed",
                reason="The repaired candidate did not pass full package validation.",
                original_error=original_error,
                patches=patches,
                validation_report=validation_report,
                next_steps=[f"/validate {candidate_path}"],
            )

        rerun_result = None
        if request.rerun_after_repair and request.user_input:
            rerun_result = self._run_package(candidate_path, request.user_input, request.session_id)
            if not rerun_result.ok:
                return RepairAgentResult(
                    target=request.target,
                    source_package_path=package_path,
                    candidate_path=candidate_path,
                    status="failed",
                    reason="The candidate package was patched and validated, but rerun still failed.",
                    original_error=original_error,
                    patches=patches,
                    validation_report=validation_report,
                    rerun_result=rerun_result,
                    next_steps=[
                        f"/trace show --path {candidate_path}",
                        f"/run {candidate_path} --input \"{request.user_input}\"",
                    ],
                )

        return RepairAgentResult(
            target=request.target,
            source_package_path=package_path,
            candidate_path=candidate_path,
            status="repaired",
            reason="Factory repaired the AgentPackage candidate and self-tested it.",
            original_error=original_error,
            patches=patches,
            validation_report=validation_report,
            rerun_result=rerun_result,
            next_steps=[
                f"/drafts use {candidate_path.name}",
                f"/run {candidate_path} --input \"...\"",
                f"/validate {candidate_path}",
            ],
        )

    def _repair_context_binary_refs(self, package_path: Path) -> list[RepairPatchSummary]:
        context_path = package_path / "context.yaml"
        if not context_path.exists():
            return []
        data = self.yaml.load(context_path.read_text(encoding="utf-8")) or {}
        sources = data.get("sources")
        if not isinstance(sources, list):
            return []

        patches: list[RepairPatchSummary] = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            ref = source.get("ref")
            if not ref:
                continue
            ref_path = _resolve_ref(package_path, str(ref))
            if not _is_probably_binary_or_non_text(ref_path):
                continue
            source["type"] = "fixture"
            source["content"] = json.dumps(
                {
                    "resource_type": "file",
                    "access": "tool_only",
                    "path": str(ref),
                    "note": "Binary or non-text resource; pass as tool context, do not read as model text.",
                },
                ensure_ascii=False,
            )
            source["ref"] = None
            source["visible_to_model"] = False
            source["visible_to_tools"] = True
            hidden = source.get("hidden_from_model") or []
            if isinstance(hidden, list):
                for field in ["api_key", "authorization", "auth_header", "tool_auth_token", "secret"]:
                    if field not in hidden:
                        hidden.append(field)
                source["hidden_from_model"] = hidden
            patches.append(
                RepairPatchSummary(
                    path="context.yaml",
                    action="rewrite_context_resource_ref",
                    message=f"Converted source {source.get('id', '<unknown>')} from file ref to tool-only resource descriptor.",
                )
            )

        if patches:
            with context_path.open("w", encoding="utf-8") as file:
                self.yaml.dump(data, file)
        return patches

    def _run_package(self, package_path: Path, user_input: str, session_id: str) -> AgentRunResult:
        runtime = AgentInstanceRuntime(
            model_service=self.model_service,
            env_file=_factory_env_file(package_path),
        )
        return runtime.run(
            AgentRunRequest(
                package_path=package_path,
                user_input=user_input,
                session_id=session_id,
            )
        )

    def _resolve_package(self, target: str, version: str | None) -> Path | None:
        path = Path(target).expanduser()
        if path.exists():
            return path.resolve()
        drafts_path = FactoryRunContext.create().drafts_path
        if target.strip() in {"", "latest"}:
            drafts = sorted(
                [item for item in drafts_path.iterdir() if item.is_dir()],
                key=_mtime,
                reverse=True,
            ) if drafts_path.exists() else []
            return drafts[0].resolve() if drafts else None
        candidate = drafts_path / target
        if candidate.exists():
            return candidate.resolve()
        record = (self.registry or FilesystemRegistry()).get(target, version)
        return record.package_path if record else None

    @staticmethod
    def _candidate_path(package_path: Path) -> Path:
        suffix = uuid.uuid4().hex[:8]
        return package_path.parent / f"{package_path.name}-repair-{suffix}"


def _looks_like_context_decode_error(message: str) -> bool:
    lowered = message.lower()
    return "utf-8" in lowered and "decode" in lowered


def _resolve_ref(package_path: Path, ref: str) -> Path:
    path = Path(ref).expanduser()
    if path.is_absolute():
        return path
    return package_path / path


def _is_probably_binary_or_non_text(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return True
    except OSError:
        return False
    suffix = path.suffix.lower()
    return suffix in {".sqlite", ".sqlite3", ".db", ".duckdb"}


def _factory_env_file(package_path: Path) -> Path:
    workspace = FactoryWorkspace.discover(package_path)
    return workspace.project_root / ".env"


def _last_error(result: AgentRunResult) -> str | None:
    for event in reversed(result.events):
        if event.status == "failed" and event.message:
            return event.message
    return None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
