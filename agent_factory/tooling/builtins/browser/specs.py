from __future__ import annotations

from copy import deepcopy

from agent_factory.tooling.builtins.browser.runtime import BROWSER_RUNTIME_RESOURCE
from agent_factory.tooling.spec import ToolLoopPolicyConfig, ToolRiskLevel, ToolSpec

_STRING = {"type": "string"}
_ACTIVE_PAGE_ID = {
    "type": "string",
    "description": "Page handle returned by browser_open; omit to use the active page.",
}
_OPEN_PAGE_ID = {
    "type": "string",
    "description": "Existing page handle to navigate. Omit to reuse the active page, or set new_page=true to create another page.",
}
_RUNTIME_RESOURCES = {
    "browser_runtime": BROWSER_RUNTIME_RESOURCE,
    "runtime_identity": "runtime_identity",
    "filesystem": "filesystem",
}
_TARGET = {
    "type": "object",
    "description": "A semantic or CSS locator. Provide exactly one of selector, role, text, label, placeholder, or test_id.",
    "properties": {
        "selector": _STRING,
        "role": _STRING,
        "name": _STRING,
        "text": _STRING,
        "label": _STRING,
        "placeholder": _STRING,
        "test_id": _STRING,
        "exact": {"type": "boolean", "default": False},
        "nth": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}
_PAGE_RESULT_PROPERTIES = {
    "browser_view_id": _STRING,
    "browser_view_action": {"type": "string", "enum": ["open", "update"]},
    "page_id": _STRING,
    "url": _STRING,
    "title": _STRING,
}


def _spec(
    tool_id: str,
    description: str,
    properties: dict,
    *,
    required: list[str] | None = None,
    output_properties: dict | None = None,
    output_required: list[str] | None = None,
    risk_level: ToolRiskLevel = "low",
    concurrent: bool = False,
    passthrough: bool = False,
) -> ToolSpec:
    return ToolSpec(
        id=tool_id,
        description=description,
        entrypoint="agent_factory.tooling.builtins.browser.tools:run",
        input_schema={
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": output_properties or dict(_PAGE_RESULT_PROPERTIES),
            "required": output_required or list(_PAGE_RESULT_PROPERTIES),
            "additionalProperties": False,
        },
        resources=dict(_RUNTIME_RESOURCES),
        risk_level=risk_level,
        concurrent=concurrent,
        output_projection="passthrough" if passthrough else "compress",
        loop_policy=ToolLoopPolicyConfig(max_calls=40, max_identical_calls=4),
    )


def get_browser_tool_specs() -> list[ToolSpec]:
    specs = [
        _spec(
            "browser_open",
            "Navigate an isolated browser page to an HTTP or HTTPS URL. By default this reuses the active page. Pass page_id to navigate a specific existing page, or set new_page=true only when another simultaneous page is intentionally required. Do not open a new page for retries, redirects, or continued work on the same site. Returns a page_id for subsequent browser tools.",
            {
                "url": _STRING,
                "page_id": _OPEN_PAGE_ID,
                "new_page": {
                    "type": "boolean",
                    "default": False,
                    "description": "Create an additional page instead of reusing the active page. Cannot be combined with page_id.",
                },
                "wait_until": {
                    "type": "string",
                    "enum": ["commit", "domcontentloaded", "load", "networkidle"],
                    "default": "domcontentloaded",
                },
            },
            required=["url"],
            output_properties={**_PAGE_RESULT_PROPERTIES, "status_code": {"type": "integer"}},
            output_required=[*list(_PAGE_RESULT_PROPERTIES), "status_code"],
            risk_level="medium",
        ),
        _spec(
            "browser_snapshot",
            "Read the current page as structured text and optionally list its links. Use this before interacting when the page state is uncertain.",
            {
                "page_id": _ACTIVE_PAGE_ID,
                "max_chars": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 200000,
                    "default": 30000,
                },
                "include_links": {"type": "boolean", "default": True},
            },
            output_properties={
                **_PAGE_RESULT_PROPERTIES,
                "text": _STRING,
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"text": _STRING, "href": _STRING},
                        "required": ["text", "href"],
                        "additionalProperties": False,
                    },
                },
                "truncated": {"type": "boolean"},
            },
            output_required=[*list(_PAGE_RESULT_PROPERTIES), "text", "links", "truncated"],
        ),
        _spec(
            "browser_click",
            "Click an element on the active browser page.",
            {"page_id": _ACTIVE_PAGE_ID, "target": deepcopy(_TARGET)},
            required=["target"],
            risk_level="medium",
        ),
        _spec(
            "browser_type",
            "Enter text into an input element. Set submit only when pressing Enter is intended.",
            {
                "page_id": _ACTIVE_PAGE_ID,
                "target": deepcopy(_TARGET),
                "text": _STRING,
                "clear": {"type": "boolean", "default": True},
                "submit": {"type": "boolean", "default": False},
            },
            required=["target", "text"],
            risk_level="medium",
        ),
        _spec(
            "browser_select",
            "Select one or more values from a browser select element.",
            {
                "page_id": _ACTIVE_PAGE_ID,
                "target": deepcopy(_TARGET),
                "values": {"type": "array", "items": _STRING, "minItems": 1},
            },
            required=["target", "values"],
            risk_level="medium",
        ),
        _spec(
            "browser_press",
            "Press a keyboard key or shortcut on an element or the active page.",
            {"page_id": _ACTIVE_PAGE_ID, "target": deepcopy(_TARGET), "key": _STRING},
            required=["key"],
            risk_level="medium",
        ),
        _spec(
            "browser_scroll",
            "Scroll the active page or a scrollable element by pixel deltas.",
            {
                "page_id": _ACTIVE_PAGE_ID,
                "target": deepcopy(_TARGET),
                "delta_x": {"type": "integer", "default": 0},
                "delta_y": {"type": "integer", "default": 600},
            },
        ),
        _spec(
            "browser_wait",
            "Wait for a bounded duration or for an element to reach a requested state.",
            {
                "page_id": _ACTIVE_PAGE_ID,
                "target": deepcopy(_TARGET),
                "milliseconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 60000,
                    "default": 5000,
                },
                "state": {
                    "type": "string",
                    "enum": ["attached", "detached", "visible", "hidden"],
                    "default": "visible",
                },
            },
        ),
        _spec(
            "browser_extract",
            "Extract text, HTML, or links from the page or a CSS selector.",
            {
                "page_id": _ACTIVE_PAGE_ID,
                "selector": _STRING,
                "format": {"type": "string", "enum": ["text", "html", "links"], "default": "text"},
                "max_chars": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 500000,
                    "default": 50000,
                },
            },
            output_properties={
                **_PAGE_RESULT_PROPERTIES,
                "format": _STRING,
                "content": _STRING,
                "truncated": {"type": "boolean"},
            },
            output_required=[*list(_PAGE_RESULT_PROPERTIES), "format", "content", "truncated"],
        ),
        _spec(
            "browser_screenshot",
            "Capture the current page as a PNG and return it to the vision-capable model. This tool is hidden from text-only models.",
            {
                "page_id": _ACTIVE_PAGE_ID,
                "target": deepcopy(_TARGET),
                "full_page": {"type": "boolean", "default": False},
                "path": _STRING,
            },
            output_properties={
                **_PAGE_RESULT_PROPERTIES,
                "path": _STRING,
                "mime_type": _STRING,
                "size_bytes": {"type": "integer"},
                "model_image": {
                    "type": "object",
                    "properties": {
                        "path": _STRING,
                        "mime_type": _STRING,
                    },
                    "required": ["path", "mime_type"],
                    "additionalProperties": False,
                },
            },
            output_required=[
                *list(_PAGE_RESULT_PROPERTIES),
                "path",
                "mime_type",
                "size_bytes",
                "model_image",
            ],
            passthrough=True,
        ),
        _spec(
            "browser_download",
            "Click a download target and save the resulting file inside the current workspace.",
            {"page_id": _ACTIVE_PAGE_ID, "target": deepcopy(_TARGET), "path": _STRING},
            required=["target"],
            output_properties={
                **_PAGE_RESULT_PROPERTIES,
                "path": _STRING,
                "suggested_filename": _STRING,
                "size_bytes": {"type": "integer"},
            },
            output_required=[
                *list(_PAGE_RESULT_PROPERTIES),
                "path",
                "suggested_filename",
                "size_bytes",
            ],
            risk_level="medium",
        ),
        _spec(
            "browser_upload",
            "Upload user-authorized files from the current workspace through a file input. Requires approval.",
            {
                "page_id": _ACTIVE_PAGE_ID,
                "target": deepcopy(_TARGET),
                "paths": {"type": "array", "items": _STRING, "minItems": 1},
            },
            required=["target", "paths"],
            output_properties={
                **_PAGE_RESULT_PROPERTIES,
                "uploaded": {"type": "array", "items": _STRING},
            },
            output_required=[*list(_PAGE_RESULT_PROPERTIES), "uploaded"],
            risk_level="high",
        ),
        _spec(
            "browser_tabs",
            "List pages in the current isolated browser context.",
            {},
            output_properties={
                "browser_view_id": _STRING,
                "browser_view_action": {"type": "string", "enum": ["update"]},
                "tabs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "page_id": _STRING,
                            "url": _STRING,
                            "title": _STRING,
                        },
                        "required": ["page_id", "url", "title"],
                        "additionalProperties": False,
                    },
                },
                "active_page_id": {"type": ["string", "null"]},
            },
            output_required=["browser_view_id", "browser_view_action", "tabs", "active_page_id"],
        ),
        _spec(
            "browser_close",
            "Close one browser page, or close the entire isolated browser context for this Agent session.",
            {"page_id": _ACTIVE_PAGE_ID, "close_context": {"type": "boolean", "default": False}},
            output_properties={
                "browser_view_id": {"type": ["string", "null"]},
                "browser_view_action": {"type": "string", "enum": ["close", "update"]},
                "closed": {"type": "boolean"},
                "remaining_pages": {"type": "integer"},
                "closed_page_id": {"type": ["string", "null"]},
                "page_id": {"type": ["string", "null"]},
                "url": {"type": ["string", "null"]},
                "title": {"type": ["string", "null"]},
            },
            output_required=[
                "browser_view_id",
                "browser_view_action",
                "closed",
                "remaining_pages",
                "closed_page_id",
            ],
        ),
    ]
    return [spec.model_copy(deep=True) for spec in specs]
