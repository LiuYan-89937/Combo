from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading


SQLiteInitializer = Callable[[], None]


_INITIALIZATION_LOCK = threading.RLock()
_INITIALIZED_DATABASES: dict[Path, tuple[int, int]] = {}


def initialize_sqlite_store(
    path: str | Path,
    initializer: SQLiteInitializer,
    *,
    timeout_ms: int,
    wal: bool,
) -> None:
    resolved = Path(path).expanduser().resolve()
    with _INITIALIZATION_LOCK:
        identity = _database_identity(resolved)
        if identity is not None and _INITIALIZED_DATABASES.get(resolved) == identity:
            return
        if wal:
            _configure_wal(resolved, timeout_ms=timeout_ms)
        initializer()
        initialized_identity = _database_identity(resolved)
        if initialized_identity is not None:
            _INITIALIZED_DATABASES[resolved] = initialized_identity


def connect_sqlite(
    path: str | Path,
    *,
    timeout_ms: int,
    foreign_keys: bool = False,
) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path), timeout=timeout_ms / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"pragma busy_timeout = {timeout_ms}")
    if foreign_keys:
        conn.execute("pragma foreign_keys = on")
    return conn


@contextmanager
def sqlite_session(
    path: str | Path,
    *,
    timeout_ms: int,
    foreign_keys: bool = False,
) -> Iterator[sqlite3.Connection]:
    conn = connect_sqlite(
        path,
        timeout_ms=timeout_ms,
        foreign_keys=foreign_keys,
    )
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _configure_wal(path: Path, *, timeout_ms: int) -> None:
    conn = connect_sqlite(path, timeout_ms=timeout_ms)
    try:
        mode = str(conn.execute("pragma journal_mode = wal").fetchone()[0]).strip().lower()
        if mode != "wal":
            raise RuntimeError(f"failed to enable SQLite WAL mode for {path}: {mode or 'unknown'}")
        conn.commit()
    finally:
        conn.close()


def _database_identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino
