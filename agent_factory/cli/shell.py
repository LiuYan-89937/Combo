from __future__ import annotations

from pathlib import Path
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agent_factory.cli.rendering import (
    FactoryStreamRenderer,
    render_banner,
    render_create_result,
    render_draft_detail,
    render_drafts_list,
    render_factory_stream_result,
    render_help,
    render_not_implemented,
    render_requirement_captured,
    render_run_agent_result,
    render_test_agent_result,
    render_validation_report,
)
from agent_factory.cli.completion import ContextualSlashCompleter
from agent_factory.cli.slash import SLASH_COMMANDS, SlashCommandDispatcher, SlashCommandResult
from agent_factory.cli.theme import PROMPT, STYLE_ACCENT, STYLE_MUTED, STYLE_SUCCESS, STYLE_WARNING
from agent_factory.application import RunAgentServiceRequest
from agent_factory.memory import AgentMemoryStore
from agent_factory.registry import FilesystemRegistry


def run_shell() -> None:
    console = Console()
    dispatcher = SlashCommandDispatcher()
    render_banner(console, workspace=Path.cwd(), state="shell")

    prompt_session = _prompt_session(dispatcher)
    while True:
        try:
            prompt = _shell_prompt(dispatcher)
            line = prompt_session.prompt(prompt) if prompt_session else input(prompt)
        except (EOFError, KeyboardInterrupt):
            console.print("")
            break

        if dispatcher.session.in_agent_chat:
            if _handle_agent_chat_line(line, console, dispatcher):
                continue

        if _should_open_requirement_box(line, dispatcher, interactive=prompt_session is not None):
            requirement = _read_requirement_box(console, prompt_session)
            if requirement is None:
                console.print("  Requirement input canceled.", style=STYLE_MUTED)
                continue
            dispatcher.session.capture_requirement(requirement)
            render_requirement_captured(requirement, console)

        if _should_auto_create_from_text(line):
            error, events = dispatcher.stream_natural_language_create_events(line)
            if error:
                render_slash_result(error, console)
                continue
            assert events is not None
            _render_factory_event_stream(console, dispatcher, events)
            _prompt_and_continue_clarification(console, prompt_session, dispatcher)
            continue

        if _should_stream_create_agent(line):
            error, events = dispatcher.stream_create_agent_events(line)
            if error:
                render_slash_result(error, console)
                continue
            assert events is not None
            _render_factory_event_stream(
                console,
                dispatcher,
                events,
                show_thinking=_should_show_thinking(line),
            )
            _prompt_and_continue_clarification(console, prompt_session, dispatcher)
            continue

        result = dispatcher.dispatch(line)
        render_slash_result(result, console)
        if result.exit_requested:
            break


def render_slash_result(result: SlashCommandResult, console: Console | None = None) -> None:
    console = console or Console()
    if result.kind == "empty":
        return
    if result.kind == "requirement":
        if result.pending_requirement:
            render_requirement_captured(result.pending_requirement, console)
        return
    if result.kind == "help":
        render_help(SLASH_COMMANDS, console, pending_requirement=result.pending_requirement)
        return
    if result.kind == "exit":
        console.print(result.message or "Exiting.")
        return
    if result.kind == "create_agent" and result.create_result:
        render_create_result(result.create_result, console)
        return
    if result.kind == "validate_agent" and result.validation_report:
        render_validation_report(result.validation_report, console)
        return
    if result.kind == "test_agent" and result.test_result:
        render_test_agent_result(result.test_result, console)
        return
    if result.kind == "drafts":
        if result.message:
            console.print("")
            console.print(f"  {result.message}")
        if result.drafts_result:
            render_drafts_list(result.drafts_result, console)
        if result.draft_detail:
            render_draft_detail(result.draft_detail, console)
        return
    if result.kind == "run_agent" and result.run_result:
        render_run_agent_result(result.run_result, console, message=result.message)
        return
    if result.kind == "agent_chat":
        console.print("")
        console.print(Text(f"  {result.message or 'Agent chat started.'}", style=STYLE_SUCCESS))
        return
    if result.kind == "repair_agent" and result.repair_result:
        console.print("")
        console.print(f"  Repair status: {result.repair_result.status}")
        if result.repair_result.reason:
            console.print(f"  Reason: {result.repair_result.reason}")
        if result.repair_result.candidate_path:
            console.print(f"  Candidate: {result.repair_result.candidate_path}")
        for patch in result.repair_result.patches:
            console.print(f"  - {patch.action}: {patch.path}")
        if result.repair_result.rerun_result:
            console.print(f"  Self-test: {result.repair_result.rerun_result.status}")
            console.print(f"  Answer: {result.repair_result.rerun_result.answer}")
        return
    if result.kind == "registry":
        console.print("")
        console.print(f"  {result.message or ''}")
        return
    if result.kind == "not_implemented":
        render_not_implemented(result.command or "command", console)
        return
    if result.message:
        console.print("")
        console.print(f"  ! {result.message}")


