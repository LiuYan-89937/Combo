from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillResourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    kind: Literal["reference", "template", "example", "asset"]
    media_type: str = "text/plain"
    size_bytes: int = 0
    readable: bool = True


class SkillScriptRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    script_ref: str
    resolved_path: str
    execution_tool: Literal["bash"] = "bash"
    size_bytes: int = 0


class SkillMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not SKILL_NAME_PATTERN.fullmatch(value):
            raise ValueError("skill name must use lowercase kebab-case")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("skill description must be non-empty")
        if len(text) > 1024:
            raise ValueError("skill description must be at most 1024 characters")
        return text


class SkillPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: SkillMetadata
    root: str
    skill_md_path: str
    body: str
    resources: list[SkillResourceRef] = Field(default_factory=list)
    scripts: list[SkillScriptRef] = Field(default_factory=list)

    @property
    def name(self) -> str:
        return self.metadata.name


class SkillLoadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    metadata: SkillMetadata
    content: str
    resources: list[SkillResourceRef] = Field(default_factory=list)
    scripts: list[SkillScriptRef] = Field(default_factory=list)
