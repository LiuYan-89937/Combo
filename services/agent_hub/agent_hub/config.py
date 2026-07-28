from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
from urllib.parse import urlparse


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    base_url: str
    database_path: Path
    admin_token: str
    admin_github_logins: frozenset[str]
    session_ttl_seconds: int
    oauth_state_ttl_seconds: int
    github_client_id: str
    github_client_secret: str
    github_success_redirect: str
    cors_origins: tuple[str, ...]
    oss_access_key_id: str
    oss_access_key_secret: str
    oss_bucket: str
    oss_public_endpoint: str
    oss_internal_endpoint: str
    oss_prefix: str
    upload_url_ttl_seconds: int
    download_url_ttl_seconds: int
    max_package_bytes: int
    max_archive_files: int
    max_uncompressed_bytes: int
    max_compression_ratio: int
    validation_poll_seconds: float
    backup_prefix: str

    @property
    def github_oauth_configured(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings(
        base_url=_url_env("AGENTHUB_BASE_URL", "http://127.0.0.1:8787"),
        database_path=Path(
            os.getenv("AGENTHUB_DATABASE_PATH", "/var/lib/fastagenthub/agenthub.sqlite3")
        ).expanduser(),
        admin_token=os.getenv("AGENTHUB_ADMIN_TOKEN", "").strip(),
        admin_github_logins=frozenset(
            item.casefold() for item in _csv_env("AGENTHUB_ADMIN_GITHUB_LOGINS")
        ),
        session_ttl_seconds=_positive_int_env("AGENTHUB_SESSION_TTL_SECONDS", 2_592_000),
        oauth_state_ttl_seconds=_positive_int_env("AGENTHUB_OAUTH_STATE_TTL_SECONDS", 600),
        github_client_id=os.getenv("AGENTHUB_GITHUB_CLIENT_ID", "").strip(),
        github_client_secret=os.getenv("AGENTHUB_GITHUB_CLIENT_SECRET", "").strip(),
        github_success_redirect=os.getenv(
            "AGENTHUB_GITHUB_SUCCESS_REDIRECT", "/api/v1/auth/me"
        ).strip(),
        cors_origins=tuple(_csv_env("AGENTHUB_CORS_ORIGINS")),
        oss_access_key_id=os.getenv("AGENTHUB_OSS_ACCESS_KEY_ID", "").strip(),
        oss_access_key_secret=os.getenv("AGENTHUB_OSS_ACCESS_KEY_SECRET", "").strip(),
        oss_bucket=os.getenv("AGENTHUB_OSS_BUCKET", "").strip(),
        oss_public_endpoint=_endpoint_env("AGENTHUB_OSS_PUBLIC_ENDPOINT"),
        oss_internal_endpoint=_endpoint_env("AGENTHUB_OSS_INTERNAL_ENDPOINT"),
        oss_prefix=_path_prefix_env("AGENTHUB_OSS_PREFIX", "agenthub"),
        upload_url_ttl_seconds=_positive_int_env("AGENTHUB_UPLOAD_URL_TTL_SECONDS", 900),
        download_url_ttl_seconds=_positive_int_env("AGENTHUB_DOWNLOAD_URL_TTL_SECONDS", 300),
        max_package_bytes=_positive_int_env(
            "AGENTHUB_MAX_PACKAGE_BYTES", 200 * 1024 * 1024
        ),
        max_archive_files=_positive_int_env("AGENTHUB_MAX_ARCHIVE_FILES", 5_000),
        max_uncompressed_bytes=_positive_int_env(
            "AGENTHUB_MAX_UNCOMPRESSED_BYTES", 500 * 1024 * 1024
        ),
        max_compression_ratio=_positive_int_env("AGENTHUB_MAX_COMPRESSION_RATIO", 100),
        validation_poll_seconds=_positive_float_env(
            "AGENTHUB_VALIDATION_POLL_SECONDS", 2.0
        ),
        backup_prefix=_path_prefix_env("AGENTHUB_BACKUP_PREFIX", "agenthub/backups"),
    )
    _validate_settings(settings)
    return settings


def _validate_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("AGENTHUB_OSS_ACCESS_KEY_ID", settings.oss_access_key_id),
            ("AGENTHUB_OSS_ACCESS_KEY_SECRET", settings.oss_access_key_secret),
            ("AGENTHUB_OSS_BUCKET", settings.oss_bucket),
            ("AGENTHUB_OSS_PUBLIC_ENDPOINT", settings.oss_public_endpoint),
            ("AGENTHUB_OSS_INTERNAL_ENDPOINT", settings.oss_internal_endpoint),
        )
        if not value
    ]
    if missing:
        raise ConfigurationError("missing required configuration: " + ", ".join(missing))
    if not settings.admin_token and not settings.admin_github_logins:
        raise ConfigurationError(
            "configure AGENTHUB_ADMIN_TOKEN or AGENTHUB_ADMIN_GITHUB_LOGINS"
        )
    redirect = urlparse(settings.github_success_redirect)
    if redirect.scheme or redirect.netloc or not settings.github_success_redirect.startswith("/"):
        raise ConfigurationError(
            "AGENTHUB_GITHUB_SUCCESS_REDIRECT must be an absolute-path reference"
        )


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    value = int(raw) if raw else default
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    value = float(raw) if raw else default
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _url_env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise ConfigurationError(f"{name} must be an absolute HTTP(S) URL")
    return value


def _endpoint_env(name: str) -> str:
    value = os.getenv(name, "").strip().rstrip("/")
    if value and not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value


def _path_prefix_env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().strip("/")
    if not value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ConfigurationError(f"{name} must be a safe object-key prefix")
    return value
