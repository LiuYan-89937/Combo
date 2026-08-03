"""Bounded semantic progress reports for background-task runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import PurePath
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.models.chat_model import get_task_model


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProgressSummaryPolicy:
    """All prompt and call limits live here so runtimes cannot expand them ad hoc."""

    max_task_title_chars: int = 160
    max_evidence_items: int = 6
    max_evidence_text_chars: int = 180
    max_artifact_names: int = 8
    max_reports_per_task: int = 8


class ProgressEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    action: str
    outcome: str
    artifacts: list[str] = Field(default_factory=list)


class ProgressSummaryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1, max_length=160)


class ProgressReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase_id: str
    title: str
    summary: str
    status: str
    artifacts: list[str] = Field(default_factory=list)
    occurred_at: str


class RuntimeEvidenceAdapter(Protocol):
    def select(self, event: FactoryFrontendEvent) -> ProgressEvidence | None: ...

    def is_milestone(self, event: FactoryFrontendEvent) -> bool: ...

    def phase_id(self, event: FactoryFrontendEvent) -> str: ...


class WorkflowEvidenceAdapter:
    """Evidence selector for manufacture and evolution workflow boundaries."""

    def __init__(self, task_type: str, policy: ProgressSummaryPolicy) -> None:
        self.task_type = task_type
        self.policy = policy

    def select(self, event: FactoryFrontendEvent) -> ProgressEvidence | None:
        if event.event_type in {"tool_call_completed", "tool_call_failed", "tool_contract_invalid"}:
            return _tool_evidence(event, self.policy)
        if event.event_type in {"node_completed", "node_failed"}:
            return _node_evidence(event, self.policy)
        return None

    def is_milestone(self, event: FactoryFrontendEvent) -> bool:
        return event.event_type in {"node_completed", "node_failed"}

    def phase_id(self, event: FactoryFrontendEvent) -> str:
        identity = event.node_id or event.stage_id or event.event_id
        return f"{self.task_type}:{identity}"


class SubAgentEvidenceAdapter:
    """Evidence selector for React and plan-and-execute package runtimes."""

    def __init__(self, policy: ProgressSummaryPolicy) -> None:
        self.policy = policy

    def select(self, event: FactoryFrontendEvent) -> ProgressEvidence | None:
        if event.event_type in {"tool_call_completed", "tool_call_failed", "tool_contract_invalid"}:
            return _tool_evidence(event, self.policy)
        if event.event_type in {"node_completed", "node_failed"}:
            return _node_evidence(event, self.policy)
        return None

    def is_milestone(self, event: FactoryFrontendEvent) -> bool:
        return event.event_type in {"node_completed", "node_failed"}

    def phase_id(self, event: FactoryFrontendEvent) -> str:
        identity = event.node_id or event.stage_id or event.event_id
        return f"sub_agent:{identity}"


@dataclass(slots=True)
class ProgressSummarySession:
    task_type: str
    task_title: str
    adapter: RuntimeEvidenceAdapter
    policy: ProgressSummaryPolicy = field(default_factory=ProgressSummaryPolicy)
    _evidence: list[ProgressEvidence] = field(default_factory=list)
    _report_count: int = 0

    def observe(self, event: FactoryFrontendEvent) -> ProgressReport | None:
        evidence = self.adapter.select(event)
        if evidence is not None:
            self._evidence.append(evidence)
            self._evidence = self._evidence[-self.policy.max_evidence_items :]
        if not self.adapter.is_milestone(event) or not self._evidence:
            return None
        return self._summarize(event)

    def flush(self, event: FactoryFrontendEvent) -> ProgressReport | None:
        if not self._evidence:
            return None
        return self._summarize(event)

    def _summarize(self, event: FactoryFrontendEvent) -> ProgressReport | None:
        if self._report_count >= self.policy.max_reports_per_task:
            self._evidence.clear()
            return None
        evidence = list(self._evidence)
        self._evidence.clear()
        request = {
            "task_type": self.task_type,
            "task_title": _bounded(self.task_title, self.policy.max_task_title_chars),
            "recent_work_evidence": [item.model_dump(mode="json") for item in evidence],
        }
        try:
            model = get_task_model()
            if model is None:
                return None
            structured = model.with_structured_output(
                ProgressSummaryDecision,
                method="json_mode",
            ).with_config(tags=["nostream", "background-progress-summary"])
            decision = structured.invoke(
                [
                    SystemMessage(
                        content=(
                            "根据提供的有限工作证据，用中文生成一条简短、客观的阶段报告。"
                            "只说明本阶段实际完成或失败的工作，不推测，不复述任务要求，不输出技术事件名。"
                        )
                    ),
                    HumanMessage(content=json.dumps(request, ensure_ascii=False, separators=(",", ":"))),
                ]
            )
            parsed = (
                decision
                if isinstance(decision, ProgressSummaryDecision)
                else ProgressSummaryDecision.model_validate(decision)
            )
        except Exception as exc:
            LOGGER.info("background progress summary skipped: %s", exc)
            return None
        self._report_count += 1
        artifacts = list(dict.fromkeys(name for item in evidence for name in item.artifacts))
        return ProgressReport(
            phase_id=self.adapter.phase_id(event),
            title=parsed.title,
            summary=parsed.summary,
            status="failed" if event.event_type in {"node_failed", "run_failed"} else "completed",
            artifacts=artifacts[: self.policy.max_artifact_names],
            occurred_at=event.timestamp,
        )


def progress_summary_session(task_type: str, task_title: str) -> ProgressSummarySession:
    policy = ProgressSummaryPolicy()
    adapter: RuntimeEvidenceAdapter = (
        SubAgentEvidenceAdapter(policy)
        if task_type == "sub_agent"
        else WorkflowEvidenceAdapter(task_type, policy)
    )
    return ProgressSummarySession(
        task_type=task_type,
        task_title=task_title,
        adapter=adapter,
        policy=policy,
    )


def _tool_evidence(
    event: FactoryFrontendEvent,
    policy: ProgressSummaryPolicy,
) -> ProgressEvidence | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    tool_name = _bounded(payload.get("tool_name") or payload.get("tool_id"), policy.max_evidence_text_chars)
    if not tool_name:
        return None
    failed = event.event_type == "tool_call_failed"
    return ProgressEvidence(
        source="tool",
        action=tool_name,
        outcome="failed" if failed else "completed",
        artifacts=_artifact_names(payload, policy),
    )


def _node_evidence(
    event: FactoryFrontendEvent,
    policy: ProgressSummaryPolicy,
) -> ProgressEvidence | None:
    label = _bounded(event.node_label or event.node_id, policy.max_evidence_text_chars)
    if not label:
        return None
    payload = event.payload if isinstance(event.payload, dict) else {}
    safe_details: list[str] = []
    for key in ("intent", "graph_kind", "selected_pattern_id", "status", "phase"):
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            safe_details.append(f"{key}={_bounded(value, policy.max_evidence_text_chars)}")
    return ProgressEvidence(
        source="workflow",
        action=label,
        outcome=("failed" if event.event_type == "node_failed" else "completed")
        + (f"; {', '.join(safe_details)}" if safe_details else ""),
        artifacts=_artifact_names(payload, policy),
    )


def _artifact_names(payload: dict[str, Any], policy: ProgressSummaryPolicy) -> list[str]:
    names: list[str] = []
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return names
    for artifact in artifacts[: policy.max_artifact_names]:
        if isinstance(artifact, dict):
            raw = artifact.get("name") or artifact.get("filename") or artifact.get("path")
        else:
            raw = artifact
        text = str(raw or "").strip()
        if text:
            names.append(_bounded(PurePath(text).name, policy.max_evidence_text_chars))
    return list(dict.fromkeys(names))


def _bounded(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]
