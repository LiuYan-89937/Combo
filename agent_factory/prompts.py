from __future__ import annotations

from enum import Enum
import json

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel


class PromptId(str, Enum):
    REQUIREMENT_CAPTURE_INTENT = "factory.requirement_capture.intent"
    REQUIREMENT_CAPTURE_CLARITY = "factory.requirement_capture.clarity"
    REQUIREMENT_CAPTURE_QUESTION = "factory.requirement_capture.question"
    REQUIREMENT_CAPTURE_MERGE = "factory.requirement_capture.merge"
    BUSINESS_PLAN_REVIEW_DRAFT = "factory.business_plan_review.draft"
    BUSINESS_PLAN_REVIEW_REVISE = "factory.business_plan_review.revise"
    RUNTIME_PATTERN_SELECTION = "factory.runtime_pattern_selection"
    GRAPH_BEHAVIOR_PLANNING = "factory.graph_behavior_planning"
    NODE_STRATEGY_PLANNING = "factory.node_strategy_planning"
    TOOL_CAPABILITY_PLANNING = "factory.tool_capability_planning"
    RESOURCE_KEY_INFERENCE = "factory.resource_condition.key_inference"
    RESOURCE_PROBE_PLANNING = "factory.resource_condition.probe_planning"
    RESOURCE_VALUE_NORMALIZATION = "factory.resource_condition.value_normalization"
    FACTORY_CHAT = "factory.chat"