def _record_streamed_create_event(dispatcher: SlashCommandDispatcher, event) -> None:
    if event.stage == "needs_clarification":
        raw_questions = event.payload.get("questions") or event.payload.get("clarification_questions") or []
        questions = [str(question) for question in raw_questions if str(question).strip()] if isinstance(raw_questions, list) else []
        options = event.payload.get("clarification_options")
        dispatcher.session.capture_clarification(
            questions=questions,
            options=options if isinstance(options, list) else [],
        )
        return
    if event.stage == "complete":
        dispatcher.session.clear_pending_clarification()
        if event.artifact_path:
            dispatcher.session.selected_agent_path = Path(event.artifact_path)
        return
    if event.stage == "not_agent_request":
        dispatcher.session.clear_pending_requirement()


def _render_factory_event_stream(
    console: Console,
    dispatcher: SlashCommandDispatcher,
    events,
    *,
    show_thinking: bool = False,
) -> list:
    stream_renderer = FactoryStreamRenderer(console, show_thinking=show_thinking)
    captured = []
    for event in events:
        captured.append(event)
        stream_renderer.render(event)
        _record_streamed_create_event(dispatcher, event)
    stream_renderer.close()
    render_factory_stream_result(captured, console)
    return captured


def _prompt_and_continue_clarification(
    console: Console,
    prompt_session,
    dispatcher: SlashCommandDispatcher,
) -> None:
    if prompt_session is None:
        return
    if not dispatcher.session.pending_clarification_options:
        return
    answers = _prompt_for_clarification(console, prompt_session, dispatcher.session.pending_clarification_options)
    if not answers:
        return
    dispatcher.session.capture_requirement("\n".join(answers))
    console.print("")
    console.print(Text("  Clarification captured. Continuing Factory production...", style=STYLE_ACCENT))
    error, events = dispatcher.stream_pending_create_events()
    if error:
        render_slash_result(error, console)
        return
    assert events is not None
    _render_factory_event_stream(console, dispatcher, events)


def _prompt_for_clarification(
    console: Console,
    prompt_session,
    questions: list[dict],
) -> list[str]:
    answers: list[str] = []
    for index, question in enumerate(questions, start=1):
        prompt_text = str(question.get("question") or "").strip()
        if not prompt_text:
            continue
        options = _normalized_question_options(question)
        _render_interactive_question(console, index, len(questions), prompt_text, options)
        completions = [
            *[str(option_index) for option_index in range(1, len(options) + 1)],
            *[option["id"] for option in options],
            *[option["label"] for option in options],
        ]
        try:
            from prompt_toolkit.completion import WordCompleter

            completer = WordCompleter(completions, ignore_case=True)
            raw_answer = prompt_session.prompt("选择 › ", completer=completer)
        except Exception:
            raw_answer = prompt_session.prompt("选择 › ")
        answer = _resolve_clarification_answer(raw_answer, options, console, prompt_session)
        if answer is None:
            return []
        answers.append(f"{prompt_text}\n回答：{answer}")
    return answers


def _inline_option_label(option: dict[str, str], index: int) -> str:
    label = option["label"]
    description = option["description"]
    if description:
        return f"{index}. {label} - {description}"
    return f"{index}. {label}"


def _render_interactive_question(
    console: Console,
    index: int,
    total: int,
    question: str,
    options: list[dict[str, str]],
) -> None:
    console.print("")
    console.print(Text(f"  Clarification {index}/{total}", style=STYLE_ACCENT))
    console.print(Text(f"  {question}", style=STYLE_WARNING))
    for option_index, option in enumerate(options, start=1):
        console.print(Text(f"    {_inline_option_label(option, option_index)}", style=STYLE_MUTED))
    console.print(Text("  输入数字、选项 id/名称，或直接输入自定义答案。", style=STYLE_MUTED))


