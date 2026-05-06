from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_factory.application import ApprovalRecord, PatchPlanService
from agent_factory.application import CreateAgentRequest, CreateAgentService
from agent_factory.factory.package_artifacts import PackageArtifactReport
from agent_factory.factory.package_verification import (
    ToolStaticCheckReport,
    ToolTestRunReport,
)
from agent_factory.factory.environment import _readiness_from_contracts
from agent_factory.factory.readiness_presenter import (
    ReadinessPresenter,
    render_readiness_clarification_prompt,
)
from agent_factory.factory.resource_resolvers import (
    ResourceResolverRegistry,
    UrlDocumentationResolver,
)
from agent_factory.factory.tool_build_pipeline import ToolBuildPipeline, ToolStateMachine
from agent_factory.factory_runtime.production import FactoryProductionState
from agent_factory.factory_runtime.production.policies import FactoryNodeAccessPolicy
from agent_factory.factory_context import ReadinessDecision, ReadinessItem, ResourceNeed
from agent_factory.registry import FilesystemRegistry
from agent_factory.specs import (
    AgentPackagePrimitives,
    Metadata,
    PreconditionSpec,
    ReadinessIssue,
    ReadinessReport,
)
from tests.test_agent_instance_runtime import _write_tool_package
from tests.test_factory_agent import service_with_responses, tool_primitives_payload, valid_primitives_payload


