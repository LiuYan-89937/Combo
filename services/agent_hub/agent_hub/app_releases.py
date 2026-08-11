from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import total_ordering
from hashlib import sha256
import logging
import re
import sqlite3
from typing import Any, Iterable
from uuid import uuid4

from agent_hub.config import Settings
from agent_hub.audit import record_audit
from agent_hub.database import Database, utc_now
from agent_hub.github_releases import (
    GitHubReleaseClient,
    GitHubReleaseError,
    StagedGitHubAsset,
)
from agent_hub.oss_store import ObjectStore


LOGGER = logging.getLogger("agent_hub.app_releases")


class AppReleaseError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

SEMVER_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
FILENAME_PATTERN = re.compile(r"^[^/\\\x00]{1,200}$")
PLATFORM_ASSETS = {
    "macos": {
        "architectures": frozenset({"aarch64"}),
        "assets": {
            "installer": {
                "extensions": (".dmg",),
                "content_type": "application/x-apple-diskimage",
                "signature_required": False,
            },
            "updater": {
                "extensions": (".app.tar.gz",),
                "content_type": "application/gzip",
                "signature_required": True,
            },
        },
    },
    "windows": {
        "architectures": frozenset({"x86_64", "arm64"}),
        "assets": {
            "installer": {
                "extensions": (".exe",),
                "content_type": "application/vnd.microsoft.portable-executable",
                "signature_required": True,
            },
        },
    },
}


