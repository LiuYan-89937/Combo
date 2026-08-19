from __future__ import annotations

from dataclasses import dataclass

from combo.dynamic_runtime.capability_definitions import ToolModelPresentation
from combo.runtime_i18n import LocalizedText, RuntimeLocale
from combo.tooling.spec import ToolSpec


@dataclass(frozen=True, slots=True)
class BuiltinToolCopy:
    description: LocalizedText
    schema_error_guidance: LocalizedText | None = None


def _copy(zh_cn: str, en_us: str, *, zh_guidance: str = "", en_guidance: str = "") -> BuiltinToolCopy:
    guidance = LocalizedText(zh_guidance, en_guidance) if zh_guidance or en_guidance else None
    return BuiltinToolCopy(description=LocalizedText(zh_cn, en_us), schema_error_guidance=guidance)


BUILTIN_TOOL_COPY: dict[str, BuiltinToolCopy] = {
    "read": _copy(
        "按行读取当前工作区内的 UTF-8 文本文件。路径不确定时先用 ls 核对目录，不要把一次读取失败当作文件不存在。",
        "Read a bounded line range from a UTF-8 text file in the current workspace. If a path is uncertain, inspect its directory with ls before concluding that the file is unavailable.",
    ),
    "write": _copy(
        "在当前工作区内创建或整体替换文本文件。完整正文使用 write_once；需要分段生成时依次使用 start、append、commit，放弃时使用 abort；局部修改请用 edit。",
        "Create or fully replace a text file in the current workspace. Use write_once for complete content; use start, append, and commit for staged generation, or abort to discard it. Use edit for local changes.",
        zh_guidance="必须明确 action。write_once 需要 path 和完整 content；start 需要 path；append 需要真实 write_id 和 content；commit 或 abort 需要真实 write_id。",
        en_guidance="Always provide action. write_once requires path and complete content; start requires path; append requires a real write_id and content; commit or abort requires a real write_id.",
    ),
    "edit": _copy(
        "在当前工作区内对单个 UTF-8 文件执行精确文本替换。",
        "Apply an exact text replacement to one UTF-8 file in the current workspace.",
        zh_guidance="提供 path、old_text 和 new_text。old_text 默认只能匹配一处；替换全部匹配时设置 replace_all=true。",
        en_guidance="Provide path, old_text, and new_text. old_text must match once by default; set replace_all=true to replace every match.",
    ),
    "glob": _copy("按 glob 模式查找当前工作区内的文件路径。", "Find file paths in the current workspace with a glob pattern."),
    "grep": _copy("在当前工作区的文件内容中搜索文本或正则表达式。", "Search file contents in the current workspace for text or a regular expression."),
    "ls": _copy("列出当前工作区内指定目录的内容。", "List the contents of a directory in the current workspace."),
    "ask_usr": _copy(
        "当子 Agent 缺少继续任务所必需的信息时，在主对话中向用户提出一个聚焦问题。少量互斥答案使用 choices，需要自由输入时启用 allow_free_text；不要用于工具审批或普通进度通知。",
        "Ask one focused question in the main conversation when a child Agent cannot continue without required information. Use choices for a small mutually exclusive set and allow_free_text for written answers. Do not use this for approvals or routine progress updates.",
    ),
    "shell": _copy(
        "在当前工作区中使用平台 shell 启动命令。普通命令使用 foreground 并等待完整结果；只有服务或监听器等跨轮次长期进程才使用 background。",
        "Run a platform shell command in the current workspace. Use foreground for ordinary commands and wait for the complete result; use background only for long-lived services or listeners that must outlive the turn.",
    ),
    "shell_status": _copy("查看 shell 以 background 模式启动的进程状态和已收集输出。", "Inspect the status and collected output of a process started by shell in background mode."),
    "shell_stop": _copy("终止 shell 启动的后台进程树，并返回最终状态和输出。", "Stop a background process tree started by shell and return its final status and output."),
    "tool_output": _copy(
        "读取保存在模型上下文之外的完整工具输出。已有真实 output_id 时直接读取；否则先列出可用输出。不得编造 output_id。",
        "Retrieve complete tool output retained outside the model context. Read directly when a real output_id is available; otherwise list available outputs first. Never invent an output_id.",
    ),
    "capability": _copy(
        "按需发现 Tool、MCP Server 和 Skill。先搜索顶层目录；选择 MCP Server 后再搜索其二级目录。搜索结果只是候选，首次使用精确对象前必须 describe 并遵循返回的定义。",
        "Discover Tool, MCP Server, and Skill capabilities on demand. Search the top-level catalog first, then a selected MCP server's directory. Results are candidates only; describe each exact target before first use and follow its returned definition.",
    ),
    "capability_invoke": _copy(
        "调用已通过 capability describe 确认的精确 Tool 或 MCP Tool。参数必须严格遵循该对象的输入 Schema；不要猜测或用校验失败探测参数。",
        "Invoke an exact Tool or MCP Tool already confirmed by capability describe. Follow that target's input schema exactly; never guess arguments or probe them through validation errors.",
    ),
    "delegate": _copy(
        "非阻塞地启动一个边界明确的子 Agent 任务。提供面向用户的角色名、执行策略、目标、验收条件和最小充分能力；没有可选能力时传空数组。接受成功不代表任务已经完成，禁止立即轮询。",
        "Start one bounded child-Agent task without blocking. Provide a user-facing role name, execution strategy, objective, acceptance criteria, and the smallest sufficient capability set; use an empty array when none is needed. Acceptance is not completion; do not poll immediately.",
    ),
    "delegate_continue": _copy(
        "继续一个已经结束的子 Agent 任务。沿用该子 Agent 的 checkpoint、角色、模型与能力上下文，创建新的任务修订并执行补充、纠正或升级要求。",
        "Continue a terminal child-Agent task. Reuse its checkpoint, role, model, and capability context while starting a new task revision for an improvement, correction, or follow-up.",
    ),
    "delegate_message": _copy(
        "向正在运行的子 Agent 直接插入一条用户消息。消息在下一个安全执行边界被读取，不取消当前工具，也不使用主会话引导流程。",
        "Insert a user message directly into a running child Agent. It is consumed at the next safe execution boundary without cancelling the current tool or using main-conversation steering.",
    ),
    "delegation_status": _copy("查看当前会话中所有子 Agent 任务的权威状态。仅在用户明确询问进度或完成通知需要读取交付详情时使用，不要轮询。", "Inspect authoritative status for all child-Agent tasks in the current conversation. Use only for an explicit progress request or to retrieve delivery details after a terminal notification; do not poll."),
    "memory": _copy("保存本轮形成的、可跨会话复用的用户偏好、约束、决定、事实或产物信息。跨会话检索由上下文系统自动完成，不要用此工具搜索记忆。", "Persist a reusable user preference, constraint, decision, fact, or artifact established in this turn. Cross-session retrieval is automatic; do not use this tool to search memories."),
    "mcp_content": _copy("读取 capability 目录中已确认的 MCP Resource，或按声明参数展开 MCP Prompt。必须先搜索并 describe 精确对象，不得复用其他对象的定义。", "Read a confirmed MCP Resource or expand an MCP Prompt with its declared arguments. Search and describe the exact object first; another object's definition is not interchangeable."),
    "knowledge": _copy("搜索、查看、添加和移除共享知识库来源。回答内部文档问题前先搜索。仅主 Agent 可用。", "Search, inspect, add, and remove shared knowledge sources. Search before answering from internal documents. Available only to the main Agent."),
    "scheduler": _copy("创建和管理绑定当前主 Agent 工作区的定时任务。仅主 Agent 可用。", "Create and manage scheduled tasks bound to the main Agent's current workspace. Available only to the main Agent."),
    "skillhub": _copy("在 SkillHub 中搜索、安装或移除 Skill，并同步到统一 Skill 池。仅主 Agent 可用。", "Search, install, or remove Skills through SkillHub and synchronize them into the unified Skill pool. Available only to the main Agent."),
    "skill_installer": _copy(
        "安装一个已经取得全部文件的完整 Skill 包。示例：用户要求安装网页中的 Skill，并且你已经取得 SKILL.md 与 references/guide.md，此时把两个文件都放入 package.files 后调用。反例：只有仓库 URL、尚未读取包内容时不要调用；应先获取并整理完整文件，禁止猜测缺失内容。仅主 Agent 可用。",
        "Install one complete Skill package after obtaining all of its files. Example: the user asks to install a Skill shown on a web page and you have collected SKILL.md plus references/guide.md; call with both files in package.files. Counterexample: when only a repository URL is known and its files have not been read, do not call yet; retrieve and assemble the complete package first. Never invent missing content. Available only to the main Agent.",
    ),
    "mcp_installer": _copy(
        "从权威来源取得完整配置后安装一个 MCP Server，server_config 接受配置对象或 JSON/YAML 文本，每次调用只提交一个 Server。示例：官方文档给出 {\"mcpServers\":{\"amap\":{\"url\":\"https://example.com/mcp\"}}}，将整份配置作为 server_config 传入。反例：只知道服务名称时，不要猜 command、URL、请求头或环境变量；应先找到官方可执行配置。仅主 Agent 可用。",
        "Install one MCP server after obtaining a complete configuration from an authoritative source. server_config accepts a decoded object or JSON/YAML text, with one server per call. Example: official docs provide {\"mcpServers\":{\"amap\":{\"url\":\"https://example.com/mcp\"}}}; pass the whole document as server_config. Counterexample: when only a service name is known, do not guess command, URL, headers, or environment values; find the official executable configuration first. Available only to the main Agent.",
    ),
    "skill": _copy("按需加载当前运行时可用的 Skill。先 describe，再加载 SKILL.md；只读取 describe 或 load 返回目录中列出的资源。", "Load a Skill available to the current runtime on demand. Describe it first, then load SKILL.md, and read only resources listed by describe or load."),
    "browser_open": _copy("在隔离浏览器中打开 HTTP 或 HTTPS 地址。默认复用活动页面；仅在确实需要并行页面时创建新标签，并返回后续操作使用的 page_id。", "Open an HTTP or HTTPS URL in the isolated browser. Reuse the active page by default; create a new tab only when simultaneous pages are intentional. Returns a page_id for later operations."),
    "browser_snapshot": _copy("读取当前页面的结构化文本和可选链接。页面状态不确定时先使用此工具。", "Read structured text and optional links from the current page. Use this first when page state is uncertain."),
    "browser_click": _copy("点击浏览器页面中的目标元素。", "Click a target element on the browser page."),
    "browser_type": _copy("向浏览器输入元素填写文本。只有确实需要按回车提交时才启用 submit。", "Enter text into a browser input. Enable submit only when pressing Enter is intentional."),
    "browser_select": _copy("在浏览器下拉选择元素中选择一个或多个值。", "Select one or more values in a browser select element."),
    "browser_press": _copy("在目标元素或当前页面上按键或执行键盘快捷键。", "Press a key or keyboard shortcut on a target element or the current page."),
    "browser_scroll": _copy("按像素距离滚动当前页面或可滚动元素。", "Scroll the current page or a scrollable element by pixel deltas."),
    "browser_wait": _copy("在限定时间内等待，或等待目标元素达到指定状态。", "Wait for a bounded duration or for a target element to reach a requested state."),
    "browser_extract": _copy("从整个页面或指定 CSS 选择器中提取文本、HTML 或链接。", "Extract text, HTML, or links from the page or a CSS selector."),
    "browser_screenshot": _copy("截取当前页面 PNG 图片并返回给支持视觉的模型；纯文本模型不可见此工具。", "Capture the current page as a PNG for a vision-capable model. This tool is hidden from text-only models."),
    "browser_download": _copy("点击下载目标，并把得到的文件保存到当前工作区。", "Click a download target and save the resulting file in the current workspace."),
    "browser_upload": _copy("通过文件输入控件上传用户已授权的当前工作区文件。该操作需要审批。", "Upload user-authorized files from the current workspace through a file input. This action requires approval."),
    "browser_tabs": _copy("列出当前隔离浏览器上下文中的所有页面。", "List all pages in the current isolated browser context."),
    "browser_close": _copy("关闭一个浏览器页面，或关闭当前 Agent 会话的整个隔离浏览器上下文。", "Close one browser page or the entire isolated browser context for the current Agent session."),
    "generate_image": _copy("使用模型池中配置的默认生图模型生成原创视觉素材，并保存到当前会话工作区。", "Generate original visual assets with the default image model configured in the model pool and save them in the current conversation workspace."),
}


def presentations_for_builtin(spec: ToolSpec) -> dict[RuntimeLocale, ToolModelPresentation]:
    try:
        copy = BUILTIN_TOOL_COPY[spec.id]
    except KeyError as exc:
        raise ValueError(f"builtin tool has no bilingual presentation: {spec.id}") from exc
    return {
        locale: ToolModelPresentation(
            description=copy.description.resolve(locale),
            schema_error_guidance=(
                copy.schema_error_guidance.resolve(locale)
                if copy.schema_error_guidance is not None
                else spec.schema_error_guidance
            ),
            input_schema=spec.input_schema,
        )
        for locale in ("zh-CN", "en-US")
    }
