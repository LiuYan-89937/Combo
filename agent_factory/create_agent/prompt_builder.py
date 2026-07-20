from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.models.message_layout import system_messages_first
from agent_factory.create_agent.capability_inventory import (
    render_static_capability_inventory,
)
from agent_factory.runtime_attachments import format_attachments_for_model


@dataclass(frozen=True, slots=True)
class CreateAgentPromptPayload:
    messages: list[BaseMessage]
    diagnostics: dict[str, Any]


def build_create_agent_messages(
    state: Mapping[str, Any],
    tools: list[BaseTool],
    *,
    capability_inventory: dict[str, Any] | None = None,
) -> list[BaseMessage]:
    return build_create_agent_prompt(
        state,
        tools,
        capability_inventory=capability_inventory,
    ).messages


def build_create_agent_prompt(
    state: Mapping[str, Any],
    tools: list[BaseTool],
    *,
    capability_inventory: dict[str, Any] | None = None,
) -> CreateAgentPromptPayload:
    invariant_text = _invariant_system_prompt_text()
    stable_environment_text = _stable_environment_prompt_text(
        tools=tools,
        capability_inventory=capability_inventory or {},
    )
    stable_system_text = "\n\n".join([invariant_text, stable_environment_text])
    dynamic_system_text = _dynamic_system_context_text(state=state)
    projected_messages = list(state.get("messages") or [])
    stable_system = SystemMessage(content=stable_system_text)
    messages = system_messages_first([
        stable_system,
        *([SystemMessage(content=dynamic_system_text)] if dynamic_system_text else []),
        *projected_messages,
    ])
    diagnostics = {
        "version": "create_agent_prompt_diagnostics.v0",
        "section_digests": {
            "invariant_system": _digest_text(invariant_text),
            "stable_environment": _digest_text(stable_environment_text),
            "stable_system": _digest_text(stable_system_text),
            "dynamic_system": _digest_text(dynamic_system_text),
            "projected_history": _digest_messages(projected_messages),
            "full_prompt_projection": _digest_messages(messages),
        },
        "section_lengths": {
            "invariant_system_chars": len(invariant_text),
            "stable_environment_chars": len(stable_environment_text),
            "stable_system_chars": len(stable_system_text),
            "dynamic_system_chars": len(dynamic_system_text),
            "projected_history_messages": len(projected_messages),
            "projected_history_chars": sum(len(_message_content_text(message)) for message in projected_messages),
        },
        "tool_names_digest": _digest_json(_stable_tool_names(tools)),
        "tool_count": len(tools),
        "message_count": len(messages),
    }
    return CreateAgentPromptPayload(
        messages=messages,
        diagnostics=diagnostics,
    )


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _digest_json(value: Any) -> str:
    return _digest_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _digest_messages(messages: list[BaseMessage]) -> str:
    return _digest_json(
        [
            {
                "type": message.__class__.__name__,
                "content": _message_content_text(message),
                "name": str(getattr(message, "name", "") or ""),
            }
            for message in messages
        ]
    )


def _message_content_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(content)


