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
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.factory_runtime.production import FactoryProductionRuntime
from agent_factory.model import ModelConfig, ModelService
from agent_factory.tools import ControlledShellRunner
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


class ConditionPreflightTests(unittest.TestCase):
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
        self.assertIn("configure_external_api", {option.id for option in readiness.options})
        self.assertIn("use_mock_only", {option.id for option in readiness.options})

    def test_external_realtime_tool_writes_runtime_config_template_after_research(self) -> None:
        primitives = _weather_primitives()
        report = analyze_tool_preconditions(
            primitives,
            "创建一个墨迹天气 Agent，查询城市当日和未来几天空气趋势",
            web_config=WebSearchConfig(provider="tavily"),
        )
        self.assertTrue(any("墨迹天气" in query for query in report.plans[0].research_queries))
        web_report = WebSearchReport(
            status="passed",
            provider="tavily",
            queries=["墨迹天气 API 官方文档 endpoint 鉴权 示例返回"],
            results=[
                WebSearchResult(
                    title="墨迹天气 API 文档",
                    url="https://example.com/moji-weather-api",
                    snippet="Endpoint and auth documentation.",
                    source="tavily",
                )
            ],
        )

        environment, contracts, readiness = EnvironmentProbeRunner().probe(
            primitives,
            requirement="创建一个墨迹天气 Agent，查询城市当日和未来几天空气趋势",
            tool_precondition_report=report,
            web_research_report=web_report,
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
            self.assertIn("ExternalConfigTemplate", text)
            self.assertIn("base_url", text)
            self.assertIn("auth", text)
            self.assertIn("https://example.com/moji-weather-api", text)

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

    def test_web_research_summary_enters_external_resource_contract(self) -> None:
        primitives = _weather_primitives()
        preconditions = analyze_tool_preconditions(
            primitives,
            "创建一个实时天气 Agent",
            web_config=WebSearchConfig(provider="tavily"),
        )
        web_report = FactoryWebSearchService(
            WebSearchConfig(provider="tavily"),
            provider=StaticSearchProvider(),
        ).search_many(["weather API official documentation"])

        _environment, contracts, _readiness = EnvironmentProbeRunner().probe(
            primitives,
            requirement="创建一个实时天气 Agent",
            tool_precondition_report=preconditions,
            web_research_report=web_report,
        )

        self.assertTrue(contracts.resources[0].details["web_research_results"])
        self.assertNotIn("AGENTFACTORY_WEB_SEARCH_API_KEY", json.dumps(contracts.resources[0].details, ensure_ascii=False))

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
            self.assertIn("configure_external_api", option_ids)
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
