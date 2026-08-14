from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Iterator

from agent_hub.config import Settings


SCHEMA_VERSION = 8
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
                  return_to text,
                  pkce_verifier_ciphertext text,
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
                  provider_token_ciphertext text,
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

                create table if not exists app_releases (
                  app_release_id text primary key,
                  version text not null unique,
                  tag_name text not null unique,
                  title text not null,
                  notes_markdown text not null,
                  status text not null
                    check (status in ('draft', 'queued', 'publishing', 'published', 'failed', 'withdrawn')),
                  github_release_id integer unique,
                  github_url text,
                  error_code text,
                  error_message text,
                  created_by text not null references users(user_id),
                  published_by text references users(user_id),
                  created_at text not null,
                  published_at text,
                  updated_at text not null
                );

                create index if not exists idx_app_releases_public
                on app_releases(status, published_at);

                create table if not exists app_release_assets (
                  asset_id text primary key,
                  app_release_id text not null
                    references app_releases(app_release_id) on delete cascade,
                  asset_kind text not null
                    check (asset_kind in ('installer', 'updater')),
                  platform text not null
                    check (platform in ('macos', 'windows')),
                  architecture text not null,
                  filename text not null,
                  content_type text not null,
                  object_key text not null unique,
                  expected_size integer not null check (expected_size > 0),
                  actual_size integer,
                  sha256 text,
                  status text not null
                    check (status in ('awaiting_upload', 'uploaded', 'publishing', 'published', 'failed')),
                  progress_bytes integer not null default 0 check (progress_bytes >= 0),
                  github_asset_id integer unique,
                  download_url text,
                  download_count integer not null default 0,
                  updater_signature text,
                  error_code text,
                  error_message text,
                  created_at text not null,
                  updated_at text not null,
                  unique(app_release_id, platform, architecture, asset_kind),
                  unique(app_release_id, filename)
                );

                create index if not exists idx_app_release_assets_release
                on app_release_assets(app_release_id, status);

                create table if not exists app_release_jobs (
                  job_id text primary key,
                  app_release_id text not null
                    references app_releases(app_release_id) on delete cascade,
                  job_type text not null check (job_type in ('publish', 'sync_metadata')),
                  status text not null
                    check (status in ('queued', 'running', 'succeeded', 'failed')),
                  stage text not null,
                  progress_bytes integer not null default 0 check (progress_bytes >= 0),
                  total_bytes integer not null default 0 check (total_bytes >= 0),
                  error_code text,
                  error_message text,
                  claimed_at text,
                  created_by text not null references users(user_id),
                  created_at text not null,
                  updated_at text not null
                );

                create index if not exists idx_app_release_jobs_queue
                on app_release_jobs(status, created_at);

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
            _add_column_if_missing(
                connection,
                table="desktop_auth_flows",
                column="provider_token_ciphertext",
                declaration="text",
            )
            _add_column_if_missing(
                connection,
                table="oauth_states",
                column="return_to",
                declaration="text",
            )
            _add_column_if_missing(
                connection,
                table="oauth_states",
                column="pkce_verifier_ciphertext",
                declaration="text",
            )
            _migrate_app_release_assets_v4(connection)
            _add_column_if_missing(
                connection,
                table="app_release_assets",
                column="download_count",
                declaration="integer not null default 0",
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


def _migrate_app_release_assets_v4(connection: sqlite3.Connection) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute("pragma table_info(app_release_assets)").fetchall()
    }
    if "asset_kind" in columns and "updater_signature" in columns:
        return
    connection.executescript(
        """
        begin immediate;

        alter table app_release_assets rename to app_release_assets_v3;

        create table app_release_assets (
          asset_id text primary key,
          app_release_id text not null
            references app_releases(app_release_id) on delete cascade,
          asset_kind text not null
            check (asset_kind in ('installer', 'updater')),
          platform text not null
            check (platform in ('macos', 'windows')),
          architecture text not null,
          filename text not null,
          content_type text not null,
          object_key text not null unique,
          expected_size integer not null check (expected_size > 0),
          actual_size integer,
          sha256 text,
          status text not null
            check (status in ('awaiting_upload', 'uploaded', 'publishing', 'published', 'failed')),
          progress_bytes integer not null default 0 check (progress_bytes >= 0),
          github_asset_id integer unique,
          download_url text,
          updater_signature text,
          error_code text,
          error_message text,
          created_at text not null,
          updated_at text not null,
          unique(app_release_id, platform, architecture, asset_kind),
          unique(app_release_id, filename)
        );

        insert into app_release_assets(
          asset_id, app_release_id, asset_kind, platform, architecture, filename,
          content_type, object_key, expected_size, actual_size, sha256, status,
          progress_bytes, github_asset_id, download_url, updater_signature,
          error_code, error_message, created_at, updated_at
        )
        select
          asset_id, app_release_id, 'installer', platform, architecture, filename,
          content_type, object_key, expected_size, actual_size, sha256, status,
          progress_bytes, github_asset_id, download_url, null,
          error_code, error_message, created_at, updated_at
        from app_release_assets_v3;

        drop table app_release_assets_v3;

        create index idx_app_release_assets_release
        on app_release_assets(app_release_id, status);

        commit;
        """
    )
