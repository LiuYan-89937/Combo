from __future__ import annotations

from enum import Enum
import json

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel


class PromptId(str, Enum):
    PRODUCT_BRIEF_DRAFT = "factory.product_brief.draft"
    RUNTIME_DESIGN_DRAFT = "factory.runtime_design.draft"
    CAPABILITY_CONTRACT_DRAFT = "factory.capability_contract.draft"
    SCHEDULER_SEED_DRAFT = "factory.scheduler_preparation.seed_draft"
    SCHEDULER_SEED_REVISION = "factory.scheduler_preparation.seed_revision"
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
                    "Runtime Design JSON schema 不包含 edges、interrupts、termination；不要描述自定义拓扑或 package-local pattern，preset pattern 拥有完整图拓扑和节点语义。\n"
                    "nodes 只用于描述所选 pattern 中已有节点的业务职责和能力策略；node_id、node_type、impl 必须与所选 pattern 完全一致。\n"
                    "pattern_slots 必须逐项覆盖所选 pattern catalog 的 required slots，slot_id 与 slot_type 必须完全一致，并通过 binding 字段表达类型化绑定。\n"
                    "resource slot 的 binding 要同时给出 resource_id、value_schema、default_value、secret_fields、resolution_strategy；description 只解释资源用途，运行值必须落到 resources.json。\n"
                    "state_namespaces 只描述业务状态，不保存 runtime 配置值；如果字段属于 resource slot，就不要再放进 state initial_shape。\n"
                    "不要把 messages、resources、artifact、memory、knowledge、scheduler、trace、context 等 RuntimeKernel 服务写成 package_state namespace。\n"
                    "不要把 operational.tool_call 设计成主动执行工具；它只执行 cognitive 节点生成的 tool_calls。\n"
                    "如果业务需要定时或周期触发，优先选择带 scheduler slot 的 preset pattern，让 scheduler 以 graph_run message 触发 ReAct 工具循环。\n"
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
                    "必须逐项消费 Runtime Design 的 pattern_slots：每个 slot 应当映射为 contract、资源需求、工具绑定策略、prompt 生成任务、scheduler 策略或 artifact 策略。\n"
                    "resources_required 必须保留资源描述，同时提供工具可读取的 value_schema/default_value/secret_fields/resolution_strategy；不要把资源描述当成 resources.json 的运行值。\n"
                    "resolution_strategy 只能使用 ask_user、discoverable、secret、optional、runtime_config、defaultable；私密凭证必须包含 secret，公开可查资料必须包含 discoverable，不确定时包含 ask_user。\n"
                    "resources_required.value_schema 必须使用 JSON Schema 标准注解描述用户表单：title 给普通用户看的字段名，description 解释为什么需要，examples 给可填写示例，default 给默认值。\n"
                    "如需额外 UI 提示，只能使用通用扩展 x-agentfactory-ui，允许字段包括 input_kind、placeholder、help、examples、secret；不要依赖字段名让前端猜业务含义。\n"
                    "x-agentfactory-ui.input_kind 只能是 text、text_list、url_list、number、boolean、secret、json 或 natural_language。\n"
                    "resources 是运行配置的唯一事实源；package_state 不允许复制外部来源、凭据、外部定位符或输出位置等资源字段，只能保存确认状态、进度、派生结果等业务状态。\n"
                    "不要生成工具代码、node.py、pattern yaml、package 文件或真实资源值。\n"
                    "不要声明任何 Python builder import path；RuntimeContract builder 只能由系统注册。\n"
                    "contract_drafts 必须包含所有 required_agent_package_contracts 与 Runtime Design 明确需要的 contract。\n"
                    "capability_plans 必须覆盖所有 standard_capability_systems；不启用的系统也要写 enabled=false 和原因。\n"
                    "工具、知识、定时、记忆、上下文、trace、sandbox、resources、artifact、node_provider 等策略必须具体，不要只写 enabled=true。\n"
                    "如果 Runtime Design 需要 package-local node，必须在 package_nodes_to_generate 中列出。\n"
                    "如果 Runtime Design 需要结构化输出，必须在 bindings_to_generate 中列出 model_operation binding，并在 prompts_to_generate 中列出对应 prompt。\n"
                    "如果 Runtime Design 需要工具，只描述工具需求、可选来源提示和运行约束；不要生成工具代码或工具相关产物。\n"
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
    if prompt_id == PromptId.SCHEDULER_SEED_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的 Scheduler Seed 解析器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "你的任务是把 Runtime Design 中已声明的 scheduler slot 和用户业务意图，落实成可校验的 SchedulerSeedPlan。\n"
                    "只能处理 seed_candidates 中已有的定时需求；不能凭空增加 Runtime Design 没声明的定时任务。\n"
                    "如果业务不需要或用户明确不启用定时任务，decision=skip，seeds=[]。\n"
                    "如果 schedule intent 已足够明确，decision=approve，seeds 必须是完整 SchedulerSeedPlan。\n"
                    "如果 schedule intent 仍不足以确定触发规则，不要猜测；decision=revise，seeds=[]，missing_questions 写出还缺什么。\n"
                    "必须保留用户表达的调度语义：频率/间隔语义用 schedule_type=interval 和正整数秒；固定日历时间用 schedule_type=cron 和五段 crontab；一次性时间用 schedule_type=date 和 ISO datetime。\n"
                    "不要把频率/间隔语义改写成固定时刻；不要把固定时刻改写成间隔。\n"
                    "timezone 默认 Asia/Shanghai，除非用户明确指定其他时区。\n"
                    "默认 target 使用候选中的 graph_run message；不要把定时任务改成工具直调，除非候选已经是 tool_call 或用户明确要求。\n"
                    "enabled_on_apply 必须为 true。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "Product Brief JSON：\n{product_brief}\n\n"
                    "Runtime Design JSON：\n{runtime_design}\n\n"
                    "Scheduler seed candidates JSON：\n{seed_candidates}\n\n"
                    "请生成 SchedulerSeedRevisionOutput JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.SCHEDULER_SEED_REVISION:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的 Scheduler Seed 修订器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "你的任务是把用户对定时任务卡片的口语化修改，落实成 scheduler seed。\n"
                    "只能修改 seed_candidates 中已有的定时需求；不能凭空增加 Runtime Design 没声明的定时任务。\n"
                    "如果用户表示暂不启用定时任务，decision=skip，seeds=[]。\n"
                    "如果用户确认并补齐了时间，decision=approve，seeds 必须是完整 SchedulerSeedPlan。\n"
                    "如果用户仍没有给出明确时间，不要猜测；decision=revise，seeds=[]，missing_questions 写出还缺什么。\n"
                    "必须保留用户表达的调度语义：频率/间隔语义用 schedule_type=interval 和正整数秒；固定日历时间用 schedule_type=cron 和五段 crontab；一次性时间用 schedule_type=date 和 ISO datetime。\n"
                    "不要把频率/间隔语义改写成固定时刻；不要把固定时刻改写成间隔。\n"
                    "timezone 默认 Asia/Shanghai，除非用户明确指定其他时区。\n"
                    "默认 target 使用候选中的 graph_run message；不要把定时任务改成工具直调，除非候选已经是 tool_call 或用户明确要求。\n"
                    "enabled_on_apply 必须为 true。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "Product Brief JSON：\n{product_brief}\n\n"
                    "Runtime Design JSON：\n{runtime_design}\n\n"
                    "Scheduler seed candidates JSON：\n{seed_candidates}\n\n"
                    "用户修改/确认原文：\n{revision_text}\n\n"
                    "请生成 SchedulerSeedRevisionOutput JSON。",
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
                    "你只能输出 PackageBuildModelPlan JSON 中允许的内容：prompt 模板、结构化输出 schema、package-local node 代码和构建摘要。\n"
                    "Package Build 不允许重新设计 graph；必须服从 Runtime Design 已选择的 preset pattern。\n"
                    "不要输出绝对路径、不要输出 package_root、不要改写 system-generated 文件、不要声明 builder import path。\n"
                    "package-local node 代码必须定义：def run(input: dict, context) -> dict。\n"
                    "Package Build 禁止生成 package tool 代码；package_tools 必须保持为空。\n"
                    "Package Build 禁止生成或改写 scheduler seed；所有定时任务 seed 只能来自 Scheduler Preparation 的 approved_seeds。\n"
                    "代码只能使用 Python 标准库、已声明依赖和通过 context 明确提供的能力；不要裸执行 shell、不要直接读写沙箱外路径、不要绕过 ToolExecutionGateway。\n"
                    "如果 package-local node 代码 import 任何非标准库 Python 包，必须在对应条目的 python_requirements 中声明可安装 requirement；"
                    "如果依赖系统包或系统命令，必须在 system_packages 或 system_binaries 中声明。"
                    "这些依赖会由系统合并进 contracts/dependencies.json 并在 sandbox_init 阶段安装/检测。\n"
                    "不要把 Python 包、系统包或命令写进 sandbox services；sandbox services 只表示真实外部依赖入口。\n"
                    "如果 Runtime Design 不需要 package-local node，对应列表必须为空。\n"
                    "如果有 cognitive.structured 节点，必须提供可执行的 JSON Schema 和 write_target。\n"
                    "prompt 模板变量只能使用 Kernel 已提供的数据源：messages、runtime_context、context、model_context、package_state、resources、current_user_input。"
                    "不要声明 raw_payload、external_records 这类没有 binding 来源的变量；如果需要数据，让 cognitive.answer 通过系统已绑定能力拿到 observation。\n"
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
                    "Scheduler Preparation JSON：\n{scheduler_preparation}\n\n"
                    "请生成 PackageBuildModelPlan JSON。",
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
