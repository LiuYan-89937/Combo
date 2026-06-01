from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.tooling.skills.schema import SkillLoadResult, SkillPackage


MAX_RESOURCE_READ_CHARS = 80000


class SkillRegistry:
    def __init__(self, skills: list[SkillPackage] | None = None) -> None:
        self._skills: dict[str, SkillPackage] = {}
        for skill in skills or []:
            self.register(skill)

    def register(self, skill: SkillPackage) -> None:
        if skill.name in self._skills:
            raise ValueError(f"duplicate skill name: {skill.name}")
        self._skills[skill.name] = skill

    def list_metadata(self) -> list[dict[str, Any]]:
        return [
            skill.metadata.model_dump(mode="json")
            for skill in sorted(self._skills.values(), key=lambda item: item.name)
        ]

    def packages(self) -> list[SkillPackage]:
        return sorted(self._skills.values(), key=lambda item: item.name)

    def describe(self, name: str) -> dict[str, Any]:
        skill = self.get(name)
        return {
            "metadata": skill.metadata.model_dump(mode="json"),
            "resources": [item.model_dump(mode="json") for item in skill.resources],
            "scripts": [item.model_dump(mode="json") for item in skill.scripts],
            "loaded_content": False,
        }

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        terms = _query_terms(query)
        if not terms:
            return []
        matches: list[tuple[int, SkillPackage, list[str]]] = []
        for skill in self.packages():
            fields = _search_fields(skill)
            matched_fields = [
                label
                for label, value in fields
                if all(term in value.casefold() for term in terms)
            ]
            if not matched_fields:
                continue
            matches.append((len(matched_fields), skill, matched_fields))
        matches.sort(key=lambda item: (-item[0], item[1].name))
        return [
            {
                **skill.metadata.model_dump(mode="json"),
                "matched_fields": matched_fields,
            }
            for _score, skill, matched_fields in matches[: max(1, limit)]
        ]

    def get(self, name: str) -> SkillPackage:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(f"unknown skill: {name}") from exc

    def load(self, name: str) -> SkillLoadResult:
        skill = self.get(name)
        return SkillLoadResult(
            name=skill.name,
            metadata=skill.metadata,
            content=skill.body,
            resources=skill.resources,
            scripts=skill.scripts,
        )

    def read_resource(self, name: str, path: str) -> dict[str, Any]:
        skill = self.get(name)
        resource = next((item for item in skill.resources if item.path == path), None)
        if resource is None:
            raise KeyError(f"unknown skill resource: {name}/{path}")
        root = Path(skill.root).resolve()
        target = (root / resource.path).resolve()
        _assert_inside(root, target)
        if not target.is_file():
            raise FileNotFoundError(str(target))
        payload: dict[str, Any] = {
            "name": name,
            "path": resource.path,
            "kind": resource.kind,
            "media_type": resource.media_type,
            "size_bytes": resource.size_bytes,
            "readable": resource.readable,
            "truncated": False,
            "content": "",
        }
        if not resource.readable:
            payload["message"] = "Resource is not text-readable; returning metadata only."
            return payload
        content = target.read_text(encoding="utf-8")
        if len(content) > MAX_RESOURCE_READ_CHARS:
            payload["content"] = content[:MAX_RESOURCE_READ_CHARS]
            payload["truncated"] = True
        else:
            payload["content"] = content
        return payload

    def to_resource_payload(self) -> dict[str, Any]:
        return {
            "version": "skill_registry.v0",
            "skills": [
                skill.model_dump(mode="json")
                for skill in sorted(self._skills.values(), key=lambda item: item.name)
            ],
        }

    @classmethod
    def from_resource_payload(cls, payload: dict[str, Any]) -> "SkillRegistry":
        skills = [
            SkillPackage.model_validate(item)
            for item in payload.get("skills", [])
            if isinstance(item, dict)
        ]
        return cls(skills)


def _assert_inside(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Skill resource path escapes skill root: {path}") from exc


def _query_terms(query: str) -> list[str]:
    return [term.casefold() for term in query.strip().split() if term.strip()]


def _search_fields(skill: SkillPackage) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = [
        ("name", skill.name),
        ("description", skill.metadata.description),
    ]
    for key, value in skill.metadata.metadata.items():
        if isinstance(value, str):
            fields.append((f"metadata.{key}", value))
        elif isinstance(value, (int, float, bool)):
            fields.append((f"metadata.{key}", str(value)))
    fields.extend(("resource", item.path) for item in skill.resources)
    fields.extend(("script", item.path) for item in skill.scripts)
    return fields
