from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
import sqlite3
from typing import Any, ContextManager, Literal, Protocol

from agent_factory.runtime_protocol import RuntimeModelUsage


ModelUsageGroupBy = Literal[
    "model",
    "credential",
    "provider",
    "runtime_role",
    "strategy",
    "workspace",
    "session",
]


class ModelUsageDatabase(Protocol):
    def connection(self, *, query_only: bool = False) -> ContextManager[sqlite3.Connection]: ...


class ModelUsageStore:
    """Read the authoritative model-usage ledger owned by the dynamic runtime database."""

    def __init__(self, database: ModelUsageDatabase) -> None:
        self._database = database

    def summary(
        self,
        *,
        group_by: ModelUsageGroupBy = "model",
        days: int = 14,
        limit: int = 12,
        model_profile_groups: dict[str, str] | None = None,
        group_labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        safe_days = min(max(int(days), 1), 365)
        safe_limit = min(max(int(limit), 1), 24)
        since_day = (datetime.now(UTC) - timedelta(days=safe_days - 1)).date().isoformat()
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select * from runtime_model_usage
                where substr(created_at, 1, 10) >= ?
                order by created_at asc
                """,
                (since_day,),
            ).fetchall()
        records = [dict(row) for row in rows]
        groups = sorted(
            _group_records(
                records,
                group_by=group_by,
                model_profile_groups=model_profile_groups,
                group_labels=group_labels,
            ),
            key=lambda item: int(item["totals"]["total_tokens"]),
            reverse=True,
        )
        visible_keys = {str(item["key"]) for item in groups[:safe_limit]}
        return {
            "group_by": group_by,
            "since": since_day,
            "until": datetime.now(UTC).date().isoformat(),
            "totals": _totals(records),
            "groups": groups,
            "series": _series(
                records,
                group_by=group_by,
                visible_keys=visible_keys,
                model_profile_groups=model_profile_groups,
                group_labels=group_labels,
            ),
        }


def insert_runtime_model_usage(conn: sqlite3.Connection, usage: RuntimeModelUsage) -> None:
    conn.execute(
        """
        insert into runtime_model_usage (
          usage_id, observation_event_id, principal_id, request_id,
          runtime_instance_id, attempt_id, session_id, turn_id, workspace_id,
          task_revision, runtime_role, strategy, node_id, model_operation,
          model_profile_id, model_profile_revision, provider, model_name,
          input_tokens, output_tokens, total_tokens, reasoning_tokens,
          cache_read_tokens, cache_write_tokens, payload_json, created_at
        ) values (
          :usage_id, :observation_event_id, :principal_id, :request_id,
          :runtime_instance_id, :attempt_id, :session_id, :turn_id, :workspace_id,
          :task_revision, :runtime_role, :strategy, :node_id, :model_operation,
          :model_profile_id, :model_profile_revision, :provider, :model_name,
          :input_tokens, :output_tokens, :total_tokens, :reasoning_tokens,
          :cache_read_tokens, :cache_write_tokens, :payload_json, :created_at
        )
        """,
        {
            **usage.model_dump(mode="json"),
            "payload_json": usage.model_dump_json(),
        },
    )


def _group_records(
    records: list[dict[str, Any]],
    *,
    group_by: ModelUsageGroupBy,
    model_profile_groups: dict[str, str] | None,
    group_labels: dict[str, str] | None,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for record in records:
        key = _group_key(record, group_by, model_profile_groups=model_profile_groups)
        group = buckets.setdefault(
            key,
            {
                "key": key,
                "label": (group_labels or {}).get(key, key),
                "provider": str(record.get("provider") or ""),
                "model_name": str(record.get("model_name") or ""),
                "model_profile_id": str(record.get("model_profile_id") or ""),
                "runtime_role": str(record.get("runtime_role") or ""),
                "strategy": str(record.get("strategy") or ""),
                "workspace_id": str(record.get("workspace_id") or ""),
                "session_id": str(record.get("session_id") or ""),
                "totals": _empty_totals(),
            },
        )
        _add_totals(group["totals"], record)
    return list(buckets.values())


def _series(
    records: list[dict[str, Any]],
    *,
    group_by: ModelUsageGroupBy,
    visible_keys: set[str],
    model_profile_groups: dict[str, str] | None,
    group_labels: dict[str, str] | None,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        key = _group_key(record, group_by, model_profile_groups=model_profile_groups)
        day = str(record.get("created_at") or "")[:10]
        if key not in visible_keys or not day:
            continue
        totals = buckets.setdefault(key, {}).setdefault(day, _empty_totals())
        _add_totals(totals, record)
    return [
        {
            "key": key,
            "label": (group_labels or {}).get(key, key),
            "points": [
                {"bucket": day, **totals}
                for day, totals in sorted(points.items())
            ],
        }
        for key, points in buckets.items()
    ]


def _group_key(
    record: dict[str, Any],
    group_by: ModelUsageGroupBy,
    *,
    model_profile_groups: dict[str, str] | None,
) -> str:
    if group_by == "credential":
        profile_id = str(record.get("model_profile_id") or "").strip()
        return (model_profile_groups or {}).get(profile_id, "unknown")
    field = {
        "provider": "provider",
        "runtime_role": "runtime_role",
        "strategy": "strategy",
        "workspace": "workspace_id",
        "session": "session_id",
    }.get(group_by)
    if field is not None:
        return str(record.get(field) or "unknown")
    profile_id = str(record.get("model_profile_id") or "").strip()
    if profile_id:
        return profile_id
    return f"{record.get('provider') or 'unknown'}:{record.get('model_name') or 'unknown'}"


def _totals(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    totals = _empty_totals()
    for record in records:
        _add_totals(totals, record)
    return totals


def _empty_totals() -> dict[str, Any]:
    return {
        "call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cache_hit_ratio": None,
    }


def _add_totals(totals: dict[str, Any], record: dict[str, Any]) -> None:
    totals["call_count"] += 1
    for field in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "reasoning_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    ):
        totals[field] += int(record.get(field) or 0)
    input_tokens = int(totals["input_tokens"])
    totals["cache_hit_ratio"] = (
        round(int(totals["cache_read_tokens"]) / input_tokens, 6)
        if input_tokens
        else None
    )
