from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StageOperatingContext:
    stage_id: str
    responsibility: str
    allowed_outputs: tuple[str, ...]
    forbidden_outputs: tuple[str, ...]

    def to_text(self) -> str:
        lines = [
            f"当前阶段：{self.stage_id}",
            f"阶段职责：{self.responsibility}",
            "允许产物：",
            *[f"- {item}" for item in self.allowed_outputs],
            "禁止事项：",
            *[f"- {item}" for item in self.forbidden_outputs],
        ]
        return "\n".join(lines)


FACTORY_OPERATING_CONTEXT = """Factory 运行边界：
- FastAgentFactory 是 CLI-first Agent Factory，当前交互以 shell/CLI 为主。
- Factory 基于 LangGraph 组织生产流程，目标产物是 RuntimeKernel AgentPackage。
- mainModel 用于核心制造流程、资源分析/重写，以及生成 Agent 的默认模型能力。
- taskModel 用于 Factory 内部轻量任务，例如 chat、意图识别、简单分类和 CLI 辅助。
- mainModel/taskModel/API key/base URL/thinking 参数都属于 Factory 自身运行配置，不是生成 Agent 的业务资源。
- 不假设未声明的 Web UI、移动端、多媒体生成、真实外部服务、数据库或部署环境已经存在。
- 每个阶段只做本阶段职责，不提前生成后续阶段产物。"""


FACTORY_DEFAULT_IMPLEMENTATION_CONTEXT = """Factory 已决定的默认实现：
- 生成出来的 Agent 默认是 RuntimeKernel 编译后的 LangGraph AgentPackage。
- 生成 Agent 由 FastAgentFactory 后台运行层编译、运行、checkpoint、trace 和 repair。
- 用户在第一阶段不需要选择运行框架、模型供应商、SDK、依赖、部署形态、Docker、测试方式或工程目录结构。
- 资源嗅探在第六阶段完成，AssemblySpec 在第七阶段完成，Package 文件和工具代码在第八阶段完成。
- 除非用户主动要求覆盖默认行为，否则不要把这些默认实现当作需求问题询问用户。"""


