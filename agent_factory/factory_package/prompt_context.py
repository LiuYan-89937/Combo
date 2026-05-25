from __future__ import annotations


FACTORY_OPERATING_CONTEXT = """Factory 运行边界：
- FastAgentFactory 是 CLI-first Agent Factory，当前交互以 shell/CLI 为主。
- Factory 的目标产物是 RuntimeKernel AgentPackage。
- mainModel/taskModel/API key/base URL/thinking 参数都属于 Factory 自身运行配置，不是生成 Agent 的业务资源。
- 当前已落地 Product Brief、Runtime Design、Capability Contract 与 Package Build 制造域；后续制造域等待设计。
"""


FACTORY_DEFAULT_IMPLEMENTATION_CONTEXT = """Factory 已决定的默认实现：
- 生成出来的 Agent 默认是 RuntimeKernel 编译后的 LangGraph AgentPackage。
- 生成 Agent 由 FastAgentFactory 后台运行层编译、运行、checkpoint、trace 和升级。
- 工具、记忆、上下文、知识、定时任务、trace、sandbox、artifact/report 都通过 RuntimeContract 接入。
"""


def factory_operating_context() -> str:
    return FACTORY_OPERATING_CONTEXT


def prompt_context_values(_node_id: str) -> dict[str, str]:
    return {
        "factory_operating_context": FACTORY_OPERATING_CONTEXT,
        "factory_default_implementation_context": FACTORY_DEFAULT_IMPLEMENTATION_CONTEXT,
        "manufacturing_status_context": "当前执行 Product Brief、Runtime Design、Capability Contract、Package Build，并在 AgentPackage 静态物化后结束，便于测试和精修。",
    }
