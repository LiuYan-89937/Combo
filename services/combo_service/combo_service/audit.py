from __future__ import annotations

import json
import sqlite3
from typing import Any

from combo_service.database import utc_now


def record_audit(
    connection: sqlite3.Connection,
    *,
    actor_user_id: str | None,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        insert into audit_log(
          actor_user_id, action, target_type, target_id, detail_json, created_at
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (
            actor_user_id,
            action,
            target_type,
            target_id,
            json.dumps(detail, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            if detail
            else None,
            utc_now(),
        ),
    )
