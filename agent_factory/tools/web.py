from __future__ import annotations

import html
import ipaddress
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_factory.factory.web_search import FactoryWebSearchService, WebSearchConfig
from agent_factory.specs import BuiltinCapabilitySpec


def execute_web_search(
    capability: BuiltinCapabilitySpec,
    arguments: dict[str, Any],
    *,
    env_file: str | Path | None = None,
    service: FactoryWebSearchService | None = None,
) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("web_search requires a non-empty query.")
    max_results = _bounded_int(arguments.get("max_results"), capability.max_results, 1, capability.max_results)
    search_service = service or FactoryWebSearchService.from_env(env_file or ".env")
    if not search_service.config.enabled:
        raise RuntimeError("web_search is not configured. Set AGENTFACTORY_WEB_SEARCH_PROVIDER and credentials.")
    report = search_service.search_many([query])
    if not report.ok:
        raise RuntimeError("; ".join(report.issues) or "web_search failed.")
    results = [
        result.model_dump(mode="json")
        for result in report.results
        if _url_allowed(result.url, capability.allowed_domains, capability.blocked_domains)
    ][:max_results]
    return {
        "status": "completed",
        "provider": report.provider,
        "query": query,
        "results": results,
        "result_count": len(results),
    }


def execute_browser_fetch(
    capability: BuiltinCapabilitySpec,
    arguments: dict[str, Any],
    *,
    env_file: str | Path | None = None,
) -> dict[str, Any]:
    url = str(arguments.get("url") or "").strip()
    if not _url_allowed(url, capability.allowed_domains, capability.blocked_domains):
        raise ValueError("browser_fetch URL is not allowed by capability policy.")
    config = WebSearchConfig.from_env(env_file or ".env")
    timeout = config.timeout_seconds
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    raw_text = response.text
    text = _html_to_text(raw_text) if "html" in content_type.lower() or "<html" in raw_text[:500].lower() else raw_text
    max_content_chars = _bounded_int(
        arguments.get("max_content_chars"),
        capability.max_content_chars,
        1,
        capability.max_content_chars,
    )
    text = text[:max_content_chars]
    return {
        "status": "completed",
        "url": str(response.url),
        "content_type": content_type,
        "title": _extract_title(raw_text),
        "text": text,
        "text_chars": len(text),
    }


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _url_allowed(url: str, allowed_domains: list[str], blocked_domains: list[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().strip(".")
    if not host or _is_private_host(host):
        return False
    if any(_domain_matches(host, domain) for domain in blocked_domains):
        return False
    if allowed_domains and not any(_domain_matches(host, domain) for domain in allowed_domains):
        return False
    return True


def _domain_matches(host: str, domain: str) -> bool:
    cleaned = domain.lower().strip().strip(".")
    return bool(cleaned) and (host == cleaned or host.endswith(f".{cleaned}"))


def _is_private_host(host: str) -> bool:
    if host in {"localhost"} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        if tag in {"p", "br", "div", "li", "section", "article", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(" ".join(parser.parts))).strip()


def _extract_title(value: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", value, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
