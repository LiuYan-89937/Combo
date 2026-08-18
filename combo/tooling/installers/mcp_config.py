from __future__ import annotations

from io import StringIO
import json
import re
from typing import Any

from ruamel.yaml import YAML


DEFAULT_CONNECT_TIMEOUT_SECONDS = 30.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_PARALLEL_REQUESTS = 1
_IDENTIFIER_SEPARATOR = re.compile(r"[^a-z0-9_]+")


def normalize_mcp_server_config(config: object) -> dict[str, Any]:
    """Normalize one common MCP client entry into a Gateway registry document."""
    decoded = _decode_document(config)
    entries = _server_entries(decoded)
    if not entries:
        raise ValueError("MCP config does not contain a recognizable server")
    if len(entries) != 1:
        raise ValueError("mcp_installer accepts exactly one MCP server per call")
    name, raw = entries[0]
    return _normalize_server(name, raw, 0)


def _decode_document(config: object) -> object:
    if isinstance(config, str):
        source = config.strip()
        if not source:
            raise ValueError("MCP config must not be empty")
        try:
            return json.loads(source)
        except json.JSONDecodeError:
            yaml = YAML(typ="safe")
            decoded = yaml.load(StringIO(source))
            if decoded is None:
                raise ValueError("MCP config must not be empty")
            return decoded
    return config


def _server_entries(value: object) -> tuple[tuple[str, dict[str, Any]], ...]:
    if isinstance(value, list):
        return tuple(
            (str(item.get("name") or item.get("server_id") or ""), item)
            for item in value
            if isinstance(item, dict)
        )
    if not isinstance(value, dict):
        return ()
    for key in ("mcpServers", "servers"):
        collection = value.get(key)
        if isinstance(collection, dict):
            return tuple(
                (str(name), item)
                for name, item in collection.items()
                if isinstance(item, dict)
            )
        if isinstance(collection, list):
            return tuple(
                (str(item.get("name") or item.get("server_id") or ""), item)
                for item in collection
                if isinstance(item, dict)
            )
    if _has_server_shape(value):
        return ((str(value.get("name") or value.get("server_id") or ""), value),)
    return tuple(
        (str(name), item)
        for name, item in value.items()
        if isinstance(item, dict) and _has_server_shape(item)
    )


def _normalize_server(name: str, raw: dict[str, Any], index: int) -> dict[str, Any]:
    fallback_name = name.strip() or f"mcp_server_{index + 1}"
    display_name = str(raw.get("display_name") or raw.get("name") or fallback_name).strip()
    server_id = _normalize_identifier(str(raw.get("server_id") or fallback_name))
    endpoint = _optional_text(raw.get("url") or raw.get("endpoint"))
    transport = _normalize_transport(raw.get("transport") or raw.get("type"), has_endpoint=endpoint is not None)
    command, arguments = _command_and_arguments(raw.get("command"), raw.get("args"))
    if transport == "stdio":
        if command is None:
            raise ValueError(f"stdio MCP server requires command: {display_name}")
        if endpoint is not None:
            raise ValueError(f"stdio MCP server forbids URL: {display_name}")
    elif endpoint is None:
        raise ValueError(f"HTTP MCP server requires URL: {display_name}")
    elif command is not None or arguments:
        raise ValueError(f"HTTP MCP server forbids command and args: {display_name}")
    return {
        "server_id": server_id,
        "display_name": display_name,
        "description": str(raw.get("description") or raw.get("summary") or "").strip(),
        "enabled": True,
        "connection": {
            "transport": transport,
            "command": command,
            "args": list(arguments),
            "cwd": _optional_text(raw.get("cwd") or raw.get("working_directory")),
            "url": endpoint,
            "env": _mapping(raw.get("env") or raw.get("environment"), field="environment"),
            "headers": _mapping(raw.get("headers"), field="headers"),
            "connect_timeout_seconds": _positive_number(
                raw.get("connect_timeout_seconds"), DEFAULT_CONNECT_TIMEOUT_SECONDS
            ),
            "request_timeout_seconds": _positive_number(
                raw.get("request_timeout_seconds") or raw.get("timeout_seconds") or raw.get("timeout"),
                DEFAULT_REQUEST_TIMEOUT_SECONDS,
            ),
            "max_parallel_requests": _positive_integer(
                raw.get("max_parallel_requests"), DEFAULT_MAX_PARALLEL_REQUESTS
            ),
        },
        "defaults": {
            "risk_level": _risk_level(raw.get("risk_level_default")),
            "allow_parallel_calls": raw.get("concurrent_default") is not False,
            "tool_id_prefix": None,
        },
        "tools": {},
    }


def _normalize_transport(value: object, *, has_endpoint: bool) -> str:
    transport = str(value or "").strip().lower().replace("-", "_")
    if not transport:
        return "streamable_http" if has_endpoint else "stdio"
    aliases = {"http": "streamable_http", "streamablehttp": "streamable_http"}
    normalized = aliases.get(transport, transport)
    if normalized not in {"stdio", "streamable_http", "sse"}:
        raise ValueError(f"unsupported MCP transport: {transport}")
    return normalized


def _command_and_arguments(command_value: object, arguments_value: object) -> tuple[str | None, tuple[str, ...]]:
    if isinstance(command_value, list):
        command_items = tuple(str(item) for item in command_value if str(item))
        command = _optional_text(command_items[0] if command_items else None)
        command_arguments = command_items[1:]
    else:
        command = _optional_text(command_value)
        command_arguments = ()
    if arguments_value is None:
        arguments = command_arguments
    elif isinstance(arguments_value, list):
        arguments = tuple(str(item) for item in arguments_value)
    else:
        raise ValueError("MCP args must be an array of strings")
    return command, arguments


def _mapping(value: object, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"MCP {field} must be an object")
    return {str(key): item for key, item in value.items()}


def _normalize_identifier(value: str) -> str:
    normalized = _IDENTIFIER_SEPARATOR.sub("_", value.strip().lower()).strip("_")
    if not normalized:
        raise ValueError("MCP server name cannot produce a stable identifier")
    if normalized[0].isdigit():
        normalized = f"mcp_{normalized}"
    return normalized[:64].rstrip("_")


def _positive_number(value: object, fallback: float) -> float:
    if value is None:
        return fallback
    number = float(value)
    if number <= 0:
        raise ValueError("MCP timeout must be positive")
    return number


def _positive_integer(value: object, fallback: int) -> int:
    if value is None:
        return fallback
    number = int(value)
    if number < 1:
        raise ValueError("MCP max_parallel_requests must be positive")
    return number


def _risk_level(value: object) -> str:
    risk = str(value or "medium").strip().lower()
    if risk not in {"low", "medium", "high"}:
        raise ValueError(f"unsupported MCP risk level: {risk}")
    return risk


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _has_server_shape(value: dict[str, Any]) -> bool:
    return any(key in value for key in ("command", "url", "endpoint", "transport", "args"))
