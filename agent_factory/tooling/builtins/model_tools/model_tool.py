from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from agent_factory.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime_tool = resources.get("model_tool")
    if not isinstance(runtime_tool, dict):
        raise ValueError("model_tool runtime resource is missing")
    capability = str(runtime_tool.get("capability") or "")
    if capability not in {"image_input", "audio_input"}:
        raise ValueError(f"unsupported local model tool capability: {capability}")
    model = runtime_tool.get("model")
    if model is None or not hasattr(model, "invoke"):
        raise ValueError("model_tool runtime resource has no runnable local model")
    content = _message_content(capability=capability, arguments=arguments, runtime_tool=runtime_tool)
    response = model.invoke([HumanMessage(content=content)])
    text, artifacts, raw_content = _project_response_content(getattr(response, "content", response))
    profile_id = str(runtime_tool.get("profile_id") or "")
    output = {
        "capability": capability,
        "profile_id": profile_id,
        "content": text,
        "artifacts": artifacts,
        "raw_content": raw_content,
        "metadata": {
            "tool_id": str(runtime_tool.get("tool_id") or ""),
            "model": str(runtime_tool.get("model_name") or ""),
            "engine": str(runtime_tool.get("engine") or ""),
            "model_source": str(runtime_tool.get("model_source") or ""),
        },
    }
    summary = text[:240] if text else f"{capability} local model tool completed."
    return tool_envelope(
        output,
        evidence={"model_tool": {"tool_id": output["metadata"]["tool_id"], "profile_id": profile_id, "capability": capability}},
        summary=summary,
    )


def _message_content(*, capability: str, arguments: dict[str, Any], runtime_tool: dict[str, Any]) -> Any:
    if capability == "image_input":
        return _image_input_content(arguments, runtime_tool)
    if capability == "audio_input":
        return _audio_input_content(arguments)
    raise ValueError(f"unsupported local model tool capability: {capability}")


def _image_input_content(arguments: dict[str, Any], runtime_tool: dict[str, Any]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": str(arguments.get("prompt") or "")}]
    for path in _input_paths(arguments, runtime_tool):
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        content.append(_image_input_part(mime_type=mime_type, data=path.read_bytes()))
    image_base64 = str(arguments.get("image_base64") or "").strip()
    if image_base64:
        mime_type = str(arguments.get("mime_type") or "image/png").strip() or "image/png"
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}})
    if len(content) == 1:
        raise ValueError("image_input requires local input paths, attachment ids, or image_base64")
    return content


def _image_input_part(*, mime_type: str, data: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}}


def _input_paths(arguments: dict[str, Any], runtime_tool: dict[str, Any]) -> list[Path]:
    paths = [_resolve_runtime_path(value, runtime_tool) for value in _string_list(arguments.get("input_paths"))]
    attachment_ids = set(_string_list(arguments.get("input_attachment_ids")))
    if attachment_ids:
        for candidate in _discover_runtime_attachment_paths(runtime_tool):
            if candidate.stem in attachment_ids or any(part in attachment_ids for part in candidate.parts):
                paths.append(candidate)
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            raise ValueError(f"local model input file does not exist: {path}")
        key = str(path)
        if key not in seen:
            result.append(path)
            seen.add(key)
    return result


def _discover_runtime_attachment_paths(runtime_tool: dict[str, Any]) -> list[Path]:
    roots = [
        Path(str(runtime_tool.get("runtime_root") or "")) / "input_files",
        Path(str(runtime_tool.get("package_root") or "")) / ".agent_runtime" / "input_files",
    ]
    return [path for root in roots if root.is_dir() for path in root.rglob("*") if path.is_file()]


def _resolve_runtime_path(value: str, runtime_tool: dict[str, Any]) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    package_root = Path(str(runtime_tool.get("package_root") or ".")).resolve()
    runtime_root = Path(str(runtime_tool.get("runtime_root") or package_root / ".agent_runtime")).resolve()
    for base in (runtime_root, package_root):
        candidate = (base / raw).resolve()
        if candidate.exists():
            return candidate
    return (runtime_root / raw).resolve()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _audio_input_content(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    prompt = str(arguments.get("prompt") or "")
    language = str(arguments.get("language") or "").strip()
    if language:
        prompt = f"{prompt}\n\nLanguage hint: {language}"
    audio_base64 = str(arguments.get("audio_base64") or "").strip()
    if not audio_base64:
        raise ValueError("audio_input requires audio_base64")
    mime_type = str(arguments.get("mime_type") or "audio/mpeg").strip() or "audio/mpeg"
    audio_format = mime_type.rsplit("/", 1)[-1] if "/" in mime_type else mime_type
    return [
        {"type": "text", "text": prompt},
        {"type": "input_audio", "input_audio": {"data": audio_base64, "format": audio_format}},
    ]


def _project_response_content(value: Any) -> tuple[str, list[dict[str, Any]], Any]:
    if isinstance(value, str):
        return value, [], value
    if isinstance(value, list):
        text_parts: list[str] = []
        artifacts: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and str(item.get("type") or "") in {"text", "output_text"}:
                text_parts.append(str(item.get("text") or ""))
            elif isinstance(item, dict):
                artifacts.append(dict(item))
            else:
                artifacts.append({"type": "unknown", "value": item})
        return "\n".join(part for part in text_parts if part), artifacts, value
    if isinstance(value, dict):
        text = value.get("text") or value.get("content") or value.get("output_text")
        artifacts = value.get("artifacts") if isinstance(value.get("artifacts"), list) else []
        return str(text or ""), [dict(item) for item in artifacts if isinstance(item, dict)], value
    return str(value or ""), [], value
