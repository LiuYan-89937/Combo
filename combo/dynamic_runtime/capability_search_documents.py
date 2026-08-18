from __future__ import annotations

from collections.abc import Mapping

from combo.dynamic_runtime.capability_search_contracts import CapabilitySearchCandidate
from combo.dynamic_runtime.capability_store import ActiveCapability


def search_candidate_from_active_capability(
    capability: ActiveCapability,
) -> CapabilitySearchCandidate:
    revision = capability.revision
    document = capability.index_revision.document
    return CapabilitySearchCandidate(
        capability_id=revision.capability_id,
        index_revision_id=capability.index_revision.index_revision_id,
        kind=revision.kind,
        search_scope="capability_catalog",
        parent_capability_id=None,
        display_name=document.display_name,
        description=document.description,
        keywords=document.keywords,
        parameter_text=parameter_text_from_definition(revision.content.definition),
    )


def search_candidates_from_active_capabilities(
    capabilities: tuple[ActiveCapability, ...],
) -> tuple[CapabilitySearchCandidate, ...]:
    return tuple(search_candidate_from_active_capability(item) for item in capabilities)


def parameter_text_from_definition(definition: Mapping[str, object]) -> str:
    schema: object = definition.get("input_schema")
    if isinstance(schema, dict) and isinstance(schema.get("canonical_schema"), dict):
        schema = schema["canonical_schema"]
    if not isinstance(schema, dict):
        return ""
    values: list[str] = []

    def visit(node: object, path: str) -> None:
        if not isinstance(node, dict):
            return
        for key in ("title", "description"):
            value = str(node.get(key) or "").strip()
            if value:
                values.append(value)
        enum = node.get("enum")
        if isinstance(enum, list):
            values.extend(str(value) for value in enum if isinstance(value, (str, int, float, bool)))
        properties = node.get("properties")
        if isinstance(properties, dict):
            for name, child in properties.items():
                child_path = f"{path}.{name}" if path else str(name)
                values.append(child_path)
                visit(child, child_path)
        items = node.get("items")
        if isinstance(items, dict):
            visit(items, f"{path}[]" if path else "items")
        for branch_name in ("oneOf", "anyOf", "allOf"):
            branches = node.get(branch_name)
            if isinstance(branches, list):
                for branch in branches:
                    visit(branch, path)

    visit(schema, "")
    return " ".join(dict.fromkeys(value for value in values if value))
