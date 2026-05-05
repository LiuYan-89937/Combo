from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.factory_runtime.redaction import redact_secrets
from agent_factory.factory_context.envelope import ArtifactRef


class DecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    decision_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    stage: str
    title: str
    summary: str
    artifact_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def ref(self) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=self.decision_id,
            artifact_type=self.artifact_type,
            summary=self.summary,
            safe_for_prompt=True,
            metadata={"stage": self.stage, "title": self.title, "confirmed": self.confirmed},
        )


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    evidence_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    stage: str
    source: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    safe_for_prompt: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def ref(self) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=self.evidence_id,
            artifact_type="EvidenceReport",
            summary=self.summary,
            safe_for_prompt=self.safe_for_prompt,
            metadata={"stage": self.stage, "source": self.source},
        )


class DecisionLedger(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    records: list[DecisionRecord] = Field(default_factory=list)

    def append(
        self,
        *,
        stage: str,
        title: str,
        summary: str,
        artifact_type: str,
        payload: dict[str, Any] | None = None,
        confirmed: bool = True,
    ) -> DecisionRecord:
        record = DecisionRecord(
            stage=stage,
            title=title,
            summary=summary,
            artifact_type=artifact_type,
            payload=redact_secrets(payload or {}),
            confirmed=confirmed,
        )
        self.records.append(record)
        return record

    def refs(self, *, confirmed_only: bool = True) -> list[ArtifactRef]:
        return [
            record.ref()
            for record in self.records
            if not confirmed_only or record.confirmed
        ]


class EvidenceStore(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    records: list[EvidenceRecord] = Field(default_factory=list)

    def append(
        self,
        *,
        stage: str,
        source: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        safe_for_prompt: bool = True,
    ) -> EvidenceRecord:
        record = EvidenceRecord(
            stage=stage,
            source=source,
            summary=summary,
            payload=redact_secrets(payload or {}),
            safe_for_prompt=safe_for_prompt,
        )
        self.records.append(record)
        return record

    def refs(self, *, safe_only: bool = True) -> list[ArtifactRef]:
        return [
            record.ref()
            for record in self.records
            if not safe_only or record.safe_for_prompt
        ]


ArtifactKind = Literal["decision", "evidence"]

