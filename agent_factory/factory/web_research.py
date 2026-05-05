from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.factory_context import FactoryContextEnvelope, apply_context_envelope
from agent_factory.factory.web_search import FactoryWebSearchService, WebSearchReport
from agent_factory.model import ModelService
from agent_factory.model.messages import MessageBuilder


ResearchSourceTrust = Literal["official", "marketplace", "vendor_article", "third_party", "unknown"]
ResearchDocumentType = Literal["html", "pdf", "openapi", "markdown", "json", "text"]
ResearchStatus = Literal["resolved", "partially_resolved", "unresolved", "skipped"]
BrowserFetchMode = Literal["auto", "disabled", "required"]
ResearchCompletenessStatus = Literal[
    "sufficient",
    "needs_more_url",
    "needs_config_values",
    "unsupported",
]


class ResearchOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    description: str = ""
    evidence_needed: list[str] = Field(default_factory=list)
    query_hints: list[str] = Field(default_factory=list)
    tool_ref: str | None = None


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    service_id: str
    service_name: str
    purpose: str = ""
    queries: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)
    operations: list[ResearchOperation] = Field(default_factory=list)
    required_facts: list[str] = Field(
        default_factory=lambda: [
            "official_documentation_url",
            "endpoint",
            "http_method",
            "authentication",
            "request_parameters",
            "sample_response",
        ]
    )

    @property
    def requires_research(self) -> bool:
        return bool(self.source_urls or self.operations)


class SearchCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    title: str = ""
    url: str
    snippet: str = ""
    provider: str = "manual_url"
    query: str | None = None
    score: float | None = None
    trust: ResearchSourceTrust = "unknown"


class FetchedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    url: str
    title: str = ""
    content: str = ""
    document_type: ResearchDocumentType = "text"
    status: Literal["fetched", "failed", "skipped"] = "skipped"
    fetcher: Literal["static", "browser"] = "static"
    trust: ResearchSourceTrust = "unknown"
    content_length: int = 0
    issues: list[str] = Field(default_factory=list)


class CleanDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    url: str
    title: str = ""
    document_type: ResearchDocumentType = "text"
    trust: ResearchSourceTrust = "unknown"
    text: str = ""
    tables: list[str] = Field(default_factory=list)
    code_blocks: list[str] = Field(default_factory=list)
    headings: list[str] = Field(default_factory=list)
    score: float = 0.0

    @property
    def has_signal(self) -> bool:
        return bool(self.text.strip() or self.tables or self.code_blocks)


