from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agent_factory.factory.environment import EnvironmentProbeRunner
from agent_factory.factory.package_artifacts import PackageArtifactGenerator
from agent_factory.factory.package_writer import PackageWriter
from agent_factory.factory.resource_binding import extract_local_resources
from agent_factory.factory.tool_preconditions import (
    RequiredCondition,
    ToolPreconditionPlan,
    ToolPreconditionReport,
    analyze_tool_preconditions,
    build_tool_precondition_request,
)
from agent_factory.factory.web_search import (
    FactoryWebSearchService,
    TavilyWebSearchProvider,
    WebSearchConfig,
    WebSearchProvider,
    WebSearchRequest,
    WebSearchReport,
    WebSearchResult,
)
from agent_factory.factory.web_research import (
    ResearchBriefBundle,
    ResearchOperation,
    ResearchPlan,
    ResearchPlanBuilder,
    WebSearchPipeline,
    WebSearchPipelineConfig,
    assess_research_completeness,
)
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.factory_runtime.production import FactoryProductionRuntime
from agent_factory.model import ModelConfig, ModelService
from agent_factory.tools import ControlledShellRunner, load_external_config_context
from agent_factory.tools.router import ToolInvocation, ToolRouter
from tests.test_factory_agent import (
    OpenAIProviderFakeAdapter,
    service_with_responses,
    valid_primitives_payload,
)


class StaticSearchProvider(WebSearchProvider):
    provider = "static"

    def search(self, request: WebSearchRequest) -> WebSearchReport:
        max_results = request.max_results or 5
        results = [
            WebSearchResult(
                title=f"Search result for {request.query}",
                url="https://example.com/docs",
                snippet="Stable public documentation snippet for tests.",
                source="static",
            )
        ][:max_results]
        return WebSearchReport(
            status="passed",
            provider=self.provider,
            queries=[request.query],
            results=results,
        )


class RecordingSearchProvider(WebSearchProvider):
    provider = "recording"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, request: WebSearchRequest) -> WebSearchReport:
        self.queries.append(request.query)
        return WebSearchReport(
            status="passed",
            provider=self.provider,
            queries=[request.query],
            results=[
                WebSearchResult(
                    title="Image segmentation official API docs",
                    url="https://docs.example.com/image-segmentation",
                    snippet="Official API reference with endpoint, authentication, request parameters, and examples.",
                    source="recording",
                    score=0.95,
                )
            ],
        )


class _SearchResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "answer": "Tavily answer summary.",
            "request_id": "request-123",
            "usage": {"credits": 1},
            "results": [
                {
                    "title": "Tavily docs",
                    "url": "https://docs.tavily.com/api-reference/endpoint/search",
                    "content": "Search endpoint documentation.",
                    "raw_content": "# Search endpoint",
                    "score": 0.91,
                }
            ],
        }


