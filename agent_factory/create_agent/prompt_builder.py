from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage
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
            "validator 只提供证据和建议，不会自动推进或回退 focus。"
            "不要直接写 .factory/system_state.json。active focus target files 是制造建议上下文，不是读写权限模型；"
            "baseline scaffold 和 baseline contracts 只由代码生成和 validator 负责，不由你逐个审计。"
        ),
        (
            "需要用户补充资源或决策时，必须调用 create_agent_control(action=ask_user, message=...)；"
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
            "full_static validation passed 后再调用 create_agent_control(action=finalize)，制造链路到此结束并进入待发布状态。"
            "发布不是制造 Agent 的职责；不要索要发布确认，不要调用发布工具，不要把用户的确认文本当作制造消息。"
            "物理发布只由用户在 Web 界面点击发布按钮触发，走系统 API 直接发布。"
            "如果用户继续提出修改意见，把它当作新的制造需求处理，修改后重新 full_static validation 和 finalize。"
        ),
        (
            "空 AgentPackage 已由代码生成，是基础结构的唯一来源。不要读取 skill example 或 schema 来巡检 scaffold。"
            "你的职责是根据用户需求完成一个完整能力增量闭环，然后显式调用 create_agent_validate。"
            "身份、内置 pattern assembly、package tool、scheduler seed、runtime resources、package knowledge、package state 这些稳定包面必须优先调用 create_agent_authoring，"
            "不要手动散写多个 package 文件后等待 validator 教你修。"
            "如果 validator 指向 scaffold-owned contract 结构损坏，优先用 create_agent_authoring(action='reset_contract', contract_key=...) 重置默认契约。"
            "业务代码内容、知识正文、资源值和自然语言 prompt 内容由你提供给 authoring 工具。"
        ),
        (
            "create_agent_authoring 参数必须使用 canonical shape。"
            "能力装配顺序固定为：先 model_pool_select 并写入 model bindings，再通过 pattern assembly 声明运行期 tool_access 与 inherited MCP candidates，"
            "需要继承 MCP 时立即 materialize_mcp_inheritance，再搜索/安装 SkillHub skill 并评估 skill guidance/assets/可注册执行入口，最后才创建 package tool 补齐剩余缺口。"
            "不要先写 package tool 再补模型选择、MCP 继承或 SkillHub 复用，也不要在模型池能力未确认前承诺或实现依赖特定模型能力的工具。"
            "模型池绑定只允许 create_agent_authoring(action='configure_model_bindings', bindings={main/task/compression...}, tool_bindings={...})；"
            "tool_bindings 与 bindings 是同级参数，绝不能塞进 bindings 内部。"
            "package tool 只允许 create_agent_authoring(action='upsert_package_tool', tool_spec=业务 ToolSpec 字段, tool_source=完整源码, "
            "python_requirements=[...], install_timeout_seconds=<estimated positive seconds>, expose_to_nodes=[...])；"
            "tool_spec 只允许包含 id、description、input_schema、output_schema、resources、risk_level、concurrent、output_compression；"
            "不要传 entrypoint、risk_evaluator、permission_scope 或 permission_tags，这些系统字段由 create_agent_authoring 统一生成。"
            "生成的 package tool 固定写入 tools/<tool_id>/tool.py，系统会生成 entrypoint=python:tools/<tool_id>/tool.py:run；"
            "tool_source 必须定义同步函数 run(arguments, resources)，不要使用 main、tool:main 或 python-import entrypoint。"
            "ToolSpec 的 input_schema 只描述运行期调用参数；"
            "不要把 output_schema、resources、risk_level、concurrent 或 output_compression 放进 input_schema。"
            "如果工具输出包含长列表、搜索候选、外部资源 id/slug/path、日志、报告或其他压缩后仍需保真的机器字段，给 tool_spec.output_compression.actions 写 action 级结构化 schema 和个性化 prompt；"
            "单链路工具把个性压缩当作唯一 action 配置；多 action 工具使用 output_compression.action_argument 和 actions 分别配置每个 action。没有 action 配置时直接走系统默认压缩。"
            "声明 Python 或系统包依赖时，必须填写 install_timeout_seconds；根据依赖体积、平台和网络状况估算，不要假定固定时长。"
            "运行时资源只在 contracts/resources.json 声明 descriptor；需要用户填写时先用 create_agent_authoring(action='upsert_resources', resources={}, resource_descriptors=[...]) 写声明，再调用 create_agent_control(action='ask_user', resource_requests=[{resource_id, description, secret}])。秘密值由前端安全写入资源存储，不会回传给模型。"
            "调用 create_agent_probe_tool(action='call') 时，必须填写 timeout_seconds，且应覆盖依赖初始化与目标工具实际执行的总时长。"
        ),
        (
            "如果需求需要可复用领域技能、文档生成惯例、设计方法、行业流程、模板资源或已有能力包，优先使用 SkillHub，而不是重新制造同类 package tool。"
            "SkillHub 必须发生在 model_pool_select、model bindings、pattern assembly tool_access 声明和必要的 inherited MCP materialization 之后、package tool authoring 之前。"
            "流程是：skillhub(action='search', query=...) 查找候选；query 必须是 1 到 3 个短关键词或精确技能名，"
            "不能传完整需求、长句、或 frontend design UI 网页 web 这类同义词堆叠；宽泛探索时拆成多次 search，例如 frontend、design、frontend design、ppt、web、网页。"
            "确认需要后只使用搜索结果里的 install_name 调用 skillhub(action='install', skill=install_name) 安装到当前 package extensions。"
            "不要把候选标题、版本号、描述文本或压缩摘要拼成 skill 参数。"
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
            "系统会在制造/probe 阶段构建并锁定依赖镜像，运行时只使用 environment.lock.json 指向的已验证镜像。"
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
    attachments = format_attachments_for_model(state.get("runtime_attachments"))
    interrupt_answer = _interrupt_answer_context(state.get("interrupt_answer"))
    return "\n\n".join(item for item in [task_analysis, interrupt_answer, attachments] if item)


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


def _stable_tool_names(tools: list[BaseTool]) -> list[str]:
    return sorted(str(tool.name) for tool in tools)
