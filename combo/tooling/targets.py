from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar


T = TypeVar("T")


class TargetSelectionError(ValueError):
    def __init__(
        self, *, kind: str, code: str,
        selector: Mapping[str, Any], candidates: list[dict[str, Any]],
    ) -> None:
        self.payload = {
            "code": code,
            "kind": kind,
            "selector": dict(selector),
            "candidates": candidates,
        }
        super().__init__(
            f"Select one {kind} by its business fields; available targets are returned in candidates."
        )


def select_target(
    items: Iterable[T],
    *,
    selector: Mapping[str, Any],
    describe: Callable[[T], dict[str, Any]],
    kind: str,
) -> T:
    entries = [(item, describe(item)) for item in items]
    fields = {key: value for key, value in selector.items() if value is not None}
    matches = [
        (item, label) for item, label in entries
        if all(label.get(key) == value for key, value in fields.items())
    ]
    if len(matches) == 1:
        return matches[0][0]
    raise TargetSelectionError(
        kind=kind,
        code="target_ambiguous" if matches else "target_not_found",
        selector=fields,
        candidates=[label for _, label in matches or entries],
    )


def target_schema(fields: Mapping[str, str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            name: {"type": "string", "minLength": 1, "description": description}
            for name, description in fields.items()
        },
        "minProperties": 1,
        "additionalProperties": False,
        "description": "Select the target by its exact business fields; combine fields when names repeat.",
    }
