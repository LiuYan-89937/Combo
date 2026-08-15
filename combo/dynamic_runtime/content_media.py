from __future__ import annotations

from pathlib import Path
from typing import Final


APPLICATION_OCTET_STREAM: Final[str] = "application/octet-stream"

# Capability resources are imported on different operating systems and inside
# bundled Python runtimes.  Keep the mappings here instead of relying on the
# host MIME database, which commonly has no entry for Markdown and differs
# between macOS, Windows, and Linux.
_MEDIA_TYPES_BY_SUFFIX: Final[dict[str, str]] = {
    # Documentation and data
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".mdown": "text/markdown",
    ".mkdn": "text/markdown",
    ".txt": "text/plain",
    ".text": "text/plain",
    ".log": "text/plain",
    ".rst": "text/plain",
    ".adoc": "text/plain",
    ".asciidoc": "text/plain",
    ".org": "text/plain",
    ".diff": "text/plain",
    ".patch": "text/plain",
    ".list": "text/plain",
    ".lst": "text/plain",
    ".b64": "text/plain",
    ".base64": "text/plain",
    ".pem": "text/plain",
    ".crt": "text/plain",
    ".key": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".jsonl": "application/json",
    ".ndjson": "application/json",
    ".geojson": "application/geo+json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".toml": "application/toml",
    ".ini": "text/plain",
    ".cfg": "text/plain",
    ".conf": "text/plain",
    ".env": "text/plain",
    ".properties": "text/plain",
    # Web and markup
    ".html": "text/html",
    ".htm": "text/html",
    ".xhtml": "application/xhtml+xml",
    ".css": "text/css",
    ".scss": "text/x-scss",
    ".sass": "text/x-sass",
    ".less": "text/x-less",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".cjs": "text/javascript",
    ".jsx": "text/jsx",
    ".ts": "text/typescript",
    ".tsx": "text/tsx",
    ".vue": "text/x-vue",
    ".svelte": "text/x-svelte",
    ".xml": "text/xml",
    ".xsl": "text/xml",
    ".xslt": "text/xml",
    ".svg": "image/svg+xml",
    ".graphql": "text/graphql",
    ".gql": "text/graphql",
    # Source files and shell scripts
    ".py": "text/x-python",
    ".pyw": "text/x-python",
    ".ipynb": "application/json",
    ".sh": "text/x-shellscript",
    ".bash": "text/x-shellscript",
    ".zsh": "text/x-shellscript",
    ".fish": "text/x-shellscript",
    ".ps1": "text/x-powershell",
    ".bat": "text/plain",
    ".cmd": "text/plain",
    ".sql": "text/x-sql",
    ".r": "text/x-r",
    ".rb": "text/x-ruby",
    ".php": "text/x-php",
    ".lua": "text/x-lua",
    ".pl": "text/x-perl",
    ".go": "text/x-go",
    ".rs": "text/x-rust",
    ".java": "text/x-java-source",
    ".kt": "text/x-kotlin",
    ".kts": "text/x-kotlin",
    ".c": "text/x-c",
    ".h": "text/x-c",
    ".cc": "text/x-c++src",
    ".cpp": "text/x-c++src",
    ".cxx": "text/x-c++src",
    ".hpp": "text/x-c++src",
    ".swift": "text/x-swift",
    ".dart": "text/x-dart",
    ".m": "text/x-objective-c",
    ".mm": "text/x-objective-c",
    ".proto": "text/plain",
    ".tex": "text/x-tex",
    # Common binary resources
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".gz": "application/gzip",
    ".tar": "application/x-tar",
    ".7z": "application/x-7z-compressed",
    ".rar": "application/vnd.rar",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".heic": "image/heic",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".wasm": "application/wasm",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_TEXT_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/json",
        "application/geo+json",
        "application/yaml",
        "application/toml",
        "application/xhtml+xml",
        "image/svg+xml",
    }
)


def media_type_for_path(path: str | Path, *, content: bytes | None = None) -> str:
    """Resolve a stable media type without consulting the host MIME database."""
    suffix = Path(path).suffix.casefold()
    known = _MEDIA_TYPES_BY_SUFFIX.get(suffix)
    if known is not None:
        return known
    if content is not None and _looks_like_utf8_text(content):
        return "text/plain"
    return APPLICATION_OCTET_STREAM


def is_text_media_type(media_type: str) -> bool:
    normalized = str(media_type or "").strip().casefold()
    return normalized.startswith("text/") or normalized in _TEXT_MEDIA_TYPES


def _looks_like_utf8_text(content: bytes) -> bool:
    if not content or b"\x00" in content:
        return False
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
