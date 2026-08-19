from __future__ import annotations

import base64
from pathlib import PurePosixPath
import time
from typing import Any, Protocol

import httpx

from combo.models.image_generation.protocol import (
    GeneratedImageSource,
    ImageGenerationRequest,
    ImageGenerationSettings,
    ImageInput,
)


class ImageGenerationAdapter(Protocol):
    def generate(self, request: ImageGenerationRequest) -> list[GeneratedImageSource]:
        ...


class ImageGenerationAdapterError(RuntimeError):
    pass


class OpenAIImageAdapter:
    def __init__(self, settings: ImageGenerationSettings) -> None:
        self.settings = settings

    def generate(self, request: ImageGenerationRequest) -> list[GeneratedImageSource]:
        if request.operation == "text_to_image" or not request.input_images:
            return self._generate(request)
        return self._edit(request)

    def _generate(self, request: ImageGenerationRequest) -> list[GeneratedImageSource]:
        payload = _compact_dict(
            {
                "model": self.settings.model,
                "prompt": request.prompt,
                "n": request.count,
                "size": request.size,
                "response_format": request.response_format,
                **request.provider_options,
            }
        )
        response = _client(self.settings).post(
            _endpoint(self.settings.base_url, "/images/generations"),
            headers=_json_headers(self.settings.api_key),
            json=payload,
        )
        return _parse_openai_image_sources(_raise_json(response))

    def _edit(self, request: ImageGenerationRequest) -> list[GeneratedImageSource]:
        files = []
        for image in request.input_images:
            if image.data is None:
                raise ImageGenerationAdapterError("OpenAI image edits require local image bytes")
            files.append(("image", (image.filename, image.data, image.mime_type)))
        data = _compact_dict(
            {
                "model": self.settings.model,
                "prompt": request.prompt,
                "n": request.count,
                "size": request.size,
                "response_format": request.response_format,
                **request.provider_options,
            }
        )
        response = _client(self.settings).post(
            _endpoint(self.settings.base_url, "/images/edits"),
            headers=_auth_headers(self.settings.api_key),
            data={key: str(value) for key, value in data.items()},
            files=files,
        )
        return _parse_openai_image_sources(_raise_json(response))


class DashScopeWanxImageAdapter:
    def __init__(self, settings: ImageGenerationSettings) -> None:
        self.settings = settings

    def generate(self, request: ImageGenerationRequest) -> list[GeneratedImageSource]:
        content: list[dict[str, Any]] = [{"text": request.prompt}]
        for image in request.input_images:
            content.append({"image": _image_reference(image)})
        payload = {
            "model": self.settings.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": _compact_dict(
                {
                    "n": request.count,
                    "size": request.size,
                    "aspect_ratio": request.aspect_ratio,
                    "seed": request.seed,
                    "negative_prompt": request.negative_prompt,
                    **request.provider_options,
                }
            ),
        }
        response = _client(self.settings).post(
            _endpoint(self.settings.base_url, "/services/aigc/multimodal-generation/generation"),
            headers=_json_headers(self.settings.api_key),
            json=payload,
        )
        body = _raise_json(response)
        task_id = _first_text(body, ("output", "task_id"), ("task_id",))
        if task_id:
            body = self._poll(task_id)
        return _parse_nested_image_sources(body)

    def _poll(self, task_id: str) -> dict[str, Any]:
        poll_path = f"/tasks/{task_id}"
        deadline = time.monotonic() + _timeout(self.settings)
        last_body: dict[str, Any] = {}
        while time.monotonic() < deadline:
            response = _client(self.settings).get(
                _endpoint(self.settings.base_url, poll_path),
                headers=_auth_headers(self.settings.api_key),
            )
            body = _raise_json(response)
            last_body = body
            status = str(_first_text(body, ("output", "task_status"), ("task_status",), ("status",)) or "").upper()
            if status in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
                return body
            if status in {"FAILED", "CANCELED", "CANCELLED"}:
                raise ImageGenerationAdapterError(f"DashScope image generation failed: {body}")
            time.sleep(1.5)
        raise ImageGenerationAdapterError(f"DashScope image generation timed out: {last_body}")


class VolcengineSeedreamImageAdapter:
    def __init__(self, settings: ImageGenerationSettings) -> None:
        self.settings = settings

    def generate(self, request: ImageGenerationRequest) -> list[GeneratedImageSource]:
        if request.operation == "text_to_image" or not request.input_images:
            return self._generate(request)
        return self._edit(request)

    def _generate(self, request: ImageGenerationRequest) -> list[GeneratedImageSource]:
        payload = _compact_dict(
            {
                "model": self.settings.model,
                "prompt": request.prompt,
                "n": request.count,
                "size": request.size,
                "response_format": request.response_format,
                "seed": request.seed,
                **request.provider_options,
            }
        )
        endpoint_path = str(request.provider_options.get("endpoint_path") or "/images/generations")
        payload.pop("endpoint_path", None)
        response = _client(self.settings).post(
            _endpoint(self.settings.base_url, endpoint_path),
            headers=_json_headers(self.settings.api_key),
            json=payload,
        )
        return _parse_openai_image_sources(_raise_json(response))

    def _edit(self, request: ImageGenerationRequest) -> list[GeneratedImageSource]:
        payload = _compact_dict(
            {
                "model": self.settings.model,
                "prompt": request.prompt,
                "n": request.count,
                "size": request.size,
                "seed": request.seed,
                "image": [_image_reference(image) for image in request.input_images],
                **request.provider_options,
            }
        )
        endpoint_path = str(request.provider_options.get("endpoint_path") or "/images/edits")
        payload.pop("endpoint_path", None)
        response = _client(self.settings).post(
            _endpoint(self.settings.base_url, endpoint_path),
            headers=_json_headers(self.settings.api_key),
            json=payload,
        )
        return _parse_nested_image_sources(_raise_json(response))


