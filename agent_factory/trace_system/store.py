from __future__ import annotations

import json
import shutil
from pathlib import Path
from threading import RLock
from typing import Any

from agent_factory.trace_system.schema import TraceFactRecord, TraceManifest, TraceReferenceRecord, utc_now


class JSONLTraceStore:
    """Filesystem-backed trace fact store.

    One trace owns one directory. The append-only JSONL files are the durable
    fact source; manifest.json is only a compact index for listing and UI entry.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = RLock()

    def ensure_trace(
        self,
        *,
        trace_id: str,
        run_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        package_id: str | None = None,
        producer_type: str | None = None,
    ) -> TraceManifest:
        with self._lock:
            manifest = self._read_manifest(trace_id)
            if manifest is None:
                manifest = TraceManifest(
                    trace_id=trace_id,
                    run_id=run_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    package_id=package_id,
                    producer_type=producer_type,
                )
            else:
                updates = {
                    "run_id": run_id or manifest.run_id,
                    "agent_id": agent_id or manifest.agent_id,
                    "session_id": session_id or manifest.session_id,
                    "package_id": package_id or manifest.package_id,
                    "producer_type": producer_type or manifest.producer_type,
                    "updated_at": utc_now(),
                }
                if manifest.status == "started":
                    updates["status"] = "running"
                manifest = manifest.model_copy(update=updates)
            self._write_manifest(manifest)
            return manifest

    def append_fact(self, record: TraceFactRecord) -> None:
        with self._lock:
            self._append_jsonl(record.trace_id, "trace.jsonl", record.model_dump(mode="json"))
            self._increment(record.trace_id, record.record_type)

    def append_reference(self, record: TraceReferenceRecord) -> None:
        with self._lock:
            self._append_jsonl(record.trace_id, "refs.jsonl", record.model_dump(mode="json"))
            self._increment(record.trace_id, "reference")

    def finish_trace(self, *, trace_id: str, status: str) -> None:
        with self._lock:
            manifest = self._read_manifest(trace_id)
            if manifest is None:
                return
            final_status = "failed" if status == "failed" else "completed"
            self._write_manifest(
                manifest.model_copy(
                    update={
                        "status": final_status,
                        "finished_at": utc_now(),
                        "updated_at": utc_now(),
                    }
                )
            )

    def delete_trace(self, trace_id: str) -> None:
        with self._lock:
            trace_dir = self._trace_dir(trace_id)
            if trace_dir.exists():
                shutil.rmtree(trace_dir)

    def manifest_for(self, trace_id: str) -> TraceManifest | None:
        with self._lock:
            return self._read_manifest(trace_id)

    def _increment(self, trace_id: str, key: str) -> None:
        manifest = self._read_manifest(trace_id)
        if manifest is None:
            return
        counters = dict(manifest.counters)
        counters[key] = int(counters.get(key, 0)) + 1
        self._write_manifest(
            manifest.model_copy(
                update={
                    "status": "running" if manifest.status == "started" else manifest.status,
                    "updated_at": utc_now(),
                    "counters": counters,
                }
            )
        )

    def _trace_dir(self, trace_id: str) -> Path:
        return self.root / "runs" / trace_id

    def _manifest_path(self, trace_id: str) -> Path:
        return self._trace_dir(trace_id) / "manifest.json"

    def _read_manifest(self, trace_id: str) -> TraceManifest | None:
        path = self._manifest_path(trace_id)
        if not path.is_file():
            return None
        return TraceManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def _write_manifest(self, manifest: TraceManifest) -> None:
        path = self._manifest_path(manifest.trace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _append_jsonl(self, trace_id: str, filename: str, payload: dict[str, Any]) -> None:
        trace_dir = self._trace_dir(trace_id)
        trace_dir.mkdir(parents=True, exist_ok=True)
        with (trace_dir / filename).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
            handle.write("\n")
