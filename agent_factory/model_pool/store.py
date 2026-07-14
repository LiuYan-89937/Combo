from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from pathlib import Path
from typing import Any

from agent_factory.model_pool.config import resolve_model_pool_store_path
from agent_factory.model_pool.schema import LocalModelArtifact, ModelPoolProfile, utc_now_text


class ModelPoolStoreError(RuntimeError):
    pass


class ModelPoolStore:
    def __init__(self, path: str | Path | None = None, *, setup: bool = True) -> None:
        self.path = resolve_model_pool_store_path(path)
        if setup:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()
        elif not self.path.is_file():
            raise ModelPoolStoreError(f"local model registry is not initialized: {self.path}")

    def upsert_artifact(self, artifact: LocalModelArtifact) -> LocalModelArtifact:
        existing = self.get_artifact(artifact.artifact_id)
        artifact = artifact.model_copy(
            update={
                "created_at": existing.created_at if existing else artifact.created_at,
                "updated_at": utc_now_text(),
            }
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into local_model_artifacts (
                  artifact_id, kind, display_name, local_path, enabled,
                  payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(artifact_id) do update set
                  kind=excluded.kind,
                  display_name=excluded.display_name,
                  local_path=excluded.local_path,
                  enabled=excluded.enabled,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    artifact.artifact_id,
                    artifact.kind,
                    artifact.display_name,
                    artifact.local_path,
                    1 if artifact.enabled else 0,
                    artifact.model_dump_json(),
                    artifact.created_at,
                    artifact.updated_at,
                ),
            )
        return artifact

    def patch_artifact(self, artifact_id: str, payload: dict[str, Any]) -> LocalModelArtifact:
        existing = self.require_artifact(artifact_id)
        candidate = LocalModelArtifact.model_validate({**existing.model_dump(mode="json"), **dict(payload)})
        return self.upsert_artifact(candidate)

    def get_artifact(self, artifact_id: str) -> LocalModelArtifact | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from local_model_artifacts where artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return LocalModelArtifact.model_validate_json(str(row["payload_json"])) if row else None

    def require_artifact(self, artifact_id: str) -> LocalModelArtifact:
        artifact = self.get_artifact(artifact_id)
        if artifact is None:
            raise ModelPoolStoreError(f"unknown local model artifact: {artifact_id}")
        return artifact

    def list_artifacts(
        self,
        *,
        kind: str | None = None,
        enabled: bool | None = None,
    ) -> list[LocalModelArtifact]:
        clauses: list[str] = []
        args: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if enabled is not None:
            clauses.append("enabled = ?")
            args.append(1 if enabled else 0)
        query = "select payload_json from local_model_artifacts"
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by updated_at desc, artifact_id asc"
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [LocalModelArtifact.model_validate_json(str(row["payload_json"])) for row in rows]

    def delete_artifact(self, artifact_id: str) -> bool:
        if self.list_profiles(artifact_id=artifact_id):
            raise ModelPoolStoreError(f"artifact is still used by model profiles: {artifact_id}")
        with self._connect() as conn:
            cursor = conn.execute("delete from local_model_artifacts where artifact_id = ?", (artifact_id,))
        return cursor.rowcount > 0

    def upsert_profile(self, profile: ModelPoolProfile) -> ModelPoolProfile:
        artifact = self.require_artifact(profile.artifact_id)
        if artifact.kind != profile.kind:
            raise ModelPoolStoreError(
                f"profile kind {profile.kind!r} must match artifact kind {artifact.kind!r}"
            )
        existing = self.get_profile(profile.profile_id)
        profile = profile.model_copy(
            update={
                "created_at": existing.created_at if existing else profile.created_at,
                "updated_at": utc_now_text(),
            },
            deep=True,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into local_model_profiles (
                  profile_id, artifact_id, kind, engine, served_model_name,
                  display_name, enabled, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(profile_id) do update set
                  artifact_id=excluded.artifact_id,
                  kind=excluded.kind,
                  engine=excluded.engine,
                  served_model_name=excluded.served_model_name,
                  display_name=excluded.display_name,
                  enabled=excluded.enabled,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    profile.profile_id,
                    profile.artifact_id,
                    profile.kind,
                    profile.engine,
                    profile.served_model_name,
                    profile.display_name,
                    1 if profile.enabled else 0,
                    profile.model_dump_json(),
                    profile.created_at,
                    profile.updated_at,
                ),
            )
        return profile

    def patch_profile(self, profile_id: str, payload: dict[str, Any]) -> ModelPoolProfile:
        existing = self.require_profile(profile_id)
        candidate = ModelPoolProfile.model_validate({**existing.model_dump(mode="json"), **dict(payload)})
        return self.upsert_profile(candidate)

    def get_profile(self, profile_id: str) -> ModelPoolProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from local_model_profiles where profile_id = ?",
                (profile_id,),
            ).fetchone()
        return ModelPoolProfile.model_validate_json(str(row["payload_json"])) if row else None

    def require_profile(self, profile_id: str) -> ModelPoolProfile:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ModelPoolStoreError(f"unknown local model profile: {profile_id}")
        return profile

    def list_profiles(
        self,
        *,
        kind: str | None = None,
        artifact_id: str | None = None,
        enabled: bool | None = None,
    ) -> list[ModelPoolProfile]:
        clauses: list[str] = []
        args: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if artifact_id:
            clauses.append("artifact_id = ?")
            args.append(artifact_id)
        if enabled is not None:
            clauses.append("enabled = ?")
            args.append(1 if enabled else 0)
        query = "select payload_json from local_model_profiles"
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by updated_at desc, profile_id asc"
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [ModelPoolProfile.model_validate_json(str(row["payload_json"])) for row in rows]

    def delete_profile(self, profile_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("delete from local_model_profiles where profile_id = ?", (profile_id,))
        return cursor.rowcount > 0

    def public_profiles(self) -> list[dict[str, Any]]:
        artifacts = {artifact.artifact_id: artifact for artifact in self.list_artifacts()}
        return [
            profile.to_public(artifacts.get(profile.artifact_id)).model_dump(mode="json")
            for profile in self.list_profiles()
        ]

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
                create table if not exists local_model_artifacts (
                  artifact_id text primary key,
                  kind text not null,
                  display_name text not null,
                  local_path text not null,
                  enabled integer not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_local_model_artifacts_kind
                  on local_model_artifacts(kind);

                create table if not exists local_model_profiles (
                  profile_id text primary key,
                  artifact_id text not null,
                  kind text not null,
                  engine text not null,
                  served_model_name text not null,
                  display_name text not null,
                  enabled integer not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_local_model_profiles_artifact
                  on local_model_profiles(artifact_id);
                create index if not exists idx_local_model_profiles_kind
                  on local_model_profiles(kind);
                create index if not exists idx_local_model_profiles_enabled
                  on local_model_profiles(enabled);
                """
            )
