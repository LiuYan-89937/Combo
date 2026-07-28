from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Iterator

from agent_hub.config import Settings


SCHEMA_VERSION = 2
SQLITE_BUSY_TIMEOUT_MS = 10_000


class Database:
    def __init__(self, settings: Settings) -> None:
        self.path = settings.database_path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                create table if not exists schema_migrations (
                  version integer primary key,
                  applied_at text not null
                );

                create table if not exists users (
                  user_id text primary key,
                  github_id integer unique,
                  github_login text not null collate nocase,
                  display_name text,
                  avatar_url text,
                  is_admin integer not null default 0 check (is_admin in (0, 1)),
                  created_at text not null,
                  updated_at text not null
                );

                create unique index if not exists idx_users_github_login
                on users(github_login collate nocase);

                create table if not exists oauth_states (
                  state_hash text primary key,
                  flow_kind text not null default 'browser',
                  desktop_flow_id text,
                  expires_at text not null,
                  created_at text not null
                );

                create table if not exists desktop_auth_flows (
                  flow_id text primary key,
                  poll_secret_hash text not null,
                  status text not null check (status in ('pending', 'authorized')),
                  user_id text references users(user_id) on delete cascade,
                  expires_at text not null,
                  authorized_at text,
                  created_at text not null
                );

                create index if not exists idx_desktop_auth_flows_expiry
                on desktop_auth_flows(expires_at);

                create table if not exists sessions (
                  session_hash text primary key,
                  user_id text not null references users(user_id) on delete cascade,
                  expires_at text not null,
                  created_at text not null
                );

                create index if not exists idx_sessions_user
                on sessions(user_id, expires_at);

                create table if not exists uploads (
                  upload_id text primary key,
                  user_id text not null references users(user_id),
                  filename text not null,
                  object_key text not null unique,
                  expected_size integer not null,
                  actual_size integer,
                  status text not null,
                  error_code text,
                  error_message text,
                  claimed_at text,
                  validation_json text,
                  created_at text not null,
                  updated_at text not null
                );

                create index if not exists idx_uploads_status
                on uploads(status, created_at);

                create table if not exists packages (
                  package_row_id text primary key,
                  publisher_user_id text not null references users(user_id),
                  publisher_login text not null collate nocase,
                  package_id text not null,
                  name text not null,
                  description text not null,
                  created_at text not null,
                  updated_at text not null,
                  unique(publisher_login, package_id)
                );

                create table if not exists releases (
                  release_id text primary key,
                  package_row_id text not null references packages(package_row_id),
                  upload_id text not null unique references uploads(upload_id),
                  version text not null,
                  sha256 text not null,
                  object_key text not null unique,
                  size_bytes integer not null,
                  status text not null,
                  validation_json text not null,
                  changelog text not null default '',
                  download_count integer not null default 0,
                  reviewed_by text references users(user_id),
                  review_message text,
                  created_at text not null,
                  published_at text,
                  updated_at text not null,
                  unique(package_row_id, version)
                );

                create index if not exists idx_releases_public
                on releases(status, published_at);

                create table if not exists audit_log (
                  audit_id integer primary key autoincrement,
                  actor_user_id text references users(user_id),
                  action text not null,
                  target_type text not null,
                  target_id text not null,
                  detail_json text,
                  created_at text not null
                );
                """
            )
            _add_column_if_missing(
                connection,
                table="oauth_states",
                column="flow_kind",
                declaration="text not null default 'browser'",
            )
            _add_column_if_missing(
                connection,
                table="oauth_states",
                column="desktop_flow_id",
                declaration="text",
            )
            connection.execute(
                """
                insert into schema_migrations(version, applied_at)
                values (?, ?)
                on conflict(version) do nothing
                """,
                (SCHEMA_VERSION, utc_now()),
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        connection.execute(f"pragma busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        connection.execute("pragma journal_mode = wal")
        connection.execute("pragma synchronous = normal")
        try:
            yield connection
        finally:
            connection.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def _add_column_if_missing(
    connection: sqlite3.Connection,
    *,
    table: str,
    column: str,
    declaration: str,
) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute(f"pragma table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"alter table {table} add column {column} {declaration}")