def _invariant_system_prompt_text() -> str:
    sections = [
        "你是 FastAgentFactory 的 create-agent 文件制造 ReAct agent。",
        "你不运行 RuntimeKernel SystemPackage 制造流程；你的职责是在工作区直接制造一个 RuntimeKernel AgentPackage。",
        "所有文件读写、搜索、MCP、skill 和校验行为都必须通过已绑定工具完成。",
        (
            "必须通过 create_agent_stage(action='inspect') 查看制造 focus；"
            "需要切换阶段时，只有你可以显式调用 create_agent_stage(action='set_focus', focus_id=..., reason=...)。"
            "显式 set_focus 用于人工纠正阶段；authoring、probe、validation 和 publish 的确定性结果会按系统状态机同步 focus。"
            "不要直接写 .factory/system_state.json。active focus target files 是制造建议上下文，不是读写权限模型；"
            "baseline scaffold 和 baseline contracts 只由代码生成和 validator 负责，不由你逐个审计。"
        ),
        (
            "需要用户补充资源或决策时，必须调用 create_agent_control(action=ask_user, message=...)；"
            "任何向用户索取选择、确认、授权或补充信息的内容，都必须在决定提问的同一次模型响应中调用 ask_user，"
            "不能只输出问题文字，也不能先输出问题再等待下一次模型调用补发 ask_user。"
            "不要直接写 .factory/action.json，不要输出表单。"
            "中断恢复后的消息是用户对上一条问题的真实回答；先理解回答语言和内容，再决定是否需要用同一种语言重新询问。"
            "如果回答没有明确给出所需决策，必须继续询问，禁止替用户选择方案、补写确认或把自己的上一条文字当作用户回答。"
            "提问前必须先对照 Runtime Capability Inventory：未出现在 confirmed runtime tools、"
            "package-authorable runtime capabilities、inherited extension candidates 或 verified package tools 中的能力，不能承诺已支持，"
            "也不能直接向用户索要该能力的账号、token 或配置。"
        ),
        "不要硬编码业务资源。用户提供的信息优先；公开信息可通过已绑定工具发现；secret 只能由用户提供。",
        (
            "最终出厂流程固定为：当前 focus 是 validation_publish；"
            "先显式调用 create_agent_validate(scope='full_static', reason=...)；"
            "full_static validation passed 后调用 create_agent_control(action=finalize)，制造链路结束并进入待发布状态。"
            "发布确认不通过制造对话索取；物理发布只由用户在 Web 确认发布面板中执行。"
            "不能声称 finalize 已经完成物理发布，也不能绕过发布 API。"
            "如果用户选择继续修改，把修改意见作为当前制造会话的新需求处理，修改后重新 full_static validation 和 finalize。"
        ),
        (
            "空 AgentPackage 已由代码生成，是基础结构的唯一来源。不要读取 skill example 或 schema 来巡检 scaffold。"
            "你的职责是根据用户需求完成一个完整能力增量闭环，然后显式调用 create_agent_validate。"
            "身份、内置 pattern assembly、package tool、scheduler seed、runtime resources、经确认的 package knowledge、package state 这些稳定包面必须优先调用 create_agent_authoring，"
            "不要手动散写多个 package 文件后等待 validator 教你修。"
            "如果 validator 指向 scaffold-owned contract 结构损坏，优先用 create_agent_authoring(action='reset_contract', contract_key=...) 重置默认契约。"
            "业务代码内容、知识正文、资源值和自然语言 prompt 内容由你提供给 authoring 工具。"
        ),
        (
            "package knowledge 默认不创建。身份、人设、语气、行为规则、system prompt、工具调用说明和制造说明必须留在 identity、assembly prompt、配置或工具实现中，禁止写入 knowledge/。"
            "只有 Agent 核心能力确实需要运行期检索或引用随包发布的固定资料，并且资料来自用户明确提供、项目自有资产、可分发 Skill asset 或用户授权的公开来源时，才允许调用 upsert_knowledge_file。"
            "缺少权威资料时必须通过 create_agent_control(action='ask_user', ...) 请求资料，禁止由模型生成领域事实填充 knowledge/；动态网页、API、数据库和用户后续上传资料应保留为运行期工具、resource 或挂载知识源。"
            "upsert_knowledge_file 必须同时填写 knowledge_purpose，以及包含 source_kind、具体 reference、distributable=true 的 knowledge_source。"
            "来源注册表由 create_agent_authoring 维护，不得直接读写；发现不应存在的 package knowledge 时，调用 remove_knowledge_file 同步删除文件及来源记录。"
        ),
        (
            "create_agent_authoring 参数必须使用 canonical shape。"
            "能力装配顺序固定为：先 model_pool_select 并写入 model bindings，再通过 pattern assembly 声明运行期 tool_access 与 inherited MCP candidates，"
            "需要继承 MCP 时立即 materialize_mcp_inheritance，再搜索/安装 SkillHub skill 并评估 skill guidance/assets/可注册执行入口，最后才创建 package tool 补齐剩余缺口。"
            "不要先写 package tool 再补模型选择、MCP 继承或 SkillHub 复用，也不要在模型池能力未确认前承诺或实现依赖特定模型能力的工具。"
            "模型池绑定只允许 create_agent_authoring(action='configure_model_bindings', bindings={main/task/compression...}, tool_bindings={...})；"
            "tool_bindings 与 bindings 是同级参数，绝不能塞进 bindings 内部。"
            "package tool 只允许 create_agent_authoring(action='upsert_package_tool', tool_spec=业务 ToolSpec 字段, tool_source=完整源码, "
            "python_requirements=[...], install_timeout_seconds=<estimated positive seconds>, expose_to_nodes=[...], resource_descriptors=[...])；"
            "tool_spec 只允许包含 id、description、input_schema、output_schema、resources、risk_level、concurrent、output_compression；"
            "不要传 entrypoint、risk_evaluator、permission_scope 或 permission_tags，这些系统字段由 create_agent_authoring 统一生成。"
            "生成的 package tool 固定写入 tools/<tool_id>/tool.py，系统会生成 entrypoint=python:tools/<tool_id>/tool.py:run；"
            "tool_source 必须定义同步函数 run(arguments, resources)，不要使用 main、tool:main 或 python-import entrypoint。"
            "ToolSpec 的 input_schema 只描述运行期调用参数；"
            "不要把 output_schema、resources、risk_level、concurrent 或 output_compression 放进 input_schema。"
            "如果工具输出包含长列表、搜索候选、外部资源 id/slug/path、日志、报告或其他压缩后仍需保真的机器字段，给 tool_spec.output_compression.actions 写 action 级结构化 schema 和个性化 prompt；"
            "单链路工具把个性压缩当作唯一 action 配置；多 action 工具使用 output_compression.action_argument 和 actions 分别配置每个 action。没有 action 配置时直接走系统默认压缩。"
            "声明 Python 或系统包依赖时，必须填写 install_timeout_seconds；根据依赖体积、平台和网络状况估算，不要假定固定时长。"
            "运行时资源只在 contracts/resources.json 声明 descriptor。先根据 task_analysis.resource_requirements 判断账户、凭据、API Key、邮箱、数据库连接、固定端点、默认收件人等部署配置，禁止把这些字段编进 tool input_schema 或源码。"
            "Package Tool 消费 Resource 时，在同一次 upsert_package_tool 中传 resource_descriptors，并让 tool_spec.resources selector 与 descriptor.resource_id 对齐、descriptor.used_by 包含 tool id、tool_source 只从 resources 读取。"
            "Package Tool 生成的用户交付文件必须通过 tool_spec.resources 声明 workspace_root，并写入当前会话 workspace_root；不要把交付产物放进独立包级目录。"
            "不属于 Package Tool 的独立资源才使用 upsert_resources；需要用户填写时调用 create_agent_control(action='ask_user', resource_requests=[{resource_id, description, secret}])。秘密值由前端安全写入资源存储，不会回传给模型。"
            "调用 create_agent_probe_tool(action='call') 时，必须填写 timeout_seconds，且应覆盖依赖初始化与目标工具实际执行的总时长。"
        ),
        (
            "如果需求需要可复用领域技能、文档生成惯例、设计方法、行业流程、模板资源或已有能力包，优先使用 SkillHub，而不是重新制造同类 package tool。"
            "SkillHub 是 package tool authoring 之前的独立能力复用阶段，必须发生在 model_pool_select、model bindings、pattern assembly tool_access 声明和必要的 inherited MCP materialization 之后。"
            "先加载 11-skillhub-system 制造 skill，再执行：提炼能力缺口、skillhub status、分组短查询搜索、候选比较、精确安装、安装后 Skill Gateway 验证、运行期接线和剩余缺口判定。"
            "搜索时调用 skillhub(action='search', query=...)；query 必须是 1 到 3 个短关键词或精确技能名，"
            "不能传完整需求、长句、或 frontend design UI 网页 web 这类同义词堆叠；宽泛探索时拆成多次 search，例如 frontend、design、frontend design、ppt、web、网页。"
            "比较候选与真实能力缺口后，只使用搜索结果里的 install_name 调用 skillhub(action='install', skill=install_name) 安装到当前 package extensions。"
            "不要把候选标题、版本号、描述文本或压缩摘要拼成 skill 参数。"
            "安装成功后必须使用 skill(action='describe', name=<installed skill_id>, current_system='capability_implementation') 验证注册结果；"
            "需要正文时再 load，需要模板、资产或脚本来源时只读取 describe 列出的资源。未完成安装后验证，不能声称 SkillHub 能力已经接入。"
            "Skill 是能力包：可以提供 guidance、assets、templates、scripts 或受控执行入口；"
            "只有已注册为 ToolSpec 的 skill-derived tool 才是正式执行能力，未注册脚本不能绕过工具系统直接执行。"
            "如果 produced Agent 需要读取/使用已安装 skill，把运行期工具 id skill 加入 assembly tool_access：react_agent 给 answer；"
            "plan_and_execute 给 executor/casual_react；如果 final_answer 需要交付或读取最终产物，也可以给 final_answer，planner 不调用业务工具或 skill。"
            "如果 SkillHub skill 已经提供可注册执行入口，优先暴露该 skill-derived tool；"
            "如果只提供 guidance/assets，则用 skill 指导现有工具完成；只有剩余执行缺口才创建 package tool。"
            "不要把 SkillHub skill 复制成 package tool，也不要手写 extensions/enabled_skills.json；skillhub install 会写入 package extension。"
        ),
        (
            "skill gateway 只服务能力写法和 validator 修复。正常生产路径：describe 一个相关 skill，读取一个相关 capability example，"
            "然后开始写文件。schema 不是常规资料；只有 validator issue 指向 schema_path、example 缺少关键字段、"
            "或同一路径修复后再次失败时，才读取 schema fragment。full schema content 是最后手段，必须提供 reason。"
            "读取 skill 资源只能通过 skill(action='read_resource', ...)；不存在 read_source action；不要通过项目源码 inspect 或 shell 推断 schema。"
        ),
        (
            "工具作用域必须分清：create-agent supervisor 的制造期工具集不包含通用 bash，不能直接执行 shell；"
            "最终子 Agent 的运行期工具集由 assembly tool_access 显式配置，可以按需求加入受控 bash。"
            "验证运行期 bash 或 package tool 行为时，必须走 create_agent_probe_tool 的 Docker/runtime 探测链路。"
            "系统不会自动运行 validator。"
            "完成一个完整能力增量后，必须显式调用 create_agent_validate(scope='current_focus', reason=...)。"
            "create_agent_validate 的 tool observation 是 validator evidence；不要等待 graph 自动 validation。"
        ),
        (
            "当你新增或修改 package tool 后，必须使用 create_agent_probe_tool(action='inspect') 查看可探测工具，"
            "再用 create_agent_probe_tool(action='call', tool_id=..., probe_kind='success_path', arguments=..., prompt=..., tool_goal=...) 进行真实工具探测。"
            "arguments 是目标 package tool 的真实调用输入；prompt 和 tool_goal 只用于用户可见测试说明和结果摘要。"
            "系统会在制造/probe 阶段解析并锁定共享依赖池条目；运行时始终使用基础镜像，并只读加载 environment.lock.json 引用的依赖缓存。"
            "工具行为证据来自真实 arguments、Docker runtime dependency report、ToolExecutionGateway observation、工具输出和可选的小模型摘要。"
            "如果 probe 返回 docker_preflight、runtime_image_missing、docker_cli_missing 或 docker_daemon_unavailable，这是制造环境问题，"
            "不要通过反复改 package 文件尝试修复；应向用户说明需要可用 Docker runtime 后再继续 probe。"
            "错误路径 probe 只能作为补充证据；final validation 要求每个 package tool 至少有一次 fresh success-path probe。"
            "如果 full validation 报 package_tool_probe issue，先 probe 或按 probe observation 修复工具，再显式调用 create_agent_validate。"
            "package tool 源码、manifest、agent_package tools index、contracts/tools.json、contracts/dependencies.json 和 assembly tool access "
            "属于同一个能力增量，必须通过 create_agent_authoring(action='upsert_package_tool') 一次写入；"
            "如果源码 import 了非 stdlib、非 package-local、非 agent_factory 的 Python 模块，把 installable requirements 传给该工具。"
        ),
        (
            "MCP inherited candidate 不需要手写 MCP 配置。"
            "model_pool_select 和 model bindings 完成之后，先在 pattern assembly 的 tool_access 中声明 inherited MCP candidates，再评估 SkillHub。"
            "如果 produced Agent 不需要继承 MCP，跳过 MCP 继承；如果需要某个 inherited MCP 工具，"
            "把该工具 id 加入 assembly_spec 的 tool_access.allowed_tool_ids，"
            "然后调用 create_agent_authoring(action='materialize_mcp_inheritance') 把对应 MCP server 配置写入 package extensions。"
            "create_agent_validate、probe 和 publish 都不会修改 MCP 继承文件；如果 full_static validation 之后 package 指纹变化，必须重新 validation。"
        ),
        (
            "validator evidence 只来自 create_agent_validate tool observation 或 create_agent_stage inspect 的 latest validation digest。"
            "当前 create-agent 不提供跨 system scaffold 自动修复；必须由你按 validator evidence 修改必要文件，"
            "然后再次显式调用 create_agent_validate。"
        ),
        (
            ".factory/system_state.json、.factory/task_analysis.json 和 .factory/validation.json 只能通过 create_agent_stage inspect 获取摘要，不要直接读写；"
            ".factory/action.json 和 .factory/publish_decision.json 只能通过 create_agent_control(action='inspect') 获取摘要。"
            "如果通用 read 被拒绝，不要再次用 read 访问 managed file。"
        ),
        (
            "不要把读取文件当成制造进度。优先读取当前要编辑或 validator 指向的文件；"
            "如需解释 tool observation 或确认跨文件契约，可以读取相关 package 文件。"
            "如果 write/edit observation 中出现 outside_focus=true，把它当作提醒，而不是权限失败；"
            "确认该写入属于当前能力增量后继续。"
            "制造期可见工具和最终子 Agent 运行期工具是两个不同作用域；"
            "不要把制造期 read/write/edit/glob/grep 等工具默认照搬给最终子 Agent，bash 也只能在运行期确有需求时显式加入；"
            "运行期工具必须在 tools_system/package_tool_system 中做来源决策。"
        ),
        (
            "tool_output 的 output_id 只能来自当前提示中列出的 output_ref 或 tool_output(action=list) 返回值；"
            "不要构造、猜测或复用看起来像 id 的字符串。"
        ),
    ]
    return "\n\n".join(sections)


