from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import mimetypes
from pathlib import Path
from typing import Any

from combo.artifact_system import ArtifactStore

from combo.dynamic_runtime.mcp_runtime import MCPRuntimePool


class MCPContentRuntime:
    """Stable model-facing directory for MCP Resources and Prompts."""

    def __init__(self, runtime: MCPRuntimePool, *, workspace_root: Path | None = None) -> None:
        self._runtime = runtime
        self._workspace_root = workspace_root.expanduser().resolve() if workspace_root is not None else None

    def for_workspace(self, workspace_root: Path) -> "MCPContentRuntime":
        return MCPContentRuntime(self._runtime, workspace_root=workspace_root)

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        needle = " ".join(str(query or "").casefold().split())
        if not needle:
            raise ValueError("MCP content search query must not be empty")
        if limit < 1 or limit > 100:
            raise ValueError("MCP content search limit must be between 1 and 100")
        matches = [item for item in self.list() if needle in _searchable(item)]
        return matches[:limit]

    def list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for server_id, catalog in sorted(self._runtime.catalogs().items()):
            items.extend(_resource_summary(server_id, item) for item in catalog.resources)
            items.extend(_template_summary(server_id, item) for item in catalog.resource_templates)
            items.extend(_prompt_summary(server_id, item) for item in catalog.prompts)
        return items

    def read_resource(self, server_id: str, uri: str) -> dict[str, Any]:
        digest = self._runtime.server_digest(server_id)
        result = self._runtime.read_resource(digest, uri)
        response: dict[str, Any] = {
            "server_id": server_id,
            "uri": uri,
            "result": result,
        }
        materialized = MCPBinaryContentMaterializer(self._workspace_root).materialize_resource_result(
            server_id=server_id,
            uri=uri,
            result=result,
        )
        response["result"] = materialized.result
        assets = materialized.assets
        if assets:
            response["assets"] = assets
            image = next((item for item in assets if str(item.get("mime_type") or "").startswith("image/")), None)
            if image is not None:
                response["model_image"] = {"path": image["path"], "mime_type": image["mime_type"]}
        return response

    def get_prompt(
        self,
        server_id: str,
        name: str,
        arguments: dict[str, str],
    ) -> dict[str, Any]:
        digest = self._runtime.server_digest(server_id)
        return {
            "server_id": server_id,
            "name": name,
            "result": self._runtime.get_prompt(digest, name, arguments),
        }


@dataclass(frozen=True, slots=True)
class MaterializedMCPContent:
    result: dict[str, Any]
    assets: list[dict[str, Any]]


class MCPBinaryContentMaterializer:
    """Convert binary MCP Resource and Tool content into workspace artifacts."""

    def __init__(self, workspace_root: Path | None) -> None:
        self._workspace_root = workspace_root.expanduser().resolve() if workspace_root is not None else None

    def materialize_resource_result(
        self,
        *,
        server_id: str,
        uri: str,
        result: dict[str, Any],
    ) -> MaterializedMCPContent:
        normalized = deepcopy(result)
        contents = normalized.get("contents")
        assets = self._materialize_content_list(
            contents,
            source_kind="mcp_resource",
            source_identity=f"{server_id}\0{uri}",
            metadata={"server_id": server_id, "uri": uri},
        )
        return MaterializedMCPContent(result=normalized, assets=assets)

    def materialize_tool_result(
        self,
        *,
        server_id: str,
        tool_name: str,
        result: dict[str, Any],
    ) -> MaterializedMCPContent:
        normalized = deepcopy(result)
        contents = normalized.get("content")
        assets = self._materialize_content_list(
            contents,
            source_kind="mcp_tool_result",
            source_identity=f"{server_id}\0{tool_name}",
            metadata={"server_id": server_id, "tool_name": tool_name},
        )
        return MaterializedMCPContent(result=normalized, assets=assets)

    def _materialize_content_list(
        self,
        contents: Any,
        *,
        source_kind: str,
        source_identity: str,
        metadata: dict[str, str],
    ) -> list[dict[str, Any]]:
        if self._workspace_root is None or not isinstance(contents, list):
            return []
        store = ArtifactStore(root=self._workspace_root, allowed_kinds=("artifact",))
        assets: list[dict[str, Any]] = []
        for index, content in enumerate(contents, start=1):
            if not isinstance(content, dict):
                continue
            binary = _binary_content(content)
            if binary is None:
                continue
            encoded, mime_type = binary
            data = base64.b64decode(encoded, validate=True)
            suffix = mimetypes.guess_extension(mime_type) or ".bin"
            digest = sha256(
                source_identity.encode("utf-8") + b"\0" + str(index).encode("ascii") + b"\0" + data
            ).hexdigest()[:20]
            record = store.write_bytes(
                kind="artifact",
                relative_path=f"mcp-content/{digest}{suffix}",
                content=data,
                metadata={"artifact_type": source_kind, "mime_type": mime_type, **metadata},
            )
            relative_path = str(record["relative_path"])
            asset = {
                "asset_id": record["artifact_id"],
                "name": Path(relative_path).name,
                "path": relative_path,
                "relative_path": relative_path,
                "mime_type": mime_type,
                "size_bytes": len(data),
            }
            assets.append(asset)
            content.clear()
            content.update({"type": "artifact", **asset})
        return assets


