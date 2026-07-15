from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


EvolutionTargetSurface = Literal[
    "package_tool",
    "pattern_assembly",
    "dependency_contract",
    "runtime_resource",
    "knowledge",
    "scheduler",
    "state",
    "validation_repair",
    "runtime_blocker",
]


@dataclass(frozen=True, slots=True)
class EvolutionTargetPlan:
    surface: EvolutionTargetSurface
    write_strategy: str
    allowed_authoring_actions: list[str]
    target_files: list[str]
    required_first_reads: list[str]
    requires_probe: bool
    validation_scope: str = "full_static"
    runtime_blocker: dict[str, Any] | None = None
    rationale: str = ""
    constraints: list[str] = field(default_factory=list)

    def to_context(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "write_strategy": self.write_strategy,
            "allowed_authoring_actions": self.allowed_authoring_actions,
            "target_files": self.target_files,
            "required_first_reads": self.required_first_reads,
            "requires_probe": self.requires_probe,
            "validation_scope": self.validation_scope,
            "runtime_blocker": self.runtime_blocker,
            "rationale": self.rationale,
            "constraints": self.constraints,
        }


def decide_evolution_target(
    *,
    user_goal: str,
    package_summary: dict[str, Any],
    trace_context: dict[str, Any],
    error_pack: dict[str, Any],
) -> EvolutionTargetPlan:
    text = " ".join(
        [
            user_goal,
            str(package_summary.get("agent_name") or ""),
            str(package_summary.get("agent_description") or ""),
            _error_text(error_pack),
        ]
    ).casefold()
    blocker = _runtime_blocker(error_pack=error_pack, trace_context=trace_context)
    if blocker is not None and _goal_is_runtime_blocker(text):
        return EvolutionTargetPlan(
            surface="runtime_blocker",
            write_strategy="stop_and_report_runtime_blocker",
            allowed_authoring_actions=[],
            target_files=[],
            required_first_reads=[],
            requires_probe=False,
            runtime_blocker=blocker,
            rationale="The requested evolution is blocked by runtime infrastructure rather than package-owned behavior.",
            constraints=["Do not modify package files to compensate for RuntimeKernel, Docker, or model infrastructure failures."],
        )
    if _has_any(text, ("pdf", "tool", "导出", "转换", "生成文件", "html", "markdown", "依赖", "weasyprint", "wkhtmltopdf")):
        return EvolutionTargetPlan(
            surface="package_tool",
            write_strategy="create_agent_authoring.upsert_package_tool",
            allowed_authoring_actions=["upsert_package_tool", "configure_dependencies"],
            target_files=[
                "tools/<tool_id>/tool.py",
                "tools/<tool_id>/manifest.json",
                "agent_package.json",
                "contracts/tools.json",
                "contracts/dependencies.json",
                "assembly_spec.json",
            ],
            required_first_reads=["agent_package.json", "assembly_spec.json", "contracts/dependencies.json", "tools/"],
            requires_probe=True,
            rationale="The user goal changes executable package-owned behavior and may require dependency updates.",
            constraints=[
                "Use one coherent upsert_package_tool call for tool source, ToolSpec, Python requirements, and exposure.",
                "Use configure_dependencies only for dependency fields not naturally represented by upsert_package_tool.",
                "Do not use generic edit/write on managed package files.",
            ],
        )
    if _has_any(text, ("prompt", "planner", "executor", "final_answer", "plan_and_execute", "计划", "执行器", "回答")):
        return EvolutionTargetPlan(
            surface="pattern_assembly",
            write_strategy="create_agent_authoring.configure_pattern_assembly",
            allowed_authoring_actions=["configure_pattern_assembly"],
            target_files=["assembly_spec.json"],
            required_first_reads=["assembly_spec.json"],
            requires_probe=False,
            rationale="The user goal changes runtime pattern prompts or tool exposure rather than package tool code.",
            constraints=["For plan_and_execute, planner must only expose runtime_plan."],
        )
    if _has_any(
        text,
        (
            "package knowledge",
            "bundled knowledge",
            "内置知识",
            "随包知识",
            "打包资料",
            "内置文档",
        ),
    ):
        return EvolutionTargetPlan(
            surface="knowledge",
            write_strategy="create_agent_authoring package knowledge actions",
            allowed_authoring_actions=["upsert_knowledge_file", "remove_knowledge_file"],
            target_files=["knowledge/", ".factory/knowledge_sources.json", "contracts/knowledge.json"],
            required_first_reads=["contracts/knowledge.json"],
            requires_probe=False,
            rationale="The user explicitly requested fixed knowledge content bundled with the AgentPackage.",
            constraints=[
                "Default to no package knowledge unless authoritative, distributable source material is confirmed.",
                "Do not store identity, persona, prompts, tool instructions, or model-generated facts in knowledge/.",
                "upsert_knowledge_file requires knowledge_purpose and knowledge_source provenance.",
            ],
        )
    if _has_any(text, ("scheduler", "定时", "计划任务", "cron")):
        return EvolutionTargetPlan(
            surface="scheduler",
            write_strategy="create_agent_authoring.upsert_scheduler_seed",
            allowed_authoring_actions=["upsert_scheduler_seed"],
            target_files=["contracts/scheduler_seed.json"],
            required_first_reads=["contracts/scheduler_seed.json"],
            requires_probe=False,
            rationale="The user goal changes package scheduled behavior.",
        )
    return EvolutionTargetPlan(
        surface="validation_repair",
        write_strategy="validator_directed_authoring",
        allowed_authoring_actions=[
            "set_identity",
            "configure_pattern_assembly",
            "upsert_package_tool",
            "configure_dependencies",
            "upsert_resources",
            "upsert_knowledge_file",
            "remove_knowledge_file",
            "upsert_scheduler_seed",
            "upsert_state",
            "reset_contract",
        ],
        target_files=["validator-indicated files only"],
        required_first_reads=["agent_package.json", "assembly_spec.json"],
        requires_probe=False,
        rationale="No narrower deterministic surface matched; proceed by current package state and validator evidence.",
        constraints=["Do not broaden scope beyond validator-indicated or user-goal-indicated files."],
    )


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle.casefold() in text for needle in needles)


def _error_text(error_pack: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in error_pack.get("error_chain") if isinstance(error_pack.get("error_chain"), list) else []:
        if isinstance(item, dict):
            parts.extend(str(item.get(key) or "") for key in ("message", "where", "type"))
    return " ".join(parts)


def _runtime_blocker(*, error_pack: dict[str, Any], trace_context: dict[str, Any]) -> dict[str, Any] | None:
    text = f"{_error_text(error_pack)} {trace_context}".casefold()
    if _has_any(text, ("docker_daemon_unavailable", "docker.preflight", "runtime_root", "model contract", "response_format")):
        return {"kind": "runtime_infrastructure", "evidence": text[:1000]}
    return None


def _goal_is_runtime_blocker(text: str) -> bool:
    return _has_any(text, ("docker", "runtime", "runkernel", "toolgateway", "approval", "授权", "卡住", "报错"))
