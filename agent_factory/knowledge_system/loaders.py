from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import importlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from langchain_core.documents import Document

from agent_factory.knowledge_system.schema import KnowledgeLimits, SourceType


TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".tsv",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".sql",
    ".html",
    ".htm",
}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
IGNORED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
}


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    title: str
    uri: str
    document_type: str
    content: str
    metadata: dict[str, Any]

    @property
    def content_hash(self) -> str:
        return sha256_text(self.content)


@dataclass(frozen=True, slots=True)
class SourceDiscovery:
    documents: list[LoadedDocument]
    file_type_counts: dict[str, int]
    warnings: list[str]


def discover_source(
    *,
    source_type: SourceType,
    uri: str,
    metadata: dict[str, Any] | None = None,
    limits: KnowledgeLimits,
) -> SourceDiscovery:
    metadata = dict(metadata or {})
    if source_type in {"filesystem", "codebase", "skill", "artifact_report"}:
        return discover_filesystem(uri=uri, source_type=source_type, metadata=metadata, limits=limits)
    if source_type == "web_snapshot":
        return discover_web_snapshot(uri=uri, metadata=metadata, limits=limits)
    if source_type == "manual_note":
        return discover_manual_note(uri=uri, metadata=metadata)
    if source_type in {"database", "mcp"}:
        return discover_managed_source(uri=uri, source_type=source_type, metadata=metadata)
    return SourceDiscovery(documents=[], file_type_counts={}, warnings=[f"unsupported source type: {source_type}"])


def discover_filesystem(
    *,
    uri: str,
    source_type: SourceType,
    metadata: dict[str, Any],
    limits: KnowledgeLimits,
) -> SourceDiscovery:
    root = Path(uri).expanduser()
    warnings: list[str] = []
    loader_warnings: set[str] = set()
    documents: list[LoadedDocument] = []
    file_type_counts: dict[str, int] = {}
    if not root.exists():
        return SourceDiscovery(
            documents=[],
            file_type_counts={},
            warnings=[f"source path is not accessible from this runtime: {uri}"],
        )
    paths = [root] if root.is_file() else _iter_source_files(root)
    for path in paths:
        if len(documents) >= limits.max_preview_files:
            warnings.append(f"preview limited to {limits.max_preview_files} files")
            break
        suffix = path.suffix.lower()
        file_type_counts[suffix or "no_extension"] = file_type_counts.get(suffix or "no_extension", 0) + 1
        loaded = load_file(path, root=root if root.is_dir() else path.parent, source_type=source_type, limits=limits)
        if loaded is None:
            if suffix in PDF_EXTENSIONS | DOCX_EXTENSIONS:
                loader_warnings.add(f"{suffix.removeprefix('.')} files require LangChain document loader dependencies")
            continue
        documents.append(loaded)
    return SourceDiscovery(documents=documents, file_type_counts=file_type_counts, warnings=[*warnings, *sorted(loader_warnings)])


def discover_web_snapshot(
    *,
    uri: str,
    metadata: dict[str, Any],
    limits: KnowledgeLimits,
) -> SourceDiscovery:
    parsed = urlparse(uri)
    if parsed.scheme not in {"http", "https"}:
        return SourceDiscovery(documents=[], file_type_counts={}, warnings=["web_snapshot requires http or https URL"])
    try:
        httpx = importlib.import_module("httpx")
        response = httpx.get(uri, timeout=20.0, follow_redirects=True)
        response.raise_for_status()
    except Exception as exc:
        return SourceDiscovery(documents=[], file_type_counts={}, warnings=[f"web fetch failed: {type(exc).__name__}: {exc}"])
    text = _html_to_text(response.text)
    if len(text) > limits.max_file_bytes:
        text = text[: limits.max_file_bytes]
    title = parsed.netloc + parsed.path
    document = LoadedDocument(
        title=metadata.get("title") or title or uri,
        uri=uri,
        document_type="web_snapshot",
        content=text,
        metadata={
            "url": uri,
            "content_hash": sha256_text(response.text),
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "snapshot_policy": "url_and_hash",
        },
    )
    return SourceDiscovery(documents=[document], file_type_counts={"web": 1}, warnings=[])