def _resolve_clarification_answer(
    raw_answer: str,
    options: list[dict[str, str]],
    console: Console,
    prompt_session,
) -> str | None:
    answer = raw_answer.strip()
    if not answer:
        return None
    if answer.isdigit():
        index = int(answer)
        if 1 <= index <= len(options):
            chosen_by_number = options[index - 1]
            if chosen_by_number["id"].lower() == "other":
                custom = prompt_session.prompt("自定义 › ").strip()
                return custom or None
            return f"{chosen_by_number['label']} ({chosen_by_number['id']})"
    by_id = {option["id"].lower(): option for option in options}
    by_label = {option["label"].lower(): option for option in options}
    chosen = by_id.get(answer.lower()) or by_label.get(answer.lower())
    if chosen and chosen["id"].lower() == "other":
        custom = prompt_session.prompt("自定义 › ").strip()
        return custom or None
    if chosen:
        return f"{chosen['label']} ({chosen['id']})"
    console.print(Text("  Custom answer accepted.", style=STYLE_MUTED))
    return answer


def _normalized_question_options(question: dict) -> list[dict[str, str]]:
    raw_options = question.get("options")
    options: list[dict[str, str]] = []
    if isinstance(raw_options, list):
        for raw_option in raw_options:
            if not isinstance(raw_option, dict):
                continue
            option_id = str(raw_option.get("id") or "").strip()
            label = str(raw_option.get("label") or "").strip()
            if not option_id and not label:
                continue
            options.append(
                {
                    "id": option_id or label,
                    "label": label or option_id,
                    "description": str(raw_option.get("description") or "").strip(),
                }
            )
    has_other = any(
        option["id"].lower() == "other" or option["label"] == "其他"
        for option in options
    )
    if not has_other:
        options.append(
            {
                "id": "other",
                "label": "其他",
                "description": "自己输入更具体的答案。",
            }
        )
    return options


def _shell_prompt(dispatcher: SlashCommandDispatcher) -> str:
    if not dispatcher.session.in_agent_chat:
        return PROMPT
    label = "agent"
    if dispatcher.session.active_agent_path:
        label = dispatcher.session.active_agent_path.name
    elif dispatcher.session.active_agent_target:
        label = Path(dispatcher.session.active_agent_target).name
    return f"{label} › "


def _handle_agent_chat_line(
    line: str,
    console: Console,
    dispatcher: SlashCommandDispatcher,
) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped in {"/exit", "/quit"}:
        dispatcher.session.exit_agent_chat()
        console.print(Text("  Left Agent chat. Factory commands are available again.", style=STYLE_MUTED))
        return True
    if stripped == "/clear":
        _clear_active_agent_session(console, dispatcher)
        return True
    if stripped.startswith("/run") and {"--yes", "-yes", "-y"}.intersection(stripped.split()):
        render_slash_result(dispatcher.dispatch(stripped), console)
        return True
    if _looks_like_tool_confirmation(stripped):
        return _confirm_pending_tool(console, dispatcher)
    if stripped == "/help":
        console.print("")
        console.print(Text("  Agent chat commands", style=STYLE_ACCENT))
        console.print(Text("  /run --yes  Approve the pending interrupted tool call", style=STYLE_MUTED))
        console.print(Text("  /exit       Leave this Agent chat", style=STYLE_MUTED))
        console.print(Text("  /clear      Clear this Agent session memory", style=STYLE_MUTED))
        return True
    if stripped.startswith("/"):
        console.print(
            Text(
                "  You are in Agent chat. Use /exit first, then run Factory commands.",
                style=STYLE_WARNING,
            )
        )
        return True
    target = dispatcher.session.active_agent_target
    if not target:
        dispatcher.session.exit_agent_chat()
        return False
    result = dispatcher.run_service.run_agent(
        RunAgentServiceRequest(
            target=target,
            user_input=stripped,
            session_id=dispatcher.session.active_session_id,
        )
    )
    _record_chat_tool_approval(dispatcher, result, stripped)
    render_run_agent_result(result, console, compact=True)
    return True


