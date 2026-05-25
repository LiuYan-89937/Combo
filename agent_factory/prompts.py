from __future__ import annotations

from enum import Enum
import json

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel


class PromptId(str, Enum):
    PRODUCT_BRIEF_DRAFT = "factory.product_brief.draft"
    RUNTIME_DESIGN_DRAFT = "factory.runtime_design.draft"
    CAPABILITY_CONTRACT_DRAFT = "factory.capability_contract.draft"
    PACKAGE_BUILD_DRAFT = "factory.package_build.draft"
    SCHEDULER_FEEDBACK_SUMMARY = "scheduler.feedback.summary"


def get_prompt(prompt_id: PromptId) -> ChatPromptTemplate:
    if prompt_id == PromptId.PRODUCT_BRIEF_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的 Product Brief 制造器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "你的任务是把用户的自然语言意图整理成可制造的业务简报，而不是做需求问卷。\n"
                    "先给出合理制造草案，只在真正阻塞制造时写 blocking_questions。\n"
                    "blocking_questions 最多 1 个；只有两个互斥业务决策都阻塞时才允许 2 个。\n\n"
                    "只能围绕业务目标、主要工作流、行动权限边界、人工确认边界、业务资源边界、输出期望和成功标准。\n"
                    "不要询问或选择模型供应商、RuntimeKernel、LangGraph、SDK、Docker、部署、依赖、测试方式、工程目录、工具实现、数据库驱动或向量库。\n"
                    "能用制造假设推进的内容，写入 manufacturing_assumptions，不要追问。\n"
                    "如果没有 blocking_questions，ready_for_runtime_design 必须为 true；如果存在 blocking_questions，必须为 false。\n"
                    "business_plan_text 要写给用户看，清晰、人性化、具体，但不要承诺后续实现细节已经完成。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "Factory 默认实现：\n{factory_default_implementation_context}\n\n"
                    "当前制造状态：\n{manufacturing_status_context}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "用户输入：\n{user_input}\n\n"
                    "已有 Product Brief 草稿：\n{current_product_brief}\n\n"
                    "请生成 Product Brief JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.RUNTIME_DESIGN_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的 Runtime Design 制造器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "你的任务是把 Product Brief 映射成 RuntimeKernel 可编译的运行蓝图。\n"
                    "所有设计必须服从 RuntimeKernel catalog；不能凭空发明 node_type、node impl、edge condition、contract 或 pattern_id。\n"
                    "必须使用 design_mode=reuse_pattern，并且只能选择 RuntimeKernel catalog 中的非 embeddable preset pattern。\n"
                    "禁止输出自定义 edges、termination 或 package-local pattern；preset pattern 拥有完整图拓扑和节点语义。\n"
                    "nodes 只用于描述所选 pattern 中已有节点的业务职责和能力策略；node_id、node_type、impl 必须与所选 pattern 完全一致。\n"
                    "pattern_slots 用于说明所选 pattern 的槽位如何绑定到 prompt、tool、resource、scheduler、state、artifact、context 等能力。\n"
                    "不要把 operational.tool_call 设计成主动执行工具；它只执行 cognitive 节点生成的 tool_calls。\n"
                    "如果业务需要定时报告，优先选择 scheduled_react_report，让 scheduler 以 graph_run message 触发 ReAct 工具循环。\n"
                    "严格结构化模型输出只有在所选 pattern 已包含 cognitive.structured 节点时才能写入 structured_outputs。\n"
                    "不要生成工具代码、Python node 代码、contract 文件、资源值或 package 文件。\n"
                    "能用 RuntimeKernel 已有能力表达的，不要创造新内核概念。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "Factory 默认实现：\n{factory_default_implementation_context}\n\n"
                    "RuntimeKernel catalog JSON：\n{runtime_kernel_catalog}\n\n"
                    "上一次 Runtime Design 校验反馈：\n{validation_feedback}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "Product Brief JSON：\n{product_brief}\n\n"
                    "用户原始输入：\n{user_input}\n\n"
                    "请生成 Runtime Design JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.CAPABILITY_CONTRACT_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的 Capability Contract 制造器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "你的任务是把 Product Brief 与 Runtime Design 转换成 AgentPackage 的基础能力装配契约。\n"
                    "这一步必须讲清楚每个系统具体接入什么、为什么接入、后续使用什么策略。\n"
                    "必须逐项消费 Runtime Design 的 pattern_slots：每个 slot 应当映射为 contract、资源需求、工具生成任务、prompt 生成任务、scheduler 策略或 artifact 策略。\n"
                    "不要生成工具代码、node.py、pattern yaml、package 文件或真实资源值。\n"
                    "不要声明任何 Python builder import path；RuntimeContract builder 只能由系统注册。\n"
                    "contract_drafts 必须包含所有 required_agent_package_contracts 与 Runtime Design 明确需要的 contract。\n"
                    "capability_plans 必须覆盖所有 standard_capability_systems；不启用的系统也要写 enabled=false 和原因。\n"
                    "工具、知识、定时、记忆、上下文、trace、sandbox、resources、artifact、node_provider 等策略必须具体，不要只写 enabled=true。\n"
                    "如果 Runtime Design 需要 package-local node，必须在 package_nodes_to_generate 中列出。\n"
                    "如果 Runtime Design 需要结构化输出，必须在 bindings_to_generate 中列出 model_operation binding，并在 prompts_to_generate 中列出对应 prompt。\n"
                    "如果 Runtime Design 需要工具，必须明确 builtin/system/package/mcp/skill 工具来源策略。\n"
                    "如果 Runtime Design 有多个 state_namespaces，不要让 contract 失败；state contract 使用一个物理 namespace，"
                    "并在 capability_plans.state.what.logical_namespaces 中记录所有逻辑 namespace。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "Factory 默认实现：\n{factory_default_implementation_context}\n\n"
                    "Capability catalog JSON：\n{capability_contract_catalog}\n\n"
                    "上一次 Capability Contract 校验反馈：\n{validation_feedback}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "Product Brief JSON：\n{product_brief}\n\n"
                    "Runtime Design JSON：\n{runtime_design}\n\n"
                    "Runtime Design 校验报告：\n{runtime_design_validation}\n\n"
                    "用户原始输入：\n{user_input}\n\n"
                    "请生成 Capability Contract JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.PACKAGE_BUILD_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的 Package Build 制造器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "你的任务是补齐系统 Materializer 无法确定的模型生成内容，而不是直接写文件。\n"
                    "Package Build 会由系统负责落盘、路径安全、原子提交和静态校验。\n"
                    "你只能输出 PackageBuildPlan JSON 中允许的内容：prompt 模板、结构化输出 schema、package-local node 代码、package tool 代码和构建摘要。\n"
                    "Package Build 不允许重新设计 graph；必须服从 Runtime Design 已选择的 preset pattern。\n"
                    "不要输出绝对路径、不要输出 package_root、不要改写 system-generated 文件、不要声明 builder import path。\n"
                    "package-local node 代码必须定义：def run(input: dict, context) -> dict。\n"
                    "package tool 代码必须定义：def run(arguments: dict, resources: dict) -> dict。\n"
                    "代码只能使用 Python 标准库、已声明依赖和通过 context/tool resources 明确提供的能力；不要裸执行 shell、不要直接读写沙箱外路径、不要绕过 ToolExecutionGateway。\n"
                    "如果 package-local node 或 package tool 代码 import 任何非标准库 Python 包，必须在对应条目的 python_requirements 中声明可安装 requirement；"
                    "如果依赖系统包或系统命令，必须在 system_packages 或 system_binaries 中声明。"
                    "这些依赖会由系统合并进 contracts/dependencies.json 并在 sandbox_init 阶段安装/检测。\n"
                    "如果 Runtime Design 不需要 package-local node 或 package-generated tool，对应列表必须为空。\n"
                    "如果有 cognitive.structured 节点，必须提供可执行的 JSON Schema 和 write_target。\n"
                    "prompt 模板变量只能使用 Kernel 已提供的数据源：messages、runtime_context、context、model_context、package_state、resources、current_user_input。"
                    "不要声明 raw_news、raw_quotes 这类没有 binding 来源的变量；如果需要数据，让 cognitive.answer 通过工具调用拿到 observation。\n"
                    "prompt 模板要面向生成 Agent 的运行时模型，不要提 FastAgentFactory 内部制造流程。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "Factory 默认实现：\n{factory_default_implementation_context}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "Product Brief JSON：\n{product_brief}\n\n"
                    "Runtime Design JSON：\n{runtime_design}\n\n"
                    "Capability Contract JSON：\n{capability_contract}\n\n"
                    "请生成 PackageBuildPlan JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.SCHEDULER_FEEDBACK_SUMMARY:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的定时任务完成事件总结器。\n"
                    "你只根据输入的 SchedulerExecutionReport 事实生成完成事件摘要。\n"
                    "不要调用工具，不要重新执行任务，不要补充未出现在事实里的内容。\n"
                    "不要把摘要写成普通对话，也不要要求用户确认。\n"
                    "如果 report.stdout_preview 有内容，优先把它作为本次任务的业务结果来总结。\n"
                    "不要只说“工具执行完成”或“退出码为 0”，除非没有任何 stdout/output 可用。\n"
                    "run.completed_count 表示这个定时任务累计第几次完成，不是本次完成了多少项操作。\n"
                    "失败或跳过时，优先使用 report.error_summary 和 report.stderr_preview 说明原因。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "输出字段：\n"
                    "- summary: 面向用户展示的中文摘要，可以包含任务结果、失败原因或跳过原因。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "定时任务执行事实 JSON：\n{feedback_context}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    raise KeyError(f"unknown prompt id: {prompt_id}")


def output_json_schema(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2)
