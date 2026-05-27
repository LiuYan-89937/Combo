from __future__ import annotations

from enum import Enum
import json

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel


class PromptId(str, Enum):
    PRODUCT_BRIEF_DRAFT = "factory.product_brief.draft"
    RUNTIME_DESIGN_DRAFT = "factory.runtime_design.draft"
    CAPABILITY_CONTRACT_DRAFT = "factory.capability_contract.draft"
    TOOL_MANUFACTURING_DRAFT = "factory.tool_manufacturing.draft"
    TOOL_SOURCE_DECISIONS_DRAFT = "factory.tool_manufacturing.source_decisions"
    TOOL_DESIGN_DRAFT = "factory.tool_manufacturing.design"
    TOOL_SPEC_DRAFT = "factory.tool_manufacturing.spec"
    TOOL_IMPLEMENTATION_DRAFT = "factory.tool_manufacturing.implementation"
    TOOL_TRIAL_PLAN_DRAFT = "factory.tool_manufacturing.trial_plan"
    EXTERNAL_RESOURCE_RESOLUTION = "factory.resource_resolution.parse_answer"
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
                    "resources_required 必须保留资源描述，同时提供工具可读取的 value_schema/default_value/secret_fields/resolution_strategy；不要把资源描述当成 resources.json 的运行值。\n"
                    "resolution_strategy 只能使用 ask_user、discoverable、secret、optional、runtime_config、defaultable；私密凭证必须包含 secret，公开可查资料必须包含 discoverable，不确定时包含 ask_user。\n"
                    "resources_required.value_schema 必须使用 JSON Schema 标准注解描述用户表单：title 给普通用户看的字段名，description 解释为什么需要，examples 给可填写示例，default 给默认值。\n"
                    "如需额外 UI 提示，只能使用通用扩展 x-agentfactory-ui，允许字段包括 input_kind、placeholder、help、examples、secret；不要依赖字段名让前端猜业务含义。\n"
                    "x-agentfactory-ui.input_kind 只能是 text、text_list、url_list、number、boolean、secret、json 或 natural_language。\n"
                    "resources 是运行配置的唯一事实源；package_state 不允许复制外部来源、凭据、账号、endpoint、输出路径等资源字段，只能保存确认状态、进度、派生结果等业务状态。\n"
                    "不要生成工具代码、node.py、pattern yaml、package 文件或真实资源值。\n"
                    "不要声明任何 Python builder import path；RuntimeContract builder 只能由系统注册。\n"
                    "contract_drafts 必须包含所有 required_agent_package_contracts 与 Runtime Design 明确需要的 contract。\n"
                    "capability_plans 必须覆盖所有 standard_capability_systems；不启用的系统也要写 enabled=false 和原因。\n"
                    "工具、知识、定时、记忆、上下文、trace、sandbox、resources、artifact、node_provider 等策略必须具体，不要只写 enabled=true。\n"
                    "如果 Runtime Design 需要 package-local node，必须在 package_nodes_to_generate 中列出。\n"
                    "如果 Runtime Design 需要结构化输出，必须在 bindings_to_generate 中列出 model_operation binding，并在 prompts_to_generate 中列出对应 prompt。\n"
                    "如果 Runtime Design 需要工具，只描述工具需求和可选来源提示；最终来源由 Tool Manufacturing 唯一决定。\n"
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
    if prompt_id == PromptId.TOOL_MANUFACTURING_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的 Tool Manufacturing 制造器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "你的任务是把 Capability Contract 中的工具需求变成可验证的工具制造资产。\n"
                    "这个 prompt 只用于兼容旧调用；新制造链路会分步生成 source decision、design、spec、implementation 和 trial plan。\n"
                    "必须先做来源决策：builtin、mcp、skill、knowledge、scheduler、package_generated。\n"
                    "已有系统能力能满足时禁止重复生成 package tool；package_generated 只用于当前 Agent 独有的确定性业务能力。\n"
                    "source 不是 package_generated 的工具，只输出 source_decision 和 binding_notes，不生成 ToolDesign、ToolSpecDraft、tool.py 或测试用例。\n"
                    "如果 source 是 mcp 或 skill，且 Factory 当前 extensions 中已有可复用配置，必须在 source_decision.inherited_extensions 写明要继承的 server_id 或 skill_id。\n"
                    "MCP 继承 extension_id 使用 mcp_servers.json 里的 server_id；Skill 继承 extension_id 使用 enabled_skills.json 里的 skill_id。\n"
                    "继承 MCP/Skill 时不要复制实现内容到模型输出；系统会从 Factory extensions 解析并写入子 Agent 的 extensions 目录。\n"
                    "source 是 package_generated 的工具，必须提供 ToolDesign、ToolSpecDraft、ToolImplementationDraft、ToolTrialPlan。\n"
                    "ToolSpecDraft 必须能转换为 RuntimeKernel ToolSpec；input_schema/output_schema 必须是严格 JSON Schema object。\n"
                    "资源绑定使用 resource_bindings 的 local_name -> selector 语义；selector 只能是点路径，例如 service_config.api_token，禁止 resources://...、{{resources...}} 或绝对路径。\n"
                    "tool.py 必须提供名为 run 的入口函数，参数必须依次为 arguments 与 resources，并返回 dict。\n"
                    "工具代码不能裸执行 shell，不能访问沙箱外路径，不能绕过 ToolExecutionGateway，不能把 secret 写入输出。\n"
                    "如果工具需要外部 Python 包，必须写入 ToolDesign.python_requirements；系统包和命令分别写入 system_packages/system_binaries。\n"
                    "trial plan 必须给出可安全执行的 scenario；系统会用同一份 scenario 先做 ToolCompiler/Gateway contract smoke，再做 task model tool-bound trial。\n"
                    "不要生成 pytest、mock DSL、fixture、import 测试代码或业务特化真实外部调用。\n"
                    "approved_package_tools 可以留空；系统会在静态检查、依赖收敛、contract smoke 和 model-bound trial 通过后生成最终 approved artifact。\n"
                    "不要生成 package 文件、manifest 路径、Docker 配置、RuntimeContract 文件或 PackageBuildPlan。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "Factory 默认实现：\n{factory_default_implementation_context}\n\n"
                    "现有工具 catalog JSON：\n{tool_catalog}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "Product Brief JSON：\n{product_brief}\n\n"
                    "Runtime Design JSON：\n{runtime_design}\n\n"
                    "Capability Contract JSON：\n{capability_contract}\n\n"
                    "请生成 ToolManufacturingOutput JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.TOOL_SOURCE_DECISIONS_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的 Tool Manufacturing 来源决策器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "你的任务只做工具来源决策，不生成 ToolDesign、ToolSpec、代码、测试或 smoke。\n"
                    "Capability Contract 中的 tool source 只是来源提示，不是锁定值；最终来源由你在 source_decisions 中决定。\n"
                    "来源只能是 builtin、mcp、skill、knowledge、scheduler、package_generated。\n"
                    "已有 builtin/MCP/Skill/knowledge/scheduler 能满足时，禁止重复生成 package tool。\n"
                    "外部 URL、API endpoint、SMTP、token、账号、secret 和业务标识以已确认资源事实为准；公开信息查询以 builtin web_search/web_fetch、knowledge、MCP 或 Skill 为辅。\n"
                    "不要把尚未通过用户输入或系统工具发现的公开信息写成固定资源或 package tool 常量。\n"
                    "如果选择 mcp 或 skill，必须在 inherited_extensions 中写明要继承的 server_id 或 skill_id。\n"
                    "如果选择 package_generated，必须说明为什么现有能力无法满足。\n"
                    "不要输出任何实现内容。\n\n"
                    "现有工具 catalog JSON：\n{tool_catalog}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "Product Brief JSON：\n{product_brief}\n\n"
                    "Runtime Design JSON：\n{runtime_design}\n\n"
                    "Capability Contract JSON：\n{capability_contract}\n\n"
                    "已确认资源事实：\n{resource_facts}\n\n"
                    "请生成 ToolSourceDecisionOutput JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.TOOL_DESIGN_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的单工具 ToolDesign 制造器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "只为当前这一个 package_generated 工具生成 ToolDesign，不生成 spec、代码、测试或 smoke。\n"
                    "资源绑定只能写 resource_bindings 列表，每项必须是 {{local_name, selector, purpose}}。\n"
                    "local_name 是工具代码里使用的本地资源名，例如 input_sources 或 api_token；selector 是资源点路径，例如 service_config.input_sources。\n"
                    "禁止输出 resource_selectors 字段；禁止 selector 使用 resources://...、{{resources...}}、描述文字或绝对路径。\n"
                    "如果需要外部 Python 包，写入 python_requirements；系统包和命令分别写入 system_packages/system_binaries。\n"
                    "禁止设计裸 shell、沙箱外路径、绕过 ToolExecutionGateway 或 secret 输出。\n\n"
                    "外部 URL、API endpoint、SMTP、token、账号、secret 和业务标识以已确认资源事实为准；公开信息查询以 builtin web_search/web_fetch、knowledge、MCP 或 Skill 为辅。\n"
                    "如果需要运行时发现公开信息，只能把它设计为工具输入、资源槽或系统工具调用策略，不能把未确认结果写成固定值。\n"
                    "如果 resource_facts 中没有具体外部来源，只能设计资源槽和 selector，不能写任何猜测域名、API、股票代码、账号或 host。\n"
                    "实现应该从 resources/arguments 或系统工具结果读取来源；外部来源不可用时返回 schema-valid 业务失败 payload。\n\n"
                    "上一轮制造校验反馈：\n{validation_feedback}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "Product Brief JSON：\n{product_brief}\n\n"
                    "Runtime Design JSON：\n{runtime_design}\n\n"
                    "Tool Requirement JSON：\n{tool_requirement}\n\n"
                    "Source Decision JSON：\n{source_decision}\n\n"
                    "Resource Requirements JSON：\n{resource_requirements}\n\n"
                    "已确认资源事实：\n{resource_facts}\n\n"
                    "请生成 ToolDesign JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.TOOL_SPEC_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的单工具 ToolSpecDraft 制造器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "只为当前这一个 package_generated 工具生成 ToolSpecDraft，不生成代码、测试或 smoke。\n"
                    "input_schema/output_schema 必须是严格 JSON Schema object，默认 additionalProperties=false。\n"
                    "resources 是 ToolSpec 的实际资源映射，格式固定为 local_resource_name -> dot_path_selector。\n"
                    "示例：{{\"input_sources\":\"service_config.input_sources\",\"api_token\":\"service_config.credentials.api_token\"}}。\n"
                    "key 必须是本地资源名，value 必须是点路径 selector；禁止反写成 selector -> 描述，禁止 resources://...、{{resources...}} 或绝对路径。\n\n"
                    "如果工具会访问外部服务，output_schema 必须包含稳定失败输出，不能只定义成功路径。业务失败应作为 output 字段表达，例如 status/error/retryable，而不是依赖 Gateway invalid_output。\n"
                    "外部资源 selector 只指向用户提供或运行时配置；公开信息发现应通过 builtin web_search/web_fetch、knowledge、MCP 或 Skill 的工具链表达，不要在 spec 里写死猜测值。\n\n"
                    "上一轮制造校验反馈：\n{validation_feedback}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "Tool Requirement JSON：\n{tool_requirement}\n\n"
                    "Source Decision JSON：\n{source_decision}\n\n"
                    "ToolDesign JSON：\n{tool_design}\n\n"
                    "Resource Requirements JSON：\n{resource_requirements}\n\n"
                    "已确认资源事实：\n{resource_facts}\n\n"
                    "请生成 ToolSpecDraft JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.TOOL_IMPLEMENTATION_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的单工具 tool.py 实现制造器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object。\n\n"
                    "只生成 ToolImplementationDraft，不生成测试或 smoke。\n"
                    "代码必须定义 def run(arguments: dict, resources: dict) -> dict。\n"
                    "只能使用 Python 标准库、ToolDesign.python_requirements 声明的依赖，以及 resources 中显式传入的值。\n"
                    "禁止裸 shell、沙箱外路径、真实 secret 输出、全局副作用和绕过 ToolExecutionGateway。\n"
                    "外部网络逻辑必须有超时和结构化失败返回。\n\n"
                    "外部服务不可达、HTTP 错误、认证失败、SMTP 失败、空结果等业务失败必须返回符合 ToolSpec output_schema 的失败 payload；不要直接 raise 让 Gateway 变成 execution_failed，除非这是不可恢复的编程错误。\n"
                    "外部 URL、API endpoint、SMTP、token、账号、secret 和业务标识只能读取 resources/arguments 中由 resource_facts 确认的值，或来自运行时系统工具的返回；禁止硬编码或编造真实外部服务地址。\n\n"
                    "不要在代码常量里写真实外部域名、URL、股票代码、账号或 API 名称；如果需要默认值，也只能使用空值或从 resources 读取。\n"
                    "如果没有用户提供的来源，工具要返回 schema-valid 的“缺少资源/未配置”结果，而不是替用户选择来源。\n\n"
                    "上一轮制造校验反馈：\n{validation_feedback}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "ToolDesign JSON：\n{tool_design}\n\n"
                    "ToolSpecDraft JSON：\n{tool_spec}\n\n"
                    "已确认资源事实：\n{resource_facts}\n\n"
                    "请生成 ToolImplementationDraft JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.TOOL_TRIAL_PLAN_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的单工具 ToolTrialPlan 制造器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "只生成 ToolTrialPlan。禁止输出 pytest、mock、fixture、Python 测试源码或导入路径。\n"
                    "scenarios 是唯一入口；每个 scenario 同时用于两个真实链路检查：\n"
                    "1. contract smoke：ToolCompiler + ToolExecutionGateway 用 arguments/resources 直接执行工具。\n"
                    "2. model-bound trial：task model 读取 user_prompt，生成 tool_call，经 ToolNode/Gateway 得到 ToolMessage，再生成最终回答。\n"
                    "scenario 必须包含 scenario_id、user_prompt、expected_tool_id、arguments、resources、expected_observation_status。\n"
                    "arguments/resources 必须短小、安全、可在制造测试环境执行；不要依赖真实外部服务、真实 secret 或业务环境。\n"
                    "如果用户提供了真实外部资源，允许 scenario 用这些资源做真实连通性测试；公开信息可由系统工具搜索作为辅助，但 trial 中不得写入用户未提供或系统工具未发现的 URL、API endpoint、SMTP、secret 或业务标识。\n"
                    "禁止用 example.com 之类占位域名冒充真实资源。\n"
                    "contract smoke 只检查 ToolCompiler、ToolExecutionGateway、schema 与 ToolMessage 链路，不做业务内容精确断言。\n"
                    "如果外部服务返回业务失败，expected_observation_status 仍应为 completed，并通过 success_criteria 描述业务状态评审。\n"
                    "expected_output_keys 只检查工具 output 的顶层键；不要要求真实新闻标题、价格、时间或网页内容逐字匹配；expected_final_answer_contains 只写稳定短语，不能要求长文本逐字匹配。\n"
                    "success_criteria 用自然语言写模型试调用评审标准，例如“模型必须调用当前工具而不是直接回答”。\n\n"
                    "上一轮制造校验反馈：\n{validation_feedback}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "ToolDesign JSON：\n{tool_design}\n\n"
                    "ToolSpecDraft JSON：\n{tool_spec}\n\n"
                    "ToolImplementationDraft JSON：\n{tool_implementation}\n\n"
                    "已确认资源事实：\n{resource_facts}\n\n"
                    "请生成 ToolTrialPlan JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.EXTERNAL_RESOURCE_RESOLUTION:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FastAgentFactory 的外部资源解析器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n\n"
                    "你的任务是把用户的口语化回答映射到 resource_request 中声明的 resources 与 sandbox schema。\n"
                    "只做理解和结构化，不生成工具设计、代码、测试或 package 文件。\n"
                    "你只输出本轮用户回答带来的增量；Existing Confirmed Resource Facts 已经是事实源，不要重复补写，也不要清空。\n"
                    "用户回答中的 URL、邮箱、路径、token、连接串可能已被本地预处理替换为 __AF_RESOURCE_VALUE_N__ 占位符；如果它对应资源值，可以原样写入资源字段，系统会在校验后还原。\n"
                    "不得把 secret 或 private-looking 占位符写入 discovery_queries；私密信息只能作为用户提供的资源值或暂不提供。\n"
                    "不要编造用户没有明确提供的 URL、账号、API key、token、连接串、文件路径、推送渠道、股票代码、市场前缀或任何业务标识。\n"
                    "如果用户说“不知道”“你去查”“自己搜索”等，且目标是公开信息，必须写入 discovery_queries；不要直接推断成资源事实。\n"
                    "discovery_queries.query 应是面向搜索工具的短查询；target_resource_id 和 target_path 指向要补齐的资源字段。\n"
                    "如果输入包含 system_discovery_results，只能把 evidence-backed 的公开结果写入 resources；无法由证据支持的仍放入 missing_questions。\n"
                    "secret、API key、账号、密码、私有连接串、私有文件路径不得进入 discovery_queries，只能由用户提供或标记暂不提供。\n"
                    "如果用户明确说暂不提供，decision=skip，resources 和 sandbox 置空。\n"
                    "如果用户说某个可选配置不需要，不要把该字段输出为 null；直接省略该字段。只有 schema 明确允许 null 时才可输出 null。\n"
                    "不要为未选择的可选配置补全子字段，例如用户未选择某个渠道时，不要要求该渠道的账号或密码。\n"
                    "如果回答中缺少必填项或无法判断字段归属，decision=needs_clarification，并只在 missing_questions 中写最少追问。\n"
                    "如果可以落实，decision=resolved，并把值写入 resources 或 sandbox。\n"
                    "resources 的顶层 key 必须是 resource_request.resources[].resource_id；每个 value 必须符合该资源 value_schema。\n"
                    "sandbox 的顶层 key 必须是 resource_request.sandbox_requirements[].requirement_id；联网权限写入 network_access boolean，挂载路径写入 mounts.<mount_id>。\n"
                    "不要输出 resource_request 中没有声明的顶层资源或 sandbox requirement。\n"
                    "secret 字段可以结构化到对应字段，但不要在 notes 中重复 secret 明文。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "Product Brief JSON：\n{product_brief}\n\n"
                    "Runtime Design JSON：\n{runtime_design}\n\n"
                    "Capability Contract JSON：\n{capability_contract}\n\n"
                    "Resource Request JSON：\n{resource_request}\n\n"
                    "系统向用户提出的问题：\n{resource_questions}\n\n"
                    "Existing Confirmed Resource Facts JSON：\n{confirmed_resources}\n\n"
                    "本地脱敏占位符清单 JSON：\n{resource_answer_placeholders}\n\n"
                    "用户回答原文：\n{user_answer}\n\n"
                    "请生成 ExternalResourceResolutionDraft JSON。",
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
                    "如果用户仍没有给出明确时间，不要猜测；decision=revise，seeds=[]，warnings 写出还缺什么。\n"
                    "schedule_type 只能是 cron、interval、date。\n"
                    "cron 使用五段 crontab；interval 使用正整数秒；date 使用 ISO datetime。\n"
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
                    "Package Build 禁止生成 package tool 代码；所有生成工具只能来自 Tool Manufacturing 的 approved_package_tools。\n"
                    "Package Build 禁止生成或改写 scheduler seed；所有定时任务 seed 只能来自 Scheduler Preparation 的 approved_seeds。\n"
                    "代码只能使用 Python 标准库、已声明依赖和通过 context 明确提供的能力；不要裸执行 shell、不要直接读写沙箱外路径、不要绕过 ToolExecutionGateway。\n"
                    "如果 package-local node 代码 import 任何非标准库 Python 包，必须在对应条目的 python_requirements 中声明可安装 requirement；"
                    "如果依赖系统包或系统命令，必须在 system_packages 或 system_binaries 中声明。"
                    "这些依赖会由系统合并进 contracts/dependencies.json 并在 sandbox_init 阶段安装/检测。\n"
                    "不要把 Python 包、系统包或命令写进 sandbox services；sandbox services 只表示真实外部服务 endpoint。\n"
                    "如果 Runtime Design 不需要 package-local node，对应列表必须为空。\n"
                    "如果有 cognitive.structured 节点，必须提供可执行的 JSON Schema 和 write_target。\n"
                    "prompt 模板变量只能使用 Kernel 已提供的数据源：messages、runtime_context、context、model_context、package_state、resources、current_user_input。"
                    "不要声明 raw_payload、external_records 这类没有 binding 来源的变量；如果需要数据，让 cognitive.answer 通过工具调用拿到 observation。\n"
                    "package tool 的 resources 映射值必须是资源选择器，例如 service_config.api_token，不要使用 {{resources...}} 模板表达式。\n"
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
                    "Tool Manufacturing JSON：\n{tool_manufacturing}\n\n"
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