def adapter_for_image_provider(settings: ImageGenerationSettings) -> ImageGenerationAdapter:
    provider = settings.provider.strip().lower()
    if provider == "openai_chat_completions":
        return OpenAIImageAdapter(settings)
    if provider == "dashscope":
        return DashScopeWanxImageAdapter(settings)
    raise ImageGenerationAdapterError(f"unsupported image generation provider: {settings.provider}")


def _client(settings: ImageGenerationSettings) -> httpx.Client:
    return httpx.Client(timeout=_timeout(settings), follow_redirects=True)


def _timeout(settings: ImageGenerationSettings) -> float:
    return float(settings.timeout_seconds or 120.0)


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _json_headers(api_key: str) -> dict[str, str]:
    return {**_auth_headers(api_key), "Content-Type": "application/json"}


def _endpoint(base_url: str, default_path: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise ImageGenerationAdapterError("image generation base_url is empty")
    path = PurePosixPath(default_path)
    base_path = PurePosixPath("/" + base.split("://", 1)[-1].split("/", 1)[1]) if "/" in base.split("://", 1)[-1] else PurePosixPath("/")
    if str(base_path).rstrip("/").endswith(str(path).rstrip("/")):
        return base
    return base + "/" + str(path).strip("/")


def _raise_json(response: httpx.Response) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ImageGenerationAdapterError(f"image generation request failed: {exc.response.status_code} {exc.response.text[:500]}") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise ImageGenerationAdapterError("image generation response is not valid JSON") from exc
    if not isinstance(body, dict):
        raise ImageGenerationAdapterError("image generation response must be a JSON object")
    return body


def _image_reference(image: ImageInput) -> str:
    if image.url:
        return image.url
    if image.data is None:
        raise ImageGenerationAdapterError("image input has neither url nor bytes")
    return f"data:{image.mime_type};base64,{base64.b64encode(image.data).decode('ascii')}"


def _parse_openai_image_sources(body: dict[str, Any]) -> list[GeneratedImageSource]:
    data = body.get("data")
    if not isinstance(data, list):
        return _parse_nested_image_sources(body)
    sources: list[GeneratedImageSource] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        b64 = item.get("b64_json")
        if isinstance(b64, str) and b64.strip():
            sources.append(
                GeneratedImageSource(
                    data=base64.b64decode(b64),
                    provider_metadata=_provider_metadata(item),
                )
            )
        elif isinstance(url, str) and url.strip():
            sources.append(
                GeneratedImageSource(
                    url=url.strip(),
                    provider_metadata=_provider_metadata(item),
                )
            )
    if not sources:
        raise ImageGenerationAdapterError(f"image generation response contained no images: {body}")
    return sources


def _parse_nested_image_sources(body: dict[str, Any]) -> list[GeneratedImageSource]:
    sources: list[GeneratedImageSource] = []
    for item in _walk_json(body):
        if not isinstance(item, dict):
            continue
        url = _text_value(item, "url") or _text_value(item, "image") or _text_value(item, "image_url")
        b64 = _text_value(item, "b64_json") or _text_value(item, "base64")
        if b64 and _looks_like_base64(b64):
            sources.append(
                GeneratedImageSource(
                    data=base64.b64decode(_strip_data_url(b64)),
                    provider_metadata=_provider_metadata(item),
                )
            )
        elif url and (url.startswith("http://") or url.startswith("https://") or url.startswith("data:image/")):
            if url.startswith("data:image/"):
                mime_type, data = _decode_data_url(url)
                sources.append(
                    GeneratedImageSource(
                        data=data,
                        mime_type=mime_type,
                        provider_metadata=_provider_metadata(item),
                    )
                )
            else:
                sources.append(
                    GeneratedImageSource(
                        url=url,
                        provider_metadata=_provider_metadata(item),
                    )
                )
    if not sources:
        raise ImageGenerationAdapterError(f"image generation response contained no images: {body}")
    return sources


def _walk_json(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _text_value(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    return item.strip() if isinstance(item, str) and item.strip() else None


def _first_text(value: dict[str, Any], *paths: tuple[str, ...]) -> str | None:
    for path in paths:
        current: Any = value
        for part in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if isinstance(current, str) and current.strip():
            return current.strip()
    return None


def _looks_like_base64(value: str) -> bool:
    text = _strip_data_url(value)
    return len(text) > 40 and all(char.isalnum() or char in "+/=\n\r" for char in text[:120])


def _strip_data_url(value: str) -> str:
    return value.split(",", 1)[1] if value.startswith("data:") and "," in value else value


def _decode_data_url(value: str) -> tuple[str, bytes]:
    header, payload = value.split(",", 1)
    mime_type = header.removeprefix("data:").split(";", 1)[0] or "image/png"
    return mime_type, base64.b64decode(payload)


def _compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None and item != ""}


def _provider_metadata(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"b64_json", "base64"}
        and not (isinstance(item, str) and item.startswith("data:image/"))
    }
