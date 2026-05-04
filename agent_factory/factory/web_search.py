from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from agent_factory.model.config import _blank_to_none, _parse_env_file, _to_int


WebSearchProviderName = Literal["disabled", "tavily"]
WebSearchDepth = Literal["basic", "advanced", "fast", "ultra-fast"]
WebSearchTopic = Literal["general", "news", "finance"]


class WebSearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    provider: WebSearchProviderName = "disabled"
    api_key: SecretStr | None = None
    base_url: str | None = None
    max_results: int = Field(default=5, ge=1)
    timeout_seconds: int = Field(default=20, ge=1)
    search_depth: WebSearchDepth = "basic"
    topic: WebSearchTopic = "general"
    include_answer: bool = False
    include_raw_content: Literal[False, "markdown", "text"] = False
    include_images: bool = False
    include_favicon: bool = False
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    country: str | None = None
    agent_web_inheritance: Literal["explicit", "never", "ask"] = "explicit"

    @classmethod
    def from_env(
        cls,
        env_file: str | Path = ".env",
        environ: Mapping[str, str] | None = None,
    ) -> "WebSearchConfig":
        file_values = _parse_env_file(Path(env_file))
        runtime_values = dict(os.environ if environ is None else environ)
        values = {**file_values, **runtime_values}
        api_key = _blank_to_none(values.get("AGENTFACTORY_WEB_SEARCH_API_KEY"))
        return cls(
            provider=_blank_to_none(values.get("AGENTFACTORY_WEB_SEARCH_PROVIDER")) or "disabled",
            api_key=SecretStr(api_key) if api_key else None,
            base_url=_blank_to_none(values.get("AGENTFACTORY_WEB_SEARCH_BASE_URL")),
            max_results=_to_int(values.get("AGENTFACTORY_WEB_SEARCH_MAX_RESULTS"), 5),
            timeout_seconds=_to_int(values.get("AGENTFACTORY_WEB_SEARCH_TIMEOUT_SECONDS"), 20),
            search_depth=_blank_to_none(values.get("AGENTFACTORY_WEB_SEARCH_SEARCH_DEPTH")) or "basic",
            topic=_blank_to_none(values.get("AGENTFACTORY_WEB_SEARCH_TOPIC")) or "general",
            include_answer=_to_bool(values.get("AGENTFACTORY_WEB_SEARCH_INCLUDE_ANSWER"), False),
            include_raw_content=_raw_content_value(
                values.get("AGENTFACTORY_WEB_SEARCH_INCLUDE_RAW_CONTENT")
            ),
            include_images=_to_bool(values.get("AGENTFACTORY_WEB_SEARCH_INCLUDE_IMAGES"), False),
            include_favicon=_to_bool(values.get("AGENTFACTORY_WEB_SEARCH_INCLUDE_FAVICON"), False),
            include_domains=_csv_values(values.get("AGENTFACTORY_WEB_SEARCH_INCLUDE_DOMAINS")),
            exclude_domains=_csv_values(values.get("AGENTFACTORY_WEB_SEARCH_EXCLUDE_DOMAINS")),
            country=_blank_to_none(values.get("AGENTFACTORY_WEB_SEARCH_COUNTRY")),
            agent_web_inheritance=_blank_to_none(values.get("AGENTFACTORY_AGENT_WEB_INHERITANCE")) or "explicit",
        )

    @property
    def enabled(self) -> bool:
        return self.provider != "disabled"

    def safe_summary(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "api_key": "**********" if self.api_key else None,
            "base_url": self.base_url,
            "max_results": self.max_results,
            "timeout_seconds": self.timeout_seconds,
            "search_depth": self.search_depth,
            "topic": self.topic,
            "include_answer": self.include_answer,
            "include_raw_content": self.include_raw_content,
            "include_images": self.include_images,
            "include_favicon": self.include_favicon,
            "include_domains": self.include_domains,
            "exclude_domains": self.exclude_domains,
            "country": self.country,
            "agent_web_inheritance": self.agent_web_inheritance,
        }


class WebSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    query: str
    max_results: int | None = None
    search_depth: WebSearchDepth | None = None
    topic: WebSearchTopic | None = None
    include_answer: bool | None = None
    include_raw_content: Literal[False, "markdown", "text"] | None = None
    include_images: bool | None = None
    include_favicon: bool | None = None
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    country: str | None = None


class WebSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    title: str
    url: str
    snippet: str
    source: str | None = None
    raw_content: str | None = None
    score: float | None = None


