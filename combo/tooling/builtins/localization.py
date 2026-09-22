from __future__ import annotations

from dataclasses import dataclass

from combo.runtime_i18n import RuntimeLocale
from combo.tooling.spec import ToolSpec
from combo.tooling.builtins.skill.specs import SKILL_TOOL_DESCRIPTION
from combo.tooling.builtins.memory.specs import MEMORY_TOOL_DESCRIPTION


@dataclass(frozen=True, slots=True)
class BuiltinToolLocalization:
    description_en_us: str
    schema_error_guidance_en_us: str = ""


BUILTIN_TOOL_LOCALIZATIONS: dict[str, BuiltinToolLocalization] = {
    'read': BuiltinToolLocalization(
        description_en_us='Read a bounded line range from a UTF-8 text file in the current workspace. offset is the 1-based starting line (default 1), not a byte offset; limit is the maximum number of lines (default 200, maximum 2000). If a path is uncertain, locate it with the files action of rg before concluding that it is unavailable.',
    ),
    'write': BuiltinToolLocalization(
        description_en_us='Create or fully replace a text file in the current workspace. Use write_once with path and complete content; for staged generation use start with path, append with the returned write_id and content, then commit with write_id, or abort to discard it. Only write_once/start accept path; append/commit/abort must not include path. Use edit for local changes.',
        schema_error_guidance_en_us='Always provide action. write_once requires path and complete content; start requires path; append requires a real write_id and content; commit or abort requires a real write_id. append/commit/abort do not accept path.',
    ),
    'edit': BuiltinToolLocalization(
        description_en_us='Apply an exact text replacement to one UTF-8 file in the current workspace. Read that same path first and copy old_text exactly, including whitespace and newlines; do not use text from another file or an older version. A failed match leaves the file unchanged: read it again or locate the text with rg, rather than switching to a full overwrite.',
        schema_error_guidance_en_us='Provide path, old_text, and new_text. old_text must match once by default; set replace_all=true to replace every match.',
    ),
    'rg': BuiltinToolLocalization(
        description_en_us='Use this tool to find paths or search file contents in the workspace, including locating code by name, extension, directory structure, text, or regular expression. Do not invoke grep, find, or ls through shell for file discovery or content search. Always pass action and pattern; path is optional. Find files: {"action":"files","pattern":"**/*.py"}. Search content: {"action":"search","pattern":"ModelPool","path":"combo"}.',
        schema_error_guidance_en_us='The fixed arguments are action, pattern, path, and max_results. Action and pattern are required.',
    ),
    'ask_usr': BuiltinToolLocalization(
        description_en_us='Ask one focused question in the main conversation when a child Agent cannot continue without required information. Use choices for a small mutually exclusive set and allow_free_text for written answers. Do not use this for approvals or routine progress updates.',
    ),
    'shell': BuiltinToolLocalization(
        description_en_us='Run build, validation, formatting, version-control, script, or service commands in the current workspace. Use rg for file discovery and file-content search, and read for line-based file reading. Use foreground for short commands within the tool timeout. Use background for long renders, builds, or services; it returns process_id immediately and completion is reported automatically. Use shell_status to inspect or wait; do not use sleep polling or detach commands with nohup or &.',
    ),
    'shell_status': BuiltinToolLocalization(
        description_en_us='Inspect a background process. wait_seconds waits for completion; after_revision also returns early for new output. Use the last output_revision. Background completion is reported automatically, so repeated polling is unnecessary.',
    ),
    'shell_stop': BuiltinToolLocalization(
        description_en_us='Stop a background process tree started by shell and return its final status and output.',
    ),
    'tool_output': BuiltinToolLocalization(
        description_en_us='Retrieve complete tool output retained outside the model context. Read directly when a real output_id is available; otherwise list available outputs first. Never invent an output_id.',
    ),
    'capability': BuiltinToolLocalization(
        description_en_us="Discover Tool, MCP Server, and Skill capabilities on demand. Search the top-level catalog first, then a selected MCP server's directory. Results are candidates only; describe each exact target before first use and follow its returned definition.",
    ),
    'capability_invoke': BuiltinToolLocalization(
        description_en_us="Invoke an exact Tool or MCP Tool already confirmed by capability describe. Follow that target's input schema exactly; never guess arguments or probe them through validation errors.",
    ),
    'delegate': BuiltinToolLocalization(
        description_en_us="Start one bounded child-Agent task without blocking. The child inherits the main Agent's currently enabled capabilities and stable built-in tools, excluding main-only controls. Optional capability names must already be enabled; an empty array still inherits the enabled set. Provide a role name, strategy, objective, and acceptance criteria. Acceptance is not completion; do not poll immediately.",
    ),
    'delegate_continue': BuiltinToolLocalization(
        description_en_us='Continue a terminal child-Agent task. Reuse its checkpoint, role, and model while refreshing capabilities from the currently enabled main Agent profile. Start a new task revision for an improvement, correction, or follow-up.',
    ),
    'delegate_message': BuiltinToolLocalization(
        description_en_us='Insert a user message directly into a running child Agent. It is consumed at the next safe execution boundary without cancelling the current tool or using main-conversation steering.',
    ),
    'delegation_status': BuiltinToolLocalization(
        description_en_us='Inspect authoritative status for all child-Agent tasks in the current conversation. Use only for an explicit progress request or to retrieve delivery details after a terminal notification; do not poll.',
    ),
    'memory': BuiltinToolLocalization(
        description_en_us=MEMORY_TOOL_DESCRIPTION,
    ),
    'mcp_content': BuiltinToolLocalization(
        description_en_us="Read a confirmed MCP Resource or expand an MCP Prompt with its declared arguments. Search and describe the exact object first; another object's definition is not interchangeable.",
    ),
    'knowledge': BuiltinToolLocalization(
        description_en_us='Search, inspect, add, and remove shared knowledge sources. Search before answering from internal documents. Available only to the main Agent.',
    ),
    'scheduler': BuiltinToolLocalization(
        description_en_us="Create and manage scheduled tasks bound to the main Agent's current workspace. Available only to the main Agent.",
    ),
    'skillhub': BuiltinToolLocalization(
        description_en_us='Search, install, or remove Skills through SkillHub and synchronize them into the unified Skill pool. Available only to the main Agent.',
    ),
    'skill_installer': BuiltinToolLocalization(
        description_en_us='Install one complete Skill package after obtaining all of its files. Example: the user asks to install a Skill shown on a web page and you have collected SKILL.md plus references/guide.md; call with both files in package.files. Counterexample: when only a repository URL is known and its files have not been read, do not call yet; retrieve and assemble the complete package first. Never invent missing content. Available only to the main Agent.',
    ),
    'mcp_installer': BuiltinToolLocalization(
        description_en_us='Install one MCP server after obtaining a complete configuration from an authoritative source. server_config accepts a decoded object or JSON/YAML text, with one server per call. Example: official docs provide {"mcpServers":{"amap":{"url":"https://example.com/mcp"}}}; pass the whole document as server_config. Counterexample: when only a service name is known, do not guess command, URL, headers, or environment values; find the official executable configuration first. Available only to the main Agent.',
    ),
    'skill': BuiltinToolLocalization(
        description_en_us=SKILL_TOOL_DESCRIPTION,
    ),
    'browser_open': BuiltinToolLocalization(
        description_en_us='Open an HTTP or HTTPS URL in the isolated browser. Reuse the active page by default; create a new tab only when simultaneous pages are intentional. Returns page state and a page_id for later operations. When page_state is verification_required or authentication_required, immediately stop all browser operations, tell the user in the main conversation to take control and complete the step manually, then end the current response and wait for confirmation. Do not retry or call other browser tools before confirmation. After confirmation, call browser_snapshot once before continuing. Neither state proves that the website is unavailable.',
    ),
    'browser_snapshot': BuiltinToolLocalization(
        description_en_us='Read the current page state, structured text, and optional links. Use this when page state is uncertain and once after the user confirms manual sign-in or human verification is complete. If verification_required or authentication_required remains, stop browser operations, notify the user in the main conversation, end the current response, and wait. Do not repeatedly retry browser tools. A blocked verification flow does not prove that the website is unavailable.',
    ),
    'browser_click': BuiltinToolLocalization(
        description_en_us='Click a target element on the browser page.',
    ),
    'browser_type': BuiltinToolLocalization(
        description_en_us='Enter text into a browser input. Enable submit only when pressing Enter is intentional.',
    ),
    'browser_select': BuiltinToolLocalization(
        description_en_us='Select one or more values in a browser select element.',
    ),
    'browser_press': BuiltinToolLocalization(
        description_en_us='Press a key or keyboard shortcut on a target element or the current page.',
    ),
    'browser_scroll': BuiltinToolLocalization(
        description_en_us='Scroll the current page or a scrollable element by pixel deltas.',
    ),
    'browser_wait': BuiltinToolLocalization(
        description_en_us='Wait for a bounded duration or for a target element to reach a requested state.',
    ),
    'browser_extract': BuiltinToolLocalization(
        description_en_us='Extract text, HTML, or links from the page or all elements matching a CSS selector. Text and HTML from multiple matches are joined with blank lines in document order.',
    ),
    'browser_screenshot': BuiltinToolLocalization(
        description_en_us='Capture the current page as a PNG for a vision-capable model. This tool is hidden from text-only models.',
    ),
    'browser_download': BuiltinToolLocalization(
        description_en_us='Click a download target and save the resulting file in the current workspace.',
    ),
    'browser_upload': BuiltinToolLocalization(
        description_en_us='Upload user-authorized files from the current workspace through a file input. This action requires approval.',
    ),
    'browser_tabs': BuiltinToolLocalization(
        description_en_us='List all pages in the current isolated browser context.',
    ),
    'browser_close': BuiltinToolLocalization(
        description_en_us='Close one browser page or the entire isolated browser context for the current Agent session.',
    ),
    'computer_use': BuiltinToolLocalization(
        description_en_us='Operate the current macOS or Windows desktop through the independent system-level visual Computer Use runtime. Use it for native desktop apps and cross-application interaction. It is completely separate from browser_* built-ins. Provide one concise complete desktop goal; the internal high-speed vision loop handles mouse and keyboard actions.',
    ),
    'generate_image': BuiltinToolLocalization(
        description_en_us='Generate original visual assets with the default image model configured in the model pool and save them in the current conversation workspace.',
    ),
}


def localized_model_copy_for_builtin(
    spec: ToolSpec,
) -> tuple[dict[RuntimeLocale, str], dict[RuntimeLocale, str]]:
    try:
        localization = BUILTIN_TOOL_LOCALIZATIONS[spec.id]
    except KeyError as exc:
        raise ValueError(f"builtin tool has no English localization: {spec.id}") from exc
    descriptions: dict[RuntimeLocale, str] = {"en-US": localization.description_en_us}
    guidance: dict[RuntimeLocale, str] = (
        {"en-US": localization.schema_error_guidance_en_us}
        if localization.schema_error_guidance_en_us
        else {}
    )
    return descriptions, guidance