_STAGE_CONTEXTS: dict[str, StageOperatingContext] = {
    "requirement_capture": StageOperatingContext(
        stage_id="requirement_capture",
        responsibility="用尽量少的问题捕获用户想制造什么 Agent，重点澄清业务目标、行动边界、业务资源范围和期望输出。",
        allowed_outputs=("requirement_frame", "refined_requirement", "业务制造计划", "必要的业务级澄清问题"),
        forbidden_outputs=("默认实现选择题", "技术选型", "运行框架选择", "部署方式选择", "工具实现", "资源准备", "AssemblySpec", "工具代码"),
    ),
    "runtime_pattern_selection": StageOperatingContext(
        stage_id="runtime_pattern_selection",
        responsibility="从 RuntimeKernel pattern catalog 中选择一个主运行模式。",
        allowed_outputs=("selected_pattern_id", "选择原因", "少量备选说明"),
        forbidden_outputs=("新增节点/边", "wrapper 规划", "工具规划", "资源规划", "AssemblySpec"),
    ),
    "graph_behavior_planning": StageOperatingContext(
        stage_id="graph_behavior_planning",
        responsibility="在已选 pattern 结构内解释各节点业务行为、路由含义和终止语义。",
        allowed_outputs=("graph_behavior_plan", "节点业务行为", "已有路由业务含义"),
        forbidden_outputs=("增删节点", "增删边", "wrapper 规划", "工具规划", "资源准备"),
    ),
    "node_strategy_planning": StageOperatingContext(
        stage_id="node_strategy_planning",
        responsibility="给已有节点规划 wrapper、上下文、记忆、policy 和工具可见性策略引用。",
        allowed_outputs=("node_strategy_plan", "strategy_refs", "proposed_strategies 声明"),
        forbidden_outputs=("策略 Python 实现", "工具代码", "资源探测", "AssemblySpec"),
    ),
    "tool_capability_planning": StageOperatingContext(
        stage_id="tool_capability_planning",
        responsibility="把图行为和节点策略转换为工具能力契约与节点可见性。",
        allowed_outputs=("tool_capabilities", "node_tool_visibility"),
        forbidden_outputs=("工具 Python 实现", "资源值", "资源嗅探", "依赖安装", "供应商选型"),
    ),
    "resource_and_condition_planning": StageOperatingContext(
        stage_id="resource_and_condition_planning",
        responsibility="根据工具能力准备生成 Agent 所需的业务资源访问契约与 Docker sandbox 前置运行契约，并把资源值转换为 sandbox 内视角。",
        allowed_outputs=("resource_requirements", "resource_check_results", "factory_resources.json", "sandbox_contract.json", "resource_preparation_report.json"),
        forbidden_outputs=("Factory 自身模型配置", "工具代码", "AssemblySpec", "AgentPackage", "harness 执行", "特化资源规则", "本机路径直接写入 Agent 资源"),
    ),
    "assembly_spec_generation": StageOperatingContext(
        stage_id="assembly_spec_generation",
        responsibility="生成并校验冻结的 AgentAssemblySpec，并确定性冻结 package 物化计划和节点渲染说明。",
        allowed_outputs=("assembly_spec", "package_materialization_plan", "render_manifest", "assembly_validation_report", "产物文件路径"),
        forbidden_outputs=("工具代码", "package 文件", "harness", "重新选择 pattern", "修改前置阶段计划"),
    ),
    "package_generation": StageOperatingContext(
        stage_id="package_generation",
        responsibility="把已验证的 AssemblySpec、resources、工具能力和节点策略物化为 AgentPackage draft。",
        allowed_outputs=("agent_package.json", "render_manifest.json", "真实工具代码草稿", "package_report", "bindings/prompts/policies/retrieval/formatters 文件"),
        forbidden_outputs=("harness", "动态工具测试结果", "重新规划 AssemblySpec", "调用真实业务外部服务", "硬编码用户资源"),
    ),
    "harness_generation_and_test": StageOperatingContext(
        stage_id="harness_generation_and_test",
        responsibility="为 AgentPackage draft 生成 sandbox/runtime/test 契约，验证宿主机交互边界，并执行 harness 测试生成返厂报告。",
        allowed_outputs=("runtime_environment_contract", "host_interaction_contract", "harness_execution_plan", "harness_report", "artifacts"),
        forbidden_outputs=("修改 AgentPackage", "生成工具代码", "重新规划 AssemblySpec", "隐式访问宿主机资源", "Docker 不可用时自动降级本机运行"),
    ),
    "factory_chat": StageOperatingContext(
        stage_id="factory_chat",
        responsibility="处理 Factory shell 的轻量聊天、检查和辅助任务。",
        allowed_outputs=("简洁中文回复", "必要的工具调用"),
        forbidden_outputs=("生成 Agent 资源文件", "修改制造流程阶段产物"),
    ),
}


def factory_operating_context() -> str:
    return FACTORY_OPERATING_CONTEXT


def stage_operating_context(stage_id: str) -> str:
    context = _STAGE_CONTEXTS.get(stage_id)
    if context is None:
        return StageOperatingContext(
            stage_id=stage_id,
            responsibility="执行当前 Factory 阶段职责。",
            allowed_outputs=("当前阶段明确要求的产物",),
            forbidden_outputs=("提前生成后续阶段产物", "把 Factory 自身配置当成生成 Agent 资源"),
        ).to_text()
    return context.to_text()


def prompt_context_values(stage_id: str) -> dict[str, str]:
    return {
        "factory_operating_context": factory_operating_context(),
        "factory_default_implementation_context": FACTORY_DEFAULT_IMPLEMENTATION_CONTEXT,
        "stage_operating_context": stage_operating_context(stage_id),
    }
