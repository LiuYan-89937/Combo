from __future__ import annotations

import json
from pathlib import Path

from agent_factory.runtime_kernel.checkpoint.schema import CheckpointRecord
from agent_factory.runtime_kernel.errors import CheckpointError


class FilesystemCheckpointManager:
    def __init__(self, root: str | Path = ".runtime_kernel/checkpoints") -> None:
        self.root = Path(root)

    def save(self, record: CheckpointRecord) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{record.checkpoint_id}.json"
        path.write_text(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, checkpoint_id: str) -> CheckpointRecord:
        path = self.root / f"{checkpoint_id}.json"
        if not path.exists():
            raise CheckpointError(f"Checkpoint not found: {checkpoint_id}")
        return CheckpointRecord.model_validate_json(path.read_text(encoding="utf-8"))