class AppReleaseRegistry:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        object_store: ObjectStore,
    ) -> None:
        self.settings = settings
        self.database = database
        self.object_store = object_store

    def create_release(
        self,
        *,
        admin: dict[str, Any],
        version: str,
        title: str,
        notes_markdown: str,
    ) -> dict[str, Any]:
        normalized_version = _version(version)
        normalized_title = _required_text(title, "title", maximum=200)
        notes = _required_text(notes_markdown, "notes_markdown", maximum=100_000)
        release_id = uuid4().hex
        now = utc_now()
        try:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    insert into app_releases(
                      app_release_id, version, tag_name, title, notes_markdown,
                      status, created_by, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, 'draft', ?, ?, ?)
                    """,
                    (
                        release_id,
                        normalized_version,
                        f"v{normalized_version}",
                        normalized_title,
                        notes,
                        str(admin["user_id"]),
                        now,
                        now,
                    ),
                )
                record_audit(
                    connection,
                    actor_user_id=str(admin["user_id"]),
                    action="app_release.created",
                    target_type="app_release",
                    target_id=release_id,
                    detail={"version": normalized_version},
                )
        except sqlite3.IntegrityError as exc:
            raise AppReleaseError(
                "app_release_version_conflict",
                "this application version already exists",
            ) from exc
        return self.release(release_id, include_private=True)

    def update_release(
        self,
        release_id: str,
        *,
        admin: dict[str, Any],
        title: str,
        notes_markdown: str,
    ) -> dict[str, Any]:
        release = self._release_row(release_id)
        if release["status"] in {"queued", "publishing", "withdrawn"}:
            raise AppReleaseError(
                "app_release_state_invalid",
                f"application release cannot be edited from status {release['status']}",
            )
        normalized_title = _required_text(title, "title", maximum=200)
        notes = _required_text(notes_markdown, "notes_markdown", maximum=100_000)
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            connection.execute(
                """
                update app_releases
                set title = ?, notes_markdown = ?, error_code = null,
                    error_message = null, updated_at = ?
                where app_release_id = ?
                """,
                (normalized_title, notes, now, release_id),
            )
            record_audit(
                connection,
                actor_user_id=str(admin["user_id"]),
                action="app_release.updated",
                target_type="app_release",
                target_id=release_id,
            )
            if release["status"] == "published":
                queued_sync = connection.execute(
                    """
                    select job_id from app_release_jobs
                    where app_release_id = ? and job_type = 'sync_metadata'
                      and status = 'queued'
                    limit 1
                    """,
                    (release_id,),
                ).fetchone()
                if queued_sync is None:
                    self._insert_job(
                        connection,
                        release_id=release_id,
                        job_type="sync_metadata",
                        created_by=str(admin["user_id"]),
                        total_bytes=0,
                    )
            connection.commit()
        return self.release(release_id, include_private=True)

    def create_asset_upload(
        self,
        release_id: str,
        *,
        admin: dict[str, Any],
        asset_kind: str,
        platform: str,
        architecture: str,
        filename: str,
        expected_size: int,
        updater_signature: str = "",
    ) -> dict[str, Any]:
        release = self._release_row(release_id)
        if release["status"] not in {"draft", "failed"}:
            raise AppReleaseError(
                "app_release_state_invalid",
                f"assets cannot be changed from status {release['status']}",
            )
        (
            normalized_kind,
            normalized_platform,
            normalized_architecture,
            normalized_filename,
            content_type,
            signature_required,
        ) = self._asset_identity(
                asset_kind=asset_kind,
                platform=platform,
                architecture=architecture,
                filename=filename,
            )
        signature = _updater_signature(
            updater_signature,
            required=signature_required,
        )
        if expected_size <= 0 or expected_size > self.settings.max_app_asset_bytes:
            raise AppReleaseError(
                "app_asset_size_invalid",
                f"asset size must be between 1 and "
                f"{self.settings.max_app_asset_bytes} bytes",
            )
        asset_id = uuid4().hex
        object_key = self.object_store.app_release_staging_key(
            app_release_id=release_id,
            asset_id=asset_id,
            filename=normalized_filename,
        )
        now = utc_now()
        old_object_key = ""
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            existing = connection.execute(
                """
                select * from app_release_assets
                where app_release_id = ? and platform = ? and architecture = ?
                  and asset_kind = ?
                """,
                (
                    release_id,
                    normalized_platform,
                    normalized_architecture,
                    normalized_kind,
                ),
            ).fetchone()
            filename_owner = connection.execute(
                """
                select asset_id from app_release_assets
                where app_release_id = ? and filename = ?
                """,
                (release_id, normalized_filename),
            ).fetchone()
            if (
                filename_owner is not None
                and (
                    existing is None
                    or str(filename_owner["asset_id"]) != str(existing["asset_id"])
                )
            ):
                connection.rollback()
                raise AppReleaseError(
                    "app_asset_filename_conflict",
                    "asset filenames must be unique within an application release",
                )
            if existing is not None:
                old_object_key = str(existing["object_key"])
                connection.execute(
                    "delete from app_release_assets where asset_id = ?",
                    (existing["asset_id"],),
                )
            connection.execute(
                """
                insert into app_release_assets(
                  asset_id, app_release_id, asset_kind, platform, architecture,
                  filename, content_type, object_key, expected_size,
                  updater_signature, status,
                  created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_upload', ?, ?)
                """,
                (
                    asset_id,
                    release_id,
                    normalized_kind,
                    normalized_platform,
                    normalized_architecture,
                    normalized_filename,
                    content_type,
                    object_key,
                    expected_size,
                    signature or None,
                    now,
                    now,
                ),
            )
            record_audit(
                connection,
                actor_user_id=str(admin["user_id"]),
                action="app_release.asset_created",
                target_type="app_release_asset",
                target_id=asset_id,
                detail={
                    "release_id": release_id,
                    "asset_kind": normalized_kind,
                    "platform": normalized_platform,
                    "architecture": normalized_architecture,
                    "filename": normalized_filename,
                    "expected_size": expected_size,
                },
            )
            connection.commit()
        if old_object_key:
            self._delete_staging_object(
                old_object_key,
                release_id=release_id,
                asset_id=str(existing["asset_id"]),
            )
        return {
            "asset": self.asset(asset_id),
            "upload_request": self.object_store.create_upload_url(
                object_key,
                content_type=content_type,
            ),
        }

    def complete_asset_upload(
        self,
        release_id: str,
        asset_id: str,
        *,
        admin: dict[str, Any],
    ) -> dict[str, Any]:
        asset = self._asset_row(release_id, asset_id)
        if asset["status"] != "awaiting_upload":
            raise AppReleaseError(
                "app_asset_state_invalid",
                f"asset cannot be completed from status {asset['status']}",
            )
        try:
            actual_size = self.object_store.object_size(str(asset["object_key"]))
        except FileNotFoundError as exc:
            raise AppReleaseError(
                "app_asset_object_missing",
                "uploaded application asset was not found",
            ) from exc
        expected_size = int(asset["expected_size"])
        if actual_size != expected_size:
            self.object_store.delete(str(asset["object_key"]))
            with self.database.connect() as connection:
                connection.execute(
                    """
                    update app_release_assets
                    set status = 'failed', actual_size = ?, error_code = ?,
                        error_message = ?, updated_at = ?
                    where asset_id = ?
                    """,
                    (
                        actual_size,
                        "app_asset_size_mismatch",
                        f"expected {expected_size} bytes, received {actual_size}",
                        utc_now(),
                        asset_id,
                    ),
                )
            raise AppReleaseError(
                "app_asset_size_mismatch",
                f"expected {expected_size} bytes, received {actual_size}",
            )
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            result = connection.execute(
                """
                update app_release_assets
                set status = 'uploaded', actual_size = ?, progress_bytes = 0,
                    error_code = null, error_message = null, updated_at = ?
                where asset_id = ? and status = 'awaiting_upload'
                """,
                (actual_size, utc_now(), asset_id),
            )
            if result.rowcount != 1:
                connection.rollback()
                raise AppReleaseError("app_asset_state_changed", "asset state changed")
            record_audit(
                connection,
                actor_user_id=str(admin["user_id"]),
                action="app_release.asset_uploaded",
                target_type="app_release_asset",
                target_id=asset_id,
                detail={"actual_size": actual_size},
            )
            connection.commit()
        return self.asset(asset_id)

    def delete_asset(
        self,
        release_id: str,
        asset_id: str,
        *,
        admin: dict[str, Any],
    ) -> None:
        release = self._release_row(release_id)
        if release["status"] not in {"draft", "failed"}:
            raise AppReleaseError(
                "app_release_state_invalid",
                f"assets cannot be changed from status {release['status']}",
            )
        asset = self._asset_row(release_id, asset_id)
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            connection.execute(
                "delete from app_release_assets where asset_id = ?",
                (asset_id,),
            )
            record_audit(
                connection,
                actor_user_id=str(admin["user_id"]),
                action="app_release.asset_deleted",
                target_type="app_release_asset",
                target_id=asset_id,
            )
            connection.commit()
        self._delete_staging_object(
            str(asset["object_key"]),
            release_id=release_id,
            asset_id=asset_id,
        )

    def delete_release(
        self,
        release_id: str,
        *,
        admin: dict[str, Any],
    ) -> None:
        release = self._release_row(release_id)
        if release["status"] not in {"draft", "failed"}:
            raise AppReleaseError(
                "app_release_state_invalid",
                f"application release cannot be deleted from status {release['status']}",
            )
        assets = self._asset_rows(release_id)
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            active_job = connection.execute(
                """
                select job_id from app_release_jobs
                where app_release_id = ? and status in ('queued', 'running')
                limit 1
                """,
                (release_id,),
            ).fetchone()
            if active_job is not None:
                connection.rollback()
                raise AppReleaseError(
                    "app_release_job_conflict",
                    "an application release job is still active",
                )
            connection.execute(
                "delete from app_releases where app_release_id = ?",
                (release_id,),
            )
            record_audit(
                connection,
                actor_user_id=str(admin["user_id"]),
                action="app_release.deleted",
                target_type="app_release",
                target_id=release_id,
                detail={"version": str(release["version"])},
            )
            connection.commit()
        for asset in assets:
            try:
                self.object_store.delete(str(asset["object_key"]))
            except Exception:
                LOGGER.exception(
                    "failed to remove deleted application release staging object",
                    extra={"release_id": release_id, "asset_id": str(asset["asset_id"])},
                )

    def queue_publish(
        self,
        release_id: str,
        *,
        admin: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.settings.github_release_configured:
            raise AppReleaseError(
                "github_release_not_configured",
                "GitHub application release publishing is not configured",
            )
        release = self._release_row(release_id)
        if release["status"] not in {"draft", "failed"}:
            raise AppReleaseError(
                "app_release_state_invalid",
                f"application release cannot be published from status {release['status']}",
            )
        assets = self._asset_rows(release_id)
        if not assets:
            raise AppReleaseError(
                "app_release_assets_required",
                "at least one uploaded application asset is required",
            )
        invalid = [row for row in assets if row["status"] != "uploaded"]
        if invalid:
            raise AppReleaseError(
                "app_release_assets_incomplete",
                "all application assets must finish uploading before publishing",
            )
        _validate_release_asset_set(assets)
        total_bytes = sum(int(row["actual_size"] or row["expected_size"]) for row in assets)
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            active_job = connection.execute(
                """
                select job_id from app_release_jobs
                where app_release_id = ? and status in ('queued', 'running')
                limit 1
                """,
                (release_id,),
            ).fetchone()
            if active_job is not None:
                connection.rollback()
                raise AppReleaseError(
                    "app_release_job_conflict",
                    "an application release job is already active",
                )
            job_id = self._insert_job(
                connection,
                release_id=release_id,
                job_type="publish",
                created_by=str(admin["user_id"]),
                total_bytes=total_bytes,
            )
            connection.execute(
                """
                update app_releases
                set status = 'queued', published_by = ?, error_code = null,
                    error_message = null, updated_at = ?
                where app_release_id = ?
                """,
                (str(admin["user_id"]), now, release_id),
            )
            record_audit(
                connection,
                actor_user_id=str(admin["user_id"]),
                action="app_release.publish_queued",
                target_type="app_release",
                target_id=release_id,
                detail={"job_id": job_id, "total_bytes": total_bytes},
            )
            connection.commit()
        return self.release(release_id, include_private=True)

    def claim_job(self) -> dict[str, Any] | None:
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            row = connection.execute(
                """
                select * from app_release_jobs
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
                update app_release_jobs
                set status = 'running', stage = 'preparing', claimed_at = ?, updated_at = ?
                where job_id = ? and status = 'queued'
                """,
                (now, now, row["job_id"]),
            )
            if result.rowcount != 1:
                connection.rollback()
                return None
            if row["job_type"] == "publish":
                connection.execute(
                    """
                    update app_releases
                    set status = 'publishing', updated_at = ?
                    where app_release_id = ? and status = 'queued'
                    """,
                    (now, row["app_release_id"]),
                )
            connection.commit()
        return dict(row)

    def process_claimed_job(self, job_id: str) -> dict[str, Any]:
        job = self._job_row(job_id)
        if job["status"] != "running":
            raise AppReleaseError(
                "app_release_job_missing",
                "claimed application release job was not found",
            )
        try:
            if job["job_type"] == "sync_metadata":
                return self._sync_metadata(dict(job))
            return self._publish(dict(job))
        except Exception as exc:
            self._fail_job(dict(job), exc)
            return {
                "job_id": job_id,
                "app_release_id": str(job["app_release_id"]),
                "status": "failed",
                "error_code": _error_code(exc),
                "error_message": f"{type(exc).__name__}: {exc}",
            }

    def recover_stale_jobs(self, *, stale_after_seconds: int = 1800) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - stale_after_seconds
        recovered = 0
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            rows = connection.execute(
                """
                select * from app_release_jobs
                where status = 'running'
                """
            ).fetchall()
            for row in rows:
                try:
                    claimed = datetime.fromisoformat(str(row["claimed_at"] or "")).timestamp()
                except ValueError:
                    claimed = 0
                if claimed >= cutoff:
                    continue
                now = utc_now()
                connection.execute(
                    """
                    update app_release_jobs
                    set status = 'queued', stage = 'recovered', claimed_at = null,
                        updated_at = ?
                    where job_id = ? and status = 'running'
                    """,
                    (now, row["job_id"]),
                )
                if row["job_type"] == "publish":
                    connection.execute(
                        """
                        update app_releases
                        set status = 'queued', updated_at = ?
                        where app_release_id = ? and status = 'publishing'
                        """,
                        (now, row["app_release_id"]),
                    )
                    connection.execute(
                        """
                        update app_release_assets
                        set status = 'uploaded', progress_bytes = 0, updated_at = ?
                        where app_release_id = ? and status = 'publishing'
                        """,
                        (now, row["app_release_id"]),
                    )
                recovered += 1
            connection.commit()
        return recovered

    def list_releases(
        self,
        *,
        include_private: bool,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(100, int(limit)))
        with self.database.connect() as connection:
            if include_private:
                rows = connection.execute(
                    """
                    select * from app_releases
                    order by created_at desc
                    limit ?
                    """,
                    (bounded_limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    select * from app_releases
                    where status = 'published'
                    """
                ).fetchall()
                rows = sorted(
                    rows,
                    key=lambda row: _semver(str(row["version"])),
                    reverse=True,
                )[:bounded_limit]
        return [
            self._release_view(row, include_private=include_private)
            for row in rows
        ]

    def latest_release(self) -> dict[str, Any]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                select * from app_releases
                where status = 'published'
                """
            ).fetchall()
        if not rows:
            raise AppReleaseError(
                "app_release_not_found",
                "no published application release was found",
            )
        stable_rows = [
            row for row in rows if not _semver(str(row["version"])).is_prerelease
        ]
        latest = max(
            stable_rows or rows,
            key=lambda row: _semver(str(row["version"])),
        )
        return self._release_view(latest, include_private=False)

    def release(
        self,
        release_id: str,
        *,
        include_private: bool,
    ) -> dict[str, Any]:
        row = self._release_row(release_id)
        if not include_private and row["status"] != "published":
            raise AppReleaseError(
                "app_release_not_found",
                "published application release was not found",
            )
        return self._release_view(row, include_private=include_private)

    def asset(self, asset_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "select * from app_release_assets where asset_id = ?",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise AppReleaseError("app_asset_not_found", "application asset was not found")
        return _asset_view(row, include_private=True)

    def installer_download_url(self, asset_id: str) -> str:
        now = utc_now()
        with self.database.connect() as connection:
            asset = connection.execute(
                """
                update app_release_assets
                set download_count = download_count + 1, updated_at = ?
                where asset_id = ?
                  and asset_kind = 'installer'
                  and status = 'published'
                  and download_url is not null
                  and download_url != ''
                  and exists (
                    select 1
                    from app_releases
                    where app_releases.app_release_id = app_release_assets.app_release_id
                      and app_releases.status = 'published'
                  )
                returning download_url
                """,
                (now, asset_id),
            ).fetchone()
        if asset is None:
            raise AppReleaseError(
                "app_asset_not_found",
                "published application installer was not found",
            )
        return str(asset["download_url"])

    def public_config(self) -> dict[str, Any]:
        try:
            latest = self.latest_release()
        except AppReleaseError:
            latest = None
        downloads = []
        if latest is not None:
            downloads = [
                {
                    "platform": asset["platform"],
                    "label": _platform_label(str(asset["platform"])),
                    "arch": _architecture_label(str(asset["architecture"])),
                    "url": f"/api/v1/app-release-assets/{asset['asset_id']}/download",
                    "version": latest["version"],
                    "sizeLabel": _size_label(int(asset["size_bytes"])),
                    "downloadCount": int(asset["download_count"]),
                }
                for asset in latest["assets"]
                if asset["asset_kind"] == "installer" and asset["download_url"]
            ]
        with self.database.connect() as connection:
            total_download_count = int(
                connection.execute(
                    """
                    select coalesce(sum(app_release_assets.download_count), 0)
                    from app_release_assets
                    join app_releases
                      on app_releases.app_release_id = app_release_assets.app_release_id
                    where app_release_assets.asset_kind = 'installer'
                      and app_release_assets.status = 'published'
                      and app_releases.status = 'published'
                    """
                ).fetchone()[0]
            )
        return {
            "githubRepoUrl": self.settings.github_repository_url,
            "downloads": downloads,
            "totalDownloadCount": (
                self.settings.installer_download_baseline + total_download_count
            ),
            "releaseManaged": latest is not None,
        }

    def update_manifest(
        self,
        *,
        target: str,
        architecture: str,
        current_version: str,
    ) -> dict[str, Any] | None:
        platform = {"darwin": "macos", "windows": "windows"}.get(
            str(target or "").strip().casefold()
        )
        normalized_architecture = str(architecture or "").strip().casefold()
        if platform is None:
            raise AppReleaseError(
                "app_update_target_invalid",
                "updates are available for darwin and windows targets",
            )
        allowed_architectures = PLATFORM_ASSETS[platform]["architectures"]
        if normalized_architecture not in allowed_architectures:
            raise AppReleaseError(
                "app_update_architecture_invalid",
                f"unsupported update architecture for {target}",
            )
        current = _semver(current_version)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                select * from app_releases
                where status = 'published'
                """
            ).fetchall()
        candidates = sorted(
            (
                row
                for row in rows
                if _semver(str(row["version"])) > current
                and (
                    current.is_prerelease
                    or not _semver(str(row["version"])).is_prerelease
                )
            ),
            key=lambda row: _semver(str(row["version"])),
            reverse=True,
        )
        for release in candidates:
            asset = self._update_asset_row(
                str(release["app_release_id"]),
                platform=platform,
                architecture=normalized_architecture,
            )
            if asset is None:
                continue
            return {
                "version": str(release["version"]),
                "pub_date": str(release["published_at"] or ""),
                "url": str(asset["download_url"] or ""),
                "signature": str(asset["updater_signature"] or ""),
                "notes": str(release["notes_markdown"]),
            }
        return None

    def _publish(self, job: dict[str, Any]) -> dict[str, Any]:
        release_id = str(job["app_release_id"])
        release = self._release_row(release_id)
        assets = self._asset_rows(release_id)
        if not assets:
            raise AppReleaseError(
                "app_release_assets_required",
                "application release has no assets",
            )
        client = GitHubReleaseClient(self.settings)
        staged: list[tuple[sqlite3.Row, StagedGitHubAsset, str]] = []
        total_progress = 0
        try:
            release_version = _semver(str(release["version"]))
            github_release = client.ensure_release(
                management_id=release_id,
                tag_name=str(release["tag_name"]),
                title=str(release["title"]),
                notes_markdown=str(release["notes_markdown"]),
                prerelease=release_version.is_prerelease,
            )
            github_release_id = int(github_release["id"])
            self._set_job_stage(
                str(job["job_id"]),
                stage="uploading_assets",
                github_release_id=github_release_id,
            )
            for asset in assets:
                asset_size = int(asset["actual_size"] or asset["expected_size"])
                self._set_asset_publishing(str(asset["asset_id"]))
                digest = sha256()
                last_reported = 0

                def source() -> Iterable[bytes]:
                    for chunk in self.object_store.iter_object(str(asset["object_key"])):
                        digest.update(chunk)
                        yield chunk

                def progress(sent: int) -> None:
                    nonlocal last_reported
                    if sent < asset_size and sent - last_reported < 4 * 1024 * 1024:
                        return
                    last_reported = sent
                    self._update_progress(
                        job_id=str(job["job_id"]),
                        asset_id=str(asset["asset_id"]),
                        asset_progress=sent,
                        job_progress=total_progress + sent,
                    )

                staged_asset = client.stage_asset(
                    github_release_id=github_release_id,
                    final_name=str(asset["filename"]),
                    marker=release_id,
                    content_type=str(asset["content_type"]),
                    size_bytes=asset_size,
                    content=source(),
                    progress=progress,
                )
                digest_hex = digest.hexdigest()
                staged.append((asset, staged_asset, digest_hex))
                total_progress += asset_size
                self._set_asset_staged(
                    asset_id=str(asset["asset_id"]),
                    digest=digest_hex,
                    github_asset_id=staged_asset.asset_id,
                )
            self._set_job_stage(str(job["job_id"]), stage="committing_assets")
            client.commit_staged_assets(
                github_release_id=github_release_id,
                staged_assets=[item[1] for item in staged],
            )
            self._set_job_stage(str(job["job_id"]), stage="publishing_release")
            published = client.publish_release(
                management_id=release_id,
                github_release_id=github_release_id,
                title=str(release["title"]),
                notes_markdown=str(release["notes_markdown"]),
                prerelease=release_version.is_prerelease,
            )
            published_assets = client.published_assets(
                github_release_id=github_release_id,
                expected_assets=[item[1] for item in staged],
            )
            now = utc_now()
            with self.database.connect() as connection:
                connection.execute("begin immediate")
                for asset, staged_asset, digest_hex in staged:
                    remote = published_assets[staged_asset.final_name]
                    connection.execute(
                        """
                        update app_release_assets
                        set status = 'published', progress_bytes = actual_size,
                            sha256 = ?, github_asset_id = ?, download_url = ?,
                            error_code = null, error_message = null, updated_at = ?
                        where asset_id = ?
                        """,
                        (
                            digest_hex,
                            int(remote["id"]),
                            str(remote.get("browser_download_url") or ""),
                            now,
                            asset["asset_id"],
                        ),
                    )
                connection.execute(
                    """
                    update app_releases
                    set status = 'published', github_release_id = ?, github_url = ?,
                        error_code = null, error_message = null,
                        published_at = coalesce(published_at, ?), updated_at = ?
                    where app_release_id = ?
                    """,
                    (
                        github_release_id,
                        str(published.get("html_url") or ""),
                        now,
                        now,
                        release_id,
                    ),
                )
                connection.execute(
                    """
                    update app_release_jobs
                    set status = 'succeeded', stage = 'completed',
                        progress_bytes = total_bytes, updated_at = ?
                    where job_id = ?
                    """,
                    (now, job["job_id"]),
                )
                record_audit(
                    connection,
                    actor_user_id=str(job["created_by"]),
                    action="app_release.published",
                    target_type="app_release",
                    target_id=release_id,
                    detail={
                        "job_id": str(job["job_id"]),
                        "github_release_id": github_release_id,
                    },
                )
                connection.commit()
            for asset in assets:
                try:
                    self.object_store.delete(str(asset["object_key"]))
                except Exception:
                    LOGGER.exception(
                        "failed to remove published application release staging object",
                        extra={
                            "release_id": release_id,
                            "asset_id": str(asset["asset_id"]),
                        },
                    )
            return self.release(release_id, include_private=True)
        finally:
            client.close()

    def _sync_metadata(self, job: dict[str, Any]) -> dict[str, Any]:
        release = self._release_row(str(job["app_release_id"]))
        github_release_id = int(release["github_release_id"] or 0)
        if github_release_id <= 0:
            raise AppReleaseError(
                "github_release_missing",
                "published application release has no GitHub release id",
            )
        client = GitHubReleaseClient(self.settings)
        try:
            remote = client.update_release_metadata(
                management_id=str(release["app_release_id"]),
                github_release_id=github_release_id,
                title=str(release["title"]),
                notes_markdown=str(release["notes_markdown"]),
            )
        finally:
            client.close()
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            connection.execute(
                """
                update app_releases
                set github_url = ?, error_code = null, error_message = null, updated_at = ?
                where app_release_id = ?
                """,
                (
                    str(remote.get("html_url") or release["github_url"] or ""),
                    now,
                    release["app_release_id"],
                ),
            )
            connection.execute(
                """
                update app_release_jobs
                set status = 'succeeded', stage = 'completed', updated_at = ?
                where job_id = ?
                """,
                (now, job["job_id"]),
            )
            connection.commit()
        return self.release(str(release["app_release_id"]), include_private=True)

    def _fail_job(self, job: dict[str, Any], error: Exception) -> None:
        code = _error_code(error)
        message = f"{type(error).__name__}: {error}"[:4_000]
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            connection.execute(
                """
                update app_release_jobs
                set status = 'failed', stage = 'failed', error_code = ?,
                    error_message = ?, updated_at = ?
                where job_id = ?
                """,
                (code, message, now, job["job_id"]),
            )
            if job["job_type"] == "publish":
                connection.execute(
                    """
                    update app_releases
                    set status = 'failed', error_code = ?, error_message = ?, updated_at = ?
                    where app_release_id = ?
                    """,
                    (code, message, now, job["app_release_id"]),
                )
                connection.execute(
                    """
                    update app_release_assets
                    set status = 'uploaded', progress_bytes = 0,
                        error_code = ?, error_message = ?, updated_at = ?
                    where app_release_id = ? and status = 'publishing'
                    """,
                    (code, message, now, job["app_release_id"]),
                )
            else:
                connection.execute(
                    """
                    update app_releases
                    set error_code = ?, error_message = ?, updated_at = ?
                    where app_release_id = ?
                    """,
                    (code, message, now, job["app_release_id"]),
                )
            connection.commit()

    def _release_view(
        self,
        row: sqlite3.Row,
        *,
        include_private: bool,
    ) -> dict[str, Any]:
        assets = [
            _asset_view(asset, include_private=include_private)
            for asset in self._asset_rows(str(row["app_release_id"]))
            if include_private
            or (
                asset["status"] == "published"
                and asset["asset_kind"] == "installer"
            )
        ]
        view: dict[str, Any] = {
            "app_release_id": str(row["app_release_id"]),
            "version": str(row["version"]),
            "tag_name": str(row["tag_name"]),
            "title": str(row["title"]),
            "notes_markdown": str(row["notes_markdown"]),
            "status": str(row["status"]),
            "github_url": str(row["github_url"] or ""),
            "created_at": str(row["created_at"]),
            "published_at": str(row["published_at"] or ""),
            "updated_at": str(row["updated_at"]),
            "assets": assets,
        }
        if include_private:
            view["error"] = (
                {
                    "code": str(row["error_code"] or ""),
                    "message": str(row["error_message"] or ""),
                }
                if row["error_code"] or row["error_message"]
                else None
            )
            with self.database.connect() as connection:
                job = connection.execute(
                    """
                    select * from app_release_jobs
                    where app_release_id = ?
                    order by created_at desc
                    limit 1
                    """,
                    (row["app_release_id"],),
                ).fetchone()
            view["latest_job"] = _job_view(job) if job is not None else None
        return view

    def _release_row(self, release_id: str) -> sqlite3.Row:
        with self.database.connect() as connection:
            row = connection.execute(
                "select * from app_releases where app_release_id = ?",
                (release_id,),
            ).fetchone()
        if row is None:
            raise AppReleaseError(
                "app_release_not_found",
                "application release was not found",
            )
        return row

    def _asset_row(self, release_id: str, asset_id: str) -> sqlite3.Row:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                select * from app_release_assets
                where app_release_id = ? and asset_id = ?
                """,
                (release_id, asset_id),
            ).fetchone()
        if row is None:
            raise AppReleaseError("app_asset_not_found", "application asset was not found")
        return row

    def _asset_rows(self, release_id: str) -> list[sqlite3.Row]:
        with self.database.connect() as connection:
            return connection.execute(
                """
                select * from app_release_assets
                where app_release_id = ?
                order by platform, architecture, asset_kind
                """,
                (release_id,),
            ).fetchall()

    def _update_asset_row(
        self,
        release_id: str,
        *,
        platform: str,
        architecture: str,
    ) -> sqlite3.Row | None:
        asset_kind = "updater" if platform == "macos" else "installer"
        architectures = (architecture,)
        placeholders = ", ".join("?" for _ in architectures)
        with self.database.connect() as connection:
            return connection.execute(
                f"""
                select * from app_release_assets
                where app_release_id = ? and platform = ? and asset_kind = ?
                  and architecture in ({placeholders})
                  and status = 'published'
                  and updater_signature is not null
                  and updater_signature != ''
                  and download_url is not null
                  and download_url != ''
                order by case when architecture = ? then 0 else 1 end
                limit 1
                """,
                (
                    release_id,
                    platform,
                    asset_kind,
                    *architectures,
                    architecture,
                ),
            ).fetchone()

    def _job_row(self, job_id: str) -> sqlite3.Row:
        with self.database.connect() as connection:
            row = connection.execute(
                "select * from app_release_jobs where job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise AppReleaseError(
                "app_release_job_not_found",
                "application release job was not found",
            )
        return row

    def _insert_job(
        self,
        connection: sqlite3.Connection,
        *,
        release_id: str,
        job_type: str,
        created_by: str,
        total_bytes: int,
    ) -> str:
        job_id = uuid4().hex
        now = utc_now()
        connection.execute(
            """
            insert into app_release_jobs(
              job_id, app_release_id, job_type, status, stage,
              total_bytes, created_by, created_at, updated_at
            ) values (?, ?, ?, 'queued', 'queued', ?, ?, ?, ?)
            """,
            (
                job_id,
                release_id,
                job_type,
                total_bytes,
                created_by,
                now,
                now,
            ),
        )
        return job_id

    def _set_job_stage(
        self,
        job_id: str,
        *,
        stage: str,
        github_release_id: int | None = None,
    ) -> None:
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            if github_release_id is not None:
                connection.execute(
                    """
                    update app_releases
                    set github_release_id = ?, updated_at = ?
                    where app_release_id = (
                      select app_release_id from app_release_jobs where job_id = ?
                    )
                    """,
                    (github_release_id, now, job_id),
                )
            connection.execute(
                """
                update app_release_jobs
                set stage = ?, updated_at = ?
                where job_id = ? and status = 'running'
                """,
                (stage, now, job_id),
            )
            connection.commit()

    def _set_asset_publishing(self, asset_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                update app_release_assets
                set status = 'publishing', progress_bytes = 0,
                    error_code = null, error_message = null, updated_at = ?
                where asset_id = ?
                """,
                (utc_now(), asset_id),
            )

    def _set_asset_staged(
        self,
        *,
        asset_id: str,
        digest: str,
        github_asset_id: int,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                update app_release_assets
                set sha256 = ?, github_asset_id = ?, progress_bytes = actual_size,
                    updated_at = ?
                where asset_id = ? and status = 'publishing'
                """,
                (digest, github_asset_id, utc_now(), asset_id),
            )

    def _update_progress(
        self,
        *,
        job_id: str,
        asset_id: str,
        asset_progress: int,
        job_progress: int,
    ) -> None:
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("begin immediate")
            connection.execute(
                """
                update app_release_assets
                set progress_bytes = ?, updated_at = ?
                where asset_id = ? and status = 'publishing'
                """,
                (asset_progress, now, asset_id),
            )
            connection.execute(
                """
                update app_release_jobs
                set progress_bytes = ?, updated_at = ?
                where job_id = ? and status = 'running'
                """,
                (job_progress, now, job_id),
            )
            connection.commit()

    def _delete_staging_object(
        self,
        object_key: str,
        *,
        release_id: str,
        asset_id: str,
    ) -> None:
        try:
            self.object_store.delete(object_key)
        except Exception:
            LOGGER.exception(
                "failed to remove application release staging object",
                extra={"release_id": release_id, "asset_id": asset_id},
            )

    @staticmethod
    def _asset_identity(
        *,
        asset_kind: str,
        platform: str,
        architecture: str,
        filename: str,
    ) -> tuple[str, str, str, str, str, bool]:
        normalized_kind = str(asset_kind or "").strip().casefold()
        normalized_platform = str(platform or "").strip().casefold()
        normalized_architecture = str(architecture or "").strip().casefold()
        normalized_filename = str(filename or "").strip()
        specification = PLATFORM_ASSETS.get(normalized_platform)
        if specification is None:
            raise AppReleaseError(
                "app_asset_platform_invalid",
                "platform must be macos or windows",
            )
        if normalized_architecture not in specification["architectures"]:
            raise AppReleaseError(
                "app_asset_architecture_invalid",
                f"unsupported architecture for {normalized_platform}",
            )
        asset_specification = specification["assets"].get(normalized_kind)
        if asset_specification is None:
            raise AppReleaseError(
                "app_asset_kind_invalid",
                f"{normalized_kind or 'unknown'} assets are not supported for "
                f"{normalized_platform}",
            )
        if not FILENAME_PATTERN.fullmatch(normalized_filename):
            raise AppReleaseError(
                "app_asset_filename_invalid",
                "asset filename must be a safe basename",
            )
        lowered_filename = normalized_filename.casefold()
        extensions = tuple(asset_specification["extensions"])
        if not lowered_filename.endswith(extensions):
            allowed = ", ".join(extensions)
            raise AppReleaseError(
                "app_asset_filename_invalid",
                f"{normalized_platform} asset must use one of: {allowed}",
            )
        return (
            normalized_kind,
            normalized_platform,
            normalized_architecture,
            normalized_filename,
            str(asset_specification["content_type"]),
            bool(asset_specification["signature_required"]),
        )


def _asset_view(row: sqlite3.Row, *, include_private: bool) -> dict[str, Any]:
    view: dict[str, Any] = {
        "asset_id": str(row["asset_id"]),
        "asset_kind": str(row["asset_kind"]),
        "platform": str(row["platform"]),
        "architecture": str(row["architecture"]),
        "filename": str(row["filename"]),
        "content_type": str(row["content_type"]),
        "size_bytes": int(row["actual_size"] or row["expected_size"]),
        "sha256": str(row["sha256"] or ""),
        "status": str(row["status"]),
        "download_url": str(row["download_url"] or ""),
        "download_count": int(row["download_count"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }
    if include_private:
        expected = int(row["expected_size"])
        progress = int(row["progress_bytes"])
        view["expected_size"] = expected
        view["progress_bytes"] = progress
        view["progress_ratio"] = min(1.0, progress / expected) if expected else 0.0
        view["has_updater_signature"] = bool(row["updater_signature"])
        view["error"] = (
            {
                "code": str(row["error_code"] or ""),
                "message": str(row["error_message"] or ""),
            }
            if row["error_code"] or row["error_message"]
            else None
        )
    return view


def _job_view(row: sqlite3.Row) -> dict[str, Any]:
    total = int(row["total_bytes"])
    progress = int(row["progress_bytes"])
    return {
        "job_id": str(row["job_id"]),
        "job_type": str(row["job_type"]),
        "status": str(row["status"]),
        "stage": str(row["stage"]),
        "progress_bytes": progress,
        "total_bytes": total,
        "progress_ratio": min(1.0, progress / total) if total else 0.0,
        "error": (
            {
                "code": str(row["error_code"] or ""),
                "message": str(row["error_message"] or ""),
            }
            if row["error_code"] or row["error_message"]
            else None
        ),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _version(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    _semver(normalized)
    return normalized


@total_ordering
@dataclass(frozen=True, slots=True)
class SemVer:
    core: tuple[int, int, int]
    prerelease: tuple[str, ...]

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        if self.core != other.core:
            return self.core < other.core
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            left_numeric = left.isdigit()
            right_numeric = right.isdigit()
            if left_numeric and right_numeric:
                return int(left) < int(right)
            if left_numeric != right_numeric:
                return left_numeric
            return left < right
        return len(self.prerelease) < len(other.prerelease)


def _semver(value: str) -> SemVer:
    normalized = str(value or "").strip()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    match = SEMVER_PATTERN.fullmatch(normalized)
    if match is None:
        raise AppReleaseError(
            "app_release_version_invalid",
            "version must be valid semantic version text",
        )
    prerelease = tuple(
        part
        for part in str(match.group("prerelease") or "").split(".")
        if part
    )
    return SemVer(
        core=(
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
        ),
        prerelease=prerelease,
    )


def _updater_signature(value: str, *, required: bool) -> str:
    normalized = str(value or "").strip()
    if required and not normalized:
        raise AppReleaseError(
            "app_asset_signature_required",
            "the Tauri updater signature is required for this asset",
        )
    if len(normalized) > 20_000 or "\x00" in normalized:
        raise AppReleaseError(
            "app_asset_signature_invalid",
            "the Tauri updater signature is invalid",
        )
    return normalized


def _validate_release_asset_set(assets: list[sqlite3.Row]) -> None:
    installers = [asset for asset in assets if asset["asset_kind"] == "installer"]
    if not installers:
        raise AppReleaseError(
            "app_release_installer_required",
            "at least one application installer is required",
        )
    identities = {
        (
            str(asset["platform"]),
            str(asset["architecture"]),
            str(asset["asset_kind"]),
        ): asset
        for asset in assets
    }
    for installer in installers:
        platform = str(installer["platform"])
        architecture = str(installer["architecture"])
        if platform == "windows":
            if not installer["updater_signature"]:
                raise AppReleaseError(
                    "app_release_update_signature_required",
                    f"Windows {architecture} installer requires its Tauri signature",
                )
            continue
        updater = identities.get((platform, architecture, "updater"))
        if updater is None or not updater["updater_signature"]:
            raise AppReleaseError(
                "app_release_updater_required",
                f"macOS {architecture} installer requires a signed updater archive",
            )
    for asset in assets:
        if asset["asset_kind"] != "updater":
            continue
        identity = (
            str(asset["platform"]),
            str(asset["architecture"]),
            "installer",
        )
        if identity not in identities:
            raise AppReleaseError(
                "app_release_installer_required",
                f"{asset['platform']} {asset['architecture']} updater has no installer",
            )


def _required_text(value: str, field: str, *, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise AppReleaseError(f"{field}_required", f"{field} must not be empty")
    if len(normalized) > maximum:
        raise AppReleaseError(
            f"{field}_too_long",
            f"{field} must contain at most {maximum} characters",
        )
    return normalized


def _error_code(error: Exception) -> str:
    if isinstance(error, AppReleaseError):
        return error.code
    if isinstance(error, GitHubReleaseError):
        return "github_release_error"
    return "app_release_internal_error"


def _platform_label(platform: str) -> str:
    return {"macos": "macOS", "windows": "Windows"}.get(
        platform,
        platform,
    )


def _architecture_label(architecture: str) -> str:
    return {
        "aarch64": "Apple Silicon",
        "x86_64": "x64",
        "arm64": "ARM64",
    }.get(architecture, architecture)


def _size_label(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
