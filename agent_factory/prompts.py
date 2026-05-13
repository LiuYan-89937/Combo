from __future__ import annotations

from enum import Enum
import json

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from agent_factory.factory_graph.schemas import CaptureIntentOutput


class PromptId(str, Enum):
    CAPTURE_REQUIREMENT_INTENT = "factory.requirement_capture.intent"
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
    RESOURCE_REQUIREMENT_INFERENCE = "factory.resource_condition.requirement_inference"
    RESOURCE_REACT = "factory.resource_condition.react"
    RESOURCE_REACT_DECISION = "factory.resource_condition.react_decision"
    ASSEMBLY_SPEC_REACT = "factory.assembly_spec_generation.react"
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
                    "Factory 运行边界：\n{factory_operating_context}\n\n当前阶段边界：\n{stage_operating_context}\n\nOutput JSON schema:\n{output_json_schema}",
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
                    "Factory 运行边界：\n{factory_operating_context}\n\n当前阶段边界：\n{stage_operating_context}\n\nOutput JSON schema:\n{output_json_schema}",
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
                    "Factory 运行边界：\n{factory_operating_context}\n\n当前阶段边界：\n{stage_operating_context}\n\nOutput JSON schema:\n{output_json_schema}",
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
                    "Factory 运行边界：\n{factory_operating_context}\n\n当前阶段边界：\n{stage_operating_context}\n\nOutput JSON schema:\n{output_json_schema}",
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
                    "涉及技术实现的内容只写成待决约束，不提前规划工具、资源或技术路线。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "当前阶段边界：\n{stage_operating_context}",
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
                    "数据库方案、API 方案、模型/框架选择或具体工具定义。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "当前阶段边界：\n{stage_operating_context}",
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
                    "Factory 运行边界：\n{factory_operating_context}\n\n当前阶段边界：\n{stage_operating_context}\n\nOutput JSON schema:\n{output_json_schema}",
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
                    "Factory 运行边界：\n{factory_operating_context}\n\n当前阶段边界：\n{stage_operating_context}\n\nOutput JSON schema:\n{output_json_schema}",
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
                    "Factory 运行边界：\n{factory_operating_context}\n\n当前阶段边界：\n{stage_operating_context}\n\nOutput JSON schema:\n{output_json_schema}",
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
                    "Factory 运行边界：\n{factory_operating_context}\n\n当前阶段边界：\n{stage_operating_context}\n\nOutput JSON schema:\n{output_json_schema}",
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
    if prompt_id == PromptId.RESOURCE_REQUIREMENT_INFERENCE:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第六阶段的资源需求推导器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你的任务是根据第五阶段工具能力契约，推导后续工具生成和测试必须依赖的资源需求。\n\n"
                    "严格约束：\n"
                    "- 只输出资源需求，不输出资源值。\n"
                    "- 不写工具 Python 实现代码，不写 Dockerfile，不写依赖安装命令。\n"
                    "- 不预设固定资源类型；requirement_id 必须来自工具能力本身的真实需要。\n"
                    "- required=true 表示没有资源、占位或用户阻塞决策就不能进入下一阶段。\n"
                    "- requirement_id 使用 snake_case，简短稳定，可被 resources.json 和后续 package_generation 引用。\n"
                    "- used_by_capability_ids 只能引用 tool_capability_plan 中已有 capability_id。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "当前阶段边界：\n{stage_operating_context}\n\n"
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
    if prompt_id == PromptId.RESOURCE_REACT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第六阶段的 ReAct 资源检查器。\n"
                    "你必须遵循 ReAct：需要检查环境、文件、命令或配置时，通过 tool_calls 调用工具；"
                    "工具 Observation 返回后再继续判断。\n\n"
                    "当不再需要工具时，必须输出一个合法 JSON 对象，不要包裹 markdown。"
                    "JSON 必须符合 ResourceReactDecision schema。"
                    "禁止输出 markdown code fence，禁止在 JSON 前后追加自然语言。"
                    "user_prompt 必须是普通 JSON string，不要包含 ``` 代码块。\n\n"
                    "严格约束：\n"
                    "- 只能使用已绑定工具检查资源条件。\n"
                    "- 如果还需要检查，不要输出 JSON；必须直接发起 tool_calls。\n"
                    "- 只有在已经不需要工具时，才输出最终 ResourceReactDecision JSON。\n"
                    "- 不安装依赖，不写文件，不生成工具代码。\n"
                    "- 不把 Factory 自身 mainModel/taskModel/API key/base URL/thinking 配置当成生成 Agent 资源。\n"
                    "- 缺失或不确定时 action=needs_user_input，并给出 user_prompt。\n"
                    "- 资源可用时 action=resources_ready，并给出 resource_draft。\n"
                    "- 用户明确阻塞或检查表明确无法继续时 action=blocked。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "当前阶段边界：\n{stage_operating_context}\n\n"
                    "ResourceReactDecision JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "资源需求：\n{resource_requirements}\n\n"
                    "用户补充：\n{user_inputs}\n\n"
                    "当前资源草稿：\n{resource_draft}\n\n"
                    "工具能力计划：\n{tool_capability_plan}\n\n"
                    "请继续 ReAct 检查，或输出最终 JSON 决策。",
                ),
                ("placeholder", "{messages}"),
            ]
        )
    if prompt_id == PromptId.RESOURCE_REACT_DECISION:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第六阶段 ReAct 最终输出的结构化决策归一化器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你的任务是把 ReAct 模型最后一次非工具输出归一化为 ResourceReactDecision。\n\n"
                    "严格约束：\n"
                    "- 只能根据 raw_model_output、资源需求、用户补充、当前资源草稿和工具观察摘要归一化。\n"
                    "- 不发起工具调用，不继续推理工具检查，不生成工具代码，不写文件。\n"
                    "- 如果 raw_model_output 中包含 markdown、代码块、尾随自然语言或坏 JSON，只提取其可理解的资源决策意图。\n"
                    "- 输出必须是单个 JSON object，禁止 markdown code fence，禁止解释性自然语言。\n"
                    "- user_prompt 必须是普通 JSON string，不要包含 ``` 代码块；如需示例，使用普通文本换行表达。\n"
                    "- 不把 Factory 自身 mainModel/taskModel/API key/base URL/thinking 配置当成生成 Agent 资源。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "当前阶段边界：\n{stage_operating_context}\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "资源需求：\n{resource_requirements}\n\n"
                    "用户补充：\n{user_inputs}\n\n"
                    "当前资源草稿：\n{resource_draft}\n\n"
                    "工具能力计划：\n{tool_capability_plan}\n\n"
                    "工具观察摘要：\n{tool_observations}\n\n"
                    "ReAct 模型最后输出：\n{raw_model_output}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.ASSEMBLY_SPEC_REACT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第七阶段的 AssemblySpec draft 生成器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你的任务是把前六阶段已确认产物转换为可校验的 AgentAssemblySpec draft。\n\n"
                    "严格约束：\n"
                    "- 只能生成 assembly draft，不生成工具代码、package 文件或 harness。\n"
                    "- 不重新选择 pattern，不修改图行为、节点策略、工具能力或资源计划。\n"
                    "- runtime.pattern_id 必须使用第二阶段已选 pattern_id。\n"
                    "- graph_overrides.node_wrappers[].node_id 只能引用第三阶段已有 node_id。\n"
                    "- tools[].id 只能引用第五阶段已有 capability_id。\n"
                    "- 必须填写 bindings；bindings 是成熟装配契约，不是第八阶段临时补齐项。\n"
                    "- bindings.services 必须声明该 Agent 运行需要的 Runtime 服务契约，例如 model_service、tool_registry、memory_engine、knowledge_engine、context_engine、policy_engine、observability_manager、checkpoint_manager。\n"
                    "- bindings.node_bindings 必须按节点绑定 prompt、tool_access、retrieval_profile、policy_profile、strategy_profile、output_formatter 等契约。\n"
                    "- cognitive.* 节点必须有 prompt binding；operational.tool_call 节点必须有 tool_access binding；memory/knowledge 检索节点必须有 retrieval_profile binding；governance.* 节点必须有 policy_profile binding；terminal/finalize 节点必须有 output_formatter binding。\n"
                    "- prompt binding payload 必须包含 prompt_id、template、variables；template 是可审查的 prompt contract，可以包含第八阶段要物化的模板内容或模板骨架。\n"
                    "- tool_access binding 只能引用第五阶段工具能力 id，并表达 allowed_tool_ids 和 approval_policy。\n"
                    "- 第八阶段只负责把第七阶段 bindings 中的 contract 物化为文件、工具代码和 package manifest，不允许重新决定绑定关系。\n"
                    "- harness 仍然不填，harness 属于第九阶段。\n"
                    "- 如果收到 validation_observation，只能在 assembly draft 范围内修正。\n"
                    "- 如果校验错误无法在 assembly draft 范围内修正，action=blocked 并说明原因。\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "当前阶段边界：\n{stage_operating_context}\n\n"
                    "AssemblyReactDecision JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "第一阶段需求摘要：\n{requirement_brief}\n\n"
                    "业务制造计划：\n{refined_plan_text}\n\n"
                    "第二阶段 pattern 选择：\n{runtime_pattern_selection}\n\n"
                    "第三阶段 pattern 结构摘要：\n{pattern_structure_summary}\n\n"
                    "第三阶段图行为计划：\n{graph_behavior_plan}\n\n"
                    "第四阶段节点策略计划：\n{node_strategy_plan}\n\n"
                    "第五阶段工具能力计划：\n{tool_capability_plan}\n\n"
                    "第六阶段资源条件计划：\n{resource_condition_plan}\n\n"
                    "上一轮 draft：\n{previous_draft}\n\n"
                    "validation_observation：\n{validation_observation}\n\n"
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
                    "Be concise, warm, and practical.\n\n"
                    "Factory 运行边界：\n{factory_operating_context}\n\n"
                    "当前阶段边界：\n{stage_operating_context}",
                ),
                ("placeholder", "{messages}"),
            ]
        )
    raise KeyError(f"unknown prompt id: {prompt_id}")


def output_json_schema(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2)
