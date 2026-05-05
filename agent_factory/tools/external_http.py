from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML

from agent_factory.factory_runtime.redaction import redact_secrets


class ExternalConfigContext(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, arbitrary_types_allowed=True)

    path: str
    exists: bool = False
    status: str = "missing"
    values: dict[str, str] = Field(default_factory=dict)
    resolved_values: dict[str, str] = Field(default_factory=dict)
    required_keys: list[str] = Field(default_factory=list)
    secret_keys: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    missing_required_keys: list[str] = Field(default_factory=list)

    def safe_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        for key in self.secret_keys:
            if key in data["resolved_values"]:
                data["resolved_values"][key] = "[REDACTED]"
        return redact_secrets(data)


class ExternalHttpClient:
    """Small runtime HTTP guard for generated read-only external tools."""

    def __init__(
        self,
        config: ExternalConfigContext,
        *,
        timeout_seconds: int = 15,
        max_response_chars: int = 20000,
        allowed_methods: set[str] | None = None,
    ) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.max_response_chars = max_response_chars
        self.allowed_methods = {method.upper() for method in (allowed_methods or {"GET", "POST"})}
        self.allowed_hosts = _allowed_hosts(config)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        method = method.upper().strip()
        if method not in self.allowed_methods:
            return {"status": "failed", "error": f"HTTP method is not allowed: {method}"}
        if self.config.missing_required_keys:
            return {
                "status": "needs_configuration",
                "configuration_file": "external_config.yaml",
                "missing_fields": self.config.missing_required_keys,
            }
        target = _absolute_url(url, self.config.resolved_values)
        host = urlparse(target).netloc.lower()
        if self.allowed_hosts and host not in self.allowed_hosts:
            return {"status": "failed", "error": f"HTTP host is not allowed: {host}"}
        try:
            response = httpx.request(
                method,
                target,
                headers=headers,
                params=params,
                json=json_data,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        except Exception as error:
            return {"status": "failed", "error": f"{type(error).__name__}: {error}"}
        body = response.text[: self.max_response_chars]
        parsed_json: Any | None = None
        try:
            parsed_json = response.json()
        except Exception:
            parsed_json = None
        return redact_secrets(
            {
                "status": "completed",
                "http_status": response.status_code,
                "url": target,
                "json": parsed_json,
                "text": None if parsed_json is not None else body,
            }
        )


def load_external_config_context(
    package_path: str | Path,
    *,
    env_file: str | Path | None = None,
) -> ExternalConfigContext:
    package_root = Path(package_path)
    path = package_root / "external_config.yaml"
    data = _load_yaml_mapping(path)
    values = _string_map(data.get("values") if isinstance(data, dict) else {})
    required_keys = _string_list(data.get("required_keys") if isinstance(data, dict) else [])
    secret_keys = _string_list(data.get("secret_keys") if isinstance(data, dict) else [])
    source_urls = _string_list(data.get("source_urls") if isinstance(data, dict) else [])
    env_values = _load_env_values(env_file)
    resolved = dict(values)
    for key in list(values.keys()) + required_keys:
        env_value = env_values.get(key) or os.environ.get(key)
        if env_value:
            resolved[key] = env_value
    missing = [key for key in required_keys if not str(resolved.get(key) or "").strip()]
    status = str(data.get("status") or "missing") if isinstance(data, dict) else "missing"
    if path.exists() and missing:
        status = "needs_user_configuration"
    elif path.exists():
        status = "ready"
    return ExternalConfigContext(
        path=str(path),
        exists=path.exists(),
        status=status,
        values=values,
        resolved_values=resolved,
        required_keys=required_keys,
        secret_keys=secret_keys,
        source_urls=source_urls,
        missing_required_keys=missing,
    )


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _load_env_values(env_file: str | Path | None) -> dict[str, str]:
    if env_file is None:
        env_path = Path(".env")
    else:
        env_path = Path(env_file)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _allowed_hosts(config: ExternalConfigContext) -> set[str]:
    hosts: set[str] = set()
    for url in config.source_urls:
        host = urlparse(url).netloc.lower()
        if host:
            hosts.add(host)
    for key, value in config.resolved_values.items():
        if not any(marker in key for marker in ("HOST", "BASE_URL", "ENDPOINT", "URL")):
            continue
        host = urlparse(value).netloc.lower()
        if host:
            hosts.add(host)
    return hosts


def _absolute_url(url: str, values: dict[str, str]) -> str:
    if urlparse(url).scheme:
        return url
    host = ""
    for key, value in values.items():
        if key.endswith(("_API_HOST", "_BASE_URL", "_HOST")) and value:
            host = value.rstrip("/")
            break
    if not host:
        return url
    return f"{host}/{url.lstrip('/')}"