class _DocumentResponse:
    headers = {"content-type": "text/html"}
    url = "https://example.com/moji-weather-api"
    text = """
    <html>
      <head><title>墨迹天气 API 文档</title></head>
      <body>
        <nav>登录 注册</nav>
        <main>
          <h1>Forecast API</h1>
          <p>Use POST https://aliv18.data.moji.com/whapi/json/alicityweather/forecast24hours.</p>
          <p>Authentication header: Authorization: APPCODE ${appcode}</p>
          <table><tr><th>参数</th><th>说明</th></tr><tr><td>cityId</td><td>城市 ID</td></tr></table>
          <pre>{"code":0,"data":{"city":{"cityId":2},"hourly":[{"temp":22}]}}</pre>
        </main>
        <footer>copyright</footer>
      </body>
    </html>
    """
    content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class _DeepSeekDocsResponse:
    headers = {"content-type": "text/html"}
    url = "https://api-docs.deepseek.com/zh-cn/"
    text = """
    <html>
      <head><title>首次调用 API | DeepSeek API Docs</title></head>
      <body>
        <h1>首次调用 API</h1>
        <table>
          <tr><td>base_url (OpenAI)</td><td>https://api.deepseek.com</td></tr>
          <tr><td>api_key</td><td>apply for an API key</td></tr>
        </table>
        <h2>调用对话 API</h2>
        <pre>curl https://api.deepseek.com/chat/completions \\
          -H "Content-Type: application/json" \\
          -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" \\
          -d '{"model":"deepseek-v4-pro","messages":[]}'</pre>
      </body>
    </html>
    """
    content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class _SegmentationDocsResponse:
    headers = {"content-type": "text/html"}
    url = "https://docs.example.com/image-segmentation"
    text = """
    <html>
      <head><title>Image Segmentation API Reference</title></head>
      <body>
        <main>
          <h1>Image Segmentation API</h1>
          <p>Use POST https://api.vision.example.com/v1/segment to segment an image.</p>
          <p>Authentication: Authorization: Bearer ${VISION_API_KEY}</p>
          <table>
            <tr><th>Parameter</th><th>Required</th></tr>
            <tr><td>image_url</td><td>true</td></tr>
          </table>
          <pre>{"mask_url":"https://cdn.example.com/mask.png","status":"completed"}</pre>
        </main>
      </body>
    </html>
    """
    content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class _HtmlResponse:
    headers = {"content-type": "text/html"}

    def __init__(self, url: str, text: str) -> None:
        self.url = url
        self.text = text
        self.content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class ConditionPreflightTests(unittest.TestCase):
    def test_url_is_not_treated_as_local_resource_path(self) -> None:
        resources = extract_local_resources(
            "官方文档：https://dev.qweather.com/docs/api/weather/weather-daily-forecast/",
            start_path="/Users/liuyan/Desktop/FastAgentFactory",
        )

        self.assertEqual(resources, [])

    def test_sqlite_probe_discovers_schema_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "customer_ops.sqlite3"
            _create_sqlite_fixture(db_path)
            primitives = _sqlite_primitives(db_path)

            _environment, contracts, readiness = EnvironmentProbeRunner().probe(
                primitives,
                requirement=f"管理本地 SQLite 数据库 {db_path}",
                start_path=tmpdir,
            )

            self.assertEqual(readiness.status, "ready")
            resource = contracts.resources[0]
            self.assertEqual(resource.type, "sqlite")
            self.assertEqual(resource.status, "ready")
            table = resource.sqlite_tables[0]
            self.assertEqual(table.name, "customer_tickets")
            self.assertIn("ticket_id", table.primary_keys)
            self.assertIn("created_at", table.required_columns)
            self.assertIn("updated_at", table.required_columns)
            self.assertTrue(table.check_constraints)

    def test_missing_resource_returns_needs_user_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.sqlite3"
            primitives = _sqlite_primitives(missing)

            _environment, contracts, readiness = EnvironmentProbeRunner().probe(
                primitives,
                requirement=f"管理本地 SQLite 数据库 {missing}",
                start_path=tmpdir,
            )

            self.assertEqual(contracts.resources[0].status, "missing")
            self.assertEqual(readiness.status, "needs_user_input")
            self.assertIn("replace_resource_path", {option.id for option in readiness.options})

    def test_controlled_shell_runner_rejects_non_allowlisted_command(self) -> None:
        runner = ControlledShellRunner(allowed_commands={"sqlite3"})

        result = runner.run(["rm", "-rf", "/tmp/nope"])

        self.assertEqual(result.status, "rejected")
        self.assertIn("not allowlisted", result.error or "")

    def test_controlled_shell_runner_requires_review_for_file_delete(self) -> None:
        runner = ControlledShellRunner(allowed_commands={"rm"})

        result = runner.run(["rm", "danger.txt"])

        self.assertEqual(result.status, "review_required")
        self.assertIsNotNone(result.review)
        assert result.review is not None
        self.assertEqual(result.review.operation, "file_delete")
        self.assertFalse(result.review.approved)

    def test_controlled_shell_runner_requires_review_for_file_write(self) -> None:
        runner = ControlledShellRunner(allowed_commands={"touch"})

        result = runner.run(["touch", "created.txt"])

        self.assertEqual(result.status, "review_required")
        self.assertIsNotNone(result.review)
        assert result.review is not None
        self.assertEqual(result.review.operation, "file_write")

    def test_controlled_shell_runner_executes_reviewed_file_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = ControlledShellRunner(allowed_commands={"touch"})

            result = runner.run(
                ["touch", "created.txt"],
                cwd=tmpdir,
                approved=True,
                reviewer="unit-test",
                approval_id="approval-1",
            )

            self.assertEqual(result.status, "completed", result.error)
            self.assertTrue((Path(tmpdir) / "created.txt").exists())
            self.assertIsNotNone(result.review)
            assert result.review is not None
            self.assertTrue(result.review.approved)
            self.assertEqual(result.review.reviewer, "unit-test")
            self.assertEqual(result.review.approval_id, "approval-1")

    def test_controlled_shell_runner_allows_readonly_probe_without_review(self) -> None:
        runner = ControlledShellRunner(allowed_commands={"sqlite3"})

        result = runner.run(["sqlite3", "--version"])

        self.assertNotEqual(result.status, "review_required")
        self.assertIsNone(result.review)

    def test_factory_graph_writes_condition_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()])
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "completed", state.error)
            assert state.package_path is not None
            self.assertTrue((state.package_path / "environment.yaml").exists())
            self.assertTrue((state.package_path / "resource_contracts.yaml").exists())
            self.assertTrue((state.package_path / "readiness.yaml").exists())
            self.assertIn("plan_capability_preconditions", state.stage_history)
            self.assertIn("analyze_tool_preconditions", state.stage_history)
            self.assertIn("factory_web_research", state.stage_history)
            self.assertIn("probe_environment", state.stage_history)

    def test_external_realtime_tool_returns_needs_user_input_without_api_contract(self) -> None:
        primitives = _weather_primitives()
        report = analyze_tool_preconditions(
            primitives,
            "创建一个实时天气 Agent，支持查询江西婺源天气",
            web_config=WebSearchConfig(provider="disabled"),
        )

        _environment, contracts, readiness = EnvironmentProbeRunner().probe(
            primitives,
            requirement="创建一个实时天气 Agent，支持查询江西婺源天气",
            tool_precondition_report=report,
        )

        self.assertEqual(readiness.status, "needs_user_input")
        self.assertEqual(contracts.resources[0].type, "external_api")
        self.assertIn("provide_external_url", {option.id for option in readiness.options})
        self.assertIn("use_mock_only", {option.id for option in readiness.options})

    def test_external_realtime_tool_writes_runtime_config_template_after_research(self) -> None:
        primitives = _weather_primitives()
        report = analyze_tool_preconditions(
            primitives,
            "创建一个墨迹天气 Agent，查询城市当日和未来几天空气趋势",
            web_config=WebSearchConfig(provider="tavily"),
        )
        self.assertTrue(any("墨迹天气" in query for query in report.plans[0].research_queries))
        service = FactoryWebSearchService(
            WebSearchConfig(provider="tavily"),
            provider=StaticSearchProvider(),
        )
        plan = ResearchPlanBuilder().build(
            requirement=(
                "创建一个墨迹天气 Agent，查询城市当日和未来几天空气趋势。"
                "官方文档 URL：https://example.com/moji-weather-api"
            ),
            tool_precondition_report=report.model_dump(mode="json"),
        )
        with patch("agent_factory.factory.web_research.httpx.get") as get:
            get.return_value = _DocumentResponse()
            research = WebSearchPipeline(search_service=service).run(plan)

        environment, contracts, readiness = EnvironmentProbeRunner().probe(
            primitives,
            requirement="创建一个墨迹天气 Agent，查询城市当日和未来几天空气趋势",
            tool_precondition_report=report,
            web_research_report=research.raw_search_report,
            research_brief_report=research,
        )

        self.assertEqual(readiness.status, "ready")
        self.assertIn(
            "external_config_template_required",
            {issue.code for issue in readiness.issues},
        )
        self.assertTrue(
            any(
                resource.details.get("configuration_template", {}).get("file")
                == "external_config.yaml"
                for resource in contracts.resources
            )
        )
        self.assertFalse(contracts.resources[0].details.get("web_research_results"))
        self.assertEqual(
            contracts.resources[0].details["research_brief"]["service_name"],
            "墨迹天气",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            PackageWriter().write_condition_specs(
                tmpdir,
                environment=environment,
                resource_contracts=contracts,
                readiness=readiness,
            )
            external_config = Path(tmpdir) / "external_config.yaml"
            self.assertTrue(external_config.exists())
            text = external_config.read_text(encoding="utf-8")
            self.assertIn("ExternalResourceConfig", text)
            self.assertIn("values", text)
            self.assertIn("MOJI_WEATHER_APPCODE", text)
            self.assertNotIn("EXTERNAL_SERVICE_DOCS_URL", text)
            self.assertIn("https://example.com/moji-weather-api", text)
            self.assertIn("WEATHER_QUERY_ENDPOINT", text)
            self.assertIn("forecast24hours", text)
            self.assertNotIn("model-studio/runs", text)
            self.assertNotIn("Endpoint and auth documentation", text)
            self.assertNotIn("base_url:", text)

    def test_tool_precondition_request_uses_semantic_task_model_prompt(self) -> None:
        request = build_tool_precondition_request(
            _weather_primitives(),
            "创建一个竞品官网变化追踪 Agent",
            web_config=WebSearchConfig(provider="tavily"),
        )

        prompt = "\n".join(message.content for message in request.messages)
        self.assertEqual(request.response_format, "json_schema")
        self.assertEqual(request.json_schema_name, "ToolPreconditionReport")
        self.assertIn("semantic precondition planner", prompt)
        self.assertIn("Semantic reasoning is primary", prompt)
        self.assertIn("local resources", prompt)

    def test_model_semantic_precondition_report_is_primary_when_available(self) -> None:
        model_payload = ToolPreconditionReport(
            plans=[
                ToolPreconditionPlan(
                    tool_id="weather_query",
                    capability_kind="browser",
                    required_conditions=[
                        RequiredCondition(
                            condition_id="weather_query.browser_access",
                            type="browser_access",
                            status="missing",
                            description="Target competitor URL and access policy are required.",
                            probe_strategy="browser_check",
                            user_input_needed=True,
                        ),
                        RequiredCondition(
                            condition_id="weather_query.schedule",
                            type="schedule",
                            status="missing",
                            description="A monitoring schedule is required.",
                            probe_strategy="schedule_check",
                            user_input_needed=True,
                        ),
                        RequiredCondition(
                            condition_id="weather_query.storage_backend",
                            type="storage_backend",
                            status="missing",
                            description="Previous page snapshots need storage.",
                            probe_strategy="storage_check",
                            user_input_needed=True,
                        ),
                    ],
                    research_queries=["competitor page change monitoring best practices"],
                    agent_should_inherit_web_search=True,
                    reason="The user needs page tracking even without an API keyword.",
                )
            ],
            source="task_model",
        ).model_dump(mode="json")

        report = analyze_tool_preconditions(
            _weather_primitives(),
            "创建一个 Agent，帮我盯住竞品页面变化",
            web_config=WebSearchConfig(provider="tavily"),
            model_service=ModelService.with_adapter(
                ModelConfig(provider="openai_compatible_chat"),
                OpenAIProviderFakeAdapter([model_payload]),
            ),
        )

        self.assertEqual(report.source, "task_model_with_rule_safety")
        self.assertEqual(report.plans[0].capability_kind, "browser")
        condition_types = {condition.type for condition in report.plans[0].required_conditions}
        self.assertIn("browser_access", condition_types)
        self.assertIn("mock_fixture", condition_types)
        self.assertIn("weather_query.browser_access", report.plans[0].missing_conditions)

    def test_competitor_tracking_rules_cover_browser_schedule_storage_and_fixture(self) -> None:
        report = analyze_tool_preconditions(
            _custom_tool_primitives("page_watch", "盯住竞品页面变化并记录差异"),
            "创建一个 Agent，盯住竞品页面变化，每天检查一次并保存变化历史",
            web_config=WebSearchConfig(provider="disabled"),
        )

        condition_types = {condition.type for condition in report.plans[0].required_conditions}
        self.assertIn("browser_access", condition_types)
        self.assertIn("schedule", condition_types)
        self.assertIn("storage_backend", condition_types)
        self.assertIn("mock_fixture", condition_types)

    def test_daily_report_email_rules_cover_credentials_permission_and_human_confirm(self) -> None:
        report = analyze_tool_preconditions(
            _custom_tool_primitives("send_daily_report", "生成日报并发送邮件"),
            "每天从销售数据生成日报并发邮件给负责人",
            web_config=WebSearchConfig(provider="disabled"),
        )

        condition_types = {condition.type for condition in report.plans[0].required_conditions}
        control_types = {control.type for control in report.plans[0].risk_controls}
        self.assertIn("external_service", condition_types)
        self.assertIn("credential", condition_types)
        self.assertIn("permission", condition_types)
        self.assertIn("human_approval", condition_types)
        self.assertIn("mock_fixture", condition_types)
        self.assertIn("human_approval", control_types)

    def test_local_pdf_rules_cover_local_dependency_contract_without_external_api(self) -> None:
        report = analyze_tool_preconditions(
            _custom_tool_primitives("organize_pdf", "整理本地 PDF 文件"),
            "整理 /tmp/invoices 里的本地 PDF，输出分类结果到本地目录",
            web_config=WebSearchConfig(provider="disabled"),
        )

        condition_types = {condition.type for condition in report.plans[0].required_conditions}
        self.assertIn("local_resource", condition_types)
        self.assertIn("python_package", condition_types)
        self.assertIn("data_contract", condition_types)
        self.assertNotIn("external_service", condition_types)

    def test_mock_only_external_tool_is_explicitly_marked(self) -> None:
        primitives = _weather_primitives()
        report = analyze_tool_preconditions(
            primitives,
            "创建一个实时天气 Agent，先只生成 mock-only 草稿",
            web_config=WebSearchConfig(provider="disabled"),
        )

        _environment, _contracts, readiness = EnvironmentProbeRunner().probe(
            primitives,
            requirement="创建一个实时天气 Agent，先只生成 mock-only 草稿",
            tool_precondition_report=report,
        )

        self.assertEqual(readiness.status, "mock_only_allowed")
        self.assertIn("mock_only_selected", {issue.code for issue in readiness.issues})

    def test_injected_web_search_provider_returns_factory_research_report(self) -> None:
        service = FactoryWebSearchService(
            WebSearchConfig(provider="tavily"),
            provider=StaticSearchProvider(),
        )

        report = service.search_many(["weather API official documentation"])

        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.provider, "tavily")
        self.assertEqual(len(report.results), 1)
        self.assertNotIn("api_key", report.model_dump_json())

    def test_tavily_provider_uses_standard_request_and_bearer_auth(self) -> None:
        provider = TavilyWebSearchProvider(
            WebSearchConfig(
                provider="tavily",
                api_key="tvly-test-key",
                search_depth="advanced",
                include_answer=True,
                include_raw_content="markdown",
                include_domains=["docs.tavily.com"],
            )
        )

        with patch("agent_factory.factory.web_search.httpx.post") as post:
            post.return_value = _SearchResponse()
            report = provider.search(WebSearchRequest(query="Tavily Search API", max_results=3))

        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.provider, "tavily")
        self.assertEqual(report.answers, ["Tavily answer summary."])
        self.assertEqual(report.request_ids, ["request-123"])
        self.assertEqual(report.usage, {"credits": 1})
        self.assertEqual(report.results[0].source, "tavily")
        self.assertEqual(report.results[0].score, 0.91)

        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.tavily.com/search")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tvly-test-key")
        self.assertNotIn("api_key", kwargs["json"])
        self.assertEqual(kwargs["json"]["query"], "Tavily Search API")
        self.assertEqual(kwargs["json"]["max_results"], 3)
        self.assertEqual(kwargs["json"]["search_depth"], "advanced")
        self.assertEqual(kwargs["json"]["include_answer"], True)
        self.assertEqual(kwargs["json"]["include_raw_content"], "markdown")
        self.assertEqual(kwargs["json"]["include_domains"], ["docs.tavily.com"])

    def test_research_brief_enters_external_resource_contract(self) -> None:
        primitives = _weather_primitives()
        preconditions = analyze_tool_preconditions(
            primitives,
            "创建一个实时天气 Agent",
            web_config=WebSearchConfig(provider="tavily"),
        )
        service = FactoryWebSearchService(
            WebSearchConfig(provider="tavily"),
            provider=StaticSearchProvider(),
        )
        plan = ResearchPlanBuilder().build(
            requirement="创建一个实时天气 Agent",
            tool_precondition_report=preconditions.model_dump(mode="json"),
        )
        with patch("agent_factory.factory.web_research.httpx.get") as get:
            get.return_value = _DocumentResponse()
            research = WebSearchPipeline(search_service=service).run(plan)

        _environment, contracts, _readiness = EnvironmentProbeRunner().probe(
            primitives,
            requirement="创建一个实时天气 Agent",
            tool_precondition_report=preconditions,
            web_research_report=research.raw_search_report,
            research_brief_report=research,
        )

        self.assertTrue(contracts.resources[0].details["research_brief"])
        self.assertFalse(contracts.resources[0].details.get("web_research_results"))
        self.assertNotIn("AGENTFACTORY_WEB_SEARCH_API_KEY", json.dumps(contracts.resources[0].details, ensure_ascii=False))

    def test_web_search_pipeline_filters_raw_snippets_from_brief(self) -> None:
        service = FactoryWebSearchService(
            WebSearchConfig(provider="tavily"),
            provider=StaticSearchProvider(),
        )
        plan = ResearchPlanBuilder().build(
            requirement="创建一个墨迹天气助手，支持按城市查询天气。官方文档 URL：https://example.com/moji-weather-api",
            tool_precondition_report={
                "plans": [
                    {
                        "tool_id": "weather_query",
                        "research_queries": ["墨迹天气 API 文档"],
                        "required_conditions": [
                            {"type": "web_research", "required": True, "description": "docs"}
                        ],
                    }
                ]
            },
        )

        with patch("agent_factory.factory.web_research.httpx.get") as get:
            get.return_value = _DocumentResponse()
            research = WebSearchPipeline(search_service=service).run(plan)

        self.assertEqual(research.status, "passed")
        self.assertIn("MOJI_WEATHER_APPCODE", {field.key for field in research.brief.recommended_config_fields})
        serialized = research.brief.model_dump_json()
        self.assertNotIn("Stable public documentation snippet", serialized)
        self.assertIn("forecast24hours", serialized)

    def test_web_search_pipeline_requires_user_url_instead_of_searching(self) -> None:
        provider = RecordingSearchProvider()
        service = FactoryWebSearchService(
            WebSearchConfig(provider="tavily", max_results=3),
            provider=provider,
        )
        plan = ResearchPlan(
            service_id="image_segmentation",
            service_name="Image Segmentation API",
            purpose="搜索图像分割 API",
            queries=["图像分割 API"],
            operations=[
                ResearchOperation(
                    id="segment_image",
                    description="segment image and return mask",
                )
            ],
        )

        research = WebSearchPipeline(search_service=service).run(plan)

        self.assertEqual(research.status, "failed")
        self.assertEqual(provider.queries, [])
        self.assertIn("external_resource_url_required", research.issues)

    def test_web_search_pipeline_extracts_single_user_provided_url(self) -> None:
        service = FactoryWebSearchService(WebSearchConfig(provider="disabled"))
        plan = ResearchPlan(
            service_id="image_segmentation",
            service_name="Image Segmentation API",
            purpose="搜索图像分割 API",
            source_urls=["https://docs.example.com/image-segmentation"],
            operations=[
                ResearchOperation(
                    id="segment_image",
                    description="segment image and return mask",
                )
            ],
        )

        with patch("agent_factory.factory.web_research.httpx.get") as get:
            get.return_value = _SegmentationDocsResponse()
            research = WebSearchPipeline(search_service=service).run(plan)

        self.assertEqual(research.status, "passed")
        operation = research.brief.facts["operations"][0]
        self.assertEqual(operation["endpoint"], "https://api.vision.example.com/v1/segment")
        self.assertEqual(operation["method"], "POST")

    def test_web_search_pipeline_deep_fetches_related_same_host_docs(self) -> None:
        service = FactoryWebSearchService(WebSearchConfig(provider="disabled"))
        entry_url = "https://dev.qweather.com/docs/api/weather/weather-daily-forecast/"
        plan = ResearchPlan(
            service_id="qweather",
            service_name="QWeather",
            purpose="按城市查询未来几天天气",
            source_urls=[entry_url],
            operations=[
                ResearchOperation(
                    id="daily_forecast",
                    description="daily weather forecast by location id or coordinates",
                )
            ],
        )
        pages = {
            entry_url.rstrip("/"): _HtmlResponse(
                entry_url,
                """
                <html><head><title>每日天气预报</title></head><body>
                  <main>
                    <h1>每日天气预报</h1>
                    <a href="/docs/configuration/authentication/">JWT身份认证</a>
                    <a href="/docs/configuration/api-host/">API Host</a>
                    <a href="/docs/api/geoapi/city-lookup/">GeoAPI 城市搜索</a>
                    <a href="/docs/reference/error-code/">错误码</a>
                    <a href="https://icons.qweather.com/">图标</a>
                    <h2>请求路径</h2><pre>/v7/weather/{days}</pre>
                    <h2>参数</h2>
                    <p>days 必选，支持 3d、7d、10d、15d、30d。</p>
                    <p>location 必选，需要查询地区的 LocationID 或经度,纬度坐标。</p>
                    <p>lang 和 unit 是可选查询参数。</p>
                    <h2>请求示例</h2>
                    <pre>curl -X GET --compressed -H 'Authorization: Bearer your_token' 'https://your_api_host/v7/weather/3d?location=101010100'</pre>
                    <h2>返回数据</h2>
                    <pre>{"code":"200","daily":[{"fxDate":"2026-05-05","tempMax":"24","tempMin":"16","textDay":"晴"}]}</pre>
                  </main>
                </body></html>
                """,
            ),
            "https://dev.qweather.com/docs/configuration/authentication": _HtmlResponse(
                "https://dev.qweather.com/docs/configuration/authentication/",
                """
                <html><head><title>JWT身份认证</title></head><body>
                  <main><h1>JWT身份认证</h1>
                  <p>QWeather API 使用 JWT Bearer Token 进行身份认证。</p>
                  <pre>Authorization: Bearer ${QWEATHER_JWT}</pre>
                  </main>
                </body></html>
                """,
            ),
            "https://dev.qweather.com/docs/configuration/api-host": _HtmlResponse(
                "https://dev.qweather.com/docs/configuration/api-host/",
                """
                <html><head><title>API Host</title></head><body>
                  <main><h1>API Host</h1>
                  <p>开发者需要将 your_api_host 替换为可用 API Host。</p>
                  <pre>https://api.qweather.com</pre>
                  </main>
                </body></html>
                """,
            ),
            "https://dev.qweather.com/docs/api/geoapi/city-lookup": _HtmlResponse(
                "https://dev.qweather.com/docs/api/geoapi/city-lookup/",
                """
                <html><head><title>城市搜索</title></head><body>
                  <main><h1>城市搜索</h1>
                  <p>城市搜索可以将城市名称转换为 LocationID。</p>
                  <pre>GET /geo/v2/city/lookup?location=beijing</pre>
                  </main>
                </body></html>
                """,
            ),
            "https://dev.qweather.com/docs/reference/error-code": _HtmlResponse(
                "https://dev.qweather.com/docs/reference/error-code/",
                """
                <html><head><title>错误码</title></head><body>
                  <main><h1>状态码</h1><p>code 200 表示请求成功，401 表示认证失败。</p></main>
                </body></html>
                """,
            ),
        }

        def response_for(url: str, *_args: object, **_kwargs: object) -> _HtmlResponse:
            key = str(url).rstrip("/")
            if key not in pages:
                raise AssertionError(f"unexpected fetch: {url}")
            return pages[key]

        with patch("agent_factory.factory.web_research.httpx.get", side_effect=response_for):
            research = WebSearchPipeline(
                search_service=service,
                config=WebSearchPipelineConfig(
                    browser_fetch="disabled",
                    max_related_pages=4,
                    max_link_depth=1,
                ),
            ).run(plan)

        fetched_urls = {document.url.rstrip("/") for document in research.fetched_documents}
        self.assertIn(entry_url.rstrip("/"), fetched_urls)
        self.assertIn("https://dev.qweather.com/docs/configuration/authentication", fetched_urls)
        self.assertIn("https://dev.qweather.com/docs/configuration/api-host", fetched_urls)
        self.assertIn("https://dev.qweather.com/docs/api/geoapi/city-lookup", fetched_urls)
        self.assertNotIn("https://icons.qweather.com", fetched_urls)
        self.assertEqual(research.status, "passed", research.issues)
        auth = research.brief.facts["auth"]
        self.assertEqual(auth["type"], "jwt_bearer")
        operation = research.brief.facts["operations"][0]
        self.assertIn("/v7/weather", operation["endpoint"])
        self.assertEqual(operation["method"], "GET")
        param_keys = {param["key"] for param in operation["params"]}
        self.assertIn("location", param_keys)
        self.assertIn("days", param_keys)

        completeness = assess_research_completeness(research)
        self.assertEqual(completeness.status, "needs_config_values")
        self.assertIn("QWEATHER_JWT", completeness.missing_config_keys)
        self.assertIn(entry_url, completeness.source_urls)

    def test_research_completeness_needs_more_url_without_user_url(self) -> None:
        plan = ResearchPlan(
            service_id="weather",
            service_name="Weather",
            operations=[
                ResearchOperation(
                    id="weather_query",
                    description="Query realtime weather.",
                    evidence_needed=["endpoint", "auth", "params"],
                )
            ],
        )

        research = WebSearchPipeline(
            search_service=FactoryWebSearchService(WebSearchConfig(provider="disabled"))
        ).run(plan)
        completeness = assess_research_completeness(research)

        self.assertEqual(completeness.status, "needs_more_url")
        self.assertIn("official_documentation_url", completeness.missing_facts)

    def test_external_config_context_resolves_env_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "agent"
            package.mkdir()
            (package / "external_config.yaml").write_text(
                "\n".join(
                    [
                        "kind: ExternalResourceConfig",
                        "status: needs_user_configuration",
                        "values:",
                        "  QWEATHER_API_HOST: ''",
                        "  QWEATHER_JWT: ''",
                        "required_keys:",
                        "  - QWEATHER_API_HOST",
                        "  - QWEATHER_JWT",
                        "secret_keys:",
                        "  - QWEATHER_JWT",
                        "source_urls:",
                        "  - https://dev.qweather.com/docs/api/weather/weather-daily-forecast/",
                    ]
                ),
                encoding="utf-8",
            )
            env_file = root / ".env"
            env_file.write_text(
                "QWEATHER_API_HOST=https://api.qweather.com\nQWEATHER_JWT=test-jwt\n",
                encoding="utf-8",
            )

            context = load_external_config_context(package, env_file=env_file)

            self.assertEqual(context.status, "ready")
            self.assertFalse(context.missing_required_keys)
            self.assertEqual(context.resolved_values["QWEATHER_API_HOST"], "https://api.qweather.com")
            self.assertEqual(context.safe_dict()["resolved_values"]["QWEATHER_JWT"], "[REDACTED]")

    def test_web_search_pipeline_prefers_operation_endpoint_over_base_url(self) -> None:
        service = FactoryWebSearchService(WebSearchConfig(provider="disabled"))
        plan = ResearchPlanBuilder().build(
            requirement="DeepSeek Chat Completions API 文档 https://api-docs.deepseek.com/zh-cn/",
            tool_precondition_report={
                "plans": [
                    {
                        "tool_id": "chat_completions",
                        "research_queries": [],
                        "required_conditions": [
                            {"type": "web_research", "required": True, "description": "docs"}
                        ],
                    }
                ]
            },
        )

        with patch("agent_factory.factory.web_research.httpx.get") as get:
            get.return_value = _DeepSeekDocsResponse()
            research = WebSearchPipeline(search_service=service).run(plan)

        operation = research.brief.facts["operations"][0]
        self.assertEqual(operation["endpoint"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(operation["method"], "POST")
        self.assertNotEqual(operation["endpoint"], "https://api.deepseek.com")

    def test_weather_tool_tests_use_domain_valid_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = _weather_primitives()
            PackageWriter().write_primitives(root, primitives)
            generator = PackageArtifactGenerator()

            generator.generate_tool_scripts(root, primitives, requirement="创建实时天气 Agent")
            generator.generate_tool_tests(root, primitives)

            test_source = (root / "generated" / "tool_tests" / "test_weather_query.py").read_text(
                encoding="utf-8"
            )
            self.assertIn("city", test_source)
            self.assertIn("江西婺源", test_source)
            self.assertNotIn('"sample": "value"', test_source)

    def test_factory_graph_stops_for_realtime_tool_missing_external_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([_weather_primitives_payload()])
            )

            state = runtime.run(requirement="创建一个实时天气 Agent，支持查询江西婺源天气", context=context)

            self.assertEqual(state.status, "needs_clarification")
            self.assertIn("resolve_readiness", state.stage_history)
            self.assertTrue(state.clarification_options)
            option_ids = {
                option["id"]
                for group in state.clarification_options
                for option in group.get("options", [])
            }
            self.assertIn("provide_external_url", option_ids)
            self.assertIsNone(state.package_path)

    def test_low_risk_tool_can_run_when_its_own_test_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = _two_tool_primitives()
            package_path = root / "package"
            PackageWriter().write_primitives(package_path, primitives)
            generator = PackageArtifactGenerator()
            generator.generate_tool_scripts(package_path, primitives)
            generator.generate_mcp_bindings(package_path, primitives)
            generator.generate_harness_scenarios(package_path, primitives)
            generator.generate_package_specs(package_path, primitives)
            reports = package_path / "generated" / "reports"
            reports.mkdir(parents=True, exist_ok=True)
            (reports / "tool_tests.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "per_tool_status": {
                            "order_query": "passed",
                            "generic_lookup": "failed",
                        },
                    }
                ),
                encoding="utf-8",
            )

            route = ToolRouter(package_path).route(
                ToolInvocation(tool_id="order_query", arguments={"query": "订单 123"})
            )

            self.assertFalse(hasattr(route, "interrupt_type"))
            self.assertEqual(route.tool_id, "order_query")