class WebSearchReport(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    status: Literal["passed", "failed", "skipped"] = "skipped"
    provider: str = "disabled"
    queries: list[str] = Field(default_factory=list)
    results: list[WebSearchResult] = Field(default_factory=list)
    answers: list[str] = Field(default_factory=list)
    usage: dict[str, object] = Field(default_factory=dict)
    request_ids: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "passed"


class WebSearchProvider:
    provider = "disabled"

    def search(self, request: WebSearchRequest) -> WebSearchReport:
        return WebSearchReport(
            status="skipped",
            provider=self.provider,
            queries=[request.query],
            issues=["web_search_disabled"],
        )


class DisabledWebSearchProvider(WebSearchProvider):
    provider = "disabled"


class TavilyWebSearchProvider(WebSearchProvider):
    provider = "tavily"

    def __init__(self, config: WebSearchConfig) -> None:
        self.config = config

    def search(self, request: WebSearchRequest) -> WebSearchReport:
        if self.config.api_key is None:
            raise RuntimeError("AGENTFACTORY_WEB_SEARCH_API_KEY is required for tavily.")
        url = _join_url(self.config.base_url or "https://api.tavily.com", "search")
        payload = _tavily_search_payload(self.config, request)
        response = httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.config.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        raw_results = data.get("results") if isinstance(data, dict) else []
        results: list[WebSearchResult] = []
        if isinstance(raw_results, list):
            for item in raw_results[: payload["max_results"]]:
                if not isinstance(item, dict):
                    continue
                results.append(
                    WebSearchResult(
                        title=str(item.get("title") or "Untitled"),
                        url=str(item.get("url") or ""),
                        snippet=str(item.get("content") or item.get("snippet") or ""),
                        source="tavily",
                        raw_content=(
                            str(raw)
                            if (raw := item.get("raw_content")) is not None
                            else None
                        ),
                        score=(
                            float(score)
                            if isinstance((score := item.get("score")), (int, float))
                            else None
                        ),
                    )
                )
        clean_results = [result for result in results if result.url]
        return WebSearchReport(
            status="passed" if clean_results else "failed",
            provider=self.provider,
            queries=[request.query],
            results=clean_results,
            answers=[str(data.get("answer"))] if isinstance(data, dict) and data.get("answer") else [],
            usage=data.get("usage") if isinstance(data, dict) and isinstance(data.get("usage"), dict) else {},
            request_ids=[str(data.get("request_id"))] if isinstance(data, dict) and data.get("request_id") else [],
            issues=[] if clean_results else ["no_search_results"],
        )


class FactoryWebSearchService:
    def __init__(
        self,
        config: WebSearchConfig | None = None,
        provider: WebSearchProvider | None = None,
    ) -> None:
        self.config = config or WebSearchConfig()
        self.provider = provider or _provider_for(self.config)

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "FactoryWebSearchService":
        return cls(WebSearchConfig.from_env(env_file))

    def search_many(self, queries: list[str]) -> WebSearchReport:
        clean_queries = [query.strip() for query in queries if query.strip()]
        if not clean_queries or not self.config.enabled:
            return WebSearchReport(
                status="skipped",
                provider=self.config.provider,
                queries=clean_queries,
                issues=[] if not clean_queries else ["web_search_disabled"],
            )
        results: list[WebSearchResult] = []
        answers: list[str] = []
        usage: dict[str, object] = {}
        request_ids: list[str] = []
        issues: list[str] = []
        for query in clean_queries:
            try:
                report = self.provider.search(_request_from_config(query, self.config))
                results.extend(report.results)
                answers.extend(report.answers)
                request_ids.extend(report.request_ids)
                usage.update(report.usage)
                issues.extend(report.issues)
            except Exception as error:
                issues.append(f"{query}: {type(error).__name__}: {error}")
        return WebSearchReport(
            status="passed" if results and not issues else "failed",
            provider=self.config.provider,
            queries=clean_queries,
            results=results,
            answers=answers,
            usage=usage,
            request_ids=request_ids,
            issues=issues,
        )


def _provider_for(config: WebSearchConfig) -> WebSearchProvider:
    if config.provider == "tavily":
        return TavilyWebSearchProvider(config)
    return DisabledWebSearchProvider()


def _request_from_config(query: str, config: WebSearchConfig) -> WebSearchRequest:
    return WebSearchRequest(
        query=query,
        max_results=config.max_results,
        search_depth=config.search_depth,
        topic=config.topic,
        include_answer=config.include_answer,
        include_raw_content=config.include_raw_content,
        include_images=config.include_images,
        include_favicon=config.include_favicon,
        include_domains=config.include_domains,
        exclude_domains=config.exclude_domains,
        country=config.country,
    )


def _tavily_search_payload(config: WebSearchConfig, request: WebSearchRequest) -> dict[str, object]:
    payload: dict[str, object] = {
        "query": request.query,
        "max_results": request.max_results or config.max_results,
        "search_depth": request.search_depth or config.search_depth,
        "topic": request.topic or config.topic,
        "include_answer": config.include_answer
        if request.include_answer is None
        else request.include_answer,
        "include_raw_content": config.include_raw_content
        if request.include_raw_content is None
        else request.include_raw_content,
        "include_images": config.include_images
        if request.include_images is None
        else request.include_images,
        "include_favicon": config.include_favicon
        if request.include_favicon is None
        else request.include_favicon,
    }
    include_domains = request.include_domains or config.include_domains
    exclude_domains = request.exclude_domains or config.exclude_domains
    country = request.country or config.country
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains
    if country:
        payload["country"] = country
    return payload


def _join_url(base_url: str, endpoint: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith(f"/{endpoint}"):
        return stripped
    return f"{stripped}/{endpoint}"


def _to_bool(value: str | None, default: bool) -> bool:
    normalized = _blank_to_none(value)
    if normalized is None:
        return default
    return normalized.lower() in {"1", "true", "yes", "on"}


def _csv_values(value: str | None) -> list[str]:
    normalized = _blank_to_none(value)
    if normalized is None:
        return []
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _raw_content_value(value: str | None) -> Literal[False, "markdown", "text"]:
    normalized = (_blank_to_none(value) or "").lower()
    if normalized in {"1", "true", "yes", "on", "markdown"}:
        return "markdown"
    if normalized == "text":
        return "text"
    return False
