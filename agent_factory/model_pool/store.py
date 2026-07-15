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


class ModelPoolStoreError(RuntimeError):
    pass


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
            self._ensure_schema()
        elif not self.path.is_file():
            raise ModelPoolStoreError(f"model pool store is not initialized: {self.path}")

    def upsert_credential(self, credential: ModelPoolCredential) -> ModelPoolCredential:
        existing = self.get_credential(credential.credential_id)
        now = utc_now_text()
        credential = credential.model_copy(
            update={
                "created_at": existing.created_at if existing else credential.created_at,
                "updated_at": now,
            }
        )
        with self._connect(write=True) as conn:
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
        if "api_key" not in update:
            update["api_key"] = existing.api_key
        candidate = ModelPoolCredential.model_validate({**existing.model_dump(mode="json"), **update})
        return self.upsert_credential(candidate)

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

    def list_credentials(self) -> list[ModelPoolCredential]:
        with self._connect() as conn:
            rows = conn.execute(
                "select payload_json from model_credentials order by updated_at desc, credential_id asc"
            ).fetchall()
        return [ModelPoolCredential.model_validate_json(str(row["payload_json"])) for row in rows]

    def delete_credential(self, credential_id: str) -> bool:
        if self.list_profiles(credential_id=credential_id):
            raise ModelPoolStoreError(f"credential is still used by model profiles: {credential_id}")
        with self._connect(write=True) as conn:
            cursor = conn.execute("delete from model_credentials where credential_id = ?", (credential_id,))
        return cursor.rowcount > 0

    def upsert_profile(self, profile: ModelPoolProfile) -> ModelPoolProfile:
        credential = self.require_credential(profile.credential_id)
        if credential.provider != profile.provider:
            raise ModelPoolStoreError(
                f"profile provider {profile.provider!r} must match credential provider {credential.provider!r}"
            )
        existing = self.get_profile(profile.profile_id)
        now = utc_now_text()
        capabilities = profile.capabilities
        if (
            profile.kind == "chat"
            and not capabilities.structured_output_methods
        ) or (
            profile.kind == "image_generation"
            and "image" not in capabilities.output_modalities
        ):
            capabilities = provider_default_capabilities(profile.provider, kind=profile.kind)
        profile = profile.model_copy(
            update={
                "capabilities": capabilities,
                "created_at": existing.created_at if existing else profile.created_at,
                "updated_at": now,
            },
            deep=True,
        )
        with self._connect(write=True) as conn:
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
        candidate = ModelPoolProfile.model_validate({**existing.model_dump(mode="json"), **dict(payload)})
        return self.upsert_profile(candidate)

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
        query += " order by updated_at desc, profile_id asc"
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [ModelPoolProfile.model_validate_json(str(row["payload_json"])) for row in rows]

    def delete_profile(self, profile_id: str) -> bool:
        with self._connect(write=True) as conn:
            cursor = conn.execute("delete from model_pool_profiles where profile_id = ?", (profile_id,))
        return cursor.rowcount > 0

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
            sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
            if self.read_only
            else sqlite3.connect(self.path)
        )
        conn.row_factory = sqlite3.Row
        if not write:
            conn.execute("pragma query_only = on")
        try:
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
                """
            )


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