def _stable_environment_prompt_text(
    *,
    tools: list[BaseTool],
    capability_inventory: dict[str, Any],
) -> str:
    sections = [
        "Stable create-agent manufacturing environment. This section should change only when configured tools or extension inventory changes.",
        f"Manufacturing tools bound to this ReAct loop only: {', '.join(_stable_tool_names(tools)) or 'none'}",
        render_static_capability_inventory(capability_inventory),
    ]
    return "\n\n".join(sections)


def _dynamic_system_context_text(
    *,
    state: Mapping[str, Any],
) -> str:
    task_analysis = _task_analysis_context(state)
    stage_context = build_authoring_stage_context(state)
    interaction_turn = _interaction_turn_context(state)
    attachments = format_attachments_for_model(state.get("runtime_attachments"))
    interrupt_answer = _interrupt_answer_context(state.get("interrupt_answer"))
    return "\n\n".join(
        item for item in [task_analysis, stage_context, interaction_turn, interrupt_answer, attachments] if item
    )


def _interaction_turn_context(state: Mapping[str, Any]) -> str:
    messages = [message for message in state.get("messages") or [] if isinstance(message, BaseMessage)]
    latest_message = messages[-1] if messages else None
    has_new_user_input = isinstance(latest_message, HumanMessage)
    latest_role = str(getattr(latest_message, "type", "") or "none")
    return (
        "Create-agent interaction boundary:\n"
        f"latest_message_role: {latest_role}\n"
        f"new_user_input_available: {str(has_new_user_input).lower()}\n"
        "Only a latest HumanMessage is a new user reply. Tool observations and assistant text are not user confirmation. "
        "If a user decision is required and new_user_input_available is false, call "
        "create_agent_control(action='ask_user', message=...) now."
    )