class EvidenceAuth(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: str | None = None
    header: str | None = None
    format: str | None = None
    placement: str | None = None
    evidence_url: str | None = None


class EvidenceParam(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    key: str
    required: bool = True
    location: str | None = None
    description: str | None = None
    example: str | None = None


class EvidenceOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    description: str = ""
    method: str | None = None
    endpoint: str | None = None
    params: list[EvidenceParam] = Field(default_factory=list)
    sample_request: str | None = None
    sample_response: str | None = None
    error_codes: list[str] = Field(default_factory=list)
    evidence_url: str | None = None


class RecommendedConfigField(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    key: str
    label: str
    required: bool = True
    secret: bool = False
    value: str = ""
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    notes: str = ""


class ExtractedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    service_name: str | None = None
    auth: EvidenceAuth | None = None
    operations: list[EvidenceOperation] = Field(default_factory=list)
    recommended_config_fields: list[RecommendedConfigField] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"


class AdvisorOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    description: str = ""
    method: str | None = None
    endpoint: str | None = None
    params: list[dict[str, Any]] = Field(default_factory=list)
    sample_request: str | None = None
    sample_response: str | None = None
    error_shape: str | None = None


class AdvisorConfigField(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    key: str
    label: str = ""
    required: bool = True
    secret: bool = False
    value: str = ""
    notes: str = ""


class ExternalAdvisorPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    service_name: str | None = None
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    summary: str = ""
    auth_type: str | None = None
    auth_notes: str | None = None
    operations: list[AdvisorOperation] = Field(default_factory=list)
    config_fields: list[AdvisorConfigField] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class ResearchSource(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    url: str
    title: str = ""
    type: ResearchDocumentType = "text"
    trusted_level: ResearchSourceTrust = "unknown"


class ResearchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    kind: Literal["ResearchBrief"] = "ResearchBrief"
    service_id: str
    service_name: str
    status: ResearchStatus = "unresolved"
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    summary: str = ""
    sources: list[ResearchSource] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    recommended_config_fields: list[RecommendedConfigField] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in {"resolved", "partially_resolved"}


class ResearchBriefBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    status: Literal["passed", "failed", "skipped"] = "skipped"
    plan: ResearchPlan | None = None
    raw_search_report: WebSearchReport
    candidates: list[SearchCandidate] = Field(default_factory=list)
    fetched_documents: list[FetchedDocument] = Field(default_factory=list)
    clean_documents: list[CleanDocument] = Field(default_factory=list)
    brief: ResearchBrief
    issues: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "passed" and self.brief.ok


class ResearchCompletenessOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    operation_id: str
    endpoint: bool = False
    method: bool = False
    auth: bool = False
    required_params: bool = False
    response_shape: bool = False
    test_fixture_strategy: bool = False
    missing_facts: list[str] = Field(default_factory=list)


class ResearchCompletenessReport(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    kind: Literal["ResearchCompletenessReport"] = "ResearchCompletenessReport"
    status: ResearchCompletenessStatus
    service_id: str = ""
    service_name: str = ""
    summary: str = ""
    operations: list[ResearchCompletenessOperation] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    missing_config_keys: list[str] = Field(default_factory=list)
    missing_urls: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)

    @property
    def ok_for_generation(self) -> bool:
        return self.status in {"sufficient", "needs_config_values"}


class WebSearchPipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    fetch_timeout_seconds: int = Field(default=20, ge=1)
    max_document_chars: int = Field(default=60000, ge=1000)
    browser_fetch: BrowserFetchMode = "auto"
    max_related_pages: int = Field(default=5, ge=0)
    max_link_depth: int = Field(default=1, ge=0)


class ResearchPlanBuilder:
    def build(
        self,
        *,
        requirement: str,
        tool_precondition_report: dict[str, Any] | None,
    ) -> ResearchPlan:
        report = tool_precondition_report if isinstance(tool_precondition_report, dict) else {}
        text = f"{requirement}\n{json.dumps(report, ensure_ascii=False)}"
        service_name = _guess_service_name(text)
        operations = _operations_from_report(report)
        urls = _extract_urls(text)
        query_hints = _queries_from_report(report)
        return ResearchPlan(
            service_id=_safe_id(service_name),
            service_name=service_name,
            purpose=requirement[:500],
            queries=_rewrite_learning_queries(
                service_name=service_name,
                requirement=requirement,
                operations=operations,
                query_hints=query_hints,
            )[:6],
            source_urls=_unique(urls)[:8],
            preferred_domains=_preferred_domains(urls),
            operations=operations,
        )


class WebSearchPipeline:
    """Controlled external documentation extractor.

    The Factory no longer searches broadly during production. If an external
    service is needed and the user has not supplied a URL, this pipeline returns
    an unresolved brief so the CLI can ask for the official URL. Once the user
    supplies a URL, the pipeline fetches that page plus a small number of
    same-host related documentation pages/tabs.
    """

    def __init__(
        self,
        *,
        search_service: FactoryWebSearchService,
        model_service: ModelService | None = None,
        config: WebSearchPipelineConfig | None = None,
    ) -> None:
        self.search_service = search_service
        self.model_service = model_service
        search_config = search_service.config
        self.config = config or WebSearchPipelineConfig(
            fetch_timeout_seconds=search_config.research_fetch_timeout_seconds,
            max_document_chars=search_config.research_max_document_chars,
            browser_fetch=search_config.research_browser_fetch,
            max_related_pages=search_config.research_max_related_pages,
            max_link_depth=search_config.research_max_link_depth,
        )

    def run(
        self,
        plan: ResearchPlan,
        *,
        context_envelope: FactoryContextEnvelope | None = None,
    ) -> ResearchBriefBundle:
        raw_report = WebSearchReport(status="skipped", provider="manual_url")
        if not plan.requires_research:
            brief = _empty_brief(plan, status="skipped", issue="no_research_required")
            return ResearchBriefBundle(raw_search_report=raw_report, brief=brief, plan=plan)

        if not plan.source_urls and not self.search_service.config.enabled:
            issue = "external_resource_url_required"
            brief = _empty_brief(plan, status="unresolved", issue=issue)
            raw_report = WebSearchReport(
                status="failed",
                provider="manual_url",
                queries=plan.queries,
                issues=[issue],
            )
            return ResearchBriefBundle(
                status="failed",
                plan=plan,
                raw_search_report=raw_report,
                brief=brief,
                issues=[issue],
            )

        initial_candidates = _manual_candidates(plan)
        if not initial_candidates:
            raw_report = self.search_service.search_many(plan.queries)
            initial_candidates = _candidates_from_search_report(raw_report, plan)
            if not initial_candidates:
                issue = "external_search_no_usable_candidates"
                brief = _empty_brief(plan, status="unresolved", issue=issue)
                return ResearchBriefBundle(
                    status="failed",
                    plan=plan,
                    raw_search_report=raw_report,
                    brief=brief,
                    issues=_unique([issue, *raw_report.issues]),
                )

        candidates, fetched = self._fetch_with_related_pages(initial_candidates, plan)
        cleaned = _rank_documents(
            [_clean_document(doc, plan) for doc in fetched if doc.status == "fetched"],
            plan,
        )
        evidence = self._extract_evidence(
            plan,
            cleaned,
            context_envelope=context_envelope,
        )
        brief = _build_brief(plan, evidence, cleaned)
        issues: list[str] = []
        for doc in fetched:
            issues.extend(f"{doc.url}: {issue}" for issue in doc.issues)
        issues.extend(evidence.issues)
        status = "passed" if brief.ok else "failed"
        return ResearchBriefBundle(
            status=status,
            plan=plan,
            raw_search_report=raw_report,
            candidates=candidates,
            fetched_documents=fetched,
            clean_documents=cleaned,
            brief=brief,
            issues=_unique(issues),
        )

    def _fetch_with_related_pages(
        self,
        initial_candidates: list[SearchCandidate],
        plan: ResearchPlan,
    ) -> tuple[list[SearchCandidate], list[FetchedDocument]]:
        candidates: list[SearchCandidate] = []
        fetched: list[FetchedDocument] = []
        seen = {_canonical_url(candidate.url) for candidate in initial_candidates}
        queue: list[tuple[SearchCandidate, int]] = [(candidate, 0) for candidate in initial_candidates]
        max_total = len(initial_candidates) + self.config.max_related_pages
        while queue and len(fetched) < max_total:
            candidate, depth = queue.pop(0)
            candidates.append(candidate)
            document = self._fetch(candidate)
            fetched.append(document)
            if depth >= self.config.max_link_depth:
                continue
            remaining = max_total - len(fetched) - len(queue)
            if remaining <= 0:
                continue
            related = _related_candidates_from_document(
                document,
                plan,
                seen_urls=seen,
                limit=remaining,
            )
            for related_candidate in related:
                key = _canonical_url(related_candidate.url)
                if key in seen:
                    continue
                seen.add(key)
                queue.append((related_candidate, depth + 1))
        return candidates, fetched

    def _fetch(self, candidate: SearchCandidate) -> FetchedDocument:
        static = _static_fetch(
            candidate,
            timeout_seconds=self.config.fetch_timeout_seconds,
            max_chars=self.config.max_document_chars,
        )
        if self.config.browser_fetch == "disabled":
            return static
        should_browser = (
            self.config.browser_fetch == "required"
            or static.status != "fetched"
            or _looks_like_dynamic_shell(static.content)
        )
        if not should_browser:
            return static
        browser = _browser_fetch(
            candidate,
            timeout_seconds=self.config.fetch_timeout_seconds,
            max_chars=self.config.max_document_chars,
        )
        if browser.status == "fetched" and (
            self.config.browser_fetch == "required"
            or _cleaned_signal_chars(browser) > _cleaned_signal_chars(static)
        ):
            return browser
        if self.config.browser_fetch == "required":
            return browser
        if browser.issues:
            static.issues.extend(f"browser_fetch: {issue}" for issue in browser.issues)
        return static

    def _extract_evidence(
        self,
        plan: ResearchPlan,
        documents: list[CleanDocument],
        *,
        context_envelope: FactoryContextEnvelope | None = None,
    ) -> ExtractedEvidence:
        openapi_evidence = _extract_openapi_evidence(plan, documents)
        if openapi_evidence is not None:
            return openapi_evidence
        if self.model_service is not None and documents:
            model_evidence = _extract_evidence_with_model(
                self.model_service,
                plan,
                documents,
                context_envelope=context_envelope,
            )
            if model_evidence is not None:
                return _validate_and_enrich_evidence(model_evidence, plan, documents)
        return _extract_evidence_by_rules(plan, documents)


def build_llm_advisor_research(
    plan: ResearchPlan,
    *,
    model_service: ModelService | None = None,
    context_envelope: FactoryContextEnvelope | None = None,
) -> tuple[ResearchBriefBundle, ResearchCompletenessReport]:
    """Build external-resource context without WebSearch.

    This is a temporary production mode for evaluating whether the configured
    LLM can complete external-resource setup from requirement semantics alone.
    The output is deliberately marked as unverified model advice.
    """

    advisor_issues: list[str] = []
    evidence = _external_advice_with_model(
        plan,
        model_service=model_service,
        context_envelope=context_envelope,
        issues=advisor_issues,
    )
    if evidence is None:
        evidence = _external_advice_by_requirement(plan)
        advisor_issues.append("llm_advisor_fallback_used")
    brief = _build_advisor_brief(plan, evidence)
    raw_report = WebSearchReport(
        status="skipped",
        provider="llm_advisor",
        queries=plan.queries,
        issues=["web_search_disabled_llm_advisor_only", *advisor_issues],
    )
    bundle = ResearchBriefBundle(
        status="skipped",
        plan=plan,
        raw_search_report=raw_report,
        brief=brief,
        issues=["facts_are_unverified_model_advice", *advisor_issues],
    )
    completeness = _advisor_completeness(plan, brief)
    return bundle, completeness


def _external_advice_with_model(
    plan: ResearchPlan,
    *,
    model_service: ModelService | None,
    context_envelope: FactoryContextEnvelope | None,
    issues: list[str],
) -> ExtractedEvidence | None:
    if model_service is None or getattr(model_service.router.config, "provider", None) == "fake":
        issues.append("llm_advisor_model_unavailable")
        return None
    request = apply_context_envelope(
        MessageBuilder.start()
        .system(
            "You are AgentFactory's external resource advisor. WebSearch is disabled. "
            "Use only your built-in knowledge and the user's requirement to propose what the Agent probably needs. "
            "Return exactly one JSON object matching ExternalAdvisorPlan. "
            "Mark uncertain fields in unresolved_fields. Never include real secret values. "
            "Every fact is unverified unless the user later confirms it. "
            "Prefer concrete env-like configuration keys and likely API operations when you know them."
        )
        .user(
            "Build a candidate external resource plan for this Agent. "
            "Focus on what the user must prepare, runtime configuration keys, likely operations, "
            "credentials, setup steps, and any uncertainty.\n\n"
            f"Research plan:\n{plan.model_dump_json(indent=2)}\n\n"
            "Output guidance:\n"
            "- config_fields should be env-like keys the user can fill later.\n"
            "- If a value might be secret, set secret=true and leave value=''.\n"
            "- If this is an API, include likely endpoint/path/method/params when your built-in knowledge is strong enough; otherwise put them in unresolved_fields.\n"
            "- Do not invent a generic CREDENTIAL field. Only output config keys you believe are meaningful for this resource.\n"
            "- If this is not an API, represent the needed web/resource facts in operations/params/unresolved_fields as best as possible."
        )
        .request(
            response_format="json_schema",
            json_schema=ExternalAdvisorPlan.model_json_schema(),
            json_schema_name="ExternalAdvisorPlan",
            metadata={"phase": "external_resource_llm_advisor", "model_role": "task"},
        ),
        context_envelope,
    )
    try:
        result = asyncio.run(
            model_service.generate_structured(
                request,
                schema=ExternalAdvisorPlan.model_json_schema(),
                schema_name="ExternalAdvisorPlan",
            )
        )
    except Exception as exc:
        issues.append(f"llm_advisor_exception:{type(exc).__name__}")
        return None
    if result.error:
        issues.append(f"llm_advisor_error:{result.error.type}")
        return None
    if not isinstance(result.data, dict):
        issues.append("llm_advisor_non_object_output")
        return None
    try:
        return _advisor_plan_to_evidence(plan, _coerce_external_advisor_plan(result.data))
    except Exception as exc:
        issues.append(f"llm_advisor_validation_error:{type(exc).__name__}")
        return None


def _coerce_external_advisor_plan(data: dict[str, Any]) -> ExternalAdvisorPlan:
    operations_data = data.get("operations")
    if not operations_data and isinstance(data.get("facts"), dict):
        operations_data = data["facts"].get("operations")
    operations: list[AdvisorOperation] = []
    for index, raw_operation in enumerate(_as_list(operations_data)):
        if isinstance(raw_operation, str):
            operations.append(AdvisorOperation(id=f"operation_{index + 1}", description=raw_operation))
            continue
        if not isinstance(raw_operation, dict):
            continue
        operation_id = raw_operation.get("id") or raw_operation.get("operation_id") or raw_operation.get("tool_ref")
        params = raw_operation.get("params") or raw_operation.get("parameters") or raw_operation.get("required_params") or []
        operations.append(
            AdvisorOperation(
                id=str(operation_id or f"operation_{index + 1}"),
                description=str(raw_operation.get("description") or raw_operation.get("summary") or ""),
                method=_optional_str(raw_operation.get("method") or raw_operation.get("http_method")),
                endpoint=_optional_str(raw_operation.get("endpoint") or raw_operation.get("path") or raw_operation.get("url")),
                params=[_coerce_param(param) for param in _as_list(params)],
                sample_request=_optional_str(raw_operation.get("sample_request") or raw_operation.get("request_example")),
                sample_response=_optional_str(raw_operation.get("sample_response") or raw_operation.get("response_example")),
                error_shape=_optional_str(raw_operation.get("error_shape") or raw_operation.get("error_response")),
            )
        )
    fields_data = (
        data.get("config_fields")
        or data.get("recommended_config_fields")
        or data.get("required_config")
        or data.get("env_keys")
        or []
    )
    config_fields: list[AdvisorConfigField] = []
    for raw_field in _as_list(fields_data):
        if isinstance(raw_field, str):
            config_fields.append(AdvisorConfigField(key=raw_field, label=raw_field))
            continue
        if not isinstance(raw_field, dict):
            continue
        key = raw_field.get("key") or raw_field.get("name") or raw_field.get("env_key")
        if not key:
            continue
        config_fields.append(
            AdvisorConfigField(
                key=str(key),
                label=str(raw_field.get("label") or raw_field.get("description") or key),
                required=bool(raw_field.get("required", True)),
                secret=bool(raw_field.get("secret", raw_field.get("is_secret", False))),
                value="" if raw_field.get("secret") else str(raw_field.get("value") or raw_field.get("default") or ""),
                notes=str(raw_field.get("notes") or raw_field.get("description") or ""),
            )
        )
    return ExternalAdvisorPlan(
        service_name=_optional_str(data.get("service_name") or data.get("service")),
        confidence=_coerce_confidence(data.get("confidence")),
        summary=str(data.get("summary") or ""),
        auth_type=_optional_str(data.get("auth_type") or _dict_get(data.get("auth"), "type")),
        auth_notes=_optional_str(data.get("auth_notes") or _dict_get(data.get("auth"), "format") or _dict_get(data.get("auth"), "notes")),
        operations=operations,
        config_fields=config_fields,
        unresolved_fields=[str(item) for item in _as_list(data.get("unresolved_fields"))],
        issues=[str(item) for item in _as_list(data.get("issues"))],
    )


def _advisor_plan_to_evidence(plan: ResearchPlan, advisor: ExternalAdvisorPlan) -> ExtractedEvidence:
    auth = None
    if advisor.auth_type or advisor.auth_notes:
        auth = EvidenceAuth(
            type=advisor.auth_type,
            header=None,
            format=advisor.auth_notes,
            placement=None,
        )
    operations: list[EvidenceOperation] = []
    for operation in advisor.operations:
        params = [
            EvidenceParam(
                key=str(param.get("key") or param.get("name") or param.get("field") or "input"),
                required=bool(param.get("required", True)),
                location=param.get("location"),
                description=param.get("description") or param.get("notes"),
                example=None if param.get("example") is None else str(param.get("example")),
            )
            for param in operation.params
        ]
        operations.append(
            EvidenceOperation(
                id=operation.id,
                description=operation.description,
                method=operation.method,
                endpoint=operation.endpoint,
                params=params,
                sample_request=operation.sample_request,
                sample_response=operation.sample_response or operation.error_shape,
            )
        )
    if not operations:
        operations = [
            EvidenceOperation(
                id=operation.id,
                description=operation.description or plan.purpose,
                params=[EvidenceParam(key="input", required=True, description="User-provided runtime input")],
            )
            for operation in plan.operations
        ]
    fields: list[RecommendedConfigField] = []
    seen_keys: set[str] = set()
    for field in advisor.config_fields:
        key = _normalize_env_key(field.key)
        if not key:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        fields.append(
            RecommendedConfigField(
                key=key,
                label=field.label or key,
                required=field.required,
                secret=field.secret,
                value="" if field.secret else str(field.value or ""),
                confidence=advisor.confidence,
                notes=field.notes,
            )
        )
    return ExtractedEvidence(
        service_name=advisor.service_name or plan.service_name,
        auth=auth,
        operations=operations,
        recommended_config_fields=fields,
        unresolved_fields=advisor.unresolved_fields,
        issues=["facts_are_unverified_model_advice", *advisor.issues],
        confidence=advisor.confidence,
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _dict_get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_param(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"key": value, "required": True}
    if isinstance(value, dict):
        return value
    return {"key": "input", "required": True, "description": str(value)}


def _coerce_confidence(value: Any) -> Literal["high", "medium", "low", "unknown"]:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low", "unknown"}:
        return text  # type: ignore[return-value]
    return "unknown"


def _external_advice_by_requirement(plan: ResearchPlan) -> ExtractedEvidence:
    operations: list[EvidenceOperation] = []
    for operation in plan.operations or [ResearchOperation(id=f"{_safe_id(plan.service_name)}_operation")]:
        operations.append(
            EvidenceOperation(
                id=operation.id,
                description=operation.description or plan.purpose,
                params=[
                    EvidenceParam(key="input", required=True, description="User-provided runtime input"),
                ],
            )
        )
    return ExtractedEvidence(
        service_name=plan.service_name,
        operations=operations,
        recommended_config_fields=[],
        unresolved_fields=["facts_unverified_without_web_search"],
        issues=["llm_advisor_fallback_used"],
        confidence="unknown",
    )


def _build_advisor_brief(plan: ResearchPlan, evidence: ExtractedEvidence) -> ResearchBrief:
    sources = [
        ResearchSource(url=url, title="User provided URL", type="text", trusted_level="unknown")
        for url in plan.source_urls[:5]
    ]
    operations = [operation.model_dump(mode="json", exclude_none=True) for operation in evidence.operations]
    auth = evidence.auth.model_dump(mode="json", exclude_none=True) if evidence.auth else None
    unresolved = _unique([*evidence.unresolved_fields, "facts_unverified_without_web_search"])
    return ResearchBrief(
        service_id=plan.service_id,
        service_name=evidence.service_name or plan.service_name,
        status="partially_resolved",
        confidence=evidence.confidence if evidence.confidence != "high" else "medium",
        summary=(
            "External resource plan produced by LLM prior knowledge only; "
            "WebSearch/fetch is disabled, so facts require user confirmation."
        ),
        sources=sources,
        facts={
            "auth": auth,
            "operations": operations,
            "advice_source": "llm_prior_knowledge_unverified",
        },
        recommended_config_fields=evidence.recommended_config_fields,
        unresolved_fields=unresolved,
        issues=_unique([*evidence.issues, "facts_are_unverified_model_advice"]),
    )


def _advisor_completeness(
    plan: ResearchPlan,
    brief: ResearchBrief,
) -> ResearchCompletenessReport:
    operations = _operations_for_completeness(plan, brief)
    operation_reports = [
        ResearchCompletenessOperation(
            operation_id=str(operation.get("id") or "operation"),
            endpoint=bool(operation.get("endpoint")),
            method=bool(operation.get("method")),
            auth=bool(brief.facts.get("auth")),
            required_params=bool(operation.get("params")),
            response_shape=bool(operation.get("sample_response") or operation.get("error_codes")),
            test_fixture_strategy=True,
            missing_facts=[],
        )
        for operation in operations
    ]
    missing_config_keys = [
        field.key
        for field in brief.recommended_config_fields
        if field.required and not str(field.value or "").strip()
    ]
    missing_facts: list[str] = []
    if plan.requires_research and not brief.recommended_config_fields:
        missing_facts.append("runtime_config_keys")
    return ResearchCompletenessReport(
        status="needs_config_values" if missing_config_keys or missing_facts else "sufficient",
        service_id=brief.service_id,
        service_name=brief.service_name,
        summary=(
            "LLM produced an external-resource candidate plan. "
            "Runtime values still need user confirmation/configuration."
        ),
        operations=operation_reports,
        missing_facts=missing_facts,
        missing_config_keys=_unique(missing_config_keys),
        source_urls=[source.url for source in brief.sources],
        issues=_unique([*brief.issues, "web_search_disabled_llm_advisor_only"]),
    )


def assess_research_completeness(bundle: ResearchBriefBundle) -> ResearchCompletenessReport:
    """Decide whether the extracted documentation is enough to build safe tools.

    This is intentionally stricter than ``ResearchBrief.ok``: a page can be useful
    evidence while still requiring either more docs URLs or runtime config values.
    """

    plan = bundle.plan
    brief = bundle.brief
    source_urls = [source.url for source in brief.sources]
    if plan is not None:
        source_urls = _unique([*source_urls, *plan.source_urls])
    service_id = brief.service_id or (plan.service_id if plan else "")
    service_name = brief.service_name or (plan.service_name if plan else "")
    if brief.status == "skipped" or (plan is not None and not plan.requires_research):
        return ResearchCompletenessReport(
            status="sufficient",
            service_id=service_id,
            service_name=service_name,
            summary="No external research is required for this package.",
            source_urls=source_urls,
        )
    if not source_urls:
        return ResearchCompletenessReport(
            status="needs_more_url",
            service_id=service_id,
            service_name=service_name,
            summary="External service documentation URL is required before tool generation.",
            missing_facts=["official_documentation_url"],
            missing_urls=["official API documentation URL"],
            issues=_unique([*bundle.issues, *brief.issues, "external_resource_url_required"]),
        )
    operations = _operations_for_completeness(plan, brief)
    auth = brief.facts.get("auth") if isinstance(brief.facts.get("auth"), dict) else None
    operation_reports: list[ResearchCompletenessOperation] = []
    missing_facts: list[str] = []
    for operation in operations:
        operation_id = str(operation.get("id") or "operation")
        endpoint = bool(operation.get("endpoint"))
        method = bool(operation.get("method"))
        params = operation.get("params") if isinstance(operation.get("params"), list) else []
        required_params = bool(params) or _endpoint_has_templated_params(str(operation.get("endpoint") or ""))
        response_shape = bool(operation.get("sample_response") or operation.get("error_codes"))
        test_fixture_strategy = bool(
            any(
                field.key.endswith("_TEST_FIXTURE") or "fixture" in field.key.lower()
                for field in brief.recommended_config_fields
            )
            or response_shape
        )
        op_missing: list[str] = []
        if not endpoint:
            op_missing.append("endpoint")
        if not method:
            op_missing.append("method")
        if not auth:
            op_missing.append("auth")
        if not required_params:
            op_missing.append("required_params")
        if not response_shape:
            op_missing.append("sample_response_or_error_shape")
        if not test_fixture_strategy:
            op_missing.append("test_fixture_strategy")
        missing_facts.extend(f"{operation_id}.{item}" for item in op_missing)
        operation_reports.append(
            ResearchCompletenessOperation(
                operation_id=operation_id,
                endpoint=endpoint,
                method=method,
                auth=bool(auth),
                required_params=required_params,
                response_shape=response_shape,
                test_fixture_strategy=test_fixture_strategy,
                missing_facts=op_missing,
            )
        )
    if not operation_reports:
        missing_facts.append("operation.endpoint")
    more_url_missing = [
        item
        for item in missing_facts
        if item.endswith(("endpoint", "method", "auth", "required_params", "sample_response_or_error_shape"))
    ]
    missing_config_keys = [
        field.key
        for field in brief.recommended_config_fields
        if field.required and not str(field.value or "").strip()
    ]
    if brief.status == "unresolved" or more_url_missing:
        return ResearchCompletenessReport(
            status="needs_more_url",
            service_id=service_id,
            service_name=service_name,
            summary="External documentation is not complete enough yet; ask the user for a more specific API/auth/reference URL.",
            operations=operation_reports,
            missing_facts=_unique(missing_facts),
            missing_config_keys=_unique(missing_config_keys),
            missing_urls=_missing_url_suggestions(more_url_missing),
            source_urls=source_urls,
            issues=_unique([*bundle.issues, *brief.issues]),
        )
    if missing_config_keys:
        return ResearchCompletenessReport(
            status="needs_config_values",
            service_id=service_id,
            service_name=service_name,
            summary="Documentation is sufficient for a draft; runtime configuration values still need to be filled.",
            operations=operation_reports,
            missing_facts=_unique(missing_facts),
            missing_config_keys=_unique(missing_config_keys),
            source_urls=source_urls,
            issues=_unique([*bundle.issues, *brief.issues]),
        )
    return ResearchCompletenessReport(
        status="sufficient",
        service_id=service_id,
        service_name=service_name,
        summary="Documentation is sufficient for tool generation.",
        operations=operation_reports,
        source_urls=source_urls,
        issues=_unique([*bundle.issues, *brief.issues]),
    )


def _static_fetch(
    candidate: SearchCandidate,
    *,
    timeout_seconds: int,
    max_chars: int,
) -> FetchedDocument:
    try:
        response = httpx.get(candidate.url, follow_redirects=True, timeout=timeout_seconds)
        response.raise_for_status()
    except Exception as error:
        return FetchedDocument(
            url=candidate.url,
            title=candidate.title,
            status="failed",
            trust=candidate.trust,
            issues=[f"static_fetch_failed: {type(error).__name__}: {error}"],
        )
    content_type = response.headers.get("content-type", "").lower()
    data = response.content
    if "pdf" in content_type or candidate.url.lower().split("?")[0].endswith(".pdf"):
        content, issues = _pdf_text(data)
        document_type: ResearchDocumentType = "pdf"
    else:
        text = response.text
        content = text[:max_chars]
        issues = []
        document_type = _document_type(candidate.url, content_type, content)
    return FetchedDocument(
        url=str(response.url),
        title=candidate.title,
        content=content[:max_chars],
        document_type=document_type,
        status="fetched",
        fetcher="static",
        trust=candidate.trust,
        content_length=len(content),
        issues=issues,
    )


def _browser_fetch(
    candidate: SearchCandidate,
    *,
    timeout_seconds: int,
    max_chars: int,
) -> FetchedDocument:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as error:
        return FetchedDocument(
            url=candidate.url,
            title=candidate.title,
            status="failed",
            fetcher="browser",
            trust=candidate.trust,
            issues=[f"playwright_unavailable: {error}"],
        )
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(candidate.url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_seconds * 1000, 5000))
            except Exception:
                pass
            title = page.title() or candidate.title
            visible_text = page.locator("body").inner_text(timeout=5000)
            content = visible_text.strip() or page.content()
            browser.close()
    except Exception as error:
        return FetchedDocument(
            url=candidate.url,
            title=candidate.title,
            status="failed",
            fetcher="browser",
            trust=candidate.trust,
            issues=[f"browser_fetch_failed: {type(error).__name__}: {error}"],
        )
    return FetchedDocument(
        url=candidate.url,
        title=title,
        content=content[:max_chars],
        document_type="text" if content == visible_text.strip() else "html",
        status="fetched",
        fetcher="browser",
        trust=candidate.trust,
        content_length=len(content),
    )


def _clean_document(document: FetchedDocument, plan: ResearchPlan) -> CleanDocument:
    content = document.content[:]
    headings: list[str] = []
    tables: list[str] = []
    code_blocks: list[str] = []
    title = document.title
    if document.document_type == "html":
        cleaned = _clean_html(content)
        title = cleaned["title"] or title
        text = cleaned["text"]
        headings = cleaned["headings"]
        tables = cleaned["tables"]
        code_blocks = cleaned["code_blocks"]
    elif document.document_type in {"json", "openapi"}:
        text, code_blocks = _clean_json_like(content)
    else:
        text = _normalize_text(content)
        code_blocks = _code_blocks_from_text(content)
    return CleanDocument(
        url=document.url,
        title=title,
        document_type=document.document_type,
        trust=document.trust,
        text=text[:50000],
        tables=tables[:20],
        code_blocks=code_blocks[:20],
        headings=headings[:40],
        score=_document_score(document.url, f"{title}\n{text}", plan, document.trust),
    )


def _clean_html(content: str) -> dict[str, Any]:
    try:
        from bs4 import BeautifulSoup
    except Exception:
        text = re.sub(r"<(script|style).*?</\1>", " ", content, flags=re.DOTALL | re.IGNORECASE)
        for tag in ["nav", "footer", "header", "aside", "form", "noscript", "svg"]:
            text = re.sub(rf"<{tag}\b.*?</{tag}>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        headings = [
            _normalize_text(re.sub(r"<[^>]+>", " ", match.group(1)))
            for match in re.finditer(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", content, flags=re.DOTALL | re.IGNORECASE)
            if match.group(1).strip()
        ]
        tables = [
            _normalize_text(re.sub(r"<[^>]+>", " | ", match.group(1)))
            for match in re.finditer(r"<table\b[^>]*>(.*?)</table>", content, flags=re.DOTALL | re.IGNORECASE)
            if match.group(1).strip()
        ]
        code_blocks = [
            _normalize_text(re.sub(r"<[^>]+>", "\n", match.group(1)))
            for match in re.finditer(r"<(?:pre|code)\b[^>]*>(.*?)</(?:pre|code)>", content, flags=re.DOTALL | re.IGNORECASE)
            if match.group(1).strip()
        ]
        text = re.sub(r"<[^>]+>", " ", text)
        return {
            "title": "",
            "text": _normalize_text(text),
            "headings": headings,
            "tables": tables,
            "code_blocks": code_blocks or _code_blocks_from_text(content),
        }
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    root = _main_content_root(soup)
    headings = [
        _normalize_text(tag.get_text(" ", strip=True))
        for tag in root.find_all(re.compile(r"^h[1-6]$"))
        if tag.get_text(strip=True)
    ]
    tables = [
        _normalize_text(table.get_text(" | ", strip=True))
        for table in root.find_all("table")
        if table.get_text(strip=True)
    ]
    code_blocks = [
        _normalize_text(tag.get_text("\n", strip=True))
        for tag in root.find_all(["code", "pre"])
        if tag.get_text(strip=True)
    ]
    text = _normalize_text(root.get_text("\n", strip=True))
    return {"title": title, "text": text, "headings": headings, "tables": tables, "code_blocks": code_blocks}


def _main_content_root(soup: Any) -> Any:
    selectors = [
        "main",
        "article",
        "[role='main']",
        ".markdown-body",
        ".docs-content",
        ".doc-content",
        ".documentation",
        ".content",
        ".post-content",
        ".entry-content",
        "#content",
    ]
    candidates: list[tuple[int, Any]] = []
    for selector in selectors:
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            if len(text) >= 120:
                candidates.append((len(text), node))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    return soup.body or soup


def _pdf_text(data: bytes) -> tuple[str, list[str]]:
    try:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages[:20]]
        return "\n".join(pages), []
    except Exception as error:
        return "", [f"pdf_extract_failed: {type(error).__name__}: {error}"]


def _clean_json_like(content: str) -> tuple[str, list[str]]:
    try:
        parsed = json.loads(content)
        pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
        return pretty, [pretty[:8000]]
    except Exception:
        return _normalize_text(content), _code_blocks_from_text(content)


def _extract_evidence_with_model(
    model_service: ModelService,
    plan: ResearchPlan,
    documents: list[CleanDocument],
    *,
    context_envelope: FactoryContextEnvelope | None = None,
) -> ExtractedEvidence | None:
    corpus = _document_corpus(documents, max_chars=24000)
    request = apply_context_envelope(
        MessageBuilder.start()
        .system(
            "You extract verifiable external resource evidence for AgentFactory. "
            "Return exactly one JSON object matching ExtractedEvidence. "
            "Only extract facts present in the user-provided document. "
            "If endpoint/auth/params/sample response are not explicit, put them in unresolved_fields."
        )
        .user(
            "Research plan:\n"
            f"{plan.model_dump_json(indent=2)}\n\n"
            "Cleaned user-provided document:\n"
            f"{corpus}\n\n"
            "Extract only the information needed to build the Agent tool. Do not invent missing fields."
        )
        .request(
            response_format="json_schema",
            json_schema=ExtractedEvidence.model_json_schema(),
            json_schema_name="ExtractedEvidence",
            metadata={"phase": "web_research_evidence_extraction", "model_role": "task"},
        ),
        context_envelope,
    )
    try:
        result = asyncio.run(
            model_service.generate_task_structured(
                request,
                schema=ExtractedEvidence.model_json_schema(),
                schema_name="ExtractedEvidence",
            )
        )
    except Exception:
        return None
    if result.error or not isinstance(result.data, dict):
        return None
    try:
        return ExtractedEvidence.model_validate(result.data)
    except Exception:
        return None


def _extract_evidence_by_rules(
    plan: ResearchPlan,
    documents: list[CleanDocument],
) -> ExtractedEvidence:
    all_text = "\n".join(_doc_signal_text(doc) for doc in documents)
    auth = _auth_from_text(all_text, documents)
    endpoints = _endpoint_candidates(all_text)
    methods = _method_candidates(all_text)
    operations: list[EvidenceOperation] = []
    for index, operation in enumerate(plan.operations or [ResearchOperation(id="default")]):
        endpoint = _best_endpoint_for_operation(operation, endpoints)
        method = _method_for_endpoint(all_text, endpoint) or (
            methods[index] if index < len(methods) else (methods[0] if methods else None)
        )
        operations.append(
            EvidenceOperation(
                id=operation.id,
                description=operation.description,
                method=method,
                endpoint=endpoint,
                params=_param_candidates(_operation_window(all_text, endpoint, operation))[:8],
                sample_response=_sample_response(all_text),
                evidence_url=_best_evidence_url(endpoint, documents),
            )
        )
    unresolved: list[str] = []
    if auth is None:
        unresolved.append("authentication")
    if not any(operation.params for operation in operations):
        unresolved.append("request_parameters")
    for operation in operations:
        if not operation.endpoint:
            unresolved.append(f"{operation.id}.endpoint")
        if not operation.method:
            unresolved.append(f"{operation.id}.http_method")
    return ExtractedEvidence(
        service_name=plan.service_name,
        auth=auth,
        operations=operations,
        recommended_config_fields=_recommended_fields(plan, auth, operations),
        unresolved_fields=_unique(unresolved),
        confidence="medium" if operations and any(op.endpoint for op in operations) else "unknown",
    )


def _extract_openapi_evidence(
    plan: ResearchPlan,
    documents: list[CleanDocument],
) -> ExtractedEvidence | None:
    for doc in documents:
        if doc.document_type not in {"openapi", "json"}:
            continue
        try:
            parsed = json.loads(doc.text)
        except Exception:
            continue
        if not isinstance(parsed, dict) or not isinstance(parsed.get("paths"), dict):
            continue
        server_url = _openapi_server_url(parsed, doc.url)
        auth = _openapi_auth(parsed, doc.url)
        candidates = _openapi_operations(parsed, server_url, doc.url)
        if not candidates:
            continue
        operations = _select_openapi_operations(plan, candidates)
        unresolved: list[str] = []
        for operation in operations:
            if not operation.endpoint:
                unresolved.append(f"{operation.id}.endpoint")
            if not operation.method:
                unresolved.append(f"{operation.id}.http_method")
            if not operation.params:
                unresolved.append(f"{operation.id}.request_parameters")
        return ExtractedEvidence(
            service_name=plan.service_name,
            auth=auth,
            operations=operations,
            recommended_config_fields=_recommended_fields(plan, auth, operations),
            unresolved_fields=_unique(unresolved),
            confidence="high",
        )
    return None


def _openapi_server_url(parsed: dict[str, Any], document_url: str) -> str:
    servers = parsed.get("servers")
    if isinstance(servers, list):
        for server in servers:
            if not isinstance(server, dict) or not isinstance(server.get("url"), str):
                continue
            value = server["url"].strip()
            if not value:
                continue
            if value.startswith(("http://", "https://")):
                return value.rstrip("/")
            parsed_doc = urlparse(document_url)
            return urljoin(f"{parsed_doc.scheme}://{parsed_doc.netloc}", value).rstrip("/")
    parsed_doc = urlparse(document_url)
    return f"{parsed_doc.scheme}://{parsed_doc.netloc}".rstrip("/")


def _openapi_auth(parsed: dict[str, Any], evidence_url: str) -> EvidenceAuth | None:
    components = parsed.get("components")
    schemes = components.get("securitySchemes") if isinstance(components, dict) else None
    if not isinstance(schemes, dict):
        return None
    for scheme in schemes.values():
        if not isinstance(scheme, dict):
            continue
        scheme_type = str(scheme.get("type") or "").lower()
        scheme_name = str(scheme.get("scheme") or "").lower()
        in_value = str(scheme.get("in") or "").lower()
        name = scheme.get("name")
        if scheme_type == "http" and scheme_name == "bearer":
            return EvidenceAuth(type="bearer_token", header="Authorization", format="Bearer ${token}", placement="header", evidence_url=evidence_url)
        if scheme_type == "apiKey":
            return EvidenceAuth(type="api_key", header=str(name) if in_value == "header" and name else None, placement=in_value or "header_or_query", evidence_url=evidence_url)
        if scheme_type == "oauth2":
            return EvidenceAuth(type="oauth2", placement="authorization_flow", evidence_url=evidence_url)
    return None


def _openapi_operations(
    parsed: dict[str, Any],
    server_url: str,
    evidence_url: str,
) -> list[EvidenceOperation]:
    result: list[EvidenceOperation] = []
    paths = parsed.get("paths")
    if not isinstance(paths, dict):
        return result
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            method_upper = str(method).upper()
            if method_upper not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            op = operation if isinstance(operation, dict) else {}
            operation_id = str(op.get("operationId") or f"{method_upper.lower()}_{path.strip('/').replace('/', '_')}")
            endpoint = urljoin(f"{server_url.rstrip('/')}/", path.lstrip("/"))
            result.append(
                EvidenceOperation(
                    id=operation_id,
                    description=str(op.get("summary") or op.get("description") or "")[:500],
                    method=method_upper,
                    endpoint=endpoint,
                    params=_openapi_params(path_item, op),
                    sample_response=_openapi_sample_response(op),
                    evidence_url=evidence_url,
                )
            )
    return result


def _openapi_params(path_item: dict[str, Any], operation: dict[str, Any]) -> list[EvidenceParam]:
    params: list[EvidenceParam] = []
    raw_params: list[Any] = []
    for value in (path_item.get("parameters"), operation.get("parameters")):
        if isinstance(value, list):
            raw_params.extend(value)
    for param in raw_params:
        if not isinstance(param, dict) or not isinstance(param.get("name"), str):
            continue
        params.append(
            EvidenceParam(
                key=param["name"],
                required=bool(param.get("required")),
                location=str(param.get("in") or "") or None,
                description=str(param.get("description") or "")[:300] or None,
            )
        )
    request_body = operation.get("requestBody")
    schema = _openapi_request_schema(request_body) if isinstance(request_body, dict) else {}
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required_names = schema.get("required") if isinstance(schema, dict) else None
    if isinstance(properties, dict):
        for key, prop in list(properties.items())[:20]:
            if not isinstance(key, str):
                continue
            params.append(
                EvidenceParam(
                    key=key,
                    required=key in required_names if isinstance(required_names, list) else bool(request_body.get("required", True)),
                    location="body",
                    description=(str(prop.get("description") or "")[:300] if isinstance(prop, dict) else None),
                )
            )
    return _dedupe_params(params)


def _openapi_request_schema(request_body: dict[str, Any]) -> dict[str, Any]:
    content = request_body.get("content")
    if not isinstance(content, dict):
        return {}
    for media in ("application/json", "application/x-www-form-urlencoded", "multipart/form-data"):
        item = content.get(media)
        if isinstance(item, dict) and isinstance(item.get("schema"), dict):
            return item["schema"]
    for item in content.values():
        if isinstance(item, dict) and isinstance(item.get("schema"), dict):
            return item["schema"]
    return {}


def _openapi_sample_response(operation: dict[str, Any]) -> str | None:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    for key in ("200", "201", "default"):
        response = responses.get(key)
        if not isinstance(response, dict):
            continue
        content = response.get("content")
        if not isinstance(content, dict):
            continue
        for media in content.values():
            if isinstance(media, dict) and "example" in media:
                return json.dumps(media["example"], ensure_ascii=False)[:2000]
    return None


def _select_openapi_operations(
    plan: ResearchPlan,
    candidates: list[EvidenceOperation],
) -> list[EvidenceOperation]:
    if not plan.operations:
        return candidates[:4]
    selected: list[EvidenceOperation] = []
    for operation in plan.operations:
        tokens = _operation_tokens(operation)
        best = max(candidates, key=lambda candidate: _openapi_operation_score(candidate, tokens))
        if best.id not in {item.id for item in selected}:
            selected.append(best)
    return selected[: max(len(plan.operations), 1)]


def _openapi_operation_score(operation: EvidenceOperation, tokens: list[str]) -> float:
    text = " ".join([operation.id, operation.description, operation.endpoint or ""]).lower()
    score = 0.0
    for token in tokens:
        if token and token in text:
            score += 5.0
    if operation.method == "GET":
        score += 0.5
    return score


def _validate_and_enrich_evidence(
    evidence: ExtractedEvidence,
    plan: ResearchPlan,
    documents: list[CleanDocument],
) -> ExtractedEvidence:
    issues = list(evidence.issues)
    operations: list[EvidenceOperation] = []
    for operation in evidence.operations:
        if operation.method and operation.method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            issues.append(f"{operation.id}: unsupported_http_method:{operation.method}")
            operation.method = None
        if operation.endpoint and not _looks_like_endpoint(operation.endpoint):
            issues.append(f"{operation.id}: invalid_endpoint:{operation.endpoint}")
            operation.endpoint = None
        if operation.endpoint and not operation.evidence_url:
            operation.evidence_url = _best_evidence_url(operation.endpoint, documents)
        operations.append(operation)
    if not operations:
        return _extract_evidence_by_rules(plan, documents)
    unresolved = list(evidence.unresolved_fields)
    for operation in operations:
        if not operation.endpoint:
            unresolved.append(f"{operation.id}.endpoint")
        if not operation.method:
            unresolved.append(f"{operation.id}.http_method")
    fields = _merge_config_fields(
        evidence.recommended_config_fields,
        _recommended_fields(plan, evidence.auth, operations),
    )
    return evidence.model_copy(
        update={
            "operations": operations,
            "recommended_config_fields": fields,
            "unresolved_fields": _unique(unresolved),
            "issues": _unique(issues),
        }
    )


def _build_brief(
    plan: ResearchPlan,
    evidence: ExtractedEvidence,
    documents: list[CleanDocument],
) -> ResearchBrief:
    sources = [
        ResearchSource(url=doc.url, title=doc.title, type=doc.document_type, trusted_level=doc.trust)
        for doc in documents[:3]
    ]
    unresolved = _unique(evidence.unresolved_fields)
    operations = [operation.model_dump(mode="json", exclude_none=True) for operation in evidence.operations]
    auth = evidence.auth.model_dump(mode="json", exclude_none=True) if evidence.auth else None
    has_endpoint = any(operation.get("endpoint") for operation in operations)
    if operations and has_endpoint and auth and not unresolved:
        status: ResearchStatus = "resolved"
    elif sources or auth or has_endpoint:
        status = "partially_resolved"
    else:
        status = "unresolved"
    confidence = evidence.confidence
    if status == "resolved" and confidence in {"unknown", "low"}:
        confidence = "medium"
    return ResearchBrief(
        service_id=plan.service_id,
        service_name=evidence.service_name or plan.service_name,
        status=status,
        confidence=confidence,
        summary=_brief_summary(plan, status, confidence, unresolved),
        sources=sources,
        facts={"auth": auth, "operations": operations},
        recommended_config_fields=_merge_config_fields(
            evidence.recommended_config_fields,
            _recommended_fields(plan, evidence.auth, evidence.operations),
        ),
        unresolved_fields=unresolved,
        issues=evidence.issues,
    )


def _empty_brief(plan: ResearchPlan, *, status: ResearchStatus, issue: str) -> ResearchBrief:
    return ResearchBrief(
        service_id=plan.service_id,
        service_name=plan.service_name,
        status=status,
        confidence="unknown",
        summary=_brief_summary(plan, status, "unknown", plan.required_facts),
        unresolved_fields=plan.required_facts,
        issues=[issue],
    )


def _manual_candidates(plan: ResearchPlan) -> list[SearchCandidate]:
    return [
        SearchCandidate(title=urlparse(url).netloc or url, url=url, trust=_source_trust(url, title=url, snippet=""))
        for url in plan.source_urls
    ]


def _candidates_from_search_report(
    report: WebSearchReport,
    plan: ResearchPlan,
) -> list[SearchCandidate]:
    scored: list[tuple[float, SearchCandidate]] = []
    seen: set[str] = set()
    for result in report.results:
        canonical = _canonical_url(result.url)
        if canonical in seen:
            continue
        seen.add(canonical)
        candidate = SearchCandidate(
            title=result.title,
            url=canonical,
            snippet="",
            provider=result.source or report.provider,
            score=result.score,
            trust=_source_trust(canonical, title=result.title, snippet=result.snippet),
        )
        scored.append((_search_candidate_score(candidate, plan), candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _score, candidate in scored[: max(1, plan_max_candidates(plan))]]


def plan_max_candidates(_plan: ResearchPlan) -> int:
    return 8


def _search_candidate_score(candidate: SearchCandidate, plan: ResearchPlan) -> float:
    trust_score = {
        "official": 20.0,
        "marketplace": 14.0,
        "vendor_article": 10.0,
        "third_party": 4.0,
        "unknown": 2.0,
    }[candidate.trust]
    text = f"{candidate.url} {candidate.title}".lower()
    score = trust_score + float(candidate.score or 0.0)
    learning_markers = [
        "docs",
        "doc",
        "developer",
        "guide",
        "tutorial",
        "configuration",
        "getting-started",
        "quickstart",
        "api",
        "文档",
        "教程",
        "配置",
        "接入",
        "指南",
        "开发",
    ]
    for marker in learning_markers:
        if marker in text:
            score += 2.0
    for token in _plan_tokens(plan):
        lowered = token.lower()
        if lowered and lowered in text:
            score += 1.5
    noisy_markers = ["blog", "news", "forum", "price", "pricing", "login", "signup", "博客", "新闻", "论坛", "价格", "登录"]
    for marker in noisy_markers:
        if marker in text:
            score -= 3.0
    return score


def _related_candidates_from_document(
    document: FetchedDocument,
    plan: ResearchPlan,
    *,
    seen_urls: set[str],
    limit: int,
) -> list[SearchCandidate]:
    if limit <= 0 or document.status != "fetched" or document.document_type != "html":
        return []
    links = _extract_document_links(document.content, base_url=document.url)
    allowed_hosts = _allowed_research_hosts(plan)
    scored: list[tuple[float, SearchCandidate]] = []
    for url, title in links:
        canonical = _canonical_url(url)
        if canonical in seen_urls:
            continue
        parsed = urlparse(canonical)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if allowed_hosts and parsed.netloc.lower() not in allowed_hosts:
            continue
        score = _related_link_score(canonical, title, plan)
        if score <= 0:
            continue
        scored.append(
            (
                score,
                SearchCandidate(
                    title=title or parsed.path or canonical,
                    url=canonical,
                    provider="related_page",
                    trust=_source_trust(canonical, title=title, snippet=""),
                    score=score,
                ),
            )
        )
    scored.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _score, candidate in scored[:limit]]


def _extract_document_links(content: str, *, base_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "html.parser")
        for tag in soup.find_all("a", href=True):
            href = str(tag.get("href") or "").strip()
            title = _normalize_text(tag.get_text(" ", strip=True))
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            links.append((urljoin(base_url, href), title))
    except Exception:
        for href in re.findall(r"href=[\"']([^\"']+)[\"']", content, flags=re.IGNORECASE):
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            links.append((urljoin(base_url, href), ""))
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url, title in links:
        canonical = _canonical_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        deduped.append((canonical, title))
    return deduped


def _allowed_research_hosts(plan: ResearchPlan) -> set[str]:
    return {urlparse(url).netloc.lower() for url in plan.source_urls if urlparse(url).netloc}


def _related_link_score(url: str, title: str, plan: ResearchPlan) -> float:
    parsed = urlparse(url)
    text = f"{parsed.path} {parsed.query} {title}".lower()
    if not parsed.path or parsed.path == "/":
        return 0.0
    score = 0.0
    for token in _plan_tokens(plan):
        if token and token.lower() in text:
            score += 2.0
    related_markers = {
        "auth": 8.0,
        "authentication": 8.0,
        "jwt": 8.0,
        "token": 6.0,
        "认证": 8.0,
        "身份认证": 8.0,
        "api-host": 8.0,
        "api host": 8.0,
        "host": 4.0,
        "开发配置": 6.0,
        "config": 4.0,
        "geoapi": 7.0,
        "location": 7.0,
        "locationid": 7.0,
        "城市": 5.0,
        "city": 5.0,
        "status-code": 5.0,
        "error": 4.0,
        "错误码": 6.0,
        "状态码": 6.0,
        "weather": 3.0,
        "forecast": 3.0,
        "天气": 3.0,
        "预报": 3.0,
        "params": 4.0,
        "参数": 4.0,
    }
    for marker, weight in related_markers.items():
        if marker in text:
            score += weight
    noisy_markers = ["price", "pricing", "blog", "contact", "github", "terms", "privacy", "download", "icons", "价格", "博客", "联系", "隐私", "服务条款"]
    if any(marker in text for marker in noisy_markers):
        score -= 8.0
    return score


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    cleaned = parsed._replace(fragment="")
    value = cleaned.geturl()
    if value.endswith("/") and parsed.path != "/":
        value = value.rstrip("/")
    return value


def _rank_documents(documents: list[CleanDocument], plan: ResearchPlan) -> list[CleanDocument]:
    return sorted([doc for doc in documents if doc.has_signal], key=lambda doc: doc.score, reverse=True)


def _document_score(url: str, text: str, plan: ResearchPlan, trust: ResearchSourceTrust) -> float:
    score = {"official": 5.0, "marketplace": 4.0, "vendor_article": 3.0, "third_party": 1.0, "unknown": 0.5}[trust]
    lowered = f"{url} {text}".lower()
    for token in _plan_tokens(plan):
        if token and token.lower() in lowered:
            score += 1.0
    for marker in ["endpoint", "authorization", "appcode", "bearer", "api key", "参数", "请求", "响应", "curl"]:
        if marker in lowered:
            score += 0.5
    return score


def _source_trust(url: str, *, title: str = "", snippet: str = "") -> ResearchSourceTrust:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    text = f"{domain} {title} {snippet} {url}".lower()
    if any(host in domain for host in ["docs.", "developer.", "dev.", "api.", "open."]):
        return "official"
    if any(host in domain for host in ["github.com", "slack.dev", "qweather.com", "tavily.com", "mojicb.com", "stripe.com"]):
        return "official"
    if any(host in domain for host in ["market.aliyun.com", "cloudmarket", "oss-"]):
        return "marketplace"
    if any(host in domain for host in ["developer.aliyun.com", "help.aliyun.com"]):
        return "vendor_article"
    if any(marker in text for marker in ["官方", "official", "developer", "docs"]):
        return "vendor_article"
    return "unknown"


def _document_type(url: str, content_type: str, content: str) -> ResearchDocumentType:
    lower_url = url.lower().split("?")[0]
    if "json" in content_type or lower_url.endswith(".json"):
        return "openapi" if "openapi" in content[:1000].lower() else "json"
    if lower_url.endswith((".yaml", ".yml")):
        return "openapi"
    if "markdown" in content_type or lower_url.endswith(".md"):
        return "markdown"
    if "html" in content_type or "<html" in content[:500].lower():
        return "html"
    return "text"


def _looks_like_dynamic_shell(content: str) -> bool:
    if "<html" in content[:1000].lower() or "<body" in content[:2000].lower():
        text = _clean_html(content)["text"]
    else:
        text = _normalize_text(re.sub(r"<[^>]+>", " ", content))
    if len(text) < 800:
        return True
    lowered = text.lower()
    shell_markers = ["enable javascript", "登录", "注册", "sign in", "window.__", "app-root"]
    return sum(marker in lowered for marker in shell_markers) >= 2


def _cleaned_signal_chars(document: FetchedDocument) -> int:
    if document.status != "fetched":
        return 0
    clean = _clean_document(document, ResearchPlan(service_id="signal_check", service_name="signal_check"))
    return len(clean.text) + sum(len(item) for item in clean.tables) + sum(len(item) for item in clean.code_blocks)


def _document_corpus(documents: list[CleanDocument], *, max_chars: int) -> str:
    chunks: list[str] = []
    remaining = max_chars
    for doc in documents[:5]:
        block = {
            "url": doc.url,
            "title": doc.title,
            "trust": doc.trust,
            "headings": doc.headings[:12],
            "text": doc.text[:6000],
            "tables": doc.tables[:5],
            "code_blocks": doc.code_blocks[:5],
        }
        text = json.dumps(block, ensure_ascii=False, indent=2)
        if len(text) > remaining:
            text = text[:remaining]
        chunks.append(text)
        remaining -= len(text)
        if remaining <= 0:
            break
    return "\n\n".join(chunks)


def _doc_signal_text(doc: CleanDocument) -> str:
    return "\n".join([doc.title, doc.text, *doc.tables, *doc.code_blocks])


def _endpoint_candidates(text: str) -> list[str]:
    candidates = re.findall(r"https?://[^\s\"'<>，。]+", text)
    path_candidates = re.findall(r"(?:(?:GET|POST|PUT|PATCH|DELETE)\s+)?(/[a-zA-Z0-9_./{}:-]{4,})", text, flags=re.IGNORECASE)
    cleaned: list[str] = []
    for value in [*candidates, *path_candidates]:
        value = value.rstrip(").,;，。]:")
        if value.startswith("//"):
            value = f"https:{value}"
        if _looks_like_endpoint(value) and value not in cleaned:
            cleaned.append(value)
    return sorted(cleaned, key=_endpoint_quality_score, reverse=True)[:20]


def _looks_like_endpoint(value: str) -> bool:
    lowered = value.lower()
    if re.search(r"\.(png|jpg|jpeg|gif|svg|ico|css|js|woff2?|ttf|git)(\?|$)", lowered):
        return False
    if value.startswith("http://") or value.startswith("https://"):
        try:
            parsed = urlparse(value)
        except ValueError:
            return False
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        if host.startswith(("localhost", "127.0.0.1", "0.0.0.0")):
            return False
        if host in {"github.com", "www.github.com", "gitlab.com", "bitbucket.org"}:
            return False
        if host.startswith(("docs.", "developer.", "developers.")):
            return False
        target = f"{host}{path}"
        return any(marker in target for marker in ["api", "/v1", "/v2", "/v3", "/v7", "graphql", "json", "whapi", "weather", "forecast", "chat.", "payment", "issues", "search", "completions"])
    return value.startswith("/") and any(marker in lowered for marker in ["/api", "/v1", "/v2", "/v3", "/v7", "json", "{", "graphql", "/search", "/segment", "/chat/completions"])


def _method_candidates(text: str) -> list[str]:
    methods = re.findall(r"\b(GET|POST|PUT|PATCH|DELETE)\b", text)
    return _unique(methods)[:10]


def _best_endpoint_for_operation(operation: ResearchOperation, endpoints: list[str]) -> str | None:
    if not endpoints:
        return None
    tokens = _operation_tokens(operation)
    return max(endpoints, key=lambda endpoint: _endpoint_operation_score(endpoint, tokens))


def _endpoint_operation_score(endpoint: str, tokens: list[str]) -> float:
    lowered = endpoint.lower()
    score = float(_endpoint_quality_score(endpoint))
    normalized = lowered.replace("-", "_").replace("/", "_")
    for token in tokens:
        if token and token in lowered:
            score += 8.0
        if token and token in normalized:
            score += 6.0
    return score


def _endpoint_quality_score(endpoint: str) -> int:
    try:
        parsed = urlparse(endpoint if endpoint.startswith(("http://", "https://")) else f"https://x{endpoint}")
    except ValueError:
        return -1000
    path = parsed.path or ""
    score = len(path)
    if path and path != "/":
        score += 20
    if any(marker in endpoint.lower() for marker in ["chat/completions", "forecast", "weather", "json", "api"]):
        score += 15
    return score


def _operation_tokens(operation: ResearchOperation) -> list[str]:
    raw = " ".join([operation.id, operation.description, operation.tool_ref or ""]).lower()
    parts = re.split(r"[^a-zA-Z0-9\u4e00-\u9fff]+", raw)
    tokens = [part for part in parts if len(part) >= 3]
    joined = "_".join(tokens)
    if joined:
        tokens.append(joined)
    return tokens


def _method_for_endpoint(text: str, endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    index = text.find(endpoint)
    if index < 0 and endpoint.startswith("https://"):
        index = text.find(endpoint.removeprefix("https:"))
    if index < 0:
        return None
    window = text[max(0, index - 200) : index + len(endpoint) + 500]
    after = window[window.find(endpoint) + len(endpoint) :] if endpoint in window else window
    if re.search(r"curl\s+" + re.escape(endpoint), window, flags=re.IGNORECASE) and re.search(r"(^|\s)-d\s+|--data|--data-raw|--form", after, flags=re.IGNORECASE):
        return "POST"
    method_match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b", window)
    if method_match:
        return method_match.group(1)
    if any(marker in after.lower() for marker in [".post", "method.post", "requests.post"]):
        return "POST"
    if any(marker in after.lower() for marker in [".get", "method.get", "requests.get"]):
        return "GET"
    return None


def _param_candidates(text: str) -> list[EvidenceParam]:
    candidates = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]{1,40})\b", text)
    interesting = {"city", "cityId", "location", "query", "q", "key", "appcode", "appid", "token", "lat", "lon", "lang", "unit", "days", "limit", "page", "per_page", "owner", "repo", "title", "body", "channel", "text", "amount", "currency", "description", "metadata", "status"}
    params: list[EvidenceParam] = []
    for item in candidates:
        if item in interesting and item not in {param.key for param in params}:
            params.append(EvidenceParam(key=item, required=item not in {"lang", "unit", "limit", "page"}))
    return params


def _auth_from_text(text: str, documents: list[CleanDocument]) -> EvidenceAuth | None:
    lowered = text.lower()
    evidence_url = documents[0].url if documents else None
    if "appcode" in lowered:
        return EvidenceAuth(type="aliyun_market_appcode", header="Authorization", format="APPCODE ${appcode}", placement="header", evidence_url=evidence_url)
    if "jwt" in lowered:
        return EvidenceAuth(type="jwt_bearer", header="Authorization", format="Bearer ${jwt}", placement="header", evidence_url=evidence_url)
    if "bearer" in lowered or "authorization:" in lowered:
        return EvidenceAuth(type="bearer_token", header="Authorization", format="Bearer ${token}", placement="header", evidence_url=evidence_url)
    if "api key" in lowered or "apikey" in lowered or "x-api-key" in lowered:
        return EvidenceAuth(type="api_key", placement="header_or_query", evidence_url=evidence_url)
    return None


def _sample_response(text: str) -> str | None:
    match = re.search(r"(\{(?:[^{}]|\{[^{}]*\}){20,2000}\})", text, flags=re.DOTALL)
    if match:
        return match.group(1)[:2000]
    return None


def _best_evidence_url(endpoint: str | None, documents: list[CleanDocument]) -> str | None:
    if endpoint:
        for doc in documents:
            if endpoint in _doc_signal_text(doc):
                return doc.url
    return documents[0].url if documents else None


def _recommended_fields(
    plan: ResearchPlan,
    auth: EvidenceAuth | None,
    operations: list[EvidenceOperation],
) -> list[RecommendedConfigField]:
    service_key = _env_key(plan.service_name)
    fields = [
        RecommendedConfigField(
            key=f"{service_key}_DOCS_URL",
            label="官方文档 URL",
            required=True,
            value=plan.source_urls[0] if plan.source_urls else "",
            confidence="medium" if plan.source_urls else "unknown",
        )
    ]
    if any(_is_relative_endpoint(operation.endpoint) for operation in operations):
        fields.append(
            RecommendedConfigField(
                key=f"{service_key}_API_HOST",
                label="API Host",
                required=True,
                value="",
                confidence="unknown",
                notes="Runtime base URL/host for relative endpoints.",
            )
        )
    if auth:
        fields.append(
            RecommendedConfigField(
                key=_credential_key(service_key, auth),
                label=_credential_label(auth),
                required=True,
                secret=True,
                value="",
                confidence="medium",
            )
        )
    for operation in operations:
        if operation.endpoint:
            fields.append(
                RecommendedConfigField(
                    key=f"{_env_key(operation.id)}_ENDPOINT",
                    label=f"{operation.id} endpoint",
                    value=operation.endpoint,
                    confidence="medium",
                )
            )
        if operation.method:
            fields.append(
                RecommendedConfigField(
                    key=f"{_env_key(operation.id)}_METHOD",
                    label=f"{operation.id} HTTP method",
                    value=operation.method,
                    confidence="medium",
                )
            )
    fields.append(
        RecommendedConfigField(
            key=f"{service_key}_TEST_FIXTURE",
            label="测试样例",
            required=False,
            value="",
            confidence="unknown",
        )
    )
    return _dedupe_fields(fields)


def _credential_key(service_key: str, auth: EvidenceAuth) -> str:
    auth_type = (auth.type or "").lower()
    if "appcode" in auth_type or "appcode" in (auth.format or "").lower():
        return f"{service_key}_APPCODE"
    if "jwt" in auth_type or "jwt" in (auth.format or "").lower():
        return f"{service_key}_JWT"
    if "api_key" in auth_type or "api key" in auth_type:
        return f"{service_key}_API_KEY"
    if "bearer" in auth_type or "token" in (auth.format or "").lower():
        return f"{service_key}_TOKEN"
    return f"{service_key}_CREDENTIAL"


def _credential_label(auth: EvidenceAuth) -> str:
    auth_type = (auth.type or "").lower()
    if "appcode" in auth_type:
        return "APPCODE"
    if "jwt" in auth_type:
        return "JWT"
    if "api_key" in auth_type:
        return "API Key"
    if "bearer" in auth_type:
        return "Bearer Token"
    return "凭证引用"


def _is_relative_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    return endpoint.startswith("/") and not endpoint.startswith("//")


def _endpoint_has_templated_params(endpoint: str) -> bool:
    return bool(re.search(r"\{[^{}]+\}|:[A-Za-z_][A-Za-z0-9_]*", endpoint))


def _operations_for_completeness(
    plan: ResearchPlan | None,
    brief: ResearchBrief,
) -> list[dict[str, Any]]:
    operations = brief.facts.get("operations")
    if isinstance(operations, list) and operations:
        return [item for item in operations if isinstance(item, dict)]
    if plan is None:
        return []
    return [
        {
            "id": operation.id,
            "description": operation.description,
            "params": [],
        }
        for operation in plan.operations
    ]


def _missing_url_suggestions(missing_facts: list[str]) -> list[str]:
    suggestions: list[str] = []
    joined = " ".join(missing_facts)
    if "auth" in joined:
        suggestions.append("authentication / authorization documentation URL")
    if "endpoint" in joined or "method" in joined:
        suggestions.append("API reference endpoint documentation URL")
    if "required_params" in joined:
        suggestions.append("request parameters documentation URL")
    if "sample_response" in joined:
        suggestions.append("response examples or error codes documentation URL")
    return _unique(suggestions)


def _dedupe_fields(fields: list[RecommendedConfigField]) -> list[RecommendedConfigField]:
    seen: set[str] = set()
    result: list[RecommendedConfigField] = []
    for field in fields:
        if field.key in seen:
            continue
        seen.add(field.key)
        result.append(field)
    return result


def _merge_config_fields(
    primary: list[RecommendedConfigField],
    defaults: list[RecommendedConfigField],
) -> list[RecommendedConfigField]:
    return _dedupe_fields([*primary, *defaults])


def _brief_summary(plan: ResearchPlan, status: ResearchStatus, confidence: str, unresolved: list[str]) -> str:
    if status == "resolved":
        return f"Verified single-page external resource evidence for {plan.service_name} with {confidence} confidence."
    if status == "partially_resolved":
        return f"Extracted partial evidence for {plan.service_name}; {len(unresolved)} field(s) still need user input."
    return f"External resource evidence for {plan.service_name} is incomplete; ask the user for an official URL or more details."


def _operations_from_report(report: dict[str, Any]) -> list[ResearchOperation]:
    operations: dict[str, ResearchOperation] = {}
    for plan in report.get("plans", []):
        if not isinstance(plan, dict):
            continue
        tool_id = str(plan.get("tool_id") or "external_tool")
        descriptions = [
            str(condition.get("description") or "")
            for condition in plan.get("required_conditions", [])
            if isinstance(condition, dict)
        ]
        operations[tool_id] = ResearchOperation(
            id=tool_id,
            description="; ".join([item for item in descriptions if item])[:500],
            evidence_needed=["endpoint", "method", "auth", "params", "sample_response"],
            query_hints=[str(query) for query in plan.get("research_queries", []) if isinstance(query, str)],
            tool_ref=tool_id,
        )
    return list(operations.values())


def _queries_from_report(report: dict[str, Any]) -> list[str]:
    queries: list[str] = []
    for plan in report.get("plans", []):
        if not isinstance(plan, dict):
            continue
        for query in plan.get("research_queries", []):
            if isinstance(query, str):
                queries.append(query)
    return _unique(queries)


def _rewrite_learning_queries(
    *,
    service_name: str,
    requirement: str,
    operations: list[ResearchOperation],
    query_hints: list[str],
) -> list[str]:
    """Generate human-style search queries for external resource learning.

    Earlier versions generated narrow fact-hunting queries such as
    "endpoint/auth/params", which worked poorly across non-API web resources.
    The Factory should first find tutorials, configuration guides, and official
    docs, then extract evidence from cleaned pages.
    """

    subject = _query_subject(service_name, requirement)
    operation_terms = _operation_query_terms(operations)
    queries = [
        f"{subject} 使用教程",
        f"{subject} 配置教程",
        f"{subject} 官方文档 接入指南",
    ]
    if _looks_like_api_need(requirement, operations, query_hints):
        queries.extend(
            [
                f"{subject} API 使用教程",
                f"{subject} API 配置",
            ]
        )
    for term in operation_terms[:2]:
        queries.append(f"{subject} {term} 使用教程")
        queries.append(f"{subject} {term} 配置")
    return _unique(_clean_query(query) for query in queries if query.strip())[:6]


def _query_subject(service_name: str, requirement: str) -> str:
    service = service_name.strip()
    if service and service.lower() not in {"external_service", "external resource", "unknown"}:
        return service
    without_urls = re.sub(r"https?://[^\s，。；；)）'\"]+", " ", requirement)
    for pattern in [
        r"创建一个([^，。\n]{2,40}?)(?:助手|Agent|agent)",
        r"查询([^，。\n]{2,40}?)(?:的|信息|数据)",
        r"使用([^，。\n]{2,40}?)(?:服务|平台|网站|接口|API)",
    ]:
        match = re.search(pattern, without_urls, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return without_urls.strip()[:40] or "外部资源"


def _operation_query_terms(operations: list[ResearchOperation]) -> list[str]:
    terms: list[str] = []
    for operation in operations:
        text = " ".join([operation.id, operation.description, operation.tool_ref or ""])
        text = re.sub(r"[_-]+", " ", text)
        for raw in re.split(r"[^a-zA-Z0-9\u4e00-\u9fff]+", text):
            item = raw.strip()
            if len(item) < 3:
                continue
            if item.lower() in {
                "api",
                "docs",
                "tool",
                "query",
                "external",
                "service",
                "required",
                "condition",
            }:
                continue
            terms.append(item)
    return _unique(terms)


def _looks_like_api_need(
    requirement: str,
    operations: list[ResearchOperation],
    query_hints: list[str],
) -> bool:
    text = " ".join(
        [
            requirement,
            " ".join(query_hints),
            " ".join(operation.description for operation in operations),
            " ".join(operation.id for operation in operations),
        ]
    ).lower()
    return any(marker in text for marker in ["api", "接口", "endpoint", "http", "鉴权", "凭证", "请求", "响应"])


def _clean_query(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _guess_service_name(text: str) -> str:
    url_match = re.search(r"https?://([^/\s，。；；)）'\"]+)", text)
    if url_match:
        return url_match.group(1).strip().lower()
    for pattern in [
        r"创建一个([^，。\n]{2,40}?)(?:助手|Agent|agent)",
        r"创建([^，。\n]{2,40}?)(?:助手|Agent|agent)",
        r"能够(?:查询|管理|处理|分析)([^，。\n]{2,40}?)(?:的|信息|数据)?",
    ]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "external_service"


def _extract_urls(text: str) -> list[str]:
    return _unique(re.findall(r"https?://[^\s，。；；)）'\"]+", text))


def _preferred_domains(urls: list[str]) -> list[str]:
    domains: list[str] = []
    for url in urls:
        domain = urlparse(url).netloc.lower()
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _plan_tokens(plan: ResearchPlan) -> list[str]:
    tokens = [plan.service_name, plan.service_id]
    for operation in plan.operations:
        tokens.extend([operation.id, operation.description])
    return [token for token in tokens if token]


def _safe_id(value: str) -> str:
    lowered = value.lower()
    if "墨迹" in value or "moji" in lowered:
        return "moji_weather"
    if "和风" in value or "qweather" in lowered:
        return "qweather"
    key = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    if key:
        return key
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"external_{digest}"


def _env_key(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", _safe_id(value)).strip("_").upper()
    return key or "EXTERNAL_RESOURCE"


def _normalize_env_key(value: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_]+", "_", str(value).strip()).strip("_").upper()
    key = re.sub(r"_+", "_", key)
    return key


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = str(value).strip()
        if clean and clean not in result:
            result.append(clean)
    return result


def _normalize_text(value: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t\r\f\v]+", " ", value)).strip()


def _code_blocks_from_text(value: str) -> list[str]:
    return [
        match.group(1).strip()
        for match in re.finditer(r"```(?:\w+)?\s*(.*?)```", value, flags=re.DOTALL)
        if match.group(1).strip()
    ]


def _operation_window(text: str, endpoint: str | None, operation: ResearchOperation) -> str:
    windows: list[str] = []
    if endpoint:
        index = text.find(endpoint)
        if index < 0 and endpoint.startswith("https://"):
            index = text.find(endpoint.removeprefix("https:"))
        if index >= 0:
            windows.append(text[max(0, index - 1000) : index + len(endpoint) + 3000])
    lowered = text.lower()
    for token in _operation_tokens(operation):
        index = lowered.find(token.lower())
        if index >= 0:
            windows.append(text[max(0, index - 500) : index + 2500])
            break
    return "\n".join(windows) if windows else text[:5000]


def _dedupe_params(params: list[EvidenceParam]) -> list[EvidenceParam]:
    seen: set[str] = set()
    result: list[EvidenceParam] = []
    for param in params:
        if param.key in seen:
            continue
        seen.add(param.key)
        result.append(param)
    return result
