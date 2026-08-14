from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jsonschema import Draft202012Validator

from combo.paths import combo_data_path
from combo.resource_system.schema import ResourceDescriptor, ResourceIdentity
from combo.sqlite_runtime import connect_sqlite, initialize_sqlite_store


RESOURCE_MASTER_KEY_ENV = "COMBO_RESOURCE_MASTER_KEY"
RESOURCE_STORE_PATH_ENV = "COMBO_RESOURCE_STORE_PATH"
RESOURCE_STORE_READ_ONLY_ENV = "COMBO_RESOURCE_STORE_READ_ONLY"
SQLITE_BUSY_TIMEOUT_MS = 10000


class ResourceStoreError(RuntimeError):
    pass


class ResourceStore:
    """Encrypted values keyed only by immutable capability resource identities."""

    def __init__(self, path: str | Path | None = None, *, master_key: str | None = None) -> None:
        self.path = Path(path or resource_store_path()).expanduser().resolve()
        self._master_key = master_key if master_key is not None else os.getenv(RESOURCE_MASTER_KEY_ENV, "")
        self.read_only = os.getenv(RESOURCE_STORE_READ_ONLY_ENV, "0") == "1"
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            initialize_sqlite_store(self.path, self._ensure_schema, timeout_ms=SQLITE_BUSY_TIMEOUT_MS, wal=True)

    @property
    def key_available(self) -> bool:
        return bool(self._master_key.strip())

    def status(self, descriptors: list[ResourceDescriptor], *, include_values: bool = False) -> list[dict[str, Any]]:
        existing = self._existing_keys(item.identity for item in descriptors)
        items: list[dict[str, Any]] = []
        for descriptor in descriptors:
            identity = descriptor.identity
            configured = identity.storage_key in existing
            item: dict[str, Any] = {
                "identity": identity.model_dump(mode="json"),
                "description": descriptor.description,
                "required": descriptor.required,
                "configured": configured,
                "secret_fields": list(descriptor.secret_fields),
                "purpose": descriptor.purpose,
                "value_schema": descriptor.value_schema,
                "key_available": self.key_available,
            }
            if include_values:
                item["value"] = self.resolve(descriptor) if configured and self.key_available else None
            items.append(item)
        return items

    def put(self, descriptor: ResourceDescriptor, value: Any) -> dict[str, Any]:
        self._assert_writable()
        errors = sorted(Draft202012Validator(descriptor.value_schema).iter_errors(value), key=lambda item: list(item.path))
        if errors:
            raise ResourceStoreError("resource value validation failed: " + "; ".join(error.message for error in errors))
        identity = descriptor.identity
        nonce = os.urandom(12)
        plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = self._cipher().encrypt(nonce, plaintext, _aad(identity))
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into capability_resources(resource_key, identity_json, nonce_b64, ciphertext_b64, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(resource_key) do update set
                  identity_json=excluded.identity_json,
                  nonce_b64=excluded.nonce_b64,
                  ciphertext_b64=excluded.ciphertext_b64,
                  updated_at=excluded.updated_at
                """,
                (identity.storage_key, identity.model_dump_json(), _b64(nonce), _b64(encrypted), now),
            )
        return {"identity": identity.model_dump(mode="json"), "configured": True, "updated_at": now}

    def delete(self, identity: ResourceIdentity) -> bool:
        self._assert_writable()
        with self._connect() as conn:
            cursor = conn.execute("delete from capability_resources where resource_key = ?", (identity.storage_key,))
        return cursor.rowcount > 0

    def resolve(self, descriptor: ResourceDescriptor) -> Any:
        identity = descriptor.identity
        with self._connect() as conn:
            row = conn.execute(
                "select identity_json, nonce_b64, ciphertext_b64 from capability_resources where resource_key = ?",
                (identity.storage_key,),
            ).fetchone()
        if row is None:
            raise ResourceStoreError(f"resource_required: {identity.resource_id}")
        stored_identity = ResourceIdentity.model_validate_json(str(row["identity_json"]))
        if stored_identity != identity:
            raise ResourceStoreError("stored resource identity does not match requested revision")
        try:
            plaintext = self._cipher().decrypt(
                _unb64(str(row["nonce_b64"])),
                _unb64(str(row["ciphertext_b64"])),
                _aad(identity),
            )
            return json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise ResourceStoreError(f"resource decryption failed: {identity.resource_id}") from exc

    def _existing_keys(self, identities: Iterator[ResourceIdentity]) -> set[str]:
        keys = tuple(item.storage_key for item in identities)
        if not keys:
            return set()
        placeholders = ",".join("?" for _ in keys)
        with self._connect() as conn:
            rows = conn.execute(
                f"select resource_key from capability_resources where resource_key in ({placeholders})",
                keys,
            ).fetchall()
        return {str(row["resource_key"]) for row in rows}

    def _cipher(self) -> AESGCM:
        if not self.key_available:
            raise ResourceStoreError(f"{RESOURCE_MASTER_KEY_ENV} is required for runtime resource values")
        return AESGCM(hashlib.sha256(self._master_key.encode("utf-8")).digest())

    def _assert_writable(self) -> None:
        if self.read_only:
            raise ResourceStoreError("runtime resource store is read-only")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            conn = connect_sqlite(f"{self.path.as_uri()}?mode=ro", timeout_ms=SQLITE_BUSY_TIMEOUT_MS, uri=True, query_only=True)
        else:
            conn = connect_sqlite(self.path, timeout_ms=SQLITE_BUSY_TIMEOUT_MS)
        try:
            yield conn
            if not self.read_only:
                conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists capability_resources (
                  resource_key text primary key,
                  identity_json text not null,
                  nonce_b64 text not null,
                  ciphertext_b64 text not null,
                  updated_at text not null
                )
                """
            )


def resource_store_path() -> Path:
    configured = os.getenv(RESOURCE_STORE_PATH_ENV, "").strip()
    return Path(configured).expanduser() if configured else combo_data_path("resources", "runtime.sqlite")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _aad(identity: ResourceIdentity) -> bytes:
    return identity.model_dump_json().encode("utf-8")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))
