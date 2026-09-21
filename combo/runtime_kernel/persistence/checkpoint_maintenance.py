from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
import logging
from pathlib import Path
import sqlite3
from time import monotonic

from combo.file_lock import exclusive_file_lock


MaintenanceProgress = Callable[[str], None]
_STORAGE_VERSION = 1
# Bound transaction/WAL growth while retiring large legacy snapshot blobs.
_BATCH_BYTES = 16 * 1024 * 1024
_BATCH_ROWS = 128
_PROGRESS_INTERVAL_SECONDS = 1.0
_PROGRESS_SQL_INSTRUCTIONS = 10_000
logger = logging.getLogger(__name__)


# LangGraph checkpoint IDs are monotonically increasing. Pending writes can
# arrive before their checkpoint, so only writes OLDER than the head are retired.
# Keeping this invariant in SQLite makes insertion and retirement one transaction,
# including calls made by other connections to the same database.
_RETENTION_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS combo_checkpoint_ignore_retired
    BEFORE INSERT ON checkpoints
    WHEN EXISTS (
        SELECT 1 FROM checkpoints
        WHERE thread_id = NEW.thread_id AND checkpoint_ns = NEW.checkpoint_ns
          AND checkpoint_id > NEW.checkpoint_id
    )
    BEGIN
        SELECT RAISE(IGNORE);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS combo_checkpoint_retain_latest
    AFTER INSERT ON checkpoints
    BEGIN
        DELETE FROM checkpoints
        WHERE thread_id = NEW.thread_id AND checkpoint_ns = NEW.checkpoint_ns
          AND checkpoint_id < NEW.checkpoint_id;
        DELETE FROM writes
        WHERE thread_id = NEW.thread_id AND checkpoint_ns = NEW.checkpoint_ns
          AND checkpoint_id < NEW.checkpoint_id;
        UPDATE checkpoints SET parent_checkpoint_id = NULL
        WHERE thread_id = NEW.thread_id AND checkpoint_ns = NEW.checkpoint_ns
          AND checkpoint_id = NEW.checkpoint_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS combo_checkpoint_ignore_retired_write
    BEFORE INSERT ON writes
    WHEN EXISTS (
        SELECT 1 FROM checkpoints
        WHERE thread_id = NEW.thread_id AND checkpoint_ns = NEW.checkpoint_ns
          AND checkpoint_id > NEW.checkpoint_id
    )
    BEGIN
        SELECT RAISE(IGNORE);
    END
    """,
)


def prepare_checkpoint_storage(
    connection: sqlite3.Connection,
    *,
    path: Path,
    on_progress: MaintenanceProgress | None = None,
) -> None:
    """Migrate before exposing the saver to runtime workers; never replace its file.

    The version is committed only after physical compaction. Interrupted pruning
    leaves every scope's newest checkpoint intact and resumes on the next start.
    The upstream saver must have initialized its tables before this is called.
    """
    with exclusive_file_lock(path.with_name(f"{path.name}.maintenance.lock")):
        connection.execute(
            """CREATE TABLE IF NOT EXISTS combo_checkpoint_migrations (
                version INTEGER PRIMARY KEY,
                completed_at TEXT NOT NULL
            )"""
        )
        version = connection.execute(
            "SELECT MAX(version) FROM combo_checkpoint_migrations"
        ).fetchone()[0]
        if version is not None and version > _STORAGE_VERSION:
            raise RuntimeError("Checkpoint storage was created by a newer Combo version")
        with _maintenance_progress(connection, on_progress) as report:
            if version is None or version < _STORAGE_VERSION:
                _migrate_latest_only(connection, path=path, report=report)
            else:
                _reclaim_free_pages(connection, report=report)


def _migrate_latest_only(
    connection: sqlite3.Connection, *, path: Path, report: MaintenanceProgress,
) -> None:
    started_at = monotonic()
    original_bytes = path.stat().st_size
    report("checkpoint_cleanup")
    logger.info(
        "Checkpoint storage migration started: version=%s bytes=%s",
        _STORAGE_VERSION, original_bytes,
    )
    _require_full_snapshots(connection)
    # DDL and policy installation succeed together. No runtime writers are
    # started until this preparation returns.
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        for statement in _RETENTION_TRIGGERS:
            connection.execute(statement)
    deleted_checkpoints = _prune_retired_rows(
        connection, table="checkpoints", payload="checkpoint", report=report,
    )
    deleted_writes = _prune_retired_rows(
        connection, table="writes", payload="value", report=report,
    )
    with connection:
        connection.execute(
            "UPDATE checkpoints SET parent_checkpoint_id = NULL "
            "WHERE parent_checkpoint_id IS NOT NULL"
        )
    _truncate_wal(connection)

    report("checkpoint_compaction")
    # DELETE alone leaves the old database allocated. VACUUM rebuilds only live
    # pages, and enables inexpensive incremental reclamation on later starts.
    connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
    connection.execute("VACUUM")
    _truncate_wal(connection)
    with connection:
        connection.execute(
            "INSERT INTO combo_checkpoint_migrations (version, completed_at) "
            "VALUES (?, CURRENT_TIMESTAMP)",
            (_STORAGE_VERSION,),
        )
    _truncate_wal(connection)
    logger.info(
        "Checkpoint storage migration completed: version=%s checkpoints_removed=%s "
        "writes_removed=%s bytes_before=%s bytes_after=%s elapsed_seconds=%.1f",
        _STORAGE_VERSION, deleted_checkpoints, deleted_writes, original_bytes,
        path.stat().st_size, monotonic() - started_at,
    )


def _require_full_snapshots(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """SELECT metadata FROM checkpoints AS snapshot
        WHERE NOT EXISTS (
            SELECT 1 FROM checkpoints AS newer
            WHERE newer.thread_id = snapshot.thread_id
              AND newer.checkpoint_ns = snapshot.checkpoint_ns
              AND newer.checkpoint_id > snapshot.checkpoint_id
        )"""
    )
    try:
        for row in rows:
            metadata = json.loads(row[0]) if row[0] else {}
            if metadata.get("counters_since_delta_snapshot"):
                raise RuntimeError("Cannot prune checkpoint history needed by delta channels")
    finally:
        rows.close()


def _prune_retired_rows(
    connection: sqlite3.Connection,
    *,
    table: str,
    payload: str,
    report: MaintenanceProgress,
) -> int:
    # Table and column names come exclusively from the two internal call sites.
    deleted = 0
    after_rowid: int | None = None
    while True:
        rowid_filter = "" if after_rowid is None else "AND retired.rowid > ?"
        parameters = () if after_rowid is None else (after_rowid,)
        rows = connection.execute(
            f"""SELECT retired.rowid, COALESCE(length(retired.{payload}), 0)
            FROM {table} AS retired
            WHERE EXISTS (
                SELECT 1 FROM checkpoints AS head
                WHERE head.thread_id = retired.thread_id
                  AND head.checkpoint_ns = retired.checkpoint_ns
                  AND head.checkpoint_id > retired.checkpoint_id
            ) {rowid_filter}
            ORDER BY retired.rowid LIMIT ?""",
            (*parameters, _BATCH_ROWS),
        ).fetchall()
        if not rows:
            return deleted
        batch: list[int] = []
        batch_bytes = 0
        for rowid, payload_bytes in rows:
            if batch and batch_bytes + payload_bytes > _BATCH_BYTES:
                deleted += _delete_batch(connection, table=table, rowids=batch)
                report("checkpoint_cleanup")
                batch = []
                batch_bytes = 0
            batch.append(rowid)
            batch_bytes += payload_bytes
        if batch:
            deleted += _delete_batch(connection, table=table, rowids=batch)
            report("checkpoint_cleanup")
        after_rowid = rows[-1][0]


def _delete_batch(connection: sqlite3.Connection, *, table: str, rowids: list[int]) -> int:
    with connection:
        cursor = connection.execute(
            f"DELETE FROM {table} WHERE rowid IN ({','.join('?' for _ in rowids)})",
            rowids,
        )
        count = cursor.rowcount
    _truncate_wal(connection)
    return count


def _truncate_wal(connection: sqlite3.Connection) -> None:
    busy, _, _ = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if busy:
        raise RuntimeError("Checkpoint storage maintenance is blocked by another database connection")


def _reclaim_free_pages(connection: sqlite3.Connection, *, report: MaintenanceProgress) -> None:
    free_pages = connection.execute("PRAGMA freelist_count").fetchone()[0]
    if not free_pages:
        return
    report("checkpoint_compaction")
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    batch_pages = max(1, _BATCH_BYTES // page_size)
    while free_pages:
        # Exhaust the pragma cursor: incremental_vacuum can return once per page.
        connection.execute(f"PRAGMA incremental_vacuum({batch_pages})").fetchall()
        _truncate_wal(connection)
        remaining = connection.execute("PRAGMA freelist_count").fetchone()[0]
        if remaining >= free_pages:
            raise RuntimeError("Checkpoint storage incremental compaction made no progress")
        free_pages = remaining
        report("checkpoint_compaction")


@contextmanager
def _maintenance_progress(
    connection: sqlite3.Connection, on_progress: MaintenanceProgress | None,
) -> Iterator[MaintenanceProgress]:
    phase = "checkpoint_cleanup"
    last_reported = 0.0

    def report(next_phase: str) -> None:
        nonlocal phase, last_reported
        phase = next_phase
        last_reported = monotonic()
        if on_progress is not None:
            on_progress(phase)

    def sql_progress() -> int:
        # Progress comes from executed SQLite instructions, not a heartbeat that
        # could conceal a blocked migration. No SQL is run inside this callback.
        if monotonic() - last_reported >= _PROGRESS_INTERVAL_SECONDS:
            report(phase)
        return 0

    connection.set_progress_handler(sql_progress, _PROGRESS_SQL_INSTRUCTIONS)
    try:
        yield report
    finally:
        connection.set_progress_handler(None, 0)