def get_prompt(prompt_id: PromptId) -> ChatPromptTemplate:
    if prompt_id == PromptId.REQUIREMENT_CAPTURE_INTENT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the intent classifier for a Factory Agent shell.\n"
                    "Return JSON only. Do not answer the user.\n"
                    "The word JSON is required: your response must be a valid JSON object.\n\n"
                    "Classify the user input into exactly one intent:\n"
                    "- chat\n"
                    "- inspect_factory\n"
                    "- manufacture_agent\n"
                    "- repair_agent\n"
                    "- unclear\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                ("user", "Classify this user input and return JSON only:\n{user_input}"),
            ]
        )
    if prompt_id == PromptId.REQUIREMENT_CAPTURE_CLARITY:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第一阶段的需求清晰度判断器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "只判断需求是否足够进入下一阶段，不要向用户提问。\n\n"
                    "判断时必须参考当前 Factory 第一阶段需求访谈上下文，"
                    "只判断业务画像是否足够清晰，不判断技术实现是否已选型。\n\n"
                    "清晰标准至少包括：Agent 目标、目标用户、使用场景、典型输入、期望输出、"
                    "业务流程、交互方式、成功标准、边界禁区、权限/隐私/数据来源边界和运行约束。\n"
                    "不要把“模型、框架、SDK、数据库、API、部署方式、工具实现方案未选择”"
                    "判定为第一阶段缺失字段；这些属于后续阶段。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "原始输入：\n{original_input}\n\n"
                    "当前 Factory 运行环境：\n{runtime_environment}\n\n"
                    "当前整理后的需求：\n{current_requirement}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.REQUIREMENT_CAPTURE_QUESTION:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第一阶段的需求澄清提问器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "一轮优先生成 1 到 3 个最关键问题；"
                    "只有缺失信息明显分散且必须同时确认时，才最多生成 5 个问题。\n"
                    "每个问题最多 5 个选项，并且必须包含一个自定义补充选项，"
                    "custom_option_id 必须指向该问题的自定义选项。\n\n"
                    "问题和选项必须只围绕业务画像字段：目标用户、使用场景、典型输入、期望输出、"
                    "业务流程、交互方式、成功标准、边界禁区、权限/隐私/数据来源边界和运行约束。\n"
                    "问题和选项必须是用户能直接从业务需求角度选择的表达。\n\n"
                    "不要询问技术实现方案。禁止要求用户在模型供应商、框架、SDK、数据库、"
                    "向量库、部署方式、具体 API、工具实现、代码方案之间做选择。\n"
                    "如果需求暗示需要外部资源或特殊能力，只能询问业务级约束，"
                    "例如是否允许联网、是否必须本地运行、是否涉及敏感数据、是否允许后续接入外部资源；"
                    "不要询问具体用哪种实现。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "原始输入：\n{original_input}\n\n"
                    "当前 Factory 运行环境：\n{runtime_environment}\n\n"
                    "当前整理后的需求：\n{current_requirement}\n\n"
                    "缺失信息：\n{missing_fields}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.REQUIREMENT_CAPTURE_MERGE:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第一阶段的需求整理器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你只能看到原始输入、当前需求版本、本轮问题组和本轮用户回答组。\n"
                    "不要保留历史问答过程，只输出合并后的 current_requirement。\n\n"
                    "整理结果必须保持在当前 Factory 第一阶段需求访谈上下文内。\n"
                    "如果用户回答涉及实现方案，不要扩展成技术设计，只保留为业务约束、"
                    "运行约束或后续待决条件。\n"
                    "如果用户选择了需要额外资源的能力，应写成资源/权限/运行约束，"
                    "不要默认视为已具备，也不要选择具体供应商或技术路线。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "原始输入：\n{original_input}\n\n"
                    "当前 Factory 运行环境：\n{runtime_environment}\n\n"
                    "当前需求版本：\n{current_requirement}\n\n"
                    "本轮问题和用户回答：\n{answers}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.BUSINESS_PLAN_REVIEW_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第一阶段的业务制造计划撰写器。\n"
                    "你的任务是把第一阶段需求整理成一份条理清晰的纯文本业务制造计划。\n"
                    "不要输出 YAML，不要输出 JSON，不要输出代码块。\n\n"
                    "计划必须使用以下固定标题，并保持标题原样：\n"
                    "{required_sections}\n\n"
                    "只从业务层面描述 Agent 应该服务谁、解决什么问题、有哪些业务行为、"
                    "如何与用户互动、业务上不负责什么、怎样算有用。\n\n"
                    "禁止在本阶段写工具方案、资源方案、资源嗅探结论、技术选型、实现设计、"
                    "数据库方案、API 方案、模型/框架选择或具体工具定义。这些属于后续阶段。\n\n"
                    "【后续规划提示】只能写业务层面后续要关注的事项；"
                    "涉及技术实现的内容只写成待决约束，不提前规划工具、资源或技术路线。",
                ),
                (
                    "user",
                    "第一阶段需求如下：\n{requirement_brief}\n\n"
                    "请输出第一阶段业务制造计划纯文本。",
                ),
            ]
        )
    if prompt_id == PromptId.BUSINESS_PLAN_REVIEW_REVISE:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第一阶段的业务制造计划修订器。\n"
                    "根据用户本轮修改意见，重写当前业务制造计划。\n"
                    "不要输出 YAML，不要输出 JSON，不要输出代码块。\n\n"
                    "计划必须使用以下固定标题，并保持标题原样：\n"
                    "{required_sections}\n\n"
                    "只修订业务制造计划本身，不保留修订过程，不追加对话记录。\n"
                    "禁止写工具方案、资源方案、资源嗅探结论、技术选型、实现设计、"
                    "数据库方案、API 方案、模型/框架选择或具体工具定义。",
                ),
                (
                    "user",
                    "第一阶段需求：\n{requirement_brief}\n\n"
                    "当前业务制造计划：\n{current_plan_text}\n\n"
                    "用户本轮修改意见：\n{revision_instruction}\n\n"
                    "请输出修订后的第一阶段业务制造计划纯文本。",
                ),
            ]
        )
    if prompt_id == PromptId.RUNTIME_PATTERN_SELECTION:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第二阶段的 RuntimeKernel pattern 选择器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你只能根据业务制造计划和 pattern catalog 摘要选择一个主运行模式。\n\n"
                    "严格约束：\n"
                    "- 必须从 pattern catalog 中选择一个 kind=main 且 embeddable=false 的 pattern_id。\n"
                    "- 不允许发明 pattern_id。\n"
                    "- 不允许引用 catalog 中没有提供的 nodes、edges、wrappers、contracts。\n"
                    "- 不规划节点职责、路由、中断点、wrapper、上下文、记忆、工具、资源或 AssemblySpec。\n"
                    "- 只解释为什么该 pattern 适合当前业务制造计划。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "第一阶段整理后的需求：\n{requirement_brief}\n\n"
                    "业务制造计划：\n{refined_plan_text}\n\n"
                    "可选 pattern catalog 摘要：\n{pattern_catalog}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.GRAPH_BEHAVIOR_PLANNING:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第三阶段的图行为规划器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你的任务是把已选 RuntimeKernel pattern 的结构摘要解释成该 Agent 的业务图行为计划。\n\n"
                    "严格约束：\n"
                    "- 只能使用 pattern_structure_summary 中已有的 node_id、node_type、routes、interrupt_points、termination。\n"
                    "- 不允许增删节点。\n"
                    "- 不允许增删边。\n"
                    "- 不允许发明 route condition。\n"
                    "- 不允许修改 pattern_id。\n"
                    "- 不规划 wrapper、上下文策略、记忆策略、policy、工具可见性、资源需求或 AssemblySpec。\n"
                    "- 只说明这个 Agent 准备如何使用该 pattern 的图行为。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "业务制造计划：\n{refined_plan_text}\n\n"
                    "第二阶段 pattern 选择结果：\n{runtime_pattern_selection}\n\n"
                    "Pattern 结构摘要：\n{pattern_structure_summary}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.NODE_STRATEGY_PLANNING:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第四阶段的节点策略规划器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你的任务是基于已确认的图行为计划，给每个已有节点规划可装配的运行策略。\n\n"
                    "严格约束：\n"
                    "- 必须为 graph_behavior_plan 中每个已有 node_id 输出一个 node strategy。\n"
                    "- 不允许增删节点。\n"
                    "- 不允许修改 pattern_id。\n"
                    "- wrapper_id 必须来自 wrapper_catalog。\n"
                    "- wrapper phase 必须来自该 wrapper 支持的 phases。\n"
                    "- 已存在策略只能引用 strategy_catalog 中的 strategy_id，并把 source 写为 catalog。\n"
                    "- 如果现有目录无法表达节点需要的策略，可以在 proposed_strategies 中新增策略声明，"
                    "并在节点 strategy_refs 中引用它且 source 写为 proposed。\n"
                    "- proposed_strategies 只允许写 strategy_id、name、description、kind、phase、"
                    "required_by_node_ids、applies_to_node_types、reads、writes、config_schema、implementation_notes。\n"
                    "- 不允许写任何策略 Python 实现代码、prompt 正文、工具实现、数据库/API 方案、资源探测结论或 AssemblySpec。\n"
                    "- 工具能力只能写引用或占位说明，不定义具体工具；具体工具规划属于第五阶段。\n"
                    "- 已确定的配置写入 config；需要后续确认的内容写入 config_notes。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "业务制造计划：\n{refined_plan_text}\n\n"
                    "第二阶段 pattern 选择结果：\n{runtime_pattern_selection}\n\n"
                    "第三阶段图行为计划：\n{graph_behavior_plan}\n\n"
                    "Pattern 结构摘要：\n{pattern_structure_summary}\n\n"
                    "可用 wrapper catalog：\n{wrapper_catalog}\n\n"
                    "可用 strategy catalog：\n{strategy_catalog}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.TOOL_CAPABILITY_PLANNING:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第五阶段的工具能力规划器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你的任务是把已确认的图行为和节点策略，转换为精简的工具能力契约。\n\n"
                    "严格约束：\n"
                    "- 只规划工具能力，不写工具 Python 实现代码。\n"
                    "- 不做资源嗅探，不决定 API key、数据库、外部服务、Docker、依赖安装或具体供应商。\n"
                    "- 不增加 category 字段，不对工具做固定分类。\n"
                    "- capability_id 必须简短、稳定、可被后续 Assembly 和 package generation 引用。\n"
                    "- required_by_node_ids 与 visible_to_node_ids 只能引用 graph_behavior_plan 中已有 node_id。\n"
                    "- node_tool_visibility 必须为每个已有 node_id 输出一条记录。\n"
                    "- allowed_tool_capability_ids、approval_required_capability_ids、blocked_tool_capability_ids "
                    "只能引用本次 tool_capabilities 中已有 capability_id。\n"
                    "- implementation_status 只能表达后续实现状态：available、needs_generation、needs_binding、unknown。\n"
                    "- input_contract 和 output_contract 只写轻量结构，不写实现细节。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "业务制造计划：\n{refined_plan_text}\n\n"
                    "第三阶段图行为计划：\n{graph_behavior_plan}\n\n"
                    "第四阶段节点策略计划：\n{node_strategy_plan}\n\n"
                    "可用工厂基础工具 ID：\n{factory_base_tool_ids}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.RESOURCE_KEY_INFERENCE:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第六阶段的资源键推导器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你的任务是根据第五阶段工具能力契约，推导后续工具生成和测试必须依赖的资源键。\n\n"
                    "严格约束：\n"
                    "- 只输出资源键，不输出资源值。\n"
                    "- 不写工具 Python 实现代码，不写 Dockerfile，不写依赖安装命令。\n"
                    "- 不预设固定资源类型；key 必须来自工具能力本身的真实需要。\n"
                    "- required=true 表示没有值、占位或用户阻塞决策就不能进入下一阶段。\n"
                    "- key 使用 snake_case，简短稳定，可被 resources.json 和后续 package_generation 引用。\n"
                    "- used_by_capability_ids 只能引用 tool_capability_plan 中已有 capability_id。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "业务制造计划：\n{refined_plan_text}\n\n"
                    "工具能力计划：\n{tool_capability_plan}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.RESOURCE_PROBE_PLANNING:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第六阶段的资源嗅探规划器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你的任务是为缺失资源键选择只读/探测工具，尝试确认可用值或证据。\n\n"
                    "严格约束：\n"
                    "- 只能选择 allowed_probe_tool_ids 中的工具。\n"
                    "- 不允许选择写入工具、补丁工具、创建目录工具、异步 shell 工具或任意 shell_run。\n"
                    "- 不调用真实业务外部 API，不安装依赖，不生成工具代码。\n"
                    "- 如果无法可靠嗅探某个 key，就不要为该 key 编造 probe。\n"
                    "- shell_env 只能检查环境变量是否存在；除非资源键明确要求保存原始值，否则 include_values=false。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "资源键：\n{required_resource_keys}\n\n"
                    "当前已准备资源：\n{resources}\n\n"
                    "允许的探测工具：\n{allowed_probe_tool_ids}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.RESOURCE_VALUE_NORMALIZATION:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第六阶段的资源值归一化器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你的任务是把已探测到或用户补充的资源值，改写成后续 package_generation "
                    "和 harness 测试可以稳定读取的 resources 键值对。\n\n"
                    "严格约束：\n"
                    "- 只能输出 required_resource_keys 中已有的 key。\n"
                    "- 不允许新增资源 key，不允许输出未要求的环境信息。\n"
                    "- 不要发明密钥、路径、服务地址、账号或任何证据不足的值。\n"
                    "- 不选择模型供应商、框架、数据库、部署方式或工具实现方案。\n"
                    "- 保留 ${RUNTIME_PROVIDED:<KEY>} 形式的运行时占位。\n"
                    "- 对用户自然语言或探测证据中的等价表达做轻度规范化，"
                    "例如清理空白、整理列表/布尔/数字/路径/地址等明确语义；证据不足则不要输出该 key。\n"
                    "- 如果已有显式值可用，除非可以更稳定更准确地表达，否则保持原值。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "资源键：\n{required_resource_keys}\n\n"
                    "当前资源值：\n{current_resources}\n\n"
                    "探测证据：\n{probe_evidence}\n\n"
                    "工具能力计划：\n{tool_capability_plan}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.FACTORY_CHAT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are FastAgentFactory's shell assistant.\n"
                    "Answer normal chat directly in Chinese.\n"
                    "Be concise, warm, and practical.",
                ),
                ("placeholder", "{messages}"),
            ]
        )
    raise KeyError(f"unknown prompt id: {prompt_id}")


def output_json_schema(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2)
