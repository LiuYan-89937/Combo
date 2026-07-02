from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage

from agent_factory.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime_tool = resources.get("model_tool")
    if not isinstance(runtime_tool, dict):
        raise ValueError("model_tool runtime resource is missing")
    model = runtime_tool.get("model")
    if model is None or not hasattr(model, "invoke"):
        raise ValueError("model_tool runtime resource has no runnable model")
    capability = str(runtime_tool.get("capability") or "")
    message = HumanMessage(content=_message_content(capability=capability, arguments=arguments))
    response = model.invoke([message])
    content, artifacts, raw_content = _project_response_content(getattr(response, "content", response))
    profile_id = str(runtime_tool.get("profile_id") or "")
    output = {
        "capability": capability,
        "profile_id": profile_id,
        "content": content,
        "artifacts": artifacts,
        "raw_content": raw_content,
        "metadata": {
            "tool_id": str(runtime_tool.get("tool_id") or ""),
            "model": str(runtime_tool.get("model_name") or ""),
            "provider": str(runtime_tool.get("provider") or ""),
        },
    }
    summary = content[:240] if content else f"{capability} model tool completed."
    return tool_envelope(
        output,
        evidence={"model_tool": {"tool_id": output["metadata"]["tool_id"], "profile_id": profile_id, "capability": capability}},
        summary=summary,
    )


def _message_content(*, capability: str, arguments: dict[str, Any]) -> Any:
    if capability == "image_input":
        return _image_input_content(arguments)
    if capability == "audio_input":
        return _audio_input_content(arguments)
    if capability == "image_output":
        prompt = str(arguments.get("prompt") or "")
        details = _compact_json({key: arguments.get(key) for key in ("size", "style", "count") if arguments.get(key)})
        return prompt if not details else f"{prompt}\n\nGeneration constraints: {details}"
    if capability == "audio_output":
        text = str(arguments.get("text") or "")
        details = _compact_json({key: arguments.get(key) for key in ("voice", "format") if arguments.get(key)})
        return text if not details else f"{text}\n\nAudio constraints: {details}"
    return json.dumps(arguments, ensure_ascii=False)


def _image_input_content(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": str(arguments.get("prompt") or "")}]
    image_url = str(arguments.get("image_url") or "").strip()
    image_base64 = str(arguments.get("image_base64") or "").strip()
    mime_type = str(arguments.get("mime_type") or "image/png").strip() or "image/png"
    if image_url:
        content.append({"type": "image_url", "image_url": {"url": image_url}})
    elif image_base64:
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}})
    return content


def _audio_input_content(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    prompt = str(arguments.get("prompt") or "")
    language = str(arguments.get("language") or "").strip()
    if language:
        prompt = f"{prompt}\n\nLanguage hint: {language}"
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    audio_url = str(arguments.get("audio_url") or "").strip()
    audio_base64 = str(arguments.get("audio_base64") or "").strip()
    mime_type = str(arguments.get("mime_type") or "audio/mpeg").strip() or "audio/mpeg"
    if audio_url:
        content.append({"type": "input_audio", "input_audio": {"url": audio_url}})
    elif audio_base64:
        audio_format = mime_type.rsplit("/", 1)[-1] if "/" in mime_type else mime_type
        content.append({"type": "input_audio", "input_audio": {"data": audio_base64, "format": audio_format}})
    return content


def _project_response_content(value: Any) -> tuple[str, list[dict[str, Any]], Any]:
    if isinstance(value, str):
        return value, [], value
    if isinstance(value, list):
        text_parts: list[str] = []
        artifacts: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, str):
                text_parts.append(item)
                continue
            if not isinstance(item, dict):
                artifacts.append({"type": "unknown", "value": item})
                continue
            item_type = str(item.get("type") or "")
            text = item.get("text")
            if item_type in {"text", "output_text"} and isinstance(text, str):
                text_parts.append(text)
            else:
                artifacts.append(dict(item))
        return "\n".join(part for part in text_parts if part), artifacts, value
    if isinstance(value, dict):
        text = value.get("text") or value.get("content") or value.get("output_text")
        artifacts = value.get("artifacts") if isinstance(value.get("artifacts"), list) else []
        return str(text or ""), [dict(item) for item in artifacts if isinstance(item, dict)], value
    return str(value or ""), [], value


def _compact_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value else ""
