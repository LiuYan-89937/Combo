from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Iterator

import oss2

from agent_hub.config import Settings


class ObjectStoreError(RuntimeError):
    pass


class ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        auth = oss2.Auth(
            settings.oss_access_key_id,
            settings.oss_access_key_secret,
        )
        self.internal_bucket = oss2.Bucket(
            auth,
            settings.oss_internal_endpoint,
            settings.oss_bucket,
            connect_timeout=30,
        )
        self.public_bucket = oss2.Bucket(
            auth,
            settings.oss_public_endpoint,
            settings.oss_bucket,
            connect_timeout=30,
        )

    def health(self) -> dict[str, Any]:
        information = self.internal_bucket.get_bucket_info()
        return {
            "bucket": self.settings.oss_bucket,
            "region": str(information.location or ""),
            "storage_class": str(information.storage_class or ""),
        }

    def incoming_key(self, upload_id: str) -> str:
        return self._key("incoming", f"{upload_id}.zip")

    def app_release_staging_key(
        self,
        *,
        app_release_id: str,
        asset_id: str,
        filename: str,
    ) -> str:
        safe_filename = PurePosixPath(filename).name
        if safe_filename != filename:
            raise ValueError("application release filename must be a basename")
        return self._key(
            "app-releases",
            "staging",
            app_release_id,
            asset_id,
            safe_filename,
        )

    def release_key(
        self,
        *,
        publisher: str,
        package_id: str,
        version: str,
        digest: str,
    ) -> str:
        return self._key(
            "packages",
            publisher.casefold(),
            package_id,
            version,
            f"{digest}.zip",
        )

    def create_upload_url(
        self,
        object_key: str,
        *,
        content_type: str = "application/zip",
    ) -> dict[str, Any]:
        self._validate_key(object_key)
        headers = {"Content-Type": content_type}
        url = self.public_bucket.sign_url(
            "PUT",
            object_key,
            self.settings.upload_url_ttl_seconds,
            headers=headers,
            slash_safe=True,
        )
        return {
            "method": "PUT",
            "url": url,
            "headers": headers,
            "expires_in_seconds": self.settings.upload_url_ttl_seconds,
        }

    def object_size(self, object_key: str) -> int:
        self._validate_key(object_key)
        try:
            metadata = self.internal_bucket.head_object(object_key)
        except oss2.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(f"OSS object not found: {object_key}") from exc
        return int(metadata.content_length)

    def download_to(self, object_key: str, target: Path) -> None:
        self._validate_key(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.internal_bucket.get_object_to_file(object_key, str(target))
        except oss2.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(f"OSS object not found: {object_key}") from exc

    def iter_object(
        self,
        object_key: str,
        *,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        self._validate_key(object_key)
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        try:
            result = self.internal_bucket.get_object(object_key)
        except oss2.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(f"OSS object not found: {object_key}") from exc
        try:
            while True:
                chunk = result.read(chunk_size)
                if not chunk:
                    break
                yield bytes(chunk)
        finally:
            result.close()

    def promote(self, source_key: str, target_key: str) -> None:
        self._validate_key(source_key)
        self._validate_key(target_key)
        if self.internal_bucket.object_exists(target_key):
            raise FileExistsError(f"immutable release object already exists: {target_key}")
        self.internal_bucket.copy_object(
            self.settings.oss_bucket,
            source_key,
            target_key,
        )
        source_size = self.object_size(source_key)
        target_size = self.object_size(target_key)
        if source_size != target_size:
            self.internal_bucket.delete_object(target_key)
            raise ObjectStoreError(
                f"promoted object size mismatch: source={source_size}, target={target_size}"
            )

    def delete(self, object_key: str) -> None:
        self._validate_key(object_key)
        self.internal_bucket.delete_object(object_key)

    def signed_download_url(self, object_key: str) -> str:
        self._validate_key(object_key)
        return self.public_bucket.sign_url(
            "GET",
            object_key,
            self.settings.download_url_ttl_seconds,
            slash_safe=True,
        )

    def upload_backup(self, source: Path, object_key: str) -> None:
        self._validate_key(object_key)
        self.internal_bucket.put_object_from_file(object_key, str(source))

    def _key(self, *parts: str) -> str:
        key = str(PurePosixPath(self.settings.oss_prefix, *parts))
        self._validate_key(key)
        return key

    def _validate_key(self, object_key: str) -> None:
        path = PurePosixPath(str(object_key or ""))
        if (
            not object_key
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or not str(path).startswith(f"{self.settings.oss_prefix}/")
        ):
            raise ValueError("unsafe OSS object key")
