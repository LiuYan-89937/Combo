from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Any

from agent_factory.model_pool.config import model_pool_store_read_only, resolve_model_pool_store_path
from agent_factory.model_pool.schema import (
    ModelPoolCredential,
    ModelPoolProfile,
    provider_default_capabilities,
    utc_now_text,
)
from agent_factory.sqlite_runtime import connect_sqlite, initialize_sqlite_store


class ModelPoolStoreError(RuntimeError):
    pass


class ModelPoolRevisionConflict(ModelPoolStoreError):
    pass


SQLITE_BUSY_TIMEOUT_MS = 10000
MODEL_POOL_SCHEMA_MIGRATIONS = (
    "2026-08-13.remove-model-capability-async-job",
    "2026-08-13.consolidate-provider-protocols",
)
INFRASTRUCTURE_MODEL_ROLE_KINDS = {
    "task": "chat",
    "embedding": "embedding",
    "image_generation": "image_generation",
}
MODEL_ROLE_BINDING_ROLES = (
    "main",
    "task",
    "compression",
    "embedding",
    "image_generation",
)


class ModelPoolStore:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        setup: bool = True,
        read_only: bool | None = None,
    ) -> None:
        self.path = resolve_model_pool_store_path(path)
        self.read_only = model_pool_store_read_only() if read_only is None else read_only
        if self.read_only:
            if not self.path.is_file():
                raise ModelPoolStoreError(f"model pool store is not initialized: {self.path}")
        elif setup:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            initialize_sqlite_store(
                self.path,
                self._ensure_schema,
                timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
                wal=True,
            )
        elif not self.path.is_file():
            raise ModelPoolStoreError(f"model pool store is not initialized: {self.path}")

    def create_credential(self, credential: ModelPoolCredential) -> ModelPoolCredential:
        return self._persist_credential(credential, expected_revision=None)

    def _persist_credential(
        self,
        credential: ModelPoolCredential,
        *,
        expected_revision: int | None,
    ) -> ModelPoolCredential:
        now = utc_now_text()
        with self._connect(write=True) as conn:
            existing = _credential_from_connection(conn, credential.credential_id)
            if expected_revision is None:
                if existing is not None:
                    raise ModelPoolStoreError(
                        f"model pool credential already exists: {credential.credential_id}"
                    )
                tombstone = conn.execute(
                    "select 1 from model_credential_tombstones where credential_id = ?",
                    (credential.credential_id,),
                ).fetchone()
                if tombstone is not None:
                    raise ModelPoolStoreError(
                        f"model credential identity was revoked and cannot be reused: {credential.credential_id}"
                    )
                if credential.revision != 1:
                    raise ModelPoolRevisionConflict("new model credential must start at revision 1")
                next_revision = 1
                created_at = credential.created_at
            else:
                if existing is None:
                    raise ModelPoolStoreError(f"unknown model pool credential: {credential.credential_id}")
                if expected_revision != existing.revision or credential.revision != expected_revision:
                    raise ModelPoolRevisionConflict(
                        f"model credential revision conflict: expected {expected_revision}, current {existing.revision}"
                    )
                next_revision = existing.revision + 1
                created_at = existing.created_at
            if not credential.enabled or not credential.api_key:
                assigned = _assigned_roles_for_credential(conn, credential.credential_id)
                if assigned:
                    role_labels = ", ".join(
                        f"{profile_id} ({'/'.join(roles)})"
                        for profile_id, roles in assigned
                    )
                    raise ModelPoolStoreError(
                        "credential is used by assigned model roles and must remain enabled with an API key: "
                        + role_labels
                    )
            credential = credential.model_copy(
                update={
                    "revision": next_revision,
                    "created_at": created_at,
                    "updated_at": now,
                }
            )
            conn.execute(
                """
                insert into model_credential_revisions(
                  credential_id, revision, payload_json, created_at
                ) values (?, ?, ?, ?)
                """,
                (
                    credential.credential_id,
                    credential.revision,
                    credential.model_dump_json(),
                    now,
                ),
            )
            conn.execute(
                """
                insert into model_credentials (
                  credential_id, provider, display_name, base_url, api_key,
                  enabled, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(credential_id) do update set
                  provider=excluded.provider,
                  display_name=excluded.display_name,
                  base_url=excluded.base_url,
                  api_key=excluded.api_key,
                  enabled=excluded.enabled,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                _credential_row(credential),
            )
        return credential

    def patch_credential(self, credential_id: str, payload: dict[str, Any]) -> ModelPoolCredential:
        existing = self.require_credential(credential_id)
        update = dict(payload)
        expected_revision = _required_expected_revision(update)
        if expected_revision != existing.revision:
            raise ModelPoolRevisionConflict(
                f"model credential revision conflict: expected {expected_revision}, current {existing.revision}"
            )
        update.pop("revision", None)
        if "api_key" not in update:
            update["api_key"] = existing.api_key
        candidate = ModelPoolCredential.model_validate(
            {**existing.model_dump(mode="json"), **update, "revision": expected_revision}
        )
        return self._persist_credential(candidate, expected_revision=expected_revision)

    def get_credential(self, credential_id: str) -> ModelPoolCredential | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from model_credentials where credential_id = ?",
                (credential_id,),
            ).fetchone()
        return ModelPoolCredential.model_validate_json(str(row["payload_json"])) if row else None

    def require_credential(self, credential_id: str) -> ModelPoolCredential:
        credential = self.get_credential(credential_id)
        if credential is None:
            raise ModelPoolStoreError(f"unknown model pool credential: {credential_id}")
        return credential

    def require_credential_revision(
        self,
        credential_id: str,
        revision: int,
    ) -> ModelPoolCredential:
        with self._connect() as conn:
            row = conn.execute(
                """
                select payload_json from model_credential_revisions
                where credential_id = ? and revision = ?
                """,
                (credential_id, revision),
            ).fetchone()
            revoked = conn.execute(
                "select 1 from model_credential_tombstones where credential_id = ?",
                (credential_id,),
            ).fetchone()
        if revoked is not None:
            raise ModelPoolStoreError(f"model credential is revoked: {credential_id}")
        if row is None:
            raise ModelPoolStoreError(
                f"unknown model credential revision: {credential_id}@{revision}"
            )
        return ModelPoolCredential.model_validate_json(str(row["payload_json"]))

    def list_credentials(self) -> list[ModelPoolCredential]:
        with self._connect() as conn:
            rows = conn.execute(
                "select payload_json from model_credentials order by created_at desc, credential_id asc"
            ).fetchall()
        return [ModelPoolCredential.model_validate_json(str(row["payload_json"])) for row in rows]

    def delete_credential(self, credential_id: str) -> bool:
        if self.list_profiles(credential_id=credential_id):
            raise ModelPoolStoreError(f"credential is still used by model profiles: {credential_id}")
        with self._connect(write=True) as conn:
            existing = _credential_from_connection(conn, credential_id)
            if existing is None:
                return False
            conn.execute(
                """
                insert into model_credential_tombstones(
                  credential_id, last_revision, deleted_at
                ) values (?, ?, ?)
                on conflict(credential_id) do nothing
                """,
                (credential_id, existing.revision, utc_now_text()),
            )
            cursor = conn.execute("delete from model_credentials where credential_id = ?", (credential_id,))
        return cursor.rowcount > 0

    def create_profile(self, profile: ModelPoolProfile) -> ModelPoolProfile:
        return self._persist_profile(profile, expected_revision=None)

    def _persist_profile(
        self,
        profile: ModelPoolProfile,
        *,
        expected_revision: int | None,
    ) -> ModelPoolProfile:
        now = utc_now_text()
        capabilities = profile.capabilities
        if profile.kind == "embedding":
            capabilities = provider_default_capabilities(profile.provider, kind="embedding")
        elif (
            profile.kind == "chat"
            and not capabilities.structured_output_methods
        ) or (
            profile.kind == "image_generation"
            and "image" not in capabilities.output_modalities
        ):
            capabilities = provider_default_capabilities(profile.provider, kind=profile.kind)
        with self._connect(write=True) as conn:
            credential = _credential_from_connection(conn, profile.credential_id)
            if credential is None:
                raise ModelPoolStoreError(f"unknown model pool credential: {profile.credential_id}")
            if credential.provider != profile.provider:
                raise ModelPoolStoreError(
                    f"profile provider {profile.provider!r} must match credential provider {credential.provider!r}"
                )
            existing = _profile_from_connection(conn, profile.profile_id)
            if expected_revision is None:
                if existing is not None:
                    raise ModelPoolStoreError(f"model pool profile already exists: {profile.profile_id}")
                tombstone = conn.execute(
                    "select 1 from model_profile_tombstones where profile_id = ?",
                    (profile.profile_id,),
                ).fetchone()
                if tombstone is not None:
                    raise ModelPoolStoreError(
                        f"model profile identity was deleted and cannot be reused: {profile.profile_id}"
                    )
                if profile.revision != 1:
                    raise ModelPoolRevisionConflict("new model profile must start at revision 1")
                next_revision = 1
                created_at = profile.created_at
            else:
                if existing is None:
                    raise ModelPoolStoreError(f"unknown model pool profile: {profile.profile_id}")
                if expected_revision != existing.revision or profile.revision != expected_revision:
                    raise ModelPoolRevisionConflict(
                        f"model profile revision conflict: expected {expected_revision}, current {existing.revision}"
                    )
                next_revision = existing.revision + 1
                created_at = existing.created_at
            if not profile.enabled:
                assigned_roles = _roles_for_profile_connection(conn, profile.profile_id)
                if assigned_roles:
                    raise ModelPoolStoreError(
                        f"model profile is assigned to roles {', '.join(assigned_roles)} and cannot be disabled: "
                        f"{profile.profile_id}"
                    )
            profile = profile.model_copy(
                update={
                    "capabilities": capabilities,
                    "revision": next_revision,
                    "created_at": created_at,
                    "updated_at": now,
                },
                deep=True,
            )
            conn.execute(
                """
                insert into model_profile_revisions(
                  profile_id, revision, credential_id, payload_json, created_at
                ) values (?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    profile.revision,
                    profile.credential_id,
                    profile.model_dump_json(),
                    now,
                ),
            )
            conn.execute(
                """
                insert into model_pool_profiles (
                  profile_id, credential_id, kind, provider, model_name, display_name,
                  enabled, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(profile_id) do update set
                  credential_id=excluded.credential_id,
                  kind=excluded.kind,
                  provider=excluded.provider,
                  model_name=excluded.model_name,
                  display_name=excluded.display_name,
                  enabled=excluded.enabled,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                _profile_row(profile),
            )
        return profile

    def patch_profile(self, profile_id: str, payload: dict[str, Any]) -> ModelPoolProfile:
        existing = self.require_profile(profile_id)
        update = dict(payload)
        expected_revision = _required_expected_revision(update)
        if expected_revision != existing.revision:
            raise ModelPoolRevisionConflict(
                f"model profile revision conflict: expected {expected_revision}, current {existing.revision}"
            )
        update.pop("revision", None)
        candidate = ModelPoolProfile.model_validate(
            {**existing.model_dump(mode="json"), **update, "revision": expected_revision}
        )
        return self._persist_profile(candidate, expected_revision=expected_revision)

    def get_profile(self, profile_id: str) -> ModelPoolProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from model_pool_profiles where profile_id = ?",
                (profile_id,),
            ).fetchone()
        return ModelPoolProfile.model_validate_json(str(row["payload_json"])) if row else None

    def require_profile(self, profile_id: str) -> ModelPoolProfile:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ModelPoolStoreError(f"unknown model pool profile: {profile_id}")
        return profile

    def require_profile_revision(self, profile_id: str, revision: int) -> ModelPoolProfile:
        with self._connect() as conn:
            row = conn.execute(
                """
                select payload_json from model_profile_revisions
                where profile_id = ? and revision = ?
                """,
                (profile_id, revision),
            ).fetchone()
        if row is None:
            raise ModelPoolStoreError(f"unknown model profile revision: {profile_id}@{revision}")
        return ModelPoolProfile.model_validate_json(str(row["payload_json"]))

    def list_profiles(
        self,
        *,
        kind: str | None = None,
        credential_id: str | None = None,
        enabled: bool | None = None,
    ) -> list[ModelPoolProfile]:
        clauses: list[str] = []
        args: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if credential_id:
            clauses.append("credential_id = ?")
            args.append(credential_id)
        if enabled is not None:
            clauses.append("enabled = ?")
            args.append(1 if enabled else 0)
        query = "select payload_json from model_pool_profiles"
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by created_at desc, profile_id asc"
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [ModelPoolProfile.model_validate_json(str(row["payload_json"])) for row in rows]

    def delete_profile(self, profile_id: str) -> bool:
        assigned_roles = self.roles_for_profile(profile_id)
        if assigned_roles:
            raise ModelPoolStoreError(
                f"model profile is assigned to roles {', '.join(assigned_roles)}: {profile_id}"
            )
        with self._connect(write=True) as conn:
            existing = _profile_from_connection(conn, profile_id)
            if existing is None:
                return False
            conn.execute(
                """
                insert into model_profile_tombstones(profile_id, last_revision, deleted_at)
                values (?, ?, ?)
                on conflict(profile_id) do nothing
                """,
                (profile_id, existing.revision, utc_now_text()),
            )
            cursor = conn.execute("delete from model_pool_profiles where profile_id = ?", (profile_id,))
        return cursor.rowcount > 0

    def embedding_binding(self) -> str | None:
        """Return the model used for knowledge-base and memory embeddings."""

        return self.role_binding("embedding")

    def task_model_binding(self) -> str | None:
        """Return the explicitly configured small-task chat model."""

        return self.role_binding("task")

    def image_generation_binding(self) -> str | None:
        """Return the image model exposed to the main Agent through generate_image."""

        return self.role_binding("image_generation")

    def infrastructure_bindings(self) -> dict[str, str | None]:
        """Return infrastructure model bindings as one coherent configuration."""

        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"select role, profile_id from model_role_bindings where role in ({','.join('?' for _ in INFRASTRUCTURE_MODEL_ROLE_KINDS)})",
                    tuple(INFRASTRUCTURE_MODEL_ROLE_KINDS),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            rows = []
        resolved = {str(row["role"]): str(row["profile_id"]) for row in rows}
        return {role: resolved.get(role) for role in INFRASTRUCTURE_MODEL_ROLE_KINDS}

    def role_binding(self, role: str) -> str | None:
        normalized_role = str(role or "").strip()
        if normalized_role not in INFRASTRUCTURE_MODEL_ROLE_KINDS:
            raise ModelPoolStoreError(f"unsupported infrastructure model role: {normalized_role}")

        try:
            with self._connect() as conn:
                row = conn.execute(
                    "select profile_id from model_role_bindings where role = ?",
                    (normalized_role,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            return None
        return str(row["profile_id"]) if row else None

    def save_embedding_binding(self, profile_id: str | None) -> str | None:
        return self.save_role_binding("embedding", profile_id)

    def save_task_model_binding(self, profile_id: str | None) -> str | None:
        return self.save_role_binding("task", profile_id)

    def save_role_binding(self, role: str, profile_id: str | None) -> str | None:
        normalized_role = str(role or "").strip()
        normalized = self._validated_role_binding(normalized_role, profile_id)
        with self._connect(write=True) as conn:
            self._write_role_binding(conn, normalized_role, normalized)
        return self.role_binding(normalized_role)

    def save_infrastructure_bindings(
        self,
        bindings: dict[str, str | None],
    ) -> dict[str, str | None]:
        """Validate and save all infrastructure bindings atomically."""

        unknown = set(bindings) - set(INFRASTRUCTURE_MODEL_ROLE_KINDS)
        if unknown:
            raise ModelPoolStoreError(
                "unsupported infrastructure model roles: " + ", ".join(sorted(unknown))
            )
        current = self.infrastructure_bindings()
        requested = {**current, **bindings}
        validated = {
            role: self._validated_role_binding(role, requested.get(role))
            for role in INFRASTRUCTURE_MODEL_ROLE_KINDS
        }
        with self._connect(write=True) as conn:
            for role, profile_id in validated.items():
                self._write_role_binding(conn, role, profile_id)
        return self.infrastructure_bindings()

    def _validated_role_binding(self, role: str, profile_id: str | None) -> str | None:
        expected_kind = INFRASTRUCTURE_MODEL_ROLE_KINDS.get(role)
        if expected_kind is None:
            raise ModelPoolStoreError(f"unsupported infrastructure model role: {role}")
        normalized = str(profile_id or "").strip() or None
        if normalized is None:
            return None
        profile = self.require_profile(normalized)
        if profile.kind != expected_kind:
            raise ModelPoolStoreError(
                f"{role} binding requires a {expected_kind} model profile: {normalized}"
            )
        if not profile.enabled:
            raise ModelPoolStoreError(f"{role} binding requires an enabled model profile: {normalized}")
        credential = self.require_credential(profile.credential_id)
        if not credential.enabled or not credential.api_key:
            raise ModelPoolStoreError(
                f"{role} binding requires an enabled credential with an API key: {normalized}"
            )
        return normalized

    @staticmethod
    def _write_role_binding(
        conn: sqlite3.Connection,
        role: str,
        profile_id: str | None,
    ) -> None:
        if profile_id is None:
            conn.execute("delete from model_role_bindings where role = ?", (role,))
            return
        conn.execute(
            """
            insert into model_role_bindings (role, profile_id, updated_at)
            values (?, ?, ?)
            on conflict(role) do update set
              profile_id=excluded.profile_id,
              updated_at=excluded.updated_at
            """,
            (role, profile_id, utc_now_text()),
        )

    def roles_for_profile(self, profile_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "select role from model_role_bindings where profile_id = ? order by role",
                (profile_id,),
            ).fetchall()
        return [str(row["role"]) for row in rows]

    def public_profiles(self) -> list[dict[str, Any]]:
        credentials = {credential.credential_id: credential for credential in self.list_credentials()}
        return [
            profile.to_public(credentials.get(profile.credential_id)).model_dump(mode="json")
            for profile in self.list_profiles()
        ]

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if write and self.read_only:
            raise ModelPoolStoreError("model pool store is read-only")
        conn = (
            connect_sqlite(
                f"{self.path.as_uri()}?mode=ro",
                timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
                uri=True,
                query_only=True,
            )
            if self.read_only
            else connect_sqlite(
                self.path,
                timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
                query_only=not write,
            )
        )
        try:
            if write:
                conn.execute("begin immediate")
            yield conn
            if write:
                conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect(write=True) as conn:
            conn.executescript(
                """
                create table if not exists model_credentials (
                  credential_id text primary key,
                  provider text not null,
                  display_name text not null,
                  base_url text not null,
                  api_key text,
                  enabled integer not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_model_credentials_provider on model_credentials(provider);

                create table if not exists model_credential_revisions (
                  credential_id text not null,
                  revision integer not null check (revision >= 1),
                  payload_json text not null,
                  created_at text not null,
                  primary key (credential_id, revision)
                );
                create table if not exists model_credential_tombstones (
                  credential_id text primary key,
                  last_revision integer not null check (last_revision >= 1),
                  deleted_at text not null
                );

                create table if not exists model_pool_profiles (
                  profile_id text primary key,
                  credential_id text not null,
                  kind text not null,
                  provider text not null,
                  model_name text not null,
                  display_name text not null,
                  enabled integer not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_model_pool_profiles_credential on model_pool_profiles(credential_id);
                create index if not exists idx_model_pool_profiles_kind on model_pool_profiles(kind);
                create index if not exists idx_model_pool_profiles_enabled on model_pool_profiles(enabled);

                create table if not exists model_profile_revisions (
                  profile_id text not null,
                  revision integer not null check (revision >= 1),
                  credential_id text not null,
                  payload_json text not null,
                  created_at text not null,
                  primary key (profile_id, revision)
                );
                create index if not exists idx_model_profile_revisions_credential
                  on model_profile_revisions(credential_id);
                create table if not exists model_profile_tombstones (
                  profile_id text primary key,
                  last_revision integer not null check (last_revision >= 1),
                  deleted_at text not null
                );

                create table if not exists model_pool_schema_migrations (
                  migration_id text primary key,
                  applied_at text not null
                );
                """
            )
            self._migrate_role_binding_schema(conn)
            self._backfill_current_revisions(conn)
            self._apply_schema_migrations(conn)

    @staticmethod
    def _apply_schema_migrations(conn: sqlite3.Connection) -> None:
        applied = {
            str(row["migration_id"])
            for row in conn.execute("select migration_id from model_pool_schema_migrations")
        }
        for migration_id in MODEL_POOL_SCHEMA_MIGRATIONS:
            if migration_id in applied:
                continue
            if migration_id == "2026-08-13.remove-model-capability-async-job":
                ModelPoolStore._remove_retired_async_job_capability(conn)
            elif migration_id == "2026-08-13.consolidate-provider-protocols":
                ModelPoolStore._consolidate_provider_protocols(conn)
            else:
                raise RuntimeError(f"unknown model pool schema migration: {migration_id}")
            conn.execute(
                "insert into model_pool_schema_migrations(migration_id, applied_at) values (?, ?)",
                (migration_id, utc_now_text()),
            )

    @staticmethod
    def _remove_retired_async_job_capability(conn: sqlite3.Connection) -> None:
        for table in ("model_pool_profiles", "model_profile_revisions"):
            conn.execute(
                f"""
                update {table}
                   set payload_json = json_remove(payload_json, '$.capabilities.async_job')
                 where json_type(payload_json, '$.capabilities.async_job') is not null
                """
            )

    @staticmethod
    def _consolidate_provider_protocols(conn: sqlite3.Connection) -> None:
        credential_provider_expression = """
            case
              when lower(json_extract(payload_json, '$.base_url')) like '%dashscope.aliyuncs.com%'
                then 'dashscope'
              else case lower(json_extract(payload_json, '$.provider'))
              when 'anthropic' then 'anthropic'
              when 'claude' then 'anthropic'
              when 'qwen' then 'dashscope'
              when 'dashscope' then 'dashscope'
              when 'dashscope_wanx' then 'dashscope'
              when 'wanx' then 'dashscope'
              when 'aliyun_wanx' then 'dashscope'
              else 'openai'
            end
            end
        """
        for table in ("model_credentials", "model_credential_revisions"):
            conn.execute(
                f"update {table} set payload_json = json_set(payload_json, '$.provider', {credential_provider_expression})"
            )
        conn.execute(
            "update model_credentials set provider = json_extract(payload_json, '$.provider')"
        )
        for table in ("model_pool_profiles", "model_profile_revisions"):
            conn.execute(
                f"""
                update {table}
                   set payload_json = json_set(
                     payload_json,
                     '$.provider',
                     coalesce(
                       (select provider from model_credentials
                         where model_credentials.credential_id = {table}.credential_id),
                       case lower(json_extract(payload_json, '$.provider'))
                         when 'anthropic' then 'anthropic'
                         when 'claude' then 'anthropic'
                         when 'qwen' then 'dashscope'
                         when 'dashscope' then 'dashscope'
                         else 'openai'
                       end
                     )
                   )
                """
            )
        conn.execute(
            "update model_pool_profiles set provider = json_extract(payload_json, '$.provider')"
        )

    @staticmethod
    def _migrate_role_binding_schema(conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "select sql from sqlite_master where type = 'table' and name = 'model_role_bindings'"
        ).fetchone()
        schema_sql = str(row["sql"] or "") if row else ""
        expected_role_literals = tuple(f"'{role}'" for role in MODEL_ROLE_BINDING_ROLES)
        if row is not None and all(role in schema_sql for role in expected_role_literals):
            return
        allowed_roles = ", ".join(expected_role_literals)
        if row is None:
            conn.execute(
                f"""
                create table model_role_bindings (
                  role text primary key check (role in ({allowed_roles})),
                  profile_id text not null,
                  updated_at text not null
                )
                """
            )
            conn.execute(
                "create index idx_model_role_bindings_profile on model_role_bindings(profile_id)"
            )
            return
        conn.executescript(
            f"""
            create table model_role_bindings_v2 (
              role text primary key check (role in ({allowed_roles})),
              profile_id text not null,
              updated_at text not null
            );
            insert into model_role_bindings_v2 (role, profile_id, updated_at)
              select role, profile_id, updated_at from model_role_bindings;
            drop table model_role_bindings;
            alter table model_role_bindings_v2 rename to model_role_bindings;
            create index if not exists idx_model_role_bindings_profile on model_role_bindings(profile_id);
            """
        )

    @staticmethod
    def _backfill_current_revisions(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            insert or ignore into model_credential_revisions(
              credential_id, revision, payload_json, created_at
            )
            select credential_id,
                   coalesce(
                     cast(json_extract(payload_json, '$.revision') as integer),
                     1
                   ),
                   payload_json,
                   updated_at
            from model_credentials
            """
        )
        conn.execute(
            """
            insert or ignore into model_profile_revisions(
              profile_id, revision, credential_id, payload_json, created_at
            )
            select profile_id,
                   coalesce(
                     cast(json_extract(payload_json, '$.revision') as integer),
                     1
                   ),
                   credential_id,
                   payload_json,
                   updated_at
            from model_pool_profiles
            """
        )


def _required_expected_revision(payload: dict[str, Any]) -> int:
    raw = payload.pop("expected_revision", None)
    if isinstance(raw, bool):
        raise ModelPoolRevisionConflict("expected_revision must be a positive integer")
    try:
        revision = int(raw)
    except (TypeError, ValueError) as exc:
        raise ModelPoolRevisionConflict("expected_revision is required") from exc
    if revision < 1:
        raise ModelPoolRevisionConflict("expected_revision must be a positive integer")
    return revision


def _credential_from_connection(
    conn: sqlite3.Connection,
    credential_id: str,
) -> ModelPoolCredential | None:
    row = conn.execute(
        "select payload_json from model_credentials where credential_id = ?",
        (credential_id,),
    ).fetchone()
    return ModelPoolCredential.model_validate_json(str(row["payload_json"])) if row else None


def _profile_from_connection(
    conn: sqlite3.Connection,
    profile_id: str,
) -> ModelPoolProfile | None:
    row = conn.execute(
        "select payload_json from model_pool_profiles where profile_id = ?",
        (profile_id,),
    ).fetchone()
    return ModelPoolProfile.model_validate_json(str(row["payload_json"])) if row else None


def _roles_for_profile_connection(conn: sqlite3.Connection, profile_id: str) -> list[str]:
    return [
        str(row["role"])
        for row in conn.execute(
            "select role from model_role_bindings where profile_id = ? order by role",
            (profile_id,),
        ).fetchall()
    ]


def _assigned_roles_for_credential(
    conn: sqlite3.Connection,
    credential_id: str,
) -> list[tuple[str, list[str]]]:
    rows = conn.execute(
        "select profile_id from model_pool_profiles where credential_id = ? order by profile_id",
        (credential_id,),
    ).fetchall()
    assigned: list[tuple[str, list[str]]] = []
    for row in rows:
        profile_id = str(row["profile_id"])
        roles = _roles_for_profile_connection(conn, profile_id)
        if roles:
            assigned.append((profile_id, roles))
    return assigned


def _credential_row(credential: ModelPoolCredential) -> tuple[Any, ...]:
    return (
        credential.credential_id,
        credential.provider,
        credential.display_name,
        credential.base_url,
        credential.api_key,
        1 if credential.enabled else 0,
        credential.model_dump_json(),
        credential.created_at,
        credential.updated_at,
    )


def _profile_row(profile: ModelPoolProfile) -> tuple[Any, ...]:
    return (
        profile.profile_id,
        profile.credential_id,
        profile.kind,
        profile.provider,
        profile.model_name,
        profile.display_name,
        1 if profile.enabled else 0,
        json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
        profile.created_at,
        profile.updated_at,
    )
