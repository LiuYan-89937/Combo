from __future__ import annotations

import importlib.util
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_context import EvidenceReport, ResourceNeed


class ResourceResolver(Protocol):
    resolver_id: str

    def supports(self, resource: ResourceNeed) -> bool:
        ...

    def resolve(self, resource: ResourceNeed) -> EvidenceReport:
        ...


class ResourceResolverRegistry:
    def __init__(self, resolvers: list[ResourceResolver] | None = None) -> None:
        self.resolvers = resolvers or [
            SQLiteResolver(),
            LocalPathResolver(),
            PythonPackageResolver(),
            SystemCommandResolver(),
            UrlDocumentationResolver(),
            CredentialConfigResolver(),
            HumanApprovalResolver(),
        ]

    def resolve(self, resource: ResourceNeed) -> EvidenceReport:
        for resolver in self.resolvers:
            if resolver.supports(resource):
                return resolver.resolve(resource)
        return EvidenceReport(
            evidence_id=f"{resource.resource_id}.unresolved",
            resource_id=resource.resource_id,
            source="resolver_registry",
            status="skipped",
            summary=f"No resolver registered for {resource.family}/{resource.kind}.",
            safe_for_prompt=True,
        )


class LocalPathResolver:
    resolver_id = "local_path"

    def supports(self, resource: ResourceNeed) -> bool:
        return resource.family in {"data", "storage", "system"} and bool(resource.location)

    def resolve(self, resource: ResourceNeed) -> EvidenceReport:
        path = Path(str(resource.location)).expanduser()
        return EvidenceReport(
            evidence_id=f"{resource.resource_id}.local_path",
            resource_id=resource.resource_id,
            source="local_path",
            status="passed" if path.exists() else "failed",
            summary=f"Path {'exists' if path.exists() else 'is missing'}: {path}",
            safe_for_prompt=True,
            details={
                "path": str(path),
                "exists": path.exists(),
                "is_file": path.is_file(),
                "is_dir": path.is_dir(),
            },
        )


class SQLiteResolver:
    resolver_id = "sqlite_schema"

    def supports(self, resource: ResourceNeed) -> bool:
        return resource.kind == "sqlite" and bool(resource.location)

    def resolve(self, resource: ResourceNeed) -> EvidenceReport:
        path = Path(str(resource.location)).expanduser()
        if not path.exists():
            return EvidenceReport(
                evidence_id=f"{resource.resource_id}.sqlite_schema",
                resource_id=resource.resource_id,
                source="sqlite_schema",
                status="failed",
                summary=f"SQLite file missing: {path}",
            )
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                tables = [
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    ).fetchall()
                ]
        except sqlite3.Error as error:
            return EvidenceReport(
                evidence_id=f"{resource.resource_id}.sqlite_schema",
                resource_id=resource.resource_id,
                source="sqlite_schema",
                status="failed",
                summary=f"SQLite schema probe failed: {error}",
            )
        return EvidenceReport(
            evidence_id=f"{resource.resource_id}.sqlite_schema",
            resource_id=resource.resource_id,
            source="sqlite_schema",
            status="passed",
            summary=f"SQLite schema available with {len(tables)} table(s).",
            details={"tables": tables},
        )


class PythonPackageResolver:
    resolver_id = "python_package"

    def supports(self, resource: ResourceNeed) -> bool:
        return resource.family == "runtime" and resource.kind == "python_package"

    def resolve(self, resource: ResourceNeed) -> EvidenceReport:
        name = str(resource.location or resource.resource_id)
        found = importlib.util.find_spec(name) is not None
        return EvidenceReport(
            evidence_id=f"{resource.resource_id}.python_package",
            resource_id=resource.resource_id,
            source="python_package",
            status="passed" if found else "failed",
            summary=f"Python package {'available' if found else 'missing'}: {name}",
        )