class RefactorArchitectureTests(unittest.TestCase):
    def test_factory_progress_history_uses_documented_14_stage_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = CreateAgentService(
                model_service=service_with_responses([valid_primitives_payload()])
            ).create_agent(
                CreateAgentRequest(
                    prompt="创建一个通用资料问答 Agent",
                    start_path=Path(tmpdir),
                    stream=False,
                )
            )

        required = [
            "capture_requirement",
            "understand_requirement",
            "plan_capabilities",
            "identify_conditions",
            "plan_resource_needs",
            "collect_evidence",
            "build_resource_contracts",
            "decide_readiness",
            "plan_implementation",
            "generate_package_specs",
            "generate_tools",
            "sandbox_test_and_repair",
            "generate_harness",
            "complete_summary",
        ]
        for stage in required:
            self.assertIn(stage, result.stage_history)

    def test_resource_resolver_registry_declares_credentials_without_secret_values(self) -> None:
        report = ResourceResolverRegistry().resolve(
            ResourceNeed(
                resource_id="qweather_key",
                family="credential",
                kind="api_key",
                configuration_keys=["QWEATHER_API_KEY"],
            )
        )

        self.assertEqual(report.status, "partial")
        self.assertIn("QWEATHER_API_KEY", report.details["configuration_keys"])
        self.assertNotIn("secret", str(report.model_dump(mode="json")).lower())

    def test_resource_resolver_registry_has_no_sqlite_specific_resolver(self) -> None:
        registry = ResourceResolverRegistry()

        self.assertNotIn(
            "sqlite_schema",
            {resolver.resolver_id for resolver in registry.resolvers},
        )

    def test_url_documentation_resolver_fetches_only_declared_url_summary(self) -> None:
        resolver = UrlDocumentationResolver(
            fetcher=lambda url: "<html><title>API Docs</title><body>secret=hidden</body></html>"
        )
        resource = ResourceNeed(
            resource_id="weather_docs",
            family="service",
            kind="url_documentation",
            location="https://docs.example.test/weather",
            required_evidence=["documentation reachable"],
        )

        report = resolver.resolve(resource)

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.details["title"], "API Docs")
        self.assertEqual(report.details["url"], "https://docs.example.test/weather")
        self.assertNotIn("secret=hidden", str(report.model_dump(mode="json")))

    def test_readiness_failures_store_structured_issue_details(self) -> None:
        report = _readiness_from_contracts(
            Metadata(name="orders-agent"),
            [],
            [
                PreconditionSpec(
                    id="orders_exists",
                    type="resource_exists",
                    description="Resource exists: /tmp/orders.sqlite",
                    status="failed",
                )
            ],
        )

        self.assertEqual(report.status, "needs_user_input")
        self.assertEqual(report.issues[0].message, "Readiness precondition failed.")
        self.assertEqual(report.issues[0].details["precondition_type"], "resource_exists")
        self.assertEqual(report.issues[0].details["target"], "/tmp/orders.sqlite")
        self.assertNotIn("Resource exists:", report.issues[0].message)
        self.assertNotIn("文件或目录不存在", report.issues[0].message)

    def test_readiness_presenter_uses_task_model_for_structured_user_copy(self) -> None:
        model_copy = {
            "summary": "订单数据库还没有通过校验，暂时不能继续生成。",
            "items": [
                {
                    "code": "resource_exists",
                    "category": "database",
                    "subject": "订单数据库文件",
                    "problem": "路径 /tmp/orders.sqlite 不存在，或当前进程无法访问。",
                    "impact": "无法读取订单表结构，也无法生成可验证的查询工具。",
                    "next_action": "提供真实 SQLite 路径，或选择创建示例数据库。",
                }
            ],
            "closing_question": "你希望我用哪种方式继续？",
        }
        readiness = ReadinessReport(
            schema_version="0.1",
            metadata=Metadata(name="orders-agent"),
            status="needs_user_input",
            issues=[
                ReadinessIssue(
                    code="resource_exists",
                    message="Readiness precondition failed.",
                    severity="error",
                    details={
                        "precondition_type": "resource_exists",
                        "target": "/tmp/orders.sqlite",
                    },
                )
            ],
        )
        decision = ReadinessDecision(
            status="needs_user_input",
            blocking=[
                ReadinessItem(
                    condition_id="resource_exists",
                    level="blocking",
                    message="Readiness precondition failed.",
                    resolution_hint="补充这项校验需要的真实资源、配置或证据；也可以选择创建示例资源或只生成草稿。",
                )
            ],
        )

        result = ReadinessPresenter(service_with_responses([model_copy])).present_sync(
            readiness,
            decision,
        )
        prompt = render_readiness_clarification_prompt(result.presentation)

        self.assertEqual(result.source, "llm")
        self.assertIn("问题：路径 /tmp/orders.sqlite 不存在", prompt)
        self.assertIn("影响：无法读取订单表结构", prompt)
        self.assertIn("建议：提供真实 SQLite 路径", prompt)
        self.assertNotIn("Resource exists:", prompt)

    def test_tool_state_machine_guards_invalid_transitions(self) -> None:
        machine = ToolStateMachine()

        self.assertEqual(machine.transition("draft", "generated"), "generated")
        with self.assertRaises(ValueError):
            machine.transition("draft", "available")

    def test_factory_node_policy_hides_raw_state_from_tool_generation(self) -> None:
        state = FactoryProductionState(
            run_id="run-1",
            requirement="raw requirement must not reach tool generation",
            raw_model_data={"raw": "model payload"},
        )
        policy = FactoryNodeAccessPolicy()

        projected = policy.project("generate_tool_scripts", state)

        self.assertEqual(projected.requirement, "")
        self.assertIsNone(projected.raw_model_data)
        proposed = projected.model_copy(update={"raw_model_data": {"leak": True}})
        with self.assertRaises(ValueError):
            policy.merge(
                "generate_tool_scripts",
                before=state,
                projected=projected,
                proposed=proposed,
            )

    def test_tool_build_pipeline_repairs_failed_tests_until_passing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            primitives = AgentPackagePrimitives.model_validate(tool_primitives_payload())
            verifier = _FlakyToolVerifier(failures_before_pass=2)
            generator = _RepairingArtifactGenerator()

            report = ToolBuildPipeline(
                artifact_generator=generator,
                verification_runner=verifier,
                max_repair_attempts=3,
            ).build(Path(tmpdir), primitives)

            self.assertTrue(report.ok, report.issues)
            self.assertEqual(report.repair_attempts, 2)
            self.assertEqual(generator.repair_calls, 2)
            self.assertEqual(set(report.tool_states.values()), {"available"})

    def test_upgrade_patch_approval_lifecycle_is_recorded_in_registry_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_package = _write_tool_package(Path(tmpdir) / "base")
            service = PatchPlanService()
            plan = service.plan_upgrade(
                base_package,
                prompt="添加高风险写入能力",
                target_version="1.1.0",
                upgrade_request_id="upgrade-001",
            )
            high_risk_change = plan.changes[0].model_copy(
                update={"risk_level": "high", "requires_approval": True}
            )
            plan = plan.model_copy(update={"changes": [high_risk_change, *plan.changes[1:]]})
            with self.assertRaises(ValueError):
                service.apply_plan(plan, Path(tmpdir) / "candidate")

            approval = ApprovalRecord(
                change_id=high_risk_change.id,
                actor="tester",
                decision="approved",
                patch_plan_id=plan.plan_id,
            )
            approved = service.attach_approval(plan, approval)
            candidate = service.apply_plan(approved, Path(tmpdir) / "candidate")

            lifecycle = candidate / "generated" / "reports" / "upgrade_lifecycle.json"
            self.assertTrue(lifecycle.exists())
            registry = FilesystemRegistry(root_path=Path(tmpdir) / "registry")
            record = registry.register(candidate, status="candidate")

            self.assertEqual(record.provenance.upgrade_request_id, "upgrade-001")
            self.assertEqual(record.provenance.patch_plan_id, plan.plan_id)
            self.assertIn(approval.approval_id, record.provenance.approval_ids)

    def test_registry_records_provenance_and_promotion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir) / "package")
            registry = FilesystemRegistry(root_path=Path(tmpdir) / "registry")

            record = registry.register(package_path, status="candidate")

            self.assertIsNotNone(record.provenance)
            self.assertIsNotNone(record.promotion_gate)
            self.assertTrue(record.promotion_gate.package_validation_passed)
            self.assertFalse(record.promotion_gate.harness_passed)
            with self.assertRaises(ValueError):
                registry.release(record.agent_name, record.version, "available")


if __name__ == "__main__":
    unittest.main()


class _RepairingArtifactGenerator:
    def __init__(self) -> None:
        self.repair_calls = 0

    def generate_tool_scripts(self, *args, **kwargs) -> PackageArtifactReport:
        return PackageArtifactReport(tool_count=1)

    def generate_tool_tests(self, *args, **kwargs) -> PackageArtifactReport:
        return PackageArtifactReport(tool_test_count=1)

    def repair_generated_tool_tests(self, *args, **kwargs) -> PackageArtifactReport:
        self.repair_calls += 1
        return PackageArtifactReport(artifact_paths=[Path(f"repair-{self.repair_calls}.py")])


class _FlakyToolVerifier:
    def __init__(self, *, failures_before_pass: int) -> None:
        self.failures_before_pass = failures_before_pass
        self.test_runs = 0

    def static_check_tool_scripts(self, package_path: Path) -> ToolStaticCheckReport:
        return ToolStaticCheckReport(status="passed")

    def run_generated_tool_tests(self, package_path: Path) -> ToolTestRunReport:
        self.test_runs += 1
        if self.test_runs <= self.failures_before_pass:
            return ToolTestRunReport(status="failed", return_code=1)
        return ToolTestRunReport(status="passed", return_code=0)