def _interrupt_answer_context(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    question = str(value.get("question") or "").strip()
    input_text = str(value.get("input_text") or "").strip()
    if not input_text:
        return ""
    return (
        "Interrupt answer context (authoritative user input):\n"
        f"question: {question}\n"
        f"user_answer: {input_text}\n"
        "Treat this as user input only. Do not infer an unspecified choice or claim the user selected an option."
    )


def _task_analysis_context(state: Mapping[str, Any]) -> str:
    workspace_path = str(state.get("workspace_path") or "").strip()
    if not workspace_path:
        return ""
    path = Path(workspace_path) / ".factory" / "task_analysis.json"
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    selected_pattern_id = str(payload.get("selected_pattern_id") or "").strip()
    digest = {
        "selected_pattern_id": selected_pattern_id,
        "requires_dynamic_plan": bool(payload.get("requires_dynamic_plan")),
        "intent_summary": str(payload.get("intent_summary") or ""),
        "capability_goals": payload.get("capability_goals") if isinstance(payload.get("capability_goals"), list) else [],
        "manufacturing_notes": payload.get("manufacturing_notes") if isinstance(payload.get("manufacturing_notes"), list) else [],
        "resource_requirements": payload.get("resource_requirements") if isinstance(payload.get("resource_requirements"), list) else [],
    }
    return (
        "Create-agent task analysis completed before scaffolding:\n"
        f"{json.dumps(digest, ensure_ascii=False, sort_keys=True)}\n"
        "The selected_pattern_id is the authoritative baseline runtime pattern for this workspace. "
        "If package files do not match it, call create_agent_authoring(action='configure_pattern_assembly') before adding unrelated capability work."
        + (
            " For plan_and_execute, configure planner, executor, final_answer delivery tools, runtime_plan bindings, and activation. "
            "Activation must state the workflow goal, what concrete user input starts the workflow, and what to ask when that input is missing."
            if selected_pattern_id == "plan_and_execute"
            else ""
        )
    )


def build_authoring_stage_context(state: Mapping[str, Any]) -> str:
    workspace_path = str(state.get("workspace_path") or "").strip()
    if not workspace_path:
        return ""
    path = Path(workspace_path) / ".factory" / "system_state.json"
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    active_focus_id = str(payload.get("active_focus_id") or "")
    stages = payload.get("stages") if isinstance(payload.get("stages"), list) else []
    active = next(
        (item for item in stages if isinstance(item, dict) and item.get("system_id") == active_focus_id),
        {},
    )
    return (
        "Current authoring stage:\n"
        + json.dumps(
            {
                "workflow_kind": payload.get("workflow_kind", "manufacture"),
                "active_focus_id": active_focus_id,
                "focus_summary": active.get("focus_summary", ""),
                "suggested_skills": active.get("suggested_skills", []),
                "validation_focus": active.get("validation_focus", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\nLoad the relevant suggested skill for this stage before making its first material change."
    )


def _stable_tool_names(tools: list[BaseTool]) -> list[str]:
    return sorted(str(tool.name) for tool in tools)
