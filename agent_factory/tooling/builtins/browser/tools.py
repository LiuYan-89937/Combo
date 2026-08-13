from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.runtime_protocol import RuntimeExecutionIdentity
from uuid import uuid4

from agent_factory.tooling.builtins.browser.runtime import (
    BROWSER_RUNTIME_RESOURCE,
    BrowserRuntime,
    browser_session_key,
)
from agent_factory.tooling.builtins.filesystem.common import (
    filesystem_allowed_roots,
    filesystem_boundary,
    resolve_path,
)
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.execution_context import current_tool_call


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    current = current_tool_call()
    tool_id = current.tool_id if current is not None else ""
    runtime = resources.get(BROWSER_RUNTIME_RESOURCE)
    if not isinstance(runtime, BrowserRuntime):
        raise RuntimeError("browser runtime resource is not configured")
    session_key = _session_key(resources)
    page_id = _optional_text(arguments.get("page_id"))

    if tool_id == "browser_open":
        output = runtime.open(
            session_key=session_key,
            url=_required_text(arguments, "url"),
            page_id=page_id,
            new_page=bool(arguments.get("new_page", False)),
            wait_until=str(arguments.get("wait_until") or "domcontentloaded"),
        )
    elif tool_id == "browser_snapshot":
        output = runtime.snapshot(
            session_key=session_key,
            page_id=page_id,
            max_chars=_bounded_int(arguments.get("max_chars", 30_000), "max_chars", 1_000, 200_000),
            include_links=bool(arguments.get("include_links", True)),
        )
    elif tool_id == "browser_click":
        output = runtime.click(
            session_key=session_key,
            page_id=page_id,
            target=_target(arguments),
        )
    elif tool_id == "browser_type":
        output = runtime.type_text(
            session_key=session_key,
            page_id=page_id,
            target=_target(arguments),
            text=_required_text(arguments, "text"),
            clear=bool(arguments.get("clear", True)),
            submit=bool(arguments.get("submit", False)),
        )
    elif tool_id == "browser_select":
        output = runtime.select(
            session_key=session_key,
            page_id=page_id,
            target=_target(arguments),
            values=_required_strings(arguments.get("values"), "values"),
        )
    elif tool_id == "browser_press":
        output = runtime.press(
            session_key=session_key,
            page_id=page_id,
            key=_required_text(arguments, "key"),
            target=_optional_target(arguments),
        )
    elif tool_id == "browser_scroll":
        output = runtime.scroll(
            session_key=session_key,
            page_id=page_id,
            delta_x=_integer(arguments.get("delta_x", 0), "delta_x"),
            delta_y=_integer(arguments.get("delta_y", 600), "delta_y"),
            target=_optional_target(arguments),
        )
    elif tool_id == "browser_wait":
        output = runtime.wait(
            session_key=session_key,
            page_id=page_id,
            milliseconds=_bounded_int(
                arguments.get("milliseconds", 5_000),
                "milliseconds",
                1,
                60_000,
            ),
            target=_optional_target(arguments),
            state=str(arguments.get("state") or "visible"),
        )
    elif tool_id == "browser_extract":
        output = runtime.extract(
            session_key=session_key,
            page_id=page_id,
            selector=_optional_text(arguments.get("selector")),
            format_name=str(arguments.get("format") or "text"),
            max_chars=_bounded_int(arguments.get("max_chars", 50_000), "max_chars", 1_000, 500_000),
        )
    elif tool_id == "browser_screenshot":
        output = runtime.screenshot(
            session_key=session_key,
            page_id=page_id,
            full_page=bool(arguments.get("full_page", False)),
            target=_optional_target(arguments),
            output_path=_output_path(
                arguments,
                resources,
                default_name=f"browser-screenshot-{uuid4().hex[:8]}.png",
            ),
        )
    elif tool_id == "browser_download":
        output = runtime.download(
            session_key=session_key,
            page_id=page_id,
            target=_target(arguments),
            output_path=_output_path(arguments, resources, default_name="downloads"),
        )
    elif tool_id == "browser_upload":
        output = runtime.upload(
            session_key=session_key,
            page_id=page_id,
            target=_target(arguments),
            paths=_input_paths(arguments, resources),
        )
    elif tool_id == "browser_tabs":
        output = runtime.tabs(session_key=session_key)
    elif tool_id == "browser_close":
        output = runtime.close(
            session_key=session_key,
            page_id=page_id,
            close_context=bool(arguments.get("close_context", False)),
        )
    else:
        raise RuntimeError(f"unsupported browser tool: {tool_id or '<unknown>'}")
    if tool_id == "browser_close":
        has_active_page = bool(output.get("page_id")) and int(output.get("remaining_pages") or 0) > 0
        output["browser_view_action"] = "update" if has_active_page else "close"
        output.setdefault("closed_page_id", page_id)
    elif "page_id" in output or output.get("tabs") is not None:
        page_created = bool(output.pop("_page_created", False))
        output["browser_view_id"] = runtime.view_id(session_key=session_key)
        output["browser_view_action"] = "open" if page_created else "update"
    return tool_envelope(output, summary=f"{tool_id} completed")


def _session_key(resources: dict[str, Any]) -> str:
    identity = resources.get("runtime_identity")
    if not isinstance(identity, RuntimeExecutionIdentity):
        raise RuntimeError("browser tools require an owned runtime attempt identity")
    return browser_session_key(
        generation=identity.generation,
        principal_id=identity.principal_id,
        session_id=identity.session_id,
        runtime_role=identity.runtime_role,
        task_id=identity.task_id,
    )


def _target(arguments: dict[str, Any]) -> dict[str, Any]:
    target = arguments.get("target")
    if not isinstance(target, dict):
        raise ValueError("target must be an object")
    return dict(target)


def _optional_target(arguments: dict[str, Any]) -> dict[str, Any] | None:
    target = arguments.get("target")
    return dict(target) if isinstance(target, dict) and target else None


def _output_path(
    arguments: dict[str, Any],
    resources: dict[str, Any],
    *,
    default_name: str,
) -> Path:
    root, allow_external = filesystem_boundary(resources)
    value = _optional_text(arguments.get("path")) or default_name
    return resolve_path(
        path=value,
        root=root,
        allow_external=allow_external,
        allowed_roots=filesystem_allowed_roots(resources),
    )


def _input_paths(arguments: dict[str, Any], resources: dict[str, Any]) -> list[Path]:
    root, allow_external = filesystem_boundary(resources)
    paths = []
    for value in _required_strings(arguments.get("paths"), "paths"):
        path = resolve_path(
            path=value,
            root=root,
            allow_external=allow_external,
            allowed_roots=filesystem_allowed_roots(resources),
        )
        if not path.is_file():
            raise FileNotFoundError(str(path))
        paths.append(path)
    return paths


def _required_text(arguments: dict[str, Any], key: str) -> str:
    value = _optional_text(arguments.get(key))
    if not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_strings(value: Any, key: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    values = [text for item in value if (text := _optional_text(item))]
    if not values:
        raise ValueError(f"{key} must contain at least one value")
    return values


def _integer(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _bounded_int(value: Any, key: str, minimum: int, maximum: int) -> int:
    parsed = _integer(value, key)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return parsed
