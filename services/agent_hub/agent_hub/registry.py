from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any
from uuid import uuid4

from agent_hub.config import Settings
from agent_hub.database import Database, utc_now
from agent_hub.oss_store import ObjectStore
from agent_hub.package_inspector import PackageInspectionError, inspect_package_archive


UPLOAD_FILENAME_PATTERN = re.compile(r"^[^/\\\x00]{1,200}\.zip$", re.IGNORECASE)
UPLOAD_STATUSES = frozenset(
    {
        "awaiting_upload",
        "queued",
        "validating",
        "pending_review",
        "rejected",
        "published",
        "failed",
    }
)


class RegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AgentHubRegistry:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        object_store: ObjectStore,
    ) -> None:
        self.settings = settings
        self.database = database
        self.object_store = object_store

    def create_upload(
        self,
        *,
        user: dict[str, Any],
        filename: str,
        expected_size: int,
    ) -> dict[str, Any]:
        filename = str(filename or "").strip()
        if not UPLOAD_FILENAME_PATTERN.fullmatch(filename):
            raise RegistryError("filename_invalid", "filename must be a safe .zip name")
        if expected_size <= 0 or expected_size > self.settings.max_package_bytes:
            raise RegistryError(
                "package_size_invalid",
                f"package size must be between 1 and {self.settings.max_package_bytes} bytes",
            )
        upload_id = uuid4().hex
        object_key = self.object_store.incoming_key(upload_id)
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                insert into uploads(
                  upload_id, user_id, filename, object_key, expected_size,
                  status, created_at, updated_at
                ) values (?, ?, ?, ?, ?, 'awaiting_upload', ?, ?)
                """,
                (
                    upload_id,
                    str(user["user_id"]),
                    filename,
                    object_key,
                    expected_size,
                    now,
                    now,
                ),
            )
            _audit(
                connection,
                actor_user_id=str(user["user_id"]),
                action="upload.created",
                target_type="upload",
                target_id=upload_id,
                detail={"filename": filename, "expected_size": expected_size},
            )
        return {
            "upload": self.upload(upload_id, user=user),
            "upload_request": self.object_store.create_upload_url(object_key),
        }

    def complete_upload(
        self,
        upload_id: str,
        *,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        row = self._owned_upload(upload_id, user=user)
        if row["status"] != "awaiting_upload":
            raise RegistryError(
                "upload_state_invalid",
                f"upload cannot be completed from status {row['status']}",
            )
        try:
            actual_size = self.object_store.object_size(str(row["object_key"]))
        except FileNotFoundError as exc:
            raise RegistryError(
                "upload_object_missing",
                "uploaded OSS object was not found",
            ) from exc
        expected_size = int(row["expected_size"])
        if actual_size != expected_size:
            self.object_store.delete(str(row["object_key"]))
            self._fail_upload(
                upload_id,
                code="upload_size_mismatch",
                message=f"expected {expected_size} bytes, received {actual_size}",
                status="failed",
            )
            raise RegistryError(
                "upload_size_mismatch",
                f"expected {expected_size} bytes, received {actual_size}",
            )
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            result = connection.execute(
                """
                update uploads
                set actual_size = ?, status = 'queued', updated_at = ?
                where upload_id = ? and status = 'awaiting_upload'
                """,
                (actual_size, now, upload_id),
            )
            if result.rowcount != 1:
                connection.rollback()
                raise RegistryError("upload_state_changed", "upload state changed")
            _audit(
                connection,
                actor_user_id=str(user["user_id"]),
                action="upload.completed",
                target_type="upload",
                target_id=upload_id,
                detail={"actual_size": actual_size},
            )
            connection.commit()
        return self.upload(upload_id, user=user)

    def upload(self, upload_id: str, *, user: dict[str, Any]) -> dict[str, Any]:
        return _upload_view(self._owned_upload(upload_id, user=user))

    def list_uploads(
        self,
        *,
        user: dict[str, Any],
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(100, int(limit)))
        with self.database.connect() as connection:
            if bool(user.get("is_admin")):
                rows = connection.execute(
                    "select * from uploads order by created_at desc limit ?",
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    select * from uploads
                    where user_id = ?
                    order by created_at desc
                    limit ?
                    """,
                    (str(user["user_id"]), limit),
                ).fetchall()
        return [_upload_view(row) for row in rows]

    def claim_validation_job(self) -> dict[str, Any] | None:
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            row = connection.execute(
                """
                select *
                from uploads
                where status = 'queued'
                order by created_at asc
                limit 1
                """
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            result = connection.execute(
                """
                update uploads
                set status = 'validating', claimed_at = ?, updated_at = ?
                where upload_id = ? and status = 'queued'
                """,
                (now, now, row["upload_id"]),
            )
            if result.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
        return dict(row)

    def validate_claimed_upload(self, upload_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "select * from uploads where upload_id = ? and status = 'validating'",
                (upload_id,),
            ).fetchone()
        if row is None:
            raise RegistryError(
                "validation_job_missing",
                "claimed validation upload was not found",
            )
        try:
            with tempfile.TemporaryDirectory(prefix="fastagenthub-validation-") as temp_dir:
                archive_path = Path(temp_dir) / "package.zip"
                self.object_store.download_to(str(row["object_key"]), archive_path)
                inspection = inspect_package_archive(archive_path, self.settings)
            return self._record_validated_release(dict(row), inspection.to_dict())
        except PackageInspectionError as exc:
            self._fail_upload(
                upload_id,
                code=exc.code,
                message=str(exc),
                status="rejected",
            )
            self.object_store.delete(str(row["object_key"]))
            return {
                "upload_id": upload_id,
                "status": "rejected",
                "error_code": exc.code,
                "error_message": str(exc),
            }
        except RegistryError as exc:
            return {
                "upload_id": upload_id,
                "status": "rejected",
                "error_code": exc.code,
                "error_message": str(exc),
            }
        except Exception as exc:
            self._fail_upload(
                upload_id,
                code="validation_internal_error",
                message=f"{type(exc).__name__}: {exc}",
                status="failed",
            )
            return {
                "upload_id": upload_id,
                "status": "failed",
                "error_code": "validation_internal_error",
                "error_message": f"{type(exc).__name__}: {exc}",
            }

    def recover_stale_validation_jobs(self, *, stale_after_seconds: int = 900) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - stale_after_seconds
        recovered = 0
        with self.database.connect() as connection:
            rows = connection.execute(
                "select upload_id, claimed_at from uploads where status = 'validating'"
            ).fetchall()
            for row in rows:
                claimed_at = str(row["claimed_at"] or "")
                try:
                    claimed_timestamp = datetime.fromisoformat(claimed_at).timestamp()
                except ValueError:
                    claimed_timestamp = 0
                if claimed_timestamp >= cutoff:
                    continue
                connection.execute(
                    """
                    update uploads
                    set status = 'queued', claimed_at = null, updated_at = ?
                    where upload_id = ? and status = 'validating'
                    """,
                    (utc_now(), row["upload_id"]),
                )
                recovered += 1
        return recovered

    def approve_release(
        self,
        release_id: str,
        *,
        admin: dict[str, Any],
        review_message: str = "",
    ) -> dict[str, Any]:
        release = self._release(release_id)
        if release["status"] != "pending_review":
            raise RegistryError(
                "release_state_invalid",
                f"release cannot be approved from status {release['status']}",
            )
        target_key = self.object_store.release_key(
            publisher=str(release["publisher_login"]),
            package_id=str(release["package_id"]),
            version=str(release["version"]),
            digest=str(release["sha256"]),
        )
        self.object_store.promote(str(release["object_key"]), target_key)
        now = utc_now()
        try:
            with self.database.connect() as connection:
                connection.execute("begin immediate")
                result = connection.execute(
                    """
                    update releases
                    set status = 'published', object_key = ?, reviewed_by = ?,
                        review_message = ?, published_at = ?, updated_at = ?
                    where release_id = ? and status = 'pending_review'
                    """,
                    (
                        target_key,
                        str(admin["user_id"]),
                        str(review_message or "")[:2_000],
                        now,
                        now,
                        release_id,
                    ),
                )
                if result.rowcount != 1:
                    connection.rollback()
                    raise RegistryError("release_state_changed", "release state changed")
                connection.execute(
                    """
                    update uploads
                    set status = 'published', updated_at = ?
                    where upload_id = ?
                    """,
                    (now, release["upload_id"]),
                )
                _audit(
                    connection,
                    actor_user_id=str(admin["user_id"]),
                    action="release.approved",
                    target_type="release",
                    target_id=release_id,
                    detail={"object_key": target_key},
                )
                connection.commit()
        except Exception:
            self.object_store.delete(target_key)
            raise
        self.object_store.delete(str(release["object_key"]))
        return self.release_detail(release_id, include_unpublished=True)

    def reject_release(
        self,
        release_id: str,
        *,
        admin: dict[str, Any],
        review_message: str,
    ) -> dict[str, Any]:
        message = str(review_message or "").strip()
        if not message:
            raise RegistryError("review_message_required", "rejection reason is required")
        release = self._release(release_id)
        if release["status"] != "pending_review":
            raise RegistryError(
                "release_state_invalid",
                f"release cannot be rejected from status {release['status']}",
            )
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            connection.execute(
                """
                update uploads
                set status = 'rejected', error_code = 'review_rejected',
                    error_message = ?, updated_at = ?
                where upload_id = ?
                """,
                (message[:2_000], now, release["upload_id"]),
            )
            connection.execute(
                "delete from releases where release_id = ? and status = 'pending_review'",
                (release_id,),
            )
            _audit(
                connection,
                actor_user_id=str(admin["user_id"]),
                action="release.rejected",
                target_type="release",
                target_id=release_id,
                detail={"reason": message[:2_000]},
            )
            connection.commit()
        self.object_store.delete(str(release["object_key"]))
        return {"release_id": release_id, "status": "rejected", "message": message}

    def unpublish_release(
        self,
        release_id: str,
        *,
        admin: dict[str, Any],
        review_message: str,
    ) -> dict[str, Any]:
        release = self._release(release_id)
        if release["status"] != "published":
            raise RegistryError(
                "release_state_invalid",
                f"release cannot be unpublished from status {release['status']}",
            )
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            connection.execute(
                """
                update releases
                set status = 'withdrawn', reviewed_by = ?, review_message = ?,
                    updated_at = ?
                where release_id = ? and status = 'published'
                """,
                (
                    str(admin["user_id"]),
                    str(review_message or "")[:2_000],
                    now,
                    release_id,
                ),
            )
            _audit(
                connection,
                actor_user_id=str(admin["user_id"]),
                action="release.unpublished",
                target_type="release",
                target_id=release_id,
                detail={"reason": str(review_message or "")[:2_000]},
            )
            connection.commit()
        return self.release_detail(release_id, include_unpublished=True)

    def list_packages(
        self,
        *,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit = max(1, min(100, int(limit)))
        offset = max(0, int(offset))
        query = str(query or "").strip()
        where = "where releases.status = 'published'"
        arguments: list[Any] = []
        if query:
            where += (
                " and (packages.package_id like ? escape '\\'"
                " or packages.name like ? escape '\\'"
                " or packages.description like ? escape '\\'"
                " or packages.publisher_login like ? escape '\\')"
            )
            pattern = f"%{_escape_like(query)}%"
            arguments.extend([pattern, pattern, pattern, pattern])
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                select packages.*, releases.*
                from packages
                join releases on releases.package_row_id = packages.package_row_id
                {where}
                order by releases.published_at desc
                """,
                tuple(arguments),
            ).fetchall()
        latest_by_package: dict[str, sqlite3.Row] = {}
        for row in rows:
            key = str(row["package_row_id"])
            current = latest_by_package.get(key)
            if current is None or _semver_key(str(row["version"])) > _semver_key(
                str(current["version"])
            ):
                latest_by_package[key] = row
        ordered = sorted(
            latest_by_package.values(),
            key=lambda item: str(item["published_at"] or ""),
            reverse=True,
        )
        total = len(ordered)
        selected = ordered[offset : offset + limit]
        return {
            "items": [_public_release_view(row) for row in selected],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def package_detail(self, publisher: str, package_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                select packages.*, releases.*
                from packages
                join releases on releases.package_row_id = packages.package_row_id
                where packages.publisher_login = ? collate nocase
                  and packages.package_id = ?
                  and releases.status = 'published'
                """,
                (publisher, package_id),
            ).fetchall()
        if not rows:
            raise RegistryError("package_not_found", "published package was not found")
        versions = sorted(
            (_public_release_view(row) for row in rows),
            key=lambda item: _semver_key(str(item["version"])),
            reverse=True,
        )
        return {
            "publisher": str(rows[0]["publisher_login"]),
            "package_id": str(rows[0]["package_id"]),
            "name": str(rows[0]["name"]),
            "description": str(rows[0]["description"]),
            "latest": versions[0],
            "versions": versions,
        }

    def release_detail(
        self,
        release_id: str,
        *,
        include_unpublished: bool = False,
    ) -> dict[str, Any]:
        release = self._release(release_id)
        if not include_unpublished and release["status"] != "published":
            raise RegistryError("release_not_found", "published release was not found")
        return _release_view(release)

    def download_url(self, release_id: str) -> str:
        release = self._release(release_id)
        if release["status"] != "published":
            raise RegistryError("release_not_found", "published release was not found")
        with self.database.connect() as connection:
            connection.execute(
                """
                update releases
                set download_count = download_count + 1, updated_at = ?
                where release_id = ? and status = 'published'
                """,
                (utc_now(), release_id),
            )
        return self.object_store.signed_download_url(str(release["object_key"]))

    def pending_releases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                select packages.*, releases.*
                from releases
                join packages on packages.package_row_id = releases.package_row_id
                where releases.status = 'pending_review'
                order by releases.created_at asc
                limit ?
                """,
                (max(1, min(200, int(limit))),),
            ).fetchall()
        return [_release_view(row) for row in rows]

    def published_releases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                select packages.*, releases.*
                from releases
                join packages on packages.package_row_id = releases.package_row_id
                where releases.status = 'published'
                order by releases.published_at desc
                limit ?
                """,
                (max(1, min(200, int(limit))),),
            ).fetchall()
        return [_release_view(row) for row in rows]

    def _record_validated_release(
        self,
        upload: dict[str, Any],
        inspection: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        release_id = uuid4().hex
        package_row_id = uuid4().hex
        validation_json = _json_dumps(inspection)
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            user = connection.execute(
                "select * from users where user_id = ?",
                (upload["user_id"],),
            ).fetchone()
            if user is None:
                connection.rollback()
                raise RegistryError("upload_user_missing", "upload owner no longer exists")
            publisher_login = str(user["github_login"])
            existing_package = connection.execute(
                """
                select package_row_id
                from packages
                where publisher_login = ? collate nocase and package_id = ?
                """,
                (publisher_login, inspection["package_id"]),
            ).fetchone()
            if existing_package is not None:
                package_row_id = str(existing_package["package_row_id"])
                connection.execute(
                    """
                    update packages
                    set name = ?, description = ?, updated_at = ?
                    where package_row_id = ?
                    """,
                    (
                        inspection["name"],
                        inspection["description"],
                        now,
                        package_row_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    insert into packages(
                      package_row_id, publisher_user_id, publisher_login, package_id,
                      name, description, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        package_row_id,
                        upload["user_id"],
                        publisher_login,
                        inspection["package_id"],
                        inspection["name"],
                        inspection["description"],
                        now,
                        now,
                    ),
                )
            try:
                connection.execute(
                    """
                    insert into releases(
                      release_id, package_row_id, upload_id, version, sha256,
                      object_key, size_bytes, status, validation_json,
                      created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?)
                    """,
                    (
                        release_id,
                        package_row_id,
                        upload["upload_id"],
                        inspection["version"],
                        inspection["sha256"],
                        upload["object_key"],
                        inspection["archive_size"],
                        validation_json,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                self._fail_upload(
                    str(upload["upload_id"]),
                    code="release_version_conflict",
                    message="this package version already exists",
                    status="rejected",
                )
                self.object_store.delete(str(upload["object_key"]))
                raise RegistryError(
                    "release_version_conflict",
                    "this package version already exists",
                ) from exc
            connection.execute(
                """
                update uploads
                set status = 'pending_review', validation_json = ?, updated_at = ?
                where upload_id = ? and status = 'validating'
                """,
                (validation_json, now, upload["upload_id"]),
            )
            _audit(
                connection,
                actor_user_id=str(upload["user_id"]),
                action="upload.validated",
                target_type="release",
                target_id=release_id,
                detail={"sha256": inspection["sha256"]},
            )
            connection.commit()
        return self.release_detail(release_id, include_unpublished=True)

    def _owned_upload(
        self,
        upload_id: str,
        *,
        user: dict[str, Any],
    ) -> sqlite3.Row:
        with self.database.connect() as connection:
            row = connection.execute(
                "select * from uploads where upload_id = ?",
                (upload_id,),
            ).fetchone()
        if row is None:
            raise RegistryError("upload_not_found", "upload was not found")
        if row["user_id"] != user["user_id"] and not bool(user.get("is_admin")):
            raise RegistryError("upload_not_found", "upload was not found")
        return row

    def _release(self, release_id: str) -> sqlite3.Row:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                select packages.*, releases.*
                from releases
                join packages on packages.package_row_id = releases.package_row_id
                where releases.release_id = ?
                """,
                (release_id,),
            ).fetchone()
        if row is None:
            raise RegistryError("release_not_found", "release was not found")
        return row

    def _fail_upload(
        self,
        upload_id: str,
        *,
        code: str,
        message: str,
        status: str,
    ) -> None:
        if status not in {"failed", "rejected"}:
            raise ValueError("invalid failed upload status")
        with self.database.connect() as connection:
            connection.execute(
                """
                update uploads
                set status = ?, error_code = ?, error_message = ?, updated_at = ?
                where upload_id = ?
                """,
                (status, code, message[:2_000], utc_now(), upload_id),
            )


def _upload_view(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    status = str(row["status"])
    if status not in UPLOAD_STATUSES:
        status = "failed"
    return {
        "upload_id": str(row["upload_id"]),
        "filename": str(row["filename"]),
        "expected_size": int(row["expected_size"]),
        "actual_size": int(row["actual_size"]) if row["actual_size"] is not None else None,
        "status": status,
        "error": (
            {
                "code": str(row["error_code"] or ""),
                "message": str(row["error_message"] or ""),
            }
            if row["error_code"] or row["error_message"]
            else None
        ),
        "validation": _json_object(row["validation_json"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _release_view(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "release_id": str(row["release_id"]),
        "publisher": str(row["publisher_login"]),
        "package_id": str(row["package_id"]),
        "name": str(row["name"]),
        "description": str(row["description"]),
        "version": str(row["version"]),
        "sha256": str(row["sha256"]),
        "size_bytes": int(row["size_bytes"]),
        "status": str(row["status"]),
        "validation": _json_object(row["validation_json"]),
        "changelog": str(row["changelog"] or ""),
        "download_count": int(row["download_count"]),
        "review_message": str(row["review_message"] or ""),
        "created_at": str(row["created_at"]),
        "published_at": str(row["published_at"] or ""),
        "updated_at": str(row["updated_at"]),
    }


def _public_release_view(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    view = _release_view(row)
    view.pop("review_message", None)
    return view


def _json_object(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _audit(
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
            _json_dumps(detail) if detail else None,
            utc_now(),
        ),
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _semver_key(value: str) -> tuple[int, int, int, int, str]:
    match = re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?",
        value,
    )
    if match is None:
        return (0, 0, 0, 0, value)
    prerelease = match.group(4)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        1 if prerelease is None else 0,
        prerelease or "",
    )