def discover_manual_note(*, uri: str, metadata: dict[str, Any]) -> SourceDiscovery:
    content = str(metadata.get("content") or uri).strip()
    if not content:
        return SourceDiscovery(documents=[], file_type_counts={}, warnings=["manual_note requires content"])
    title = str(metadata.get("title") or "Manual note").strip()
    return SourceDiscovery(
        documents=[
            LoadedDocument(
                title=title,
                uri=f"manual_note:{sha256_text(content)[:12]}",
                document_type="manual_note",
                content=content,
                metadata={key: value for key, value in metadata.items() if key != "content"},
            )
        ],
        file_type_counts={"manual_note": 1},
        warnings=[],
    )


def discover_managed_source(*, uri: str, source_type: SourceType, metadata: dict[str, Any]) -> SourceDiscovery:
    description = str(metadata.get("description") or metadata.get("schema_summary") or uri).strip()
    if not description:
        description = f"{source_type} managed source"
    title = str(metadata.get("title") or metadata.get("display_name") or f"{source_type} source").strip()
    return SourceDiscovery(
        documents=[
            LoadedDocument(
                title=title,
                uri=uri,
                document_type=source_type,
                content=description,
                metadata={"managed_source": True, **metadata},
            )
        ],
        file_type_counts={source_type: 1},
        warnings=[],
    )


def load_file(path: Path, *, root: Path, source_type: SourceType, limits: KnowledgeLimits) -> LoadedDocument | None:
    try:
        if path.stat().st_size > limits.max_file_bytes:
            return None
    except OSError:
        return None
    suffix = path.suffix.lower()
    document_type = suffix.removeprefix(".") or "file"
    if not _supported_suffix(suffix):
        return None
    documents = _load_file_documents(path=path, suffix=suffix)
    content = "\n\n".join(document.page_content for document in documents).strip()
    content = content.strip()
    if not content:
        return None
    try:
        relative = str(path.relative_to(root))
    except ValueError:
        relative = path.name
    return LoadedDocument(
        title=relative,
        uri=str(path),
        document_type=document_type,
        content=content,
        metadata={
            "file_name": path.name,
            "relative_path": relative,
            "file_type": suffix.removeprefix(".") or "file",
            "source_type": source_type,
            "loader": _loader_name(documents),
        },
    )


def _supported_suffix(suffix: str) -> bool:
    return suffix in TEXT_EXTENSIONS or suffix in PDF_EXTENSIONS or suffix in DOCX_EXTENSIONS


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def _iter_source_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in IGNORED_DIRS for part in path.parts)
    )


def _load_file_documents(*, path: Path, suffix: str) -> list[Document]:
    loader = _build_langchain_loader(path=path, suffix=suffix)
    if loader is not None:
        try:
            return loader.load()
        except (ImportError, ModuleNotFoundError):
            return _fallback_file_documents(path=path, suffix=suffix)
    return _fallback_file_documents(path=path, suffix=suffix)


def _build_langchain_loader(*, path: Path, suffix: str):
    try:
        document_loaders = importlib.import_module("langchain_community.document_loaders")
    except ModuleNotFoundError:
        return None
    if suffix in PDF_EXTENSIONS:
        return document_loaders.PyPDFLoader(str(path))
    if suffix in DOCX_EXTENSIONS:
        return document_loaders.Docx2txtLoader(str(path))
    if suffix in {".html", ".htm"}:
        return document_loaders.BSHTMLLoader(str(path), open_encoding="utf-8")
    if suffix in TEXT_EXTENSIONS:
        return document_loaders.TextLoader(str(path), encoding="utf-8", autodetect_encoding=True)
    return None


def _fallback_file_documents(*, path: Path, suffix: str) -> list[Document]:
    if suffix in TEXT_EXTENSIONS:
        content = _read_text(path)
        if suffix in {".html", ".htm"}:
            content = _html_to_text(content)
        return [Document(page_content=content, metadata={"loader": "internal_text_fallback"})]
    return []


def _loader_name(documents: list[Document]) -> str:
    if not documents:
        return "none"
    loaders = [str(document.metadata.get("loader") or "").strip() for document in documents if document.metadata]
    if loaders and loaders[0]:
        return loaders[0]
    return "langchain_document_loader"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _html_to_text(value: str) -> str:
    BeautifulSoup = importlib.import_module("bs4").BeautifulSoup
    soup = BeautifulSoup(value, "html.parser")
    for item in soup(["script", "style", "noscript"]):
        item.decompose()
    text = soup.get_text("\n")
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.strip() for line in text.splitlines())).strip()


def json_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
