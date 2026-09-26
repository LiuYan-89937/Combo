from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any
from uuid import uuid4

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.schedule_validation import validate_execution_mode, validate_schedule
from combo.dynamic_runtime.repositories.shared import utc_now_text


# Run states that mean a job still occupies its execution slot. Serial jobs
# refuse to start a new run while any of these is present.
ACTIVE_RUN_STATUSES = ("queued", "running", "waiting_approval", "waiting_external")


class WorkspaceSchedulerStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database
        self._change_listener: Callable[[], None] | None = None

    def bind_change_listener(self, listener: Callable[[], None] | None) -> None:
        self._change_listener = listener

    def jobs(self, workspace_ids: tuple[str, ...]) -> list[dict[str, Any]]:
        if not workspace_ids:
            return []
        placeholders = ",".join("?" for _ in workspace_ids)
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                f"""
                select job.payload_json, job.status, job.next_fire_at, job.last_fire_at,
                       workspace.principal_id
                from scheduler_jobs as job
                join workspaces as workspace on workspace.workspace_id = job.workspace_id
                where job.workspace_id in ({placeholders}) and job.status != 'deleted'
                order by job.updated_at desc
                """,
                workspace_ids,
            ).fetchall()
        return [{
            **json.loads(str(row["payload_json"])),
            "principal_id": str(row["principal_id"]),
            "status": str(row["status"]),
            "next_fire_at": row["next_fire_at"],
            "last_fire_at": row["last_fire_at"],
        } for row in rows]

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_schedule(
            payload.get("schedule_type"),
            payload.get("schedule_expr"),
            payload.get("timezone", "UTC"),
        )
        execution_mode = validate_execution_mode(payload.get("execution_mode"))
        job_id = uuid4().hex
        now = utc_now_text()
        enabled = bool(payload.get("enabled", True))
        status = "enabled" if enabled else "paused"
        job_payload = {key: value for key, value in payload.items() if key != "principal_id"}
        job = {
            **job_payload,
            "execution_mode": execution_mode,
            "enabled": enabled,
            "job_id": job_id,
            "created_at": now,
            "updated_at": now,
        }
        with self._database.transaction() as connection:
            connection.execute(
                "insert into scheduler_jobs(job_id, workspace_id, revision, status, payload_json, created_at, updated_at, next_fire_at, last_fire_at) values (?, ?, 1, ?, ?, ?, ?, null, null)",
                (job_id, str(payload["workspace_id"]), status, json.dumps(job, ensure_ascii=False, sort_keys=True), now, now),
            )
        self._notify_changed()
        return {**job, "status": status, "next_fire_at": None, "last_fire_at": None}

    def require_job(self, job_id: str) -> dict[str, Any]:
        with self._database.connection(query_only=True) as connection:
            row = connection.execute(
                """
                select job.payload_json, job.status, workspace.principal_id
                from scheduler_jobs as job
                join workspaces as workspace on workspace.workspace_id = job.workspace_id
                where job.job_id = ? and job.status != 'deleted'
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"scheduler job not found: {job_id}")
        return {
            **json.loads(str(row["payload_json"])),
            "principal_id": str(row["principal_id"]),
            "status": str(row["status"]),
        }

    def find_job(self, job_id: str) -> dict[str, Any] | None:
        """Like :meth:`require_job` but returns ``None`` for unknown or deleted jobs."""
        try:
            return self.require_job(job_id)
        except LookupError:
            return None

    def create_run(
        self,
        *,
        job_id: str,
        payload: dict[str, Any],
        allow_overlap: bool = True,
    ) -> dict[str, Any]:
        """Create a SchedulerRun for ``job_id``.

        ``allow_overlap=False`` enforces serial execution: when the job still
        owns a non-terminal run, no new run is created and a ``skipped``
        sentinel is returned instead. The check shares the insert's write
        transaction, so concurrent callers cannot both start a run.
        """
        run_id = uuid4().hex
        now = utc_now_text()
        scheduled_fire_at = str(payload.get("scheduled_fire_at") or now)
        run = {
            **payload,
            "run_id": run_id,
            "job_id": job_id,
            "status": "queued",
            "scheduled_at": scheduled_fire_at,
            "started_at": None,
            "completed_at": None,
        }
        with self._database.transaction() as connection:
            if not allow_overlap and self._has_active_run(connection, job_id):
                return {
                    "job_id": job_id,
                    "scheduled_fire_at": scheduled_fire_at,
                    "status": "skipped",
                    "skipped": True,
                    "reason": "previous run has not finished",
                }
            existing = connection.execute(
                "select payload_json, status from scheduler_runs where job_id = ? and json_extract(payload_json, '$.scheduled_fire_at') = ?",
                (job_id, scheduled_fire_at),
            ).fetchone()
            if existing is not None:
                return {
                    **json.loads(str(existing["payload_json"])),
                    "status": str(existing["status"]),
                    "deduplicated": True,
                }
            connection.execute(
                "insert into scheduler_runs values (?, ?, 'queued', null, ?, ?, ?, null)",
                (run_id, job_id, json.dumps(run, ensure_ascii=False, sort_keys=True), now, now),
            )
        return {**run, "deduplicated": False}

    def enabled_jobs(self) -> list[dict[str, Any]]:
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                """
                select job.payload_json, job.status, job.next_fire_at, job.last_fire_at,
                       workspace.principal_id
                from scheduler_jobs as job
                join workspaces as workspace on workspace.workspace_id = job.workspace_id
                where job.status = 'enabled'
                order by job.created_at
                """
            ).fetchall()
        return [
            {
                **json.loads(str(row["payload_json"])),
                "principal_id": str(row["principal_id"]),
                "status": str(row["status"]),
                "next_fire_at": row["next_fire_at"],
                "last_fire_at": row["last_fire_at"],
            }
            for row in rows
        ]

    def set_fire_times(self, job_id: str, *, next_fire_at: str | None, last_fire_at: str | None = None) -> None:
        now = utc_now_text()
        with self._database.transaction() as connection:
            changed = connection.execute(
                """
                update scheduler_jobs
                set next_fire_at = ?, last_fire_at = coalesce(?, last_fire_at), updated_at = ?
                where job_id = ? and status != 'deleted'
                """,
                (next_fire_at, last_fire_at, now, job_id),
            ).rowcount
            if changed != 1:
                raise LookupError(f"scheduler job not found: {job_id}")

    def set_schedule_error(self, job_id: str, error: str | None) -> None:
        now = utc_now_text()
        with self._database.transaction() as connection:
            row = connection.execute(
                "select payload_json from scheduler_jobs where job_id = ? and status != 'deleted'",
                (job_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"scheduler job not found: {job_id}")
            payload = json.loads(str(row["payload_json"]))
            if error:
                payload["schedule_error"] = error
            else:
                payload.pop("schedule_error", None)
            payload["updated_at"] = now
            connection.execute(
                "update scheduler_jobs set payload_json = ?, next_fire_at = null, updated_at = ? where job_id = ?",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), now, job_id),
            )

    def mark_skipped(self, job_id: str, skipped_at: str) -> None:
        """Record that a serial fire was dropped because a run was still active.

        A skipped fire never becomes a run, so the marker lives on the job
        payload instead. This deliberately does not notify the change listener:
        skipping does not alter the schedule.
        """
        now = utc_now_text()
        with self._database.transaction() as connection:
            row = connection.execute(
                "select payload_json from scheduler_jobs where job_id = ? and status != 'deleted'",
                (job_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"scheduler job not found: {job_id}")
            payload = json.loads(str(row["payload_json"]))
            payload["last_skipped_at"] = skipped_at
            payload["updated_at"] = now
            connection.execute(
                "update scheduler_jobs set payload_json = ?, updated_at = ? where job_id = ?",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), now, job_id),
            )

    def update_run(
        self,
        run_id: str,
        *,
        status: str,
        patch: dict[str, Any] | None = None,
        runtime_instance_id: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"queued", "running", "waiting_approval", "waiting_external", "completed", "failed", "cancelled"}:
            raise ValueError(f"unsupported scheduler run status: {status}")
        now = utc_now_text()
        terminal_at = now if status in {"completed", "failed", "cancelled"} else None
        with self._database.transaction() as connection:
            row = connection.execute(
                "select payload_json from scheduler_runs where run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"scheduler run not found: {run_id}")
            current = json.loads(str(row["payload_json"]))
            updated = {
                **current,
                **dict(patch or {}),
                "status": status,
                "started_at": current.get("started_at") or (now if status in {"running", "waiting_approval", "waiting_external"} else None),
                "completed_at": terminal_at,
            }
            connection.execute(
                """
                update scheduler_runs
                set status = ?, runtime_instance_id = coalesce(?, runtime_instance_id),
                    payload_json = ?, updated_at = ?, terminal_at = ?
                where run_id = ?
                """,
                (status, runtime_instance_id, json.dumps(updated, ensure_ascii=False, sort_keys=True), now, terminal_at, run_id),
            )
        return updated

    def append_run_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_text()
        with self._database.transaction() as connection:
            sequence = int(connection.execute(
                "select coalesce(max(sequence), 0) + 1 from scheduler_run_events where run_id = ?",
                (run_id,),
            ).fetchone()[0])
            connection.execute(
                "insert into scheduler_run_events values (?, ?, ?, ?, ?)",
                (run_id, sequence, event_type, json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), now),
            )
        return {"run_id": run_id, "sequence": sequence, "event_type": event_type, "payload": payload, "created_at": now}

    def record_runtime_observation(self, run_id: str, chunk: Any) -> None:
        if not isinstance(chunk, dict):
            return
        chunk_type = str(chunk.get("type") or "").strip()
        payload = chunk.get("payload")
        if not isinstance(payload, dict):
            return
        if chunk_type == "tool_activity":
            raw_events = payload.get("events")
            if not isinstance(raw_events, list):
                return
            for event in raw_events:
                if isinstance(event, dict) and str(event.get("event_type") or "").strip():
                    self.append_run_event(run_id, "tool_activity", event)
            return
        if chunk_type not in {"node_event", "context_event"}:
            return
        event_type = str(payload.get("event_type") or "runtime_activity").strip()
        if event_type in {"approval_required", "question"}:
            return
        body = payload.get("payload")
        event_payload = dict(body) if isinstance(body, dict) else {
            key: value for key, value in payload.items() if key != "event_type"
        }
        self.append_run_event(run_id, event_type, event_payload)
        if event_type in {"tool_started", "model_call_started", "runtime_started"}:
            self.update_run(run_id, status="running")

    def run_events(self, run_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                "select * from scheduler_run_events where run_id = ? and sequence > ? order by sequence",
                (run_id, max(0, after)),
            ).fetchall()
        return [
            {
                "run_id": str(row["run_id"]),
                "sequence": int(row["sequence"]),
                "event_type": str(row["event_type"]),
                "payload": json.loads(str(row["payload_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def runs(self, *, job_id: str | None, limit: int) -> list[dict[str, Any]]:
        query = "select payload_json, status from scheduler_runs"
        parameters: list[Any] = []
        if job_id:
            query += " where job_id = ?"
            parameters.append(job_id)
        query += " order by created_at desc limit ?"
        parameters.append(max(1, limit))
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [{**json.loads(str(row["payload_json"])), "status": str(row["status"])} for row in rows]

    def runs_for_principal(
        self,
        principal_id: str,
        *,
        job_id: str | None,
        workspace_id: str | None = None,
        source_session_id: str | None = None,
        limit: int,
    ) -> list[dict[str, Any]]:
        owned_jobs = self.jobs_for_principal(principal_id)
        if workspace_id is not None:
            owned_jobs = [
                job for job in owned_jobs
                if str(job.get("workspace_id") or "") == workspace_id
            ]
        if source_session_id is not None:
            owned_jobs = [
                job for job in owned_jobs
                if str(job.get("source_session_id") or "") == source_session_id
            ]
        owned_job_ids = {str(job["job_id"]) for job in owned_jobs}
        if job_id is not None and job_id not in owned_job_ids:
            return []
        runs = self.runs(job_id=job_id, limit=limit)
        return [run for run in runs if str(run.get("job_id") or "") in owned_job_ids]

    def jobs_for_principal(self, principal_id: str) -> list[dict[str, Any]]:
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                """
                select job.payload_json, job.status, workspace.principal_id
                from scheduler_jobs as job
                join workspaces as workspace on workspace.workspace_id = job.workspace_id
                where job.status != 'deleted' and workspace.principal_id = ?
                order by job.created_at
                """,
                (principal_id,),
            ).fetchall()
        return [
            {
                **json.loads(str(row["payload_json"])),
                "principal_id": str(row["principal_id"]),
                "status": str(row["status"]),
            }
            for row in rows
        ]

    def require_run(self, run_id: str) -> dict[str, Any]:
        with self._database.connection(query_only=True) as connection:
            row = connection.execute(
                "select payload_json, status, runtime_instance_id from scheduler_runs where run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"scheduler run not found: {run_id}")
        return {
            **json.loads(str(row["payload_json"])),
            "status": str(row["status"]),
            "runtime_instance_id": row["runtime_instance_id"],
        }

    def active_runs(self) -> list[dict[str, Any]]:
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                "select payload_json, status, runtime_instance_id from scheduler_runs where status in ('queued', 'running', 'waiting_approval', 'waiting_external') order by created_at"
            ).fetchall()
        return [{
            **json.loads(str(row["payload_json"])),
            "status": str(row["status"]),
            "runtime_instance_id": row["runtime_instance_id"],
        } for row in rows]

    @staticmethod
    def _has_active_run(connection: Any, job_id: str) -> bool:
        placeholders = ",".join("?" for _ in ACTIVE_RUN_STATUSES)
        row = connection.execute(
            f"select 1 from scheduler_runs where job_id = ? and status in ({placeholders}) limit 1",
            (job_id, *ACTIVE_RUN_STATUSES),
        ).fetchone()
        return row is not None

    def has_active_run(self, job_id: str) -> bool:
        """Whether the job still owns its execution slot."""
        with self._database.connection(query_only=True) as connection:
            return self._has_active_run(connection, job_id)

    def set_status(self, job_id: str, status: str) -> None:
        if status not in {"enabled", "paused", "deleted"}:
            raise ValueError(f"unsupported scheduler status: {status}")
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "update scheduler_jobs set status = ?, revision = revision + 1, updated_at = ? where job_id = ? and status != 'deleted'",
                (status, utc_now_text(), job_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(f"scheduler job not found: {job_id}")
        self._notify_changed()

    def _notify_changed(self) -> None:
        listener = self._change_listener
        if listener is not None:
            listener()
