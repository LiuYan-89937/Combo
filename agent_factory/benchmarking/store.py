from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from pathlib import Path

from agent_factory.benchmarking.schema import BenchmarkRun, utc_now_text
from agent_factory.paths import factory_artifact_path


class BenchmarkStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser().resolve() if path else factory_artifact_path(
            "benchmark", "benchmark.sqlite"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def save(self, run: BenchmarkRun) -> BenchmarkRun:
        updated = run.model_copy(update={"updated_at": utc_now_text()}, deep=True)
        with self._connect() as conn:
            conn.execute(
                """
                insert into benchmark_runs (
                  run_id, status, profile_id, name, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id) do update set
                  status=excluded.status,
                  profile_id=excluded.profile_id,
                  name=excluded.name,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    updated.run_id,
                    updated.status,
                    updated.spec.profile_id,
                    updated.spec.name,
                    updated.model_dump_json(),
                    updated.created_at,
                    updated.updated_at,
                ),
            )
        return updated

    def get(self, run_id: str) -> BenchmarkRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from benchmark_runs where run_id = ?",
                (run_id,),
            ).fetchone()
        return BenchmarkRun.model_validate_json(str(row["payload_json"])) if row else None

    def require(self, run_id: str) -> BenchmarkRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"unknown benchmark run: {run_id}")
        return run

    def list(self, *, limit: int = 100) -> list[BenchmarkRun]:
        normalized_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                "select payload_json from benchmark_runs order by created_at desc limit ?",
                (normalized_limit,),
            ).fetchall()
        return [BenchmarkRun.model_validate_json(str(row["payload_json"])) for row in rows]

    def delete(self, run_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("delete from benchmark_runs where run_id = ?", (run_id,))
        return cursor.rowcount > 0

    def interrupt_incomplete(self) -> int:
        updated_count = 0
        for run in self.list(limit=500):
            if run.status not in {"queued", "running"}:
                continue
            self.save(
                run.model_copy(
                    update={
                        "status": "interrupted",
                        "error": "benchmark process stopped before the run completed",
                        "completed_at": utc_now_text(),
                    },
                    deep=True,
                )
            )
            updated_count += 1
        return updated_count

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists benchmark_runs (
                  run_id text primary key,
                  status text not null,
                  profile_id text not null,
                  name text not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_benchmark_runs_created_at
                  on benchmark_runs(created_at desc);
                create index if not exists idx_benchmark_runs_profile
                  on benchmark_runs(profile_id, created_at desc);
                """
            )
