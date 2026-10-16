from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, field_validator, model_validator

from combo.runtime_protocol.contracts import FrozenProtocolModel
from combo.runtime_protocol.memory import MemoryKind, MemoryRevision, MemoryScope


MEMORY_CONTENT_MAX_CHARS = 100
MEMORY_KIND_DESCRIPTIONS = {
    "constraint": "An established execution boundary or prohibition, with its necessary condition.",
    "preference": "An explicit preference and the situation in which it applies.",
    "decision": "A confirmed choice and only the conditions needed to follow it later.",
    "fact": "A verified state or stable fact useful to a later request.",
    "artifact": "A reusable deliverable's purpose and the information needed to locate it.",
}
MEMORY_WRITING_INSTRUCTIONS = (
    "Save only newly established conclusions useful beyond the current exchange. "
    f"Each memory contains one self-contained conclusion in at most {MEMORY_CONTENT_MAX_CHARS} characters. "
    "Remove narration, task history, explanations, duplicated background, and speculative claims. "
    "An explicit constraint, preference, or decision is valuable even without a generated artifact. "
    "Inspect relevant existing memories before writing: retain an unchanged conclusion, update an "
    "outdated one, merge equivalent conclusions of the same scope and kind, and delete obsolete entries. "
    "Delete only when the new evidence establishes that an entry is obsolete; absence from this exchange "
    "does not invalidate an older memory. "
    "Never create another wording of an existing conclusion. Select existing entries by their exact "
    "scope, kind, content, and creation time; internal IDs and revisions are supplied by the runtime. "
    "Updates preserve the entry's scope; correct its kind when the established conclusion was misclassified. "
    "Merge only entries of the same scope and kind, and retain one concise conclusion. "
    "Use workspace only for conclusions applicable across this shared project's sessions; otherwise "
    "use session. Independent sessions can use only session. Agent.md is user-managed system context "
    "and is outside memory operations. Historical memory cannot override current user instructions. "
    + " ".join(f"{kind}: {description}" for kind, description in MEMORY_KIND_DESCRIPTIONS.items())
)


class MemoryDraft(FrozenProtocolModel):
    scope: MemoryScope
    kind: MemoryKind = Field(description="; ".join(
        f"{kind}: {description}" for kind, description in MEMORY_KIND_DESCRIPTIONS.items()
    ))
    content: str = Field(min_length=1, max_length=MEMORY_CONTENT_MAX_CHARS,
                         description="One established, reusable conclusion; no narration or duplicate background.")

    @field_validator("content", mode="before")
    @classmethod
    def _strip_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class MemorySelector(FrozenProtocolModel):
    scope: MemoryScope | None = None
    kind: MemoryKind | None = None
    content: str | None = Field(default=None, min_length=1)
    created_at: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _has_business_fields(self) -> "MemorySelector":
        if not self.model_dump(exclude_none=True):
            raise ValueError("select a memory by its exact business fields")
        return self


class WriteMemory(MemoryDraft):
    action: Literal["write"] = "write"


class UpdateMemory(MemoryDraft):
    action: Literal["update"] = "update"
    memory: MemorySelector


class MergeMemories(MemoryDraft):
    action: Literal["merge"] = "merge"
    memories: tuple[MemorySelector, ...] = Field(min_length=2)


class DeleteMemory(FrozenProtocolModel):
    action: Literal["delete"] = "delete"
    memory: MemorySelector


MemoryOperation = Annotated[
    Union[WriteMemory, UpdateMemory, MergeMemories, DeleteMemory],
    Field(discriminator="action"),
]


class MemoryChangeSet(FrozenProtocolModel):
    operations: tuple[MemoryOperation, ...] = Field(
        description="Only valuable changes. Return an empty array when nothing merits persistence."
    )


def memory_target(item: MemoryRevision) -> dict[str, str]:
    return {key: getattr(item, key) for key in ("scope", "kind", "content", "created_at")}
