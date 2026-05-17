from __future__ import annotations

from agent_factory.factory_graph.constants import STAGE_IDS
from agent_factory.runtime_render import NodeRenderSpec


FACTORY_NODE_RENDER_SPECS: dict[str, NodeRenderSpec] = {
    "requirement_capture": NodeRenderSpec(
        node_id="requirement_capture",
        label="需求捕获",
        kind="llm_subgraph",
        purpose="澄清用户要制造什么 Agent，并形成用户确认过的业务制造计划。",
        doing="判断需求是否清晰，必要时追问用户，并整理成可继续制造的需求与计划。",
        expected_output="经过澄清的 Agent 需求和初步制造计划。",
    ),
    "runtime_pattern_selection": NodeRenderSpec(
        node_id="runtime_pattern_selection",
        label="运行模式选择",
        kind="llm_planning",
        purpose="根据业务制造计划选择 RuntimeKernel pattern。",
        doing="读取 pattern 摘要并选择最适合当前 Agent 的运行模式。",
        expected_output="选定的 RuntimeKernel pattern 及选择理由。",
    ),
    "graph_behavior_planning": NodeRenderSpec(
        node_id="graph_behavior_planning",
        label="图行为规划",
        kind="llm_planning",
        purpose="把选定 pattern 具体化为节点职责、顺序、路由和中断点。",
        doing="规划图中每个节点的业务行为和节点间流转方式。",
        expected_output="图行为规划结果。",
    ),
    "node_strategy_planning": NodeRenderSpec(
        node_id="node_strategy_planning",
        label="节点策略规划",
        kind="llm_planning",
        purpose="为已有节点规划 wrapper、上下文、记忆、policy 和工具可见性策略引用。",
        doing="根据节点职责选择运行策略，不生成具体实现代码。",
        expected_output="节点级策略规划结果。",
    ),
    "tool_capability_planning": NodeRenderSpec(
        node_id="tool_capability_planning",
        label="工具能力规划",
        kind="llm_planning",
        purpose="规划生成 Agent 需要的工具能力、可见节点和审批倾向。",
        doing="整理工具能力契约，不生成工具代码。",
        expected_output="工具能力规划结果。",
    ),
    "resource_and_condition_planning": NodeRenderSpec(
        node_id="resource_and_condition_planning",
        label="资源与条件规划",
        kind="resource_planning",
        purpose="准备工具和策略运行所需的资源、环境、权限和前置条件。",
        doing="根据工具能力判断资源需求，并等待后续统一工具系统重构具体行为。",
        expected_output="资源条件计划和资源文件路径。",
    ),
    "assembly_spec_generation": NodeRenderSpec(
        node_id="assembly_spec_generation",
        label="装配规格生成",
        kind="validator_react",
        purpose="生成并校验 AgentAssemblySpec 和 package materialization plan。",
        doing="让模型生成装配规格，并把校验 observation 反馈给模型修正。",
        expected_output="已验证的 AssemblySpec、物化计划和校验报告。",
    ),
    "package_generation": NodeRenderSpec(
        node_id="package_generation",
        label="包生成",
        kind="code_materialization",
        purpose="把装配规格和物化计划落成 AgentPackage draft。",
        doing="生成真实工具代码草稿、配置文件和 package 报告。",
        expected_output="可静态校验的 AgentPackage draft。",
    ),
    "harness_generation_and_test": NodeRenderSpec(
        node_id="harness_generation_and_test",
        label="Harness 生成与测试",
        kind="sandbox_validation",
        purpose="生成 harness 并在 sandbox 契约下验证 AgentPackage。",
        doing="准备运行环境契约、执行测试计划并收集报告。",
        expected_output="harness report 和可供返厂维修的失败证据。",
    ),
    "repair_or_finalize": NodeRenderSpec(
        node_id="repair_or_finalize",
        label="修复或定稿",
        kind="repair_finalize",
        purpose="根据 harness/trace 修复或确认最终出厂结果。",
        doing="读取测试报告，修复可修问题或输出最终交付结果。",
        expected_output="最终 AgentPackage 或返厂维修报告。",
    ),
    "factory_tool_approval": NodeRenderSpec(
        node_id="factory_tool_approval",
        label="工具审批",
        kind="human_interrupt",
        purpose="在执行受保护工具前请求用户审批。",
        doing="展示工具调用参数并等待用户批准、拒绝或要求重写。",
        expected_output="工具审批 observation。",
    ),
    "factory_tools": NodeRenderSpec(
        node_id="factory_tools",
        label="工具执行",
        kind="tool_node",
        purpose="执行模型提出且通过审批的 Factory 工具调用。",
        doing="运行工具并把结果作为 observation 返回给模型。",
        expected_output="工具执行结果和 observation。",
    ),
}


def get_factory_node_render_spec(node_id: str) -> NodeRenderSpec:
    return FACTORY_NODE_RENDER_SPECS[node_id].model_copy(deep=True)


def validate_factory_render_manifest() -> None:
    missing = [stage_id for stage_id in STAGE_IDS if stage_id not in FACTORY_NODE_RENDER_SPECS]
    if missing:
        raise ValueError(f"Factory render manifest missing stage specs: {', '.join(missing)}")
