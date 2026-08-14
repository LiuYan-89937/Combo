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
    github_release_owner: str
    github_release_repo: str
    github_release_token: str
    cors_origins: tuple[str, ...]
    oss_access_key_id: str
    oss_access_key_secret: str
    oss_bucket: str
    oss_public_endpoint: str
    oss_internal_endpoint: str
    oss_prefix: str
    upload_url_ttl_seconds: int
    max_app_asset_bytes: int
    installer_download_baseline: int
    worker_poll_seconds: float
    backup_prefix: str

    @property
    def github_oauth_configured(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def github_release_configured(self) -> bool:
        return bool(
            self.github_release_owner
            and self.github_release_repo
            and self.github_release_token
        )

    @property
    def github_repository_url(self) -> str:
        if not self.github_release_owner or not self.github_release_repo:
            return ""
        return (
            f"https://github.com/{self.github_release_owner}/"
            f"{self.github_release_repo}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings(
        base_url=_url_env("COMBO_SERVICE_BASE_URL", "http://127.0.0.1:8787"),
        database_path=Path(
            os.getenv("COMBO_SERVICE_DATABASE_PATH", "/var/lib/combo-service/combo_service.sqlite3")
        ).expanduser(),
        admin_token=os.getenv("COMBO_SERVICE_ADMIN_TOKEN", "").strip(),
        admin_github_logins=frozenset(
            item.casefold() for item in _csv_env("COMBO_SERVICE_ADMIN_GITHUB_LOGINS")
        ),
        session_ttl_seconds=_positive_int_env("COMBO_SERVICE_SESSION_TTL_SECONDS", 2_592_000),
        oauth_state_ttl_seconds=_positive_int_env("COMBO_SERVICE_OAUTH_STATE_TTL_SECONDS", 600),
        github_client_id=os.getenv("COMBO_SERVICE_GITHUB_CLIENT_ID", "").strip(),
        github_client_secret=os.getenv("COMBO_SERVICE_GITHUB_CLIENT_SECRET", "").strip(),
        github_success_redirect=os.getenv(
            "COMBO_SERVICE_GITHUB_SUCCESS_REDIRECT", "/api/v1/auth/me"
        ).strip(),
        github_release_owner=os.getenv(
            "COMBO_SERVICE_GITHUB_RELEASE_OWNER", ""
        ).strip(),
        github_release_repo=os.getenv(
            "COMBO_SERVICE_GITHUB_RELEASE_REPO", ""
        ).strip(),
        github_release_token=os.getenv(
            "COMBO_SERVICE_GITHUB_RELEASE_TOKEN", ""
        ).strip(),
        cors_origins=tuple(_csv_env("COMBO_SERVICE_CORS_ORIGINS")),
        oss_access_key_id=os.getenv("COMBO_SERVICE_OSS_ACCESS_KEY_ID", "").strip(),
        oss_access_key_secret=os.getenv("COMBO_SERVICE_OSS_ACCESS_KEY_SECRET", "").strip(),
        oss_bucket=os.getenv("COMBO_SERVICE_OSS_BUCKET", "").strip(),
        oss_public_endpoint=_endpoint_env("COMBO_SERVICE_OSS_PUBLIC_ENDPOINT"),
        oss_internal_endpoint=_endpoint_env("COMBO_SERVICE_OSS_INTERNAL_ENDPOINT"),
        oss_prefix=_path_prefix_env("COMBO_SERVICE_OSS_PREFIX", "combo_service"),
        upload_url_ttl_seconds=_positive_int_env("COMBO_SERVICE_UPLOAD_URL_TTL_SECONDS", 900),
        max_app_asset_bytes=_positive_int_env(
            "COMBO_SERVICE_MAX_APP_ASSET_BYTES", 1024 * 1024 * 1024
        ),
        installer_download_baseline=_non_negative_int_env(
            "COMBO_SERVICE_INSTALLER_DOWNLOAD_BASELINE", 0
        ),
        worker_poll_seconds=_positive_float_env(
            "COMBO_SERVICE_WORKER_POLL_SECONDS", 2.0
        ),
        backup_prefix=_path_prefix_env("COMBO_SERVICE_BACKUP_PREFIX", "combo_service/backups"),
    )
    _validate_settings(settings)
    return settings


def _validate_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("COMBO_SERVICE_OSS_ACCESS_KEY_ID", settings.oss_access_key_id),
            ("COMBO_SERVICE_OSS_ACCESS_KEY_SECRET", settings.oss_access_key_secret),
            ("COMBO_SERVICE_OSS_BUCKET", settings.oss_bucket),
            ("COMBO_SERVICE_OSS_PUBLIC_ENDPOINT", settings.oss_public_endpoint),
            ("COMBO_SERVICE_OSS_INTERNAL_ENDPOINT", settings.oss_internal_endpoint),
        )
        if not value
    ]
    if missing:
        raise ConfigurationError("missing required configuration: " + ", ".join(missing))
    if not settings.admin_token and not settings.admin_github_logins:
        raise ConfigurationError(
            "configure COMBO_SERVICE_ADMIN_TOKEN or COMBO_SERVICE_ADMIN_GITHUB_LOGINS"
        )
    redirect = urlparse(settings.github_success_redirect)
    if redirect.scheme or redirect.netloc or not settings.github_success_redirect.startswith("/"):
        raise ConfigurationError(
            "COMBO_SERVICE_GITHUB_SUCCESS_REDIRECT must be an absolute-path reference"
        )
    if bool(settings.github_release_owner) != bool(settings.github_release_repo):
        raise ConfigurationError(
            "COMBO_SERVICE_GITHUB_RELEASE_OWNER and COMBO_SERVICE_GITHUB_RELEASE_REPO "
            "must be configured together"
        )
    if settings.github_release_token and not (
        settings.github_release_owner and settings.github_release_repo
    ):
        raise ConfigurationError(
            "COMBO_SERVICE_GITHUB_RELEASE_TOKEN requires a configured GitHub repository"
        )
    for name, value in (
        ("COMBO_SERVICE_GITHUB_RELEASE_OWNER", settings.github_release_owner),
        ("COMBO_SERVICE_GITHUB_RELEASE_REPO", settings.github_release_repo),
    ):
        if value and (
            value in {".", ".."}
            or "/" in value
            or "\\" in value
            or any(character.isspace() for character in value)
        ):
            raise ConfigurationError(f"{name} must be a GitHub path segment")


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    value = int(raw) if raw else default
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _non_negative_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    value = int(raw) if raw else default
    if value < 0:
        raise ConfigurationError(f"{name} must be zero or greater")
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