def _create_sqlite_fixture(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            """
            CREATE TABLE customer_tickets (
              ticket_id TEXT PRIMARY KEY,
              customer_name TEXT NOT NULL,
              channel TEXT NOT NULL,
              title TEXT NOT NULL,
              description TEXT NOT NULL,
              status TEXT NOT NULL CHECK (status IN ('open', 'pending', 'resolved', 'closed')),
              priority TEXT NOT NULL,
              assignee TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )


def _sqlite_primitives(db_path: Path):
    payload = valid_primitives_payload()
    payload["knowledge"]["sources"] = [
        {
            "id": "customer_ops_sqlite",
            "type": "file",
            "ref": str(db_path),
            "visible_to_model": False,
            "visible_to_tools": True,
            "access_mode": "read_write",
            "sandbox_required": True,
        }
    ]
    payload["knowledge"]["inject_as"] = "tool"
    return PackageWriter().validator.loader.load_primitives(_write_primitives_payload(payload))


def _two_tool_primitives():
    payload = valid_primitives_payload()
    payload["toolsets"]["toolsets"][0]["exposed_tools"] = ["order_query", "generic_lookup"]
    return PackageWriter().validator.loader.load_primitives(_write_primitives_payload(payload))


def _weather_primitives():
    return PackageWriter().validator.loader.load_primitives(
        _write_primitives_payload(_weather_primitives_payload())
    )


def _custom_tool_primitives(tool_id: str, description: str):
    payload = valid_primitives_payload()
    payload["instructions"]["metadata"]["name"] = "Custom Agent"
    payload["instructions"]["goal"] = description
    payload["toolsets"]["toolsets"] = [
        {
            "id": "custom_tools",
            "description": description,
            "exposed_tools": [tool_id],
            "hidden_tools": [],
            "proposal_only": True,
            "selection_strategy": "auto",
        }
    ]
    payload["knowledge"]["sources"] = []
    return PackageWriter().validator.loader.load_primitives(_write_primitives_payload(payload))


def _weather_primitives_payload() -> dict:
    payload = valid_primitives_payload()
    payload["instructions"]["metadata"]["name"] = "Weather Agent"
    payload["instructions"]["goal"] = "查询实时天气并给出简洁回复。"
    payload["toolsets"]["metadata"]["name"] = "Weather Agent"
    payload["toolsets"]["toolsets"] = [
        {
            "id": "weather_tools",
            "description": "Tools for querying realtime weather from an external API.",
            "exposed_tools": ["weather_query"],
            "hidden_tools": [],
            "proposal_only": True,
            "selection_strategy": "auto",
        }
    ]
    payload["knowledge"]["sources"] = []
    return payload


def _write_primitives_payload(payload: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    primitives = __import__("agent_factory.specs", fromlist=["AgentPackagePrimitives"]).AgentPackagePrimitives.model_validate(payload)
    PackageWriter().write_primitives(root, primitives)
    return root


if __name__ == "__main__":
    unittest.main()