def _looks_like_tool_confirmation(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {
        "确认",
        "确认执行",
        "同意",
        "批准",
        "继续",
        "执行",
        "yes",
        "y",
        "-yes",
        "approve",
        "approved",
        "confirm",
        "--yes",
        "-y",
    }


def _confirm_pending_tool(console: Console, dispatcher: SlashCommandDispatcher) -> bool:
    pending = dispatcher.session.pending_tool_approval
    target = dispatcher.session.active_agent_target
    if not pending or not target:
        console.print(Text("  No pending tool call to approve.", style=STYLE_WARNING))
        return True
    tool_id = str(pending.get("tool_id") or "tool")
    user_input = str(pending.get("user_input") or "")
    console.print(Text(f"  Approving pending tool call: {tool_id}", style=STYLE_ACCENT))
    result = dispatcher.run_service.run_agent(
        RunAgentServiceRequest(
            target=target,
            user_input=user_input,
            session_id=dispatcher.session.active_session_id,
            approved_tool_call_id=tool_id,
        )
    )
    _record_chat_tool_approval(dispatcher, result, user_input)
    render_run_agent_result(result, console, compact=True)
    return True


def _record_chat_tool_approval(
    dispatcher: SlashCommandDispatcher,
    result,
    user_input: str,
) -> None:
    if not result.result or result.result.status != "interrupted":
        dispatcher.session.clear_tool_approval()
        return
    interrupted = [item for item in result.result.tool_results if item.status == "interrupted"]
    if not interrupted:
        dispatcher.session.clear_tool_approval()
        return
    item = interrupted[0]
    dispatcher.session.capture_tool_approval(
        user_input=user_input,
        tool_call_id=item.invocation_id,
        tool_id=item.tool_id,
    )


def _clear_active_agent_session(console: Console, dispatcher: SlashCommandDispatcher) -> None:
    package_path = dispatcher.session.active_agent_path
    if package_path is None and dispatcher.session.active_agent_target:
        target_path = Path(dispatcher.session.active_agent_target)
        if target_path.exists():
            package_path = target_path
        else:
            draft_path = dispatcher.drafts_service.resolve_draft(dispatcher.session.active_agent_target)
            if draft_path is not None:
                package_path = draft_path
            else:
                record = FilesystemRegistry().get(dispatcher.session.active_agent_target)
                if record is not None:
                    package_path = record.package_path
    if package_path is None:
        console.print(Text("  Cannot resolve active Agent package for memory clearing.", style=STYLE_WARNING))
        return
    removed = AgentMemoryStore(package_path).clear_session(
        session_id=dispatcher.session.active_session_id
    )
    console.print(
        Text(
            f"  Cleared session '{dispatcher.session.active_session_id}' ({removed} record(s)).",
            style=STYLE_MUTED,
        )
    )


def _prompt_session(dispatcher: SlashCommandDispatcher):
    if not sys.stdin.isatty():
        return None
    try:
        from prompt_toolkit import PromptSession
    except ImportError:
        return None

    return PromptSession(
        completer=ContextualSlashCompleter(
            session=dispatcher.session,
            drafts_service=dispatcher.drafts_service,
        )
    )


def _should_stream_create_agent(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("/create-agent"):
        return False
    return "--no-stream" not in stripped.split()


def _should_auto_create_from_text(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("/")


def _should_show_thinking(line: str) -> bool:
    parts = line.strip().split()
    return "--show-thinking" in parts and "--hide-thinking" not in parts


def _should_open_requirement_box(
    line: str,
    dispatcher: SlashCommandDispatcher,
    *,
    interactive: bool,
) -> bool:
    if not interactive:
        return False
    stripped = line.strip()
    if not (stripped == "/create-agent" or stripped.startswith("/create-agent ")):
        return False
    if "--prompt" in stripped or " -p" in f" {stripped}":
        return False
    return not bool(dispatcher.session.pending_requirement)


def _read_requirement_box(console: Console, prompt_session) -> str | None:
    body = Text()
    body.append("Type the Agent requirement below, then press Enter to send.\n", style=STYLE_MUTED)
    body.append("Cancel with ", style=STYLE_MUTED)
    body.append("/cancel", style=STYLE_ACCENT)
    body.append(".", style=STYLE_MUTED)
    console.print("")
    console.print(Panel(body, title="Agent Requirement", border_style=STYLE_ACCENT))

    try:
        line = prompt_session.prompt("│ ") if prompt_session is not None else input("│ ")
    except (EOFError, KeyboardInterrupt):
        return None
    return _collect_requirement_lines(lambda: line)


def _collect_requirement_lines(read_line) -> str | None:
    try:
        line = read_line()
    except (EOFError, KeyboardInterrupt):
        return None
    marker = line.strip()
    if marker in {"/cancel", "/abort"}:
        return None
    if marker in {"/done", "/end"}:
        return None
    requirement = line.strip()
    return requirement or None