class SystemCommandResolver:
    resolver_id = "system_command"

    def supports(self, resource: ResourceNeed) -> bool:
        return resource.family == "system" and resource.kind == "command"

    def resolve(self, resource: ResourceNeed) -> EvidenceReport:
        command = str(resource.location or resource.resource_id)
        path = shutil.which(command)
        return EvidenceReport(
            evidence_id=f"{resource.resource_id}.system_command",
            resource_id=resource.resource_id,
            source="system_command",
            status="passed" if path else "failed",
            summary=f"System command {'available' if path else 'missing'}: {command}",
            details={"path": path},
        )


class UrlDocumentationResolver:
    resolver_id = "url_documentation"

    def __init__(self, *, fetcher: Callable[[str], str] | None = None, timeout_seconds: float = 10.0) -> None:
        self.fetcher = fetcher
        self.timeout_seconds = timeout_seconds

    def supports(self, resource: ResourceNeed) -> bool:
        location = str(resource.location or "")
        kind = resource.kind.lower()
        evidence = " ".join(resource.required_evidence).lower()
        return (
            resource.family == "service"
            and _is_http_url(location)
            and (
                kind in {"url_documentation", "web_documentation", "documentation", "api_docs", "url"}
                or "documentation" in evidence
                or "docs" in evidence
            )
        )

    def resolve(self, resource: ResourceNeed) -> EvidenceReport:
        url = str(resource.location or "")
        if not _is_http_url(url):
            return EvidenceReport(
                evidence_id=f"{resource.resource_id}.url_documentation",
                resource_id=resource.resource_id,
                source="url_documentation",
                status="failed",
                summary="Documentation URL is missing or not HTTP(S).",
            )
        try:
            body, metadata = self._fetch(url)
        except Exception as error:
            return EvidenceReport(
                evidence_id=f"{resource.resource_id}.url_documentation",
                resource_id=resource.resource_id,
                source="url_documentation",
                status="failed",
                summary=f"Documentation URL could not be fetched: {type(error).__name__}",
                details={"url": url},
            )
        title = _extract_title(body)
        return EvidenceReport(
            evidence_id=f"{resource.resource_id}.url_documentation",
            resource_id=resource.resource_id,
            source="url_documentation",
            status="passed",
            summary=(
                f"Documentation URL is reachable"
                f"{f' with title: {title}' if title else ''}."
            ),
            safe_for_prompt=True,
            details={
                "url": url,
                "title": title,
                "content_length": len(body),
                **metadata,
            },
        )

    def _fetch(self, url: str) -> tuple[str, dict[str, object]]:
        if self.fetcher is not None:
            return self.fetcher(url), {}
        response = httpx.get(url, follow_redirects=True, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.text, {
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "final_url": str(response.url),
        }


class CredentialConfigResolver:
    resolver_id = "credential_config"

    def supports(self, resource: ResourceNeed) -> bool:
        return resource.family == "credential"

    def resolve(self, resource: ResourceNeed) -> EvidenceReport:
        return EvidenceReport(
            evidence_id=f"{resource.resource_id}.credential_config",
            resource_id=resource.resource_id,
            source="credential_config",
            status="partial",
            summary="Credential value is not read; runtime config keys are declared only.",
            safe_for_prompt=True,
            details={"configuration_keys": resource.configuration_keys},
        )


class HumanApprovalResolver:
    resolver_id = "human_approval"

    def supports(self, resource: ResourceNeed) -> bool:
        return resource.family in {"human", "permission"}

    def resolve(self, resource: ResourceNeed) -> EvidenceReport:
        return EvidenceReport(
            evidence_id=f"{resource.resource_id}.human_approval",
            resource_id=resource.resource_id,
            source="human_approval",
            status="partial",
            summary="Human approval or permission is required at runtime.",
            safe_for_prompt=True,
        )


class ResourceResolutionSummary(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    reports: list[EvidenceReport] = Field(default_factory=list)


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    return title[:160] if title else None
