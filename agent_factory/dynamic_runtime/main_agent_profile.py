from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile


PROFILE_VERSION = "main_agent_capability_profile.v1"


@dataclass(frozen=True, slots=True)
class MainAgentCapabilityProfile:
    revision: int
    capability_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("main Agent capability profile revision must be positive")
        normalized = tuple(dict.fromkeys(_required_text(value) for value in self.capability_ids))
        object.__setattr__(self, "capability_ids", normalized)

    def to_document(self) -> dict[str, object]:
        return {
            "version": PROFILE_VERSION,
            "revision": self.revision,
            "capability_ids": list(self.capability_ids),
        }


class MainAgentCapabilityProfileStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path).expanduser().resolve()

    def read(self) -> MainAgentCapabilityProfile:
        if not self._path.exists():
            return MainAgentCapabilityProfile(revision=1, capability_ids=())
        document = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("version") != PROFILE_VERSION:
            raise ValueError("main Agent capability profile uses an unsupported version")
        values = document.get("capability_ids")
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("main Agent capability profile capability_ids must be an array of strings")
        return MainAgentCapabilityProfile(
            revision=int(document.get("revision") or 0),
            capability_ids=tuple(values),
        )

    def replace(
        self,
        *,
        expected_revision: int,
        capability_ids: tuple[str, ...],
    ) -> MainAgentCapabilityProfile:
        current = self.read()
        if current.revision != expected_revision:
            raise RuntimeError("main_agent_capability_profile_revision_conflict")
        replacement = MainAgentCapabilityProfile(
            revision=current.revision + 1,
            capability_ids=capability_ids,
        )
        self._write(replacement)
        return replacement

    def ensure(self) -> MainAgentCapabilityProfile:
        profile = self.read()
        if not self._path.exists():
            self._write(profile)
        return profile

    def _write(self, profile: MainAgentCapabilityProfile) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="main-agent-profile-",
            dir=self._path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(profile.to_document(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)


def _required_text(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("main Agent capability profile contains an empty capability ID")
    return normalized