def _binary_content(content: dict[str, Any]) -> tuple[str, str] | None:
    if content.get("type") == "image" and isinstance(content.get("data"), str):
        return content["data"], str(content.get("mime_type") or "image/png")
    if isinstance(content.get("blob"), str):
        return content["blob"], str(content.get("mime_type") or "application/octet-stream")
    resource = content.get("resource")
    if content.get("type") == "resource" and isinstance(resource, dict) and isinstance(resource.get("blob"), str):
        return resource["blob"], str(resource.get("mime_type") or "application/octet-stream")
    return None


def _resource_summary(server_id: str, item: Any) -> dict[str, Any]:
    return {
        "kind": "resource",
        "server_id": server_id,
        "name": str(getattr(item, "name", "")),
        "title": getattr(item, "title", None),
        "description": str(getattr(item, "description", "") or ""),
        "uri": str(getattr(item, "uri", "")),
        "mime_type": str(getattr(item, "mime_type", "") or ""),
        "size": getattr(item, "size", None),
        "icons": [icon.model_dump(mode="json", exclude_none=True) for icon in (item.icons or ())],
        "annotations": item.annotations.model_dump(mode="json", exclude_none=True) if item.annotations else None,
    }


def _template_summary(server_id: str, item: Any) -> dict[str, Any]:
    return {
        "kind": "resource_template",
        "server_id": server_id,
        "name": str(getattr(item, "name", "")),
        "title": getattr(item, "title", None),
        "description": str(getattr(item, "description", "") or ""),
        "uri_template": str(getattr(item, "uri_template", "")),
        "mime_type": str(getattr(item, "mime_type", "") or ""),
        "icons": [icon.model_dump(mode="json", exclude_none=True) for icon in (item.icons or ())],
        "annotations": item.annotations.model_dump(mode="json", exclude_none=True) if item.annotations else None,
    }


def _prompt_summary(server_id: str, item: Any) -> dict[str, Any]:
    arguments = getattr(item, "arguments", ()) or ()
    return {
        "kind": "prompt",
        "server_id": server_id,
        "name": str(getattr(item, "name", "")),
        "title": getattr(item, "title", None),
        "description": str(getattr(item, "description", "") or ""),
        "arguments": [
            {
                "name": str(getattr(argument, "name", "")),
                "description": str(getattr(argument, "description", "") or ""),
                "required": bool(getattr(argument, "required", False)),
            }
            for argument in arguments
        ],
        "icons": [icon.model_dump(mode="json", exclude_none=True) for icon in (item.icons or ())],
    }


def _searchable(item: dict[str, Any]) -> str:
    return " ".join(str(value) for value in item.values()).casefold()
